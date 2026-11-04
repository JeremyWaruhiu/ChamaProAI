"""The migrations and the immutability triggers on real PostgreSQL.

Skipped unless CHAMAPRO_TEST_POSTGRES_URL points at a server the test may
create and drop a scratch database on (never Supabase production):

    CHAMAPRO_TEST_POSTGRES_URL=postgresql://postgres:pw@localhost:5432/postgres pytest tests/test_postgres.py

The rest of the suite runs on SQLite.
"""
import os
import secrets
from contextlib import contextmanager
from datetime import date

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from chamapro import config
from chamapro.api import ledger, profiles
from chamapro.api.db import (Applicant, AuditLog, Decision, Guarantor, Interview,
                             LoanApplication, Member, User, alembic_config, head_revision, init_db)

SERVER = os.getenv("CHAMAPRO_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not SERVER, reason="set CHAMAPRO_TEST_POSTGRES_URL to run")
GUARDED = {"assessments": "assessments are immutable", "decisions": "decisions are immutable",
           "audit_log": "audit_log is append-only",
           "member_profile_history": "member_profile_history is append-only",
           "account_entries": "account_entries is append-only"}


@contextmanager
def scratch_database():
    """A new, empty database on SERVER, dropped afterwards; yields its URL."""
    base = make_url(config._database_url(SERVER))
    name = f"chamapro_test_{secrets.token_hex(4)}"
    admin = create_engine(base, isolation_level="AUTOCOMMIT")
    with admin.connect() as c:
        c.exec_driver_sql(f"CREATE DATABASE {name}")
    try:
        yield base.set(database=name).render_as_string(hide_password=False)
    finally:
        with admin.connect() as c:
            c.exec_driver_sql(f"DROP DATABASE IF EXISTS {name} WITH (FORCE)")
        admin.dispose()


@pytest.fixture(scope="module")
def pg_url():
    with scratch_database() as url:
        yield url


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
        ledger.post_entry(db, member.id, "deposits", "deposit", 5000, "PG-D1", officer)
        profiles.save_profile(db, member, {"household_size": 4}, "registration", officer)
        db.commit()
        return {"interview_id": iv.id, "decision_id": d.id, "application_id": app.id}


def test_schema_is_at_head_and_init_db_accepts_it(engine):
    with engine.connect() as c:
        assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == head_revision()
    init_db(engine)          # at head: a no-op, no error


def test_init_db_refuses_to_migrate_postgres_implicitly():
    # Its own empty database, not a schema of the module's: the module's has been
    # migrated by the `engine` fixture by the time this runs in a full run, and
    # hiding it behind a search_path startup option fails wherever that option is
    # not honoured (PgBouncer, Supabase's pooler), so the test passed alone only.
    with scratch_database() as url:
        eng = create_engine(url)
        try:
            with pytest.raises(RuntimeError, match="alembic upgrade head"):
                init_db(eng)
            assert not inspect(eng).get_table_names()                  # nothing was created
        finally:
            eng.dispose()


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


def test_0004_on_postgres(engine, rows):
    """What SQLite alone cannot show: partial unique indexes, the conditional
    upsert behind the daily caps, and booleans in a real boolean column."""
    from datetime import timedelta

    from chamapro.api import pilot
    from chamapro.api.db import InterviewBooking, PilotDailyUsage, nairobi_today, utcnow

    with Session(engine) as db:
        member = db.scalar(select(Member).where(Member.member_no == "PG-1"))
        assert member.self_signed_up is False
        member.phone = "0712345678"
        db.flush()
        assert member.phone == "+254712345678"
        when = utcnow() + timedelta(days=1)
        kw = dict(application_id=rows["application_id"], member_id=member.id, language="en")
        db.add(InterviewBooking(starts_at=when, status="confirmed", **kw))
        db.flush()
        db.add(InterviewBooking(starts_at=when, status="cancelled", **kw))
        db.flush()              # a cancelled row holds no slot
        db.commit()
    with Session(engine) as db:
        db.add(InterviewBooking(starts_at=when, status="started", **kw))
        with pytest.raises(IntegrityError, match="uq_interview_bookings_slot"):
            db.commit()
    with Session(engine) as db:
        db.add(InterviewBooking(starts_at=when + timedelta(hours=1), status="requested", **kw))
        with pytest.raises(IntegrityError, match="uq_interview_bookings_open"):
            db.commit()
    with Session(engine) as db:
        day = nairobi_today()
        assert pilot._take(db, day, "all", 2) is True
        assert pilot._take(db, day, "all", 2) is True
        assert pilot._take(db, day, "all", 2) is False
        db.commit()
        assert db.get(PilotDailyUsage, (day, "all")).used == 2


def test_0004_stops_on_a_shared_number_on_postgres():
    with scratch_database() as url:
        cfg = alembic_config(url)
        command.upgrade(cfg, "0003")
        eng = create_engine(url)
        with eng.begin() as c:
            for i, phone in enumerate(("0712345678", "+254712345678", "0799000000", None)):
                c.execute(text("INSERT INTO members (member_no, full_name, phone, joined_on, created_at) "
                               "VALUES (:n, 'F', :p, '2020-01-01', now())"), {"n": f"M{i}", "p": phone})
        with pytest.raises(RuntimeError, match="member 1"):
            command.upgrade(cfg, "head")
        with eng.connect() as c:           # one transaction: not even the rewrite stayed
            assert c.execute(text("SELECT version_num FROM alembic_version")).scalar() == "0003"
            assert c.execute(text("SELECT phone FROM members WHERE member_no = 'M0'")).scalar() == "0712345678"
        with eng.begin() as c:
            c.execute(text("UPDATE members SET phone = NULL WHERE member_no = 'M1'"))
        command.upgrade(cfg, "head")
        with eng.connect() as c:
            assert c.execute(text("SELECT phone FROM members WHERE member_no = 'M0'")).scalar() == "+254712345678"
        eng.dispose()


def test_0005_on_postgres(engine, rows):
    """The ledger's constraints and queries on the real thing: the composite key,
    the CHECKs, a window function and a filtered count, and the partial index."""
    from chamapro.api.db import AccountEntry, GuarantorPledge, LoanAccount, MemberAccount, utcnow

    with Session(engine) as db:
        m = db.scalar(select(Member).where(Member.member_no == "PG-1"))
        other = Member(member_no="PG-3", full_name="Another", joined_on=date(2021, 1, 1))
        db.add(other)
        db.flush()
        ledger.post_entry(db, other.id, "deposits", "deposit", 9000, "PG-O1")
        ledger.post_entry(db, m.id, "share_capital", "deposit", 100, "PG-S1")
        ledger.post_entry(db, m.id, "transactional", "deposit", 300, "PG-T1")
        assert ledger.balances(db, m.id) == {"deposits": 5000, "share_capital": 100, "transactional": 300}
        assert [e.reference for e in ledger.last_entries(db, m.id)["transactional"]] == ["PG-T1"]
        assert ledger.deposits_balances(db, [m.id, other.id]) == {m.id: 5000, other.id: 9000}

        app = db.scalar(select(LoanApplication).where(LoanApplication.id == rows["application_id"]))
        assert ledger.rule_savings(db, [app])[app.id].from_ledger is False   # decided before these entries
        loan = ledger.issue_loan(db, other.id, 2000, 6, 400)
        db.add(Guarantor(loan_account_id=loan.id, member_id=m.id, full_name="F", member_no="PG-1", phone="0",
                         relationship_="x", amount_guaranteed_kes=1500, status="verified"))
        db.flush()
        cap = ledger.capacities(db, [m.id])[m.id]
        assert (cap.deposits_kes, cap.guaranteed_kes, cap.capacity_kes) == (5000, 1500, 3500)
        assert ledger.known_to_the_sacco(db, other.id) == (["active"], True, False)
        ledger.recover_guarantee(db, m.id, loan, 200, "PG-REC")
        assert ledger.known_to_the_sacco(db, m.id)[2] is True
        ledger.add_pledge(db, m.id, other.id)
        db.commit()
        account = db.scalar(select(MemberAccount).where(MemberAccount.member_id == m.id,
                                                        MemberAccount.kind == "deposits"))
        ids = (m.id, other.id, account.id, loan.id)

    def refused(row, match):
        with Session(engine) as db:
            db.add(row)
            with pytest.raises(IntegrityError, match=match):
                db.commit()

    entry = dict(account_id=ids[2], amount_kes=-1, posted_at=utcnow(), reference="PG-BAD")
    refused(AccountEntry(account_kind="deposits", entry_type="withdrawal", **entry),
            "ck_account_entries_no_deposit_withdrawal")
    refused(AccountEntry(account_kind="transactional", entry_type="loan_repayment", **entry),
            "fk_account_entries_account")           # it is a deposits account
    refused(AccountEntry(account_kind="deposits", entry_type="deposit", **entry), "ck_account_entries_sign")
    refused(GuarantorPledge(borrower_member_id=ids[0], guarantor_member_id=ids[1], status="active"),
            "uq_guarantor_pledges_active")
    with Session(engine) as db:         # a withdrawn pledge can be made again
        p = db.scalar(select(GuarantorPledge).where(GuarantorPledge.borrower_member_id == ids[0],
                                                    GuarantorPledge.guarantor_member_id == ids[1]))
        ledger.withdraw_pledge(p)
        db.commit()
        ledger.add_pledge(db, ids[0], ids[1])
        db.commit()
        assert db.get(LoanAccount, ids[3]).status == "active"


def test_0005_keeps_guarantors_on_postgres():
    """The one existing table it alters, up and down, with rows in it."""
    with scratch_database() as url:
        cfg = alembic_config(url)
        command.upgrade(cfg, "0004")
        eng = create_engine(url)
        with eng.begin() as c:
            c.execute(text("INSERT INTO users (id, username, password_hash, role, is_active, created_at) "
                           "VALUES (1, 'o', 'x', 'officer', true, now())"))
            c.execute(text("INSERT INTO members (id, member_no, full_name, joined_on, created_at) "
                           "VALUES (1, 'M-1', 'F', '2020-01-01', now()), (2, 'm-1', 'G', '2020-01-01', now())"))
            c.execute(text("INSERT INTO loan_applications (id, member_id, amount_requested_kes, purpose, "
                           "term_months, sacco_savings_kes, status, created_by, created_at, updated_at) "
                           "VALUES (1, 1, 100, 'p', 6, 10, 'draft', 1, now(), now())"))
            c.execute(text("INSERT INTO guarantors (id, application_id, full_name, member_no, phone, relationship, "
                           "amount_guaranteed_kes, status, submitted_at) "
                           "VALUES (1, 1, 'G', 'M-1', '07', 'x', 5, 'pending', now())"))
        command.upgrade(cfg, "0005")     # two member numbers differ only by case: the lower id
        with eng.connect() as c:
            assert c.execute(text("SELECT member_id FROM guarantors")).scalar() == 1
            insp = inspect(eng)
            assert next(col for col in insp.get_columns("guarantors")
                        if col["name"] == "application_id")["nullable"] is True
        with eng.begin() as c:
            c.execute(text("INSERT INTO member_accounts (id, member_id, kind, created_at) "
                           "VALUES (1, 1, 'deposits', now())"))
            c.execute(text("INSERT INTO account_entries (account_id, account_kind, entry_type, amount_kes, "
                           "posted_at, reference, created_at) VALUES (1, 'deposits', 'deposit', 5, now(), 'r', now())"))
        command.downgrade(cfg, "0004")
        insp = inspect(eng)
        assert "account_entries" not in insp.get_table_names()
        assert next(col for col in insp.get_columns("guarantors")
                    if col["name"] == "application_id")["nullable"] is False
        with eng.connect() as c:
            assert c.execute(text("SELECT count(*) FROM guarantors")).scalar() == 1
            assert c.execute(text("SELECT count(*) FROM pg_trigger WHERE tgname LIKE 'account_entries%'")).scalar() == 0
        command.upgrade(cfg, "head")
        eng.dispose()


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
