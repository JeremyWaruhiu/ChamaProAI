"""Request and response bodies."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Stored status is queued | transcribed | failed. Reads report the one clip the
# worker has in hand as "transcribing"; it is still "queued" in the database.
ResponseStatus = Literal["queued", "transcribing", "transcribed", "failed"]
InterviewStatus = Literal["open", "assessed"]
QuestionSet = Literal["v1", "v2"]
Language = Literal["kik", "en"]
Mode = Literal["live", "practice"]
Source = Literal["audio", "typed"]
Sex = Literal["female", "male"]
MaritalStatus = Literal["married", "single", "widowed", "divorced"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Error(BaseModel):
    detail: str


class ApplicantForm(BaseModel):
    """Entered by the officer; fills age, is_female, education and marital_*
    directly, so the interview does not ask for them."""
    age: int = Field(ge=16, le=110)
    sex: Sex
    education: int = Field(ge=0, le=8, description="Code from GET /api/applicant-form "
                                                     "(FinAccess A20 ladder the classifier was trained on)")
    marital_status: MaritalStatus


class InterviewCreate(BaseModel):
    applicant_name: str | None = Field(default=None, max_length=200)
    applicant: ApplicantForm | None = Field(default=None, description="Required for question set v2")
    question_set: QuestionSet = Field(default="v2", description="v1 is the 40-sentence set of the recorded corpus")
    language: Language = "kik"
    mode: Mode = Field(default="live", description="practice interviews are excluded from live statistics")


class InterviewCreated(BaseModel):
    id: int
    status: InterviewStatus


class TypedResponse(BaseModel):
    sentence_no: int = Field(ge=1)
    text: str = Field(min_length=1, max_length=5000)


class Option(BaseModel):
    value: str | int
    label: str


class ApplicantFormOptions(BaseModel):
    sex: list[Option]
    education: list[Option] = Field(description="The classifier's education ladder, in order")
    marital_status: list[Option]


class ResponseQueued(BaseModel):
    id: int
    interview_id: int
    sentence_no: int
    status: ResponseStatus


class ResponseDeleted(BaseModel):
    id: int
    interview_id: int
    sentence_no: int
    was_queued: bool = Field(description="True if it was removed from the transcription queue")


class TranscriptEdit(BaseModel):
    transcript: str = Field(min_length=1)


class ResponseOut(ORM):
    id: int
    sentence_no: int
    domain: str | None
    source: Source = Field(description="typed answers skip ASR and have no audio")
    status: ResponseStatus
    error: str | None
    duration_s: float | None
    transcript: str | None
    transcript_asr: str | None = Field(description="ASR output before any edit")
    edited: bool
    edited_at: datetime | None
    asr_model: str | None
    asr_seconds: float | None
    translation: str | None
    signals: list[str] | None
    created_at: datetime


class Contribution(BaseModel):
    feature: str
    value: float | None
    shap: float


ConditionResult = Literal["pass", "fail", "pending"]
Agreement = Literal["agree", "diverge", "pending", "undetermined"]


class RuleCondition(BaseModel):
    name: Literal["savings_multiple", "guarantors", "tenure"]
    label: str
    result: ConditionResult
    detail: str
    agreement: Agreement = Field(description="agree / diverge with the model; pending while the "
                                             "condition is; undetermined when the model said Medium")


class Comparator(BaseModel):
    """The SACCO's own rule (Chapter 5), computed live; never stored with the
    assessment, which stays exactly as the model produced it."""
    rule: str
    max_borrowable_kes: int
    amount_requested_kes: int
    tenure_months: int
    verified_guarantors: int
    conditions: list[RuleCondition]
    result: ConditionResult = Field(description="fail if any condition fails; pending if any is pending")
    rule_recommendation: Literal["approve", "approve_with_guarantors", "decline"] = Field(
        description="approve_with_guarantors: every other condition passes, guarantors pending")
    model_recommendation: DecisionValue | None
    agreement: Agreement
    mode: Mode = Field(description="practice applications are left out of live statistics")


class AssessmentOut(ORM):
    id: int
    risk_class: str
    probabilities: dict[str, float]
    feature_vector: dict[str, float | None]
    contributions: list[Contribution] | str = Field(
        description="Top SHAP contributions, or a string saying why unavailable")
    extracted: dict
    applicant_form: dict | None = Field(default=None, description="Form values merged into the vector; "
                                                                  "null when the interview had no form")
    extraction_completeness: float
    features_populated: int
    features_total: int
    features_not_extractable: list[str]
    extraction_model: str
    model_file: str
    model_sha256: str
    assessed_by: str | None = Field(default=None, description="Username; null before sign-in existed")
    created_at: datetime
    comparator: Comparator | None = Field(default=None, description="The SACCO rule, when the "
                                          "interview belongs to a loan application")


class Question(BaseModel):
    id: str
    version: QuestionSet
    topic: str
    order: int = Field(description="Position in its set; a response's sentence_no")
    text_en: str
    text_kik: str = Field(description="Empty until a native speaker supplies it")
    features: list[str] = Field(description="Classifier features the question is asked for")


DecisionValue = Literal["approve", "decline", "refer"]
Outcome = Literal["approve", "approve_with_guarantor", "approve_reduced", "refer", "decline"]


class DecisionCreate(BaseModel):
    """`outcome` is the decision; `decision` (approve | decline | refer) is
    its older name and still accepted. `note` is the older name of officer_notes."""
    outcome: Outcome | None = None
    decision: DecisionValue | None = None
    approved_amount_kes: int | None = Field(default=None, gt=0, description="approve_reduced: "
                                            "required, below the amount requested")
    guarantors_required: int | None = Field(default=None, ge=1, le=10, description=
                                            "approve_with_guarantor only; default 2")
    officer_notes: str | None = Field(default=None, max_length=2000,
                                      description="Never shown to the member")
    note: str | None = Field(default=None, max_length=2000)
    member_message: str | None = Field(default=None, max_length=1000,
                                       description="Plain language, shown to the member")

    @model_validator(mode="after")
    def _one_outcome(self):
        if self.outcome is None and self.decision is None:
            raise ValueError("outcome: field required")
        if self.outcome is not None and self.decision is not None and self.outcome != self.decision:
            raise ValueError("give outcome or decision, not two different values")
        if self.officer_notes is not None and self.note is not None:
            raise ValueError("give officer_notes or note, not both")
        return self

    @property
    def chosen(self) -> str:
        return self.outcome or self.decision

    @property
    def notes(self) -> str | None:
        return (self.officer_notes if self.officer_notes is not None else self.note or "").strip() or None


class DecisionOut(ORM):
    decision: DecisionValue = Field(description="approve | decline | refer, on every decision")
    outcome: Outcome = Field(validation_alias="effective_outcome",
                             description="Equal to decision on decisions made before outcomes existed")
    approved_amount_kes: int | None = None
    guarantors_required: int | None = None
    officer_notes: str | None = Field(default=None, validation_alias="effective_notes")
    note: str | None = Field(default=None, validation_alias="effective_notes",
                             description="Same as officer_notes (older name)")
    member_message: str | None = None
    decided_by: str | None = Field(default=None, description="Username; null before sign-in existed")
    created_at: datetime


Role = Literal["admin", "officer", "member"]


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=1024)


class GoogleLogin(BaseModel):
    credential: str = Field(min_length=1, max_length=8192, description="ID token from Google Identity Services")


class AuthConfig(BaseModel):
    google_client_id: str | None = Field(description="Null when Google sign-in is not configured")


class Me(ORM):
    username: str
    role: Role


class Applicant(ORM):
    id: int
    name: str | None
    age: int | None = None
    sex: Sex | None = None
    education: int | None = None
    marital_status: MaritalStatus | None = None


class Counts(BaseModel):
    queued: int = 0
    transcribing: int = 0
    transcribed: int = 0
    failed: int = 0


class InterviewSummary(BaseModel):
    id: int
    applicant_name: str | None
    created_at: datetime
    status: InterviewStatus
    question_set: QuestionSet
    language: Language
    mode: Mode
    responses_recorded: int
    questions_total: int
    counts: Counts
    risk_class: str | None = Field(description="Set once the interview is assessed")
    decision: DecisionValue | None = Field(description="The officer's decision, once recorded")


class InterviewState(ORM):
    id: int
    status: InterviewStatus
    question_set: QuestionSet
    language: Language
    mode: Mode
    created_at: datetime
    applicant: Applicant
    counts: Counts
    responses: list[ResponseOut]
    assessment: AssessmentOut | None
    decision: DecisionOut | None
    application_id: int | None = Field(default=None, description="The loan application it belongs "
                                       "to; null for legacy, demo and practice interviews without one")


class AsrStatus(BaseModel):
    loaded: bool
    engine: str | None = Field(description="openvino | torch, as actually loaded after any fallback")
    device: str | None = Field(description="GPU | CPU, as actually loaded after any fallback")
    model: str | None
    language: str
    error: str | None = None


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    classifier_present: bool
    api_key_configured: bool
    asr_model: str
    asr_language: str
    asr_loaded: bool
    asr_engine: str | None = Field(description="Kikuyu ASR engine actually in use")
    asr_device: str | None = Field(description="Kikuyu ASR device actually in use")
    asr_decoding: str
    asr: dict[str, AsrStatus] = Field(description="Per interview language; English loads on first use")
    extraction_model: str
    classifier: dict | None = Field(description="classifier_meta.json, if present")


# --- Members, applications, guarantors -----------------------------------------

ApplicationStatus = Literal["draft", "interview_pending", "interview_complete", "assessed",
                            "decided", "guarantor_required", "guarantor_submitted",
                            "approved", "declined"]
GuarantorStatus = Literal["pending", "verified", "rejected"]
MEMBER_NO = r"^[A-Za-z0-9][A-Za-z0-9/-]{0,31}$"
PHONE = re.compile(r"^(\+254|0)[17]\d{8}$")   # Kenyan mobile: 07.., 01.., +2547.., +2541..


def clean_phone(value: str | None) -> str | None:
    if value is None:
        return None
    value = re.sub(r"[\s-]", "", value)
    if not PHONE.match(value):
        raise ValueError("a Kenyan mobile number such as 0712345678 or +254712345678")
    return value


def not_blank(value: str | None) -> str | None:
    if value is not None and not value.strip():
        raise ValueError("must not be blank")
    return value and value.strip()


class MemberCreate(BaseModel):
    """No national ID number: not collected (Kenya Data Protection Act 2019)."""
    model_config = ConfigDict(extra="forbid")
    member_no: str = Field(pattern=MEMBER_NO)
    full_name: str = Field(min_length=1, max_length=200)
    phone: str | None = None
    joined_on: date = Field(description="Membership start date")

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        return clean_phone(v)

    @field_validator("full_name")
    @classmethod
    def _name(cls, v: str | None) -> str | None:
        return not_blank(v)

    @field_validator("joined_on")
    @classmethod
    def _past(cls, v: date | None) -> date | None:
        if v is not None and v > date.today():
            raise ValueError("cannot be in the future")
        return v


class MemberUpdate(MemberCreate):
    member_no: str | None = Field(default=None, pattern=MEMBER_NO)
    full_name: str | None = Field(default=None, min_length=1, max_length=200)
    joined_on: date | None = None


class MemberOut(ORM):
    id: int
    member_no: str
    full_name: str
    phone: str | None
    joined_on: date
    user_id: int | None = Field(description="The member's own login, if linked")
    created_at: datetime


class ApplicationCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    member_id: int
    amount_requested_kes: int = Field(gt=0, le=100_000_000)
    purpose: str = Field(min_length=1, max_length=500)
    term_months: int = Field(ge=1, le=120)
    sacco_savings_kes: int = Field(ge=0, le=1_000_000_000, description="From the SACCO's records")
    interview_id: int | None = None

    @field_validator("purpose")
    @classmethod
    def _purpose(cls, v: str) -> str:
        return not_blank(v)


class LinkInterview(BaseModel):
    interview_id: int


class InterviewBrief(BaseModel):
    id: int
    status: InterviewStatus
    question_set: QuestionSet
    language: Language
    mode: Mode
    created_at: datetime


class TimelineEntry(BaseModel):
    status: ApplicationStatus
    label: str
    at: datetime


class GuarantorIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str = Field(min_length=1, max_length=200)
    member_no: str = Field(pattern=MEMBER_NO)
    phone: str
    relationship: str = Field(min_length=1, max_length=60)
    amount_guaranteed_kes: int = Field(gt=0, le=100_000_000)

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        return clean_phone(v)

    @field_validator("full_name", "relationship")
    @classmethod
    def _text(cls, v: str) -> str:
        return not_blank(v)


class GuarantorSubmit(BaseModel):
    guarantors: list[GuarantorIn] = Field(min_length=1, max_length=10)


class GuarantorOut(BaseModel):
    """Staff view."""
    id: int
    full_name: str
    member_no: str
    phone: str
    relationship: str
    amount_guaranteed_kes: int
    status: GuarantorStatus
    submitted_at: datetime
    verified_by: str | None = Field(description="Username of the officer who verified or rejected it")
    verified_at: datetime | None


class GuarantorReview(BaseModel):
    reason: str | None = Field(default=None, max_length=500, description="Kept in the audit log")


class ApplicationSummary(BaseModel):
    id: int
    member_id: int
    member_no: str
    member_name: str
    amount_requested_kes: int
    term_months: int
    status: ApplicationStatus
    interview_id: int | None
    risk_class: str | None
    outcome: Outcome | None
    created_at: datetime
    updated_at: datetime


class ApplicationDetail(ApplicationSummary):
    purpose: str
    sacco_savings_kes: int
    created_by: str
    member: MemberOut
    interview: InterviewBrief | None
    assessment: AssessmentOut | None
    decision: DecisionOut | None
    comparator: Comparator | None = Field(description="Set once the interview is assessed")
    guarantors: list[GuarantorOut]
    timeline: list[TimelineEntry]


# --- A member's own view: no probabilities, feature names or officer notes ------

class MemberGuarantorOut(BaseModel):
    full_name: str
    member_no: str
    phone: str
    relationship: str
    amount_guaranteed_kes: int
    status: GuarantorStatus
    submitted_at: datetime


class MyApplicationSummary(BaseModel):
    id: int
    amount_requested_kes: int
    purpose: str
    term_months: int
    status: ApplicationStatus
    status_label: str
    created_at: datetime
    updated_at: datetime


class MyApplication(MyApplicationSummary):
    timeline: list[TimelineEntry]
    outcome: Outcome | None
    approved_amount_kes: int | None
    guarantors_required: int | None
    guarantors_still_needed: int = Field(description="How many more to submit now; 0 unless status "
                                                     "is guarantor_required")
    member_message: str | None
    reasons: list[str] = Field(description="Up to three plain-language reasons, once decided")
    guarantors: list[MemberGuarantorOut]


# --- Administration -------------------------------------------------------------

USERNAME = r"^[A-Za-z0-9._@-]{3,64}$"
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class UserOut(ORM):
    id: int
    username: str
    role: Role
    email: str | None
    is_active: bool
    created_at: datetime
    member_id: int | None = None
    member_no: str | None = None


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    username: str = Field(pattern=USERNAME)
    password: str = Field(min_length=10, max_length=1024)
    role: Role = "officer"
    email: str | None = Field(default=None, max_length=254)
    member_id: int | None = Field(default=None, description="Members only: link the login to a member")


class PasswordReset(BaseModel):
    password: str = Field(min_length=10, max_length=1024)


class RoleChange(BaseModel):
    role: Role


class EmailLink(BaseModel):
    email: str | None = Field(max_length=254, description="null unlinks")


class MemberLink(BaseModel):
    member_id: int | None = Field(description="null unlinks")


class AuditOut(BaseModel):
    id: int
    actor_user_id: int | None
    actor: str | None = Field(description="Username of the actor; null for shell scripts")
    action: str
    entity: str
    entity_id: int | None
    details: dict
    created_at: datetime
