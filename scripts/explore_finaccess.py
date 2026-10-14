"""Command-line viewer for the FinAccess 2024 Stata microdata.

FinAccess variable names are opaque codes (E1xiG, B3F2, ...), so start with
`search` to find variables by name or question text, then inspect them.

    python scripts/explore_finaccess.py overview
    python scripts/explore_finaccess.py dictionary --out codebook.csv
    python scripts/explore_finaccess.py search chama
    python scripts/explore_finaccess.py show county
    python scripts/explore_finaccess.py crosstab county A08

Stata value labels are converted to readable categories. The source file is
only ever read.
"""
from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

import pandas as pd

DEFAULT_FILE = Path("data/raw/2024_Finaccess_Publicdata.dta")
MAX_LABEL = 70
FEW_UNIQUE = 25
MAX_CROSSTAB_LEVELS = 100


# --------------------------------------------------------------------------
# Loading

class Meta:
    """Variable labels, value labels and the variable -> label-set mapping."""

    def __init__(self, path: Path):
        with pd.io.stata.StataReader(path) as r:
            self.var_labels = {k: str(v) for k, v in r.variable_labels().items()}
            self.value_labels = r.value_labels()
            # Not public API; without it every column goes through read_stata.
            lbllist = getattr(r, "_lbllist", None)
        names = list(self.var_labels)
        self.label_set = dict(zip(names, lbllist)) if lbllist is not None else {}

    @property
    def names(self) -> list[str]:
        return list(self.var_labels)

    def has_duplicate_labels(self, var: str) -> bool:
        m = self.value_labels.get(self.label_set.get(var, ""))
        return bool(m) and len(set(m.values())) < len(m)


def fail(msg: str) -> None:
    sys.exit(f"error: {msg}")


def open_meta(path: Path) -> Meta:
    if not path.exists():
        fail(f"file not found: {path}")
    if not path.is_file():
        fail(f"not a file: {path}")
    try:
        return Meta(path)
    except Exception as e:  # pandas raises several types for non-Stata input
        fail(f"{path} is not a readable Stata .dta file ({type(e).__name__}: {e})")


def load(path: Path, meta: Meta, columns: list[str] | None = None) -> pd.DataFrame:
    """Read the file with value labels applied.

    read_stata refuses to convert a column whose label set maps two codes to
    the same text (B3F2 and a handful of others in FinAccess 2024). Those
    columns are read as raw codes and labelled here, with the code appended
    to the repeated labels so they stay distinct.
    """
    cols = columns or meta.names
    dup = [c for c in cols if meta.has_duplicate_labels(c)]
    clean = [c for c in cols if c not in dup]
    print(f"reading {len(cols):,} variable(s) from {path} ...", file=sys.stderr)

    parts = []
    if clean:
        parts.append(pd.read_stata(path, columns=clean, iterator=False,
                                   convert_categoricals=True))
    if dup:
        raw = pd.read_stata(path, columns=dup, iterator=False,
                            convert_categoricals=False)
        for c in dup:
            raw[c] = apply_labels(raw[c], meta.value_labels[meta.label_set[c]])
        parts.append(raw)
    df = pd.concat(parts, axis=1)[cols]
    # Stata stores a missing string as "", so count it as missing.
    for c in df.columns:
        if pd.api.types.is_string_dtype(df[c]) and not isinstance(df[c].dtype, pd.CategoricalDtype):
            df[c] = df[c].mask(df[c].str.strip() == "")
    return df


def apply_labels(s: pd.Series, mapping: dict) -> pd.Series:
    texts = list(mapping.values())
    names = {k: (v if texts.count(v) == 1 else f"{v} [{k}]") for k, v in mapping.items()}
    codes = sorted(s.dropna().unique())
    # Like read_stata, codes without a label keep their numeric value.
    cats = [names.get(k, k) for k in sorted(set(codes) | set(mapping))]
    return pd.Series(pd.Categorical(s.map(lambda v: names.get(v, v)), categories=cats),
                     index=s.index, name=s.name)


def resolve(meta: Meta, var: str) -> str:
    """Exact name, else a unique case-insensitive match."""
    if var in meta.var_labels:
        return var
    hits = [n for n in meta.names if n.lower() == var.lower()]
    if len(hits) == 1:
        return hits[0]
    fail(f"no variable named {var!r}. Try: search {var}")


# --------------------------------------------------------------------------
# Formatting

def trunc(text, width: int = MAX_LABEL) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= width else text[:width - 3] + "..."


def print_table(rows: list[list], headers: list[str], right: set[int] = frozenset()) -> None:
    """Aligned plain-text table; columns in `right` are right-aligned."""
    cells = [[trunc(h) for h in headers]] + [[trunc(v) for v in r] for r in rows]
    widths = [max(len(r[i]) for r in cells) for i in range(len(headers))]

    def line(r):
        return "  ".join(v.rjust(w) if i in right else v.ljust(w)
                         for i, (v, w) in enumerate(zip(r, widths))).rstrip()

    print(line(cells[0]))
    print("  ".join("-" * w for w in widths))
    for r in cells[1:]:
        print(line(r))


def human_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:,.1f} {unit}"
        n /= 1024
    return f"{n:,.1f} TB"


def num(v: float) -> str:
    return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.2f}"


def pct(n: float, d: float) -> str:
    return f"{100 * n / d:.1f}" if d else "-"


def is_numeric(s: pd.Series) -> bool:
    return pd.api.types.is_numeric_dtype(s) and not isinstance(s.dtype, pd.CategoricalDtype)


# --------------------------------------------------------------------------
# Commands

def cmd_overview(a, meta: Meta) -> None:
    df = load(a.file, meta)
    print(f"file      {a.file}  ({human_bytes(a.file.stat().st_size)} on disk)")
    print(f"rows      {len(df):,}")
    print(f"columns   {df.shape[1]:,}")
    print(f"memory    {human_bytes(df.memory_usage(deep=True).sum())} (loaded, value labels applied)")
    print()
    counts = df.dtypes.astype(str).value_counts()
    print_table([[t, f"{n:,}"] for t, n in counts.items()], ["dtype", "variables"], right={1})


def dictionary(df: pd.DataFrame, meta: Meta) -> pd.DataFrame:
    n = len(df)
    nonnull = df.notna().sum()
    out = pd.DataFrame({
        "variable": df.columns,
        "label": [meta.var_labels.get(c, "") for c in df.columns],
        "dtype": df.dtypes.astype(str).values,
        "non_null": nonnull.values,
        "missing_pct": ((1 - nonnull / n) * 100).round(1).values if n else 0.0,
        "n_unique": df.nunique().values,
    })
    return out.sort_values("variable", key=lambda s: s.str.lower(), ignore_index=True)


def print_dictionary(d: pd.DataFrame) -> None:
    rows = [[r.variable, r.label, r.dtype, f"{r.non_null:,}", f"{r.missing_pct:.1f}",
             f"{r.n_unique:,}"] for r in d.itertuples()]
    print_table(rows, ["variable", "label", "dtype", "non_null", "missing_%", "n_unique"],
                right={3, 4, 5})


def cmd_dictionary(a, meta: Meta) -> None:
    if a.out and a.out.resolve() == a.file.resolve():
        fail("--out would overwrite the source file")
    d = dictionary(load(a.file, meta), meta)
    if a.out:
        d.to_csv(a.out, index=False)
        print(f"{len(d):,} variables -> {a.out}")
    else:
        print_dictionary(d)


def cmd_search(a, meta: Meta) -> None:
    term = a.term.lower()
    hits = [n for n, lab in meta.var_labels.items()
            if term in n.lower() or term in lab.lower()]
    if not hits:
        print(f"no variable name or label contains {a.term!r}")
        return
    print_dictionary(dictionary(load(a.file, meta, hits), meta))
    print(f"\n{len(hits)} match(es) for {a.term!r}")


def cmd_show(a, meta: Meta) -> None:
    var = resolve(meta, a.var)
    s = load(a.file, meta, [var])[var]
    n, valid = len(s), int(s.notna().sum())
    print(f"variable  {var}")
    print(f"label     {meta.var_labels.get(var) or '(none)'}")
    print(f"dtype     {s.dtype}")
    print(f"missing   {n - valid:,} of {n:,} ({pct(n - valid, n)}%)")
    print()

    nunique = s.nunique()
    if is_numeric(s) and nunique >= FEW_UNIQUE:
        desc = s.describe()
        dec = s.quantile([i / 10 for i in range(1, 10)])
        rows = [[k, num(v)] for k, v in desc.items()]
        rows += [[f"p{round(q * 100)}", num(v)] for q, v in dec.items()]
        print_table(rows, ["statistic", "value"], right={1})
        return

    counts = s.value_counts(sort=False)
    counts = counts[counts > 0]
    if not isinstance(s.dtype, pd.CategoricalDtype):
        counts = counts.sort_values(ascending=False)
    shown = counts if isinstance(s.dtype, pd.CategoricalDtype) else counts.head(FEW_UNIQUE)
    rows = [[v, f"{c:,}", pct(c, n), pct(c, valid)] for v, c in shown.items()]
    if n - valid:
        rows.append(["<missing>", f"{n - valid:,}", pct(n - valid, n), ""])
    print_table(rows, ["value", "n", "%_all", "%_valid"], right={1, 2, 3})
    if len(shown) < len(counts):
        print(f"\n... {len(counts) - len(shown):,} more values not shown "
              f"(top {len(shown)} of {nunique:,} by frequency)")


def cmd_crosstab(a, meta: Meta) -> None:
    va, vb = resolve(meta, a.a), resolve(meta, a.b)
    if va == vb:
        fail("crosstab needs two different variables")
    df = load(a.file, meta, [va, vb])
    for v in (va, vb):
        k = df[v].nunique()
        if k > MAX_CROSSTAB_LEVELS:
            fail(f"{v} has {k:,} distinct values; too many for a crosstab. "
                 f"Use: show {v}")

    print(f"rows      {va}  {meta.var_labels.get(va, '')}")
    print(f"columns   {vb}  {meta.var_labels.get(vb, '')}")
    both = df.dropna()
    print(f"cases     {len(both):,} with both answered ({len(df) - len(both):,} excluded)")
    print("cells     row percentages\n")
    if both.empty:
        return

    counts = pd.crosstab(both[va], both[vb])
    counts = counts.loc[counts.sum(axis=1) > 0, counts.sum(axis=0) > 0]
    shares = counts.div(counts.sum(axis=1), axis=0) * 100
    total = counts.sum(axis=0) / counts.values.sum() * 100

    rows = [[idx, *(f"{x:.1f}" for x in r), f"{counts.loc[idx].sum():,}"]
            for idx, r in zip(shares.index, shares.values)]
    rows.append(["All", *(f"{x:.1f}" for x in total), f"{counts.values.sum():,}"])
    ncols = shares.shape[1]
    print_table(rows, [va, *map(str, shares.columns), "n"], right=set(range(1, ncols + 2)))


# --------------------------------------------------------------------------

def main() -> None:
    if hasattr(signal, "SIGPIPE"):  # quiet exit when piped into head/less
        signal.signal(signal.SIGPIPE, signal.SIG_DFL)

    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", type=Path, default=DEFAULT_FILE,
                    help=f"Stata .dta file (default: {DEFAULT_FILE})")
    sub = ap.add_subparsers(dest="command", required=True, metavar="COMMAND")

    p = sub.add_parser("overview", help="row/column counts, memory, dtypes")
    p.set_defaults(func=cmd_overview)

    p = sub.add_parser("dictionary", help="data dictionary for every variable")
    p.add_argument("--out", type=Path, help="write the dictionary to this CSV instead")
    p.set_defaults(func=cmd_dictionary)

    p = sub.add_parser("search", help="find variables by name or label")
    p.add_argument("term", help="case-insensitive substring")
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("show", help="summarise one variable")
    p.add_argument("var")
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("crosstab", help="crosstab of two variables, row percentages")
    p.add_argument("a", metavar="A", help="row variable")
    p.add_argument("b", metavar="B", help="column variable")
    p.set_defaults(func=cmd_crosstab)

    a = ap.parse_args()
    a.func(a, open_meta(a.file))


if __name__ == "__main__":
    main()
