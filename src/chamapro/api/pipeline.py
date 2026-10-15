"""Bridge to the pipeline scripts, plus the background transcription worker.

The scripts in scripts/ are the pipeline; this module only imports them and
holds the one ASR model the process loads at startup.
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

from .db import Response, SessionLocal, utcnow  # noqa: E402

log = logging.getLogger("chamapro.api")

AUDIO_SUFFIXES = ingest_audio.SUFFIXES | {".mp4", ".wma", ".aiff", ".aif"}

_asr = None
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
    global _asr
    log.info("loading ASR model %s", config.ASR_MODEL)
    _asr = transcribe.load_asr(config.ASR_MODEL)
    log.info("ASR model ready")


def asr_loaded() -> bool:
    return _asr is not None


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
        path, duration = r.audio_path, r.duration_s

    try:
        if _asr is None:
            raise RuntimeError("ASR model not loaded")
        out = transcribe.transcribe_clip(path, _asr, config.ASR_LANGUAGE, duration=duration)
    except Exception as e:
        log.exception("transcription failed for response %s", response_id)
        update = {"status": "failed", "error": f"{type(e).__name__}: {e}"}
    else:
        log.info("response %s transcribed in %ss", response_id, out["seconds"])
        update = {"status": "transcribed", "error": None, "transcript": out["text"],
                  "transcript_asr": out["text"], "asr_seconds": out["seconds"],
                  "asr_model": config.ASR_MODEL, "transcribed_at": utcnow()}

    with SessionLocal() as db:
        r = db.get(Response, response_id)
        if r is None or r.status != "queued":
            return
        for k, v in update.items():
            setattr(r, k, v)
        db.commit()


class TranscriptionBusy(Exception):
    """The response is being transcribed at this moment."""


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
