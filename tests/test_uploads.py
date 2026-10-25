"""Uploads and audio formats: conversion, storage, background transcription,
and reviewer edits to the resulting transcript."""
import threading

import pytest
import soundfile as sf

from chamapro import config

from conftest import FORM, needs_ffmpeg, new_interview, uploads, wait_until


def test_health_reports_pipeline(client):
    h = client.get("/api/health").json()
    assert h["asr_loaded"] is True
    assert h["asr_model"] == config.ASR_MODEL
    assert h["asr_language"] == config.ASR_LANGUAGE
    assert (h["asr_engine"], h["asr_device"]) == ("torch", "CPU")     # what the fake loaded as
    assert h["asr_decoding"] == config.ASR_DECODING == "timestamps"
    assert h["asr"]["kik"]["loaded"] is True and h["asr"]["kik"]["engine"] == "torch"
    assert h["asr"]["en"]["language"] == "en"
    assert h["classifier_present"] == config.CLASSIFIER_PATH.exists()
    assert h["api_key_configured"] == bool(config.GEMINI_API_KEY)
    ready = h["classifier_present"] and h["api_key_configured"]
    assert h["status"] == ("ok" if ready else "degraded")


def test_create_interview(client, state):
    r = client.post("/api/interviews", json={"applicant_name": "  Wanjiru  ", "applicant": FORM})
    assert r.status_code == 201
    assert r.json() == {"id": r.json()["id"], "status": "open"}
    st = state(r.json()["id"])
    assert st["applicant"] == {"id": st["applicant"]["id"], "name": "Wanjiru", **FORM}
    assert (st["question_set"], st["language"], st["mode"]) == ("v2", "kik", "live")


def test_v2_interview_needs_the_applicant_form(client):
    for body in (None, {"applicant_name": "x"}):
        r = client.post("/api/interviews", json=body)
        assert r.status_code == 422
        assert "applicant form" in r.json()["detail"]


def test_v1_interview_needs_no_form(client, state):
    r = client.post("/api/interviews", json={"question_set": "v1"})
    assert r.status_code == 201
    st = state(r.json()["id"])
    assert st["question_set"] == "v1" and st["applicant"]["age"] is None


@pytest.mark.parametrize("field, bad", [("age", 12), ("age", "forty"), ("sex", "other"),
                                        ("education", 9), ("education", -1),
                                        ("marital_status", "engaged")])
def test_applicant_form_is_validated(client, field, bad):
    r = client.post("/api/interviews", json={"applicant": {**FORM, field: bad}})
    assert r.status_code == 422 and field in r.json()["detail"]


def test_language_and_mode_are_stored(client, state):
    iid = new_interview(client, language="en", mode="practice")
    st = state(iid)
    assert (st["language"], st["mode"]) == ("en", "practice")


def test_upload_outside_the_question_set_is_refused(client, interview, upload):
    r = upload(interview, 9)                     # v2 has eight questions
    assert r.status_code == 422
    assert r.json()["detail"] == "sentence_no: question set v2 has no question 9"


def test_upload_returns_202_before_transcription_finishes(client, asr, interview, upload, state):
    asr.gate = threading.Event()                 # hold the clip in the model
    r = upload(interview, 1)
    assert r.status_code == 202
    assert r.json() == {"id": r.json()["id"], "interview_id": interview,
                        "sentence_no": 1, "status": "queued"}
    assert asr.started.wait(5)
    assert state(interview)["responses"][0]["status"] == "transcribing"

    asr.gate.set()
    wait_until(lambda: state(interview)["counts"]["transcribed"] == 1)
    resp = state(interview)["responses"][0]
    assert resp["transcript"] == resp["transcript_asr"] == f"kikuyu response_{r.json()['id']}_s01"
    assert resp["asr_model"] == config.ASR_MODEL and resp["edited"] is False


@pytest.mark.parametrize("fmt, content_type", [
    ("wav", "audio/wav"),
    ("ogg", "audio/ogg"),
    ("stereo44k", "application/octet-stream"),   # no audio/* type: accepted by extension
    pytest.param("webm", "audio/webm;codecs=opus", marks=needs_ffmpeg),  # Chrome/Firefox
    pytest.param("m4a", "audio/mp4", marks=needs_ffmpeg),                # Safari
])
def test_audio_is_stored_as_16k_mono_wav(client, audio, interview, upload, state, fmt, content_type):
    r = upload(interview, 1, audio[fmt], content_type)
    assert r.status_code == 202, r.json()

    rid = r.json()["id"]
    assert uploads(interview) == [f"response_{rid}_s01.wav"]   # temp file cleaned up
    info = sf.info(str(config.UPLOADS_DIR / str(interview) / f"response_{rid}_s01.wav"))
    assert (info.samplerate, info.channels, info.subtype) == (16000, 1, "PCM_16")
    assert info.duration == pytest.approx(1.0, abs=0.05)
    wait_until(lambda: state(interview)["counts"]["transcribed"] == 1)


def test_responses_carry_topic_and_sort_by_sentence(client, interview, upload, state):
    for n in (8, 1, 6, 2):
        assert upload(interview, n).status_code == 202
    wait_until(lambda: state(interview)["counts"] == {"queued": 0, "transcribing": 0, "transcribed": 4, "failed": 0})
    rs = state(interview)["responses"]
    assert [x["sentence_no"] for x in rs] == [1, 2, 6, 8]
    assert [x["domain"] for x in rs] == ["household", "income", "guarantorship", "chama_borrowing"]
    assert {x["source"] for x in rs} == {"audio"}


def test_v1_responses_carry_the_manifest_domain(client, upload, state):
    iid = client.post("/api/interviews", json={"question_set": "v1"}).json()["id"]
    for n in (12, 1):
        assert upload(iid, n).status_code == 202
    wait_until(lambda: state(iid)["counts"]["transcribed"] == 2)
    assert [x["domain"] for x in state(iid)["responses"]] == ["household", "expenditure"]


def test_failed_transcription_is_reported(client, asr, interview, upload, state):
    asr.fail = True
    upload(interview, 1)
    wait_until(lambda: state(interview)["counts"]["failed"] == 1)
    resp = state(interview)["responses"][0]
    assert resp["status"] == "failed"
    assert "decoder exploded" in resp["error"]
    assert resp["transcript"] is None


def test_edit_transcript_is_recorded(client, ready_interview, state):
    before = state(ready_interview)["responses"][0]
    r = client.patch(f"/api/responses/{before['id']}", json={"transcript": "  corrected  "})
    assert r.status_code == 200
    after = r.json()
    assert after["transcript"] == "corrected"
    assert after["transcript_asr"] == before["transcript"]      # model output kept
    assert after["edited"] is True and after["edited_at"] is not None
    assert state(ready_interview)["responses"][0]["edited"] is True


def test_failed_clip_can_be_transcribed_by_hand(client, asr, interview, upload, state):
    asr.fail = True
    rid = upload(interview, 1).json()["id"]
    wait_until(lambda: state(interview)["counts"]["failed"] == 1)

    r = client.patch(f"/api/responses/{rid}", json={"transcript": "typed by reviewer"})

    assert r.status_code == 200
    assert r.json()["status"] == "transcribed" and r.json()["error"] is None
    assert r.json()["transcript_asr"] is None and r.json()["edited"] is True
