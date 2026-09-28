"""Browse the FinAccess 2024 microdata without trying to open all of it.

The file is 20,871 rows x 3,816 columns -- roughly 80 million cells. Google
Sheets caps at 10 million and Excel will struggle, so opening it whole is the
wrong approach. Work with the codebook and with slices instead.

    # 1. Write the codebook: every variable name and its survey question
    python tools/explore_finaccess.py --dictionary

    # 2. Find variables by keyword
    python tools/explore_finaccess.py --search "income"
    python tools/explore_finaccess.py --search "sacco|chama"

    # 3. Look at what one variable actually contains
    python tools/explore_finaccess.py --values E2E
    python tools/explore_finaccess.py --values A20

    # 4. Export chosen columns to a CSV that opens anywhere
    python tools/explore_finaccess.py --export county,E2E,A18,Sex,B3Ii

Outputs go to data/explore/ and are gitignored: they are derived from
licensed microdata.
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DTA = ROOT / "data" / "raw" / "2024_Finaccess_Publicdata.dta"
OUT = ROOT / "data" / "explore"


def labels() -> dict[str, str]:
    with pd.io.stata.StataReader(DTA) as r:
        return {k: str(v) for k, v in r.variable_labels().items()}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dictionary", action="store_true",
                    help="write the full codebook (3,816 rows) to CSV")
    ap.add_argument("--search", metavar="REGEX",
                    help="find variables whose name or question text matches")
    ap.add_argument("--values", metavar="VAR",
                    help="show the distribution of one variable")
    ap.add_argument("--export", metavar="COLS",
                    help="comma-separated columns to export as CSV")
    ap.add_argument("--rows", type=int, default=None,
                    help="limit exported rows (default: all)")
    a = ap.parse_args()

    if not DTA.exists():
        raise SystemExit(f"Not found: {DTA}\nPut the FinAccess .dta in data/raw/ first.")
    OUT.mkdir(parents=True, exist_ok=True)
    L = labels()

    if a.dictionary:
        df = pd.DataFrame({"variable": list(L), "question": list(L.values())})
        p = OUT / "finaccess_variable_dictionary.csv"
        df.to_csv(p, index=False)
        print(f"{len(df):,} variables -> {p}")
        print("Opens instantly in Excel or Google Sheets. Start here.")

    if a.search:
        rx = re.compile(a.search, re.I)
        hits = [(k, v) for k, v in L.items() if rx.search(k) or rx.search(v)]
        print(f"{len(hits)} match(es) for {a.search!r}:\n")
        for k, v in hits[:60]:
            print(f"  {k:26} {v[:74]}")
        if len(hits) > 60:
            print(f"  ... and {len(hits) - 60} more")

    if a.values:
        s = pd.read_stata(DTA, columns=[a.values], convert_categoricals=True)[a.values]
        print(f"\n{a.values} -- {L.get(a.values, '(no label)')}")
        print(f"type {s.dtype} | {s.notna().sum():,} answered, {s.isna().sum():,} blank\n")
        if s.dtype.kind in "ifc":
            print(s.describe().round(2).to_string())
        else:
            print(s.value_counts(dropna=False).head(25).to_string())

    if a.export:
        cols = [c.strip() for c in a.export.split(",") if c.strip()]
        missing = [c for c in cols if c not in L]
        if missing:
            raise SystemExit(f"Not in the file: {missing}\nUse --search to find the right names.")
        df = pd.read_stata(DTA, columns=cols, convert_categoricals=True)
        if a.rows:
            df = df.head(a.rows)
        p = OUT / ("finaccess_" + "_".join(cols[:4])[:50] + ".csv")
        df.to_csv(p, index=False)
        print(f"{len(df):,} rows x {len(cols)} cols -> {p}")


if __name__ == "__main__":
    main()
