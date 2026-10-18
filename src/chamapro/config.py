"""Central configuration: loads .env once and exposes keys and paths.

Every other module imports from here instead of calling os.getenv itself,
so there is exactly one place that knows where secrets and data live.
"""
from __future__ import annotations

import os
from pathlib import Path

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
ASR_MODEL: str = os.getenv("ASR_MODEL") or "openai/whisper-small"
ASR_LANGUAGE: str = os.getenv("ASR_LANGUAGE") or "sw"

SCRIPTS_DIR = PROJECT_ROOT / "scripts"
# Built from docs/interview_questions.txt by scripts/build_questions.py
QUESTIONS_PATH = Path(__file__).resolve().parent / "questions.json"
MODELS_DIR = PROJECT_ROOT / "models"
CLASSIFIER_PATH = MODELS_DIR / "classifier.joblib"
CLASSIFIER_META_PATH = MODELS_DIR / "classifier_meta.json"

# --- API ---------------------------------------------------------------------
DB_PATH = Path(os.getenv("CHAMAPRO_DB") or DATA_DIR / "chamapro.db")
UPLOADS_DIR = Path(os.getenv("CHAMAPRO_UPLOADS") or DATA_DIR / "uploads")
MAX_UPLOAD_BYTES = 25 * 1024 * 1024


def require(name: str) -> str:
    """Return the named env var or raise a clear error naming what's missing."""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"{name} is not set. Copy .env.example to .env and fill it in."
        )
    return value
