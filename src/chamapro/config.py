"""Central configuration: loads .env once and exposes keys and paths.

Every other module imports from here instead of calling os.getenv itself,
so there is exactly one place that knows where secrets and data live.
"""
from __future__ import annotations

import os
from datetime import date, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from dotenv import load_dotenv

# --- Paths -------------------------------------------------------------------
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
EXPERIMENTS_DIR = PROJECT_ROOT / "experiments"
HF_CACHE_DIR = PROJECT_ROOT / ".hf_cache"

# --- Environment -------------------------------------------------------------
# load_dotenv is a no-op if .env doesn't exist, so tests / CI without secrets
# still import cleanly; individual keys are checked when they're actually used.
load_dotenv(PROJECT_ROOT / ".env")

# Keep HF downloads inside the project unless the user has set HF_HOME.
# Must be set before transformers/datasets are imported anywhere.
os.environ.setdefault("HF_HOME", str(HF_CACHE_DIR))

GOOGLE_API_KEY: str | None = os.getenv("GOOGLE_API_KEY") or None
HF_TOKEN: str | None = os.getenv("HF_TOKEN") or None
KHAYA_API_KEY: str | None = os.getenv("KHAYA_API_KEY") or None

# --- Pipeline ----------------------------------------------------------------
# Same precedence the scripts use: a dedicated Gemini key, else the AI Studio key.
GEMINI_API_KEY: str | None = os.getenv("GEMINI_API_KEY") or GOOGLE_API_KEY
# None lets each pipeline stage fall back to its own default model.
GEMINI_MODEL: str | None = os.getenv("GEMINI_MODEL") or None
def _project_path(value: str) -> Path:
    """A path from .env; relative ones are taken from the project root."""
    p = Path(value)
    return p if p.is_absolute() else PROJECT_ROOT / p


# Kikuyu interviews. ASR_MODEL is the torch model, used when the OpenVINO
# export (scripts/export_openvino.py) is missing or ASR_ENGINE=torch.
ASR_MODEL: str = os.getenv("ASR_MODEL") or "microsoft/paza-whisper-large-v3-turbo"
ASR_LANGUAGE: str = os.getenv("ASR_LANGUAGE") or "sw"
ASR_ENGINE: str = (os.getenv("ASR_ENGINE") or "openvino").lower()       # openvino | torch
ASR_DEVICE: str = (os.getenv("ASR_DEVICE") or "GPU").upper()            # GPU | CPU (falls back to CPU)
ASR_OV_MODEL_DIR: Path = _project_path(os.getenv("ASR_OV_MODEL_DIR") or "models/paza-ov-int8")
# timestamps | plain; see scripts/benchmark_asr.py before changing it.
ASR_DECODING: str = (os.getenv("ASR_DECODING") or "timestamps").lower()
# Generation cap per second of audio; None keeps transcribe.TOKENS_PER_SECOND.
ASR_TOKENS_PER_SECOND: float | None = float(os.getenv("ASR_TOKENS_PER_SECOND") or 0) or None
# English interviews: same engine and device settings, loaded on first use.
ASR_EN_MODEL: str = os.getenv("ASR_EN_MODEL") or "openai/whisper-large-v3-turbo"
ASR_EN_OV_MODEL_DIR: Path = _project_path(os.getenv("ASR_EN_OV_MODEL_DIR") or "models/whisper-en-ov-int8")

SCRIPTS_DIR = PROJECT_ROOT / "scripts"
# Built from docs/interview_questions.txt by scripts/build_questions.py
QUESTIONS_PATH = Path(__file__).resolve().parent / "questions.json"
MODELS_DIR = PROJECT_ROOT / "models"
CLASSIFIER_PATH = MODELS_DIR / "classifier.joblib"
CLASSIFIER_META_PATH = MODELS_DIR / "classifier_meta.json"
# Aggregate evaluation figures, written by scripts/export_results.py
RESULTS_SUMMARY_PATH = PROJECT_ROOT / "results" / "summary.json"
# The built dashboard (cd frontend && npm run build), served by the API at /.
FRONTEND_DIST = _project_path(os.getenv("CHAMAPRO_FRONTEND_DIST") or "frontend/dist")

# --- API ---------------------------------------------------------------------
DB_PATH = Path(os.getenv("CHAMAPRO_DB") or DATA_DIR / "chamapro.db")


def _database_url(value: str | None) -> str:
    """SQLAlchemy URL for the database. Unset means the SQLite file at DB_PATH.
    A plain postgres:// or postgresql:// URL (as Supabase shows it) is pointed
    at the psycopg 3 driver, the one in requirements.txt."""
    if not value:
        return f"sqlite:///{DB_PATH}"
    for prefix in ("postgres://", "postgresql://"):
        if value.startswith(prefix):
            return "postgresql+psycopg://" + value[len(prefix):]
    return value


# SQLite now; Supabase Postgres by setting this to the session pooler string.
DATABASE_URL: str = _database_url(os.getenv("DATABASE_URL"))
UPLOADS_DIR = Path(os.getenv("CHAMAPRO_UPLOADS") or DATA_DIR / "uploads")
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

# --- Audio storage -----------------------------------------------------------
# local keeps clips in UPLOADS_DIR; supabase puts them in a private bucket and
# replays them through short-lived signed URLs. The service-role key bypasses
# row-level security: it is read here, on the server, and never sent to a browser.
STORAGE_BACKEND: str = (os.getenv("STORAGE_BACKEND") or "local").lower()   # local | supabase
SUPABASE_URL: str | None = os.getenv("SUPABASE_URL") or None
SUPABASE_SERVICE_ROLE_KEY: str | None = os.getenv("SUPABASE_SERVICE_ROLE_KEY") or None
SUPABASE_BUCKET: str = os.getenv("SUPABASE_BUCKET") or "interview-audio"
SUPABASE_SIGNED_URL_SECONDS: int = int(os.getenv("SUPABASE_SIGNED_URL_SECONDS") or 120)

# --- Sign-in -----------------------------------------------------------------
SESSION_HOURS = 8
LOGIN_MAX_FAILURES = 5          # per username ...
LOGIN_WINDOW_SECONDS = 15 * 60  # ... in this window, then 429
# Session cookie Secure flag: "1" always, "0" never, unset = on except for localhost.
COOKIE_SECURE: str | None = os.getenv("CHAMAPRO_COOKIE_SECURE") or None
# OAuth 2.0 Web client ID for "Sign in with Google"; unset = Google sign-in off.
GOOGLE_CLIENT_ID: str | None = os.getenv("GOOGLE_CLIENT_ID") or None

# --- Volunteer pilot ---------------------------------------------------------
# Self sign-up exists only while this is set; it is the code volunteers are given.
PILOT_INVITE_CODE: str | None = os.getenv("PILOT_INVITE_CODE") or None
SIGNUP_MAX_PER_IP: int = int(os.getenv("SIGNUP_MAX_PER_IP") or 10)    # sign-up attempts per address ...
SIGNUP_WINDOW_SECONDS: int = int(os.getenv("SIGNUP_WINDOW_SECONDS") or 3600)   # ... in this window, then 429
# Self-service practice submissions per Nairobi day. Staff assessments do not count.
PILOT_MAX_SUBMISSIONS_PER_MEMBER: int = int(os.getenv("PILOT_MAX_SUBMISSIONS_PER_MEMBER") or 5)
PILOT_MAX_ASSESSMENTS_PER_DAY: int = int(os.getenv("PILOT_MAX_ASSESSMENTS_PER_DAY") or 20)

# --- Automatic decisions -----------------------------------------------------
# The policy's thresholds (api/decisions.py). A decision records the version, and
# changing any of these from its default adds a hash of the values to it, so one
# version always means one set of thresholds.
POLICY_BASE_VERSION = "2026.11.3"
POLICY_DEFAULTS = {"AUTO_APPROVE_LIMIT_KES": 50_000, "LOAN_INTEREST_MONTHLY": 0.01,
                   "AFFORDABILITY_RATIO": 1 / 3, "AFFORDABILITY_NEAR_BAND": 0.15, "PROFILE_STALE_DAYS": 180,
                   "UNVERIFIED_INCREASE_TOLERANCE": 0.30}
AUTO_APPROVE_LIMIT_KES: int = int(os.getenv("AUTO_APPROVE_LIMIT_KES") or POLICY_DEFAULTS["AUTO_APPROVE_LIMIT_KES"])
LOAN_INTEREST_MONTHLY: float = float(os.getenv("LOAN_INTEREST_MONTHLY") or POLICY_DEFAULTS["LOAN_INTEREST_MONTHLY"])
AFFORDABILITY_RATIO: float = float(os.getenv("AFFORDABILITY_RATIO") or POLICY_DEFAULTS["AFFORDABILITY_RATIO"])
AFFORDABILITY_NEAR_BAND: float = float(os.getenv("AFFORDABILITY_NEAR_BAND") or POLICY_DEFAULTS["AFFORDABILITY_NEAR_BAND"])
PROFILE_STALE_DAYS: int = int(os.getenv("PROFILE_STALE_DAYS") or POLICY_DEFAULTS["PROFILE_STALE_DAYS"])
# How far above the profile a stated income is taken at the member's word.
UNVERIFIED_INCREASE_TOLERANCE: float = float(os.getenv("UNVERIFIED_INCREASE_TOLERANCE")
                                             or POLICY_DEFAULTS["UNVERIFIED_INCREASE_TOLERANCE"])
REVERSAL_HOURS: int = int(os.getenv("REVERSAL_HOURS") or 24)    # how long an automatic payout can be undone
# Self-service requests per member per hour, then 429. Each evaluation runs the classifier.
SELF_SERVICE_EVALUATIONS_PER_HOUR: int = int(os.getenv("SELF_SERVICE_EVALUATIONS_PER_HOUR") or 60)
SELF_SERVICE_COMMITS_PER_HOUR: int = int(os.getenv("SELF_SERVICE_COMMITS_PER_HOUR") or 10)

# --- Conversation ------------------------------------------------------------
SACCO_NAME: str = os.getenv("SACCO_NAME") or "ChamaPro SACCO"
CONVERSATION_IDLE_MINUTES: int = int(os.getenv("CONVERSATION_IDLE_MINUTES") or 15)     # then abandoned
CONVERSATION_MAX_QUESTIONS: int = int(os.getenv("CONVERSATION_MAX_QUESTIONS") or 3)    # clarifications, then refer
CONVERSATION_MAX_AUDIO_SECONDS: int = int(os.getenv("CONVERSATION_MAX_AUDIO_SECONDS") or 60)
CONVERSATION_STARTS_PER_HOUR: int = int(os.getenv("CONVERSATION_STARTS_PER_HOUR") or 20)
CONVERSATION_REPLIES_PER_HOUR: int = int(os.getenv("CONVERSATION_REPLIES_PER_HOUR") or 120)
# Off by default, so that nothing reaches Gemini by accident: only the parsers run.
# scripts/converse.py turns it on with --live; a server, with this variable.
CONVERSATION_GEMINI_LIVE: bool = os.getenv("CONVERSATION_GEMINI_LIVE") == "1"
CONVERSATION_GEMINI_SECONDS: float = float(os.getenv("CONVERSATION_GEMINI_SECONDS") or 8)

# --- Speech recognition warm-up ----------------------------------------------
# After the Kikuyu ASR loads, it transcribes one clip in the background, and the classifier
# scores once, so a member's first reply waits for neither. 0 turns both off. The English
# model loads on first use unless ASR_WARM_ENGLISH=1 loads and warms it the same way.
ASR_WARM: bool = os.getenv("ASR_WARM", "1") != "0"
ASR_WARM_ENGLISH: bool = os.getenv("ASR_WARM_ENGLISH") == "1"

# --- Speech output -----------------------------------------------------------
# Both models are CC-BY-NC 4.0: see README, "Licence and third-party components".
TTS_ENABLED: bool = os.getenv("TTS_ENABLED", "1") != "0"
TTS_KIK_MODEL: str = os.getenv("TTS_KIK_MODEL") or "facebook/mms-tts-kik"
TTS_EN_MODEL: str = os.getenv("TTS_EN_MODEL") or "facebook/mms-tts-eng"
TTS_DEVICE: str = os.getenv("TTS_DEVICE") or "cpu"
TTS_CACHE_DIR: Path = _project_path(os.getenv("TTS_CACHE_DIR") or "data/tts_cache")

# --- Interview bookings ------------------------------------------------------
# Kenya keeps no daylight saving, so the fixed offset is right wherever the
# server has no time zone database (a slim container image).
try:
    NAIROBI = ZoneInfo("Africa/Nairobi")
except ZoneInfoNotFoundError:
    NAIROBI = timezone(timedelta(hours=3), "EAT")
BOOKING_WINDOW_DAYS: int = int(os.getenv("BOOKING_WINDOW_DAYS") or 90)   # how far ahead a slot can be taken

# Weekdays among these cannot be booked. Fixed dates and Easter are certain. The
# two Idd dates depend on the moon and are gazetted shortly before: the 2027 ones
# are estimates, to be corrected once gazetted. A holiday falling on a Sunday is
# observed on the Monday (Public Holidays Act), so that Monday is listed as well.
DEFAULT_PUBLIC_HOLIDAYS = {
    "2026-01-01": "New Year's Day", "2026-03-20": "Idd-ul-Fitr", "2026-04-03": "Good Friday",
    "2026-04-06": "Easter Monday", "2026-05-01": "Labour Day", "2026-05-27": "Idd-ul-Azha",
    "2026-06-01": "Madaraka Day", "2026-10-10": "Mazingira Day", "2026-10-20": "Mashujaa Day",
    "2026-12-12": "Jamhuri Day", "2026-12-25": "Christmas Day", "2026-12-26": "Boxing Day",
    "2027-01-01": "New Year's Day", "2027-03-10": "Idd-ul-Fitr", "2027-03-26": "Good Friday",
    "2027-03-29": "Easter Monday", "2027-05-01": "Labour Day", "2027-05-17": "Idd-ul-Azha",
    "2027-06-01": "Madaraka Day", "2027-10-10": "Mazingira Day",
    "2027-10-11": "Mazingira Day (observed)", "2027-10-20": "Mashujaa Day",
    "2027-12-12": "Jamhuri Day", "2027-12-13": "Jamhuri Day (observed)",
    "2027-12-25": "Christmas Day", "2027-12-26": "Boxing Day",
    "2027-12-27": "Boxing Day (observed)",
}


def _public_holidays(value: str | None) -> dict[date, str]:
    """PUBLIC_HOLIDAYS as YYYY-MM-DD:Name,YYYY-MM-DD:Name, replacing the list
    above when set. A malformed entry stops startup: a holiday that silently
    fell out of the list would be open for booking."""
    if not value:
        return {date.fromisoformat(d): name for d, name in DEFAULT_PUBLIC_HOLIDAYS.items()}
    out = {}
    for entry in value.split(","):
        day, sep, name = entry.strip().partition(":")
        if not sep or not name.strip():
            raise ValueError(f"PUBLIC_HOLIDAYS: expected YYYY-MM-DD:Name, got {entry!r}")
        out[date.fromisoformat(day)] = name.strip()
    return out


PUBLIC_HOLIDAYS: dict[date, str] = _public_holidays(os.getenv("PUBLIC_HOLIDAYS"))


def require(name: str) -> str:
    """Return the named env var or raise a clear error naming what's missing."""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"{name} is not set. Copy .env.example to .env and fill it in."
        )
    return value
