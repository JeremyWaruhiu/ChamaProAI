"""Request and response bodies."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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


class Question(BaseModel):
    id: str
    version: QuestionSet
    topic: str
    order: int = Field(description="Position in its set; a response's sentence_no")
    text_en: str
    text_kik: str = Field(description="Empty until a native speaker supplies it")
    features: list[str] = Field(description="Classifier features the question is asked for")


DecisionValue = Literal["approve", "decline", "refer"]


class DecisionCreate(BaseModel):
    decision: DecisionValue
    note: str | None = Field(default=None, max_length=2000)


class DecisionOut(ORM):
    decision: DecisionValue
    note: str | None
    decided_by: str | None = Field(default=None, description="Username; null before sign-in existed")
    created_at: datetime


Role = Literal["officer", "admin"]


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
