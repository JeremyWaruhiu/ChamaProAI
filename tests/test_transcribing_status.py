"""Reads distinguish "queued" (waiting) from "transcribing" (in the model now).

The database stores both as queued; only the clip the worker holds is
reported as transcribing.
"""
import threading

from chamapro.api.db import Response, SessionLocal

from conftest import wait_until


def statuses(state, interview_id):
    return {x["sentence_no"]: x["status"] for x in state(interview_id)["responses"]}


def listed(client, interview_id):
    return next(x for x in client.get("/api/interviews").json() if x["id"] == interview_id)


def test_clip_in_the_model_is_transcribing_the_rest_queued(client, asr, interview, upload, state):
    asr.gate = threading.Event()
    upload(interview, 1)
    assert asr.started.wait(5)
    upload(interview, 2)
    upload(interview, 3)

    st = state(interview)
    assert statuses(state, interview) == {1: "transcribing", 2: "queued", 3: "queued"}
    assert st["counts"] == {"queued": 2, "transcribing": 1, "transcribed": 0, "failed": 0}
    item = listed(client, interview)
    assert item["counts"] == st["counts"] and item["responses_recorded"] == 3

    asr.gate.set()
    wait_until(lambda: state(interview)["counts"]["transcribed"] == 3)
    assert state(interview)["counts"]["transcribing"] == 0


def test_status_moves_to_the_next_clip(client, asr, interview, upload, state):
    asr.gate = threading.Event()
    upload(interview, 1)
    assert asr.started.wait(5)
    upload(interview, 2)

    first_gate, asr.gate = asr.gate, threading.Event()   # clip 2 waits on a new gate
    asr.started.clear()
    first_gate.set()                     # let clip 1 finish ...
    assert asr.started.wait(5)           # ... and the worker take clip 2
    wait_until(lambda: statuses(state, interview) == {1: "transcribed", 2: "transcribing"})


def test_other_interviews_show_no_transcribing(client, asr, upload, state):
    busy = client.post("/api/interviews").json()["id"]
    idle = client.post("/api/interviews").json()["id"]
    asr.gate = threading.Event()
    upload(busy, 1)
    assert asr.started.wait(5)
    upload(idle, 1)

    assert statuses(state, busy) == {1: "transcribing"}
    assert statuses(state, idle) == {1: "queued"}
    assert listed(client, idle)["counts"]["transcribing"] == 0


def test_queued_row_not_in_the_worker_is_queued(client, asr, interview, state, wav):
    with SessionLocal() as db:           # stored as queued, never handed to the worker
        db.add(Response(interview_id=interview, sentence_no=9, audio_path=str(wav),
                        status="queued"))
        db.commit()
    assert statuses(state, interview) == {9: "queued"}
    assert listed(client, interview)["counts"]["transcribing"] == 0


def test_transcribing_is_not_stored(client, asr, interview, upload, state):
    asr.gate = threading.Event()
    rid = upload(interview, 1).json()["id"]
    assert asr.started.wait(5)
    assert statuses(state, interview) == {1: "transcribing"}
    with SessionLocal() as db:
        assert db.get(Response, rid).status == "queued"


def test_assess_still_waits_for_a_transcribing_clip(client, asr, interview, upload):
    asr.gate = threading.Event()
    upload(interview, 5)
    assert asr.started.wait(5)
    r = client.post(f"/api/interviews/{interview}/assess")
    assert r.status_code == 409 and "still being transcribed" in r.json()["detail"]
