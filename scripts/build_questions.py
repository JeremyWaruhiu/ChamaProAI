"""Build question set v1 in src/chamapro/questions.json from docs/interview_questions.txt.

questions.json holds every question set as one list; each question has id,
version, topic, order, text_en, text_kik and features (the classifier
features it is asked for). v1 is the 40-sentence set of the recorded corpus:
English comes from the text file, each topic from data/manifest.csv so the
dashboard groups exactly as the recordings do. Later sets (v2) are edited in
questions.json directly and kept as they are. Kikuyu text already in the
file is kept, so re-running after editing the English never erases a native
speaker's translations.

    python scripts/build_questions.py
    python scripts/build_questions.py --check   # exit 1 if the JSON is stale
"""
import argparse, csv, json, re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs" / "interview_questions.txt"
MANIFEST = ROOT / "data" / "manifest.csv"
OUT = ROOT / "src" / "chamapro" / "questions.json"


def parse(text):
    """{sentence_no: english} from lines like '12. Do you have school fees?'"""
    qs = {}
    for ln in text.splitlines():
        m = re.match(r"^(\d{1,2})\.\s+(\S.*?)\s*$", ln)
        if m:
            n = int(m.group(1))
            if n in qs:
                raise ValueError(f"question {n} appears twice")
            qs[n] = m.group(2)
    return qs


VERSION = "v1"


def build(source=SOURCE, manifest=MANIFEST, existing=OUT):
    english = parse(Path(source).read_text(encoding="utf-8"))
    with Path(manifest).open(newline="", encoding="utf-8") as fh:
        domain = {int(r["sentence_no"]): r["domain"] for r in csv.DictReader(fh)
                  if r["sentence_no"]}
    if sorted(english) != sorted(domain):
        raise ValueError(f"questions {sorted(set(english) ^ set(domain))} do not match "
                         "the manifest's sentence numbers")
    current = json.loads(Path(existing).read_text(encoding="utf-8")) if Path(existing).exists() else []
    kikuyu = {q["order"]: q.get("text_kik", "") for q in current if q["version"] == VERSION}
    v1 = [{"id": f"{VERSION}-q{n:02d}", "version": VERSION, "topic": domain[n], "order": n,
           "text_en": english[n], "text_kik": kikuyu.get(n, ""), "features": []}
          for n in sorted(english)]
    return v1 + [q for q in current if q["version"] != VERSION]


def render(questions):
    return json.dumps(questions, indent=2, ensure_ascii=False) + "\n"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="verify only; write nothing")
    a = ap.parse_args()
    try:
        out = render(build())
    except (OSError, ValueError) as e:
        sys.exit(f"build failed: {e}")
    current = OUT.read_text(encoding="utf-8") if OUT.exists() else ""
    if a.check:
        sys.exit(0 if out == current else f"{OUT.name} is out of date; run build_questions.py")
    OUT.write_text(out, encoding="utf-8")
    print(f"wrote {len(json.loads(out))} questions -> {OUT}")


if __name__ == "__main__":
    main()
