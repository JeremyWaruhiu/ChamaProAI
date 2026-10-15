"""Convert interview recordings to 16 kHz mono WAV and build the manifest.

Importable: convert() and domain_for() are reused by the API upload path.
"""
import argparse, csv, re, sys
from pathlib import Path
import librosa, soundfile as sf

MANIFEST = Path("data/manifest.csv")
WAV_DIR = Path("data/audio_16k")
COLUMNS = ["id","speaker","sentence_no","condition","path",
           "kikuyu_ref","english_ref","domain","duration_s"]
SUFFIXES = {".m4a",".wav",".mp3",".ogg",".opus",".flac",".aac",".webm"}
DOMAINS = [(1,5,"household"),(6,10,"income"),(11,15,"expenditure"),
           (16,20,"assets"),(21,25,"debt_repayment"),(26,30,"sacco_history"),
           (31,35,"chama"),(36,40,"intent_planning")]

def domain_for(n):
    for lo, hi, name in DOMAINS:
        if n and lo <= n <= hi: return name
    return ""

def convert(src, dst):
    """Write src as 16 kHz mono PCM_16 WAV at dst; return its duration in s."""
    w, _ = librosa.load(str(src), sr=16000, mono=True)
    Path(dst).parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(dst), w, 16000, subtype="PCM_16")
    return round(len(w)/16000, 2)

def number(name):
    m = re.search(r"(\d{1,3})(?!.*\d)", Path(name).stem)
    return int(m.group(1)) if m else None

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--in", dest="src", type=Path, required=True)
    p.add_argument("--speaker", required=True)
    p.add_argument("--condition", default="clean")
    a = p.parse_args()

    files = sorted(f for f in a.src.iterdir() if f.suffix.lower() in SUFFIXES)
    if not files: sys.exit(f"no audio in {a.src}")

    rows = []
    if MANIFEST.exists():
        with MANIFEST.open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
    seen = {r["id"] for r in rows}

    for f in files:
        n = number(f.name)
        cid = f"{a.speaker}_{a.condition}_{n:03d}" if n else f"{a.speaker}_{a.condition}_{f.stem}"
        if cid in seen:
            print(f"  skip {f.name}"); continue
        out = WAV_DIR / f"{cid}.wav"
        try:
            dur = convert(f, out)
        except Exception as e:
            print(f"  FAIL {f.name}: {e}"); continue
        rows.append({"id":cid,"speaker":a.speaker,"sentence_no":n or "",
                     "condition":a.condition,"path":str(out),"kikuyu_ref":"",
                     "english_ref":"","domain":domain_for(n),
                     "duration_s":dur})
        print(f"  ok   {f.name} -> {out.name} ({rows[-1]['duration_s']}s)")

    rows.sort(key=lambda r: r["id"])
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("w", newline="", encoding="utf-8") as fh:
        wtr = csv.DictWriter(fh, fieldnames=COLUMNS); wtr.writeheader(); wtr.writerows(rows)

    total = sum(float(r["duration_s"] or 0) for r in rows)
    print(f"\n{len(rows)} clips, {total/60:.1f} minutes -> {MANIFEST}")

if __name__ == "__main__":
    main()
