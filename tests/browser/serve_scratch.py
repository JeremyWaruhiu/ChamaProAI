"""A real server on a scratch demo database, for tests/browser/demo_run.mjs. It builds the
database with seed_demo.py --demo-db in a folder it is given, whatever .env says, and replaces
Gemini with a stand-in, so nothing reaches Google. Speech and the Kikuyu ASR are real if the
models are on disk; ASR_FAKE=1 uses a stand-in that says what it is told.

    python tests/browser/serve_scratch.py <scratch folder> <port>

Passwords are new each run, written to <scratch folder>/logins.json.
"""
from __future__ import annotations

import json
import os
import secrets
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
scratch, port = Path(sys.argv[1]).resolve(), int(sys.argv[2])
scratch.mkdir(parents=True, exist_ok=True)
db_path = scratch / "demo.db"
os.environ.update(DATABASE_URL=f"sqlite:///{db_path}", STORAGE_BACKEND="local", CHAMAPRO_UPLOADS=str(scratch / "uploads"),
                  CONVERSATION_GEMINI_LIVE="1", GEMINI_API_KEY="", GOOGLE_API_KEY="",
                  GOOGLE_CLIENT_ID="", CHAMAPRO_FRONTEND_DIST=str(ROOT / "frontend" / "dist"))
if not db_path.exists():
    subprocess.run([sys.executable, str(ROOT / "scripts" / "seed_demo.py"), "--demo-db", str(db_path)], check=True,
                   stdout=subprocess.DEVNULL, env=os.environ)

import uvicorn  # noqa: E402
from sqlalchemy import select  # noqa: E402

from chamapro.api import auth  # noqa: E402
from chamapro.api.db import SessionLocal, User, engine, init_db  # noqa: E402
from chamapro.api.main import app  # noqa: E402
from chamapro.conversation import extract  # noqa: E402

if engine.url.get_backend_name() != "sqlite" or engine.url.database != str(db_path):
    sys.exit("this script runs only on its own scratch database")
init_db()

logins = {}
with SessionLocal() as db:
    for name in ("w.kamau", "n.mwangi", "j.mwangi", "s.achieng"):
        user = db.scalar(select(User).where(User.username == name))
        logins[name] = secrets.token_urlsafe(12)
        user.password_hash = auth.hash_password(logins[name])
    db.commit()
(scratch / "logins.json").write_text(json.dumps(logins))

# --- The stand-in for Gemini ----------------------------------------------------------------
ENGLISH = {"CONSENT": "Yes, I agree.", "G2": "Yes, that is correct.", "G2_NO_INCOME": "Yes, that is correct.",
           "R1": "I would like forty thousand shillings to buy a dairy cow.", "C1": "Over twelve months.",
           "C2": "No, it is twenty two thousand now.", "CONFIRM": "Yes, go ahead."}
FIELDS = {"CONSENT": {"answer": "yes"}, "G2": {"answer": "yes"}, "G2_NO_INCOME": {"answer": "yes"},
          "R1": {"amount_kes": 40000, "purpose_category": "livestock", "purpose_text": "a dairy cow"}, "C1": {"term_months": 12},
          "C2": {"monthly_income_kes": 22000}, "CONFIRM": {"answer": "yes"}}
misheard = []       # "60,000" is read as 66,000 once, so the run sees CHECK_AMOUNT


def stand_in(prompt: str) -> str:
    question = prompt.split("Question id: ", 1)[1].split("\n", 1)[0].strip()
    said = prompt.split("<answer>\n", 1)[1].split("\n</answer>", 1)[0].strip()
    parsed = extract.parsers(question, said, "en")
    if any(c.isdigit() for c in said) or said.lower().split()[0:1] in (["yes"], ["no"], ["over"], ["twelve"]):
        # Typed English: read what it says, and agree with the parsers but for the one slip.
        fields = dict(parsed)
        if question == "R1" and "60,000" in said and not misheard:
            misheard.append(1)
            fields["amount_kes"] = 66000
        return json.dumps({"english": said, "fields": fields, "confidence": 0.95})
    return json.dumps({"english": ENGLISH.get(question, said), "fields": FIELDS.get(question, {}), "confidence": 0.95})


extract.client = stand_in
if os.environ.get("ASR_FAKE") == "1":
    from chamapro.api import pipeline as pl

    class Says:
        def __call__(self, *a, **k):
            return {"text": "Ritwa riakwa nĩ Wanjiru", "chunks": []}
    pl.transcribe.load_asr = lambda name, *a, **k: pl.transcribe.ASR(Says(), "torch", "CPU", name)

uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
