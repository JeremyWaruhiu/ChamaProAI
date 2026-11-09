"""Speech output: text in, a small audio file out, cached by hash of (model, text).

The models run on the CPU by default, loaded on first use, one sentence at a time per
model: VITS is CPU-bound, and two threads in one model would only slow each other down. A
failure of any kind is logged and returns None, and the turn goes on as text.

facebook/mms-tts-kik and facebook/mms-tts-eng are CC-BY-NC 4.0: non-commercial use only.
"""
from __future__ import annotations

import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from chamapro import config

from . import templates

log = logging.getLogger("chamapro.tts")

MEDIA_TYPE = "audio/mpeg"


class TTSEngine(ABC):
    @abstractmethod
    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        """Mono samples and their sampling rate."""


class VitsEngine(TTSEngine):
    """A transformers VitsModel: the MMS voices, or anything saved the same way."""

    def __init__(self, model_name: str, device: str | None = None):
        self.model_name, self.device = model_name, device or config.TTS_DEVICE
        self._lock = threading.Lock()
        self._model = self._tokenizer = None

    def _load(self) -> None:
        if self._model is None:
            import torch
            from transformers import AutoTokenizer, VitsModel
            if config.CPU_THREADS:      # process-wide; the container's quota, not the host's cores
                torch.set_num_threads(config.CPU_THREADS)
            log.info("loading TTS model %s on %s", self.model_name, self.device)
            self._tokenizer = AutoTokenizer.from_pretrained(self.model_name)
            self._model = VitsModel.from_pretrained(self.model_name).to(self.device).eval()

    def synthesize(self, text: str) -> tuple[np.ndarray, int]:
        import torch
        with self._lock:
            self._load()
            inputs = self._tokenizer(text, return_tensors="pt").to(self.device)
            with torch.no_grad():
                wave = self._model(**inputs).waveform
            return wave.squeeze().cpu().numpy(), int(self._model.config.sampling_rate)


_factory: Callable[[str], TTSEngine] = VitsEngine
_engines: dict[str, TTSEngine] = {}
_engines_lock = threading.Lock()


def use_factory(factory: Callable[[str], TTSEngine]) -> None:
    """Install another engine for every model (tests)."""
    global _factory
    _factory = factory
    _engines.clear()


def reset() -> None:
    use_factory(VitsEngine)


def engine_for(model_name: str) -> TTSEngine:
    with _engines_lock:
        if model_name not in _engines:
            _engines[model_name] = _factory(model_name)
        return _engines[model_name]


def model_for(voice: str) -> str:
    return config.TTS_KIK_MODEL if voice == "kik" else config.TTS_EN_MODEL


def cache_key(model_name: str, text: str) -> str:
    return hashlib.sha256(f"{model_name}\0{text}".encode()).hexdigest()


def cached_path(key: str) -> Path:
    return config.TTS_CACHE_DIR / f"{key}.mp3"


def _encode(samples: np.ndarray, rate: int, dst: Path) -> None:
    """Compress to a small MP3, which every phone can play. In place by rename, so a
    file in the cache is always whole."""
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is not installed")
    dst.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=dst.parent, prefix=".tts-") as tmp:
        wav, mp3 = Path(tmp) / "in.wav", Path(tmp) / "out.mp3"
        sf.write(wav, samples, rate)
        r = subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-i", str(wav), "-ac", "1",
                            "-codec:a", "libmp3lame", "-b:a", "32k", str(mp3)],
                           capture_output=True, text=True, timeout=60)
        if r.returncode != 0:
            raise RuntimeError(f"ffmpeg failed: {r.stderr[:200]}")
        os.replace(mp3, dst)


@dataclass(frozen=True)
class Speech:
    key: str
    model: str
    path: Path
    ms: int             # 0 on a cache hit


def audio_for(model_name: str, text: str) -> Speech | None:
    """The file for this text in this voice, made if the cache does not have it."""
    if not config.TTS_ENABLED or not text.strip():
        return None
    started = time.perf_counter()
    key = cache_key(model_name, text)
    path = cached_path(key)
    if path.is_file():
        return Speech(key, model_name, path, 0)
    try:
        samples, rate = engine_for(model_name).synthesize(text)
        _encode(samples, rate, path)
    except Exception:
        log.exception("speech failed; the turn goes on as text")
        return None
    return Speech(key, model_name, path, round((time.perf_counter() - started) * 1000))


def speak(line: templates.Rendered) -> Speech | None:
    return audio_for(model_for(line.voice), line.spoken)


def prewarm() -> int:
    """Every fixed line, so the first member to hear it does not wait. Returns how many are ready."""
    return sum(speak(line) is not None for line in templates.fixed_lines())


def prewarm_in_background() -> None:
    def run():
        try:
            log.info("speech cache: %d fixed lines ready", prewarm())
            # A cache hit never loads a voice, and a line it has not heard should not wait for that too.
            voices = ["en", "kik"] if any(e["kik"] for e in templates.load().values()) else ["en"]
            for voice in voices:
                engine_for(model_for(voice)).synthesize("Ready.")
        except Exception:
            log.exception("speech cache could not be warmed")
    if config.TTS_ENABLED:
        threading.Thread(target=run, name="tts-prewarm", daemon=True).start()
