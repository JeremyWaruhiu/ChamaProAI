"""Error codes: every failure is JSON {"detail": "<string>"} with the right status."""
import threading
import time
from types import SimpleNamespace

import pytest
import requests

from chamapro import config
from chamapro.api import pipeline as pl

from conftest import uploads, wait_until


def detail(r, status):
    assert r.status_code == status, r.text
    body = r.json()
    assert list(body) == ["detail"] and isinstance(body["detail"], str)
    return body["detail"]


# --- Uploads -----------------------------------------------------------------

def test_upload_to_unknown_interview_is_404(upload):
    assert detail(upload(999999, 1), 404) == "interview 999999 not found"


def test_duplicate_sentence_is_409(interview, upload):
    assert upload(interview, 1).status_code == 202
    assert detail(upload(interview, 1), 409) == "sentence 1 already has a response"


def test_non_audio_content_type_and_extension_is_415(interview, upload):
    d = detail(upload(interview, 1, content_type="text/plain", filename="notes.txt",
                      content=b"hello"), 415)
    assert "not an audio file" in d and "text/plain" in d


@pytest.mark.parametrize("content_type", ["audio/wav", "text/plain"])
def test_undecodable_audio_is_415(interview, upload, content_type):
    r = upload(interview, 1, content_type=content_type, filename="fake.wav", content=b"not audio")
    assert detail(r, 415) == "could not decode audio"
    assert uploads(interview) == []                   # nothing left behind


def test_empty_upload_is_415(interview, upload):
    assert detail(upload(interview, 1, content=b""), 415) == "empty upload"


def test_upload_over_25_mb_is_413(interview, upload):
    assert config.MAX_UPLOAD_BYTES == 25 * 1024 * 1024
    r = upload(interview, 1, content=b"\0" * (config.MAX_UPLOAD_BYTES + 1))
    assert detail(r, 413) == "audio exceeds 25 MB"
    assert uploads(interview) == []


def test_missing_sentence_no_is_422(client, interview, wav):
    r = client.post(f"/api/interviews/{interview}/responses",
                    files={"file": ("clip.wav", wav.read_bytes(), "audio/wav")})
    assert detail(r, 422) == "sentence_no: Field required"


@pytest.mark.parametrize("value", ["0", "-3", "two"])
def test_invalid_sentence_no_is_422(client, interview, wav, value):
    r = client.post(f"/api/interviews/{interview}/responses", data={"sentence_no": value},
                    files={"file": ("clip.wav", wav.read_bytes(), "audio/wav")})
    assert detail(r, 422).startswith("sentence_no: ")


# --- Reads and edits ---------------------------------------------------------

def test_unknown_interview_is_404(client):
    assert detail(client.get("/api/interviews/999999"), 404) == "interview 999999 not found"


def test_unknown_route_is_404_json(client):
    detail(client.get("/api/nope"), 404)


def test_patch_unknown_response_is_404(client):
    r = client.patch("/api/responses/999999", json={"transcript": "x"})
    assert detail(r, 404) == "response 999999 not found"


@pytest.mark.parametrize("text", ["", "   "])
def test_patch_blank_transcript_is_422(client, ready_interview, state, text):
    rid = state(ready_interview)["responses"][0]["id"]
    detail(client.patch(f"/api/responses/{rid}", json={"transcript": text}), 422)


def test_patch_while_queued_is_409(client, asr, interview, upload):
    asr.gate = threading.Event()
    rid = upload(interview, 1).json()["id"]
    r = client.patch(f"/api/responses/{rid}", json={"transcript": "too early"})
    assert "still being transcribed" in detail(r, 409)


# --- Assess ------------------------------------------------------------------

def test_assess_unknown_interview_is_404(client):
    detail(client.post("/api/interviews/999999/assess"), 404)


def test_assess_without_responses_is_409(client, interview):
    r = client.post(f"/api/interviews/{interview}/assess")
    assert detail(r, 409) == "no transcribed responses to assess"


def test_assess_with_only_failed_responses_is_409(client, asr, interview, upload, state):
    asr.fail = True
    upload(interview, 1)
    wait_until(lambda: state(interview)["counts"]["failed"] == 1)
    assert detail(client.post(f"/api/interviews/{interview}/assess"), 409) == \
        "no transcribed responses to assess"


def test_assess_while_queued_is_409(client, asr, interview, upload):
    asr.gate = threading.Event()
    upload(interview, 4)
    r = client.post(f"/api/interviews/{interview}/assess")
    assert "still being transcribed" in detail(r, 409) and "[4]" in r.json()["detail"]


def test_assess_without_api_key_is_503(client, monkeypatch, ready_interview):
    monkeypatch.setattr(config, "GEMINI_API_KEY", None)
    assert "GEMINI_API_KEY" in detail(client.post(f"/api/interviews/{ready_interview}/assess"), 503)


def test_assess_without_classifier_is_503(client, gemini, monkeypatch, tmp_path, ready_interview):
    monkeypatch.setattr(config, "CLASSIFIER_PATH", tmp_path / "missing.joblib")
    assert "classifier not available" in detail(
        client.post(f"/api/interviews/{ready_interview}/assess"), 503)
    assert gemini.translated == []                    # failed before calling out


@pytest.mark.parametrize("failure", ["network", "http-503"])
def test_gemini_unreachable_after_retries_is_503(client, monkeypatch, classifier_stub,
                                                 ready_interview, failure):
    """Runs the real retry loop in translate_extract.call; only the transport is fake."""
    attempts, sleeps = [], []

    def fake_post(*args, **kwargs):
        attempts.append(1)
        if failure == "network":
            raise requests.ConnectionError("no route to host")
        return SimpleNamespace(status_code=503, text="overloaded")

    monkeypatch.setattr(config, "GEMINI_API_KEY", "test-key")
    monkeypatch.setattr(pl.translate_extract.requests, "post", fake_post)
    monkeypatch.setattr(pl.translate_extract, "time", SimpleNamespace(time=time.time, sleep=sleeps.append))

    d = detail(client.post(f"/api/interviews/{ready_interview}/assess"), 503)

    assert d.startswith("translation: extraction service unavailable after retries")
    assert len(attempts) == 5 and sleeps == [2, 4, 8, 16]


def test_feature_extraction_unreachable_is_503_and_keeps_translations(
        client, gemini, classifier_stub, ready_interview, state):
    gemini.extraction = "down"
    d = detail(client.post(f"/api/interviews/{ready_interview}/assess"), 503)
    assert d.startswith("feature extraction: extraction service unavailable")
    st = state(ready_interview)
    assert st["status"] == "open" and st["assessment"] is None
    assert all(x["translation"] for x in st["responses"])   # committed before extraction


@pytest.mark.parametrize("stage, prefix", [("translation", "translation"),
                                           ("extraction", "feature extraction")])
def test_unparseable_gemini_output_is_502(client, gemini, classifier_stub, ready_interview,
                                          stage, prefix):
    setattr(gemini, stage, "garbage")
    d = detail(client.post(f"/api/interviews/{ready_interview}/assess"), 502)
    assert d == f"{prefix}: extraction service returned unparseable output"
