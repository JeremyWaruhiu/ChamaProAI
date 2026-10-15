"""Readable view of the cascade results; does not modify any file."""
import csv, re
from collections import Counter
from pathlib import Path

def shorten(t, limit=60):
    w = t.split()
    if len(w) > 6 and len(set(w)) / len(w) < 0.35:
        tok, n = Counter(w).most_common(1)[0]
        return f"[collapsed: '{tok}' x{n} of {len(w)} words]"
    return t if len(t) <= limit else t[:limit - 1] + "…"

rows = list(csv.DictReader(Path("data/translation_output.csv").open(encoding="utf-8")))
print(f"{'#':>3}  {'Kikuyu (ASR)':<62}  English")
print("-" * 140)
for r in rows:
    eng = r["english_out"].strip() or "— no translation —"
    print(f"{r['sentence_no']:>3}  {shorten(r['kikuyu_in']):<62}  {eng[:70]}")
    if r["signals"]:
        print(f"     {'':<62}  signals: {r['signals'][:70]}")
print("-" * 140)
done = sum(1 for r in rows if r["english_out"].strip())
print(f"{done}/{len(rows)} translated ({done/len(rows):.1%})")
