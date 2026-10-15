"""Request and response bodies."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ResponseStatus = Literal["queued", "transcribed", "failed"]
InterviewStatus = Literal["open", "assessed"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class Error(BaseModel):
    detail: str


class InterviewCreate(BaseModel):
    applicant_name: str | None = Field(default=None, max_length=200)


class InterviewCreated(BaseModel):
    id: int
    status: InterviewStatus


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
    extraction_completeness: float
    features_populated: int
    features_total: int
    features_not_extractable: list[str]
    extraction_model: str
    model_file: str
    model_sha256: str
    created_at: datetime


class Applicant(ORM):
    id: int
    name: str | None


class Counts(BaseModel):
    queued: int = 0
    transcribed: int = 0
    failed: int = 0


class InterviewState(ORM):
    id: int
    status: InterviewStatus
    created_at: datetime
    applicant: Applicant
    counts: Counts
    responses: list[ResponseOut]
    assessment: AssessmentOut | None


class Health(BaseModel):
    status: Literal["ok", "degraded"]
    classifier_present: bool
    api_key_configured: bool
    asr_model: str
    asr_language: str
    asr_loaded: bool
    extraction_model: str
    classifier: dict | None = Field(description="classifier_meta.json, if present")
