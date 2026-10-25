"""SQLite storage: applicants, interviews, responses, assessments, users.

An assessment row is the audit record (Chapter 4): it stores the exact feature
vector the classifier saw, never something re-derived later. The officer's
decision is a separate record. SQLite triggers reject any UPDATE or DELETE on
either, so the guarantee holds even outside the API.
"""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import (JSON, Boolean, DateTime, Float, ForeignKey, Integer,
                        String, Text, TypeDecorator, UniqueConstraint,
                        create_engine, event)
from sqlalchemy.orm import (DeclarativeBase, Mapped, mapped_column,
                            relationship, sessionmaker, validates)

from chamapro import config


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def normalise_email(value: str | None) -> str | None:
    """Emails are compared lower-case; blank means none."""
    value = (value or "").strip().lower()
    return value or None


class UTCDateTime(TypeDecorator):
    """SQLite drops tzinfo; store UTC and hand it back timezone-aware."""
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
    Kept apart from the assessment: the model recommends, the officer decides."""
    __tablename__ = "decisions"
    id: Mapped[int] = mapped_column(primary_key=True)
    interview_id: Mapped[int] = mapped_column(ForeignKey("interviews.id"), unique=True)
    decision: Mapped[str] = mapped_column(String(20))   # approve | decline | refer
    note: Mapped[str | None] = mapped_column(Text)
    # Who recorded it. Null on decisions made before sign-in existed.
    decided_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    interview: Mapped[Interview] = relationship(back_populates="decision")


class User(Base):
    """A loan officer or administrator. Created with scripts/create_user.py."""
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))  # scrypt$n$r$p$salt$hash
    role: Mapped[str] = mapped_column(String(20))             # officer | admin
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


IMMUTABLE_TRIGGERS = [
    f"""CREATE TRIGGER IF NOT EXISTS {table}_no_{op.lower()}
        BEFORE {op} ON {table}
        BEGIN SELECT RAISE(ABORT, '{table} are immutable'); END"""
    for table in ("assessments", "decisions") for op in ("UPDATE", "DELETE")
]

config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
engine = create_engine(f"sqlite:///{config.DB_PATH}",
                       connect_args={"check_same_thread": False, "timeout": 30})
SessionLocal = sessionmaker(engine, expire_on_commit=False)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _):
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA foreign_keys=ON")
    cur.execute("PRAGMA journal_mode=WAL")  # dashboard polls while workers write
    cur.close()


# Columns added after the first release. ADD COLUMN leaves existing rows as
# they were (NULL, or the DEFAULT given) and fires no UPDATE trigger, so
# immutability holds. Interviews from before question sets existed are the
# 40-sentence Kikuyu set, live, with recorded answers: v1 / kik / live / audio.
ADDED_COLUMNS = [("assessments", "assessed_by", "VARCHAR(64)"),
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
# SQLite cannot add a UNIQUE column, so uniqueness comes from an index
# (the same one create_all makes on a new database).
ADDED_INDEXES = ["CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email ON users (email)"]


def init_db(bind=None) -> None:
    """Create missing tables and columns; existing rows are kept as they are."""
    bind = bind if bind is not None else engine
    Base.metadata.create_all(bind)
    with bind.begin() as conn:
        for table, column, ddl_type in ADDED_COLUMNS:
            have = {r[1] for r in conn.exec_driver_sql(f"PRAGMA table_info({table})")}
            if column not in have:
                conn.exec_driver_sql(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")
        for ddl in ADDED_INDEXES + IMMUTABLE_TRIGGERS:
            conn.exec_driver_sql(ddl)
