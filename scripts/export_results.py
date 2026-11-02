"""Export aggregate model and evaluation figures for the admin results page.

Writes results/summary.json: aggregate numbers only -- no rows, no audio, no
transcripts, no personal data. Everything is computed here from local
artefacts; nothing is retrained and no metric is typed in by hand. A value
that cannot be computed is null, with the reason in that section's "notes".

    python scripts/export_results.py
    python scripts/export_results.py --out results/summary.json
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "03_classifier"))
sys.path.insert(0, str(ROOT / "scripts"))

MODEL = ROOT / "models" / "classifier.joblib"
META = ROOT / "models" / "classifier_meta.json"
# The comparison model, trained on the same split and never deployed:
# python scripts/train_and_save.py --estimator random_forest --name random_forest
RF_MODEL = ROOT / "models" / "random_forest.joblib"
RF_META = ROOT / "models" / "random_forest_meta.json"
# What must match between the two model cards for the comparison to be fair.
SAME_SPLIT = ("frame", "protocol", "seed", "n_train", "feature_order")
MANIFEST = ROOT / "data" / "manifest.csv"
# ASR hypotheses and the cascade's translations of them, per ASR system.
ASR_RUNS = {
    "paza": (ROOT / "data" / "asr_paza.csv", ROOT / "data" / "translation_output.csv"),
    "whisper_small": (ROOT / "data" / "asr_output_whisper_small.csv",
                      ROOT / "data" / "translation_output_whisper_small.csv"),
}
SHAP_SAMPLE = 500


def rel(p: Path) -> str:
    return str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else str(p)


def r4(x) -> float:
    return round(float(x), 4)


# --- Model card ----------------------------------------------------------------

def model_card() -> dict:
    notes = []
    meta = json.loads(META.read_text(encoding="utf-8")) if META.exists() else {}
    if not meta:
        notes.append(f"{rel(META)} not found")
    sha = None
    if MODEL.exists():
        sha = hashlib.sha256(MODEL.read_bytes()).hexdigest()
    else:
        notes.append(f"{rel(MODEL)} not found; SHA-256 not computed")
    return {
        "source": f"{rel(META)}; SHA-256 computed over {rel(MODEL)}",
        "estimator": meta.get("estimator"),
        "frame": meta.get("frame"),
        "protocol": meta.get("protocol"),
        "seed": meta.get("seed"),
        "n_train": meta.get("n_train"),
        "n_features": meta.get("n_features"),
        "classes": meta.get("classes"),
        "trained_on": meta.get("trained_on"),
        "model_file": MODEL.name,
        "model_sha256": sha,
        "notes": notes,
    }


# --- Held-out evaluation ---------------------------------------------------------

def scored(clf, X, y) -> dict:
    """Macro AUC, macro-F1 and per-class precision and recall of clf on (X, y)."""
    from model import evaluate
    ev = evaluate(y, clf.predict(X), clf.predict_proba(X))
    return {"auc_macro_ovr": ev.get("auc_ovr_macro"), "macro_f1": ev["macro_f1"],
            "per_class": {k: {"precision": v["precision"], "recall": v["recall"]}
                          for k, v in ev["per_class"].items()},
            "confusion_matrix": ev["confusion_matrix"]}


# The headline metrics: AUC and macro-F1, and High-class recall, which the
# protocol in experiments/03_classifier/model.py reports beside macro-F1.
HEADLINE = {"auc_macro_ovr": lambda m: m.get("auc_macro_ovr"),
            "macro_f1": lambda m: m.get("macro_f1"),
            "high_recall": lambda m: ((m.get("per_class") or {}).get("High") or {}).get("recall")}


def versus(deployed: dict, rf: dict) -> dict:
    """Which model is better on each headline metric, and by how much (RF minus deployed)."""
    out = {}
    for metric, get in HEADLINE.items():
        a, b = get(deployed), get(rf)
        if a is None or b is None:
            out[metric] = {"deployed": a, "random_forest": b, "difference": None, "better": None}
            continue
        diff = r4(b - a)
        out[metric] = {"deployed": a, "random_forest": b, "difference": diff,
                       "better": "tie" if diff == 0 else "random_forest" if diff > 0 else "deployed"}
    return out


def random_forest(meta: dict, X, y, deployed: dict, validation: str, frame: Path) -> dict:
    """The saved RandomForest scored on the same held-out rows as the deployed model."""
    sec = {"source": f"{rel(RF_MODEL)} scored on {rel(frame)}", "validation": validation,
           "estimator": None, "trained_on": None, "auc_macro_ovr": None, "macro_f1": None,
           "per_class": None, "per_class_recall": None, "confusion_matrix": None,
           "versus_deployed": None, "notes": []}
    if not (RF_MODEL.exists() and RF_META.exists()):
        sec["notes"].append(f"{rel(RF_MODEL)} not found; train it with python scripts/train_and_save.py "
                            "--estimator random_forest --name random_forest")
        return sec
    rf_meta = json.loads(RF_META.read_text(encoding="utf-8"))
    sec.update(estimator=rf_meta.get("estimator"), trained_on=rf_meta.get("trained_on"))
    differ = [k for k in SAME_SPLIT if rf_meta.get(k) != meta.get(k)]
    if differ:
        sec["notes"].append(f"not compared: {rel(RF_META)} differs from {rel(META)} in "
                            f"{', '.join(differ)}, so it was not trained on the same split")
        return sec
    import joblib
    out = scored(joblib.load(RF_MODEL), X, y)
    sec.update(out, per_class_recall={k: v["recall"] for k, v in out["per_class"].items()},
               versus_deployed=versus(deployed, out))
    return sec


def held_out(meta: dict) -> tuple[dict, dict, dict, dict]:
    """(performance, class_balance, random_forest, shap) on the Central Kenya holdout."""
    from model import DEFAULT_FRAME, RISK, comparator, evaluate, encode

    names = [RISK[i] for i in (0, 1, 2)]
    frame = DEFAULT_FRAME.parent / meta["frame"] if meta.get("frame") else DEFAULT_FRAME
    validation = ("geographic holdout: trained on the other 42 counties, scored on "
                  "Central Kenya, which the model never saw (scripts/train_and_save.py "
                  f"protocol central_kenya_held_out, seed {meta.get('seed')})")
    perf = {"source": f"{rel(MODEL)} scored on {rel(frame)}", "validation": validation,
            "n_test": None, "auc_macro_ovr": None, "macro_f1": None,
            "comparator_macro_f1": None, "per_class": None, "confusion_matrix": None,
            "labels": names, "notes": []}
    balance = {"source": rel(frame), "validation": validation, "labels": names,
               "train": None, "test": None, "notes": []}
    rf = {"source": rel(RF_MODEL), "validation": validation, "per_class_recall": None, "notes": []}
    shap_out = {"source": f"shap.TreeExplainer on {rel(MODEL)}", "validation": validation,
                "sample_size": None, "top_features": None, "notes": []}

    missing = [p for p in (frame, MODEL) if not p.exists()]
    if missing or meta.get("protocol") != "central_kenya_held_out":
        why = (f"missing {', '.join(rel(p) for p in missing)}" if missing else
               f"model protocol is {meta.get('protocol')!r}, so there is no held-out set")
        for sec in (perf, balance, rf, shap_out):
            sec["notes"].append(why)
        return perf, balance, rf, shap_out

    import joblib
    import pandas as pd

    df = pd.read_csv(frame, low_memory=False)
    X, y3, central = encode(df)
    X = X[meta["feature_order"]]
    Xtr, ytr = X.loc[~central], y3.loc[~central]
    Xte, yte = X.loc[central], y3.loc[central]

    counts = lambda y: {RISK[i]: int((y == i).sum()) for i in (0, 1, 2)}
    balance["train"], balance["test"] = counts(ytr), counts(yte)
    if len(Xtr) != meta.get("n_train"):
        perf["notes"].append(f"rebuilt training split has {len(Xtr)} rows but the model "
                             f"card records {meta.get('n_train')}; the frame may have changed")

    clf = joblib.load(MODEL)
    perf.update(n_test=int(len(Xte)), **scored(clf, Xte, yte))
    if perf["auc_macro_ovr"] is None:
        perf["notes"].append("AUC undefined: a class is absent from the held-out set")
    perf["comparator_macro_f1"] = evaluate(yte, comparator(df.loc[central]))["macro_f1"]
    perf["comparator_source"] = "comparator() in experiments/03_classifier/model.py"
    rf = random_forest(meta, Xte, yte, perf, validation, frame)

    try:
        import shap
        sample = Xte.sample(min(SHAP_SAMPLE, len(Xte)), random_state=meta.get("seed", 42))
        arr = np.abs(np.array(shap.TreeExplainer(clf).shap_values(sample)))
        # Same axis handling as model.py: (samples, features, classes) or (classes, samples, features)
        if arr.ndim == 3 and arr.shape[1] == X.shape[1]:
            imp = arr.mean(axis=(0, 2))
        elif arr.ndim == 3:
            imp = arr.mean(axis=(0, 1))
        else:
            imp = arr.mean(axis=0)
        order = np.argsort(imp)[::-1][:10]
        shap_out["sample_size"] = int(len(sample))
        shap_out["top_features"] = [{"feature": X.columns[i], "mean_abs_shap": round(float(imp[i]), 5)}
                                    for i in order]
    except Exception as e:  # noqa: BLE001 -- recorded, never fatal
        shap_out["notes"].append(f"SHAP unavailable: {type(e).__name__}: {e}")
    return perf, balance, rf, shap_out


# --- ASR and translation -------------------------------------------------------

def collapsed(text: str) -> bool:
    """Decoder repetition collapse: the test shorten() uses in scripts/view_results.py."""
    w = text.split()
    return len(w) > 6 and len(set(w)) / len(w) < 0.35


def read_csv(path: Path) -> list[dict]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def asr_comparison() -> dict:
    out = {"source": ("ASR: data/asr_paza.csv, data/asr_output_whisper_small.csv; "
                      "translation: data/translation_output*.csv; chrF++ and BLEU via "
                      "scripts/score.py against data/manifest.csv english_ref"),
           "validation": ("one speaker, 40 scripted sentences; per-domain figures rest on "
                          "about 5 sentences each and are indicative only"),
           "collapse_rule": "more than 6 words and under 35% distinct (scripts/view_results.py)",
           "systems": {}, "domains": [], "notes": []}
    try:
        import score
    except Exception as e:  # noqa: BLE001
        score = None
        out["notes"].append(f"scripts/score.py could not be imported ({type(e).__name__}: {e}); "
                            "chrF++ and BLEU not computed")
    domain_of = {r["id"]: r["domain"] for r in read_csv(MANIFEST)} if MANIFEST.exists() else {}
    if domain_of:
        out["domains"] = list(dict.fromkeys(domain_of.values()))

    for name, (asr_path, tr_path) in ASR_RUNS.items():
        sysout = {"asr_file": rel(asr_path), "translation_file": rel(tr_path),
                  "overall": None, "by_domain": None}
        out["systems"][name] = sysout
        if not asr_path.exists():
            out["notes"].append(f"{name}: {rel(asr_path)} not found")
            continue
        asr = read_csv(asr_path)
        tr = {r["id"]: r for r in read_csv(tr_path)} if tr_path.exists() else None
        if tr is None:
            out["notes"].append(f"{name}: {rel(tr_path)} not found; yield, chrF++ and BLEU null")
        scored = None
        if score is not None and tr is not None and MANIFEST.exists():
            scored = score.score(score.load(tr_path, MANIFEST))

        def block(rows, chrf):
            n = len(rows)
            done = sum(bool((tr.get(r["id"], {}).get("english_out") or "").strip())
                       for r in rows) if tr is not None else None
            return {"n": n,
                    "collapse_count": sum(collapsed(r["hypothesis"]) for r in rows),
                    "yield": None if done is None or n == 0 else r4(done / n),
                    "chrf_pp": chrf["chrf++"] if chrf else None,
                    "bleu": chrf["bleu"] if chrf else None}

        sysout["overall"] = block(asr, scored["corpus"] if scored else None)
        by_domain = {}
        for d in dict.fromkeys(r["domain"] for r in asr):
            by_domain[d] = block([r for r in asr if r["domain"] == d],
                                 scored["domains"].get(d) if scored else None)
        sysout["by_domain"] = by_domain
    return out


# --- Main ------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "results" / "summary.json")
    a = ap.parse_args()

    card = model_card()
    meta = json.loads(META.read_text(encoding="utf-8")) if META.exists() else {}
    perf, balance, rf, shap_out = held_out(meta)
    summary = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator": "scripts/export_results.py",
        "model_card": card,
        "held_out": perf,
        "class_balance": balance,
        "random_forest": rf,
        "shap": shap_out,
        "asr": asr_comparison(),
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"wrote {a.out}")
    for key, sec in summary.items():
        for n in sec.get("notes", []) if isinstance(sec, dict) else []:
            print(f"  note [{key}]: {n}")


if __name__ == "__main__":
    main()
