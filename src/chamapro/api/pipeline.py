"""Bridge to the pipeline scripts, plus the background transcription worker.

The scripts in scripts/ are the pipeline; this module only imports them and
holds the ASR models: the Kikuyu one, loaded at startup, and the English one,
loaded the first time an English answer is transcribed.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import sys
import tempfile
import threading
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import select

from chamapro import config

sys.path.insert(0, str(config.SCRIPTS_DIR))
import ingest_audio  # noqa: E402
import score_interview  # noqa: E402
import transcribe  # noqa: E402
import translate_extract  # noqa: E402

from . import storage  # noqa: E402
from .db import Response, SessionLocal, utcnow  # noqa: E402

log = logging.getLogger("chamapro.api")

AUDIO_SUFFIXES = ingest_audio.SUFFIXES | {".mp4", ".wma", ".aiff", ".aif"}

# Language code stored on an interview -> the ASR language token.
ASR_LANGUAGES = {"kik": config.ASR_LANGUAGE, "en": "en"}

_asr: transcribe.ASR | None = None       # Kikuyu
_asr_en: transcribe.ASR | None = None    # English, loaded on first use
_asr_en_error: str | None = None
_asr_en_lock = threading.Lock()
# One worker thread transcribes one clip at a time: inference is CPU-bound and
# the HF pipeline is not thread-safe. Request-scoped BackgroundTasks only
# enqueue, so a 40-clip interview never parks 40 threads in the shared pool.
# A deque under a condition (not queue.Queue) so a deleted clip can be pulled
# out of the queue and the clip being transcribed right now is known.
_cond = threading.Condition()
_pending: deque[int] = deque()
_current: int | None = None
_stopping = False


def load_asr() -> None:
    """Load the Kikuyu model on the configured engine and device; any
    fallback is logged and shows in /api/health."""
    global _asr
    log.info("loading Kikuyu ASR: engine=%s device=%s", config.ASR_ENGINE, config.ASR_DEVICE)
    _asr = transcribe.load_asr(config.ASR_MODEL, config.ASR_ENGINE, config.ASR_DEVICE,
                               config.ASR_OV_MODEL_DIR, log=log.info)
    log.info("Kikuyu ASR ready: %s", _asr.label)


def english_asr() -> transcribe.ASR:
    """The English model with the same engine settings, loaded on first use."""
    global _asr_en, _asr_en_error
    with _asr_en_lock:
        if _asr_en is None:
            log.info("loading English ASR: engine=%s device=%s", config.ASR_ENGINE, config.ASR_DEVICE)
            try:
                _asr_en = transcribe.load_asr(config.ASR_EN_MODEL, config.ASR_ENGINE, config.ASR_DEVICE,
                                              config.ASR_EN_OV_MODEL_DIR, log=log.info)
            except Exception as e:
                _asr_en_error = f"{type(e).__name__}: {e}"
                raise
            _asr_en_error = None
            log.info("English ASR ready: %s", _asr_en.label)
        return _asr_en


def asr_loaded() -> bool:
    return _asr is not None


def asr_status() -> dict:
    """What each language's ASR runs on, for /api/health."""
    out = {}
    for lang, asr, err in (("kik", _asr, None), ("en", _asr_en, _asr_en_error)):
        out[lang] = {"loaded": asr is not None, "engine": asr and asr.engine,
                     "device": asr and asr.device, "model": asr and asr.label,
                     "language": ASR_LANGUAGES[lang], "error": err}
    return out


def asr_settings() -> dict:
    """Decoding settings shared by every transcription."""
    return {"decoding": config.ASR_DECODING,
            "tokens_per_second": config.ASR_TOKENS_PER_SECOND or transcribe.TOKENS_PER_SECOND}


def extraction_model() -> str:
    """The Gemini model the extraction stage will actually call."""
    return config.GEMINI_MODEL or score_interview.DEFAULT_GEM


class NotAudio(ValueError):
    pass


def convert_upload(src: Path, dst: Path) -> float:
    """Convert to 16 kHz mono WAV at dst and return the duration in seconds.

    Uses the same conversion as ingest_audio.py. librosa cannot read webm/mp4
    (what browsers record), so those go through ffmpeg to WAV first.
    """
    try:
        dur = ingest_audio.convert(src, dst)
    except Exception as first:
        if not shutil.which("ffmpeg"):
            raise NotAudio(f"could not decode audio: {first}") from None
        with tempfile.TemporaryDirectory() as tmp:
            wav = Path(tmp) / "decoded.wav"
            r = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(src),
                                "-vn", "-ac", "1", "-ar", "16000", str(wav)],
                               capture_output=True, text=True, timeout=120)
            if r.returncode != 0 or not wav.exists():
                raise NotAudio("could not decode audio") from None
            dur = ingest_audio.convert(wav, dst)
    if dur <= 0:
        dst.unlink(missing_ok=True)
        raise NotAudio("audio contains no samples")
    return dur


def transcribe_response(response_id: int) -> None:
    """Transcribe one queued response and record the outcome."""
    with SessionLocal() as db:
        r = db.get(Response, response_id)
        if r is None or r.status != "queued":
            return
        ref, duration, language = r.audio_path, r.duration_s, r.interview.language

    store = storage.for_ref(ref)
    try:
        asr = english_asr() if language == "en" else _asr
        if asr is None:
            raise RuntimeError("ASR model not loaded")
        out = transcribe.transcribe_clip(str(store.local_path(ref)), asr.pipe,
                                         ASR_LANGUAGES[language], duration=duration,
                                         **asr_settings())
    except Exception as e:
        log.exception("transcription failed for response %s", response_id)
        update = {"status": "failed", "error": f"{type(e).__name__}: {e}"}
    else:
        log.info("response %s transcribed in %ss", response_id, out["seconds"])
        update = {"status": "transcribed", "error": None, "transcript": out["text"],
                  "transcript_asr": out["text"], "asr_seconds": out["seconds"],
                  "asr_model": asr.label, "transcribed_at": utcnow()}
    finally:
        try:
            store.release(ref)
        except Exception:  # a stale cache file is harmless
            log.exception("could not release the local copy of response %s", response_id)

    with SessionLocal() as db:
        r = db.get(Response, response_id)
        if r is None or r.status != "queued":
            return
        for k, v in update.items():
            setattr(r, k, v)
        db.commit()


class TranscriptionBusy(Exception):
    """The response is being transcribed at this moment."""


def transcribing() -> int | None:
    """Id of the response the worker is transcribing right now, if any."""
    with _cond:
        return _current


def enqueue(response_id: int) -> None:
    with _cond:
        if response_id != _current and response_id not in _pending:
            _pending.append(response_id)
            _cond.notify()


@contextmanager
def withheld(response_id: int) -> Iterator[bool]:
    """Keep a response away from the worker while the caller deletes it.

    Removes it from the queue (yielding whether it was there) and holds the
    queue until the block exits, so the worker cannot pick it up meanwhile.
    Raises TranscriptionBusy if the worker is already transcribing it.
    """
    with _cond:
        if response_id == _current:
            raise TranscriptionBusy(response_id)
        was_queued = response_id in _pending
        if was_queued:
            _pending.remove(response_id)
        yield was_queued


def _work() -> None:
    global _current
    while True:
        with _cond:
            while not _pending and not _stopping:
                _cond.wait()
            if _stopping:
                return
            _current = rid = _pending.popleft()
        try:
            transcribe_response(rid)
        except Exception:  # e.g. DB locked; keep the worker alive
            log.exception("worker error on response %s", rid)
        finally:
            with _cond:
                _current = None


def start_worker() -> None:
    """Start the transcription worker and requeue anything a previous process
    left queued (server restart, --reload)."""
    global _stopping
    with _cond:
        _stopping = False
        _pending.clear()
    threading.Thread(target=_work, name="transcription", daemon=True).start()
    with SessionLocal() as db:
        ids = list(db.scalars(select(Response.id)
                              .where(Response.status == "queued")
                              .order_by(Response.id)))
    if ids:
        log.info("resuming %d queued transcription(s)", len(ids))
    for rid in ids:
        enqueue(rid)


def stop_worker() -> None:
    """Let the current clip finish; anything still queued resumes next start."""
    global _stopping
    with _cond:
        _stopping = True
        _pending.clear()
        _cond.notify_all()
