"""Benchmark the ASR engines and decoding modes over the 40 manifest clips.

Runs every clip in data/manifest.csv under each engine/device (torch CPU,
OpenVINO CPU int8, OpenVINO GPU int8), each in two decoding modes:

    timestamps   timestamped decoding, chunks past the clip end dropped, token cap
    plain        plain decoding, token cap

and records per run: total RTF (ASR seconds / audio seconds), mean per-clip
RTF, repetition-collapse count (scripts/view_results.py), and agreement with
the reference transcripts in data/asr_paza.csv (character-level similarity).

Per-clip transcripts go to data/asr_benchmark/ (gitignored: personal data);
only aggregate numbers go to results/asr_benchmark.json.

    python scripts/benchmark_asr.py
    python scripts/benchmark_asr.py --runs openvino:GPU --limit 5

Never falls back: a run whose engine or device cannot load is recorded as
skipped, with the reason, rather than silently measured on something else.
"""
from __future__ import annotations

import argparse, csv, gc, json, os, platform, statistics, sys, time
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

from rapidfuzz.distance import Levenshtein

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import transcribe  # noqa: E402
from view_results import collapsed  # noqa: E402

RUNS = [("torch", "CPU"), ("openvino", "CPU"), ("openvino", "GPU")]
PACKAGES = ["torch", "transformers", "openvino", "optimum-intel", "optimum", "nncf", "numpy"]


def norm(t: str) -> str:
    return " ".join(t.casefold().split())


def similarity(a: str, b: str) -> float:
    """Character-level similarity, 1 - Levenshtein distance / longer length,
    after case-folding and collapsing whitespace. Two empty strings agree."""
    return float(Levenshtein.normalized_similarity(norm(a), norm(b)))


def summarise(rows: list[dict]) -> dict:
    audio = sum(r["duration_s"] for r in rows)
    asr = sum(r["seconds"] for r in rows)
    agree = [r["agreement"] for r in rows if r["agreement"] is not None]
    return {
        "n": len(rows),
        "audio_seconds": round(audio, 2),
        "asr_seconds": round(asr, 2),
        "total_rtf": round(asr / audio, 4) if audio else None,
        "mean_rtf": round(statistics.fmean(r["seconds"] / r["duration_s"] for r in rows), 4)
                    if rows else None,
        "collapse_count": sum(r["collapsed"] for r in rows),
        "empty_count": sum(not r["hypothesis"].strip() for r in rows),
        "agreement_n": len(agree),
        "agreement_mean": round(statistics.fmean(agree), 4) if agree else None,
        "agreement_median": round(statistics.median(agree), 4) if agree else None,
        "agreement_min": round(min(agree), 4) if agree else None,
        "exact_matches": sum(a == 1.0 for a in agree),
    }


def device_names() -> dict:
    try:
        import openvino as ov
        core = ov.Core()
        return {d: core.get_property(d, "FULL_DEVICE_NAME") for d in core.available_devices}
    except Exception as e:  # noqa: BLE001 -- informational only
        return {"error": f"{type(e).__name__}: {e}"}


def versions() -> dict:
    out = {"python": platform.python_version()}
    for p in PACKAGES:
        try:
            out[p] = metadata.version(p)
        except metadata.PackageNotFoundError:
            out[p] = None
    return out


def run_one(engine, device, clips, ref, a, log) -> dict:
    t0 = time.time()
    try:
        asr = transcribe.load_asr(a.model, engine, device, a.ov_dir, log=log, fallback=False)
    except Exception as e:  # noqa: BLE001 -- recorded as skipped
        log(f"  skipped: {type(e).__name__}: {e}")
        return {mode: {"skipped": f"{type(e).__name__}: {e}"} for mode in a.modes}
    load_s = round(time.time() - t0, 2)

    out = {}
    try:
        for mode in a.modes:
            # Warm-up (model compile, caches): one clip, not counted.
            transcribe.transcribe_clip(clips[0]["path"], asr.pipe, a.language,
                                       clips[0]["duration_s"], decoding=mode,
                                       tokens_per_second=a.tokens_per_second)
            rows = []
            for i, c in enumerate(clips, 1):
                res = transcribe.transcribe_clip(c["path"], asr.pipe, a.language, c["duration_s"],
                                                 decoding=mode, tokens_per_second=a.tokens_per_second)
                r_ref = ref.get(c["id"])
                rows.append({"id": c["id"], "sentence_no": c["sentence_no"],
                             "duration_s": c["duration_s"], "seconds": res["seconds"],
                             "rtf": round(res["seconds"] / c["duration_s"], 4),
                             "token_cap": transcribe.token_cap(c["duration_s"], a.tokens_per_second),
                             "collapsed": collapsed(res["text"]),
                             "agreement": None if r_ref is None else round(similarity(res["text"], r_ref), 4),
                             "hypothesis": res["text"]})
                log(f"  [{engine} {device} {mode}] {i}/{len(clips)} {c['id']} "
                    f"{res['seconds']:.2f}s  {res['text'][:60]}")
            name = f"{engine}_{device.lower()}_{mode}"
            path = a.clips_dir / f"{name}.csv"
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", newline="", encoding="utf-8") as fh:
                w = csv.DictWriter(fh, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
            out[mode] = {**summarise(rows), "load_seconds": load_s, "model": asr.model}
            log(f"  -> {path}")
    finally:
        del asr
        gc.collect()
    return out


def table(results: dict) -> str:
    head = (f"{'engine':<9} {'device':<6} {'decoding':<11} {'total RTF':>9} {'mean RTF':>9} "
            f"{'collapse':>8} {'empty':>5} {'agree mean':>10} {'agree min':>9} {'exact':>5}")
    lines = [head, "-" * len(head)]
    for run, modes in results.items():
        engine, device = run.split(":")
        for mode, m in modes.items():
            if "skipped" in m:
                lines.append(f"{engine:<9} {device:<6} {mode:<11} skipped: {m['skipped'][:60]}")
                continue
            fmt = lambda x, p=3: "—" if x is None else f"{x:.{p}f}"
            lines.append(f"{engine:<9} {device:<6} {mode:<11} {fmt(m['total_rtf']):>9} "
                         f"{fmt(m['mean_rtf']):>9} {m['collapse_count']:>8} {m['empty_count']:>5} "
                         f"{fmt(m['agreement_mean']):>10} {fmt(m['agreement_min']):>9} "
                         f"{m['exact_matches']:>5}")
    return "\n".join(lines)


def parse_runs(text: str) -> list[tuple[str, str]]:
    runs = []
    for item in text.split(","):
        engine, _, device = item.strip().partition(":")
        if engine not in transcribe.ENGINES or device.upper() not in ("CPU", "GPU"):
            raise argparse.ArgumentTypeError(f"bad run {item!r}; use engine:DEVICE, e.g. openvino:GPU")
        runs.append((engine, device.upper()))
    return runs


def main():
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=parse_runs, default=RUNS,
                    help="comma-separated engine:DEVICE (default: torch:CPU,openvino:CPU,openvino:GPU)")
    ap.add_argument("--modes", nargs="+", choices=transcribe.DECODINGS, default=list(transcribe.DECODINGS))
    ap.add_argument("--limit", type=int, default=0, help="only the first N clips")
    ap.add_argument("--model", default=os.getenv("ASR_MODEL") or "microsoft/paza-whisper-large-v3-turbo")
    ap.add_argument("--ov-dir", type=Path,
                    default=ROOT / (os.getenv("ASR_OV_MODEL_DIR") or "models/paza-ov-int8"))
    ap.add_argument("--language", default=os.getenv("ASR_LANGUAGE") or "sw")
    ap.add_argument("--tokens-per-second", type=float,
                    default=float(os.getenv("ASR_TOKENS_PER_SECOND") or transcribe.TOKENS_PER_SECOND))
    ap.add_argument("--manifest", type=Path, default=ROOT / "data" / "manifest.csv")
    ap.add_argument("--reference", type=Path, default=ROOT / "data" / "asr_paza.csv")
    ap.add_argument("--clips-dir", type=Path, default=ROOT / "data" / "asr_benchmark")
    ap.add_argument("--out", type=Path, default=ROOT / "results" / "asr_benchmark.json")
    a = ap.parse_args()

    with a.manifest.open(newline="", encoding="utf-8") as fh:
        clips = [{"id": r["id"], "sentence_no": r["sentence_no"], "path": str(ROOT / r["path"]),
                  "duration_s": float(r["duration_s"])} for r in csv.DictReader(fh)]
    if a.limit:
        clips = clips[:a.limit]
    missing = [c["id"] for c in clips if not Path(c["path"]).exists()]
    if missing:
        sys.exit(f"{len(missing)} clip(s) missing, e.g. {missing[:3]}")
    ref = {}
    if a.reference.exists():
        with a.reference.open(newline="", encoding="utf-8") as fh:
            ref = {r["id"]: r["hypothesis"] for r in csv.DictReader(fh)}

    log = lambda m: print(m, flush=True)
    results = {}
    for engine, device in a.runs:
        log(f"\n== {engine} {device} ==")
        results[f"{engine}:{device}"] = run_one(engine, device, clips, ref, a, log)

    ref_rows = [ref[c["id"]] for c in clips if c["id"] in ref]
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "generator": "scripts/benchmark_asr.py",
        "clips": len(clips),
        "audio_seconds": round(sum(c["duration_s"] for c in clips), 2),
        "settings": {"model": a.model, "ov_dir": str(a.ov_dir.relative_to(ROOT))
                     if a.ov_dir.is_relative_to(ROOT) else str(a.ov_dir),
                     "language": a.language, "tokens_per_second": a.tokens_per_second,
                     "tokens_base": transcribe.TOKENS_BASE,
                     "max_new_tokens_ceiling": transcribe.MAX_NEW_TOKENS},
        "definitions": {
            "timestamps": "timestamped decoding; chunks starting at or after the clip end dropped; "
                          "max_new_tokens = tokens_base + tokens_per_second * clip seconds",
            "plain": "plain decoding (no timestamps); same max_new_tokens cap",
            "total_rtf": "sum of ASR seconds / sum of audio seconds (below 1 is faster than real time)",
            "mean_rtf": "mean of per-clip ASR seconds / clip seconds",
            "timing": "wall clock per clip, model already loaded, after one uncounted warm-up clip",
            "collapse_count": "more than 6 words and under 35% distinct (scripts/view_results.py)",
            "agreement": "character-level similarity to data/asr_paza.csv, 1 - Levenshtein distance / "
                         "longer length, after case-folding and collapsing whitespace",
            "reference": "data/asr_paza.csv: torch, timestamped decoding with end-of-clip "
                         "truncation and no token cap",
        },
        "reference": {"file": str(a.reference.relative_to(ROOT)) if a.reference.is_relative_to(ROOT)
                      else str(a.reference),
                      "n": len(ref_rows), "collapse_count": sum(collapsed(t) for t in ref_rows)},
        "environment": {"platform": platform.platform(), "cpu_count": os.cpu_count(),
                        "openvino_devices": device_names(), "packages": versions()},
        "runs": results,
    }
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print("\n" + table(results))
    print(f"\nreference {out['reference']['file']}: {out['reference']['collapse_count']} collapsed "
          f"of {out['reference']['n']}")
    print(f"wrote {a.out} (aggregates) and {a.clips_dir}/ (per-clip transcripts, gitignored)")


if __name__ == "__main__":
    main()
