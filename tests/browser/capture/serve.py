"""The capture server: the seeded demo in <scratch>/capture.db, whatever .env says. SQLite and
local audio only, Supabase blanked, the Kikuyu ASR not loaded (every answer is typed), and the
bot's speech from a copy of data/tts_cache. Gemini is off unless --gemini-live, which takes the
key from .env and lets it read each answer, as on the day.

    python tests/browser/capture/serve.py <scratch> <port> [--gemini-live]

fresh.sh starts it. New passwords each run, in <scratch>/logins.json.
"""
from __future__ import annotations

import json
import os
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
scratch, port = Path(sys.argv[1]).resolve(), int(sys.argv[2])
live = "--gemini-live" in sys.argv[3:]
db_path = scratch / "capture.db"
os.environ.update(DATABASE_URL=f"sqlite:///{db_path}", CHAMAPRO_DB=str(db_path), STORAGE_BACKEND="local",
                  CHAMAPRO_UPLOADS=str(scratch / "uploads"), SUPABASE_URL="", SUPABASE_SERVICE_ROLE_KEY="",
                  GOOGLE_CLIENT_ID="", HF_TOKEN="", KHAYA_API_KEY="", ASR_WARM="0", HF_HUB_OFFLINE="1",
                  TRANSFORMERS_OFFLINE="1", TTS_CACHE_DIR=str(scratch / "tts_cache"), CHAMAPRO_COOKIE_SECURE="0",
                  CHAMAPRO_FRONTEND_DIST=str(ROOT / "frontend" / "dist"),
                  CONVERSATION_GEMINI_LIVE="1" if live else "0")
if not live:
    os.environ.update(GEMINI_API_KEY="", GOOGLE_API_KEY="")

from sqlalchemy import select  # noqa: E402

from chamapro import config  # noqa: E402

if config.DATABASE_URL != f"sqlite:///{db_path}" or config.STORAGE_BACKEND != "local" or config.SUPABASE_URL:
    sys.exit("the capture server runs only on its own scratch database, with local audio")
if live and not config.GEMINI_API_KEY:
    sys.exit("--gemini-live needs GEMINI_API_KEY in .env")
if not live and (config.GEMINI_API_KEY or config.CONVERSATION_GEMINI_LIVE):
    sys.exit("without --gemini-live nothing may reach Gemini")

import uvicorn  # noqa: E402

from chamapro.api import auth  # noqa: E402
from chamapro.api import pipeline as pl  # noqa: E402
from chamapro.api.db import SessionLocal, User, init_db  # noqa: E402
from chamapro.api.main import app  # noqa: E402

init_db()
logins = {}
with SessionLocal() as db:
    for name in ("w.kamau", "n.mwangi", "j.mwangi", "s.achieng"):
        user = db.scalar(select(User).where(User.username == name))
        logins[name] = secrets.token_urlsafe(12)
        user.password_hash = auth.hash_password(logins[name])
    db.commit()
(scratch / "logins.json").write_text(json.dumps(logins))
(scratch / "server.json").write_text(json.dumps({"port": port, "gemini_live": live}))

pl.load_asr = lambda: None
uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
