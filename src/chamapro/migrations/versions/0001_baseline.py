"""Baseline: the schema as it stood before Alembic.

Revision ID: 0001
Revises:
Create Date: 2026-10-26

On an empty database this creates every table. On a database made before
Alembic (init_db's create_all plus ADD COLUMN), it creates only the tables
that are missing and adds only the columns that are missing, as init_db used
to: ADD COLUMN leaves existing rows as they were (NULL, or the DEFAULT given)
and fires no UPDATE trigger, so immutability holds. Interviews from before
question sets existed become v1 / kik / live, responses audio.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from chamapro.migrations.guards import private_table, reject_changes

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def tables() -> dict[str, list]:
    """Table name -> columns and constraints, in creation order."""
    return {
        "applicants": [
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("name", sa.String(200)),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("age", sa.Integer),
            sa.Column("sex", sa.String(10)),
            sa.Column("education", sa.Integer),
            sa.Column("marital_status", sa.String(10)),
        ],
        "interviews": [
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("applicant_id", sa.Integer, sa.ForeignKey("applicants.id"), nullable=False),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("question_set", sa.String(8), nullable=False, server_default="v1"),
            sa.Column("language", sa.String(8), nullable=False, server_default="kik"),
            sa.Column("mode", sa.String(10), nullable=False, server_default="live"),
        ],
        "responses": [
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("interview_id", sa.Integer, sa.ForeignKey("interviews.id"), nullable=False,
                      index=True),
            sa.Column("sentence_no", sa.Integer, nullable=False),
            sa.Column("domain", sa.String(40)),
            sa.Column("audio_path", sa.Text, nullable=False),
            sa.Column("duration_s", sa.Float),
            sa.Column("status", sa.String(20), nullable=False),
            sa.Column("error", sa.Text),
            sa.Column("transcript", sa.Text),
            sa.Column("transcript_asr", sa.Text),
            sa.Column("asr_model", sa.String(200)),
            sa.Column("asr_seconds", sa.Float),
            sa.Column("transcribed_at", sa.DateTime),
            sa.Column("edited", sa.Boolean, nullable=False),
            sa.Column("edited_at", sa.DateTime),
            sa.Column("translation", sa.Text),
            sa.Column("signals", sa.JSON),
            sa.Column("translated_at", sa.DateTime),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("source", sa.String(10), nullable=False, server_default="audio"),
            sa.UniqueConstraint("interview_id", "sentence_no"),
        ],
        "assessments": [
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("interview_id", sa.Integer, sa.ForeignKey("interviews.id"), nullable=False,
                      unique=True),
            sa.Column("risk_class", sa.String(20), nullable=False),
            sa.Column("probabilities", sa.JSON, nullable=False),
            sa.Column("feature_vector", sa.JSON, nullable=False),
            sa.Column("contributions", sa.JSON, nullable=False),
            sa.Column("extracted", sa.JSON, nullable=False),
            sa.Column("extraction_completeness", sa.Float, nullable=False),
            sa.Column("features_populated", sa.Integer, nullable=False),
            sa.Column("features_total", sa.Integer, nullable=False),
            sa.Column("features_not_extractable", sa.JSON, nullable=False),
            sa.Column("extraction_model", sa.String(200), nullable=False),
            sa.Column("model_file", sa.String(200), nullable=False),
            sa.Column("model_sha256", sa.String(64), nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("assessed_by", sa.String(64)),
            sa.Column("applicant_form", sa.JSON),
        ],
        "decisions": [
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("interview_id", sa.Integer, sa.ForeignKey("interviews.id"), nullable=False,
                      unique=True),
            sa.Column("decision", sa.String(20), nullable=False),
            sa.Column("note", sa.Text),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("decided_by", sa.String(64)),
        ],
        "users": [
            sa.Column("id", sa.Integer, primary_key=True),
            sa.Column("username", sa.String(64), nullable=False, unique=True),
            sa.Column("password_hash", sa.String(255), nullable=False),
            sa.Column("role", sa.String(20), nullable=False),
            sa.Column("is_active", sa.Boolean, nullable=False),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("email", sa.String(254)),
        ],
        "sessions": [
            sa.Column("token_hash", sa.String(64), primary_key=True),
            sa.Column("user_id", sa.Integer, sa.ForeignKey("users.id", ondelete="CASCADE"),
                      nullable=False, index=True),
            sa.Column("created_at", sa.DateTime, nullable=False),
            sa.Column("expires_at", sa.DateTime, nullable=False),
            sa.Column("auth_method", sa.String(20)),
        ],
    }


# Columns added in place by init_db before Alembic, with the DDL it used.
# Only a pre-Alembic SQLite database can lack them.
LEGACY_COLUMNS = [("assessments", "assessed_by", "VARCHAR(64)"),
                  ("decisions", "decided_by", "VARCHAR(64)"),
                  ("users", "email", "VARCHAR(254)"),
                  ("sessions", "auth_method", "VARCHAR(20)"),
                  ("interviews", "question_set", "VARCHAR(8) NOT NULL DEFAULT 'v1'"),
                  ("interviews", "language", "VARCHAR(8) NOT NULL DEFAULT 'kik'"),
                  ("interviews", "mode", "VARCHAR(10) NOT NULL DEFAULT 'live'"),
                  ("applicants", "age", "INTEGER"),
                  ("applicants", "sex", "VARCHAR(10)"),
                  ("applicants", "education", "INTEGER"),
                  ("applicants", "marital_status", "VARCHAR(10)"),
                  ("responses", "source", "VARCHAR(10) NOT NULL DEFAULT 'audio'"),
                  ("assessments", "applicant_form", "JSON")]


def upgrade() -> None:
    insp = sa.inspect(op.get_bind()) if not op.get_context().as_sql else None
    have = set(insp.get_table_names()) if insp else set()
    for name, cols in tables().items():
        if name not in have:
            op.create_table(name, *cols)
            private_table(name)
    for table, column, ddl in LEGACY_COLUMNS:
        if table in have and column not in {c["name"] for c in insp.get_columns(table)}:
            op.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")
    # SQLite cannot add a UNIQUE column, so uniqueness comes from an index.
    if "users" not in have or "ix_users_email" not in {i["name"] for i in insp.get_indexes("users")}:
        op.create_index("ix_users_email", "users", ["email"], unique=True)
    reject_changes("assessments", "assessments are immutable")
    reject_changes("decisions", "decisions are immutable")


def downgrade() -> None:
    raise RuntimeError("the baseline holds the interview records; downgrading below it would "
                       "drop every table. Drop them by hand if that is really meant.")
