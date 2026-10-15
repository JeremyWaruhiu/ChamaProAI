"""Run an ASR model over the manifest clips and write hypotheses.

Importable: load_asr() builds the pipeline once, transcribe_clip() runs it on
one file. The API holds a single loaded pipeline and calls transcribe_clip().
"""
import argparse, csv, os, time
from pathlib import Path
from dotenv import load_dotenv
import soundfile as sf
import torch
from transformers import pipeline

MANIFEST = Path("data/manifest.csv")


def device():
    return 0 if torch.cuda.is_available() else -1


def load_asr(model_name):
    """Load the ASR pipeline. Slow; do it once and reuse the result."""
    return pipeline("automatic-speech-recognition", model=model_name, device=device())


def transcribe_clip(path, model, language, duration=None):
    """Transcribe one clip with a loaded pipeline -> {text, seconds}.

    Chunks timestamped past the clip's end are dropped (decoder run-on);
    duration is read from the file when not given.
    """
    gen = {"language": language, "task": "transcribe",
           "condition_on_prev_tokens": False}
    t = time.time()
    res = model(str(path), generate_kwargs=gen, return_timestamps=True)
    dur = float(duration) if duration is not None else sf.info(str(path)).duration
    keep = [c["text"] for c in res.get("chunks", [])
            if c.get("timestamp") and c["timestamp"][0] is not None
            and c["timestamp"][0] < dur]
    txt = ("".join(keep) if keep else res["text"]).strip()
    return {"text": txt, "seconds": round(time.time()-t, 2)}


def main():
    load_dotenv(override=True)
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="only first N clips")
    ap.add_argument("--model", default=os.getenv("ASR_MODEL", "openai/whisper-small"))
    ap.add_argument("--language", default=os.getenv("ASR_LANGUAGE", "sw"))
    ap.add_argument("--out", default="data/asr_output.csv",
                    help="output path; use a distinct file per model to compare runs")
    a = ap.parse_args()

    OUT = Path(a.out)
    with MANIFEST.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if a.limit: rows = rows[:a.limit]
    if not rows: raise SystemExit("manifest empty")

    dev = device()
    print(f"model={a.model} language={a.language} device={'gpu' if dev==0 else 'cpu'}")
    print(f"{len(rows)} clips -> {OUT}\n")

    asr = load_asr(a.model)

    out, t0 = [], time.time()
    for i, r in enumerate(rows, 1):
        p = r["path"]
        if not Path(p).exists():
            print(f"  [{i}/{len(rows)}] MISSING {p}"); continue
        try:
            res = transcribe_clip(p, asr, a.language, duration=r["duration_s"])
        except Exception as e:
            print(f"  [{i}/{len(rows)}] FAIL {r['id']}: {e}"); continue
        out.append({"id": r["id"], "sentence_no": r["sentence_no"],
                    "domain": r["domain"], "hypothesis": res["text"],
                    "asr_seconds": res["seconds"]})
        print(f"  [{i}/{len(rows)}] {r['id']}: {res['text'][:70]}")

    if not out:
        raise SystemExit("\nnothing transcribed; existing output left untouched")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    with OUT.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["id","sentence_no","domain","hypothesis","asr_seconds"])
        w.writeheader(); w.writerows(out)
    print(f"\n{len(out)} transcribed in {time.time()-t0:.0f}s -> {OUT}")


if __name__ == "__main__":
    main()
