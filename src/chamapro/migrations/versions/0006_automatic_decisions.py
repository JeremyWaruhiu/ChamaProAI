"""Automatic decisions: the policy trace on an assessment, the policy version on a
decision, the system user, reversal and refund entries, idempotency keys.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-04

Nothing existing changes value. Every application so far came through the branch.

On SQLite a CHECK can only be changed by rebuilding the table, so loan_applications,
loan_accounts and account_entries are rebuilt, and the ledger's triggers are put back
(dropping a table takes them with it; no trigger fires). db._migration_engine runs
this with foreign keys off and checks them afterwards, as SQLite's own procedure says.
On PostgreSQL these are plain ALTERs, and the triggers are not involved.

A user called "system" who is not this one stops the migration, changing nothing: who
keeps the name is a person's decision, not a script's.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import context, op

from chamapro.migrations.guards import private_table, reject_changes

revision = "0006"
down_revision = "0005"
branch_labels = None
depends_on = None

NEW_TABLES = ("self_service_runs", "idempotency_keys")
LEDGER_MESSAGE = "account_entries is append-only"
APPLICATION_STATUSES = ("draft", "interview_pending", "interview_complete", "assessed", "decided",
                        "guarantor_required", "guarantor_submitted", "approved", "declined")
LOAN_STATUSES = ("active", "repaid", "defaulted")
ENTRY_TYPES = ("deposit", "withdrawal", "loan_disbursement", "loan_repayment", "guarantee_recovery", "dividend")
OLD_RULES = (
    ("ck_account_entries_sign",
     "(entry_type IN ('deposit', 'loan_disbursement', 'dividend') AND amount_kes > 0) "
     "OR (entry_type IN ('withdrawal', 'loan_repayment', 'guarantee_recovery') AND amount_kes < 0)"),
    ("ck_account_entries_disbursed_to_transactional",
     "entry_type NOT IN ('loan_disbursement', 'loan_repayment') OR account_kind = 'transactional'"),
    ("ck_account_entries_recovered_from_deposits",
     "entry_type != 'guarantee_recovery' OR account_kind = 'deposits'"),
)
NEW_RULES = (
    ("ck_account_entries_sign",
     "(entry_type IN ('deposit', 'loan_disbursement', 'dividend') AND amount_kes > 0) "
     "OR (entry_type IN ('withdrawal', 'loan_repayment', 'guarantee_recovery', 'deposit_refund') AND amount_kes < 0) "
     "OR (entry_type = 'loan_reversal' AND amount_kes != 0)"),
    ("ck_account_entries_disbursed_to_transactional",
     "entry_type NOT IN ('loan_disbursement', 'loan_repayment', 'loan_reversal') OR account_kind = 'transactional'"),
    ("ck_account_entries_recovered_from_deposits",
     "entry_type NOT IN ('guarantee_recovery', 'deposit_refund') OR account_kind = 'deposits'"),
)


def one_of(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def set_check(batch, name: str, sql: str) -> None:
    batch.drop_constraint(name, type_="check")
    batch.create_check_constraint(name, sql)


def refuse_a_real_system_user() -> None:
    if context.is_offline_mode():
        return
    if op.get_bind().execute(sa.text("SELECT 1 FROM users WHERE username = 'system'")).first():
        raise RuntimeError("a user called 'system' already exists; rename them before running 0006, "
                           "which reserves the name for automatic decisions; nothing was changed")


def upgrade() -> None:
    refuse_a_real_system_user()
    with op.batch_alter_table("loan_applications") as batch:
        batch.add_column(sa.Column("channel", sa.String(14), nullable=False, server_default="branch"))
        set_check(batch, "ck_loan_applications_status",
                  one_of("status", (*APPLICATION_STATUSES, "offered", "reversed")))
        batch.create_check_constraint("ck_loan_applications_channel", one_of("channel", ("branch", "self_service")))
    with op.batch_alter_table("loan_accounts") as batch:
        set_check(batch, "ck_loan_accounts_status", one_of("status", (*LOAN_STATUSES, "reversed")))
    with op.batch_alter_table("account_entries") as batch:
        set_check(batch, "ck_account_entries_type", one_of("entry_type", (*ENTRY_TYPES, "loan_reversal", "deposit_refund")))
        for name, sql in NEW_RULES:
            set_check(batch, name, sql)
    reject_changes("account_entries", LEDGER_MESSAGE)

    # Adding a nullable column rewrites no row, so no immutability trigger is involved.
    op.add_column("assessments", sa.Column("provenance", sa.JSON))
    op.add_column("assessments", sa.Column("overrides", sa.JSON))
    op.add_column("assessments", sa.Column("policy_trace", sa.JSON))
    op.add_column("decisions", sa.Column("policy_version", sa.String(32)))
    with op.batch_alter_table("interviews") as batch:
        batch.alter_column("mode", existing_type=sa.String(10), type_=sa.String(12),
                           existing_nullable=False, existing_server_default="live")
    with op.batch_alter_table("guarantors") as batch:
        batch.add_column(sa.Column("accepted_under_pledge", sa.Boolean, nullable=False,
                                   server_default=sa.false()))

    op.create_table(
        "self_service_runs",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("application_id", sa.Integer, sa.ForeignKey("loan_applications.id"), nullable=False, index=True),
        sa.Column("interview_id", sa.Integer, sa.ForeignKey("interviews.id"), nullable=False, unique=True),
        sa.Column("trigger", sa.String(12), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, index=True),
    )
    op.create_table(
        "idempotency_keys",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("actor_user_id", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("request_hash", sa.String(64), nullable=False),
        sa.Column("status_code", sa.Integer),
        sa.Column("response", sa.JSON),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("actor_user_id", "key", name="uq_idempotency_keys_actor_key"),
    )
    for table in NEW_TABLES:
        private_table(table)
    # A users table loaded with explicit ids leaves its sequence behind them.
    if op.get_context().dialect.name == "postgresql":
        op.execute("SELECT setval(pg_get_serial_sequence('users', 'id'), "
                   "GREATEST((SELECT max(id) FROM users), 1))")
    # "!" is no scrypt hash, so no password matches it.
    op.execute(sa.text("INSERT INTO users (username, password_hash, role, display_name, is_active, created_at) "
                       "VALUES ('system', '!', 'system', 'Automatic decision', :no, CURRENT_TIMESTAMP)")
               .bindparams(no=False))


def downgrade() -> None:
    """Stops if an automatic decision, reversal or refund exists: they are immutable
    records that the older schema has no place for, and dropping them is a decision
    for a person, not this script."""
    if not context.is_offline_mode():
        bind = op.get_bind()
        held = {"automatic decisions": "SELECT 1 FROM self_service_runs",
                "reversed loans": "SELECT 1 FROM loan_accounts WHERE status = 'reversed'",
                "reversal or refund entries":
                    "SELECT 1 FROM account_entries WHERE entry_type IN ('loan_reversal', 'deposit_refund')"}
        found = [what for what, sql in held.items() if bind.execute(sa.text(sql)).first()]
        if found:
            raise RuntimeError(f"cannot go below 0006: the database holds {', '.join(found)}; nothing was changed")
    op.execute("DELETE FROM users WHERE username = 'system'")
    for table in reversed(NEW_TABLES):
        op.drop_table(table)
    with op.batch_alter_table("guarantors") as batch:
        batch.drop_column("accepted_under_pledge")
    with op.batch_alter_table("interviews") as batch:
        batch.alter_column("mode", existing_type=sa.String(12), type_=sa.String(10),
                           existing_nullable=False, existing_server_default="live")
    op.drop_column("decisions", "policy_version")
    op.drop_column("assessments", "policy_trace")
    op.drop_column("assessments", "overrides")
    op.drop_column("assessments", "provenance")
    with op.batch_alter_table("account_entries") as batch:
        set_check(batch, "ck_account_entries_type", one_of("entry_type", ENTRY_TYPES))
        for name, sql in OLD_RULES:
            set_check(batch, name, sql)
    reject_changes("account_entries", LEDGER_MESSAGE)
    with op.batch_alter_table("loan_accounts") as batch:
        set_check(batch, "ck_loan_accounts_status", one_of("status", LOAN_STATUSES))
    with op.batch_alter_table("loan_applications") as batch:
        batch.drop_constraint("ck_loan_applications_channel", type_="check")
        set_check(batch, "ck_loan_applications_status", one_of("status", APPLICATION_STATUSES))
        batch.drop_column("channel")
