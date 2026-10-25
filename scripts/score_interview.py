"""Turn an extracted interview into a credit risk assessment.

Reads the English translations, asks the extraction model for a typed feature
object (each answer sent with its question and the fields that question
targets), builds the feature vector in the order the classifier expects, and
produces a risk class with its SHAP attribution. The applicant form, where an
interview has one, fills age, sex, education and marital status directly;
those are then left out of the prompt.

    python scripts/score_interview.py
    python scripts/score_interview.py --input data/translation_output.csv

Importable: extract_features() -> build_vector() -> assess(). score() is
assess() plus the exact vector the classifier saw and the model's hash, for
callers that must store the record rather than re-derive it.
"""
from __future__ import annotations

import argparse, csv, hashlib, io, json, math, os, re, sys, time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "models" / "classifier.joblib"
META = ROOT / "models" / "classifier_meta.json"
QUESTIONS = ROOT / "src" / "chamapro" / "questions.json"
DEFAULT_GEM = "gemini-3.6-flash"

# Extraction schema, one entry per top-level field, in the order asked for.
FIELDS = {
    "age": '"age": int or null',
    "household_size": '"household_size": int or null',
    "children": '"children": int or null',
    "children_under5": '"children_under5": int or null',
    "children_in_school": '"children_in_school": int or null',
    "monthly_income_kes": '"monthly_income_kes": number or null',
    "agri_income_kes": '"agri_income_kes": number or null',
    "income_sources": """"income_sources": {
    "farming": 0/1, "employed": 0/1, "casual_worker": 0/1,
    "own_business": 0/1, "social_transfer": 0/1, "renting_out": 0/1,
    "investments": 0/1, "pension": 0/1, "remittances": 0/1,
    "other": 0/1, "none": 0/1
  }""",
    "non_monetary_savings": """"non_monetary_savings": {
    "land_or_buildings": 0/1, "livestock": 0/1, "jewellery": 0/1,
    "digital_assets": 0/1, "agroforestry": 0/1
  }""",
    "education_level": '"education_level": 0-8 or null',
    "sacco_loan_use": '"sacco_loan_use": 0/1/2 or null',
    "chama_loan_use": '"chama_loan_use": 0/1/2 or null',
    "is_female": '"is_female": 0/1 or null',
    "marital_status": '"marital_status": "married"|"single"|"widowed"|"divorced"|null',
    "purchases_last_12m": """"purchases_last_12m": {
    "land_or_plot": 0/1, "new_house": 0/1, "house_materials": 0/1,
    "business_equipment": 0/1, "farm_equipment": 0/1, "livestock": 0/1
  }""",
    "lost_as_guarantor": '"lost_as_guarantor": { "sacco": 0/1, "chama": 0/1 }',
}

# Sub-keys of the flag groups, in classifier order: B3A__1.., F1__1.., B1L__1..
INCOME_SOURCES = ["farming", "employed", "casual_worker", "own_business",
                  "social_transfer", "renting_out", "investments",
                  "pension", "remittances", "other", "none"]
SAVINGS = ["land_or_buildings", "livestock", "jewellery", "digital_assets", "agroforestry"]
PURCHASES = ["land_or_plot", "new_house", "house_materials",
             "business_equipment", "farm_equipment", "livestock"]

# Classifier feature -> the extraction field it is built from.
FEATURE_FIELD = {
    "age": "age", "household_size": "household_size", "children": "children",
    "children_under5": "children_under5", "children_in_school": "children_in_school",
    "log_monthly_income": "monthly_income_kes", "income_missing": "monthly_income_kes",
    "log_agri_income": "agri_income_kes", "education": "education_level",
    "sacco_loan_use": "sacco_loan_use", "chama_loan_use": "chama_loan_use",
    "is_female": "is_female", "E3B__3": "lost_as_guarantor", "E3B__7": "lost_as_guarantor",
    **{f"marital_{m}": "marital_status" for m in ("married", "single", "widowed", "divorced")},
    **{f"B3A__{i}": "income_sources" for i in range(1, len(INCOME_SOURCES) + 1)},
    **{f"F1__{i}": "non_monetary_savings" for i in range(1, len(SAVINGS) + 1)},
    **{f"B1L__{i}": "purchases_last_12m" for i in range(1, len(PURCHASES) + 1)},
}

# The applicant form (entered by the officer) fills these; with a form they
# are left out of the extraction prompt. EDU_LADDER is the encoding the
# classifier was trained on (experiments/03_classifier/model.py), FinAccess
# A20 categories in order.
FORM_FIELDS = ("age", "is_female", "education_level", "marital_status")
EDU_LADDER = {
    "None": 0,
    "Some primary": 1,
    "Primary completed": 2,
    "Some secondary": 3,
    "Secondary completed": 4,
    "Some technical training after secondary school": 5,
    "Completed technical training after secondary school": 6,
    "Some university": 7,
    "University completed": 8,
}
MARITAL_STATUSES = ("married", "single", "widowed", "divorced")


def form_values(age, sex, education, marital_status):
    """The applicant form as extraction fields, ready to merge over them."""
    return {"age": age,
            "is_female": None if sex is None else int(sex == "female"),
            "education_level": education,
            "marital_status": marital_status}


def schema(known=()):
    return "{\n" + ",\n".join(f"  {v}" for k, v in FIELDS.items() if k not in known) + "\n}"


SCHEMA = schema()

PROMPT = """Below is a loan applicant interview, translated to English.
Extract ONLY facts the applicant actually stated. Where a fact was not stated,
return null for that field and 0 for the binary flags. Never infer, estimate or
guess. An incomplete answer is correct; an invented one is not.
{layout}
Field rules:
{rules}

Scales:
{scales}

Return ONLY this JSON object, no prose, no code fences:
{schema}

Interview:
{body}"""

LAYOUT = """
Each answer is shown under the question it answers and the fields that
question asks about. Take facts only from what the applicant said, never from
the wording of a question. A fact stated in answer to a different question
still counts. Record each fact once.
"""

# (field the rule is about, rule text)
RULES = [
    ("monthly_income_kes", """  monthly_income_kes is TOTAL monthly income. If the applicant states only one
    income figure, it belongs here, not in agri_income_kes."""),
    ("agri_income_kes", """  agri_income_kes only when a figure is explicitly identified as farm, crop or
    livestock income, separately from total income. Never duplicate one figure
    into both fields."""),
    ("is_female", "  is_female only if the applicant states their sex. Never infer it from a name."),
]
QUESTION_RULES = [
    ("income_sources", """  income_sources: set the flag for every way of earning money the applicant
    names, including the main one given with their monthly income."""),
]
SCALES = [
    ("education_level", """  education_level: 0 none, 1 some primary, 2 primary complete, 3 some secondary,
    4 secondary complete, 5 some technical, 6 technical complete, 7 some
    university, 8 university complete"""),
    ("sacco_loan_use", "  sacco_loan_use / chama_loan_use: 0 never used, 1 used to use, 2 currently use"),
]


@dataclass(frozen=True)
class Answer:
    """One response for extraction: the English text, and where known the
    question it answers and the classifier features that question targets."""
    n: object
    text: str
    question: str = ""
    features: tuple = ()


def fields_for(features):
    """Extraction fields that build the given classifier features, in order."""
    return list(dict.fromkeys(FEATURE_FIELD[f] for f in features if f in FEATURE_FIELD))


def render_body(answers, known=()):
    if not any(a.question for a in answers):
        return "\n".join(f"{a.n}. {a.text.strip()}" for a in answers)
    parts = []
    for a in answers:
        fields = [f for f in fields_for(a.features) if f not in known]
        head = f"Q{a.n}" + (f" (fields: {', '.join(fields)})" if fields else "")
        parts.append(f"{head}\nQuestion: {a.question.strip()}\nAnswer: {a.text.strip()}")
    return "\n\n".join(parts)


def build_prompt(answers, known=()):
    """The extraction prompt. known: fields the applicant form already fills,
    left out of the schema and its rules."""
    layout = LAYOUT if any(a.question for a in answers) else ""
    rules = RULES + (QUESTION_RULES if layout else [])
    return PROMPT.format(
        layout=layout,
        rules="\n".join(t for f, t in rules if f not in known),
        scales="\n".join(t for f, t in SCALES if f not in known),
        schema=schema(known), body=render_body(answers, known))


class FeatureParseError(ValueError):
    """The extraction model's reply was not valid JSON; .raw holds the reply."""
    def __init__(self, raw):
        super().__init__("could not parse feature JSON")
        self.raw = raw


def resolve(key=None, model=None):
    """Explicit arguments win; otherwise fall back to the environment."""
    key = key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not key: raise RuntimeError("no GEMINI_API_KEY in .env")
    return key, model or os.getenv("GEMINI_MODEL", DEFAULT_GEM)


def call(prompt, key, model, tries=5, timeout=300, log=print):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    for i in range(1, tries + 1):
        try:
            r = requests.post(url, headers={"x-goog-api-key": key,
                              "Content-Type": "application/json"},
                              json={"contents": [{"parts": [{"text": prompt}]}],
                                    "generationConfig": {"temperature": 0}},
                              timeout=timeout)
        except requests.exceptions.RequestException as e:
            if i == tries: raise
            log(f"  network {type(e).__name__}, retry in {2**i}s"); time.sleep(2**i); continue
        if r.status_code == 200:
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        if r.status_code in (429, 500, 502, 503) and i < tries:
            log(f"  {r.status_code}, retry in {2**i}s"); time.sleep(2**i); continue
        raise RuntimeError(f"{r.status_code}: {r.text[:300]}")


def extract_features(english_responses, *, known=(), key=None, model=None, log=print):
    """Ask the extraction model for the typed feature object.

    english_responses is Answer objects, or (n, english) pairs; blank answers
    are skipped. known names fields the applicant form fills (FORM_FIELDS),
    which are not asked for. Raises ValueError if no answer remains,
    FeatureParseError on a non-JSON reply.
    """
    answers = [a if isinstance(a, Answer) else Answer(*a) for a in english_responses]
    answers = [a for a in answers if a.text.strip()]
    if not answers: raise ValueError("no translated responses in input")
    key, model = resolve(key, model)
    raw = call(build_prompt(answers, known), key, model, log=log)
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise FeatureParseError(raw) from None


def logp(v):
    return float(np.log1p(v)) if v is not None else np.nan


def build_vector(features, feature_order, form=None):
    """Map the typed object onto the classifier's feature contract. form
    (form_values()) is merged over the extracted fields and wins."""
    f, order = {**features, **(form or {})}, feature_order
    src = f.get("income_sources") or {}
    sav = f.get("non_monetary_savings") or {}
    mar = (f.get("marital_status") or "").lower()
    inc = f.get("monthly_income_kes")

    v = {
        "age": f.get("age"),
        "household_size": f.get("household_size"),
        "children": f.get("children"),
        "children_under5": f.get("children_under5"),
        "children_in_school": f.get("children_in_school"),
        "log_monthly_income": logp(inc),
        "income_missing": 1 if inc is None else 0,
        "log_agri_income": logp(f.get("agri_income_kes")),
        "education": f.get("education_level"),
        "sacco_loan_use": f.get("sacco_loan_use"),
        "chama_loan_use": f.get("chama_loan_use"),
        "is_female": f.get("is_female"),
        "marital_married": 1 if mar == "married" else 0,
        "marital_single": 1 if mar == "single" else 0,
        "marital_widowed": 1 if mar == "widowed" else 0,
        "marital_divorced": 1 if mar == "divorced" else 0,
    }
    for i, k in enumerate(INCOME_SOURCES, 1):
        v[f"B3A__{i}"] = int(src.get(k, 0) or 0)
    for i, k in enumerate(SAVINGS, 1):
        v[f"F1__{i}"] = int(sav.get(k, 0) or 0)
    buy = f.get("purchases_last_12m") or {}
    for i, k in enumerate(PURCHASES, 1):
        v[f"B1L__{i}"] = int(buy.get(k, 0) or 0)
    lost = f.get("lost_as_guarantor") or {}
    v["E3B__3"] = int(lost.get("sacco", 0) or 0)
    v["E3B__7"] = int(lost.get("chama", 0) or 0)

    row = {c: v.get(c, np.nan) for c in order}
    row = {c: (np.nan if x is None else x) for c, x in row.items()}
    unmapped = [c for c in order if c not in v]
    return pd.DataFrame([row], columns=order), unmapped


@dataclass(frozen=True)
class Scored:
    assessment: dict        # the assessment.json shape, as assess() returns
    vector: pd.DataFrame    # the exact single-row input the classifier saw
    model_file: str
    model_sha256: str


@lru_cache(maxsize=2)
def _load(model_path, meta_path, stamp):
    data = Path(model_path).read_bytes()
    meta = json.loads(Path(meta_path).read_text(encoding="utf-8"))
    return joblib.load(io.BytesIO(data)), meta, hashlib.sha256(data).hexdigest()


def load_classifier(model_path=MODEL, meta_path=META):
    """(classifier, meta, sha256), cached until either file changes on disk."""
    m, t = Path(model_path), Path(meta_path)
    return _load(str(m), str(t), (m.stat().st_mtime_ns, t.stat().st_mtime_ns))


def score(features, model_path=MODEL, meta_path=META, form=None):
    """features: what the extraction model returned; form: form_values() of
    the applicant form, or None for an interview without one (v1)."""
    clf, meta, sha = load_classifier(model_path, meta_path)
    order, classes = meta["feature_order"], meta["classes"]

    X, unmapped = build_vector(features, order, form)
    present = int(X.notna().sum(axis=1).iloc[0])
    completeness = round(present / len(order), 3)

    pred = int(clf.predict(X)[0])
    proba = clf.predict_proba(X)[0]
    label = classes[str(pred)]

    contrib = []
    try:
        import shap
        sv = np.array(shap.TreeExplainer(clf).shap_values(X))
        arr = sv[pred] if sv.ndim == 3 and sv.shape[0] == len(proba) else (
              sv[..., pred] if sv.ndim == 3 else sv)
        arr = np.asarray(arr).reshape(-1)
        for i in np.argsort(np.abs(arr))[::-1][:8]:
            contrib.append({"feature": order[i],
                            "value": None if pd.isna(X.iloc[0, i]) else float(X.iloc[0, i]),
                            "shap": round(float(arr[i]), 4)})
    except Exception as e:
        contrib = f"unavailable: {type(e).__name__}: {e}"

    out = {
        "risk_class": label,
        "probabilities": {classes[str(i)]: round(float(p), 4) for i, p in enumerate(proba)},
        "extraction_completeness": completeness,
        "features_populated": present,
        "features_total": len(order),
        "features_not_extractable_from_interview": unmapped,
        "extracted": features,
        "applicant_form": form,
        "top_contributions": contrib,
    }
    return Scored(out, X, Path(model_path).name, sha)


def assess(features, model_path=MODEL, meta_path=META, form=None):
    """Typed feature object -> dict in the assessment.json shape."""
    return score(features, model_path, meta_path, form).assessment


def main():
    load_dotenv(override=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="data/translation_output.csv")
    ap.add_argument("--out", default="data/assessment.json")
    a = ap.parse_args()

    try:
        key, gem = resolve()
    except RuntimeError as e:
        sys.exit(str(e))
    if not MODEL.exists(): sys.exit("no model; run scripts/train_and_save.py first")

    rows = list(csv.DictReader(Path(a.input).open(encoding="utf-8")))
    # The recorded corpus answers question set v1, sentence by sentence.
    qs = {q["order"]: q for q in json.loads(QUESTIONS.read_text(encoding="utf-8"))
          if q["version"] == "v1"}
    responses = [Answer(r["sentence_no"], r["english_out"],
                        qs.get(int(r["sentence_no"]), {}).get("text_en", ""),
                        tuple(qs.get(int(r["sentence_no"]), {}).get("features", [])))
                 for r in rows if r["english_out"].strip()]
    if not responses: sys.exit("no translated responses in input")
    print(f"extracting features from {len(responses)} responses")

    try:
        feats = extract_features(responses, key=key, model=gem)
    except FeatureParseError as e:
        Path("data/features_raw.txt").write_text(e.raw, encoding="utf-8")
        sys.exit("could not parse feature JSON; raw saved to data/features_raw.txt")

    out = assess(feats)
    Path(a.out).write_text(json.dumps(out, indent=2), encoding="utf-8")

    present, total = out["features_populated"], out["features_total"]
    contrib = out["top_contributions"]
    print(f"\nRISK: {out['risk_class']}")
    for k, p in out["probabilities"].items(): print(f"  {k:<8} {p:.1%}")
    print(f"\nevidence: {present}/{total} features ({out['extraction_completeness']:.0%})")
    if isinstance(contrib, list):
        print("\ntop contributions:")
        for c in contrib: print(f"  {c['feature']:<22} value={c['value']}  shap={c['shap']:+.3f}")
    print(f"\nwrote {a.out}")


if __name__ == "__main__":
    main()
