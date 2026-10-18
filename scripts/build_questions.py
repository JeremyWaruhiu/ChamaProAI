"""Build src/chamapro/questions.json from docs/interview_questions.txt.

English comes from the text file; each question's domain comes from
data/manifest.csv so the dashboard groups exactly as the recordings do.
Kikuyu text already in questions.json is kept, so re-running after editing
the English never erases a native speaker's translations.

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


def build(source=SOURCE, manifest=MANIFEST, existing=OUT):
    english = parse(Path(source).read_text(encoding="utf-8"))
    with Path(manifest).open(newline="", encoding="utf-8") as fh:
        domain = {int(r["sentence_no"]): r["domain"] for r in csv.DictReader(fh)
                  if r["sentence_no"]}
    if sorted(english) != sorted(domain):
        raise ValueError(f"questions {sorted(set(english) ^ set(domain))} do not match "
                         "the manifest's sentence numbers")
    kikuyu = {}
    if Path(existing).exists():
        kikuyu = {q["sentence_no"]: q.get("kikuyu", "")
                  for q in json.loads(Path(existing).read_text(encoding="utf-8"))}
    return [{"sentence_no": n, "domain": domain[n], "english": english[n],
             "kikuyu": kikuyu.get(n, "")} for n in sorted(english)]


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
