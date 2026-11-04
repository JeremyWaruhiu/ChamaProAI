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
    assert schema_revision(engine) == head_revision() == "0007"
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
        # 0006 adds the system user; every row that was there stays exactly as it was.
        assert [r[:len(cols)] for r in new_rows if r[1] != "system"] == rows, t
    assert after["decisions"][1][len(before["decisions"][1]):] == \
        ["outcome", "approved_amount_kes", "guarantors_required", "officer_notes", "member_message", "policy_version"]
    assert len(list(tmp_path.glob("chamapro.db.pre-0007-*.bak"))) == 1   # backed up once


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


def at_0003(tmp_path, *members):
    """A database one revision back, holding these (id, phone) members."""
    path = tmp_path / "m.db"
    command.upgrade(alembic_config(f"sqlite:///{path}"), "0003")
    con = sqlite3.connect(path)
    con.executemany("INSERT INTO members (id, member_no, full_name, phone, joined_on, created_at) "
                    "VALUES (?, ?, 'F', ?, '2020-01-01', '2020-01-01')",
                    [(i, f"M-{i}", phone) for i, phone in members])
    con.commit()
    con.close()
    return path


def test_0004_rewrites_existing_phones_to_the_one_form(tmp_path):
    path = at_0003(tmp_path, (1, "0712345678"), (2, "+254712345679"), (3, "0112 345-678"),
                   (4, "254712345670"), (5, None), (6, ""), (7, "not a number"))
    init_db(create_engine(f"sqlite:///{path}"))
    con = sqlite3.connect(path)
    rows = dict(con.execute("SELECT id, phone FROM members").fetchall())
    con.close()
    assert rows == {1: "+254712345678", 2: "+254712345679", 3: "+254112345678", 4: "+254712345670",
                    5: None, 6: None, 7: "notanumber"}


def test_0004_stops_on_a_shared_number_and_changes_nothing(tmp_path):
    path = at_0003(tmp_path, (1, "0712345678"), (2, "+254712345678"), (3, "0799999999"))
    engine = create_engine(f"sqlite:///{path}")
    with pytest.raises(RuntimeError, match=r"member 1: \+254712345678; member 2: \+254712345678"):
        init_db(engine)
    assert schema_revision(engine) == "0003"
    con = sqlite3.connect(path)
    assert con.execute("SELECT phone FROM members ORDER BY id").fetchall() == \
        [("0712345678",), ("+254712345678",), ("0799999999",)]
    assert "self_signed_up" not in {r[1] for r in con.execute("PRAGMA table_info(members)")}
    con.close()


def test_phone_is_unique_only_when_present(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'p.db'}")
    init_db(engine)
    con = sqlite3.connect(tmp_path / "p.db")
    insert = ("INSERT INTO members (member_no, full_name, phone, joined_on, created_at, self_signed_up) "
              "VALUES (?, 'F', ?, '2020-01-01', '2020-01-01', 0)")
    con.execute(insert, ("A", None))
    con.execute(insert, ("B", None))
    con.execute(insert, ("C", "+254712345678"))
    with pytest.raises(sqlite3.IntegrityError, match="members.phone"):
        con.execute(insert, ("D", "+254712345678"))
    con.close()


def test_0004_downgrades_and_comes_back(tmp_path):
    path = tmp_path / "d.db"
    url = f"sqlite:///{path}"
    command.upgrade(alembic_config(url), "0004")
    command.downgrade(alembic_config(url), "0003")
    names = set(inspect(create_engine(url)).get_table_names())
    assert not names & {"interview_bookings", "sacco_events", "practice_interviews",
                        "pilot_daily_usage", "sus_responses"}
    assert "self_signed_up" not in {c["name"] for c in inspect(create_engine(url)).get_columns("members")}
    command.upgrade(alembic_config(url), "0004")
    assert schema_revision(create_engine(url)) == "0004"


def test_postgres_sql_covers_the_new_tables_offline():
    out = io.StringIO()
    with redirect_stdout(out):
        command.upgrade(alembic_config("postgresql+psycopg://u:p@localhost/x"), "0003:0004", sql=True)
    sql = out.getvalue()
    for table in ("interview_bookings", "sacco_events", "practice_interviews", "pilot_daily_usage",
                  "sus_responses"):
        assert f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY" in sql
    assert "CREATE UNIQUE INDEX uq_members_phone ON members (phone)" in sql
    assert "CREATE UNIQUE INDEX uq_interview_bookings_slot ON interview_bookings (starts_at) " \
           "WHERE status IN ('requested', 'confirmed', 'started')" in sql
    assert "UPDATE members SET phone = '+254' || substr(phone, 2)" in sql


NEW_IN_0005 = ("member_profiles", "member_profile_history", "member_accounts", "loan_accounts",
               "account_entries", "guarantor_pledges")


def at_0004(path):
    """A 0004 database holding a member, an application and two guarantors: one
    whose number is a member's, in another case, and one whose number is nobody's."""
    url = f"sqlite:///{path}"
    command.upgrade(alembic_config(url), "0004")
    con = sqlite3.connect(path)
    con.executescript("""
        INSERT INTO users (id, username, password_hash, role, is_active, created_at)
            VALUES (1, 'o', 'x', 'officer', 1, '2020-01-01');
        INSERT INTO members (id, member_no, full_name, phone, joined_on, created_at, self_signed_up,
                             savings_kes, birth_year)
            VALUES (1, 'M-1', 'F', '+254700000111', '2020-01-01', '2020-01-01', 0, 7000, 1980);
        INSERT INTO loan_applications (id, member_id, amount_requested_kes, purpose, term_months,
                                       sacco_savings_kes, status, created_by, created_at, updated_at,
                                       savings_self_declared)
            VALUES (1, 1, 100, 'p', 6, 10, 'draft', 1, '2020-01-01', '2020-01-01', 1);
        INSERT INTO guarantors (id, application_id, full_name, member_no, phone, relationship,
                                amount_guaranteed_kes, status, submitted_at)
            VALUES (1, 1, 'G', 'm-1', '0700', 'x', 5, 'pending', '2020-01-01'),
                   (2, 1, 'H', 'nobody', '0700', 'x', 5, 'verified', '2020-01-01');
    """)
    con.commit()
    con.close()
    return url


def test_0005_keeps_every_existing_value(tmp_path):
    path = tmp_path / "m.db"
    url = at_0004(path)
    tables = ["members", "loan_applications", "guarantors"]
    before = dump(path, tables)
    command.upgrade(alembic_config(url), "0005")
    after = dump(path, tables)
    for t in tables:
        rows, cols = before[t]
        new_rows, new_cols = after[t]
        kept = [new_cols.index(c) for c in cols]
        assert [tuple(r[i] for i in kept) for r in new_rows] == rows, t
    con = sqlite3.connect(path)
    assert con.execute("SELECT id, member_id FROM guarantors ORDER BY id").fetchall() == [(1, 1), (2, None)]
    for table in NEW_IN_0005:         # nothing invented: no profile, no opening balance
        assert con.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,)
    con.close()


def test_0005_downgrades_and_comes_back(tmp_path):
    path = tmp_path / "m.db"
    url = at_0004(path)
    before = dump(path, ["guarantors"])
    command.upgrade(alembic_config(url), "0005")
    con = sqlite3.connect(path)
    con.executescript("""
        INSERT INTO member_accounts (id, member_id, kind, created_at) VALUES (1, 1, 'deposits', '2020-01-01');
        INSERT INTO account_entries (account_id, account_kind, entry_type, amount_kes, posted_at, reference, created_at)
            VALUES (1, 'deposits', 'deposit', 500, '2020-01-02', 'r', '2020-01-02');
        INSERT INTO loan_accounts (id, member_id, principal_kes, disbursed_on, term_months,
                                   monthly_instalment_kes, status, created_at, updated_at)
            VALUES (1, 1, 100, '2020-01-02', 6, 20, 'active', '2020-01-02', '2020-01-02');
        INSERT INTO guarantors (id, loan_account_id, full_name, member_no, phone, relationship,
                                amount_guaranteed_kes, status, submitted_at)
            VALUES (3, 1, 'J', 'M-1', '0700', 'x', 5, 'verified', '2020-01-02');
    """)
    con.commit()
    con.close()

    command.downgrade(alembic_config(url), "0004")

    names = set(inspect(create_engine(url)).get_table_names())
    assert not names & set(NEW_IN_0005)
    assert dump(path, ["guarantors"]) == before       # a guarantee on a loan alone went with the loan
    application_id = next(c for c in inspect(create_engine(url)).get_columns("guarantors")
                          if c["name"] == "application_id")
    assert application_id["nullable"] is False
    con = sqlite3.connect(path)
    assert con.execute("SELECT name FROM sqlite_master WHERE type = 'trigger' AND "
                       "name LIKE 'account_entries%'").fetchall() == []
    con.close()

    command.upgrade(alembic_config(url), "head")
    assert schema_revision(create_engine(url)) == head_revision()


def test_0005_on_sqlite_keeps_the_guarantor_checks_through_the_rebuild(tmp_path):
    path = tmp_path / "m.db"
    command.upgrade(alembic_config(at_0004(path)), "0005")
    con = sqlite3.connect(path)
    with pytest.raises(sqlite3.IntegrityError, match="ck_guarantors_status"):
        con.execute("UPDATE guarantors SET status = 'bogus' WHERE id = 1")
    with pytest.raises(sqlite3.IntegrityError, match="ck_guarantors_backs_something"):
        con.execute("UPDATE guarantors SET application_id = NULL WHERE id = 1")
    con.close()


def test_postgres_sql_guards_the_ledger_and_the_history():
    out = io.StringIO()
    with redirect_stdout(out):
        command.upgrade(alembic_config("postgresql+psycopg://u:p@localhost/x"), "0004:0005", sql=True)
    sql = out.getvalue()
    for table, message in [("member_profile_history", "member_profile_history is append-only"),
                           ("account_entries", "account_entries is append-only")]:
        for when, level in [("UPDATE", "ROW"), ("DELETE", "ROW"), ("TRUNCATE", "STATEMENT")]:
            assert (f"CREATE TRIGGER {table}_no_{when.lower()} BEFORE {when} ON {table} "
                    f"FOR EACH {level} EXECUTE FUNCTION chamapro_reject_change('{message}')") in sql
    for table in NEW_IN_0005:
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


# --- 0006 ----------------------------------------------------------------------------------

def at_0005(path):
    url = f"sqlite:///{path}"
    command.upgrade(alembic_config(url), "0005")
    return url


ROWS_0005 = """
INSERT INTO users (id, username, password_hash, role, is_active, created_at) VALUES (1, 'o', 'x', 'officer', 1, '2026-10-01');
INSERT INTO members (id, member_no, full_name, joined_on, created_at) VALUES (1, 'M-1', 'Fictional One', '2020-01-01', '2026-10-01');
INSERT INTO members (id, member_no, full_name, joined_on, created_at) VALUES (2, 'M-2', 'Fictional Two', '2020-01-01', '2026-10-01');
INSERT INTO loan_applications (id, member_id, amount_requested_kes, purpose, term_months, sacco_savings_kes, status,
    created_by, created_at, updated_at) VALUES (1, 1, 1000, 'x', 6, 500, 'approved', 1, '2026-10-01', '2026-10-01');
INSERT INTO loan_accounts (id, member_id, application_id, principal_kes, disbursed_on, term_months, monthly_instalment_kes,
    status, created_at, updated_at) VALUES (1, 1, 1, 1000, '2026-10-01', 6, 180, 'active', '2026-10-01', '2026-10-01');
INSERT INTO member_accounts (id, member_id, kind, created_at) VALUES (1, 1, 'transactional', '2026-10-01');
INSERT INTO account_entries (id, account_id, account_kind, entry_type, amount_kes, posted_at, reference, loan_account_id, created_at)
    VALUES (1, 1, 'transactional', 'loan_disbursement', 1000, '2026-10-01', 'LOAN-1', 1, '2026-10-01');
INSERT INTO guarantors (id, application_id, full_name, member_no, phone, relationship, amount_guaranteed_kes, status, submitted_at,
    member_id, loan_account_id) VALUES (1, 1, 'Fictional Two', 'M-2', '0712345678', 'x', 500, 'verified', '2026-10-01', 2, 1);
"""


def filled_0005(path):
    url = at_0005(path)
    con = sqlite3.connect(path)
    con.executescript(ROWS_0005)
    con.commit()
    con.close()
    return url


def test_0006_keeps_every_row_and_constraint_through_the_rebuilds(tmp_path):
    path = tmp_path / "db.sqlite"
    url = filled_0005(path)
    before = dump(path, ["loan_applications", "loan_accounts", "account_entries", "guarantors"])
    command.upgrade(alembic_config(url), "0006")
    after = dump(path, ["loan_applications", "loan_accounts", "account_entries", "guarantors"])
    assert after["loan_accounts"] == before["loan_accounts"] and after["account_entries"] == before["account_entries"]
    con = sqlite3.connect(path)
    con.execute("PRAGMA foreign_keys=ON")
    assert con.execute("PRAGMA foreign_key_check").fetchall() == []
    assert con.execute("SELECT channel FROM loan_applications").fetchall() == [("branch",)]
    assert con.execute("SELECT accepted_under_pledge FROM guarantors").fetchall() == [(0,)]
    bad = ["UPDATE account_entries SET amount_kes = 1", "DELETE FROM account_entries",
           "INSERT INTO loan_accounts (member_id, application_id, principal_kes, disbursed_on, term_months, "
           "monthly_instalment_kes, status, created_at, updated_at) VALUES (1, 1, 1, '2026-10-01', 1, 1, 'active', "
           "'2026-10-01', '2026-10-01')",     # one loan per application: what stops a second payout
           "UPDATE loan_applications SET status = 'nonsense'", "UPDATE loan_accounts SET status = 'nonsense'",
           "UPDATE loan_applications SET channel = 'nonsense'",
           "INSERT INTO account_entries (account_id, account_kind, entry_type, amount_kes, posted_at, reference, created_at) "
           "VALUES (1, 'transactional', 'deposit_refund', -1, '2026-10-01', 'R', '2026-10-01')",
           "INSERT INTO account_entries (account_id, account_kind, entry_type, amount_kes, posted_at, reference, created_at) "
           "VALUES (1, 'transactional', 'loan_reversal', 0, '2026-10-01', 'R', '2026-10-01')",
           "INSERT INTO loan_accounts (member_id, principal_kes, disbursed_on, term_months, monthly_instalment_kes, status, "
           "created_at, updated_at) VALUES (99, 1, '2026-10-01', 1, 1, 'active', '2026-10-01', '2026-10-01')"]
    for sql in bad:
        with pytest.raises(sqlite3.IntegrityError):
            con.execute(sql)
        con.rollback()
    con.close()


def test_0006_runs_through_init_db_with_rows_pointing_at_the_rebuilt_tables(tmp_path):
    path = tmp_path / "db.sqlite"
    filled_0005(path)
    engine = create_engine(f"sqlite:///{path}")
    init_db(engine)
    assert schema_revision(engine) == "0007"
    con = sqlite3.connect(path)
    assert con.execute("SELECT count(*) FROM guarantors WHERE loan_account_id = 1").fetchone() == (1,)
    con.close()
    engine.dispose()


def test_init_db_stops_on_a_broken_foreign_key_and_changes_nothing(tmp_path):
    path = tmp_path / "db.sqlite"
    filled_0005(path)
    con = sqlite3.connect(path)
    con.execute("INSERT INTO guarantors (application_id, full_name, member_no, phone, relationship, amount_guaranteed_kes, "
                "status, submitted_at) VALUES (77, 'x', 'x', 'x', 'x', 1, 'pending', '2026-10-01')")
    con.commit()
    con.close()
    engine = create_engine(f"sqlite:///{path}")
    with pytest.raises(RuntimeError, match="broken foreign key"):
        init_db(engine)
    assert schema_revision(engine) == "0005"
    engine.dispose()


def test_0006_stops_on_a_real_system_user(tmp_path):
    path = tmp_path / "db.sqlite"
    url = at_0005(path)
    con = sqlite3.connect(path)
    con.execute("INSERT INTO users (username, password_hash, role, is_active, created_at) "
                "VALUES ('system', 'x', 'admin', 1, '2026-10-01')")
    con.commit()
    con.close()
    with pytest.raises(RuntimeError, match="already exists"):
        command.upgrade(alembic_config(url), "0006")


def test_0006_downgrades_and_comes_back_and_refuses_with_decisions(tmp_path):
    path = tmp_path / "db.sqlite"
    url = filled_0005(path)
    command.upgrade(alembic_config(url), "0006")
    command.downgrade(alembic_config(url), "0005")
    con = sqlite3.connect(path)
    assert con.execute("SELECT count(*) FROM users WHERE username = 'system'").fetchone() == (0,)
    assert "channel" not in {r[1] for r in con.execute("PRAGMA table_info(loan_applications)")}
    assert {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type = 'trigger' AND tbl_name = 'account_entries'")} \
        == {"account_entries_no_update", "account_entries_no_delete"}
    con.close()
    command.upgrade(alembic_config(url), "0006")
    con = sqlite3.connect(path)
    con.execute("INSERT INTO loan_accounts (member_id, principal_kes, disbursed_on, term_months, monthly_instalment_kes, status, "
                "created_at, updated_at) VALUES (1, 1, '2026-10-01', 1, 1, 'reversed', '2026-10-01', '2026-10-01')")
    con.commit()
    con.close()
    with pytest.raises(RuntimeError, match="reversed loans"):
        command.downgrade(alembic_config(url), "0005")


def test_postgres_sql_covers_0006_offline():
    out = io.StringIO()
    with redirect_stdout(out):
        command.upgrade(alembic_config("postgresql+psycopg://u:p@localhost/x"), "0005:0006", sql=True)
    sql = out.getvalue()
    assert "ALTER TABLE self_service_runs ENABLE ROW LEVEL SECURITY" in sql
    assert "ALTER TABLE idempotency_keys ENABLE ROW LEVEL SECURITY" in sql
    assert "DROP CONSTRAINT ck_account_entries_sign" in sql and "loan_reversal" in sql
    assert "CREATE TRIGGER account_entries_no_update" in sql
    assert "'system'" in sql
