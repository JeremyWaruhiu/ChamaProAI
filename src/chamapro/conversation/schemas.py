"""What each question can extract: one schema per question id, with ranges. What the
language model returns is validated against these; anything else is treated as no answer."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

KES_MAX = 100_000_000
YesNoValue = Literal["yes", "no"]
PURPOSES = Literal["business", "farming", "livestock", "school_fees", "medical", "housing", "household", "transport", "other"]


class Fields(BaseModel):
    model_config = ConfigDict(extra="ignore")


class Corrections(Fields):
    household_size: int | None = Field(default=None, ge=1, le=60)
    children: int | None = Field(default=None, ge=0, le=60)
    monthly_income_kes: int | None = Field(default=None, ge=0, le=KES_MAX)


class YesNo(Fields):
    answer: YesNoValue | None = None
    corrections: Corrections | None = None


class R1(Fields):
    amount_kes: int | None = Field(default=None, gt=0, le=KES_MAX)
    purpose_category: PURPOSES | None = None
    purpose_text: str | None = Field(default=None, max_length=500)


class C1(Fields):
    term_months: int | None = Field(default=None, ge=1, le=120)


class C2(Fields):
    answer: YesNoValue | None = None
    monthly_income_kes: int | None = Field(default=None, ge=0, le=KES_MAX)


class C3(Fields):
    expected_monthly_return_kes: int | None = Field(default=None, ge=0, le=KES_MAX)


class C4(Fields):
    chama_loan_active: bool | None = None
    chama_instalment_kes: int | None = Field(default=None, ge=0, le=KES_MAX)


class C5(Fields):
    full_name: str | None = Field(default=None, max_length=200)
    member_no: str | None = Field(default=None, max_length=32)
    nobody: bool | None = None


class CheckAmount(Fields):
    answer: YesNoValue | None = None
    amount_kes: int | None = Field(default=None, ge=0, le=KES_MAX)


QUESTIONS: dict[str, type[Fields]] = {
    "CONSENT": YesNo, "G2": YesNo, "R1": R1, "C1": C1, "C2": C2, "C2_NEW": C2, "C3": C3, "C4": C4, "C5": C5, "C6": YesNo,
    "CHECK_AMOUNT": CheckAmount, "CONFIRM": YesNo,
}
# The one money figure a question can give, for comparing the model with the parser.
MONEY_FIELD = {"R1": "amount_kes", "C2": "monthly_income_kes", "C2_NEW": "monthly_income_kes",
               "C3": "expected_monthly_return_kes", "C4": "chama_instalment_kes"}


class ModelAnswer(BaseModel):
    english: str = Field(default="", max_length=2000)
    fields: dict = Field(default_factory=dict)
    confidence: float = Field(ge=0, le=1)


def validated(question_id: str, raw: dict) -> tuple[ModelAnswer, dict]:
    """(the envelope, the question's fields). Raises ValidationError if either is wrong."""
    answer = ModelAnswer.model_validate(raw)
    return answer, QUESTIONS[question_id].model_validate(answer.fields).model_dump(exclude_none=True)


__all__ = ["QUESTIONS", "MONEY_FIELD", "ValidationError", "validated"]
