"""POST /api/interviews/{id}/decision: the officer decides, after the model
recommends, once."""
import sqlite3

import pytest

from chamapro import config


def decide(client, interview_id, decision="approve", note=None):
    body = {"decision": decision} | ({"note": note} if note is not None else {})
    return client.post(f"/api/interviews/{interview_id}/decision", json=body)


@pytest.mark.parametrize("decision", ["approve", "decline", "refer"])
def test_decision_is_recorded(client, assessed_interview, state, decision):
    r = decide(client, assessed_interview, decision, "  Spoke to her chama chair.  ")
    assert r.status_code == 201
    d = r.json()
    assert d["decision"] == decision
    assert d["note"] == "Spoke to her chama chair."
    assert d["created_at"].endswith("Z")
    st = state(assessed_interview)
    assert st["decision"] == d
    assert st["assessment"]["risk_class"] == "Medium"        # model's view untouched


def test_note_is_optional_and_blank_is_null(client, assessed_interview):
    assert decide(client, assessed_interview, "refer", "   ").json()["note"] is None


def test_officer_may_disagree_with_the_model(client, assessed_interview, state):
    # the model said Medium (refer); the officer approves, and both are kept
    assert decide(client, assessed_interview, "approve", "Known member, 10 years").status_code == 201
    st = state(assessed_interview)
    assert (st["assessment"]["risk_class"], st["decision"]["decision"]) == ("Medium", "approve")


def test_decision_shows_in_the_list(client, assessed_interview):
    decide(client, assessed_interview, "decline")
    item = next(x for x in client.get("/api/interviews").json() if x["id"] == assessed_interview)
    assert (item["risk_class"], item["decision"]) == ("Medium", "decline")


def test_second_decision_is_409(client, assessed_interview, state):
    decide(client, assessed_interview, "approve")
    r = decide(client, assessed_interview, "decline")
    assert r.status_code == 409 and "immutable" in r.json()["detail"]
    assert state(assessed_interview)["decision"]["decision"] == "approve"


def test_decision_before_assessment_is_409(client, ready_interview, state):
    r = decide(client, ready_interview)
    assert r.status_code == 409 and "no assessment yet" in r.json()["detail"]
    assert state(ready_interview)["decision"] is None


def test_unknown_interview_is_404(client):
    r = decide(client, 999999)
    assert r.status_code == 404 and r.json() == {"detail": "interview 999999 not found"}


@pytest.mark.parametrize("body", [{}, {"decision": "maybe"}, {"decision": "APPROVE"},
                                  {"decision": "approve", "note": "x" * 2001}])
def test_invalid_body_is_422(client, assessed_interview, body):
    r = client.post(f"/api/interviews/{assessed_interview}/decision", json=body)
    assert r.status_code == 422 and isinstance(r.json()["detail"], str)


@pytest.mark.parametrize("sql", ["UPDATE decisions SET decision = 'decline' WHERE interview_id = ?",
                                 "DELETE FROM decisions WHERE interview_id = ?"])
def test_database_rejects_changes_to_a_decision(client, assessed_interview, sql):
    decide(client, assessed_interview, "approve")
    con = sqlite3.connect(config.DB_PATH, isolation_level=None)
    try:
        with pytest.raises(sqlite3.IntegrityError, match="decisions are immutable"):
            con.execute(sql, (assessed_interview,))
        assert con.execute("SELECT decision FROM decisions WHERE interview_id = ?",
                           (assessed_interview,)).fetchone() == ("approve",)
    finally:
        con.close()
