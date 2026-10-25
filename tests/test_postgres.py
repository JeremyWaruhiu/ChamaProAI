"""The migrations and the immutability triggers on real PostgreSQL.

Skipped unless CHAMAPRO_TEST_POSTGRES_URL points at a server the test may
create and drop a scratch database on (never Supabase production):

    CHAMAPRO_TEST_POSTGRES_URL=postgresql://postgres:pw@localhost:5432/postgres pytest tests/test_postgres.py

The rest of the suite runs on SQLite.
"""
import os
import secrets
from datetime import date

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from chamapro import config
from chamapro.api.db import (Applicant, AuditLog, Decision, Guarantor, Interview,
                             LoanApplication, Member, User, alembic_config, init_db)

SERVER = os.getenv("CHAMAPRO_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not SERVER, reason="set CHAMAPRO_TEST_POSTGRES_URL to run")
GUARDED = {"assessments": "assessments are immutable", "decisions": "decisions are immutable",
           "audit_log": "audit_log is append-only"}


@pytest.fixture(scope="module")
def pg_url():
    base = make_url(config._database_url(SERVER))
    name = f"chamapro_test_{secrets.token_hex(4)}"
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.exec_driver_sql(f"CREATE DATABASE {name}")
    url = base.set(database=name).render_as_string(hide_password=False)
    try:
        yield url
    finally:
        with admin.connect() as c:
            c.exec_driver_sql(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        admin.dispose()


@pytest.fixture(scope="module")
def engine(pg_url):
    command.upgrade(alembic_config(pg_url), "head")
    eng = create_engine(pg_url)
    yield eng
    eng.dispose()


@pytest.fixture(scope="module")
def rows(engine):
    """One of everything, written through the ORM."""
    with Session(engine) as db:
        officer = User(username="pg_officer", password_hash="x", role="officer")
        member = Member(member_no="PG-1", full_name="Fictional Member", joined_on=date(2020, 1, 1))
        iv = Interview(applicant=Applicant(name="pg"), status="assessed")
        db.add_all([officer, member, iv])
        db.flush()
        db.execute(text(
            "INSERT INTO assessments (interview_id, risk_class, probabilities, feature_vector, "
            "contributions, extracted, extraction_completeness, features_populated, features_total, "
            "features_not_extractable, extraction_model, model_file, model_sha256, created_at) "
            "VALUES (:i, 'Low', '{}', '{}', '[]', '{}', 0.5, 1, 2, '[]', 'g', 'c', 'x', now())"),
            {"i": iv.id})
        app = LoanApplication(member=member, amount_requested_kes=1000, purpose="seed",
                              term_months=6, sacco_savings_kes=500, status="guarantor_required",
                              interview=iv, created_by=officer.id)
        d = Decision(interview=iv, decision="approve", outcome="approve_with_guarantor",
                     approved_amount_kes=1000, guarantors_required=2, officer_notes="n")
        db.add_all([app, d, AuditLog(actor_user_id=officer.id, action="t", entity="t",
                                     entity_id=1, details={"k": 1})])
        db.flush()
        db.add(Guarantor(application=app, full_name="G", member_no="PG-2", phone="0712345678",
                         relationship_="friend", amount_guaranteed_kes=500))
        db.commit()
        return {"interview_id": iv.id, "decision_id": d.id, "application_id": app.id}


def test_schema_is_at_head_and_init_db_accepts_it(engine):
    with engine.connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0002"
    init_db(engine)          # at head: a no-op, no error


def test_init_db_refuses_to_migrate_postgres_implicitly(pg_url):
    other = create_engine(pg_url)
    with other.begin() as c:
        c.exec_driver_sql("CREATE SCHEMA empty_one")
    eng = create_engine(pg_url, connect_args={"options": "-csearch_path=empty_one"})
    with pytest.raises(RuntimeError, match="alembic upgrade head"):
        init_db(eng)
    eng.dispose()
    other.dispose()


def test_every_table_has_row_level_security(engine):
    with engine.connect() as c:
        off = c.execute(text("SELECT relname FROM pg_class JOIN pg_namespace n "
                             "ON n.oid = relnamespace WHERE nspname = 'public' "
                             "AND relkind = 'r' AND NOT relrowsecurity")).scalars().all()
    assert off == []


@pytest.mark.parametrize("table", sorted(GUARDED))
@pytest.mark.parametrize("sql", ["UPDATE {t} SET id = id", "DELETE FROM {t}", "TRUNCATE {t}"])
def test_triggers_reject_changes(engine, rows, table, sql):
    with engine.connect() as c:
        with pytest.raises(IntegrityError, match=GUARDED[table]):
            c.execute(text(sql.format(t=table)))
        c.rollback()
        assert c.execute(text(f"SELECT count(*) FROM {table}")).scalar() >= 1


def test_orm_cannot_update_a_decision(engine, rows):
    with Session(engine) as db:
        d = db.get(Decision, rows["decision_id"])
        d.officer_notes = "rewritten"
        with pytest.raises(IntegrityError, match="decisions are immutable"):
            db.commit()


def test_mutable_tables_still_change(engine, rows):
    with Session(engine) as db:
        app = db.get(LoanApplication, rows["application_id"])
        app.status = "guarantor_submitted"
        app.guarantors[0].status = "verified"
        db.commit()
    with Session(engine) as db:
        assert db.get(LoanApplication, rows["application_id"]).status == "guarantor_submitted"


def test_check_constraints(engine, rows):
    with engine.connect() as c:
        with pytest.raises(IntegrityError):
            c.execute(text("UPDATE loan_applications SET status = 'bogus'"))
        c.rollback()


def test_downgrade_and_upgrade_again(pg_url, engine, rows):
    engine.dispose()
    command.downgrade(alembic_config(pg_url), "0001")
    insp = inspect(create_engine(pg_url))
    assert "audit_log" not in insp.get_table_names()
    assert "outcome" not in {c["name"] for c in insp.get_columns("decisions")}
    command.upgrade(alembic_config(pg_url), "head")
    with create_engine(pg_url).connect() as c:     # the row survives; its new columns do not
        assert c.execute(text("SELECT decision, outcome FROM decisions")).one() == ("approve", None)
