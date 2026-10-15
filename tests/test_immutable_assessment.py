"""The assessment is the audit record (Chapter 4): once written, neither the
database nor the API will change it, or the responses it was built from."""
import sqlite3

import pytest
from sqlalchemy.exc import IntegrityError

from chamapro import config
from chamapro.api.db import Assessment, SessionLocal

from conftest import needs_classifier, uploads


@pytest.fixture
def raw():
    """A connection that bypasses the API. Autocommit, so a rejected statement
    leaves no open transaction holding the database lock."""
    con = sqlite3.connect(config.DB_PATH, isolation_level=None)
    yield con
    con.close()


def test_schema_has_the_four_tables_and_guard_triggers(client, raw):

    tables = {r[0] for r in raw.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    triggers = {r[0] for r in raw.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
    assert {"applicants", "interviews", "responses", "assessments"} <= tables
    assert {"assessments_no_update", "assessments_no_delete"} <= triggers


@pytest.mark.parametrize("sql", ["UPDATE assessments SET risk_class = 'Low' WHERE interview_id = ?",
                                 "DELETE FROM assessments WHERE interview_id = ?"])
def test_database_rejects_changes_outside_the_api(assessed_interview, raw, sql):
    with pytest.raises(sqlite3.IntegrityError, match="assessments are immutable"):
        raw.execute(sql, (assessed_interview,))
    row = raw.execute("SELECT risk_class FROM assessments WHERE interview_id = ?",
                      (assessed_interview,)).fetchone()
    assert row == ("Medium",)


def test_orm_cannot_update_an_assessment(assessed_interview):
    with SessionLocal() as db:
        a = db.query(Assessment).filter_by(interview_id=assessed_interview).one()
        a.risk_class = "Low"
        with pytest.raises(IntegrityError, match="assessments are immutable"):
            db.commit()


def test_reassess_is_409(client, assessed_interview, state):
    before = state(assessed_interview)["assessment"]
    r = client.post(f"/api/interviews/{assessed_interview}/assess")
    assert r.status_code == 409 and "immutable" in r.json()["detail"]
    assert state(assessed_interview)["assessment"] == before


def test_responses_are_frozen_after_assessment(client, assessed_interview, upload, state):
    rid = state(assessed_interview)["responses"][0]["id"]
    files = uploads(assessed_interview)

    r = client.patch(f"/api/responses/{rid}", json={"transcript": "rewritten"})
    assert r.status_code == 409 and "immutable" in r.json()["detail"]
    r = upload(assessed_interview, 20)
    assert r.status_code == 409 and "immutable" in r.json()["detail"]
    r = client.delete(f"/api/responses/{rid}")
    assert r.status_code == 409 and "immutable" in r.json()["detail"]

    assert state(assessed_interview)["responses"][0]["transcript"] != "rewritten"
    assert len(state(assessed_interview)["responses"]) == 3
    assert uploads(assessed_interview) == files


@needs_classifier
def test_real_assessment_is_immutable_too(client, gemini, ready_interview, raw):
    assert client.post(f"/api/interviews/{ready_interview}/assess").status_code == 201
    with pytest.raises(sqlite3.IntegrityError, match="assessments are immutable"):
        raw.execute("UPDATE assessments SET feature_vector = '{}' WHERE interview_id = ?",
                    (ready_interview,))
    assert client.post(f"/api/interviews/{ready_interview}/assess").status_code == 409
