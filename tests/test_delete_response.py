"""DELETE /api/responses/{id}: re-recording a clip before assessment."""
import threading

from chamapro.api import pipeline as pl

from conftest import needs_classifier, uploads, wait_until


def transcribed(state, interview_id, n=1):
    return lambda: state(interview_id)["counts"]["transcribed"] == n


def test_delete_transcribed_response_allows_reupload(client, asr, interview, upload, state):
    rid = upload(interview, 1).json()["id"]
    wait_until(transcribed(state, interview))
    assert uploads(interview) == [f"response_{rid}_s01.wav"]

    r = client.delete(f"/api/responses/{rid}")

    assert r.status_code == 200
    assert r.json() == {"id": rid, "interview_id": interview, "sentence_no": 1,
                        "was_queued": False}
    assert state(interview)["responses"] == []
    assert uploads(interview) == []
    assert upload(interview, 1).status_code == 202


def test_delete_queued_response_leaves_the_queue(client, asr, interview, upload, state):
    asr.gate = threading.Event()
    first = upload(interview, 1).json()["id"]
    assert asr.started.wait(5)                      # worker is busy on the first clip
    second = upload(interview, 2).json()["id"]
    with pl._cond:
        assert list(pl._pending) == [second]

    r = client.delete(f"/api/responses/{second}")

    assert r.status_code == 200 and r.json()["was_queued"] is True
    with pl._cond:
        assert second not in pl._pending
    assert uploads(interview) == [f"response_{first}_s01.wav"]

    asr.gate.set()
    wait_until(transcribed(state, interview))
    assert asr.calls == [f"response_{first}_s01.wav"]  # deleted clip never ran
    assert [x["id"] for x in state(interview)["responses"]] == [first]
    assert upload(interview, 2).status_code == 202


def test_delete_during_transcription_is_refused_then_succeeds(client, asr, interview, upload, state):
    asr.gate = threading.Event()
    rid = upload(interview, 1).json()["id"]
    assert asr.started.wait(5)

    r = client.delete(f"/api/responses/{rid}")

    assert r.status_code == 409
    assert "retry" in r.json()["detail"]
    assert r.headers["retry-after"] == "10"
    assert [x["id"] for x in state(interview)["responses"]] == [rid]
    assert uploads(interview) == [f"response_{rid}_s01.wav"]

    asr.gate.set()
    wait_until(transcribed(state, interview))
    assert client.delete(f"/api/responses/{rid}").status_code == 200
    assert uploads(interview) == []


@needs_classifier
def test_delete_after_assessment_is_refused(client, asr, gemini, interview, upload, state):
    rid = upload(interview, 1).json()["id"]
    wait_until(transcribed(state, interview))
    assert client.post(f"/api/interviews/{interview}/assess").status_code == 201

    r = client.delete(f"/api/responses/{rid}")

    assert r.status_code == 409
    assert "assessed" in r.json()["detail"]
    assert [x["id"] for x in state(interview)["responses"]] == [rid]
    assert uploads(interview) == [f"response_{rid}_s01.wav"]


def test_delete_unknown_response(client):
    r = client.delete("/api/responses/999999")
    assert r.status_code == 404
    assert r.json() == {"detail": "response 999999 not found"}
