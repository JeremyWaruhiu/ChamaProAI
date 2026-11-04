"""Member self-service: profile fields, unique phones, interview bookings, SACCO
events, practice interviews, usage caps and SUS responses.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-04

Existing rows keep every value they had, except members.phone: it is rewritten
to the one stored form, +254XXXXXXXXX, so that "unique when present" means what
it says. That step is plain SQL so `alembic upgrade head --sql` prints it too.

Two members who share a number stop the migration: which of them keeps it is a
person's decision, not this script's. Nothing is changed in that case. No table
with a trigger is touched.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import context, op

from chamapro.migrations.guards import private_table

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None

BOOKING_STATUSES = ("requested", "confirmed", "started", "cancelled")
EVENT_TYPES = ("agm", "member_meeting", "training", "loan_deadline", "other")
HOLDS_SLOT = "status IN ('requested', 'confirmed', 'started')"
OPEN_BOOKING = "status IN ('requested', 'confirmed')"
NEW_TABLES = ("interview_bookings", "sacco_events", "practice_interviews", "pilot_daily_usage",
              "sus_responses")


def one_of(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def member_columns() -> list[sa.Column]:
    return [sa.Column("email", sa.String(254)),
            sa.Column("savings_kes", sa.Integer),
            sa.Column("savings_verified_by", sa.String(64)),
            sa.Column("savings_verified_at", sa.DateTime),
            sa.Column("birth_year", sa.Integer),
            sa.Column("sex", sa.String(10)),
            sa.Column("education", sa.Integer),
            sa.Column("marital_status", sa.String(10)),
            sa.Column("consent_version", sa.String(32)),
            sa.Column("consent_at", sa.DateTime),
            sa.Column("self_signed_up", sa.Boolean, nullable=False, server_default=sa.false())]


def normalise_phones() -> None:
    """Every form the API has accepted to +254XXXXXXXXX; anything else stays as
    it is. Runs on SQLite and PostgreSQL alike."""
    stripped = "replace(replace(replace(replace(phone, ' ', ''), '-', ''), '(', ''), ')', '')"
    op.execute(f"UPDATE members SET phone = {stripped} WHERE phone IS NOT NULL")
    op.execute("UPDATE members SET phone = NULL WHERE phone = ''")
    op.execute("UPDATE members SET phone = '+254' || substr(phone, 2) "
               "WHERE length(phone) = 10 AND (phone LIKE '07%' OR phone LIKE '01%')")
    op.execute("UPDATE members SET phone = '+' || phone "
               "WHERE length(phone) = 12 AND (phone LIKE '2547%' OR phone LIKE '2541%')")


def refuse_duplicate_phones() -> None:
    """A clear message instead of the unique index's bare failure. Offline there
    is no data to look at; the index reports any duplicate when the SQL is run."""
    if context.is_offline_mode():
        return
    rows = op.get_bind().execute(sa.text(
        "SELECT phone, count(*) FROM members WHERE phone IS NOT NULL "
        "GROUP BY phone HAVING count(*) > 1 ORDER BY phone")).all()
    if rows:
        ids = op.get_bind().execute(sa.text(
            "SELECT id, phone FROM members WHERE phone IN "
            "(SELECT phone FROM members WHERE phone IS NOT NULL GROUP BY phone HAVING count(*) > 1) "
            "ORDER BY phone, id")).all()
        listing = "; ".join(f"member {i}: {p}" for i, p in ids)
        raise RuntimeError(f"cannot make members.phone unique: {len(rows)} number(s) are shared "
                           f"({listing}). Decide who keeps each number, clear or correct the "
                           "others, then run the migration again. Nothing was changed.")


def upgrade() -> None:
    normalise_phones()
    refuse_duplicate_phones()      # before any DDL, for a plain `alembic upgrade` on SQLite
    for col in member_columns():
        op.add_column("members", col)
    op.create_index("uq_members_phone", "members", ["phone"], unique=True)
    op.add_column("loan_applications", sa.Column("savings_self_declared", sa.Boolean, nullable=False,
                                                 server_default=sa.false()))

    op.create_table(
        "interview_bookings",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("application_id", sa.Integer, sa.ForeignKey("loan_applications.id"),
                  nullable=False, index=True),
        sa.Column("member_id", sa.Integer, sa.ForeignKey("members.id"), nullable=False, index=True),
        sa.Column("starts_at", sa.DateTime, nullable=False),
        sa.Column("language", sa.String(8), nullable=False),
        sa.Column("status", sa.String(12), nullable=False),
        sa.Column("interview_id", sa.Integer, sa.ForeignKey("interviews.id")),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.CheckConstraint(one_of("status", BOOKING_STATUSES), name="ck_interview_bookings_status"),
    )
    op.create_index("uq_interview_bookings_slot", "interview_bookings", ["starts_at"], unique=True,
                    sqlite_where=sa.text(HOLDS_SLOT), postgresql_where=sa.text(HOLDS_SLOT))
    op.create_index("uq_interview_bookings_open", "interview_bookings", ["application_id"], unique=True,
                    sqlite_where=sa.text(OPEN_BOOKING), postgresql_where=sa.text(OPEN_BOOKING))
    op.create_table(
        "sacco_events",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("event_type", sa.String(20), nullable=False),
        sa.Column("starts_at", sa.DateTime, nullable=False, index=True),
        sa.Column("location", sa.String(200)),
        sa.Column("online_link", sa.String(500)),
        sa.Column("description", sa.Text),
        sa.Column("created_by", sa.Integer, sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("updated_at", sa.DateTime, nullable=False),
        sa.CheckConstraint(one_of("event_type", EVENT_TYPES), name="ck_sacco_events_type"),
    )
    op.create_table(
        "practice_interviews",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("interview_id", sa.Integer, sa.ForeignKey("interviews.id"), nullable=False, unique=True),
        sa.Column("application_id", sa.Integer, sa.ForeignKey("loan_applications.id"),
                  nullable=False, index=True),
        sa.Column("member_id", sa.Integer, sa.ForeignKey("members.id"), nullable=False, index=True),
        sa.Column("submitted_at", sa.DateTime),
        sa.Column("created_at", sa.DateTime, nullable=False),
    )
    op.create_table(
        "pilot_daily_usage",
        sa.Column("day", sa.Date, primary_key=True),
        sa.Column("scope", sa.String(40), primary_key=True),
        sa.Column("used", sa.Integer, nullable=False),
        sa.CheckConstraint("used >= 0", name="ck_pilot_daily_usage_used"),
    )
    op.create_table(
        "sus_responses",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("interview_id", sa.Integer, sa.ForeignKey("interviews.id"), nullable=False, unique=True),
        sa.Column("member_id", sa.Integer, sa.ForeignKey("members.id"), nullable=False, index=True),
        sa.Column("answers", sa.JSON, nullable=False),
        sa.Column("score", sa.Float, nullable=False),
        sa.Column("comment", sa.Text),
        sa.Column("created_at", sa.DateTime, nullable=False, index=True),
    )
    for table in NEW_TABLES:
        private_table(table)


def downgrade() -> None:
    # Phones stay in the +254 form: the API accepted it before this revision too.
    for table in reversed(NEW_TABLES):
        op.drop_table(table)
    op.drop_column("loan_applications", "savings_self_declared")
    op.drop_index("uq_members_phone", "members")
    # SQLite 3.35+ drops a column in place; no trigger fires, no row changes.
    for col in reversed(member_columns()):
        op.drop_column("members", col.name)
