"""The decision engine: evaluate(member, request, overrides) -> Evaluation. It reads
and never writes; committing one is self_service.py's work.

The language model decides nothing here. The classifier scores the person from the
profile; the SACCO rule and an affordability check score the request; and a fixed,
versioned policy (settle) picks the outcome from those facts alone. It is a pure
function of Facts, so a table of cases can test every outcome without a database, and
everything it read is kept in Evaluation.trace for a loan officer or an examiner.

The model can only ever ask for a person to look. High risk is a referral, and "not
now" comes only from a rule the member has not met yet.

A clarification is a question the policy would like answered before it settles. The
answer arrives as an override, which replaces the profile's value for this evaluation
only. A key present in overrides means the question has been asked, and null means the
member gave no answer: so a question is never asked twice, whatever the caller does.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import threading
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from chamapro import config

from . import comparator, ledger, member_text, profiles
from .db import (GuarantorPledge, LoanAccount, Member, MemberProfile, MemberProfileHistory, nairobi_today)
from .pipeline import score_interview

log = logging.getLogger("chamapro.api")

MAX_QUESTIONS = 2
# SHAP contributions kept on each evaluation: the presenter view charts ten.
SHAP_KEPT = 10
OVERRIDE_KEYS = ("term_months", "monthly_income_kes", "expected_monthly_return_kes", "chama_loan_use",
                 "chama_instalment_kes", "extra_guarantor", "accepted_amount_kes", "household_size", "children")
# Answers that replace a profile value the classifier reads.
FEATURE_OVERRIDES = ("monthly_income_kes", "chama_loan_use", "household_size", "children")
# What can clear a Medium score: an answer about the person. A term says nothing about them.
CLEARS_MEDIUM = frozenset({"C2", "C3", "C4"})
INCOME_FEATURES = ("log_monthly_income", "income_missing")
# Words in a purpose that mean the loan earns money. The member's own words decide
# nothing but whether C3 is worth asking, and an answer only ever adds to affordability.
INCOME_GENERATING = ("business", "shop", "stock", "kiosk", "capital", "trade", "dairy", "cow", "goat", "sheep",
                     "livestock", "poultry", "chicken", "pig", "farm", "seed", "fertili", "crop", "greenhouse",
                     "irrigation", "equipment", "machine", "boda", "transport", "rent")


class ClassifierMissing(RuntimeError):
    """No model to score with: nothing can be decided or recorded."""


class BadOverride(ValueError):
    """An override the engine does not take."""


def policy_version() -> str:
    """The base version, with a hash of the thresholds if any differs from its default."""
    values = thresholds()
    if all(values[k] == v for k, v in config.POLICY_DEFAULTS.items()):
        return config.POLICY_BASE_VERSION
    digest = hashlib.sha256(json.dumps(values, sort_keys=True).encode()).hexdigest()[:8]
    return f"{config.POLICY_BASE_VERSION}+{digest}"


def thresholds() -> dict:
    return {"AUTO_APPROVE_LIMIT_KES": config.AUTO_APPROVE_LIMIT_KES,
            "LOAN_INTEREST_MONTHLY": config.LOAN_INTEREST_MONTHLY,
            "AFFORDABILITY_RATIO": config.AFFORDABILITY_RATIO,
            "AFFORDABILITY_NEAR_BAND": config.AFFORDABILITY_NEAR_BAND,
            "PROFILE_STALE_DAYS": config.PROFILE_STALE_DAYS,
            "UNVERIFIED_INCREASE_TOLERANCE": config.UNVERIFIED_INCREASE_TOLERANCE,
            "SAVINGS_MULTIPLIER": comparator.SAVINGS_MULTIPLIER,
            "MIN_GUARANTORS": comparator.MIN_GUARANTORS,
            "MIN_TENURE_MONTHS": comparator.MIN_TENURE_MONTHS}


def income_generating(purpose: str) -> bool:
    text = purpose.lower()
    return any(word in text for word in INCOME_GENERATING)


# --- Guarantors ------------------------------------------------------------------------

@dataclass(frozen=True)
class GuarantorOption:
    member_id: int
    member_no: str
    full_name: str
    phone: str
    free_kes: int
    pledge_id: int | None = None        # None: named in the conversation, has not pledged


def choose_guarantors(options: tuple[GuarantorOption, ...], need_kes: int) -> tuple[GuarantorOption, ...]:
    """Standing pledges first, most capacity first; at least the minimum number,
    then as many more as it takes to cover the need. A guarantor with no free
    capacity is not one."""
    able = sorted((g for g in options if g.free_kes > 0),
                  key=lambda g: (g.pledge_id is None, -g.free_kes, g.member_id))
    chosen = able[:comparator.MIN_GUARANTORS]
    for g in able[comparator.MIN_GUARANTORS:]:
        if sum(c.free_kes for c in chosen) >= need_kes:
            break
        chosen.append(g)
    return tuple(chosen)


def allocate(chosen: tuple[GuarantorOption, ...], need_kes: int) -> list[tuple[GuarantorOption, int]]:
    """What each guarantor holds: the need split evenly, the smallest capacities filled
    first and the rest carried on. Each holds at least KSh 1, even when the member's own
    deposits cover the loan: a guarantors row always holds something, and they are still
    the two names the SACCO rule asks for."""
    left, out = max(need_kes, 0), {}
    for i, g in enumerate(sorted(chosen, key=lambda c: (c.free_kes, c.member_id))):
        share = min(g.free_kes, max(math.ceil(left / (len(chosen) - i)), 1))
        out[g.member_id] = share
        left = max(left - share, 0)
    return [(g, out[g.member_id]) for g in chosen]


# --- The facts, and what follows from them -----------------------------------------------

@dataclass(frozen=True)
class Facts:
    """Everything the policy reads. No database, no model: all of it already decided."""
    requested_kes: int
    purpose: str
    amount_kes: int                     # the request, or the amount accepted under C6
    term_months: int | None
    income_kes: int | None
    deposits_kes: int | None            # None: no deposits entries, so nothing on record
    declared_savings_kes: int           # what the rule reads when deposits_kes is None
    own_free_kes: int                   # own deposits not backing someone else
    months_member: int
    risk_class: str
    contributions: list | str = field(default_factory=list)
    expected_return_kes: int = 0
    loan_instalments_kes: int = 0
    chama_instalment_kes: int = 0
    guarantors: tuple[GuarantorOption, ...] = ()
    any_guarantor: bool = False         # a pledge or a named member, with capacity or not
    income_age_days: int | None = 0     # None: no date, so older than anything
    income_verified: bool = True
    chama_use_known: bool = True
    credit_age_days: int | None = 0
    in_arrears: bool = False
    asked: frozenset[str] = frozenset()         # question ids
    answered: frozenset[str] = frozenset()      # those given a value
    declined: frozenset[str] = frozenset()      # asked, no value
    final: bool = False                         # no more questions: settle on what is here
    outstanding_principal_kes: int = 0          # on the member's active loans
    profile_income_kes: int | None = None
    income_stated: bool = False                 # the income came from the conversation
    refer_reason: str | None = None             # the caller is stopping here: a person decides


@dataclass(frozen=True)
class Worked:
    """The arithmetic, reported whether or not it passes."""
    rule_max_kes: int
    instalment_kes: int | None
    obligations_kes: int
    disposable_kes: int | None
    limit_kes: float | None             # the most a month's instalment may be
    affordable_max_kes: int | None
    offer_kes: int | None               # the lower of the two maximums
    affordability_passes: bool | None
    affordability_near: bool
    capacity_need_kes: int
    chosen: tuple[GuarantorOption, ...]
    capacity_passes: bool

    @property
    def needs_named(self) -> bool:
        return any(g.pledge_id is None for g in self.chosen)


def income_ceiling(profile_income_kes: int | None) -> int | None:
    """The most a member's word carries; None when the profile holds no figure to go by."""
    if profile_income_kes is None:
        return None
    return int(round(profile_income_kes * (1 + config.UNVERIFIED_INCREASE_TOLERANCE), 6))


def income_needs_officer(f: Facts) -> bool:
    """A stated income too far above the profile, or with no figure to compare it with.
    It is still scored and shown; only a person can act on it."""
    if not f.income_stated or f.income_kes is None:
        return False
    ceiling = income_ceiling(f.profile_income_kes)
    return ceiling is None or f.income_kes > ceiling


def income_is_top_driver(contributions) -> bool:
    if not isinstance(contributions, list):
        return False
    top = sorted(contributions, key=lambda c: abs(c.get("shap") or 0), reverse=True)[:3]
    return any(c.get("feature") in INCOME_FEATURES for c in top)


def work_out(f: Facts) -> Worked:
    held = f.deposits_kes if f.deposits_kes is not None else f.declared_savings_kes
    rule_max = max(comparator.SAVINGS_MULTIPLIER * max(held, 0) - f.outstanding_principal_kes, 0)
    obligations = f.loan_instalments_kes + f.chama_instalment_kes
    instalment = disposable = limit = affordable = passes = None
    near = False
    if f.term_months is not None:
        instalment = ledger.instalment_kes(f.amount_kes, f.term_months)
        if f.income_kes is not None:
            disposable = f.income_kes + f.expected_return_kes - obligations
            limit = config.AFFORDABILITY_RATIO * max(disposable, 0)
            affordable = ledger.largest_principal(limit, f.term_months)
            passes = instalment <= limit
            near = limit > 0 and abs(instalment - limit) <= config.AFFORDABILITY_NEAR_BAND * limit
    offer = rule_max if affordable is None else min(rule_max, affordable)
    # Capacity is needed for what could be lent, not for what cannot.
    backing = min(f.amount_kes, offer) if offer > 0 else f.amount_kes
    need = max(backing - f.own_free_kes, 0)
    chosen = choose_guarantors(f.guarantors, need)
    covered = len(chosen) >= comparator.MIN_GUARANTORS and sum(g.free_kes for g in chosen) >= need
    return Worked(rule_max, instalment, obligations, disposable, limit, affordable, offer, passes, near, need, chosen,
                  covered)


def check_rows(f: Facts, w: Worked) -> list[dict]:
    """Every check, with its values. passed is None when it could not be worked out."""
    def row(check, passed, **values):
        return {"check": check, "passed": passed, "values": values}
    need_months = comparator.MIN_TENURE_MONTHS
    return [
        row("deposits_on_record", f.deposits_kes is not None, deposits_kes=f.deposits_kes,
            declared_savings_kes=None if f.deposits_kes is not None else f.declared_savings_kes),
        row("membership", f.months_member >= need_months, months=f.months_member, minimum=need_months),
        row("savings_multiple", f.amount_kes <= w.rule_max_kes, amount_kes=f.amount_kes, maximum_kes=w.rule_max_kes,
            multiplier=comparator.SAVINGS_MULTIPLIER, outstanding_principal_kes=f.outstanding_principal_kes),
        row("guarantors", len(w.chosen) >= comparator.MIN_GUARANTORS, usable=len(w.chosen),
            minimum=comparator.MIN_GUARANTORS, any_at_all=f.any_guarantor),
        row("guarantor_capacity", w.capacity_passes, need_kes=w.capacity_need_kes, own_free_kes=f.own_free_kes,
            guarantors=[{"member_no": g.member_no, "free_kes": g.free_kes, "pledged": g.pledge_id is not None}
                        for g in f.guarantors], chosen=[g.member_no for g in w.chosen]),
        row("affordability", w.affordability_passes, instalment_kes=w.instalment_kes,
            monthly_income_kes=f.income_kes, expected_monthly_return_kes=f.expected_return_kes,
            loan_instalments_kes=f.loan_instalments_kes, chama_instalment_kes=f.chama_instalment_kes,
            disposable_kes=w.disposable_kes, limit_kes=None if w.limit_kes is None else round(w.limit_kes, 2),
            ratio=config.AFFORDABILITY_RATIO, rate=config.LOAN_INTEREST_MONTHLY, term_months=f.term_months),
        row("auto_limit", f.amount_kes <= config.AUTO_APPROVE_LIMIT_KES, amount_kes=f.amount_kes,
            limit_kes=config.AUTO_APPROVE_LIMIT_KES),
        row("income_increase", not income_needs_officer(f), stated=f.income_stated, monthly_income_kes=f.income_kes,
            profile_income_kes=f.profile_income_kes, most_accepted_kes=income_ceiling(f.profile_income_kes),
            tolerance=config.UNVERIFIED_INCREASE_TOLERANCE),
        row("risk", model_allows(f), risk_class=f.risk_class, clarifications_answered=sorted(f.answered)),
        row("no_arrears", not f.in_arrears, in_arrears=f.in_arrears),
    ]


# --- Clarifications ---------------------------------------------------------------------

def stale(age_days: int | None) -> bool:
    return age_days is None or age_days > config.PROFILE_STALE_DAYS


def question_triggers(f: Facts, w: Worked) -> dict[str, bool]:
    """Whether each question's condition holds, regardless of whether it can be asked."""
    above_both = (w.affordable_max_kes is not None and f.amount_kes > w.rule_max_kes
                  and f.amount_kes > w.affordable_max_kes)
    return {
        "C1": f.term_months is None,
        "C2": f.income_kes is None or stale(f.income_age_days)
              or (not f.income_verified and income_is_top_driver(f.contributions)),
        "C3": w.affordability_near and income_generating(f.purpose),
        "C4": not f.chama_use_known or stale(f.credit_age_days),
        "C5": not w.capacity_passes,
        "C6": above_both,
    }


def clarifications(f: Facts, w: Worked, fired: dict[str, bool]) -> list[str]:
    """At most two question ids, in priority order: those whose condition holds, that
    have not been asked, and whose answer could still change the outcome."""
    if f.final or f.refer_reason or f.months_member < comparator.MIN_TENURE_MONTHS and f.deposits_kes is not None:
        return []
    if f.deposits_kes is None or income_needs_officer(f):
        ask = {"C1"}            # an officer decides whatever else is said; the record needs a term
    elif not f.any_guarantor:
        return []
    elif f.risk_class == "High":
        ask = {"C1", "C2", "C4"}    # only what can move the score: nothing else changes a referral
    elif f.amount_kes > config.AUTO_APPROVE_LIMIT_KES and (w.offer_kes >= f.amount_kes
                                                            or w.offer_kes > config.AUTO_APPROVE_LIMIT_KES):
        ask = {"C1", "C6"}      # an officer decides this amount; only a lower one changes that
    else:
        ask = set(fired)
    wanted = [q for q in sorted(ask) if fired[q] and q not in f.asked]
    # C3 and C6 turn on the affordability figure: not worth asking while its inputs may change.
    if any(q in wanted for q in ("C1", "C2", "C4")):
        wanted = [q for q in wanted if q not in ("C3", "C6")]
    return wanted[:MAX_QUESTIONS]


# --- The policy -------------------------------------------------------------------------

@dataclass(frozen=True)
class Settled:
    outcome: str        # approve | approve_reduced | refer | not_now | clarify
    reason_code: str
    amount_kes: int | None = None       # the loan on offer; approve and approve_reduced only
    months_left: int | None = None


def model_allows(f: Facts) -> bool:
    return f.risk_class == "Low" or (f.risk_class == "Medium" and bool(f.answered & CLEARS_MEDIUM))


def settle(f: Facts, w: Worked, questions: list[str]) -> Settled:
    """The fixed policy: the first rule that applies. See docs/design_changes.md."""
    if f.deposits_kes is None:
        return Settled("refer", "self_declared")
    if f.months_member < comparator.MIN_TENURE_MONTHS:
        return Settled("not_now", "membership", months_left=comparator.MIN_TENURE_MONTHS - f.months_member)
    if not f.any_guarantor:
        return Settled("not_now", "no_guarantors")
    if f.refer_reason:
        return Settled("refer", f.refer_reason)
    if questions:
        return Settled("clarify", "clarify")
    if income_needs_officer(f):
        return Settled("refer", "income_unconfirmed")
    if f.risk_class == "High":
        return Settled("refer", "officer_review")
    if f.in_arrears:
        return Settled("refer", "arrears")
    if f.term_months is None or f.income_kes is None or f.declined & {"C2", "C4"}:
        return Settled("refer", "details_missing")
    if not model_allows(f):
        return Settled("refer", "officer_review")
    if f.amount_kes > min(w.rule_max_kes, w.affordable_max_kes):
        if w.offer_kes * 2 < f.requested_kes:
            return Settled("refer", "offer_too_small")
        if w.offer_kes > config.AUTO_APPROVE_LIMIT_KES:
            return Settled("refer", "above_limit")
        if not w.capacity_passes:
            return Settled("refer", "guarantors_short")
        if w.needs_named:
            return Settled("refer", "named_guarantor")
        return Settled("approve_reduced", "reduced_rule" if w.rule_max_kes <= w.affordable_max_kes
                       else "reduced_affordability", amount_kes=w.offer_kes)
    if f.amount_kes > config.AUTO_APPROVE_LIMIT_KES:
        return Settled("refer", "above_limit")
    if not w.capacity_passes:
        return Settled("refer", "guarantors_short")
    if w.needs_named:
        return Settled("refer", "named_guarantor")
    return Settled("approve", "approve", amount_kes=f.amount_kes)


# --- From the database to the facts --------------------------------------------------------

@dataclass(frozen=True)
class LoanRequest:
    amount_kes: int
    purpose: str
    term_months: int | None = None


@dataclass
class Evaluation:
    member_id: int
    request: LoanRequest
    overrides: dict
    facts: Facts
    worked: Worked
    settled: Settled
    questions: list[str]
    reason: str
    risk_class: str
    probabilities: dict
    contributions: list | str
    feature_vector: dict
    features: dict
    provenance: dict
    extraction_completeness: float
    features_populated: int
    features_total: int
    model_file: str
    model_sha256: str
    extra_guarantor_found: bool | None
    policy_version: str
    trace: dict

    @property
    def outcome(self) -> str:
        return self.settled.outcome

    @property
    def amount_kes(self) -> int | None:
        return self.settled.amount_kes

    @property
    def instalment_kes(self) -> int | None:
        """On the amount on offer, or on the amount asked while nothing is on offer."""
        term = self.facts.term_months
        return None if term is None else ledger.instalment_kes(self.amount_kes or self.facts.amount_kes, term)

    def guarantor_shares(self) -> list[tuple[GuarantorOption, int]]:
        """Who backs the amount on offer, and for how much. Only pledged guarantors can
        reach here on an approval: settle refers anything that needs a named one."""
        return allocate(self.worked.chosen, self.worked.capacity_need_kes)


def score_features(features: dict) -> score_interview.Scored:
    """The classifier and explainer as they are; never retrained."""
    if not (config.CLASSIFIER_PATH.exists() and config.CLASSIFIER_META_PATH.exists()):
        raise ClassifierMissing("classifier not available; run scripts/train_and_save.py")
    return score_interview.score(features, config.CLASSIFIER_PATH, config.CLASSIFIER_META_PATH, top=SHAP_KEPT)


def warm_classifier_in_background() -> None:
    """The classifier and SHAP load on the first evaluation, about 7 s in front of a member."""
    def run():
        try:
            score_features({f: {} if f == "lost_as_guarantor" else None for f in score_interview.FIELDS})
            log.info("classifier and SHAP ready")
        except Exception:
            log.exception("the classifier could not be warmed; the first evaluation will take longer")
    if config.ASR_WARM:
        threading.Thread(target=run, name="classifier-warm", daemon=True).start()


def clean_overrides(overrides: dict | None, request: LoanRequest) -> dict:
    overrides = dict(overrides or {})
    unknown = sorted(set(overrides) - set(OVERRIDE_KEYS))
    if unknown:
        raise BadOverride(f"overrides: {', '.join(unknown)} cannot be given in a conversation")
    if "chama_instalment_kes" in overrides and "chama_loan_use" not in overrides:
        raise BadOverride("overrides: chama_instalment_kes comes with chama_loan_use")
    accepted = overrides.get("accepted_amount_kes")
    if accepted is not None and accepted > request.amount_kes:
        raise BadOverride(f"overrides: accepted_amount_kes cannot exceed the KSh {request.amount_kes:,} requested")
    return overrides


def confirmations(db: Session, member_id: int) -> list[tuple[datetime, list]]:
    """The member's own "still right"s, each with the groups it covered: none named means
    the whole profile. Not profile.confirmed_at, which any edit or check of any one group
    moves: that says nothing about their income."""
    return [tuple(row) for row in db.execute(select(MemberProfileHistory.created_at, MemberProfileHistory.groups)
                                             .where(MemberProfileHistory.member_id == member_id,
                                                    MemberProfileHistory.change == "confirm"))]


def last_confirmed(seen: list[tuple[datetime, list]], group: str) -> datetime | None:
    return max((at for at, groups in seen if not groups or group in groups), default=None)


def income_is_stale(db: Session, member: Member, today: date | None = None) -> bool:
    """Whether the income on record is too old to read back to the member as fact."""
    age = group_age_days(member.profile, "income", last_confirmed(confirmations(db, member.id), "income"),
                         today or nairobi_today())
    return stale(age)


def group_age_days(p: MemberProfile | None, group: str, confirmed: datetime | None, today: date) -> int | None:
    """Days since this group was last set, checked or confirmed; None if never."""
    if p is None:
        return None
    dates = [d for d in (getattr(p, f"{group}_updated_at"), getattr(p, f"{group}_verified_at"), confirmed) if d]
    if not dates:
        return None
    return max((today - max(dates).astimezone(config.NAIROBI).date()).days, 0)


def loan_standing(db: Session, member_id: int, today: date) -> tuple[int, bool, int]:
    """(the instalments of their active loans, whether any loan is behind or defaulted,
    the principal still outstanding on their active loans)."""
    rows = db.scalars(select(LoanAccount).where(LoanAccount.member_id == member_id,
                                                LoanAccount.status.in_(ledger.STILL_OWED))).all()
    paid = ledger.paid_on_loans(db, [x.id for x in rows])
    active = [x for x in rows if x.status == "active"]
    behind = any(x.status == "defaulted" or ledger.days_in_arrears(x, paid.get(x.id, 0), today) > 0 for x in rows)
    outstanding = sum(ledger.outstanding_principal(x, paid.get(x.id, 0)) for x in active)
    return sum(x.monthly_instalment_kes for x in active), behind, outstanding


def named_member(db: Session, m: Member, named: dict | None) -> Member | None:
    """The member a C5 answer names, if both their number and their name match. Asking
    for both, and saying only found or not found, keeps this from telling anyone who
    holds a member number."""
    if not named:
        return None
    no, name = (named.get("member_no") or "").strip().upper(), (named.get("full_name") or "")
    other = db.scalar(select(Member).where(func.upper(Member.member_no) == no))
    if other is None or other.id == m.id or " ".join(name.split()).casefold() != " ".join(other.full_name.split()).casefold():
        return None
    return other


def guarantor_options(db: Session, m: Member, named: Member | None) -> tuple[tuple[GuarantorOption, ...], bool, int]:
    """(usable guarantors, whether there is any at all, the member's own free deposits).
    A pledge from someone with no phone cannot be used, as in sacco.offers_for. A pledge
    backs no more than its guarantor agreed to: with no ceiling set, nothing automatically."""
    pledges = db.scalars(select(GuarantorPledge).where(GuarantorPledge.borrower_member_id == m.id,
                                                       GuarantorPledge.status == "active")
                         .options(joinedload(GuarantorPledge.guarantor)).order_by(GuarantorPledge.id)).all()
    pledged = {p.guarantor_member_id for p in pledges}
    extra = named if named is not None and named.id not in pledged else None
    caps = ledger.capacities(db, {m.id, *pledged, *([extra.id] if extra else [])})
    held = ledger.held_under_pledges(db, [p.id for p in pledges])
    options = [GuarantorOption(p.guarantor_member_id, p.guarantor.member_no, p.guarantor.full_name, p.guarantor.phone,
                               min(caps[p.guarantor_member_id].available_kes,
                                   max((p.max_amount_kes or 0) - held.get(p.id, 0), 0)), p.id)
               for p in pledges if p.guarantor.phone]
    if extra is not None:
        options.append(GuarantorOption(extra.id, extra.member_no, extra.full_name, extra.phone or "",
                                       caps[extra.id].available_kes))
    return tuple(options), bool(pledges) or named is not None, caps[m.id].available_kes


ANSWER_KEY = {"C1": "term_months", "C2": "monthly_income_kes", "C3": "expected_monthly_return_kes",
              "C4": "chama_loan_use", "C5": "extra_guarantor", "C6": "accepted_amount_kes"}


def evaluate(db: Session, member: Member, request: LoanRequest, overrides: dict | None = None,
             final: bool = False, today: date | None = None, refer_reason: str | None = None) -> Evaluation:
    """Read everything, score, settle. Writes nothing, and the profile stays as it is.
    final: settle on what is known, with no more questions (accepting an offer).
    refer_reason: the caller is stopping here and a person decides (a reason code);
    the rules a member has not met yet still come first."""
    today = today or nairobi_today()
    overrides = clean_overrides(overrides, request)
    known = profiles.profile_features(db, member, today)
    p = member.profile
    features = {**known.features}
    provenance = {**known.provenance}
    for key in FEATURE_OVERRIDES:
        if overrides.get(key) is not None:
            features[key] = overrides[key]
            provenance[key] = "conversation"
    for key in ("term_months", "expected_monthly_return_kes", "chama_instalment_kes", "accepted_amount_kes"):
        if overrides.get(key) is not None:
            provenance[key] = "conversation"

    scored = score_features(features)
    out = scored.assessment
    vector = {c: None if math.isnan(v := float(x)) else v for c, x in scored.vector.iloc[0].items()}

    named = named_member(db, member, overrides.get("extra_guarantor"))
    options, any_guarantor, own_free = guarantor_options(db, member, named)
    deposits = ledger.deposits_balance(db, member.id)
    instalments, behind, outstanding = loan_standing(db, member.id, today)
    confirmed = confirmations(db, member.id)
    asked = {q for q, key in ANSWER_KEY.items() if key in overrides}
    answered = {q for q in asked if overrides[ANSWER_KEY[q]] is not None}
    # C5 is answered only by a member who is found: anyone can be named.
    if named is None:
        answered.discard("C5")

    facts = Facts(
        requested_kes=request.amount_kes, purpose=request.purpose,
        amount_kes=overrides.get("accepted_amount_kes") or request.amount_kes,
        term_months=overrides["term_months"] if "term_months" in overrides else request.term_months,
        income_kes=features["monthly_income_kes"], deposits_kes=deposits,
        declared_savings_kes=max(member.savings_kes or 0, 0),
        # Self-declared savings fail "on record" and nothing else: the other checks read the figure.
        own_free_kes=own_free if deposits is not None else max(member.savings_kes or 0, 0),
        months_member=comparator.months_between(member.joined_on, today), risk_class=out["risk_class"],
        contributions=out["top_contributions"], expected_return_kes=overrides.get("expected_monthly_return_kes") or 0,
        loan_instalments_kes=instalments, chama_instalment_kes=overrides.get("chama_instalment_kes") or 0,
        guarantors=options, any_guarantor=any_guarantor,
        # Asked already: the answer is fresh, and no answer is settled as details_missing.
        income_age_days=0 if "C2" in asked else group_age_days(p, "income", last_confirmed(confirmed, "income"), today),
        income_verified=provenance.get("monthly_income_kes") in ("verified", "conversation"),
        chama_use_known=features["chama_loan_use"] is not None,
        credit_age_days=group_age_days(p, "credit", last_confirmed(confirmed, "credit"), today), in_arrears=behind,
        asked=frozenset(asked), answered=frozenset(answered), declined=frozenset(asked - answered), final=final,
        outstanding_principal_kes=outstanding, profile_income_kes=known.features["monthly_income_kes"],
        income_stated=overrides.get("monthly_income_kes") is not None, refer_reason=refer_reason)
    worked = work_out(facts)
    fired = question_triggers(facts, worked)
    questions = clarifications(facts, worked, fired)
    settled = settle(facts, worked, questions)

    trace = {
        "policy_version": policy_version(), "evaluated_on": today.isoformat(), "thresholds": thresholds(),
        "request": {"amount_kes": request.amount_kes, "purpose": request.purpose, "term_months": request.term_months},
        "effective": {"amount_kes": facts.amount_kes, "term_months": facts.term_months},
        "checks": check_rows(facts, worked),
        "maximums": {"rule_kes": worked.rule_max_kes, "affordable_kes": worked.affordable_max_kes},
        "refer_reason": refer_reason,
        "clarifications": {"conditions": fired, "asked": sorted(asked), "answered": sorted(answered),
                           "returned": questions,
                           "income_age_days": group_age_days(p, "income", last_confirmed(confirmed, "income"), today),
                           "income_verified": known.provenance.get("monthly_income_kes") == "verified",
                           "income_top_three_driver": income_is_top_driver(facts.contributions)},
        "model": {"risk_class": out["risk_class"], "probabilities": out["probabilities"],
                  "model_file": scored.model_file, "model_sha256": scored.model_sha256},
        "outcome": settled.outcome, "reason_code": settled.reason_code, "amount_kes": settled.amount_kes,
    }
    return Evaluation(
        member_id=member.id, request=request, overrides=overrides, facts=facts, worked=worked, settled=settled,
        questions=questions, reason=member_text.decision_reason(settled.reason_code, _reason_values(facts, worked, settled)),
        risk_class=out["risk_class"], probabilities=out["probabilities"], contributions=out["top_contributions"],
        feature_vector=vector, features=features, provenance=provenance,
        extraction_completeness=out["extraction_completeness"], features_populated=out["features_populated"],
        features_total=out["features_total"], model_file=scored.model_file, model_sha256=scored.model_sha256,
        extra_guarantor_found=None if "extra_guarantor" not in overrides else named is not None,
        policy_version=policy_version(), trace=trace)


def _reason_values(f: Facts, w: Worked, s: Settled) -> dict:
    amount = s.amount_kes or f.amount_kes
    term = f.term_months
    return {"amount": amount, "requested": f.requested_kes, "term": term,
            "instalment": None if term is None else ledger.instalment_kes(amount, term),
            "rule_max": w.rule_max_kes, "affordable_max": w.affordable_max_kes,
            "months_left": s.months_left, "min_months": comparator.MIN_TENURE_MONTHS,
            "min_guarantors": comparator.MIN_GUARANTORS, "limit": config.AUTO_APPROVE_LIMIT_KES}
