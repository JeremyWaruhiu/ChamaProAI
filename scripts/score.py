"""Score pipeline translations against the worksheet's English references.

chrF++ (decision metric, as in experiment 01) and BLEU via sacrebleu, for the
whole corpus and per domain. References are manifest.csv's english_ref.

    python scripts/score.py
    python scripts/score.py data/translation_output.csv --json results.json

A blank english_out (translation failed or judged unintelligible) is scored
as an empty hypothesis, so the corpus figure reflects what the cascade
actually delivered; `translated` says how many rows had any output.
"""
import argparse, csv, json, sys
from pathlib import Path

from sacrebleu import corpus_bleu, corpus_chrf

MANIFEST = Path("data/manifest.csv")
RUNS = {"whisper_small": Path("data/translation_output_whisper_small.csv"),
        "paza": Path("data/translation_output.csv")}


def load(translations, manifest=MANIFEST):
    """[(domain, hypothesis, reference)] for every manifest row with a reference."""
    with Path(manifest).open(newline="", encoding="utf-8") as fh:
        ref = {r["id"]: r for r in csv.DictReader(fh) if r["english_ref"].strip()}
    if not ref:
        raise ValueError(f"{manifest} has no english_ref values")
    with Path(translations).open(newline="", encoding="utf-8") as fh:
        hyp = {r["id"]: r["english_out"].strip() for r in csv.DictReader(fh)}
    return [(m["domain"], hyp.get(i, ""), m["english_ref"].strip()) for i, m in ref.items()]


def metrics(rows):
    hyps, refs = [h for _, h, _ in rows], [r for _, _, r in rows]
    return {"n": len(rows), "translated": sum(bool(h) for h in hyps),
            "chrf++": round(corpus_chrf(hyps, [refs], word_order=2).score, 2),
            "bleu": round(corpus_bleu(hyps, [refs]).score, 2)}


def score(rows):
    domains = list(dict.fromkeys(d for d, _, _ in rows))   # manifest order
    return {"corpus": metrics(rows),
            "domains": {d: metrics([r for r in rows if r[0] == d]) for d in domains}}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*", type=Path,
                    help="translation CSVs (default: the whisper_small and paza runs)")
    ap.add_argument("--manifest", type=Path, default=MANIFEST)
    ap.add_argument("--json", type=Path, help="also write the scores here")
    a = ap.parse_args()

    runs = {f.stem: f for f in a.files} if a.files else RUNS
    results = {}
    for name, path in runs.items():
        if not path.exists():
            sys.exit(f"missing {path}")
        results[name] = score(load(path, a.manifest))

    for name, res in results.items():
        c = res["corpus"]
        print(f"\n{name}  ({runs[name]})")
        print(f"  {'domain':<18} {'n':>3} {'transl':>6} {'chrF++':>7} {'BLEU':>6}")
        for d, m in [("CORPUS", c), *res["domains"].items()]:
            print(f"  {d:<18} {m['n']:>3} {m['translated']:>6} {m['chrf++']:>7.2f} {m['bleu']:>6.2f}")
    print("\nPer-domain figures rest on 5 sentences each; read them as indicative only.")

    if a.json:
        a.json.write_text(json.dumps(results, indent=2), encoding="utf-8")
        print(f"wrote {a.json}")


if __name__ == "__main__":
    main()
