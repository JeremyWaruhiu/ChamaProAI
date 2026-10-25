"""Aggregate the cascade comparison of OpenVINO GPU int8 against Paza torch.

Does the OpenVINO GPU int8 engine (timestamped decoding) cost downstream
translation quality? Each ASR output is translated twice with
translate_extract.py; the Paza torch transcripts are re-translated under the
same settings as a like-for-like control, because the committed 47.15 chrF++
(results/summary.json) predates pinning the translator's temperature to 0:

    python scripts/translate_extract.py --input data/asr_benchmark/openvino_gpu_timestamps.csv --out data/translation_output_ov_gpu_int8_r1.csv
    python scripts/translate_extract.py --input data/asr_paza.csv --out data/translation_output_paza_rerun_r1.csv
    (and again with _r2)
    python scripts/aggregate_cascade.py

Scores every translation with score.py against data/manifest.csv english_ref
and writes only aggregates to results/cascade_openvino_gpu_int8.json; the
transcripts and translations stay in data/ (gitignored). The translator
recorded is GEMINI_MODEL from .env as it stands now, so pass --translator if
it has changed since the translations were made.
"""
import argparse, json, os, sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import score, translate_extract  # noqa: E402

OUT = Path("results/cascade_openvino_gpu_int8.json")
# run name -> (ASR file, its translations, one per repeat)
RUNS = {
    "openvino_gpu_int8_timestamps": ("data/asr_benchmark/openvino_gpu_timestamps.csv",
                                     ["data/translation_output_ov_gpu_int8_r1.csv",
                                      "data/translation_output_ov_gpu_int8_r2.csv"]),
    "paza_torch_rerun": ("data/asr_paza.csv",
                         ["data/translation_output_paza_rerun_r1.csv",
                          "data/translation_output_paza_rerun_r2.csv"]),
}
SUMMARY = Path("results/summary.json")


def baseline():
    """The committed Paza torch figures, from results/summary.json."""
    paza = json.loads((ROOT / SUMMARY).read_text(encoding="utf-8"))["asr"]["systems"]["paza"]
    return {
        "system": f"paza_torch ({SUMMARY.as_posix()})",
        "asr_file": paza["asr_file"], "translation_file": paza["translation_file"],
        "chrf_pp": paza["overall"]["chrf_pp"], "bleu": paza["overall"]["bleu"],
        "by_domain_chrf_pp": {d: v["chrf_pp"] for d, v in paza["by_domain"].items()},
        "note": "translated 2026-10-15 before translate_extract pinned temperature 0 and before .env "
                "was last edited, so its Gemini model and sampling are not recorded; the paza_torch_rerun "
                "rows re-translate the same transcripts under this file's settings as a like-for-like control",
    }


def run(asr, files):
    """Scores for each repeat of one ASR output, and their means."""
    reps = []
    for f in files:
        path = ROOT / f
        if not path.exists():
            sys.exit(f"missing {f}; translate it first (see the docstring)")
        res = score.score(score.load(path, ROOT / score.MANIFEST))
        reps.append({"translation_file": f, "corpus": res["corpus"],
                     "by_domain_chrf_pp": {d: m["chrf++"] for d, m in res["domains"].items()},
                     "by_domain_bleu": {d: m["bleu"] for d, m in res["domains"].items()}})
    mean = lambda k: round(sum(r["corpus"][k] for r in reps) / len(reps), 2)
    return {"asr_file": asr, "repeats": reps,
            "mean_chrf_pp": mean("chrf++"), "mean_bleu": mean("bleu")}


def main():
    load_dotenv(ROOT / ".env", override=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--translator", default=os.getenv("GEMINI_MODEL", translate_extract.DEFAULT_MODEL),
                    help="Gemini model the translations were made with (default: GEMINI_MODEL)")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()

    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator": "scripts/aggregate_cascade.py over scripts/translate_extract.py "
                     "--input <asr csv> --out <csv> runs, scored with scripts/score.py",
        "question": "does the OpenVINO GPU int8 engine (timestamped decoding) cost downstream "
                    "translation quality against the Paza torch transcripts?",
        "settings": {"translator": a.translator, "temperature": 0, "chunk": 10,
                     "prompt": "translate_extract.PROMPT, unchanged",
                     "references": "data/manifest.csv english_ref",
                     "metrics": "sacrebleu corpus chrF++ (word_order=2) and BLEU"},
        "baseline": baseline(),
        "runs": {name: run(asr, files) for name, (asr, files) in RUNS.items()},
        "validation": "one speaker, 40 scripted sentences of fictional worksheet content; per-domain "
                      "figures rest on 5 sentences each and are indicative only",
    }

    b = out["baseline"]
    print(f"  {'system':<38} {'chrF++':>7} {'BLEU':>6}")
    print(f"  {'paza_torch (committed)':<38} {b['chrf_pp']:>7.2f} {b['bleu']:>6.2f}")
    for name, r in out["runs"].items():
        print(f"  {name + ' (mean)':<38} {r['mean_chrf_pp']:>7.2f} {r['mean_bleu']:>6.2f}")

    path = a.out if a.out.is_absolute() else ROOT / a.out
    path.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    print(f"wrote {a.out}")


if __name__ == "__main__":
    main()
