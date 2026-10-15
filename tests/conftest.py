"""API test fixtures: a scratch database and uploads folder, a fake ASR model
whose speed the test controls, a fake Gemini, and no network.

    pytest

Tests that score with the real classifier are marked needs_classifier and
skip when models/classifier.joblib is absent.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path

# Must precede any chamapro import: config reads these once at import time.
_TMP = Path(tempfile.mkdtemp(prefix="chamapro-test-"))
os.environ["CHAMAPRO_DB"] = str(_TMP / "test.db")
os.environ["CHAMAPRO_UPLOADS"] = str(_TMP / "uploads")

import numpy as np  # noqa: E402
import pytest  # noqa: E402
import requests  # noqa: E402
import soundfile as sf  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from chamapro import config  # noqa: E402
from chamapro.api import pipeline as pl  # noqa: E402
from chamapro.api.db import Assessment, Interview, SessionLocal  # noqa: E402
from chamapro.api.main import app  # noqa: E402

needs_classifier = pytest.mark.skipif(
    not (config.CLASSIFIER_PATH.exists() and config.CLASSIFIER_META_PATH.exists()),
    reason="needs models/classifier.joblib (run scripts/train_and_save.py)")
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="needs ffmpeg")


# --- Helpers -----------------------------------------------------------------

def wait_until(predicate, timeout=10.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if predicate():
            return
        time.sleep(0.02)
    raise AssertionError("condition not met within timeout")


def worker_idle():
    with pl._cond:
        return pl._current is None and not pl._pending


def uploads(interview_id):
    folder = config.UPLOADS_DIR / str(interview_id)
    return sorted(p.name for p in folder.iterdir()) if folder.exists() else []


# --- Fakes -------------------------------------------------------------------

class FakeASR:
    """Stands in for the Whisper pipeline. Set .gate to an Event to hold a
    clip mid-transcription until the test releases it; set .fail to raise."""

    def __init__(self):
        self.calls: list[str] = []
        self.started = threading.Event()
        self.gate: threading.Event | None = None
        self.fail = False

    def __call__(self, path, **kwargs):
        self.calls.append(Path(path).name)
        self.started.set()
        if self.gate is not None:
            self.gate.wait(timeout=10)
        if self.fail:
            raise RuntimeError("decoder exploded")
        return {"text": f"kikuyu {Path(path).stem}", "chunks": []}


class FakeGemini:
    """Replaces call() in both Gemini stages. Each stage's mode is "ok",
    "down" (raises a network error) or "garbage" (returns non-JSON)."""

    def __init__(self):
        self.translation = "ok"
        self.extraction = "ok"
        self.features = {"age": 42, "household_size": 6, "agri_income_kes": 8000,
                         "income_sources": {"farming": 1}, "sacco_loan_use": 2}
        self.translated: list[list[str]] = []   # sentence numbers per request

    def __call__(self, prompt, key, model, **kwargs):
        if "JSON array" in prompt:              # translate_extract.PROMPT
            mode, body = self.translation, prompt.split("Responses:")[1]
        else:                                   # score_interview.PROMPT
            mode, body = self.extraction, None
        if mode == "down":
            raise requests.ConnectionError("unreachable")
        if mode == "garbage":
            return "sorry, I cannot help with that"
        if body is None:
            return json.dumps(self.features)
        items = re.findall(r"^(\d+)\. (.*)$", body, flags=re.M)
        self.translated.append([n for n, _ in items])
        return "```json\n" + json.dumps(
            [{"n": n, "english": f"english of {t}", "signals": [f"signal {n}"]}
             for n, t in items]) + "\n```"


# --- Fixtures ----------------------------------------------------------------

@pytest.fixture(scope="session")
def client():
    pl.transcribe.load_asr = lambda name: FakeASR()  # never load the real model
    with TestClient(app) as c:
        yield c


@pytest.fixture
def asr(monkeypatch, client):
    fake = FakeASR()
    monkeypatch.setattr(pl, "_asr", fake)
    yield fake
    if fake.gate is not None:
        fake.gate.set()
    wait_until(worker_idle)


@pytest.fixture
def gemini(monkeypatch):
    fake = FakeGemini()
    monkeypatch.setattr(pl.translate_extract, "call", fake)
    monkeypatch.setattr(pl.score_interview, "call", fake)
    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    return fake


@pytest.fixture
def classifier_stub(monkeypatch, tmp_path):
    """Pass assess's classifier pre-check without the real model, for tests
    whose request must fail before anything is scored."""
    if not config.CLASSIFIER_PATH.exists():
        model, meta = tmp_path / "classifier.joblib", tmp_path / "classifier_meta.json"
        model.write_bytes(b"stub")
        meta.write_text("{}")
        monkeypatch.setattr(config, "CLASSIFIER_PATH", model)
        monkeypatch.setattr(config, "CLASSIFIER_META_PATH", meta)


@pytest.fixture(scope="session")
def audio(tmp_path_factory):
    """One second of tone in each format the dashboard might send."""
    d = tmp_path_factory.mktemp("audio")
    t = np.linspace(0, 1, 16000, endpoint=False)
    tone = 0.1 * np.sin(2 * np.pi * 440 * t)
    paths = {"wav": d / "clip.wav", "ogg": d / "clip.ogg", "stereo44k": d / "stereo.wav"}
    sf.write(str(paths["wav"]), tone, 16000)
    sf.write(str(paths["ogg"]), tone, 16000, format="OGG", subtype="VORBIS")
    t44 = np.linspace(0, 1, 44100, endpoint=False)
    sf.write(str(paths["stereo44k"]), np.stack([np.sin(2 * np.pi * 440 * t44)] * 2, axis=1) * 0.1, 44100)
    if shutil.which("ffmpeg"):
        for ext in ("webm", "m4a"):
            paths[ext] = d / f"clip.{ext}"
            subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-y",
                            "-i", str(paths["wav"]), str(paths[ext])], check=True)
    return paths


@pytest.fixture
def wav(audio):
    return audio["wav"]


@pytest.fixture
def interview(client):
    return client.post("/api/interviews", json={"applicant_name": "test"}).json()["id"]


@pytest.fixture
def upload(client, audio, asr):
    def _upload(interview_id, sentence_no, path=None, content_type="audio/wav",
                filename=None, content=None):
        path = Path(path or audio["wav"])
        data = path.read_bytes() if content is None else content
        return client.post(f"/api/interviews/{interview_id}/responses",
                           data={"sentence_no": str(sentence_no)},
                           files={"file": (filename or path.name, data, content_type)})
    return _upload


@pytest.fixture
def state(client):
    return lambda interview_id: client.get(f"/api/interviews/{interview_id}").json()


@pytest.fixture
def ready_interview(interview, upload, state):
    """An interview with sentences 2, 6 and 7 transcribed."""
    for n in (2, 6, 7):
        assert upload(interview, n).status_code == 202
    wait_until(lambda: state(interview)["counts"]["transcribed"] == 3)
    return interview


@pytest.fixture
def assessed_interview(ready_interview):
    """ready_interview with an assessment written straight to the database,
    so immutability can be tested without the real classifier."""
    with SessionLocal() as db:
        iv = db.get(Interview, ready_interview)
        db.add(Assessment(
            interview_id=iv.id, risk_class="Medium",
            probabilities={"Low": 0.2, "Medium": 0.5, "High": 0.3},
            feature_vector={"age": 42.0, "log_monthly_income": None},
            contributions=[{"feature": "age", "value": 42.0, "shap": 0.1}],
            extracted={"age": 42}, extraction_completeness=0.5,
            features_populated=1, features_total=2, features_not_extractable=[],
            extraction_model="fake-gemini", model_file="classifier.joblib",
            model_sha256="0" * 64))
        iv.status = "assessed"
        db.commit()
    return ready_interview
