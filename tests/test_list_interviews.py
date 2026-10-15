"""GET /api/interviews: the dashboard's interview list."""
from conftest import wait_until


def listed(client, interview_id):
    r = client.get("/api/interviews")
    assert r.status_code == 200
    return next(x for x in r.json() if x["id"] == interview_id)


def test_new_interview_is_listed_empty(client, state):
    iid = client.post("/api/interviews", json={"applicant_name": "Njeri"}).json()["id"]
    item = listed(client, iid)
    assert item == {"id": iid, "applicant_name": "Njeri",
                    "created_at": state(iid)["created_at"], "status": "open",
                    "responses_recorded": 0, "questions_total": 40,
                    "counts": {"queued": 0, "transcribing": 0, "transcribed": 0, "failed": 0},
                    "risk_class": None}


def test_unnamed_applicant_is_null(client):
    iid = client.post("/api/interviews").json()["id"]
    assert listed(client, iid)["applicant_name"] is None


def test_counts_follow_transcription(client, asr, interview, upload, state):
    asr.fail = False
    upload(interview, 1)
    upload(interview, 2)
    wait_until(lambda: state(interview)["counts"]["transcribed"] == 2)
    asr.fail = True
    upload(interview, 3)
    wait_until(lambda: state(interview)["counts"]["failed"] == 1)

    item = listed(client, interview)
    assert item["responses_recorded"] == 3
    assert item["counts"] == {"queued": 0, "transcribing": 0, "transcribed": 2, "failed": 1}
    assert item["status"] == "open" and item["risk_class"] is None


def test_assessed_interview_shows_risk_class(client, assessed_interview):
    item = listed(client, assessed_interview)
    assert item["status"] == "assessed"
    assert item["risk_class"] == "Medium"
    assert item["responses_recorded"] == 3


def test_newest_first(client):
    ids = [client.post("/api/interviews").json()["id"] for _ in range(3)]
    order = [x["id"] for x in client.get("/api/interviews").json()]
    assert [i for i in order if i in ids] == ids[::-1]
