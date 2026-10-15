"""Translate Kikuyu -> English and extract financial signals via Gemini."""
import argparse, csv, json, os, re, sys, time
from pathlib import Path
from dotenv import load_dotenv
load_dotenv(override=True)
import requests

KEY = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
MODEL = os.getenv("GEMINI_MODEL", "gemini-3.8-flash")
URL = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
OUT = Path("data/translation_output.csv")

PROMPT = """You are helping assess a loan application at a Kenyan SACCO.
Below are numbered responses spoken in Kikuyu by one applicant. The Kikuyu was
transcribed by a speech model with no Kikuyu training, so spelling and word
boundaries are unreliable; interpret phonetically where needed.

For each, return:
  n        the response number, exactly as given
  english  a faithful English translation, no embellishment. If the input is
           unintelligible, return "" rather than guessing.
  signals  any financial or behavioural facts stated, as short strings;
           [] if none. Record only what is said, never an inference.

Return ONLY a JSON array, no prose, no code fences.

Responses:
{body}"""

def call(prompt, tries=5, timeout=300):
    for i in range(1, tries + 1):
        try:
            r = requests.post(URL, headers={"x-goog-api-key": KEY,
                              "Content-Type": "application/json"},
                              json={"contents": [{"parts": [{"text": prompt}]}],
                                    "generationConfig": {"temperature": 0}},
                              timeout=timeout)
        except requests.exceptions.RequestException as e:
            if i == tries: raise
            w = 2 ** i
            print(f"    network: {type(e).__name__}, retry {i}/{tries-1} in {w}s")
            time.sleep(w); continue
        if r.status_code == 200:
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        if r.status_code in (429, 500, 502, 503) and i < tries:
            w = 2 ** i
            print(f"    {r.status_code}, retry {i}/{tries-1} in {w}s")
            time.sleep(w); continue
        raise RuntimeError(f"{r.status_code}: {r.text[:300]}")

def parse(raw):
    raw = re.sub(r"^```(?:json)?|```$", "", raw.strip(), flags=re.M).strip()
    return json.loads(raw)

ap = argparse.ArgumentParser()
ap.add_argument("--source", choices=["asr", "ref"], default="asr")
ap.add_argument("--limit", type=int, default=0)
ap.add_argument("--chunk", type=int, default=10,
                help="responses per request; 0 = all in one")
a = ap.parse_args()

if not KEY: sys.exit("no GEMINI_API_KEY in .env")

if a.source == "asr":
    src = Path("data/asr_output.csv")
    if not src.exists(): sys.exit("run transcribe.py first")
    rows = [(r["sentence_no"], r["hypothesis"], r["id"])
            for r in csv.DictReader(src.open(newline="", encoding="utf-8"))]
else:
    rows = [(r["sentence_no"], r["kikuyu_ref"], r["id"])
            for r in csv.DictReader(Path("data/manifest.csv").open(newline="", encoding="utf-8"))
            if r["kikuyu_ref"].strip()]
    if not rows: sys.exit("kikuyu_ref column is empty")

if a.limit: rows = rows[:a.limit]
size = a.chunk if a.chunk > 0 else len(rows)
chunks = [rows[i:i+size] for i in range(0, len(rows), size)]
print(f"source={a.source} model={MODEL} n={len(rows)} requests={len(chunks)}")

by_n, t0 = {}, time.time()
for ci, ch in enumerate(chunks, 1):
    body = "\n".join(f"{n}. {t}" for n, t, _ in ch)
    t = time.time()
    try:
        parsed = parse(call(PROMPT.format(body=body)))
    except json.JSONDecodeError:
        print(f"  chunk {ci}: unparseable, skipped"); continue
    except Exception as e:
        print(f"  chunk {ci}: FAILED {type(e).__name__}"); continue
    for d in parsed:
        by_n[str(d.get("n"))] = d
    print(f"  chunk {ci}/{len(chunks)}: {len(parsed)} responses in {time.time()-t:.0f}s")

OUT.parent.mkdir(parents=True, exist_ok=True)
with OUT.open("w", newline="", encoding="utf-8") as fh:
    w = csv.DictWriter(fh, fieldnames=["id","sentence_no","kikuyu_in","english_out","signals"])
    w.writeheader()
    for n, t, cid in rows:
        d = by_n.get(str(n), {})
        w.writerow({"id": cid, "sentence_no": n, "kikuyu_in": t,
                    "english_out": d.get("english", ""),
                    "signals": "; ".join(d.get("signals", []))})
print(f"\n{len(by_n)}/{len(rows)} translated in {time.time()-t0:.0f}s -> {OUT}")
