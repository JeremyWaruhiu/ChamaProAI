"""Turn an extracted interview into a credit risk assessment.

Reads the English translations, asks the extraction model for a typed feature
object, builds the feature vector in the order the classifier expects, and
produces a risk class with its SHAP attribution.

    python scripts/score_interview.py
    python scripts/score_interview.py --input data/translation_output.csv
"""
from __future__ import annotations

import argparse, csv, json, math, os, re, sys, time
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import requests
from dotenv import load_dotenv

load_dotenv(override=True)

ROOT = Path(__file__).resolve().parents[1]
MODEL = ROOT / "models" / "classifier.joblib"
META = ROOT / "models" / "classifier_meta.json"
KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
GEM = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEM}:generateContent"

SCHEMA = """{
  "age": int or null,
  "household_size": int or null,
  "children": int or null,
  "children_under5": int or null,
  "children_in_school": int or null,
  "monthly_income_kes": number or null,
  "agri_income_kes": number or null,
  "income_sources": {
    "farming": 0/1, "employed": 0/1, "casual_worker": 0/1,
    "own_business": 0/1, "social_transfer": 0/1, "renting_out": 0/1,
    "investments": 0/1, "pension": 0/1, "remittances": 0/1,
    "other": 0/1, "none": 0/1
  },
  "non_monetary_savings": {
    "land_or_buildings": 0/1, "livestock": 0/1, "jewellery": 0/1,
    "digital_assets": 0/1, "agroforestry": 0/1
  },
  "education_level": 0-8 or null,
  "sacco_loan_use": 0/1/2 or null,
  "chama_loan_use": 0/1/2 or null,
  "is_female": 0/1 or null,
  "marital_status": "married"|"single"|"widowed"|"divorced"|null
}"""

PROMPT = """Below is a loan applicant interview, translated to English.
Extract ONLY facts the applicant actually stated. Where a fact was not stated,
return null for that field and 0 for the binary flags. Never infer, estimate or
guess. An incomplete answer is correct; an invented one is not.

Scales:
  education_level: 0 none, 1 some primary, 2 primary complete, 3 some secondary,
    4 secondary complete, 5 some technical, 6 technical complete, 7 some
    university, 8 university complete
  sacco_loan_use / chama_loan_use: 0 never used, 1 used to use, 2 currently use

Return ONLY this JSON object, no prose, no code fences:
{schema}

Interview:
{body}"""


def call(prompt, tries=5, timeout=300):
    for i in range(1, tries + 1):
        try:
            r = requests.post(URL, headers={"x-goog-api-key": KEY,
                              "Content-Type": "application/json"},
                              json={"contents": [{"parts": [{"text": prompt}]}]},
                              timeout=timeout)
        except requests.exceptions.RequestException as e:
            if i == tries: raise
            print(f"  network {type(e).__name__}, retry in {2**i}s"); time.sleep(2**i); continue
        if r.status_code == 200:
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        if r.status_code in (429, 500, 502, 503) and i < tries:
            print(f"  {r.status_code}, retry in {2**i}s"); time.sleep(2**i); continue
        raise RuntimeError(f"{r.status_code}: {r.text[:300]}")


def logp(v):
    return float(np.log1p(v)) if v is not None else np.nan


def build_vector(f, order):
    """Map the typed object onto the classifier's feature contract."""
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
    for i, k in enumerate(["farming", "employed", "casual_worker", "own_business",
                           "social_transfer", "renting_out", "investments",
                           "pension", "remittances", "other", "none"], 1):
        v[f"B3A__{i}"] = int(src.get(k, 0) or 0)
    for i, k in enumerate(["land_or_buildings", "livestock", "jewellery",
                           "digital_assets", "agroforestry"], 1):
        v[f"F1__{i}"] = int(sav.get(k, 0) or 0)

    row = {c: v.get(c, np.nan) for c in order}
    row = {c: (np.nan if x is None else x) for c, x in row.items()}
    unmapped = [c for c in order if c not in v]
    return pd.DataFrame([row], columns=order), unmapped


ap = argparse.ArgumentParser()
ap.add_argument("--input", default="data/translation_output.csv")
ap.add_argument("--out", default="data/assessment.json")
a = ap.parse_args()

if not KEY: sys.exit("no GEMINI_API_KEY in .env")
if not MODEL.exists(): sys.exit("no model; run scripts/train_and_save.py first")

meta = json.loads(META.read_text(encoding="utf-8"))
order, classes = meta["feature_order"], meta["classes"]

rows = list(csv.DictReader(Path(a.input).open(encoding="utf-8")))
body = "\n".join(f"{r['sentence_no']}. {r['english_out'].strip()}"
                 for r in rows if r["english_out"].strip())
if not body: sys.exit("no translated responses in input")
print(f"extracting features from {body.count(chr(10))+1} responses")

raw = call(PROMPT.format(schema=SCHEMA, body=body))
raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
try:
    feats = json.loads(raw)
except json.JSONDecodeError:
    Path("data/features_raw.txt").write_text(raw, encoding="utf-8")
    sys.exit("could not parse feature JSON; raw saved to data/features_raw.txt")

X, unmapped = build_vector(feats, order)
present = int(X.notna().sum(axis=1).iloc[0])
completeness = round(present / len(order), 3)

clf = joblib.load(MODEL)
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
    "extracted": feats,
    "top_contributions": contrib,
}
Path(a.out).write_text(json.dumps(out, indent=2), encoding="utf-8")

print(f"\nRISK: {label}")
for k, p in out["probabilities"].items(): print(f"  {k:<8} {p:.1%}")
print(f"\nevidence: {present}/{len(order)} features ({completeness:.0%})")
if isinstance(contrib, list):
    print("\ntop contributions:")
    for c in contrib: print(f"  {c['feature']:<22} value={c['value']}  shap={c['shap']:+.3f}")
print(f"\nwrote {a.out}")
