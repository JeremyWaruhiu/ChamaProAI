"""Create the demo interviews without re-running Whisper.

1. The Kikuyu demo (question set v1, live): reads the saved ASR output
   (data/asr_paza.csv) and the matching clips in data/audio_16k/, and writes
   one interview whose 40 responses are all marked transcribed.
2. An English practice interview (question set v2, practice) for a fictional
   applicant: the applicant form filled in and all eight answers typed. Needs
   no audio, so it can be seeded on any machine.

Both are ready for review and assessment in the dashboard.

    python scripts/seed_demo.py
    python scripts/seed_demo.py --practice-only    # without the audio corpus

Idempotent: it ensures one open demo interview holds every row of the CSV,
and one open practice interview holds every typed answer.
A second run changes nothing; a run after a response was deleted restores
only that response; a run after the demo was assessed (assessments are
immutable) starts a fresh demo interview.

Audio is copied into data/uploads/<interview_id>/ like any upload, so
re-recording in the dashboard deletes the copy, never the corpus file.
"""
from __future__ import annotations

import argparse, csv, json, shutil, sys
from dataclasses import dataclass
from pathlib import Path

import soundfile as sf
from sqlalchemy import select

from chamapro import config
from chamapro.api.db import (Applicant, Interview, Response, SessionLocal,
                             init_db, utcnow)

DEMO_NAME = "Demo applicant (S01)"
# The model that produced data/asr_paza.csv, recorded as each row's provenance.
CSV_ASR_MODEL = "microsoft/paza-whisper-large-v3-turbo"

# The practice applicant is invented: no real person's details.
PRACTICE_NAME = "Practice: Mary Wambui (fictional)"
PRACTICE_FORM = {"age": 38, "sex": "female", "education": 4,   # Secondary completed
                 "marital_status": "married"}
# One typed English answer per v2 question, keyed by its order.
PRACTICE_ANSWERS = {
    1: "There are five of us at home: my husband, me and our three children. "
       "Two of the children are in school, and the youngest is three, so one is under five.",
    2: "My main income is selling milk from our two dairy cows to the cooperative. "
       "In a normal month the household earns about 18,000 shillings altogether.",
    3: "My husband does casual work on building sites, and my sister in Nairobi sometimes "
       "sends us money. About 12,000 shillings a month comes from farming: the milk and "
       "some vegetables.",
    4: "Yes. We have the two cows and some goats, and we keep maize in the store after the "
       "harvest. We also own the land our house is on.",
    5: "This year we bought a dairy goat and put new iron sheets on the kitchen roof. "
       "We did not buy any land or equipment.",
    6: "Yes, once. I guaranteed a friend's SACCO loan and she stopped paying, so I lost "
       "5,000 shillings from my deposits. It was a SACCO loan, not a chama loan.",
    7: "Yes. I took a SACCO loan to buy the cows and finished repaying it last year.",
    8: "Yes, I have a small loan from my chama now, which I am still repaying.",
}


@dataclass
class Seeded:
    interview_id: int
    created: bool       # a new interview was made
    added: int          # responses written this run
    total: int          # responses the interview now holds


def read_rows(csv_path: Path, audio_dir: Path) -> list[dict]:
    """CSV rows with their source clip; refuses if any clip is missing."""
    with csv_path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    if not rows:
        raise ValueError(f"{csv_path} has no rows")
    for r in rows:
        r["sentence_no"] = int(r["sentence_no"])
        r["audio"] = audio_dir / f"{r['id']}.wav"
    missing = [r["audio"].name for r in rows if not r["audio"].exists()]
    if missing:
        raise FileNotFoundError(f"{len(missing)} clip(s) missing from {audio_dir}: "
                                + ", ".join(missing[:5]))
    nos = [r["sentence_no"] for r in rows]
    if len(set(nos)) != len(nos):
        raise ValueError(f"{csv_path} repeats a sentence_no")
    return rows


def seed(csv_path: Path, audio_dir: Path, name: str = DEMO_NAME,
         asr_model: str = CSV_ASR_MODEL) -> Seeded:
    rows = read_rows(csv_path, audio_dir)
    init_db()
    copied: list[Path] = []
    with SessionLocal() as db:
        iv = db.scalars(select(Interview).join(Applicant)
                        .where(Applicant.name == name, Interview.status == "open")
                        .order_by(Interview.id.desc())).first()
        created = iv is None
        if created:
            iv = Interview(applicant=Applicant(name=name), question_set="v1",
                           language="kik", mode="live")
            db.add(iv)
            db.flush()

        have = {r.sentence_no for r in iv.responses}
        todo = [r for r in rows if r["sentence_no"] not in have]
        folder = config.UPLOADS_DIR / str(iv.id)
        try:
            now = utcnow()
            for r in todo:
                resp = Response(
                    interview_id=iv.id, sentence_no=r["sentence_no"],
                    domain=r["domain"] or None, audio_path="",
                    duration_s=round(sf.info(str(r["audio"])).duration, 2),
                    status="transcribed", transcript=r["hypothesis"],
                    transcript_asr=r["hypothesis"], asr_model=asr_model,
                    asr_seconds=float(r["asr_seconds"]) if r.get("asr_seconds") else None,
                    transcribed_at=now)
                db.add(resp)
                db.flush()
                dst = folder / f"response_{resp.id}_s{r['sentence_no']:02d}.wav"
                folder.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(r["audio"], dst)
                copied.append(dst)
                resp.audio_path = str(dst)
            db.commit()
        except BaseException:
            db.rollback()
            for p in copied:
                p.unlink(missing_ok=True)
            raise
        return Seeded(iv.id, created, len(todo), len(have) + len(todo))


def seed_practice(name: str = PRACTICE_NAME) -> Seeded:
    """The English practice interview: form filled, every v2 answer typed."""
    questions = {q["order"]: q for q in json.loads(config.QUESTIONS_PATH.read_text(encoding="utf-8"))
                 if q["version"] == "v2"}
    if sorted(questions) != sorted(PRACTICE_ANSWERS):
        raise ValueError("practice answers do not match question set v2")
    init_db()
    with SessionLocal() as db:
        iv = db.scalars(select(Interview).join(Applicant)
                        .where(Applicant.name == name, Interview.status == "open",
                               Interview.mode == "practice")
                        .order_by(Interview.id.desc())).first()
        created = iv is None
        if created:
            iv = Interview(applicant=Applicant(name=name, **PRACTICE_FORM), question_set="v2",
                           language="en", mode="practice")
            db.add(iv)
            db.flush()
        have = {r.sentence_no for r in iv.responses}
        todo = [n for n in sorted(PRACTICE_ANSWERS) if n not in have]
        for n in todo:
            db.add(Response(interview_id=iv.id, sentence_no=n, domain=questions[n]["topic"],
                            source="typed", audio_path="", status="transcribed",
                            transcript=PRACTICE_ANSWERS[n]))
        db.commit()
        return Seeded(iv.id, created, len(todo), len(have) + len(todo))


def report(kind: str, res: Seeded) -> None:
    if res.created:
        print(f"created {kind} interview {res.interview_id} with {res.added} responses")
    elif res.added:
        print(f"{kind} interview {res.interview_id}: restored {res.added} missing responses")
    else:
        print(f"{kind} interview {res.interview_id} already complete; nothing to do")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, default=config.DATA_DIR / "asr_paza.csv")
    ap.add_argument("--audio", type=Path, default=config.DATA_DIR / "audio_16k")
    ap.add_argument("--name", default=DEMO_NAME, help="applicant name that marks the demo")
    ap.add_argument("--asr-model", default=CSV_ASR_MODEL,
                    help="model that produced the CSV, stored as provenance")
    ap.add_argument("--practice-only", action="store_true",
                    help="seed only the English practice interview (no audio corpus needed)")
    a = ap.parse_args()

    if not a.practice_only:
        try:
            res = seed(a.csv, a.audio, a.name, a.asr_model)
        except (OSError, ValueError, KeyError) as e:
            sys.exit(f"seed failed, nothing written: {e}")
        report("demo", res)
        print(f"  {res.total} responses, database {config.DB_PATH}")

    res = seed_practice()
    report("practice", res)
    print(f"  {res.total} typed English answers, database {config.DB_PATH}")


if __name__ == "__main__":
    main()
