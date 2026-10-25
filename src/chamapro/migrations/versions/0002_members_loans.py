"""Members, loan applications, guarantors, the audit log, decision outcomes.

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-26

Decisions gain their columns by ADD COLUMN only: existing decisions keep
every value they had, read with a null outcome (shown as their `decision`),
and the immutability triggers are neither fired nor dropped. No table that
has a trigger is rebuilt. The audit log is append-only from the start.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from chamapro.migrations.guards import allow_changes, private_table, reject_changes

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None

APPLICATION_STATUSES = ("draft", "interview_pending", "interview_complete", "assessed", "decided",
                        "guarantor_required", "guarantor_submitted", "approved", "declined")
GUARANTOR_STATUSES = ("pending", "verified", "rejected")


def decision_columns() -> list[sa.Column]:
    return [sa.Column("outcome", sa.String(30)),
            sa.Column("approved_amount_kes", sa.Integer),
            sa.Column("guarantors_required", sa.Integer),
            sa.Column("officer_notes", sa.Text),
            sa.Column("member_message", sa.Text)]


def one_of(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def upgrade() -> None:
    op.create_table(
        "members",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("member_no", sa.String(32), nullable=False, unique=True),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("phone", sa.String(20)),
        sa.Column("joined_on", sa.Date, nullable=False),
        sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id"), unique=True),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "loan_applications",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("member_id", sa.Integer, sa.ForeignKey("members.id"), nullable=False, index=True),
        sa.Column("amount_requested_kes", sa.Integer, nullable=False),
        sa.Column("purpose", sa.Text, nullable=False),
        sa.Column("term_months", sa.Integer, nullable=False),
        sa.Column("sacco_savings_kes", sa.Integer, nullable=False),
        sa.Column("interview_id", sa.Integer, sa.ForeignKey("interviews.id"), unique=True),
        sa.Column("status", sa.String(24), nullable=False, index=True),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.CheckConstraint(one_of("status", APPLICATION_STATUSES), name="ck_loan_applications_status"),
        sa.CheckConstraint("amount_requested_kes > 0", name="ck_loan_applications_amount"),
        sa.CheckConstraint("term_months > 0", name="ck_loan_applications_term"),
        sa.CheckConstraint("sacco_savings_kes >= 0", name="ck_loan_applications_savings"),
    )
    op.create_table(
        "guarantors",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("application_id", sa.Integer, sa.ForeignKey("loan_applications.id"),
                  nullable=False, index=True),
        sa.Column("full_name", sa.String(200), nullable=False),
        sa.Column("member_no", sa.String(32), nullable=False),
        sa.Column("phone", sa.String(20), nullable=False),
        sa.Column("relationship", sa.String(60), nullable=False),
        sa.Column("amount_guaranteed_kes", sa.Integer, nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("submitted_at", sa.DateTime, nullable=False),
        sa.Column("verified_by", sa.Integer, sa.ForeignKey("users.id")),
        sa.Column("verified_at", sa.DateTime),
        sa.CheckConstraint(one_of("status", GUARANTOR_STATUSES), name="ck_guarantors_status"),
        sa.CheckConstraint("amount_guaranteed_kes > 0", name="ck_guarantors_amount"),
    )
    op.create_table(
        "audit_log",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("actor_user_id", sa.Integer, sa.ForeignKey("users.id"), index=True),
        sa.Column("action", sa.String(64), nullable=False, index=True),
        sa.Column("entity", sa.String(40), nullable=False),
        sa.Column("entity_id", sa.Integer),
        sa.Column("details", sa.JSON, nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False, index=True),
    )
    op.create_index("ix_audit_log_entity", "audit_log", ["entity", "entity_id"])
    for table in ("members", "loan_applications", "guarantors", "audit_log", "alembic_version"):
        private_table(table)
    reject_changes("audit_log", "audit_log is append-only")

    for col in decision_columns():
        op.add_column("decisions", col)


def downgrade() -> None:
    # SQLite 3.35+ drops a column in place; no trigger fires, no row changes.
    for col in reversed(decision_columns()):
        op.drop_column("decisions", col.name)
    allow_changes("audit_log")
    for table in ("audit_log", "guarantors", "loan_applications", "members"):
        op.drop_table(table)
