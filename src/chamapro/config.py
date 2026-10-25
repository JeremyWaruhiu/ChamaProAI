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

# --- API ---------------------------------------------------------------------
DB_PATH = Path(os.getenv("CHAMAPRO_DB") or DATA_DIR / "chamapro.db")
UPLOADS_DIR = Path(os.getenv("CHAMAPRO_UPLOADS") or DATA_DIR / "uploads")
MAX_UPLOAD_BYTES = 25 * 1024 * 1024

# --- Sign-in -----------------------------------------------------------------
SESSION_HOURS = 8
LOGIN_MAX_FAILURES = 5          # per username ...
LOGIN_WINDOW_SECONDS = 15 * 60  # ... in this window, then 429
# Session cookie Secure flag: "1" always, "0" never, unset = on except for localhost.
COOKIE_SECURE: str | None = os.getenv("CHAMAPRO_COOKIE_SECURE") or None
# OAuth 2.0 Web client ID for "Sign in with Google"; unset = Google sign-in off.
GOOGLE_CLIENT_ID: str | None = os.getenv("GOOGLE_CLIENT_ID") or None


def require(name: str) -> str:
    """Return the named env var or raise a clear error naming what's missing."""
    value = os.getenv(name)
    if not value:
        raise RuntimeError(
            f"{name} is not set. Copy .env.example to .env and fill it in."
        )
    return value
