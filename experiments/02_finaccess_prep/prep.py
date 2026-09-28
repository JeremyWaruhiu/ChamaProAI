"""Experiment 02 -- build the ChamaPro AI modelling frame from FinAccess 2024.

Produces a tidy, labelled dataset and a profile report. No model is trained
here; encoding and training belong to experiment 03.

    python experiments/02_finaccess_prep/prep.py
    python experiments/02_finaccess_prep/prep.py --include-suspect

Design decisions worth defending:

1. Central Kenya is HELD OUT of training entirely, not merely evaluated on.
   Training on all 13,111 labelled rows and then "evaluating on the Central
   subset" would score the model on rows it had already seen. Instead the
   model trains on the other 42 counties and Central Kenya is an unseen
   target population. Costs ~1,685 training rows; buys an honest number.

2. Rows with blank E2E did not borrow. They are filtered, never imputed.

3. Leakage variables are excluded by name and by stated reason, see
   features.py. `--include-suspect` re-admits the borderline ones so the
   effect can be measured and reported rather than argued.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))
import features as F  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DTA = ROOT / "data" / "raw" / "2024_Finaccess_Publicdata.dta"
OUT = Path(__file__).parent / "results"


def load(include_suspect: bool) -> pd.DataFrame:
    cols = ["county", F.TARGET] + F.FEATURES + F.WEIGHTS
    if include_suspect:
        cols += list(F.SUSPECT)
    missing_ok = []
    with pd.io.stata.StataReader(DTA) as r:
        available = set(r.variable_labels())
    for c in cols:
        if c not in available:
            missing_ok.append(c)
    if missing_ok:
        raise SystemExit(f"Variables not in the .dta: {missing_ok}")
    return pd.read_stata(DTA, columns=cols, convert_categoricals=True)


def build(df: pd.DataFrame) -> pd.DataFrame:
    tgt = df[F.TARGET].astype("string").str.strip()
    labelled = tgt.isin(F.TARGET_MAP)
    df = df.loc[labelled].copy()
    df["risk_class"] = tgt.loc[labelled].map(F.TARGET_MAP).astype("int8")
    df["risk_label"] = df["risk_class"].map(F.RISK_LABELS)
    df["county"] = df["county"].astype("string").str.strip()
    df["is_central"] = df["county"].isin(F.CENTRAL_KENYA)
    return df


def report(df: pd.DataFrame, include_suspect: bool) -> dict:
    train, evalset = df.loc[~df.is_central], df.loc[df.is_central]

    def dist(d):
        v = d["risk_label"].value_counts()
        n = len(d)
        return {k: {"n": int(v.get(k, 0)),
                    "pct": round(100 * v.get(k, 0) / n, 1)} for k in ("Low", "Medium", "High")}

    feats = list(F.FEATURES) + (list(F.SUSPECT) if include_suspect else [])
    nulls = df[feats].isna().mean().mul(100).round(1).sort_values(ascending=False)

    return {
        "source_file": DTA.name,
        "include_suspect": include_suspect,
        "n_features": len(feats),
        "labelled_rows": len(df),
        "train_rows_non_central": len(train),
        "eval_rows_central": len(evalset),
        "class_distribution": {"train": dist(train), "eval_central": dist(evalset)},
        "leakage_excluded": len(F.LEAKAGE_EXCLUDED),
        "features_over_20pct_missing": {k: float(v) for k, v in nulls[nulls > 20].items()},
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--include-suspect", action="store_true",
                    help="re-admit borderline-leakage variables for a sensitivity run")
    a = ap.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    df = build(load(a.include_suspect))
    rep = report(df, a.include_suspect)

    suffix = "_suspect" if a.include_suspect else ""
    frame_path = OUT / f"modelling_frame{suffix}.csv"
    prof_path = OUT / f"prep_profile{suffix}.json"
    df.to_csv(frame_path, index=False)
    prof_path.write_text(json.dumps(rep, indent=2))

    print(json.dumps(rep, indent=2))
    print(f"\nwrote {frame_path.name} ({len(df):,} rows x {df.shape[1]} cols)")
    print(f"wrote {prof_path.name}")


if __name__ == "__main__":
    main()
