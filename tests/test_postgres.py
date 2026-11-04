"""The migrations and the immutability triggers on real PostgreSQL.

Skipped unless CHAMAPRO_TEST_POSTGRES_URL points at a server the test may
create and drop a scratch database on (never Supabase production):

    CHAMAPRO_TEST_POSTGRES_URL=postgresql://postgres:pw@localhost:5432/postgres pytest tests/test_postgres.py

The rest of the suite runs on SQLite.
"""
import os
import secrets
import threading
import time
from contextlib import contextmanager
from datetime import date

import pytest
from alembic import command
from sqlalchemy import create_engine, event, inspect, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from chamapro import config
from chamapro.api import decisions, ledger, profiles, self_service
from chamapro.api.db import (Applicant, AuditLog, Decision, Guarantor, Interview, LoanAccount,
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


# --- Automatic decisions: what only real row locks can show --------------------------------

@pytest.fixture
def stand_in_model(monkeypatch):
    """Low every time, and slow enough that two requests really overlap."""
    import pandas as pd
    import score_interview

    def score(_):
        time.sleep(0.2)
        return score_interview.Scored(
            {"risk_class": "Low", "probabilities": {"Low": 0.6, "Medium": 0.3, "High": 0.1}, "top_contributions": [],
             "extraction_completeness": 0.9, "features_populated": 30, "features_total": 35},
            pd.DataFrame([{"age": 40.0}]), "classifier.joblib", "0" * 64)
    monkeypatch.setattr(decisions, "score_features", score)


PROFILE = {"monthly_income_kes": 90000, "household_size": 4, "chama_loan_use": 0, "income_sources": {"employed": 1}}


def add_person(db, label: str, deposits: int = 0, profile: bool = False) -> Member:
    m = Member(member_no=f"PGD-{label}-{secrets.token_hex(3)}", full_name=f"Fictional {label}", joined_on=date(2020, 1, 1),
               phone=f"07{secrets.randbelow(10 ** 8):08d}")
    db.add(m)
    db.flush()
    if deposits:
        ledger.post_entry(db, m.id, "deposits", "deposit", deposits, f"PG-{secrets.token_hex(4)}")
    if profile:
        p = profiles.save_profile(db, m, PROFILE, "registration", None)
        p.income_verified_at, p.income_verified_by = p.income_updated_at, "pg"
    return m


def together(engine, jobs):
    """Run each job(session) on its own connection, released at the same moment; each
    outcome is what it returned or raised."""
    gate, out = threading.Barrier(len(jobs)), [None] * len(jobs)

    def run(i, job):
        with Session(engine, expire_on_commit=False) as db:
            gate.wait()
            try:
                out[i] = job(db)
            except Exception as e:
                out[i] = e
    threads = [threading.Thread(target=run, args=(i, j)) for i, j in enumerate(jobs)]
    [t.start() for t in threads]
    [t.join(60) for t in threads]
    assert not any(t.is_alive() for t in threads), "deadlocked"
    return out


def commit_for(member_id: int, actor_id: int, amount: int, key: str, term: int = 12):
    def job(db):
        member, actor = db.get(Member, member_id), db.get(User, actor_id)
        ev = decisions.evaluate(db, member, decisions.LoanRequest(amount, "School fees", term))
        return self_service.commit(db, ev, key, actor)
    return job


def test_two_loans_cannot_spend_the_same_capacity(engine, stand_in_model):
    """Each borrower's guarantors can cover either loan, not both. Their pledges are in
    opposite orders, which without a fixed locking order would be a deadlock as well."""
    with Session(engine, expire_on_commit=False) as db:
        actor = User(username=f"pg_{secrets.token_hex(3)}", password_hash="x", role="officer")
        db.add(actor)
        g1, g2 = add_person(db, "G1", 12000), add_person(db, "G2", 12000)
        a, b = add_person(db, "A", 10000, True), add_person(db, "B", 10000, True)
        ledger.add_pledge(db, a.id, g1.id), ledger.add_pledge(db, a.id, g2.id)
        ledger.add_pledge(db, b.id, g2.id), ledger.add_pledge(db, b.id, g1.id)
        db.commit()
        ids = actor.id, a.id, b.id, g1.id, g2.id
    actor_id, a_id, b_id, g1_id, g2_id = ids
    # Each asks 30,000: 20,000 beyond their own 10,000. The two guarantors hold 24,000.
    out = together(engine, [commit_for(a_id, actor_id, 30000, "race-a"), commit_for(b_id, actor_id, 30000, "race-b")])
    won = [r for r in out if isinstance(r, dict) and r["outcome"] == "approve"]
    lost = [r for r in out if isinstance(r, self_service.CannotCommit)]
    assert len(won) == 1 and len(lost) == 1, out
    with Session(engine) as db:
        caps = ledger.capacities(db, [g1_id, g2_id])
        assert sum(c.guaranteed_kes for c in caps.values()) == 20000
        assert all(c.guaranteed_kes <= c.deposits_kes for c in caps.values())
        loans_now = db.scalars(select(LoanAccount).where(LoanAccount.member_id.in_([a_id, b_id]))).all()
        assert len(loans_now) == 1


def test_a_double_submit_at_the_same_moment_pays_out_once(engine, stand_in_model):
    with Session(engine, expire_on_commit=False) as db:
        actor = User(username=f"pg_{secrets.token_hex(3)}", password_hash="x", role="officer")
        db.add(actor)
        m = add_person(db, "D", 30000, True)
        g1, g2 = add_person(db, "DG1", 30000), add_person(db, "DG2", 30000)
        ledger.add_pledge(db, m.id, g1.id), ledger.add_pledge(db, m.id, g2.id)
        db.commit()
        actor_id, member_id = actor.id, m.id
    out = together(engine, [commit_for(member_id, actor_id, 40000, "double") for _ in range(4)])
    assert all(isinstance(r, dict) for r in out) and all(r == out[0] for r in out), out
    with Session(engine) as db:
        assert ledger.balances(db, member_id)["transactional"] == 40000
        assert len(db.scalars(select(LoanAccount).where(LoanAccount.member_id == member_id)).all()) == 1


def test_two_withdrawals_at_once_cannot_overdraw(engine):
    with Session(engine) as db:
        m = add_person(db, "W")
        ledger.post_entry(db, m.id, "transactional", "deposit", 1000, f"PG-{secrets.token_hex(4)}")
        db.commit()
        member_id = m.id

    def withdraw(db):
        ledger.lock_members(db, [member_id])
        time.sleep(0.1)
        entry = ledger.post_entry(db, member_id, "transactional", "withdrawal", -800, f"PG-{secrets.token_hex(4)}")
        db.commit()
        return entry.id
    out = together(engine, [withdraw, withdraw])
    assert sum(isinstance(r, ledger.LedgerError) for r in out) == 1, out
    with Session(engine) as db:
        assert ledger.balances(db, member_id)["transactional"] == 200


def test_lock_members_really_locks_and_in_order(pg_url, engine):
    """A second transaction cannot take a row the first holds."""
    with Session(engine) as db:
        a, b = add_person(db, "L1"), add_person(db, "L2")
        ledger.account_of(db, a.id, "deposits")
        db.commit()
        ids = [a.id, b.id]
    statements = []
    other = create_engine(pg_url, connect_args={"options": "-c lock_timeout=200"})

    @event.listens_for(engine, "before_cursor_execute")
    def seen(conn, cursor, statement, *_):
        if "FOR UPDATE" in statement:
            statements.append(statement)
    try:
        with Session(engine) as holder:
            ledger.lock_members(holder, reversed(ids))
            with other.connect() as c, pytest.raises(OperationalError):
                c.execute(text("SELECT id FROM members WHERE id = :i FOR UPDATE"), {"i": ids[0]})
    finally:
        event.remove(engine, "before_cursor_execute", seen)
        other.dispose()
    assert len(statements) == 2
    assert "ORDER BY members.id" in statements[0] and "ORDER BY member_accounts.id" in statements[1]


def test_0006_migrates_and_the_ledger_stays_guarded(engine):
    with engine.connect() as c:
        assert c.execute(text("SELECT role, is_active FROM users WHERE username = 'system'")).one() == ("system", False)
        for table in ("self_service_runs", "idempotency_keys"):
            assert c.execute(text("SELECT relrowsecurity FROM pg_class WHERE relname = :t"), {"t": table}).scalar() is True
    with pytest.raises(IntegrityError, match="append-only"):
        with engine.begin() as c:
            c.execute(text("UPDATE account_entries SET amount_kes = 1"))
    with Session(engine) as db:
        m = add_person(db, "M")
        entry = ledger.post_entry(db, m.id, "transactional", "deposit", 500, f"PG-{secrets.token_hex(4)}")
        ledger.post_entry(db, m.id, "transactional", "loan_reversal", -100, f"PG-{secrets.token_hex(4)}")
        db.commit()
        assert entry.id
    with Session(engine) as db, pytest.raises(IntegrityError, match="ck_account_entries"):
        m2 = add_person(db, "M2")
        ledger.post_entry(db, m2.id, "deposits", "loan_reversal", 100, f"PG-{secrets.token_hex(4)}")
