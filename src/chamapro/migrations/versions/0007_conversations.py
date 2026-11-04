"""The conversation backend: conversations and their append-only turns, notices to
members, and a ceiling on standing guarantors' pledges.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-04

Nothing existing changes value. A pledge made before this has no ceiling, and nobody
can say what its guarantor would have agreed to: it backs no automatic decision until
they set one. An officer's review of a branch application can still use it.

Conversations are kept out of the statistics by construction: they are not interviews,
and the decision one leads to is a self_service run, which the statistics already leave out.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import context, op

from chamapro.migrations.guards import private_table, reject_changes

revision = "0007"
down_revision = "0006"
branch_labels = None
depends_on = None

NEW_TABLES = ("member_notices", "conversations", "conversation_turns")
TURNS_MESSAGE = "conversation_turns is append-only"


def upgrade() -> None:
    op.add_column("guarantor_pledges", sa.Column("max_amount_kes", sa.Integer))
    op.create_table(
        "member_notices",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("member_id", sa.Integer, sa.ForeignKey("members.id"), nullable=False, index=True),
        sa.Column("kind", sa.String(24), nullable=False),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("loan_account_id", sa.Integer, sa.ForeignKey("loan_accounts.id")),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "conversations",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("member_id", sa.Integer, sa.ForeignKey("members.id"), nullable=False, index=True),
        sa.Column("language", sa.String(3), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("state", sa.String(14), nullable=False),
        sa.Column("context", sa.JSON, nullable=False),
        sa.Column("consent_given", sa.Boolean),
        sa.Column("consent_version", sa.String(32)),
        sa.Column("consent_at", sa.DateTime),
        sa.Column("policy_version", sa.String(32), nullable=False),
        sa.Column("self_service_run_id", sa.Integer, sa.ForeignKey("self_service_runs.id")),
        sa.Column("application_id", sa.Integer, sa.ForeignKey("loan_applications.id")),
        sa.Column("turn_count", sa.Integer, nullable=False),
        sa.Column("busy_until", sa.DateTime),
        sa.Column("last_activity_at", sa.DateTime, nullable=False),
        sa.Column("started_at", sa.DateTime, nullable=False),
        sa.Column("ended_at", sa.DateTime),
        sa.CheckConstraint("status IN ('open', 'completed', 'abandoned')", name="ck_conversations_status"),
        sa.CheckConstraint("language IN ('en', 'kik')", name="ck_conversations_language"),
    )
    op.create_index("uq_conversations_one_open", "conversations", ["member_id"], unique=True,
                    sqlite_where=sa.text("status = 'open'"), postgresql_where=sa.text("status = 'open'"))
    op.create_table(
        "conversation_turns",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("conversation_id", sa.Integer, sa.ForeignKey("conversations.id"), nullable=False, index=True),
        sa.Column("seq", sa.Integer, nullable=False),
        sa.Column("speaker", sa.String(6), nullable=False),
        sa.Column("template_id", sa.String(20)),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column("text_en", sa.Text),
        sa.Column("kik_pending", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("audio_ref", sa.String(300)),
        sa.Column("tts_model", sa.String(120)),
        sa.Column("spoken_text", sa.Text),
        sa.Column("input_mode", sa.String(5)),
        sa.Column("asr_transcript", sa.Text),
        sa.Column("asr_model", sa.String(120)),
        sa.Column("translation", sa.Text),
        sa.Column("extraction", sa.JSON),
        sa.Column("explain", sa.JSON),
        sa.Column("actions", sa.JSON),
        sa.Column("asr_ms", sa.Integer),
        sa.Column("extract_ms", sa.Integer),
        sa.Column("evaluate_ms", sa.Integer),
        sa.Column("tts_ms", sa.Integer),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.UniqueConstraint("conversation_id", "seq", name="uq_conversation_turns_seq"),
        sa.CheckConstraint("speaker IN ('bot', 'member')", name="ck_conversation_turns_speaker"),
        sa.CheckConstraint("input_mode IS NULL OR input_mode IN ('voice', 'text')",
                           name="ck_conversation_turns_input_mode"),
    )
    reject_changes("conversation_turns", TURNS_MESSAGE)
    for table in NEW_TABLES:
        private_table(table)


def downgrade() -> None:
    """Stops if a conversation exists: its turns are immutable records, and dropping
    them is a decision for a person, not this script."""
    if not context.is_offline_mode():
        if op.get_bind().execute(sa.text("SELECT 1 FROM conversations")).first():
            raise RuntimeError("cannot go below 0007: the database holds conversations; nothing was changed")
    op.drop_table("conversation_turns")
    op.drop_index("uq_conversations_one_open", table_name="conversations")
    op.drop_table("conversations")
    op.drop_table("member_notices")
    op.drop_column("guarantor_pledges", "max_amount_kes")
