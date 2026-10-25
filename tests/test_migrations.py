"""Alembic: a fresh database, a pre-Alembic one with rows (kept exactly), the
backup taken first, atomic failure, the models matching the migrations, and
the PostgreSQL trigger SQL."""
import io
import sqlite3
from contextlib import redirect_stdout

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from chamapro.api import schemas as s
from chamapro.api.db import Base, Decision, alembic_config, head_revision, init_db, schema_revision

from legacy_schema import make_legacy_db

LEGACY_ROWS = """
INSERT INTO applicants (id, name, created_at) VALUES (1, 'Demo applicant (S01)', '2026-10-01 08:00:00');
INSERT INTO interviews (id, applicant_id, status, created_at) VALUES (1, 1, 'assessed', '2026-10-01 08:00:00');
INSERT INTO interviews (id, applicant_id, status, created_at, question_set, language, mode)
    VALUES (2, 1, 'assessed', '2026-10-02 08:00:00', 'v2', 'en', 'practice');
INSERT INTO responses (id, interview_id, sentence_no, audio_path, status, edited, created_at, transcript)
    VALUES (1, 1, 1, '/data/uploads/1/response_1_s01.wav', 'transcribed', 0, '2026-10-01 08:00:00', 'njeka');
INSERT INTO assessments (id, interview_id, risk_class, probabilities, feature_vector, contributions,
    extracted, extraction_completeness, features_populated, features_total, features_not_extractable,
    extraction_model, model_file, model_sha256, created_at)
    VALUES (1, 1, 'Medium', '{"Low": 0.2}', '{"age": 42.0}', '[]', '{}', 0.5, 1, 40, '[]', 'g',
            'classifier.joblib', 'abc', '2026-10-01 09:00:00');
INSERT INTO decisions (id, interview_id, decision, note, created_at, decided_by)
    VALUES (1, 1, 'refer', 'Spoke to the chama chair.', '2026-10-01 10:00:00', 'officer1');
INSERT INTO users (id, username, password_hash, role, is_active, created_at)
    VALUES (1, 'admin', 'scrypt$x', 'admin', 1, '2026-10-01 07:00:00');
"""
LEGACY_TABLES = ["applicants", "interviews", "responses", "assessments", "decisions", "users",
                 "sessions"]


def dump(path, tables=LEGACY_TABLES):
    con = sqlite3.connect(path)
    try:
        out = {}
        for t in tables:
            cols = [r[1] for r in con.execute(f"PRAGMA table_info({t})")]
            out[t] = con.execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall(), cols
        return out
    finally:
        con.close()


@pytest.fixture
def legacy(tmp_path):
    path = tmp_path / "chamapro.db"
    make_legacy_db(path, LEGACY_ROWS)
    return path


def test_fresh_database_reaches_head(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'new.db'}")
    init_db(engine)
    assert schema_revision(engine) == head_revision() == "0002"
    names = set(inspect(engine).get_table_names())
    assert {"members", "loan_applications", "guarantors", "audit_log", "alembic_version"} <= names
    assert not list(tmp_path.glob("*.bak"))                  # nothing to back up


def test_legacy_rows_survive_exactly(legacy, tmp_path):
    before = dump(legacy)
    engine = create_engine(f"sqlite:///{legacy}")
    init_db(engine)
    init_db(engine)                                         # at head: a no-op
    after = dump(legacy)
    for t in LEGACY_TABLES:
        rows, cols = before[t]
        new_rows, new_cols = after[t]
        assert new_cols[:len(cols)] == cols
        assert [r[:len(cols)] for r in new_rows] == rows, t
    assert after["decisions"][1][len(before["decisions"][1]):] == \
        ["outcome", "approved_amount_kes", "guarantors_required", "officer_notes", "member_message"]
    assert len(list(tmp_path.glob("chamapro.db.pre-0002-*.bak"))) == 1   # backed up once


def test_backup_holds_the_pre_migration_database(legacy, tmp_path):
    before = dump(legacy)
    init_db(create_engine(f"sqlite:///{legacy}"))
    (bak,) = tmp_path.glob("*.bak")
    assert dump(bak) == before
    con = sqlite3.connect(bak)
    assert con.execute("SELECT name FROM sqlite_master WHERE name = 'alembic_version'").fetchone() is None
    con.close()


def test_existing_decisions_stay_readable(legacy):
    engine = create_engine(f"sqlite:///{legacy}")
    init_db(engine)
    with Session(engine) as db:
        out = s.DecisionOut.model_validate(db.get(Decision, 1)).model_dump()
    assert out["decision"] == out["outcome"] == "refer"
    assert out["note"] == out["officer_notes"] == "Spoke to the chama chair."
    assert out["decided_by"] == "officer1" and out["approved_amount_kes"] is None


@pytest.mark.parametrize("sql, message", [
    ("UPDATE assessments SET risk_class = 'Low'", "assessments are immutable"),
    ("DELETE FROM decisions", "decisions are immutable"),
    ("UPDATE decisions SET outcome = 'approve'", "decisions are immutable"),
    ("DELETE FROM audit_log", "audit_log is append-only")])
def test_triggers_guard_migrated_rows(legacy, sql, message):
    init_db(create_engine(f"sqlite:///{legacy}"))
    con = sqlite3.connect(legacy, isolation_level=None)
    con.execute("INSERT INTO audit_log (action, entity, details, created_at) "
                "VALUES ('t', 't', '{}', '2026-10-26')")      # row triggers need a row
    try:
        with pytest.raises(sqlite3.IntegrityError, match=message):
            con.execute(sql)
    finally:
        con.close()


def test_a_failed_migration_changes_nothing(legacy):
    con = sqlite3.connect(legacy)
    con.execute("CREATE TABLE members (id INTEGER PRIMARY KEY)")    # 0002 will collide with it
    con.commit()
    con.close()
    before = dump(legacy, LEGACY_TABLES + ["members"])
    with pytest.raises(Exception, match="members"):
        init_db(create_engine(f"sqlite:///{legacy}"))
    assert dump(legacy, LEGACY_TABLES + ["members"]) == before
    names = set(inspect(create_engine(f"sqlite:///{legacy}")).get_table_names())
    assert "alembic_version" not in names and "audit_log" not in names


def test_models_match_the_migrations(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'm.db'}")
    init_db(engine)
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_postgres_sql_has_the_triggers_and_row_level_security():
    out = io.StringIO()
    with redirect_stdout(out):
        command.upgrade(alembic_config("postgresql+psycopg://u:p@localhost/x"), "head", sql=True)
    sql = out.getvalue()
    assert "CREATE OR REPLACE FUNCTION chamapro_reject_change()" in sql
    assert "ERRCODE = 'integrity_constraint_violation'" in sql
    for table, message in [("assessments", "assessments are immutable"),
                           ("decisions", "decisions are immutable"),
                           ("audit_log", "audit_log is append-only")]:
        for when, level in [("UPDATE", "ROW"), ("DELETE", "ROW"), ("TRUNCATE", "STATEMENT")]:
            assert (f"CREATE TRIGGER {table}_no_{when.lower()} BEFORE {when} ON {table} "
                    f"FOR EACH {level} EXECUTE FUNCTION chamapro_reject_change('{message}')") in sql
    for table in ["applicants", "interviews", "responses", "assessments", "decisions", "users",
                  "sessions", "members", "loan_applications", "guarantors", "audit_log"]:
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in sql


def test_postgres_is_never_migrated_implicitly(monkeypatch):
    class FakePG:
        dialect = type("D", (), {"name": "postgresql"})()
    monkeypatch.setattr("chamapro.api.db.schema_revision", lambda bind: None)
    with pytest.raises(RuntimeError, match="alembic upgrade head"):
        init_db(FakePG())


def test_database_url_accepts_supabase_style_urls():
    from chamapro import config
    assert config._database_url(None).startswith("sqlite:///")
    assert config._database_url("postgresql://u:p@aws-0-eu.pooler.supabase.com:5432/postgres") == \
        "postgresql+psycopg://u:p@aws-0-eu.pooler.supabase.com:5432/postgres"
    assert config._database_url("postgres://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
    assert config._database_url("postgresql+psycopg://u:p@h/db") == "postgresql+psycopg://u:p@h/db"
