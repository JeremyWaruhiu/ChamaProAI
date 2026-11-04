"""The member database: profiles and their history, savings accounts and an
append-only ledger, issued loans, standing guarantors.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-04

Nothing existing changes value. No member, application or decision is rewritten,
and no ledger entry is invented: a member has no entries until the SACCO's records
are posted, and until then the SACCO rule keeps reading their application's own
sacco_savings_kes (ledger.rule_savings).

guarantors gains three nullable columns and is rebuilt on SQLite, because
application_id stops being NOT NULL. guarantors.member_id is filled in where a
submitted member number is one of ours, compared as the API compares them. No
table with a trigger is touched.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from chamapro.migrations.guards import allow_changes, private_table, reject_changes

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None

PROFILE_SOURCES = ("registration", "member_update", "officer_verified", "seed")
PROFILE_GROUPS = ("personal", "household", "income", "assets", "credit")
ACCOUNT_KINDS = ("deposits", "share_capital", "transactional")
ENTRY_TYPES = ("deposit", "withdrawal", "loan_disbursement", "loan_repayment",
               "guarantee_recovery", "dividend")
LOAN_STATUSES = ("active", "repaid", "defaulted")
PLEDGE_STATUSES = ("active", "withdrawn")
ENTRY_RULES = (
    ("ck_account_entries_sign",
     "(entry_type IN ('deposit', 'loan_disbursement', 'dividend') AND amount_kes > 0) "
     "OR (entry_type IN ('withdrawal', 'loan_repayment', 'guarantee_recovery') AND amount_kes < 0)"),
    ("ck_account_entries_no_deposit_withdrawal",
     "NOT (entry_type = 'withdrawal' AND account_kind = 'deposits')"),
    ("ck_account_entries_disbursed_to_transactional",
     "entry_type NOT IN ('loan_disbursement', 'loan_repayment') OR account_kind = 'transactional'"),
    ("ck_account_entries_recovered_from_deposits",
     "entry_type != 'guarantee_recovery' OR account_kind = 'deposits'"),
)
NEW_TABLES = ("member_profiles", "member_profile_history", "member_accounts", "loan_accounts",
              "account_entries", "guarantor_pledges")
HISTORY_MESSAGE = "member_profile_history is append-only"
LEDGER_MESSAGE = "account_entries is append-only"


def one_of(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def group_columns(group: str) -> list[sa.Column]:
    return [sa.Column(f"{group}_source", sa.String(20)),
            sa.Column(f"{group}_updated_at", sa.DateTime),
            sa.Column(f"{group}_verified_by", sa.String(64)),
            sa.Column(f"{group}_verified_at", sa.DateTime)]


def upgrade() -> None:
    op.create_table(
        "member_profiles",
        sa.Column("member_id", sa.Integer, sa.ForeignKey("members.id"), primary_key=True),
        sa.Column("date_of_birth", sa.Date),
        sa.Column("sex", sa.String(10)),
        sa.Column("education", sa.Integer),
        sa.Column("marital_status", sa.String(10)),
        sa.Column("household_size", sa.Integer),
        sa.Column("children", sa.Integer),
        sa.Column("children_under5", sa.Integer),
        sa.Column("children_in_school", sa.Integer),
        sa.Column("monthly_income_kes", sa.Integer),
        sa.Column("agri_income_kes", sa.Integer),
        sa.Column("income_sources", sa.JSON),
        sa.Column("non_monetary_savings", sa.JSON),
        sa.Column("purchases_last_12m", sa.JSON),
        sa.Column("chama_loan_use", sa.Integer),
        sa.Column("lost_as_guarantor_chama", sa.Integer),
        *(col for g in PROFILE_GROUPS for col in group_columns(g)),
        sa.Column("confirmed_at", sa.DateTime),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        *(sa.CheckConstraint(f"{g}_source IS NULL OR {one_of(f'{g}_source', PROFILE_SOURCES)}",
                             name=f"ck_member_profiles_{g}_source") for g in PROFILE_GROUPS),
        sa.CheckConstraint("education IS NULL OR education BETWEEN 0 AND 8",
                           name="ck_member_profiles_education"),
        sa.CheckConstraint("chama_loan_use IS NULL OR chama_loan_use IN (0, 1, 2)",
                           name="ck_member_profiles_chama_loan_use"),
        sa.CheckConstraint("lost_as_guarantor_chama IS NULL OR lost_as_guarantor_chama IN (0, 1)",
                           name="ck_member_profiles_lost_chama"),
    )
    op.create_table(
        "member_profile_history",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("member_id", sa.Integer, sa.ForeignKey("members.id"), nullable=False, index=True),
        sa.Column("change", sa.String(20), nullable=False),
        sa.Column("groups", sa.JSON, nullable=False),
        sa.Column("snapshot", sa.JSON, nullable=False),
        sa.Column("actor_user_id", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "member_accounts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("member_id", sa.Integer, sa.ForeignKey("members.id"), nullable=False),
        sa.Column("kind", sa.String(14), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.CheckConstraint(one_of("kind", ACCOUNT_KINDS), name="ck_member_accounts_kind"),
        sa.UniqueConstraint("member_id", "kind", name="uq_member_accounts_member_kind"),
        sa.UniqueConstraint("id", "kind", name="uq_member_accounts_id_kind"),
    )
    op.create_table(
        "loan_accounts",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("member_id", sa.Integer, sa.ForeignKey("members.id"), nullable=False, index=True),
        sa.Column("application_id", sa.Integer, sa.ForeignKey("loan_applications.id"), unique=True),
        sa.Column("principal_kes", sa.Integer, nullable=False),
        sa.Column("disbursed_on", sa.Date, nullable=False),
        sa.Column("term_months", sa.Integer, nullable=False),
        sa.Column("monthly_instalment_kes", sa.Integer, nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.CheckConstraint(one_of("status", LOAN_STATUSES), name="ck_loan_accounts_status"),
        sa.CheckConstraint("principal_kes > 0", name="ck_loan_accounts_principal"),
        sa.CheckConstraint("term_months > 0", name="ck_loan_accounts_term"),
        sa.CheckConstraint("monthly_instalment_kes > 0", name="ck_loan_accounts_instalment"),
    )
    op.create_table(
        "account_entries",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("account_id", sa.Integer, nullable=False),
        sa.Column("account_kind", sa.String(14), nullable=False),
        sa.Column("entry_type", sa.String(20), nullable=False),
        sa.Column("amount_kes", sa.Integer, nullable=False),
        sa.Column("posted_at", sa.DateTime, nullable=False),
        sa.Column("reference", sa.String(40), nullable=False),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("loan_account_id", sa.Integer, sa.ForeignKey("loan_accounts.id"), index=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.ForeignKeyConstraint(["account_id", "account_kind"], ["member_accounts.id", "member_accounts.kind"],
                                name="fk_account_entries_account"),
        sa.CheckConstraint(one_of("entry_type", ENTRY_TYPES), name="ck_account_entries_type"),
        *(sa.CheckConstraint(sql, name=name) for name, sql in ENTRY_RULES),
        sa.UniqueConstraint("account_id", "reference", name="uq_account_entries_reference"),
    )
    op.create_index("ix_account_entries_account_posted", "account_entries",
                    ["account_id", "posted_at", "id"])
    op.create_table(
        "guarantor_pledges",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("borrower_member_id", sa.Integer, sa.ForeignKey("members.id"), nullable=False),
        sa.Column("guarantor_member_id", sa.Integer, sa.ForeignKey("members.id"), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.CheckConstraint(one_of("status", PLEDGE_STATUSES), name="ck_guarantor_pledges_status"),
        sa.CheckConstraint("borrower_member_id != guarantor_member_id", name="ck_guarantor_pledges_self"),
    )
    op.create_index("uq_guarantor_pledges_active", "guarantor_pledges",
                    ["borrower_member_id", "guarantor_member_id"], unique=True,
                    sqlite_where=sa.text("status = 'active'"), postgresql_where=sa.text("status = 'active'"))
    op.create_index("ix_guarantor_pledges_guarantor", "guarantor_pledges", ["guarantor_member_id"])

    with op.batch_alter_table("guarantors") as batch:
        batch.add_column(sa.Column("member_id", sa.Integer))
        batch.add_column(sa.Column("pledge_id", sa.Integer))
        batch.add_column(sa.Column("loan_account_id", sa.Integer))
        batch.alter_column("application_id", existing_type=sa.Integer, nullable=True)
        batch.create_foreign_key("fk_guarantors_member", "members", ["member_id"], ["id"])
        batch.create_foreign_key("fk_guarantors_pledge", "guarantor_pledges", ["pledge_id"], ["id"])
        batch.create_foreign_key("fk_guarantors_loan", "loan_accounts", ["loan_account_id"], ["id"])
        batch.create_check_constraint("ck_guarantors_backs_something",
                                      "application_id IS NOT NULL OR loan_account_id IS NOT NULL")
        batch.create_index("ix_guarantors_member_id", ["member_id"])
        batch.create_index("ix_guarantors_loan_account_id", ["loan_account_id"])
    op.execute("UPDATE guarantors SET member_id = (SELECT min(m.id) FROM members m "
               "WHERE upper(m.member_no) = upper(guarantors.member_no))")

    reject_changes("member_profile_history", HISTORY_MESSAGE)
    reject_changes("account_entries", LEDGER_MESSAGE)
    for table in NEW_TABLES:
        private_table(table)


def downgrade() -> None:
    # A guarantee on a loan with no application goes with the loan it backed.
    op.execute("DELETE FROM guarantors WHERE application_id IS NULL")
    with op.batch_alter_table("guarantors") as batch:
        batch.drop_index("ix_guarantors_loan_account_id")
        batch.drop_index("ix_guarantors_member_id")
        batch.drop_constraint("ck_guarantors_backs_something", type_="check")
        batch.drop_constraint("fk_guarantors_loan", type_="foreignkey")
        batch.drop_constraint("fk_guarantors_pledge", type_="foreignkey")
        batch.drop_constraint("fk_guarantors_member", type_="foreignkey")
        batch.alter_column("application_id", existing_type=sa.Integer, nullable=False)
        batch.drop_column("loan_account_id")
        batch.drop_column("pledge_id")
        batch.drop_column("member_id")
    allow_changes("account_entries")
    allow_changes("member_profile_history")
    for table in reversed(NEW_TABLES):
        op.drop_table(table)
