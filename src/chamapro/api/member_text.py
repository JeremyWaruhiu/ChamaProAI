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
    "offered": "A smaller loan is on offer: waiting for your answer",
    "reversed": "Payout reversed",
}


# A plain-language sentence for a practice result. It follows the model's class,
# as a result must, but never names it: no class, score or probability is shown.
PRACTICE_RESULT = {
    "Low": "From these practice answers, a loan application like this one looks likely to go well.",
    "Medium": "From these practice answers, a loan officer would probably want to look more closely "
              "at an application like this one.",
    "High": "From these practice answers, an application like this one would probably need more "
            "support, such as savings or guarantors, before it could be approved.",
}
PRACTICE_NOTE = " This is practice only: it is not a loan decision and does not change your application."


def practice_result(risk_class: str) -> str:
    return PRACTICE_RESULT.get(risk_class, "Your practice answers have been looked at.") + PRACTICE_NOTE


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
        "not_now": "We cannot take this loan further just now. Please speak to your loan officer "
                   "about what could help.",
    }[outcome]


# Why an automatic decision came out as it did. Fixed templates, one per reason code
# in decisions.settle, so nothing a member reads is generated. Keyed by language, for
# Kikuyu in the next phase. A referral for risk and one for a Medium score with nothing
# left to ask share one sentence: the wording must not give the class away.
BOOK = " You can book a time to see a loan officer."
DECISION_REASONS = {"en": {
    "approve": "You can have KSh {amount:,} now. It goes to your transactional account, and you will repay "
               "KSh {instalment:,} a month for {term} months.",
    "reduced_rule": "We can offer KSh {amount:,} rather than the KSh {requested:,} you asked for. That is the most "
                    "your deposits allow. If you accept, you will repay KSh {instalment:,} a month for {term} months.",
    "reduced_affordability": "We can offer KSh {amount:,} rather than the KSh {requested:,} you asked for. That is the "
                             "most your income allows over this time. If you accept, you will repay "
                             "KSh {instalment:,} a month for {term} months.",
    "clarify": "We need a little more from you before we can answer.",
    "self_declared": "Your savings are not on the SACCO's records yet, so a loan officer needs to look at this "
                     "application with you." + BOOK,
    "officer_review": "A loan officer will look at this application with you." + BOOK,
    "income_unconfirmed": "Your income needs officer confirmation: it is well above the figure on your record, "
                          "or we have no figure to compare it with." + BOOK,
    "question_cap": "We have asked as many questions as we can here, so a loan officer will look at this "
                    "application with you." + BOOK,
    "not_understood": "We could not be sure of one of your answers, so a loan officer will look at this "
                      "application with you." + BOOK,
    "offer_declined": "You would rather not take the amount we could offer, so a loan officer will look at this "
                      "application with you." + BOOK,
    "review_requested": "You asked for a loan officer to review this, so one will." + BOOK,
    "arrears": "You have a loan payment outstanding, so a loan officer needs to look at this application with you." + BOOK,
    "details_missing": "We do not have everything we need to answer this ourselves, so a loan officer will look at "
                       "it with you." + BOOK,
    "offer_too_small": "What we could offer is less than half of what you asked for, so a loan officer will look at "
                       "this application with you." + BOOK,
    "above_limit": "Loans above KSh {limit:,} are looked at by a loan officer." + BOOK,
    "guarantors_short": "Your guarantors do not yet cover this loan, so a loan officer will look at it with you." + BOOK,
    "named_guarantor": "The guarantor you named has not pledged to back you yet, so a loan officer needs to confirm "
                       "them with you." + BOOK,
    "membership": "You can apply once you have been a member for {min_months} months. You have "
                  "{months_left} more {months_word} to go.",
    "no_guarantors": "You need at least {min_guarantors} members who have pledged to guarantee you before you can "
                     "apply. Please ask them to speak to a loan officer.",
}}
QUESTION_REASONS = {"en": {
    "C1": "We need to know over how many months you would like to repay.",
    "C2": "We need your current monthly income to work out this loan.",
    "C3": "This loan is close to what your income allows. What you expect it to bring in each month would count.",
    "C4": "We need to know whether you are borrowing from a chama now, and what you pay each month.",
    "C5": "Your guarantors do not yet cover this loan. Another member could guarantee you.",
    "C6": "This is more than both your deposits and your income allow. You could accept a smaller amount.",
}}
QUESTION_SETS_FEATURE = {
    "C1": ["term_months"], "C2": ["monthly_income_kes"], "C3": ["expected_monthly_return_kes"],
    "C4": ["chama_loan_use", "chama_instalment_kes"], "C5": ["extra_guarantor"], "C6": ["accepted_amount_kes"],
}


def decision_reason(code: str, values: dict, language: str = "en") -> str:
    left = values.get("months_left") or 0
    return DECISION_REASONS[language][code].format(**values, months_word="month" if left == 1 else "months")


def question_reason(question: str, language: str = "en") -> str:
    return QUESTION_REASONS[language][question]


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


def reasons(risk_class: str, contributions: list[dict] | str, n: int = 3, verb: str = "counted") -> list[str]:
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
        out.append(f"{what} {verb} in your favour." if in_favour(risk_class, c["shap"])
                   else f"{what} {verb} against your application.")
        if len(out) == n:
            break
    return out


def _kes(n: float | None) -> str:
    return f"KSh {int(n):,}"


def _check_sentence(check: str, passed: bool | None, v: dict) -> str | None:
    """One check in the member's own figures. Nothing about a guarantor beyond how many,
    and the risk check in the same words for Medium and High: a referral must not give the
    class away. None for a check this version does not know: left out, never shown raw."""
    if check == "deposits_on_record":
        return f"Your deposits on record are {_kes(v['deposits_kes'])}." if passed else \
            f"Your savings of {_kes(v['declared_savings_kes'] or 0)} are not on the SACCO's records yet."
    if check == "membership":
        return f"You have been a member for {v['months']} months. The minimum is {v['minimum']}."
    if check == "savings_multiple":
        return f"{_kes(v['amount_kes'])} is {'within' if passed else 'more than'} what your deposits allow, " \
               f"{_kes(v['maximum_kes'])}."
    if check == "guarantors":
        return f"You have {v['usable']} who can guarantee you. At least {v['minimum']} are needed."
    if check == "guarantor_capacity":
        return f"{_kes(v['own_free_kes'])} of your own deposits is free. With your guarantors, that " \
               f"{'covers' if passed else 'does not yet cover'} this loan."
    if check == "affordability":
        if passed is None:
            return "We could not yet work out what you can afford."
        return f"The instalment of {_kes(v['instalment_kes'])} a month is {'within' if passed else 'more than'} " \
               f"the {_kes(v['limit_kes'])} a month your income allows."
    if check == "auto_limit":
        return f"{_kes(v['amount_kes'])} is within the {_kes(v['limit_kes'])} we can decide here." if passed else \
            f"Loans above {_kes(v['limit_kes'])} are looked at by a loan officer."
    if check == "income_increase":
        if not v["stated"]:
            return "We used the income on your record." if v["monthly_income_kes"] is not None else \
                "There is no income on your record."
        return f"The income you gave, {_kes(v['monthly_income_kes'])}, " + \
            ("is close enough to your record to use." if passed else "needs an officer to confirm it.")
    if check == "risk":
        return "Your details fit what we can decide here." if passed else "A loan officer should look at your details with you."
    if check == "no_arrears":
        return "You have no loan payment outstanding." if passed else "You have a loan payment outstanding."
    return None


def plain_explain(full: dict) -> dict:
    """All a member gets of how a decision was worked out, built field by field from the
    turn's record: the reason, each check passed or not in their own figures, and the three
    largest drivers as sentences. No class, probability, SHAP value or other member's figure."""
    checks = []
    for c in (full.get("trace") or full).get("checks") or []:
        text = _check_sentence(c["check"], c["passed"], c["values"])
        if text is not None:
            checks.append({"passed": c["passed"], "text": text})
    return {"reason": full["reason"], "checks": checks,
            "drivers": reasons(full["risk_class"], full.get("contributions") or [], verb="counts")}
