"""The Kikuyu translation, as one spreadsheet a translator can fill in.

    python scripts/translations.py export      # writes translations/kikuyu.csv
    python scripts/translations.py import      # reads it back

export lists everything a member reads in a Kikuyu conversation: each bot line (templates.yaml),
the chat screen and outcome card (strings.ts, t.chat), the Why sentences (member_text.py) and the
Yes and No buttons, with where it appears, the English, its slots and a Kikuyu column. Anything
already translated in those places stays filled in.

import checks that every {slot} in the English is in the Kikuyu and that the Kikuyu has no other,
and writes nothing at all if not. Then it writes three files: the kik entries of templates.yaml,
frontend/src/strings.kik.json (the chat, when the language is Gikuyu) and
src/chamapro/api/member_text_kik.json. A row left empty stays in English, as now, and is reported.

Numbers: a bot line's numbers go into its slots as Kikuyu words; screen text and Why sentences keep
figures. A slot's format, as in {amount:,}, can be dropped or kept. Changing CONSENT changes the
version a member's consent is stored with, which is what it is for. Rebuild the frontend, and run
scripts/warm_demo.py again: new words need new speech.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import string
import sys
from dataclasses import dataclass
from pathlib import Path

import yaml

from chamapro.api import member_text
from chamapro.conversation import templates

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "translations" / "kikuyu.csv"
STRINGS_TS = ROOT / "frontend" / "src" / "strings.ts"
STRINGS_KIK = ROOT / "frontend" / "src" / "strings.kik.json"
COLUMNS = ("id", "where", "english", "slots", "kikuyu")
BOT, SCREEN, WHY, BUTTON = "bot speech", "screen text", "Why sentence", "button"
# Shown before anyone has chosen a language, so they cannot depend on it.
BEFORE_CHOOSING = {"chat.chooseLanguage", "chat.chooseLead", "chat.kikuyu", "chat.english", "chat.starting", "chat.startFailed"}
# Spoken as the member's answer and read by lexicon.py: these two take their words from the Yes and No rows.
BUTTONS = {"button.yes": "Yes", "button.no": "No"}
MONTHS = {"chat.months.one": "{n} month", "chat.months.many": "{n} months"}


@dataclass
class Row:
    id: str
    where: str
    english: str
    kikuyu: str = ""

    @property
    def slots(self) -> set[str]:
        return slots_of(self.english)


def slots_of(text: str) -> set[str]:
    return {name for _, name, _, _ in string.Formatter().parse(text) if name}


def chat_strings(path: Path = STRINGS_TS) -> dict[str, str]:
    """The string leaves of t.chat, by dotted id. A small reader of that one object: a test
    on the frontend's side holds it to what the object really holds."""
    source = path.read_text(encoding="utf-8")
    start = source.index("\n  chat: {") + len("\n  chat: {")
    token = re.compile(r"(\w+):\s*(?:'((?:[^'\\]|\\.)*)'|(\{)|\([^)]*\)\s*=>[^\n]*)|(\})")
    out, path_now, i = {}, ["chat"], start
    while True:
        m = token.search(source, i)
        if m is None:
            raise ValueError("t.chat has no end in strings.ts")
        i = m.end()
        if m[4]:
            if len(path_now) == 1:
                return out
            path_now.pop()
        elif m[3]:
            path_now.append(m[1])
        elif m[2] is not None:
            out[".".join([*path_now, m[1]])] = m[2].replace("\\'", "'")


def current_kikuyu() -> tuple[dict, dict, dict]:
    table = templates.load()
    strings = json.loads(STRINGS_KIK.read_text(encoding="utf-8")) if STRINGS_KIK.is_file() else {}
    return table, strings, member_text.kikuyu()


def rows() -> list[Row]:
    table, strings, why = current_kikuyu()
    out = [Row(f"template.{tid}", BUTTON if tid.startswith("ACTION_") else BOT, e["en"], e["kik"] or "") for tid, e in table.items()]
    leaves = chat_strings()
    out += [Row(k, SCREEN, v, strings.get(k, "")) for k, v in leaves.items()
            if k not in BEFORE_CHOOSING and not k.startswith(("chat.yes.", "chat.no."))]
    out += [Row(k, SCREEN, v, strings.get(k, "")) for k, v in MONTHS.items()]
    out += [Row(k, BUTTON, v, strings.get(k, "")) for k, v in BUTTONS.items()]
    out += [Row(k, WHY, v, why.get(k, "")) for k, v in member_text.catalogue()]
    return out


def export(path: Path = CSV_PATH) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    table = rows()
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(COLUMNS)
        for r in table:
            w.writerow([r.id, r.where, r.english, " ".join(sorted(r.slots)), r.kikuyu])
    return len(table)


@dataclass
class Checked:
    translated: dict[str, str]
    missing: list[str]
    problems: list[str]


def read_filled(path: Path = CSV_PATH) -> Checked:
    known = {r.id: r for r in rows()}
    with path.open(newline="", encoding="utf-8-sig") as fh:     # a spreadsheet may add the BOM
        reader = csv.DictReader(fh)
        if set(COLUMNS) - set(reader.fieldnames or ()):
            raise ValueError(f"{path} needs the columns {', '.join(COLUMNS)}")
        filled = list(reader)
    out, problems = {}, []
    for row in filled:
        rid, words = row["id"], (row["kikuyu"] or "").strip()
        expected = known.get(rid)
        if expected is None:
            problems.append(f"{rid}: no such line now; export again")
            continue
        if not words:
            continue
        try:
            found = slots_of(words)
        except ValueError as e:
            problems.append(f"{rid}: a brace does not close: {e}")
            continue
        if expected.slots - found:
            problems.append(f"{rid}: missing {', '.join('{' + s + '}' for s in sorted(expected.slots - found))}")
        if found - expected.slots:
            problems.append(f"{rid}: has {', '.join('{' + s + '}' for s in sorted(found - expected.slots))}, which the English does not")
        if row["english"] != expected.english:
            problems.append(f"{rid}: the English has changed since this was exported; check the translation and export again")
        out[rid] = words
    seen = {r["id"] for r in filled}
    return Checked(out, [k for k in known if k not in out or k not in seen], problems)


def write_templates(translated: dict[str, str], path: Path = templates.PATH) -> None:
    """Only the kik lines change: the comments, the order and the English stay as they are."""
    lines, current = path.read_text(encoding="utf-8").splitlines(), None
    for i, line in enumerate(lines):
        if m := re.fullmatch(r"(\w+):", line):
            current = m[1]
        elif line.startswith("  kik:") and current:
            words = translated.get(f"template.{current}", "")
            lines[i] = "  kik: " + json.dumps(words, ensure_ascii=False)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    templates.check(yaml.safe_load(path.read_text(encoding="utf-8")))       # refuses at once if it no longer reads


def write_json(path: Path, values: dict[str, str]) -> None:
    path.write_text(json.dumps(values, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")


def import_filled(csv_path: Path = CSV_PATH) -> int:
    checked = read_filled(csv_path)
    if checked.problems:
        print(f"{len(checked.problems)} line(s) cannot go in, and nothing was written:", file=sys.stderr)
        for p in checked.problems:
            print(f"  {p}", file=sys.stderr)
        return 1
    t = checked.translated
    write_templates(t)
    write_json(STRINGS_KIK, {k: v for k, v in t.items() if k.startswith(("chat.", "button."))})
    write_json(member_text.KIKUYU_PATH, {k: v for k, v in t.items() if k.startswith("why.")})
    print(f"{len(t)} translated; {len(checked.missing)} still in English"
          + (": " + ", ".join(checked.missing[:12]) + (" ..." if len(checked.missing) > 12 else "") if checked.missing else ""))
    print("Now: cd frontend && npm run build; python scripts/warm_demo.py")
    return 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=["export", "import"])
    ap.add_argument("--csv", type=Path, default=CSV_PATH)
    a = ap.parse_args()
    if a.what == "export":
        print(f"{export(a.csv)} lines in {a.csv}")
        return 0
    return import_filled(a.csv)


if __name__ == "__main__":
    sys.exit(main())
