"""Request and response bodies."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .db import normalise_phone

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
    display_name: str | None = Field(default=None, description="Shown beside the role; null shows the username")


class ProfileMember(BaseModel):
    member_no: str
    full_name: str


class Profile(BaseModel):
    """The signed-in user's own account (GET /api/auth/profile)."""
    username: str
    role: Role
    display_name: str | None = None
    email: str | None = Field(description="The Google account linked for sign-in, if any")
    google_sign_in_available: bool = Field(description="False when the server has no Google client ID")
    member: ProfileMember | None = Field(description="Member logins: the member record linked")
    signed_in_with: str | None = Field(description="password | google, for this session")
    active_sessions: int = Field(description="Signed-in browsers, this one included")
    created_at: datetime


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=1024)
    new_password: str = Field(min_length=10, max_length=1024)


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
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE = re.compile(r"^(\+254|0)[17]\d{8}$")   # Kenyan mobile: 07.., 01.., +2547.., +2541..


def clean_phone(value: str | None) -> str | None:
    if value is None:
        return None
    value = re.sub(r"[\s-]", "", value)
    if not PHONE.match(value):
        raise ValueError("a Kenyan mobile number such as 0712345678 or +254712345678")
    return value


def clean_contact_email(value: str | None) -> str | None:
    """A member's contact address, lower-case; blank is none."""
    value = (value or "").strip().lower()
    if value and not EMAIL.match(value):
        raise ValueError("not an email address")
    return value or None


def clean_member_phone(value: str | None) -> str | None:
    """A member's number: accepts 07.., 01.., +2547.., +2541.., 2547.. and 2541..,
    stored as +254XXXXXXXXX. Blank is none."""
    return None if value is None else normalise_phone(value)


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
        return clean_member_phone(v)

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


SavingsStatus = Literal["none", "self_declared", "verified"]


class MemberOut(ORM):
    id: int
    member_no: str
    full_name: str
    phone: str | None
    joined_on: date
    user_id: int | None = Field(description="The member's own login, if linked")
    created_at: datetime
    email: str | None = None
    savings_kes: int | None = None
    savings_verified_by: str | None = None
    savings_verified_at: datetime | None = None
    self_signed_up: bool = False


class MemberVerify(BaseModel):
    """Staff verify a member's savings, correcting the figure or the membership
    start date if the SACCO's records differ."""
    model_config = ConfigDict(extra="forbid")
    savings_kes: int | None = Field(default=None, ge=0, le=1_000_000_000,
                                    description="Omit to verify the figure already there")
    joined_on: date | None = None

    @field_validator("joined_on")
    @classmethod
    def _past(cls, v: date | None) -> date | None:
        if v is not None and v > date.today():
            raise ValueError("cannot be in the future")
        return v


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
    mode: Mode | None = Field(default=None, description="Its interview's mode; null before it has one")
    risk_class: str | None
    outcome: Outcome | None
    created_at: datetime
    updated_at: datetime


BookingStatus = Literal["requested", "confirmed", "started", "cancelled"]


class BookingOut(BaseModel):
    """Staff view of an interview booking. Times are UTC; the dashboard shows Nairobi time."""
    id: int
    application_id: int
    member_id: int
    member_no: str
    member_name: str
    member_phone: str | None
    amount_requested_kes: int
    purpose: str
    term_months: int
    starts_at: datetime
    language: Language
    status: BookingStatus
    interview_id: int | None


class PracticeBrief(BaseModel):
    """Staff view of a member's practice run; opens the full assessment."""
    interview_id: int
    language: Language
    status: InterviewStatus
    answered: int
    risk_class: str | None
    created_at: datetime
    submitted_at: datetime | None


class ApplicationDetail(ApplicationSummary):
    purpose: str
    sacco_savings_kes: int
    savings_self_declared: bool = Field(default=False, description="The figure is what the member "
                                        "declared; an officer has not verified it")
    booking: BookingOut | None = Field(default=None, description="The booked interview, if any")
    practice_interviews: list[PracticeBrief] = Field(default_factory=list)
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
    mode: Mode = Field(default="live", description="practice: a training record, no real loan")
    created_at: datetime
    updated_at: datetime


class MyBooking(BaseModel):
    id: int
    application_id: int
    starts_at: datetime
    language: Language
    status: BookingStatus


class HistoryEntry(BaseModel):
    label: str
    at: datetime


class MyPracticeBrief(BaseModel):
    id: int
    language: Language
    status: InterviewStatus
    mode: Literal["practice"] = "practice"
    answered: int
    questions_total: int
    created_at: datetime


class MyApplication(MyApplicationSummary):
    timeline: list[TimelineEntry]
    history: list[HistoryEntry] = Field(default_factory=list, description="Status changes and "
                                        "interview bookings, oldest first, in words")
    booking: MyBooking | None = None
    practice: list[MyPracticeBrief] = Field(default_factory=list)
    outcome: Outcome | None
    approved_amount_kes: int | None
    guarantors_required: int | None
    guarantors_still_needed: int = Field(description="How many more to submit now; 0 unless status "
                                                     "is guarantor_required")
    member_message: str | None
    reasons: list[str] = Field(description="Up to three plain-language reasons, once decided")
    guarantors: list[MemberGuarantorOut]


SlotTime = Literal["08:30", "09:00", "09:30", "10:00", "10:30", "11:00", "11:30", "12:00",
                   "12:30", "13:00", "13:30", "14:00", "14:30", "15:00", "15:30", "16:00"]
PURPOSES = ("School fees", "Business stock or capital", "Farm inputs", "Dairy or livestock",
            "Home improvement", "Medical costs", "Buying land or an asset", "Other")
Purpose = Literal["School fees", "Business stock or capital", "Farm inputs", "Dairy or livestock",
                  "Home improvement", "Medical costs", "Buying land or an asset", "Other"]


class Signup(BaseModel):
    model_config = ConfigDict(extra="forbid")
    full_name: str = Field(min_length=1, max_length=200)
    phone: str = Field(max_length=32)
    email: str | None = Field(default=None, max_length=254)
    password: str = Field(min_length=10, max_length=1024, description="Same policy as create_user.py")
    password_confirm: str = Field(max_length=1024)
    invite_code: str = Field(min_length=1, max_length=200)
    consent: bool = Field(description="Must be true")
    consent_version: str = Field(max_length=32, description="The version of the text the person read")

    @field_validator("full_name")
    @classmethod
    def _name(cls, v: str) -> str:
        return " ".join(not_blank(v).split())

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str) -> str:
        phone = clean_member_phone(v)
        if phone is None:
            raise ValueError("a phone number is required")
        return phone

    @field_validator("email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        return clean_contact_email(v)

    @model_validator(mode="after")
    def _matches(self):
        if self.password != self.password_confirm:
            raise ValueError("password_confirm: the passwords do not match")
        if not self.consent:
            raise ValueError("consent: you must agree to take part")
        return self


class SignupResult(Me):
    member_no: str = Field(description="The generated member number")


class SignupInfo(BaseModel):
    """What the public sign-up page needs before anyone is signed in."""
    enabled: bool = Field(description="False when PILOT_INVITE_CODE is not set")
    consent_version: str
    consent_text: list[str]


class MyMember(BaseModel):
    """The signed-in member's own record. member_no, full_name, joined_on and a
    verified savings figure can be changed only by staff."""
    member_no: str
    full_name: str
    phone: str | None
    email: str | None
    savings_kes: int | None
    savings_status: SavingsStatus
    savings_label: str
    savings_limit_kes: int | None = Field(description="SACCO rule: savings x the multiplier")
    joined_on: date
    tenure_months: int
    age: int | None
    sex: Sex | None
    education: int | None
    marital_status: MaritalStatus | None
    applicant_complete: bool
    consent_current: bool = Field(description="Has agreed to the current consent text")


class MyMemberUpdate(BaseModel):
    """Everything else on the record is read-only here: any other field is refused."""
    model_config = ConfigDict(extra="forbid")
    phone: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=254)
    savings_kes: int | None = Field(default=None, ge=0, le=1_000_000_000)
    applicant: ApplicantForm | None = None

    @field_validator("phone")
    @classmethod
    def _phone(cls, v: str | None) -> str | None:
        return clean_member_phone(v)

    @field_validator("email")
    @classmethod
    def _email(cls, v: str | None) -> str | None:
        return clean_contact_email(v)


class ApplyOptions(ApplicantFormOptions):
    purposes: list[str]
    savings_multiplier: int
    min_tenure_months: int
    max_term_months: int


class Slot(BaseModel):
    """An interview slot chosen by date and time at the branch (Nairobi)."""
    date: date
    time: SlotTime


class BookingRequest(Slot):
    model_config = ConfigDict(extra="forbid")
    language: Language


class MyApplicationCreate(BookingRequest):
    """What the member types. Name, member number, phone, savings and tenure come
    from their record; sending any of them is refused."""
    amount_requested_kes: int = Field(gt=0, le=100_000_000)
    purpose: Purpose
    purpose_other: str | None = Field(default=None, max_length=500)
    term_months: int = Field(ge=1, le=120)
    # Only when the record has none yet; they are then saved to it.
    declared_savings_kes: int | None = Field(default=None, ge=0, le=1_000_000_000)
    applicant: ApplicantForm | None = None

    @model_validator(mode="after")
    def _other(self):
        if self.purpose == "Other" and not (self.purpose_other or "").strip():
            raise ValueError("purpose_other: say what the loan is for")
        return self

    @property
    def purpose_text(self) -> str:
        return self.purpose_other.strip() if self.purpose == "Other" else self.purpose


class Holiday(BaseModel):
    date: date
    name: str


class BookingCalendar(BaseModel):
    """The rules behind the date picker; the API enforces the same ones."""
    today: date = Field(description="Today in Nairobi")
    last_date: date
    holidays: list[Holiday]
    times: list[str]
    timezone: str


class SlotOut(BaseModel):
    time: str
    starts_at: datetime
    available: bool
    reason: Literal["booked", "past"] | None


class DaySlots(BaseModel):
    date: date
    blocked_reason: str | None = Field(description="Why the whole day cannot be booked")
    slots: list[SlotOut]


class EventIn(BaseModel):
    """Date and time are at the branch (Nairobi); stored in UTC."""
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=200)
    event_type: Literal["agm", "member_meeting", "training", "loan_deadline", "other"]
    date: date
    time: str = Field(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")
    location: str | None = Field(default=None, max_length=200)
    online_link: str | None = Field(default=None, max_length=500)
    description: str | None = Field(default=None, max_length=2000)

    @field_validator("title")
    @classmethod
    def _title(cls, v: str) -> str:
        return not_blank(v)

    @field_validator("location", "description")
    @classmethod
    def _optional(cls, v: str | None) -> str | None:
        return (v or "").strip() or None

    @field_validator("online_link")
    @classmethod
    def _link(cls, v: str | None) -> str | None:
        v = (v or "").strip()
        # Rendered as a link on members' phones: http(s) only, never javascript:.
        if v and not re.fullmatch(r"https?://\S+", v, flags=re.I):
            raise ValueError("must be a full http:// or https:// address")
        return v or None


class EventOut(ORM):
    id: int
    title: str
    event_type: str
    starts_at: datetime
    location: str | None
    online_link: str | None
    description: str | None


class MemberHome(BaseModel):
    events: list[EventOut]
    next_interview: MyBooking | None
    applications: list[MyApplicationSummary]


class StartPractice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    language: Language


class ConsentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    consent: bool
    consent_version: str = Field(max_length=32)


class MyQuestion(BaseModel):
    """A question without the classifier features it is asked for."""
    order: int
    topic: str
    text_en: str
    text_kik: str


class MyResponse(BaseModel):
    """An answer as the member sees it: no translation, no extraction signals,
    no engine errors."""
    id: int
    sentence_no: int
    source: Source
    status: ResponseStatus
    transcript: str | None
    edited: bool
    duration_s: int | None


class MyTranscriptEdit(BaseModel):
    transcript: str = Field(min_length=1, max_length=5000)


class PracticeResult(BaseModel):
    message: str = Field(description="The result in plain language")
    reasons: list[str] = Field(description="Up to three, in words")


class PracticeLimits(BaseModel):
    remaining_today: int
    allowed_per_day: int
    pilot_full_today: bool


class MyPractice(BaseModel):
    id: int
    application_id: int
    language: Language
    mode: Literal["practice"] = "practice"
    status: InterviewStatus
    created_at: datetime
    questions: list[MyQuestion]
    responses: list[MyResponse]
    result: PracticeResult | None
    sus_answered: bool
    limits: PracticeLimits


class SusIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answers: list[int] = Field(min_length=10, max_length=10, description="Ten answers, 1-5, in order")
    comment: str | None = Field(default=None, max_length=2000)

    @field_validator("answers")
    @classmethod
    def _scale(cls, v: list[int]) -> list[int]:
        if any(a < 1 or a > 5 for a in v):
            raise ValueError("each answer is from 1 to 5")
        return v


class MemberAnswers(BaseModel):
    member_no: str
    answers: int
    interviews: int


class PilotComment(BaseModel):
    member_no: str
    comment: str
    score: float
    created_at: datetime


class PilotStats(BaseModel):
    volunteers: int
    practice_by_language: dict[str, int]
    completed_assessments: int
    answers_total: int
    answers_per_member: list[MemberAnswers]
    sus_mean: float | None = Field(description="Null until there is a response")
    sus_n: int
    sus_members: int = Field(description="How many members those responses came from")
    comments: list[PilotComment]
    signup_open: bool
    per_member_cap: int
    daily_cap: int
    used_today: int


# --- Administration -------------------------------------------------------------

USERNAME = r"^[A-Za-z0-9._@-]{3,64}$"


class UserOut(ORM):
    id: int
    username: str
    display_name: str | None = None
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
    display_name: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=254)
    member_id: int | None = Field(default=None, description="Members only: link the login to a member")


class PasswordReset(BaseModel):
    password: str = Field(min_length=10, max_length=1024)


class RoleChange(BaseModel):
    role: Role


class DisplayNameChange(BaseModel):
    display_name: str | None = Field(max_length=120, description="null or blank shows the username")


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
