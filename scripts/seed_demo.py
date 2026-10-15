"""Create a complete 40-response demo interview without re-running Whisper.

Reads the saved ASR output (data/asr_paza.csv) and the matching clips in
data/audio_16k/, and writes one interview whose responses are all marked
transcribed, ready for review and assessment in the dashboard.

    python scripts/seed_demo.py

Idempotent: it ensures one open demo interview holds every row of the CSV.
A second run changes nothing; a run after a response was deleted restores
only that response; a run after the demo was assessed (assessments are
immutable) starts a fresh demo interview.

Audio is copied into data/uploads/<interview_id>/ like any upload, so
re-recording in the dashboard deletes the copy, never the corpus file.
"""
from __future__ import annotations

import argparse, csv, shutil, sys
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
            iv = Interview(applicant=Applicant(name=name))
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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", type=Path, default=config.DATA_DIR / "asr_paza.csv")
    ap.add_argument("--audio", type=Path, default=config.DATA_DIR / "audio_16k")
    ap.add_argument("--name", default=DEMO_NAME, help="applicant name that marks the demo")
    ap.add_argument("--asr-model", default=CSV_ASR_MODEL,
                    help="model that produced the CSV, stored as provenance")
    a = ap.parse_args()

    try:
        res = seed(a.csv, a.audio, a.name, a.asr_model)
    except (OSError, ValueError, KeyError) as e:
        sys.exit(f"seed failed, nothing written: {e}")

    if res.created:
        print(f"created demo interview {res.interview_id} with {res.added} responses")
    elif res.added:
        print(f"demo interview {res.interview_id}: restored {res.added} missing responses")
    else:
        print(f"demo interview {res.interview_id} already complete; nothing to do")
    print(f"  {res.total} responses, database {config.DB_PATH}")


if __name__ == "__main__":
    main()
