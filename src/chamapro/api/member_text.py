"""Plain language for members: status labels, default decision messages and
the reasons drawn from the assessment's top SHAP contributions.

A member never sees a probability, a risk class, a feature name or an
officer's note. Reasons say what counted for or against them, in words.

Direction: SHAP values are stored for the predicted class. For Low, a
positive value pushed towards Low (in the member's favour). For Medium and
High, a positive value pushed towards that higher-risk class (against), and a
negative one away from it (in favour). For Medium this is approximate: away
from Medium may be towards Low or High; the larger share is towards Low.

Age, sex and marital status are left out of the reasons: they come from the
applicant form, the member cannot act on them, and naming one as counting
against someone reads as discrimination whatever the model's arithmetic.
"""
from __future__ import annotations

PERSONAL = {"age", "is_female", "marital_married", "marital_single", "marital_widowed",
            "marital_divorced"}

STATUS_LABEL = {
    "draft": "Application started",
    "interview_pending": "Interview arranged",
    "interview_complete": "Interview completed",
    "assessed": "Being reviewed by a loan officer",
    "decided": "Passed to the loan committee",
    "guarantor_required": "Guarantors needed",
    "guarantor_submitted": "Guarantors being checked",
    "approved": "Approved",
    "declined": "Not approved",
}


def default_message(outcome: str, approved: int | None, guarantors: int | None) -> str:
    """Shown when the officer left member_message blank."""
    amount = f"KSh {approved:,}" if approved else "your loan"
    return {
        "approve": f"Good news: {amount} has been approved.",
        "approve_reduced": f"Your loan has been approved for {amount}, which is less than you "
                           "asked for. Your loan officer can explain why.",
        "approve_with_guarantor": f"Your loan can be approved once {guarantors or 2} guarantor(s) "
                                  "have been confirmed. Please add your guarantors.",
        "refer": "Your application has been passed to the loan committee for a closer look. "
                 "We will contact you.",
        "decline": "We are not able to approve this loan at this time. Please speak to your "
                   "loan officer about the reasons and what could help next time.",
    }[outcome]


# feature -> (what it is when present / true, when absent / false); one
# phrase for numeric features. Phrases start a sentence.
INCOME_SOURCES = ["farming", "employment", "casual work", "your own business",
                  "social transfers", "renting out property", "investments", "a pension",
                  "money sent by family", "other sources"]
ASSETS = ["land or buildings", "livestock", "jewellery", "digital assets", "trees"]
PURCHASES = ["land", "a new house", "building materials", "business equipment",
             "farm equipment", "livestock"]
LOAN_USE = {0: "Not having borrowed from a {0} before", 1: "Your past borrowing from a {0}",
            2: "Your current {0} loan"}

PHRASES: dict[str, tuple[str, str] | str] = {
    "household_size": "The size of your household",
    "children": "The number of children in your household",
    "children_under5": "The number of young children at home",
    "children_in_school": "The number of children in school",
    "log_monthly_income": "Your monthly household income",
    "log_agri_income": "Your farm income",
    "income_missing": ("Not giving a monthly income figure", "Giving a monthly income figure"),
    "education": "Your education",
    "B3A__1": ("Your regular farm income", "Not having farm income"),
    "B3A__11": ("Having no regular source of income", "Having a source of income"),
    "E3B__3": ("Having lost money as a SACCO guarantor before",
               "Never having lost money as a SACCO guarantor"),
    "E3B__7": ("Having lost money as a chama guarantor before",
               "Never having lost money as a chama guarantor"),
}
for _i, _src in enumerate(INCOME_SOURCES[1:], 2):
    PHRASES[f"B3A__{_i}"] = (f"Your income from {_src}", f"Not having income from {_src}")
for _i, _a in enumerate(ASSETS, 1):
    PHRASES[f"F1__{_i}"] = (f"Owning {_a}", f"Not owning {_a}")
for _i, _p in enumerate(PURCHASES, 1):
    PHRASES[f"B1L__{_i}"] = (f"Buying {_p} in the last year", f"Not buying {_p} in the last year")


def subject(feature: str, value: float | None) -> str | None:
    """What the feature says about the member, as the start of a sentence."""
    if feature in ("sacco_loan_use", "chama_loan_use"):
        kind = "SACCO" if feature == "sacco_loan_use" else "chama"
        if value is None:
            return f"Not having details of your {kind} borrowing"
        return LOAN_USE.get(round(value), LOAN_USE[1]).format(kind)
    phrase = PHRASES.get(feature)
    if phrase is None:
        return None
    if value is None:
        what = phrase if isinstance(phrase, str) else phrase[0]
        return f"Not having details of {what[0].lower() + what[1:]}"
    if isinstance(phrase, str):
        return phrase
    return phrase[0] if value >= 0.5 else phrase[1]


def in_favour(risk_class: str, shap: float) -> bool:
    return shap > 0 if risk_class == "Low" else shap < 0


def reasons(risk_class: str, contributions: list[dict] | str, n: int = 3) -> list[str]:
    """Up to n sentences from the largest contributions; none if SHAP was unavailable."""
    if not isinstance(contributions, list):
        return []
    out = []
    for c in sorted(contributions, key=lambda c: abs(c.get("shap") or 0), reverse=True):
        if c.get("feature") in PERSONAL or not c.get("shap"):
            continue
        what = subject(c["feature"], c.get("value"))
        if what is None:
            continue
        out.append(f"{what} counted in your favour." if in_favour(risk_class, c["shap"])
                   else f"{what} counted against your application.")
        if len(out) == n:
            break
    return out
