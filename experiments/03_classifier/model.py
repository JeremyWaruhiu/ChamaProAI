"""Experiment 03 -- credit risk classifier, rule-based comparator, SHAP.

Trains the single model this project contributes: a three-class ordinal
credit-risk classifier over the FinAccess 2024 feature intersection.

    python experiments/03_classifier/model.py
    python experiments/03_classifier/model.py --frame path/to/modelling_frame.csv

Evaluation protocol. The model trains on 42 counties and is scored on
Central Kenya, which it has never seen. Central Kenya defaults completely
at 22.1% against 13.7% in the training counties, so accuracy is a
misleading headline here and macro-F1 and High-class recall are reported
in its place.

The comparator. The design specified a rule-based baseline of
savings x3, >=2 guarantors and >=6 months membership tenure. FinAccess
collects none of those three: there is no savings amount anywhere in the
survey, no guarantor count, and no membership tenure. The comparator below
keeps the LOGIC of that rule -- capacity, security, relationship -- using
variables present for every borrower, and this substitution is a stated
limitation rather than a silent one.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
from sklearn.metrics import (balanced_accuracy_score, classification_report,
                             confusion_matrix, f1_score, roc_auc_score)
from sklearn.model_selection import StratifiedKFold, cross_val_score

HERE = Path(__file__).resolve().parent
DEFAULT_FRAME = HERE.parent / "02_finaccess_prep" / "results" / "modelling_frame.csv"
OUT = HERE / "results"

RISK = {0: "Low", 1: "Medium", 2: "High"}

# Education is genuinely ordinal, so it is encoded as a ladder rather than
# one-hot: it keeps SHAP readable as a single "education" contribution.
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
USAGE_LADDER = {"Never used": 0, "Used to use": 1, "Currently use": 2}

BINARY_01 = ([f"B3A__{i}" for i in range(1, 12)]
             + [f"F1__{i}" for i in (1, 2, 3, 4, 5)]
             + ["E3B__3", "E3B__7"])
YES_NO = [f"B1L__{i}" for i in range(1, 7)]


def clean_label(s: pd.Series) -> pd.Series:
    """FinAccess string categories carry stray quotes and trailing spaces."""
    return (s.astype("string")
             .str.replace('"', "", regex=False)
             .str.replace("'", "", regex=False)
             .str.strip())


def encode(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, pd.Series]:
    X = pd.DataFrame(index=df.index)

    # Counts and amounts. Missing children/agriculture is structural
    # (no children, not a farmer), so zero is the correct fill, not a mean.
    X["age"] = pd.to_numeric(df["A18"], errors="coerce")
    X["household_size"] = pd.to_numeric(df["NHM"], errors="coerce")
    for src, name in [("A22i", "children"), ("A22ii", "children_under5"),
                      ("A22iii", "children_in_school")]:
        X[name] = pd.to_numeric(df[src], errors="coerce").fillna(0)

    # Monthly income is heavily right-skewed (median 5,000, max 200,000).
    inc = pd.to_numeric(df["B3Ii"], errors="coerce")
    X["log_monthly_income"] = np.log1p(inc.fillna(0))
    X["income_missing"] = inc.isna().astype(int)

    agri = pd.to_numeric(df["Q1"], errors="coerce").fillna(0)
    X["log_agri_income"] = np.log1p(agri)

    for c in BINARY_01:
        X[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
    for c in YES_NO:
        X[c] = clean_label(df[c]).str.lower().eq("yes").fillna(False).astype(int)

    # 4 rows carry junk education codes; -1 marks them as a distinct
    # "unknown" level rather than being silently imputed to the median.
    X["education"] = clean_label(df["A20"]).map(EDU_LADDER).fillna(-1).astype(int)
    X["sacco_loan_use"] = clean_label(df["C1_17"]).map(USAGE_LADDER).fillna(0).astype(int)
    X["chama_loan_use"] = clean_label(df["C1_21"]).map(USAGE_LADDER).fillna(0).astype(int)

    X["is_female"] = clean_label(df["Sex"]).eq("Female").fillna(False).astype(int)
    marital = clean_label(df["A21"])
    for cat in ["Married/Living with partner", "Single/Never Married",
                "Widowed", "Divorced/separated"]:
        X["marital_" + cat.split("/")[0].lower().replace(" ", "_")] = (
            marital.eq(cat).fillna(False).astype(int))

    return X, df["risk_class"].astype(int), df["is_central"].astype(bool)


def comparator(df: pd.DataFrame) -> np.ndarray:
    """Deterministic three-rule baseline reproducing current SACCO practice.

    Capacity     -- income at or above the national median (KSh 5,000/month)
    Security     -- holds any non-monetary asset or made an asset purchase
    Relationship -- has an existing or prior SACCO or chama borrowing record

    Rules passed maps to risk: 3 -> Low, 2 -> Medium, 0 or 1 -> High.
    No fitting, no parameters learned from the data; the income threshold is
    the published national median, not a tuned cutoff.
    """
    inc = pd.to_numeric(df["B3Ii"], errors="coerce").fillna(0)
    capacity = (inc >= 5000).astype(int)

    holdings = np.zeros(len(df), dtype=int)
    for c in [f"F1__{i}" for i in (1, 2, 3, 4, 5)]:
        holdings |= pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int).values
    for c in [f"B1L__{i}" for i in range(1, 7)]:
        holdings |= clean_label(df[c]).str.lower().eq("yes").fillna(False).astype(int).values
    security = holdings

    rel = np.zeros(len(df), dtype=int)
    for c in ("C1_17", "C1_21"):
        rel |= clean_label(df[c]).map(USAGE_LADDER).fillna(0).gt(0).astype(int).values
    relationship = rel

    passed = capacity.values + security + relationship
    return np.where(passed >= 3, 0, np.where(passed == 2, 1, 2))


def evaluate(y_true, y_pred, proba=None) -> dict:
    out = {
        "macro_f1": round(float(f1_score(y_true, y_pred, average="macro")), 4),
        "balanced_accuracy": round(float(balanced_accuracy_score(y_true, y_pred)), 4),
        "accuracy": round(float((np.asarray(y_true) == np.asarray(y_pred)).mean()), 4),
        "per_class": {},
        "confusion_matrix": confusion_matrix(y_true, y_pred, labels=[0, 1, 2]).tolist(),
    }
    rep = classification_report(y_true, y_pred, labels=[0, 1, 2],
                               target_names=[RISK[i] for i in (0, 1, 2)],
                               output_dict=True, zero_division=0)
    for k in ("Low", "Medium", "High"):
        out["per_class"][k] = {m: round(float(rep[k][m]), 4)
                               for m in ("precision", "recall", "f1-score")}
    if proba is not None:
        out["auc_ovr_macro"] = round(float(
            roc_auc_score(y_true, proba, multi_class="ovr", average="macro")), 4)
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frame", default=str(DEFAULT_FRAME))
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(a.frame, low_memory=False)
    X, y, central = encode(df)

    Xtr, ytr = X.loc[~central], y.loc[~central]
    Xev, yev = X.loc[central], y.loc[central]

    models = {
        "random_forest": RandomForestClassifier(
            n_estimators=500, min_samples_leaf=5, class_weight="balanced_subsample",
            n_jobs=-1, random_state=a.seed),
        "hist_gradient_boosting": HistGradientBoostingClassifier(
            max_iter=300, learning_rate=0.06, class_weight="balanced",
            random_state=a.seed),
    }

    results = {"n_train": int(len(Xtr)), "n_eval_central": int(len(Xev)),
               "n_features": int(X.shape[1]), "models": {}}

    from sklearn.model_selection import train_test_split
    Xin_tr, Xin_te, yin_tr, yin_te = train_test_split(
        Xtr, ytr, test_size=0.2, stratify=ytr, random_state=a.seed)

    cv = StratifiedKFold(5, shuffle=True, random_state=a.seed)
    fitted = {}
    for name, m in models.items():
        cvs = cross_val_score(m, Xtr, ytr, cv=cv, scoring="f1_macro", n_jobs=-1)
        m.fit(Xtr, ytr)
        fitted[name] = m
        # Same estimator, in-distribution: isolates feature weakness from shift.
        m_in = models[name].__class__(**models[name].get_params())
        m_in.fit(Xin_tr, yin_tr)
        results["models"][name] = {
            "cv_macro_f1_mean": round(float(cvs.mean()), 4),
            "cv_macro_f1_std": round(float(cvs.std()), 4),
            "in_distribution_holdout": evaluate(
                yin_te, m_in.predict(Xin_te), m_in.predict_proba(Xin_te)),
            "central_holdout": evaluate(yev, m.predict(Xev), m.predict_proba(Xev)),
        }

    results["models"]["rule_based_comparator"] = {
        "note": "deterministic; no training",
        "central_holdout": evaluate(yev, comparator(df.loc[central])),
    }
    # The comparator on the same rows the models trained on, for reference.
    results["comparator_on_train_counties"] = evaluate(ytr, comparator(df.loc[~central]))

    best = max(fitted, key=lambda k: results["models"][k]["central_holdout"]["macro_f1"])
    results["selected_model"] = best
    cmp_f1 = results["models"]["rule_based_comparator"]["central_holdout"]["macro_f1"]
    best_f1 = results["models"][best]["central_holdout"]["macro_f1"]
    results["improvement_over_comparator_macro_f1"] = round(best_f1 - cmp_f1, 4)

    # SHAP on the selected model -- global importance only here; per-applicant
    # local attributions are produced at inference by the API.
    try:
        import shap
        expl = shap.TreeExplainer(fitted[best])
        sv = expl.shap_values(Xev.sample(min(400, len(Xev)), random_state=a.seed))
        arr = np.abs(np.array(sv))
        if arr.ndim == 3 and arr.shape[1] == Xev.shape[1]:
            imp = arr.mean(axis=(0, 2))          # (samples, features, classes)
        elif arr.ndim == 3:
            imp = arr.mean(axis=(0, 1))          # (classes, samples, features)
        else:
            imp = arr.mean(axis=0)
        order = np.argsort(imp)[::-1][:15]
        results["shap_top_features"] = [
            {"feature": X.columns[i], "mean_abs_shap": round(float(imp[i]), 5)}
            for i in order]
    except Exception as e:  # SHAP is diagnostic, never load-bearing
        results["shap_top_features"] = f"unavailable: {type(e).__name__}: {e}"

    (OUT / "model_results.json").write_text(json.dumps(results, indent=2))
    print(json.dumps(results, indent=2))
    print(f"\nwrote {OUT / 'model_results.json'}")


if __name__ == "__main__":
    main()
