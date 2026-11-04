"""Storage: applicants, interviews, responses, assessments, users, members,
member profiles, savings accounts and their ledger, issued loans, standing
guarantors, loan applications, guarantors, interview bookings, SACCO events, the
volunteer pilot's records, automatic decisions, idempotency keys and the audit log.

SQLite by default; PostgreSQL (Supabase) by setting DATABASE_URL. The schema
is owned by the Alembic migrations in chamapro/migrations, not by this file:
init_db() runs them.

An assessment row is the audit record (Chapter 4): it stores the exact feature
vector the classifier saw, never something re-derived later. The officer's
decision is a separate record. Database triggers (SQLite and PostgreSQL)
reject any UPDATE or DELETE on either, on the audit log, on a member's profile
history and on the savings ledger, so the guarantee holds even outside the API.
"""
from __future__ import annotations

import logging
import re
import sqlite3
from contextvars import ContextVar
from datetime import date, datetime, timezone
from pathlib import Path

from sqlalchemy import (JSON, Boolean, CheckConstraint, Date, DateTime, Engine,
                        Float, ForeignKey, ForeignKeyConstraint, Index, Integer, String, Text,
                        TypeDecorator, UniqueConstraint, create_engine, event,
                        false, make_url, text)
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


def nairobi_today() -> date:
    """The calendar date at the branch: bookings and daily limits count by this."""
    return datetime.now(config.NAIROBI).date()


# 07.. or 01.. nationally, 2547.. or 2541.. internationally, with or without the +.
_PHONE = re.compile(r"(?:\+?254|0)([17][0-9]{8})")


def normalise_phone(value: str | None) -> str | None:
    """A Kenyan mobile number as +254XXXXXXXXX; blank means none. Raises
    ValueError for anything else. One stored form, so a duplicate is a duplicate
    however it was typed."""
    value = re.sub(r"[\s()-]", "", value or "")
    if not value:
        return None
    match = _PHONE.fullmatch(value)
    if match is None:
        raise ValueError("a Kenyan mobile number such as 0712345678 or +254712345678")
    return "+254" + match[1]


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
    # Set only by scripts/seed_demo.py, to find its own rows again; never sent to a browser.
    seed_tag: Mapped[str | None] = mapped_column(String(40), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class Interview(Base):
    __tablename__ = "interviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    applicant_id: Mapped[int] = mapped_column(ForeignKey("applicants.id"))
    status: Mapped[str] = mapped_column(String(20), default="open")  # open | assessed
    # Rows from before these existed are v1 / kik / live (see ADDED_COLUMNS).
    question_set: Mapped[str] = mapped_column(String(8), default="v2")    # v1 | v2
    language: Mapped[str] = mapped_column(String(8), default="kik")       # kik | en
    # self_service: no answers; the record of an automatic decision (SelfServiceRun).
    mode: Mapped[str] = mapped_column(String(12), default="live")         # live | practice | self_service
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
    # Automatic decisions only: where each value came from, what the member said in
    # the conversation, and every check the policy ran with its values.
    provenance: Mapped[dict | None] = mapped_column(JSON)
    overrides: Mapped[dict | None] = mapped_column(JSON)
    policy_trace: Mapped[dict | None] = mapped_column(JSON)

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
    # approve | approve_with_guarantor | approve_reduced | refer | decline | not_now
    outcome: Mapped[str | None] = mapped_column(String(30))
    approved_amount_kes: Mapped[int | None] = mapped_column(Integer)
    guarantors_required: Mapped[int | None] = mapped_column(Integer)
    officer_notes: Mapped[str | None] = mapped_column(Text)    # never shown to members
    member_message: Mapped[str | None] = mapped_column(Text)   # plain language, shown to the member
    policy_version: Mapped[str | None] = mapped_column(String(32))  # automatic decisions only

    interview: Mapped[Interview] = relationship(back_populates="decision")

    @property
    def effective_outcome(self) -> str:
        return self.outcome or self.decision

    @property
    def effective_notes(self) -> str | None:
        return self.officer_notes or self.note


# Who an automatic decision is by. Migration 0006 makes this one row: inactive, no
# usable password, a role no endpoint admits, and hidden from the admin's user list.
SYSTEM_USERNAME = "system"
SYSTEM_ROLE = "system"


class User(Base):
    """A loan officer, administrator or SACCO member. Created with
    scripts/create_user.py or by an admin (POST /api/admin/users)."""
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))  # scrypt$n$r$p$salt$hash
    role: Mapped[str] = mapped_column(String(20))             # admin | officer | member
    # The name shown beside the role; the username stays the login.
    display_name: Mapped[str | None] = mapped_column(String(120))
    # Google account linked for "Sign in with Google"; stored lower-case.
    # Set with scripts/link_google.py; a Google login never creates a user.
    email: Mapped[str | None] = mapped_column(String(254), unique=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    seed_tag: Mapped[str | None] = mapped_column(String(40), index=True)   # as Applicant.seed_tag
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
    __table_args__ = (Index("uq_members_phone", "phone", unique=True),)
    id: Mapped[int] = mapped_column(primary_key=True)
    member_no: Mapped[str] = mapped_column(String(32), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    # +254XXXXXXXXX, unique when present. Staff-created members may have none.
    phone: Mapped[str | None] = mapped_column(String(20))
    joined_on: Mapped[date] = mapped_column(Date)      # membership start, for the tenure rule
    # The member's own login, if they have one.
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), unique=True)
    seed_tag: Mapped[str | None] = mapped_column(String(40), index=True)   # as Applicant.seed_tag
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    # A contact address the member typed, unverified. Not users.email: that one
    # signs in with Google, and must stay something only an admin can set.
    email: Mapped[str | None] = mapped_column(String(254))
    # Null: not entered. Self-declared until savings_verified_at is set.
    savings_kes: Mapped[int | None] = mapped_column(Integer)
    savings_verified_by: Mapped[str | None] = mapped_column(String(64))    # username
    savings_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # The applicant form, kept for next time. A birth year rather than an age,
    # so it does not go stale, and rather than a birth date, which is not needed.
    birth_year: Mapped[int | None] = mapped_column(Integer)
    sex: Mapped[str | None] = mapped_column(String(10))
    education: Mapped[int | None] = mapped_column(Integer)
    marital_status: Mapped[str | None] = mapped_column(String(10))
    consent_version: Mapped[str | None] = mapped_column(String(32))
    consent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    # Volunteers who signed up themselves, as against members staff created.
    self_signed_up: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    user: Mapped[User | None] = relationship()
    applications: Mapped[list[LoanApplication]] = relationship(back_populates="member")
    profile: Mapped[MemberProfile | None] = relationship(back_populates="member")

    @validates("phone")
    def _canonical_phone(self, _key, value):
        return normalise_phone(value)


APPLICATION_STATUSES = ("draft", "interview_pending", "interview_complete", "assessed", "decided",
                        "guarantor_required", "guarantor_submitted", "approved", "declined",
                        "offered", "reversed")
APPLICATION_CHANNELS = ("branch", "self_service")
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
        CheckConstraint(_one_of("channel", APPLICATION_CHANNELS), name="ck_loan_applications_channel"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    amount_requested_kes: Mapped[int] = mapped_column(Integer)
    purpose: Mapped[str] = mapped_column(Text)
    term_months: Mapped[int] = mapped_column(Integer)
    sacco_savings_kes: Mapped[int] = mapped_column(Integer)   # from the SACCO's records
    # True while that figure is only what the member declared; see Member.savings_kes.
    savings_self_declared: Mapped[bool] = mapped_column(Boolean, default=False,
                                                        server_default=false())
    channel: Mapped[str] = mapped_column(String(14), default="branch", server_default="branch")
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
        CheckConstraint("application_id IS NOT NULL OR loan_account_id IS NOT NULL",
                        name="ck_guarantors_backs_something"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    # Null only on a loan issued without an application (loan_account_id says which).
    application_id: Mapped[int | None] = mapped_column(ForeignKey("loan_applications.id"), index=True)
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

    application: Mapped[LoanApplication | None] = relationship(back_populates="guarantors")
    verifier: Mapped[User | None] = relationship()
    # The member this is, when member_no is one of ours: what guarantee capacity
    # is counted against. member_no and phone stay as they were submitted.
    member_id: Mapped[int | None] = mapped_column(ForeignKey("members.id"), index=True)
    pledge_id: Mapped[int | None] = mapped_column(ForeignKey("guarantor_pledges.id"))
    # Set when the loan is issued; a guarantee counts against capacity from then on.
    loan_account_id: Mapped[int | None] = mapped_column(ForeignKey("loan_accounts.id"), index=True)
    # Accepted by the system under pledge_id, without an officer's review.
    accepted_under_pledge: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


# --- A member's profile -----------------------------------------------------------------------

PROFILE_SOURCES = ("registration", "member_update", "officer_verified", "seed")
# What each group of member_profiles holds; each has its own <group>_source,
# _updated_at, _verified_by and _verified_at columns.
PROFILE_GROUPS = {
    "personal": ("date_of_birth", "sex", "education", "marital_status"),
    "household": ("household_size", "children", "children_under5", "children_in_school"),
    "income": ("monthly_income_kes", "agri_income_kes", "income_sources"),
    "assets": ("non_monetary_savings", "purchases_last_12m"),
    "credit": ("chama_loan_use", "lost_as_guarantor_chama"),
}


class MemberProfile(Base):
    """One current row per member: every classifier input the v2 questions
    collected that the SACCO cannot read from its own records. Keys inside the
    JSON flags are score_interview's. sacco_loan_use and lost_as_guarantor.sacco
    are not here: profiles.profile_features derives them from the ledger."""
    __tablename__ = "member_profiles"
    __table_args__ = (
        *(CheckConstraint(f"{g}_source IS NULL OR {_one_of(f'{g}_source', PROFILE_SOURCES)}",
                          name=f"ck_member_profiles_{g}_source") for g in PROFILE_GROUPS),
        CheckConstraint("education IS NULL OR education BETWEEN 0 AND 8",
                        name="ck_member_profiles_education"),
        CheckConstraint("chama_loan_use IS NULL OR chama_loan_use IN (0, 1, 2)",
                        name="ck_member_profiles_chama_loan_use"),
        CheckConstraint("lost_as_guarantor_chama IS NULL OR lost_as_guarantor_chama IN (0, 1)",
                        name="ck_member_profiles_lost_chama"),
    )
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), primary_key=True)
    date_of_birth: Mapped[date | None] = mapped_column(Date)     # age is derived from it
    sex: Mapped[str | None] = mapped_column(String(10))
    education: Mapped[int | None] = mapped_column(Integer)       # 0-8, score_interview.EDU_LADDER
    marital_status: Mapped[str | None] = mapped_column(String(10))
    household_size: Mapped[int | None] = mapped_column(Integer)
    children: Mapped[int | None] = mapped_column(Integer)
    children_under5: Mapped[int | None] = mapped_column(Integer)
    children_in_school: Mapped[int | None] = mapped_column(Integer)
    monthly_income_kes: Mapped[int | None] = mapped_column(Integer)
    agri_income_kes: Mapped[int | None] = mapped_column(Integer)
    income_sources: Mapped[dict | None] = mapped_column(JSON)    # score_interview.INCOME_SOURCES -> 0/1
    non_monetary_savings: Mapped[dict | None] = mapped_column(JSON)   # score_interview.SAVINGS -> 0/1
    purchases_last_12m: Mapped[dict | None] = mapped_column(JSON)     # score_interview.PURCHASES -> 0/1
    chama_loan_use: Mapped[int | None] = mapped_column(Integer)  # 0 never, 1 used to, 2 currently
    lost_as_guarantor_chama: Mapped[int | None] = mapped_column(Integer)   # lost_as_guarantor.chama

    personal_source: Mapped[str | None] = mapped_column(String(20))
    personal_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    personal_verified_by: Mapped[str | None] = mapped_column(String(64))   # username
    personal_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    household_source: Mapped[str | None] = mapped_column(String(20))
    household_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    household_verified_by: Mapped[str | None] = mapped_column(String(64))
    household_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    income_source: Mapped[str | None] = mapped_column(String(20))
    income_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    income_verified_by: Mapped[str | None] = mapped_column(String(64))
    income_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    assets_source: Mapped[str | None] = mapped_column(String(20))
    assets_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    assets_verified_by: Mapped[str | None] = mapped_column(String(64))
    assets_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    credit_source: Mapped[str | None] = mapped_column(String(20))
    credit_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    credit_verified_by: Mapped[str | None] = mapped_column(String(64))
    credit_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime)

    # When the member last said it is right, or an officer verified it.
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    member: Mapped[Member] = relationship(back_populates="profile")


class MemberProfileHistory(Base):
    """Append-only: a snapshot of the whole profile after every change, kept by
    database triggers. change is a PROFILE_SOURCES value or "confirm"."""
    __tablename__ = "member_profile_history"
    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    change: Mapped[str] = mapped_column(String(20))
    groups: Mapped[list] = mapped_column(JSON)      # the field groups this change touched
    snapshot: Mapped[dict] = mapped_column(JSON)    # the row's columns, ISO dates as text
    # Null for scripts run from the shell, as in the audit log.
    actor_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


# --- Savings accounts and their ledger --------------------------------------------------------

ACCOUNT_KINDS = ("deposits", "share_capital", "transactional")
ENTRY_TYPES = ("deposit", "withdrawal", "loan_disbursement", "loan_repayment",
               "guarantee_recovery", "dividend", "loan_reversal", "deposit_refund")
LOAN_STATUSES = ("active", "repaid", "defaulted", "reversed")
PLEDGE_STATUSES = ("active", "withdrawn")
# The sign of each type's amount, and the accounts it may be posted to: deposits
# back loans and are never withdrawn, only refunded to a departing member; loans
# are paid out to the transactional account, and undone there by a loan_reversal,
# whose sign is the opposite of the entry it compensates; and a guarantee is
# recovered from the guarantor's deposits.
ENTRY_RULES = (
    ("ck_account_entries_sign",
     "(entry_type IN ('deposit', 'loan_disbursement', 'dividend') AND amount_kes > 0) "
     "OR (entry_type IN ('withdrawal', 'loan_repayment', 'guarantee_recovery', 'deposit_refund') AND amount_kes < 0) "
     "OR (entry_type = 'loan_reversal' AND amount_kes != 0)"),
    ("ck_account_entries_no_deposit_withdrawal",
     "NOT (entry_type = 'withdrawal' AND account_kind = 'deposits')"),
    ("ck_account_entries_disbursed_to_transactional",
     "entry_type NOT IN ('loan_disbursement', 'loan_repayment', 'loan_reversal') OR account_kind = 'transactional'"),
    ("ck_account_entries_recovered_from_deposits",
     "entry_type NOT IN ('guarantee_recovery', 'deposit_refund') OR account_kind = 'deposits'"),
)


class MemberAccount(Base):
    """One of a member's three accounts. Its balance is never stored: it is the
    sum of its entries (ledger.py)."""
    __tablename__ = "member_accounts"
    __table_args__ = (
        CheckConstraint(_one_of("kind", ACCOUNT_KINDS), name="ck_member_accounts_kind"),
        UniqueConstraint("member_id", "kind", name="uq_member_accounts_member_kind"),
        # What account_entries' composite foreign key points at.
        UniqueConstraint("id", "kind", name="uq_member_accounts_id_kind"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    kind: Mapped[str] = mapped_column(String(14))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class AccountEntry(Base):
    """Append-only: one signed movement on an account, kept by database triggers.
    A correction is a new entry. account_kind repeats the account's kind, held
    true by the composite foreign key, so that CHECK constraints can state
    ENTRY_RULES and the database itself refuses a withdrawal from deposits."""
    __tablename__ = "account_entries"
    __table_args__ = (
        ForeignKeyConstraint(["account_id", "account_kind"], ["member_accounts.id", "member_accounts.kind"],
                             name="fk_account_entries_account"),
        CheckConstraint(_one_of("entry_type", ENTRY_TYPES), name="ck_account_entries_type"),
        *(CheckConstraint(sql, name=name) for name, sql in ENTRY_RULES),
        UniqueConstraint("account_id", "reference", name="uq_account_entries_reference"),
        # Serves every balance and "the last ten entries" without touching the table's other rows.
        Index("ix_account_entries_account_posted", "account_id", "posted_at", "id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    account_id: Mapped[int] = mapped_column(Integer)
    account_kind: Mapped[str] = mapped_column(String(14))
    entry_type: Mapped[str] = mapped_column(String(20))
    amount_kes: Mapped[int] = mapped_column(Integer)
    posted_at: Mapped[datetime] = mapped_column(UTCDateTime)
    reference: Mapped[str] = mapped_column(String(40))
    # Null for scripts run from the shell, as in the audit log.
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    # The loan a disbursement, repayment or recovery belongs to.
    loan_account_id: Mapped[int | None] = mapped_column(ForeignKey("loan_accounts.id"), index=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class LoanAccount(Base):
    """An issued loan. What has been repaid and any arrears are computed from
    the ledger (ledger.py), never stored."""
    __tablename__ = "loan_accounts"
    __table_args__ = (
        CheckConstraint(_one_of("status", LOAN_STATUSES), name="ck_loan_accounts_status"),
        CheckConstraint("principal_kes > 0", name="ck_loan_accounts_principal"),
        CheckConstraint("term_months > 0", name="ck_loan_accounts_term"),
        CheckConstraint("monthly_instalment_kes > 0", name="ck_loan_accounts_instalment"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    # The application it came from; loans from before the system have none.
    application_id: Mapped[int | None] = mapped_column(ForeignKey("loan_applications.id"), unique=True)
    principal_kes: Mapped[int] = mapped_column(Integer)
    disbursed_on: Mapped[date] = mapped_column(Date)
    term_months: Mapped[int] = mapped_column(Integer)
    monthly_instalment_kes: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), default="active")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class GuarantorPledge(Base):
    """A member standing ready to guarantee another member's loans. It holds no
    amount: capacity is worked out when an application needs it, and a pledge
    becomes a guarantors row, reviewed like any other."""
    __tablename__ = "guarantor_pledges"
    __table_args__ = (
        CheckConstraint(_one_of("status", PLEDGE_STATUSES), name="ck_guarantor_pledges_status"),
        CheckConstraint("borrower_member_id != guarantor_member_id", name="ck_guarantor_pledges_self"),
        Index("uq_guarantor_pledges_active", "borrower_member_id", "guarantor_member_id", unique=True,
              sqlite_where=text("status = 'active'"), postgresql_where=text("status = 'active'")),
        Index("ix_guarantor_pledges_guarantor", "guarantor_member_id"),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    borrower_member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    guarantor_member_id: Mapped[int] = mapped_column(ForeignKey("members.id"))
    status: Mapped[str] = mapped_column(String(10), default="active")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    borrower: Mapped[Member] = relationship(foreign_keys=[borrower_member_id])
    guarantor: Mapped[Member] = relationship(foreign_keys=[guarantor_member_id])


BOOKING_STATUSES = ("requested", "confirmed", "started", "cancelled")
EVENT_TYPES = ("agm", "member_meeting", "training", "loan_deadline", "other")
_HOLDS_SLOT = "status IN ('requested', 'confirmed', 'started')"
_OPEN_BOOKING = "status IN ('requested', 'confirmed')"


class InterviewBooking(Base):
    """A half-hour interview slot at the one branch. The partial unique indexes
    are what make double booking impossible, whichever request gets there first."""
    __tablename__ = "interview_bookings"
    __table_args__ = (
        CheckConstraint(_one_of("status", BOOKING_STATUSES), name="ck_interview_bookings_status"),
        Index("uq_interview_bookings_slot", "starts_at", unique=True,
              sqlite_where=text(_HOLDS_SLOT), postgresql_where=text(_HOLDS_SLOT)),
        Index("uq_interview_bookings_open", "application_id", unique=True,
              sqlite_where=text(_OPEN_BOOKING), postgresql_where=text(_OPEN_BOOKING)),
    )
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("loan_applications.id"), index=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime)    # shown in Nairobi time
    language: Mapped[str] = mapped_column(String(8))            # kik | en
    status: Mapped[str] = mapped_column(String(12), default="requested")
    interview_id: Mapped[int | None] = mapped_column(ForeignKey("interviews.id"))   # once started
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    application: Mapped[LoanApplication] = relationship()
    member: Mapped[Member] = relationship()


class SaccoEvent(Base):
    __tablename__ = "sacco_events"
    __table_args__ = (CheckConstraint(_one_of("event_type", EVENT_TYPES), name="ck_sacco_events_type"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    event_type: Mapped[str] = mapped_column(String(20))
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    location: Mapped[str | None] = mapped_column(String(200))
    online_link: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class PracticeInterview(Base):
    """A member's own practice run on their application. Kept apart from
    LoanApplication.interview_id, the one interview that moves the application:
    a practice run must never advance a real application, or take the place of
    the interview an officer holds."""
    __tablename__ = "practice_interviews"
    id: Mapped[int] = mapped_column(primary_key=True)
    interview_id: Mapped[int] = mapped_column(ForeignKey("interviews.id"), unique=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("loan_applications.id"), index=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    interview: Mapped[Interview] = relationship()
    member: Mapped[Member] = relationship()
    application: Mapped[LoanApplication] = relationship()


class PilotDailyUsage(Base):
    """Submissions used on one Nairobi day, per member and in total (scope
    "member:<id>" or "all"), raised by a conditional UPDATE so two requests at
    once cannot pass the cap together."""
    __tablename__ = "pilot_daily_usage"
    __table_args__ = (CheckConstraint("used >= 0", name="ck_pilot_daily_usage_used"),)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    scope: Mapped[str] = mapped_column(String(40), primary_key=True)
    used: Mapped[int] = mapped_column(Integer, default=0)


class SusResponse(Base):
    """One System Usability Scale questionnaire, offered after a submission."""
    __tablename__ = "sus_responses"
    id: Mapped[int] = mapped_column(primary_key=True)
    interview_id: Mapped[int] = mapped_column(ForeignKey("interviews.id"), unique=True)
    member_id: Mapped[int] = mapped_column(ForeignKey("members.id"), index=True)
    answers: Mapped[list] = mapped_column(JSON)      # ten integers, 1-5, in question order
    score: Mapped[float] = mapped_column(Float)      # 0-100
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)


class SelfServiceRun(Base):
    """One automatic decision on an application: which interview holds its immutable
    assessment and decision. Kept apart from LoanApplication.interview_id, which moves
    on: to the second run when a member accepts a reduced offer, to the live interview
    when a referral is booked. The record of what the system decided must not."""
    __tablename__ = "self_service_runs"
    id: Mapped[int] = mapped_column(primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("loan_applications.id"), index=True)
    interview_id: Mapped[int] = mapped_column(ForeignKey("interviews.id"), unique=True)
    trigger: Mapped[str] = mapped_column(String(12))     # commit | acceptance
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)

    application: Mapped[LoanApplication] = relationship()
    interview: Mapped[Interview] = relationship()


class IdempotencyKey(Base):
    """One money-moving request per key, per user. The row goes in first, in the
    request's own transaction, so a second request with the key waits for the first
    and then gets the reply it stored; a request refused leaves no row."""
    __tablename__ = "idempotency_keys"
    __table_args__ = (UniqueConstraint("actor_user_id", "key", name="uq_idempotency_keys_actor_key"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    actor_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    key: Mapped[str] = mapped_column(String(64))
    request_hash: Mapped[str] = mapped_column(String(64))
    status_code: Mapped[int | None] = mapped_column(Integer)
    response: Mapped[dict | list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


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
        # Supabase's pooler closes idle connections, and recycling ahead of
        # its idle timeout does not catch one dropped for any other reason: a
        # dead pooled connection hangs the request that gets it. The pre-ping
        # costs a round trip per checkout (~200 ms from Nairobi to eu-west-1),
        # so a request checks out once (auth shares get_db's session).
        # connect_timeout stops a stalled connect at 10 s instead of hanging.
        return create_engine(url, pool_size=5, max_overflow=5, pool_recycle=240,
                             pool_timeout=10, pool_pre_ping=True,
                             connect_args={"connect_timeout": 10})
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

# Statements run for the current API request, for its log line (main.QueryLog).
# None outside a request: the transcription worker's queries are not counted.
query_count: ContextVar[list[int] | None] = ContextVar("query_count", default=None)


@event.listens_for(engine, "before_cursor_execute")
def _count_query(*_):
    if (n := query_count.get()) is not None:
        n[0] += 1


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
    failed migration leaves the database as it was.

    Foreign keys are off, as SQLite's own procedure for rebuilding a table says:
    with them on, dropping a table other tables point at fails, and a CHECK can
    only be changed by a rebuild. init_db checks them before it commits."""
    eng = create_engine(url)

    @event.listens_for(eng, "connect")
    def _connect(dbapi_conn, _):
        dbapi_conn.isolation_level = None
        dbapi_conn.execute("PRAGMA foreign_keys=OFF")

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
            broken = conn.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
            if broken:
                raise RuntimeError(f"migrating left {len(broken)} broken foreign key(s), the first in "
                                   f"table {broken[0][0]}; nothing was changed")
    finally:
        mig.dispose()
