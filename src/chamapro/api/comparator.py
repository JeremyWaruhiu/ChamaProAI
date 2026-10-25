"""The SACCO's own lending rule (Chapter 5), set beside the model:

    maximum borrowable = SACCO savings x 3
    at least 2 guarantors
    at least 6 months' membership (from joined_on to the application date)

Computed live from the application, its guarantors and the stored
assessment; nothing here is written to the immutable assessment.

Agreement compares each condition, and the rule as a whole, with the model's
recommendation (Low -> approve, Medium -> refer, High -> decline): a passed
condition agrees with approve, a failed one with decline. Medium is a referral,
neither for nor against, so it is "undetermined". Guarantors cannot exist at
assessment time, so the guarantor condition is "pending" until enough are
submitted, and the rule's recommendation is then "approve_with_guarantors"
when everything else passes, which leans the same way as approve.
"""
from __future__ import annotations

from datetime import date, timedelta, timezone

from . import schemas as s
from .db import LoanApplication

SAVINGS_MULTIPLIER = 3
MIN_GUARANTORS = 2
MIN_TENURE_MONTHS = 6
RULE = (f"SACCO rule (Chapter 5): borrow up to {SAVINGS_MULTIPLIER} x savings, at least "
        f"{MIN_GUARANTORS} guarantors, at least {MIN_TENURE_MONTHS} months' membership")
# Membership is counted to the application's date in Kenya (UTC+3, no daylight saving).
EAT = timezone(timedelta(hours=3))
# The officer decision each model risk class recommends (RISK_MEANING in the dashboard).
RECOMMENDED_DECISION = {"Low": "approve", "Medium": "refer", "High": "decline"}


def months_between(start: date, end: date) -> int:
    """Whole months from start to end; 0 if end is before start."""
    months = (end.year - start.year) * 12 + end.month - start.month - (end.day < start.day)
    return max(months, 0)


def agreement(result: str, model: str | None) -> str:
    if result == "pending":
        return "pending"
    if model not in ("approve", "decline"):
        return "undetermined"
    return "agree" if (result == "pass") == (model == "approve") else "diverge"


def guarantor_result(statuses: list[str]) -> tuple[str, int, str]:
    verified = statuses.count("verified")
    pending = statuses.count("pending")
    if verified >= MIN_GUARANTORS:
        return "pass", verified, f"{verified} guarantor(s) verified"
    if not statuses:
        return "pending", 0, "no guarantors submitted yet"
    if verified + pending >= MIN_GUARANTORS:
        return "pending", verified, f"{verified} verified, {pending} awaiting verification"
    return "fail", verified, (f"{verified} verified of {MIN_GUARANTORS} needed; "
                              f"{statuses.count('rejected')} rejected")


def evaluate(app: LoanApplication, risk_class: str | None) -> s.Comparator:
    model = RECOMMENDED_DECISION.get(risk_class or "")
    ceiling = app.sacco_savings_kes * SAVINGS_MULTIPLIER
    tenure = months_between(app.member.joined_on, app.created_at.astimezone(EAT).date())
    g_result, verified, g_detail = guarantor_result([g.status for g in app.guarantors])

    raw = [
        ("savings_multiple", f"Amount requested is at most {SAVINGS_MULTIPLIER} x SACCO savings",
         "pass" if app.amount_requested_kes <= ceiling else "fail",
         f"KSh {app.amount_requested_kes:,} requested; maximum KSh {ceiling:,} "
         f"(savings KSh {app.sacco_savings_kes:,})"),
        ("guarantors", f"At least {MIN_GUARANTORS} guarantors", g_result, g_detail),
        ("tenure", f"At least {MIN_TENURE_MONTHS} months' membership",
         "pass" if tenure >= MIN_TENURE_MONTHS else "fail",
         f"{tenure} month(s) from joining ({app.member.joined_on.isoformat()}) to the application"),
    ]
    conditions = [s.RuleCondition(name=n, label=label, result=r, detail=d,
                                  agreement=agreement(r, model))
                  for n, label, r, d in raw]
    results = [c.result for c in conditions]
    overall = "fail" if "fail" in results else "pending" if "pending" in results else "pass"
    recommendation = {"pass": "approve", "fail": "decline",
                      "pending": "approve_with_guarantors"}[overall]
    return s.Comparator(
        rule=RULE, max_borrowable_kes=ceiling, amount_requested_kes=app.amount_requested_kes,
        tenure_months=tenure, verified_guarantors=verified, conditions=conditions,
        result=overall, rule_recommendation=recommendation, model_recommendation=model,
        agreement=agreement("fail" if overall == "fail" else "pass", model),
        mode=app.interview.mode if app.interview else "live")
