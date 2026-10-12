"""Run Whisper over the manifest clips and write hypotheses."""
import argparse, csv, os, time
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(override=True)
import torch
from transformers import pipeline

MANIFEST = Path("data/manifest.csv")
OUT = Path("data/asr_output.csv")

ap = argparse.ArgumentParser()
ap.add_argument("--limit", type=int, default=0, help="only first N clips")
ap.add_argument("--model", default=os.getenv("ASR_MODEL", "openai/whisper-small"))
ap.add_argument("--language", default=os.getenv("ASR_LANGUAGE", "sw"))
a = ap.parse_args()

with MANIFEST.open(newline="", encoding="utf-8") as fh:
    rows = list(csv.DictReader(fh))
if a.limit: rows = rows[:a.limit]
if not rows: raise SystemExit("manifest empty")

dev = 0 if torch.cuda.is_available() else -1
print(f"model={a.model} language={a.language} device={'gpu' if dev==0 else 'cpu'}")
print(f"{len(rows)} clips\n")

asr = pipeline("automatic-speech-recognition", model=a.model, device=dev)
gen = {"language": a.language, "task": "transcribe"}

out = []
t0 = time.time()
for i, r in enumerate(rows, 1):
    p = r["path"]
    if not Path(p).exists():
        print(f"  [{i}/{len(rows)}] MISSING {p}"); continue
    t = time.time()
    try:
        txt = asr(p, generate_kwargs=gen)["text"].strip()
    except Exception as e:
        print(f"  [{i}/{len(rows)}] FAIL {r['id']}: {e}"); continue
    out.append({"id": r["id"], "sentence_no": r["sentence_no"],
                "domain": r["domain"], "hypothesis": txt,
                "asr_seconds": round(time.time()-t, 2)})
    print(f"  [{i}/{len(rows)}] {r['id']}: {txt[:70]}")

OUT.parent.mkdir(parents=True, exist_ok=True)
with OUT.open("w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=["id","sentence_no","domain","hypothesis","asr_seconds"])
    w.writeheader(); w.writerows(out)
print(f"\n{len(out)} transcribed in {time.time()-t0:.0f}s -> {OUT}")
