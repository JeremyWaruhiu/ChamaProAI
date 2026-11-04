"""Committing an automatic decision, the endpoints the next phase's conversation calls,
and the officer's page of decisions.

commit(evaluation, key) writes a loan application, an interview holding its immutable
assessment (with the features, provenance, overrides, SHAP and the policy's full trace)
and a decision by the system user. On an automatic approval the member's standing
guarantors become guarantors rows accepted under their pledge, and the loan is paid out.
A reduced offer waits for the member, a referral for an officer.

Nothing trusts the evaluation handed in: under the locks, the engine runs again on what
the database now says, and if that is not what the member was told, nothing is written.

Members get only what schemas.SelfServiceEvaluation allows, built field by field; the
trace, the class, the SHAP values and any guarantor's capacity are for staff.
"""
from __future__ import annotations

from dataclasses import dataclass

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from chamapro import config

from . import audit, comparator, decisions, idempotency, ledger, loans, member_text
from . import schemas as s
from .auth import LoginLimiter, require_member, require_officer
from .db import (SYSTEM_USERNAME, Applicant, Assessment, Decision, Guarantor, GuarantorPledge, Interview, LoanAccount,
                 LoanApplication, Member, SelfServiceRun, User, get_db, utcnow)
from .decisions import Evaluation, LoanRequest
from .ledger_api import IdemKey, reversal_deadline
from .pilot import required_member
from .sacco import STANDING_GUARANTOR

ERRORS = {code: {"model": s.Error} for code in (401, 403, 404, 409, 422, 429, 503)}
router = APIRouter(prefix="/api", responses=ERRORS)

# loan_applications.term_months is required; someone who gave no term and is referred
# still needs a record. Only an officer's decision can follow from it, and the trace
# says no term was given.
TERM_FOR_THE_RECORD = 12
COARSE = {"approve": "approve", "approve_reduced": "approve", "refer": "refer", "not_now": "decline"}
STATUS_AFTER = {"approve": "approved", "approve_reduced": "offered", "refer": "decided", "not_now": "declined"}
# Where a self-service application is finished with, once any loan has been paid out.
FINISHED = ("declined", "reversed")
# Recorded on an assessment instead of an extraction model: nothing was extracted.
PROFILE_NOT_EXTRACTED = "none: read from the member's profile"

evaluations = LoginLimiter(config.SELF_SERVICE_EVALUATIONS_PER_HOUR, 3600)
commits = LoginLimiter(config.SELF_SERVICE_COMMITS_PER_HOUR, 3600)


class CannotCommit(Exception):
    """Nothing was written; str(e) says why, in words a member can read."""


@dataclass
class DecisionChanged(CannotCommit):
    """Under the locks the engine no longer agrees with what the member was told."""
    fresh: Evaluation

    def __str__(self) -> str:
        return "Something has changed since you were told this. Please ask again."


def system_user(db: Session) -> User:
    return db.scalar(select(User).where(User.username == SYSTEM_USERNAME))


def lock_everyone(db: Session, member: Member, overrides: dict) -> set[int]:
    """The borrower and everyone who could back them, in the fixed order. A pledge made
    after this is not among them; commit notices and stops."""
    ids = {member.id, *db.scalars(select(GuarantorPledge.guarantor_member_id)
                                  .where(GuarantorPledge.borrower_member_id == member.id,
                                         GuarantorPledge.status == "active"))}
    named = decisions.named_member(db, member, overrides.get("extra_guarantor"))
    if named is not None:
        ids.add(named.id)
    ledger.lock_members(db, ids)
    return ids


def has_open_application(db: Session, member_id: int) -> bool:
    """One at a time: another self-service application still being decided or not yet
    paid out, whose loan the next request would not otherwise see."""
    return db.scalar(select(LoanApplication.id)
                     .outerjoin(LoanAccount, LoanAccount.application_id == LoanApplication.id)
                     .where(LoanApplication.member_id == member_id, LoanApplication.channel == "self_service",
                            LoanApplication.status.not_in(FINISHED), LoanAccount.id.is_(None)).limit(1)) is not None


def record_run(db: Session, ev: Evaluation, app: LoanApplication, member: Member, system: User, trigger: str) -> Decision:
    """The immutable record of one automatic decision: an interview with no answers,
    its assessment and its decision. The application moves on to it."""
    iv = Interview(applicant=Applicant(name=member.full_name, age=ev.features.get("age"), sex=member.sex,
                                       education=ev.features.get("education_level"),
                                       marital_status=ev.features.get("marital_status")),
                   question_set="v2", language="en", mode="self_service", status="assessed")
    a = Assessment(interview=iv, risk_class=ev.risk_class, probabilities=ev.probabilities,
                   feature_vector=ev.feature_vector, contributions=ev.contributions, extracted=ev.features,
                   applicant_form=None, extraction_completeness=ev.extraction_completeness,
                   features_populated=ev.features_populated, features_total=ev.features_total,
                   features_not_extractable=[], extraction_model=PROFILE_NOT_EXTRACTED,
                   model_file=ev.model_file, model_sha256=ev.model_sha256, assessed_by=SYSTEM_USERNAME,
                   provenance=ev.provenance, overrides=ev.overrides, policy_trace=ev.trace)
    d = Decision(interview=iv, decision=COARSE[ev.outcome], outcome=ev.outcome, approved_amount_kes=ev.amount_kes,
                 guarantors_required=comparator.MIN_GUARANTORS if ev.amount_kes else None,
                 member_message=ev.reason, decided_by=SYSTEM_USERNAME, policy_version=ev.policy_version)
    db.add_all([iv, a, d])
    db.flush()
    run = SelfServiceRun(application_id=app.id, interview_id=iv.id, trigger=trigger)
    db.add(run)
    app.interview_id = iv.id
    db.flush()
    audit.record(db, system, "assessment.create", "assessment", a.id, interview_id=iv.id, risk_class=a.risk_class)
    audit.record(db, system, "decision.create", "decision", d.id, interview_id=iv.id, application_id=app.id,
                 outcome=ev.outcome, approved_amount_kes=ev.amount_kes, policy_version=ev.policy_version)
    return d


def accept_guarantors_and_pay(db: Session, ev: Evaluation, app: LoanApplication, system: User) -> LoanAccount:
    """Standing guarantors become guarantors rows accepted under their pledge, holding
    what is needed of the loan, and the loan is paid out."""
    now = utcnow()
    for g, amount in ev.guarantor_shares():
        row = Guarantor(application=app, full_name=g.full_name, member_no=g.member_no, phone=g.phone,
                        relationship_=STANDING_GUARANTOR, amount_guaranteed_kes=amount, status="verified",
                        verified_by=system.id, verified_at=now, member_id=g.member_id, pledge_id=g.pledge_id,
                        accepted_under_pledge=True)
        db.add(row)
        db.flush()
        audit.record(db, system, "guarantor.accept_pledge", "guarantor", row.id, application_id=app.id,
                     pledge_id=g.pledge_id)
    loan = ledger.pay_out(db, app, ev.amount_kes, system)
    audit.record(db, system, "loan.pay_out", "loan_account", loan.id, application_id=app.id, automatic=True)
    return loan


def committed_reply(ev: Evaluation, app: LoanApplication, loan: LoanAccount | None) -> s.SelfServiceCommitted:
    return s.SelfServiceCommitted(
        application_id=app.id, outcome=ev.outcome, status=app.status, status_label=member_text.STATUS_LABEL[app.status],
        message=ev.reason, amount_kes=ev.amount_kes, term_months=app.term_months,
        monthly_instalment_kes=ev.instalment_kes if ev.amount_kes else None, loan_id=loan.id if loan else None,
        can_book_interview=ev.outcome == "refer", can_accept=ev.outcome == "approve_reduced",
        policy_version=ev.policy_version)


def apply_outcome(db: Session, ev: Evaluation, app: LoanApplication, member: Member, trigger: str,
                  locked: set[int]) -> s.SelfServiceCommitted:
    """Record the decision, move the application, and pay out if it says so."""
    if any(g.member_id not in locked for g in ev.worked.chosen):
        raise DecisionChanged(ev)       # a pledge made since the locks: start again
    system = system_user(db)
    record_run(db, ev, app, member, system, trigger)
    loans.set_status(db, app, STATUS_AFTER[ev.outcome], system, automatic=True)
    loan = accept_guarantors_and_pay(db, ev, app, system) if ev.outcome == "approve" else None
    return committed_reply(ev, app, loan)


def commit(db: Session, evaluation: Evaluation, idempotency_key: str, actor: User,
           expected: tuple[str, int | None] | None = None) -> dict:
    """Write the decision, once per key: a repeat gets the first reply and pays out
    nothing. expected is (outcome, amount) as the member was told, by default the
    evaluation's own. Commits. Raises CannotCommit, having written nothing."""
    request, overrides = evaluation.request, evaluation.overrides
    try:
        row, stored = idempotency.claim(db, actor, idempotency_key, "self_service.commit",
                                        {"member": evaluation.member_id, "amount_kes": request.amount_kes,
                                         "purpose": request.purpose, "term_months": request.term_months,
                                         "overrides": overrides})
    except idempotency.KeyReused as e:
        raise CannotCommit(str(e)) from None
    if row is None:
        return stored
    try:
        member = db.get(Member, evaluation.member_id)
        locked = lock_everyone(db, member, overrides)
        fresh = decisions.evaluate(db, member, request, overrides)
        wanted = expected or (evaluation.outcome, evaluation.amount_kes)
        if (fresh.outcome, fresh.amount_kes) != wanted:
            raise DecisionChanged(fresh)
        if fresh.outcome == "clarify":
            raise CannotCommit("There are questions still to answer before this can be decided.")
        if has_open_application(db, member.id):
            raise CannotCommit("You already have an application being decided. Please finish that one first.")
        term = fresh.facts.term_months or TERM_FOR_THE_RECORD
        savings = fresh.facts.deposits_kes if fresh.facts.deposits_kes is not None else fresh.facts.declared_savings_kes
        app = LoanApplication(member_id=member.id, amount_requested_kes=request.amount_kes, purpose=request.purpose,
                              term_months=term, sacco_savings_kes=max(savings, 0),
                              savings_self_declared=fresh.facts.deposits_kes is None, channel="self_service",
                              status="draft", created_by=actor.id)
        db.add(app)
        db.flush()
        audit.record(db, actor, "application.create", "loan_application", app.id, status="draft", member_id=member.id,
                     amount_requested_kes=request.amount_kes, via="self_service")
        reply = idempotency.finish(row, apply_outcome(db, fresh, app, member, "commit", locked))
        db.commit()
        return reply
    except (CannotCommit, ledger.LedgerError, IntegrityError) as e:
        db.rollback()
        if isinstance(e, CannotCommit):
            raise
        raise CannotCommit("That could not be saved just now. Please try again.") from e


def accept_offer(db: Session, app: LoanApplication, idempotency_key: str, actor: User) -> dict:
    """The member takes the reduced offer. The engine runs again at that amount, with
    no more questions: an approval pays out; anything else goes where it says, recorded
    the same way, because a capacity can have been spent since the offer was made."""
    try:
        row, stored = idempotency.claim(db, actor, idempotency_key, "self_service.accept", {"application": app.id})
    except idempotency.KeyReused as e:
        raise CannotCommit(str(e)) from None
    if row is None:
        return stored
    try:
        member = db.get(Member, app.member_id)
        previous = app.interview.assessment.overrides or {}
        offered = app.interview.decision.approved_amount_kes
        overrides = {**previous, "accepted_amount_kes": offered}
        locked = lock_everyone(db, member, overrides)
        db.refresh(app)
        if app.status != "offered":
            raise CannotCommit("This offer is no longer open.")
        request = LoanRequest(app.amount_requested_kes, app.purpose, app.term_months)
        fresh = decisions.evaluate(db, member, request, overrides, final=True)
        reply = idempotency.finish(row, apply_outcome(db, fresh, app, member, "acceptance", locked))
        db.commit()
        return reply
    except (CannotCommit, ledger.LedgerError, IntegrityError) as e:
        db.rollback()
        if isinstance(e, CannotCommit):
            raise
        raise CannotCommit("That could not be saved just now. Please try again.") from e


# --- What a member sees -------------------------------------------------------------------

def member_view(ev: Evaluation) -> s.SelfServiceEvaluation:
    w = ev.worked
    final = ev.outcome != "clarify"
    return s.SelfServiceEvaluation(
        outcome=ev.outcome, reason=ev.reason,
        questions=[s.ClarificationOut(id=q, reason=member_text.question_reason(q),
                                      sets=member_text.QUESTION_SETS_FEATURE[q]) for q in ev.questions],
        amount_requested_kes=ev.request.amount_kes, amount_on_offer_kes=ev.amount_kes,
        term_months=ev.facts.term_months, monthly_instalment_kes=ev.instalment_kes,
        maximum_by_savings_kes=w.rule_max_kes, maximum_affordable_kes=w.affordable_max_kes,
        extra_guarantor_found=ev.extra_guarantor_found,
        reasons=member_text.reasons(ev.risk_class, ev.contributions) if final else [],
        policy_version=ev.policy_version)


def limited(limiter: LoginLimiter, key: str) -> None:
    """Every attempt counts: each one runs the classifier, and enough of them could
    tell a member something about a guarantor's capacity."""
    wait = limiter.retry_after(key)
    if wait is not None:
        raise HTTPException(429, "too many requests; please try again later", headers={"Retry-After": str(wait)})
    limiter.fail(key)


def evaluated(db: Session, member: Member, body: s.SelfServiceRequest) -> Evaluation:
    try:
        return decisions.evaluate(db, member, LoanRequest(body.amount_kes, body.purpose, body.term_months),
                                  body.overrides.model_dump(exclude_unset=True))
    except decisions.BadOverride as e:
        raise HTTPException(422, str(e)) from None
    except decisions.ClassifierMissing:
        raise HTTPException(503, "We could not look at this just now. Please try again later.") from None


@router.post("/self-service/evaluate", response_model=s.SelfServiceEvaluation)
def self_service_evaluate(body: s.SelfServiceRequest, db: Session = Depends(get_db),
                          user: User = Depends(require_member)):
    """What would happen, and what we still need to ask. Writes nothing."""
    member = required_member(db, user)
    limited(evaluations, f"member:{member.id}")
    return member_view(evaluated(db, member, body))


@router.post("/self-service/commit", status_code=201, response_model=s.SelfServiceCommitted)
def self_service_commit(body: s.SelfServiceCommit, key: IdemKey, db: Session = Depends(get_db),
                        user: User = Depends(require_member)):
    """Act on what the member was told. If the engine no longer agrees, 409 and nothing
    is written: evaluate again."""
    member = required_member(db, user)
    limited(commits, f"member:{member.id}")
    try:
        return JSONResponse(commit(db, evaluated(db, member, body), key, user,
                                   expected=(body.expected_outcome, body.expected_amount_kes)), status_code=201)
    except CannotCommit as e:
        raise HTTPException(409, str(e)) from None


def my_offer(db: Session, user: User, application_id: int) -> LoanApplication:
    """The member's own application; anyone else's is the same 404 as none at all."""
    app = loans.own_application(db, user, application_id)
    if app.channel != "self_service":
        raise HTTPException(404, f"application {application_id} not found")
    return app


@router.post("/self-service/applications/{application_id}/accept", status_code=201,
             response_model=s.SelfServiceCommitted)
def self_service_accept(application_id: int, key: IdemKey, db: Session = Depends(get_db),
                        user: User = Depends(require_member)):
    """Take the smaller loan on offer."""
    app = my_offer(db, user, application_id)
    limited(commits, f"member:{app.member_id}")
    try:
        return JSONResponse(accept_offer(db, app, key, user), status_code=201)
    except decisions.ClassifierMissing:
        raise HTTPException(503, "We could not look at this just now. Please try again later.") from None
    except CannotCommit as e:
        raise HTTPException(409, str(e)) from None


@router.post("/self-service/applications/{application_id}/decline", response_model=s.MyApplication)
def self_service_decline(application_id: int, key: IdemKey, db: Session = Depends(get_db),
                         user: User = Depends(require_member)):
    """Turn the offer down; the application ends and nothing was held for it."""
    app = my_offer(db, user, application_id)

    def work(_) -> s.MyApplication:
        db.refresh(app)
        if app.status != "offered":
            raise HTTPException(409, "This offer is no longer open.")
        loans.set_status(db, app, "declined", user, offer_declined=True)
        return loans.my_view(db, app)
    return idempotency.run_once(db, user, key, f"self_service.decline:{application_id}", {}, work, status_code=200)


# --- The officer's page -------------------------------------------------------------------

LOAD = (joinedload(SelfServiceRun.application).joinedload(LoanApplication.member),
        joinedload(SelfServiceRun.interview).joinedload(Interview.assessment),
        joinedload(SelfServiceRun.interview).joinedload(Interview.decision))


def decision_out(run: SelfServiceRun, loan: LoanAccount | None) -> dict:
    app, iv = run.application, run.interview
    d, a = iv.decision, iv.assessment
    deadline = None
    # The payout belongs to the approval: not to an earlier reduced offer on the same application.
    this_paid = loan if d.outcome == "approve" else None
    if this_paid is not None and this_paid.status == "active":
        until = reversal_deadline(this_paid, app)
        deadline = until if until is not None and utcnow() <= until else None
    return dict(id=run.id, application_id=app.id, member_id=app.member_id, member_no=app.member.member_no,
                member_name=app.member.full_name, trigger=run.trigger, outcome=d.outcome,
                amount_requested_kes=app.amount_requested_kes, amount_kes=d.approved_amount_kes,
                risk_class=a.risk_class, policy_version=d.policy_version, application_status=app.status,
                loan_id=this_paid.id if this_paid else None, loan_status=this_paid.status if this_paid else None,
                reversible_until=deadline, created_at=run.created_at)


@router.get("/automatic-decisions", response_model=list[s.AutomaticDecision])
def list_automatic_decisions(outcome: s.SelfServiceOutcome | None = None, limit: int = Query(100, ge=1, le=500),
                             offset: int = Query(0, ge=0), db: Session = Depends(get_db),
                             _: User = Depends(require_officer)):
    """Newest first. Two queries however many rows there are."""
    stmt = (select(SelfServiceRun).options(*LOAD).order_by(SelfServiceRun.created_at.desc(), SelfServiceRun.id.desc())
            .limit(limit).offset(offset))
    if outcome is not None:
        stmt = stmt.join(Decision, Decision.interview_id == SelfServiceRun.interview_id).where(Decision.outcome == outcome)
    runs = db.scalars(stmt).all()
    paid = {x.application_id: x for x in db.scalars(select(LoanAccount).where(
        LoanAccount.application_id.in_({r.application_id for r in runs})))}
    return [s.AutomaticDecision(**decision_out(r, paid.get(r.application_id))) for r in runs]


@router.get("/automatic-decisions/{run_id}", response_model=s.AutomaticDecisionDetail)
def get_automatic_decision(run_id: int, db: Session = Depends(get_db), _: User = Depends(require_officer)):
    run = db.get(SelfServiceRun, run_id, options=LOAD)
    if run is None:
        raise HTTPException(404, f"automatic decision {run_id} not found")
    a, d = run.interview.assessment, run.interview.decision
    paid = db.scalar(select(LoanAccount).where(LoanAccount.application_id == run.application_id))
    return s.AutomaticDecisionDetail(
        **decision_out(run, paid), probabilities=a.probabilities, contributions=a.contributions,
        feature_vector=a.feature_vector, features=a.extracted, provenance=a.provenance or {}, overrides=a.overrides or {},
        trace=a.policy_trace or {}, member_message=d.member_message, model_file=a.model_file, model_sha256=a.model_sha256)
