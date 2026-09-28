"""Experiment 04 -- SACCO and chama borrower subset with loan-module features.

Experiment 03 showed the FinAccess feature intersection carries little signal:
AUC 0.58-0.61, and an in-distribution holdout no better, so the ceiling is the
features rather than regional transfer. Those features describe WHO someone is.
They say almost nothing about the LOAN.

The per-lender modules do. This script restricts to respondents who actually
borrowed from a SACCO or a chama and adds what those modules record: amount
requested, amount approved, number of loans, collateral type, repayment
frequency and how long ago the loan was taken.

    python experiments/04_borrower_subset/prep_borrowers.py

Protocol change, stated deliberately. Central Kenya falls to ~368 rows here,
too few for a geographic holdout, so experiment 04 uses a stratified random
split. That is a weaker generalisation claim than experiment 03's and the
write-up must say so rather than quietly swapping protocols.

Excluded as leakage: E1xiG / E1xiK, the outstanding loan amount. A larger
outstanding balance is partly a CONSEQUENCE of having defaulted.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "02_finaccess_prep"))
import features as F  # noqa: E402

DTA = ROOT / "data" / "raw" / "2024_Finaccess_Publicdata.dta"
OUT = HERE / "results"

LOAN_COLS = [f"E1{s}{lend}" for lend in ("G", "K")
             for s in ("i", "ii", "iii", "iv", "v", "vii", "viii", "ix")]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    cols = ["county", F.TARGET] + F.FEATURES + F.WEIGHTS + LOAN_COLS
    df = pd.read_stata(DTA, columns=cols, convert_categoricals=True)

    tgt = df[F.TARGET].astype("string").str.strip()
    labelled = tgt.isin(F.TARGET_MAP)
    borrowed = (pd.to_numeric(df["E1viiG"], errors="coerce").notna()
                | pd.to_numeric(df["E1viiK"], errors="coerce").notna())

    keep = labelled & borrowed
    out = df.loc[keep].copy()
    out["risk_class"] = tgt.loc[keep].map(F.TARGET_MAP).astype("int8")
    out["risk_label"] = out["risk_class"].map(F.RISK_LABELS)
    out["county"] = out["county"].astype("string").str.strip()
    out["is_central"] = out["county"].isin(F.CENTRAL_KENYA)

    v = out["risk_label"].value_counts()
    profile = {
        "rows": int(len(out)),
        "of_which_sacco": int(pd.to_numeric(out["E1viiG"], errors="coerce").notna().sum()),
        "of_which_chama": int(pd.to_numeric(out["E1viiK"], errors="coerce").notna().sum()),
        "central_kenya_rows": int(out["is_central"].sum()),
        "class_distribution": {k: {"n": int(v.get(k, 0)),
                                   "pct": round(100 * v.get(k, 0) / len(out), 1)}
                               for k in ("Low", "Medium", "High")},
        "protocol": "stratified random split (Central Kenya too small for a "
                    "geographic holdout at this sample size)",
        "leakage_excluded": {
            "E1xiG/E1xiK": "outstanding loan amount is partly a consequence of default"},
    }
    out.to_csv(OUT / "borrower_frame.csv", index=False)
    (OUT / "borrower_profile.json").write_text(json.dumps(profile, indent=2))
    print(json.dumps(profile, indent=2))
    print(f"\nwrote borrower_frame.csv ({len(out):,} rows x {out.shape[1]} cols)")


if __name__ == "__main__":
    main()
