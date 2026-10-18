"""SQLite storage: applicants, interviews, responses, assessments.

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
                            relationship, sessionmaker)

from chamapro import config


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


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
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Interview(Base):
    __tablename__ = "interviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    applicant_id: Mapped[int] = mapped_column(ForeignKey("applicants.id"))
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | assessed
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
    domain: Mapped[str | None] = mapped_column(String(40))
    audio_path: Mapped[str] = mapped_column(Text)
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
    extracted: Mapped[dict] = mapped_column(JSON)
    extraction_completeness: Mapped[float] = mapped_column(Float)
    features_populated: Mapped[int] = mapped_column(Integer)
    features_total: Mapped[int] = mapped_column(Integer)
    features_not_extractable: Mapped[list] = mapped_column(JSON)
    extraction_model: Mapped[str] = mapped_column(String(200))
    model_file: Mapped[str] = mapped_column(String(200))
    model_sha256: Mapped[str] = mapped_column(String(64))
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
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    interview: Mapped[Interview] = relationship(back_populates="decision")


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


def init_db() -> None:
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for ddl in IMMUTABLE_TRIGGERS:
            conn.exec_driver_sql(ddl)
