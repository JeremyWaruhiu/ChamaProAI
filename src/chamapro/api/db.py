"""Storage: applicants, interviews, responses, assessments, users, members,
loan applications, guarantors and the audit log.

SQLite by default; PostgreSQL (Supabase) by setting DATABASE_URL. The schema
is owned by the Alembic migrations in chamapro/migrations, not by this file:
init_db() runs them.

An assessment row is the audit record (Chapter 4): it stores the exact feature
vector the classifier saw, never something re-derived later. The officer's
decision is a separate record. Database triggers (SQLite and PostgreSQL)
reject any UPDATE or DELETE on either, and on the audit log, so the guarantee
holds even outside the API.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import (JSON, Boolean, CheckConstraint, Date, DateTime, Engine,
                        Float, ForeignKey, Index, Integer, String, Text,
                        TypeDecorator, UniqueConstraint, create_engine, event,
                        make_url)
from sqlalchemy.orm import (DeclarativeBase, Mapped, mapped_column,
                            relationship, sessionmaker, validates)

from chamapro import config

log = logging.getLogger("chamapro.db")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalise_email(value: str | None) -> str | None:
    """Emails are compared lower-case; blank means none."""
    value = (value or "").strip().lower()
    return value or None


class UTCDateTime(TypeDecorator):
    """Stored as naive UTC on both SQLite and PostgreSQL; handed back timezone-aware."""
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        return value.astimezone(timezone.utc).replace(tzinfo=None) if value else value

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=timezone.utc) if value else value


class Base(DeclarativeBase):
    pass


class Applicant(Base):
    __tablename__ = "applicants"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str | None] = mapped_column(String(200))
    # The applicant form, entered by the officer when the interview is created.
    # Null on applicants from before the form existed (question set v1).
    age: Mapped[int | None] = mapped_column(Integer)
    sex: Mapped[str | None] = mapped_column(String(10))              # female | male
    education: Mapped[int | None] = mapped_column(Integer)           # 0-8, score_interview.EDU_LADDER
    marital_status: Mapped[str | None] = mapped_column(String(10))   # married | single | widowed | divorced
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Interview(Base):
    __tablename__ = "interviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    applicant_id: Mapped[int] = mapped_column(ForeignKey("applicants.id"))
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | assessed
    # Rows from before these existed are v1 / kik / live (see ADDED_COLUMNS).
    question_set: Mapped[str] = mapped_column(String(8), default="v2")    # v1 | v2
    language: Mapped[str] = mapped_column(String(8), default="kik")       # kik | en
    mode: Mapped[str] = mapped_column(String(10), default="live")         # live | practice
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    applicant: Mapped[Applicant] = relationship()
    responses: Mapped[list[Response]] = relationship(
        back_populates="interview", order_by="Response.sentence_no")
    assessment: Mapped[Assessment | None] = relationship(back_populates="interview")
    decision: Mapped[Decision | None] = relationship(back_populates="interview")
    # Legacy, demo and practice interviews may have none.
    application: Mapped[LoanApplication | None] = relationship(back_populates="interview")


class Response(Base):
    __tablename__ = "responses"
    __table_args__ = (UniqueConstraint("interview_id", "sentence_no"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    interview_id: Mapped[int] = mapped_column(ForeignKey("interviews.id"), index=True)
    sentence_no: Mapped[int] = mapped_column(Integer)
    domain: Mapped[str | None] = mapped_column(String(40))   # the question's topic
    source: Mapped[str] = mapped_column(String(10), default="audio")   # audio | typed
    audio_path: Mapped[str] = mapped_column(Text)            # "" for a typed answer
    duration_s: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="queued")  # queued | transcribed | failed
    error: Mapped[str | None] = mapped_column(Text)
    # transcript is the working text; transcript_asr keeps what the model said
    transcript: Mapped[str | None] = mapped_column(Text)
    transcript_asr: Mapped[str | None] = mapped_column(Text)
    asr_model: Mapped[str | None] = mapped_column(String(200))
    asr_seconds: Mapped[float | None] = mapped_column(Float)
    transcribed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    edited_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    translation: Mapped[str | None] = mapped_column(Text)
    signals: Mapped[list | None] = mapped_column(JSON)
    translated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    interview: Mapped[Interview] = relationship(back_populates="responses")


class Assessment(Base):
    __tablename__ = "assessments"
    id: Mapped[int] = mapped_column(primary_key=True)
    interview_id: Mapped[int] = mapped_column(ForeignKey("interviews.id"), unique=True)
    risk_class: Mapped[str] = mapped_column(String(20))
    probabilities: Mapped[dict] = mapped_column(JSON)
    feature_vector: Mapped[dict] = mapped_column(JSON)   # feature -> value|null, classifier order
    contributions: Mapped[list | str] = mapped_column(JSON)
    extracted: Mapped[dict] = mapped_column(JSON)            # the extraction model's reply
    # The applicant form as merged into the vector; null when there was none.
    applicant_form: Mapped[dict | None] = mapped_column(JSON)
    extraction_completeness: Mapped[float] = mapped_column(Float)
    features_populated: Mapped[int] = mapped_column(Integer)
    features_total: Mapped[int] = mapped_column(Integer)
    features_not_extractable: Mapped[list] = mapped_column(JSON)
    extraction_model: Mapped[str] = mapped_column(String(200))
    model_file: Mapped[str] = mapped_column(String(200))
    model_sha256: Mapped[str] = mapped_column(String(64))
    # Who ran it. Null on assessments made before sign-in existed.
    assessed_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    interview: Mapped[Interview] = relationship(back_populates="assessment")


class Decision(Base):
    """The loan officer's decision, recorded after seeing the assessment.
    Kept apart from the assessment: the model recommends, the officer decides.

    `decision` is the coarse value every row has (approve | decline | refer);
    `outcome` the full one. Rows from before outcomes existed have no outcome,
    no amounts and their officer's note in `note`; they cannot be updated to
    add them (immutable), so reads fall back (see effective_outcome)."""
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    interview_id: Mapped[int] = mapped_column(ForeignKey("interviews.id"), unique=True)
    decision: Mapped[str] = mapped_column(String(20))   # approve | decline | refer
    note: Mapped[str | None] = mapped_column(Text)      # legacy rows only; now officer_notes
    # Who recorded it. Null on decisions made before sign-in existed.
    decided_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    # approve | approve_with_guarantor | approve_reduced | refer | decline
    outcome: Mapped[str | None] = mapped_column(String(30))
    approved_amount_kes: Mapped[int | None] = mapped_column(Integer)
    guarantors_required: Mapped[int | None] = mapped_column(Integer)
    officer_notes: Mapped[str | None] = mapped_column(Text)    # never shown to members
    member_message: Mapped[str | None] = mapped_column(Text)   # plain language, shown to the member

    interview: Mapped[Interview] = relationship(back_populates="decision")

    @property
    def effective_outcome(self) -> str:
        return self.outcome or self.decision

    @property
    def effective_notes(self) -> str | None:
        return self.officer_notes or self.note


class User(Base):
    """A loan officer, administrator or SACCO member. Created with
    scripts/create_user.py or by an admin (POST /api/admin/users)."""
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))  # scrypt$n$r$p$salt$hash
    role: Mapped[str] = mapped_column(String(20))             # admin | officer | member
    # Google account linked for "Sign in with Google"; stored lower-case.
    # Set with scripts/link_google.py; a Google login never creates a user.
    email: Mapped[str | None] = mapped_column(String(254), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    @validates("email")
    def _lower_email(self, _key, value):
        return normalise_email(value)


class AuthSession(Base):
    """A signed-in browser. Only the SHA-256 of the cookie token is stored."""
    __tablename__ = "sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    auth_method: Mapped[str | None] = mapped_column(String(20))  # password | google

    user: Mapped[User] = relationship()


class Member(Base):
    """A SACCO member. No national ID number is stored (data minimisation,
    Kenya Data Protection Act 2019): the member number identifies them."""
    __tablename__ = "members"
    id: Mapped[int] = mapped_column(primary_key=True)
    member_no: Mapped[str] = mapped_column(String(32), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    phone: Mapped[str | None] = mapped_column(String(20))
    joined_on: Mapped[date] = mapped_column(Date)      # membership start, for the tenure rule
    # The member's own login, if they have one.
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    user: Mapped[User | None] = relationship()
    applications: Mapped[list[LoanApplication]] = relationship(back_populates="member")


APPLICATION_STATUSES = ("draft", "interview_pending", "interview_complete", "assessed", "decided",
                        "guarantor_required", "guarantor_submitted", "approved", "declined")
GUARANTOR_STATUSES = ("pending", "verified", "rejected")


def _one_of(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class LoanApplication(Base):
    __tablename__ = "loan_applications"
    __table_args__ = (
        CheckConstraint(_one_of("status", APPLICATION_STATUSES), name="ck_loan_applications_status"),
        CheckConstraint("amount_requested_kes > 0", name="ck_loan_applications_amount"),
        CheckConstraint("term_months > 0", name="ck_loan_applications_term"),
        CheckConstraint("sacco_savings_kes >= 0", name="ck_loan_applications_savings"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    amount_requested_kes: Mapped[int] = mapped_column(Integer)
    purpose: Mapped[str] = mapped_column(Text)
    term_months: Mapped[int] = mapped_column(Integer)
    sacco_savings_kes: Mapped[int] = mapped_column(Integer)   # from the SACCO's records
    interview_id: Mapped[int | None] = mapped_column(ForeignKey("interviews.id"), unique=True)
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    member: Mapped[Member] = relationship(back_populates="applications")
    interview: Mapped[Interview | None] = relationship(back_populates="application")
    guarantors: Mapped[list[Guarantor]] = relationship(back_populates="application",
                                                       order_by="Guarantor.id")
    creator: Mapped[User] = relationship()


class Guarantor(Base):
    __tablename__ = "guarantors"
    __table_args__ = (
        CheckConstraint(_one_of("status", GUARANTOR_STATUSES), name="ck_guarantors_status"),
        CheckConstraint("amount_guaranteed_kes > 0", name="ck_guarantors_amount"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("loan_applications.id"), index=True)
    full_name: Mapped[str] = mapped_column(String(200))
    member_no: Mapped[str] = mapped_column(String(32))
    phone: Mapped[str] = mapped_column(String(20))
    relationship_: Mapped[str] = mapped_column("relationship", String(60))
    amount_guaranteed_kes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), default="pending")
    submitted_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    # The officer who verified or rejected it.
    verified_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    application: Mapped[LoanApplication] = relationship(back_populates="guarantors")
    verifier: Mapped[User | None] = relationship()


class AuditLog(Base):
    """Append-only: database triggers reject UPDATE and DELETE."""
    __tablename__ = "audit_log"
    __table_args__ = (Index("ix_audit_log_entity", "entity", "entity_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    # Null for actions with no signed-in user (scripts run from the shell).
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), index=True)
    action: Mapped[str] = mapped_column(String(64), index=True)
    entity: Mapped[str] = mapped_column(String(40))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    details: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


def make_engine(url: str) -> Engine:
    if make_url(url).get_backend_name() != "sqlite":
        # Supabase's pooler closes idle connections; check before use.
        return create_engine(url, pool_pre_ping=True)
    eng = create_engine(url, connect_args={"check_same_thread": False, "timeout": 30})

    @event.listens_for(eng, "connect")
    def _sqlite_pragmas(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys=ON")
        cur.execute("PRAGMA journal_mode=WAL")  # dashboard polls while workers write
        cur.close()
    return eng


def sqlite_file(bind: Engine) -> Path | None:
    """The database file behind a SQLite engine; None for memory or another dialect."""
    url = bind.url
    return Path(url.database) if url.get_backend_name() == "sqlite" and url.database \
        and url.database != ":memory:" else None


engine = make_engine(config.DATABASE_URL)   # connects on first use, not here
if (_f := sqlite_file(engine)) is not None:
    _f.parent.mkdir(parents=True, exist_ok=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


def get_db():
    with SessionLocal() as db:
        yield db


# --- Migrations ----------------------------------------------------------------

MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations"


def alembic_config(url: str | None = None):
    from alembic.config import Config
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    # ConfigParser interpolates %; a password may contain one.
    cfg.set_main_option("sqlalchemy.url", (url or config.DATABASE_URL).replace("%", "%%"))
    return cfg


def head_revision() -> str:
    from alembic.script import ScriptDirectory
    return ScriptDirectory.from_config(alembic_config()).get_current_head()


def schema_revision(bind: Engine) -> str | None:
    from alembic.runtime.migration import MigrationContext
    with bind.connect() as conn:
        return MigrationContext.configure(conn).get_current_revision()


def backup_sqlite(path: Path, tag: str) -> Path | None:
    """Copy a SQLite database that holds tables before migrating it; the
    online backup API takes the WAL into account. Returns the copy."""
    if not path.is_file() or path.stat().st_size == 0:
        return None
    src = sqlite3.connect(path)
    try:
        if not src.execute("SELECT count(*) FROM sqlite_master WHERE type='table'").fetchone()[0]:
            return None
        dst_path = path.with_name(f"{path.name}.pre-{tag}-{utcnow():%Y%m%d%H%M%S}.bak")
        dst = sqlite3.connect(dst_path)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return dst_path


def _migration_engine(url) -> Engine:
    """A SQLite engine whose transactions really are transactions, DDL
    included (pysqlite otherwise commits before each CREATE/ALTER), so a
    failed migration leaves the database as it was."""
    eng = create_engine(url)

    @event.listens_for(eng, "connect")
    def _connect(dbapi_conn, _):
        dbapi_conn.isolation_level = None
        dbapi_conn.execute("PRAGMA foreign_keys=ON")

    @event.listens_for(eng, "begin")
    def _begin(conn):
        conn.exec_driver_sql("BEGIN")
    return eng


def init_db(bind: Engine | None = None) -> None:
    """Bring the schema to the latest migration (`alembic upgrade head`).

    SQLite is upgraded here, in one transaction, after a backup copy of a
    database that already holds tables. PostgreSQL is never migrated
    implicitly: it must already be at head, or this raises and says to run
    `alembic upgrade head`. Existing rows are kept as they are."""
    from alembic import command
    bind = engine if bind is None else bind
    current, head = schema_revision(bind), head_revision()
    if current == head:
        return
    if bind.dialect.name != "sqlite":
        raise RuntimeError(f"database schema is at {current or 'no revision'} but this code needs "
                           f"{head}; run `alembic upgrade head` against DATABASE_URL first")
    path = sqlite_file(bind)
    if path is not None and (copy := backup_sqlite(path, head)) is not None:
        log.info("database at %s; backed up to %s before migrating to %s",
                 current or "pre-Alembic schema", copy, head)
    mig = _migration_engine(bind.url)
    try:
        with mig.begin() as conn:
            cfg = alembic_config(bind.url.render_as_string(hide_password=False))
            cfg.attributes["connection"] = conn
            command.upgrade(cfg, "head")
    finally:
        mig.dispose()
