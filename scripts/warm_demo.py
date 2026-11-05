"""Get a live demonstration ready: every line the bot will say to Wanjiru and Njeri, amounts
included, goes into data/tts_cache, and Paza transcribes one corpus clip.

    python scripts/warm_demo.py
    python scripts/warm_demo.py --source <another demo database>

Everything runs on a temporary copy of the demo database: data/demo.db itself is copied, never
opened, and its hash is checked at the end. Each conversation runs through service.reply, the
code the API runs, and is then undone with the admin's reset. Nothing reaches Gemini: only the
parsers read the answers, so the timings are without it. The first pass fills the cache and the
second measures it; a line the second pass has to make is an error.

Run it with the server stopped, or it may copy a database that is being written.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
ap.add_argument("--source", type=Path, default=ROOT / "data" / "demo.db", help="the demo database to copy")
ap.add_argument("--no-speech", action="store_true", help="check the script only: nothing is spoken or cached")
ap.add_argument("--no-asr", action="store_true", help="leave Paza alone")
args = ap.parse_args()
if not args.source.is_file():
    sys.exit(f"no demo database at {args.source}: build one with scripts/seed_demo.py --demo-db")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


source_hash = sha256(args.source)
_tmp = tempfile.TemporaryDirectory(prefix="chamapro-warm-")
scratch = Path(_tmp.name)
copy = scratch / "demo.db"
shutil.copy2(args.source, copy)
if args.source.with_name(args.source.name + "-wal").is_file():
    shutil.copy2(args.source.with_name(args.source.name + "-wal"), scratch / "demo.db-wal")

# Before chamapro is imported: config reads these once, and .env must not choose the database.
os.environ.update(DATABASE_URL=f"sqlite:///{copy}", CHAMAPRO_DB=str(copy), STORAGE_BACKEND="local",
                  CHAMAPRO_UPLOADS=str(scratch / "uploads"), CONVERSATION_GEMINI_LIVE="0", ASR_WARM="0",
                  TTS_ENABLED="0" if args.no_speech else "1")

from sqlalchemy import select  # noqa: E402

from chamapro import config  # noqa: E402
from chamapro.api import pipeline as pl  # noqa: E402
from chamapro.api import presenter  # noqa: E402
from chamapro.api.db import Member, SessionLocal, User, engine, init_db  # noqa: E402
from chamapro.conversation import service, tts  # noqa: E402

if engine.url.get_backend_name() != "sqlite" or Path(engine.url.database) != copy:
    sys.exit("this script runs only on its temporary copy")

# The exact demo answers. Njeri gives no term with her request, so she hears C1 as well.
SCRIPTS = {
    ("Wanjiru Kamau", "en"): [("Yes, I agree", ["G2"]), ("Yes, that is correct", ["R1"]),
                              ("Forty thousand for a dairy cow", ["C1"]), ("Twelve months", ["CONFIRM"]),
                              ("Yes, go ahead", ["O1", "END"])],
    ("Wanjiru Kamau", "kik"): [("Ĩĩ", ["G2"]), ("Nĩ guo", ["R1"]), ("Ngũkwenda ngiri mĩrongo ĩna ngũre ng'ombe", ["C1"]),
                               ("Mĩeri ikũmi na igĩrĩ", ["CONFIRM"]), ("Ĩĩ", ["O1", "END"])],
    ("Njeri Mwangi", "en"): [("Yes, I agree", ["G2_NO_INCOME"]), ("Yes, that is correct", ["R1"]),
                             ("Sixty thousand for school fees", ["C1"]), ("Twelve months", ["C2"]),
                             ("No, it is twenty two thousand now", ["CONFIRM"]), ("Yes, go ahead", ["O2", "END"])],
    ("Njeri Mwangi", "kik"): [("Ĩĩ", ["G2_NO_INCOME"]), ("Nĩ guo", ["R1"]),
                              ("Ngũkwenda ngiri mĩrongo ĩtandatũ cia cukuru", ["C1"]), ("Mĩeri ikũmi na igĩrĩ", ["C2"]),
                              ("Aca, nĩ ngiri mĩrongo ĩĩrĩ na igĩrĩ", ["CONFIRM"]), ("Ĩĩ", ["O2", "END"])],
}
STALE = ("It looks older than the code: rebuild it with\n"
         "    STORAGE_BACKEND=local CHAMAPRO_UPLOADS=data/demo_uploads python scripts/seed_demo.py --demo-db data/demo.db --replace\n"
         "and note the new passwords it prints.")


def run_one(db, name: str, language: str, script: list, cold: bool) -> list[tuple]:
    member = db.scalar(select(Member).where(Member.full_name == name, Member.seed_tag.in_(presenter.DEMO_TAGS)))
    if member is None:
        sys.exit(f"{name} is not in {args.source} as a demo member. {STALE}")
    user = db.get(User, member.user_id)
    rows, started = [], time.perf_counter()
    conv, _ = service.start(db, member, language)
    openers = service.turns_of(db, conv)
    rows.append(("start", "G1 CONSENT", None, None, sum(t.tts_ms or 0 for t in openers), time.perf_counter() - started))
    misses = sum(t.tts_ms or 0 for t in openers)
    for words, want in script:
        started = time.perf_counter()
        spoken, bots, _ = service.reply(db, conv, member, user, text=words)
        wall = time.perf_counter() - started
        said = [t.template_id for t in bots]
        if said != want:
            sys.exit(f"{name} ({language}): after {words!r} the bot said {said}, not {want}. {STALE}")
        misses += spoken.tts_ms or 0
        rows.append((words, " ".join(said), spoken.extract_ms, spoken.evaluate_ms, spoken.tts_ms or 0, wall))
    if not cold and misses and config.TTS_ENABLED:
        sys.exit(f"{name} ({language}): the warm pass had to make speech ({misses} ms): the cache is not holding it")
    return rows


def reset(db) -> None:
    admin = db.scalar(select(User).where(User.role == "admin"))
    presenter.demo_reset(db=db, user=admin)


def show(name: str, language: str, rows: list) -> None:
    print(f"\n{name}, {language}, warm cache (ms; wall includes the database)")
    print(f"  {'understand':>10} {'decide':>7} {'speak':>6} {'wall':>7}  said    answer")
    for words, said, understand, decide, speak, wall in rows:
        print(f"  {understand if understand is not None else '-':>10} {decide if decide is not None else '-':>7} "
              f"{speak:>6} {wall * 1000:>7.0f}  {said:<14} {words}")
    print(f"  total {sum(r[5] for r in rows):.2f} s of server work across {len(rows)} steps")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    init_db()
    if config.TTS_ENABLED:
        started = time.perf_counter()
        print(f"fixed lines ready: {tts.prewarm()} in {time.perf_counter() - started:.1f} s")
    with SessionLocal() as db:
        started = time.perf_counter()
        for (name, language), script in SCRIPTS.items():
            run_one(db, name, language, script, cold=True)
            reset(db)
        print(f"first pass, filling the cache: {time.perf_counter() - started:.1f} s")
        for (name, language), script in SCRIPTS.items():
            rows = run_one(db, name, language, script, cold=False)
            show(name, language, rows)
            reset(db)
    if config.TTS_ENABLED:
        print(f"\ncached in {config.TTS_CACHE_DIR}: {len(list(config.TTS_CACHE_DIR.glob('*.mp3')))} files")
    if not args.no_asr:
        started = time.perf_counter()
        pl.load_asr()
        print(f"\nPaza: loaded in {time.perf_counter() - started:.1f} s on {pl.asr_status()['kik']['device']}")
        for attempt in ("first clip", "second clip"):
            print(f"Paza: {attempt} {pl.warm_asr()['kik']:.1f} s")
    if sha256(args.source) != source_hash:
        sys.exit(f"{args.source} changed while this ran: something else has it open")
    print(f"\n{args.source} is as it was.")
    engine.dispose()


if __name__ == "__main__":
    main()
