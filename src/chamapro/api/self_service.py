"""Committing an automatic decision, the endpoints the next phase's conversation calls,
and the officer's page of decisions.

record(evaluation, key) writes a loan application, an interview holding its immutable
assessment (with the features, provenance, overrides, SHAP and the policy's full trace)
and a decision by the system user. On an automatic approval the member's standing
guarantors become guarantors rows accepted under their pledge, and the loan is paid out.
A reduced offer waits for the member, a referral for an officer. Every automatic outcome
can be sent to an officer to review (Data Protection Act s.35), and a guarantor whose
pledge is used hears about it on My SACCO.

Nothing trusts the evaluation handed in: under the locks, the engine runs again on what
the database now says, and if that is not what the member was told, nothing is written.

The whole of it goes to the database as one statement (batch.py), with whatever else the
caller wants kept with it: a conversation sends its turns along, so that the money and the
words that announce it cannot be parted. From lock to commit that is five round trips.

Members get only what schemas.SelfServiceEvaluation allows, built field by field; the
trace, the class, the SHAP values and any guarantor's capacity are for staff.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from chamapro import config
from chamapro.conversation import templates

from . import audit, comparator, decisions, idempotency, ledger, loans, member_text
from . import schemas as s
from .auth import LoginLimiter, require_member, require_officer
from .batch import Batch, reserve as reserve_ids
from .db import (SYSTEM_USERNAME, AccountEntry, Applicant, Assessment, Decision, Guarantor, GuarantorPledge, IdempotencyKey,
                 Interview, LoanAccount, LoanApplication, Member, MemberNotice, SelfServiceRun, User, get_db, nairobi_today,
                 utcnow)
from .decisions import FINISHED, Evaluation, LoanRequest, Snapshot
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


@dataclass(frozen=True)
class SystemActor:
    """Who an automatic decision is by: the system user, as far as a row needs to know."""
    id: int


def system_user(db: Session) -> User:
    return db.scalar(select(User).where(User.username == SYSTEM_USERNAME))


def has_open_application(db: Session, member_id: int) -> bool:
    """One at a time: another self-service application still being decided or not yet
    paid out, whose loan the next request would not otherwise see."""
    return db.scalar(select(LoanApplication.id)
                     .outerjoin(LoanAccount, LoanAccount.application_id == LoanApplication.id)
                     .where(LoanApplication.member_id == member_id, LoanApplication.channel == "self_service",
                            LoanApplication.status.not_in(FINISHED), LoanAccount.id.is_(None)).limit(1)) is not None


def answers_on_record(assessment: Assessment) -> dict:
    """What an earlier decision was given, to run the engine on again. A guarantor named at the
    question that no longer exists stays on the record and is not an answer any more."""
    return {k: v for k, v in (assessment.overrides or {}).items() if k in decisions.OVERRIDE_KEYS}


def rows_for(*evaluations_: Evaluation) -> dict[str, int]:
    """The ids an evaluation's decision will be written under, reserved with the locks. If the
    fresh evaluation under them turns out to want more, Batch fetches them, at a round trip."""
    runs, paid = len(evaluations_), [e for e in evaluations_ if e.outcome == "approve"]
    return {"applicants": runs, "interviews": runs, "assessments": runs, "decisions": runs, "self_service_runs": runs,
            "loan_accounts": len(paid), "account_entries": len(paid), "member_accounts": len(paid),
            "guarantors": sum(len(e.worked.chosen) for e in paid)}


def record_run(out: Batch, ev: Evaluation, app: LoanApplication, member: Member, system, trigger: str,
               move_application: bool = True) -> SelfServiceRun:
    """The immutable record of one automatic decision: an interview with no answers,
    its assessment and its decision. The application moves on to it, unless the loan
    it decided is already out and this is only a request to look at it."""
    who = Applicant(name=member.full_name, age=ev.features.get("age"), sex=member.sex,
                    education=ev.features.get("education_level"), marital_status=ev.features.get("marital_status"))
    iv = Interview(applicant_id=out.give_id(who), question_set="v2", language="en", mode="self_service", status="assessed")
    out.give_id(iv)
    a = Assessment(interview_id=iv.id, risk_class=ev.risk_class, probabilities=ev.probabilities,
                   feature_vector=ev.feature_vector, contributions=ev.contributions, extracted=ev.features,
                   applicant_form=None, extraction_completeness=ev.extraction_completeness,
                   features_populated=ev.features_populated, features_total=ev.features_total,
                   features_not_extractable=[], extraction_model=PROFILE_NOT_EXTRACTED,
                   model_file=ev.model_file, model_sha256=ev.model_sha256, assessed_by=SYSTEM_USERNAME,
                   provenance=ev.provenance, overrides=ev.overrides, policy_trace=ev.trace)
    d = Decision(interview_id=iv.id, decision=COARSE[ev.outcome], outcome=ev.outcome, approved_amount_kes=ev.amount_kes,
                 guarantors_required=comparator.MIN_GUARANTORS if ev.amount_kes else None,
                 member_message=ev.reason, decided_by=SYSTEM_USERNAME, policy_version=ev.policy_version)
    run = SelfServiceRun(application_id=app.id, interview_id=iv.id, trigger=trigger)
    out.give_id(a), out.give_id(d), out.give_id(run)
    for row in (who, iv, a, d, run):
        out.add(row)
    if move_application:
        app.interview_id = iv.id
    audit.record(out, system, "assessment.create", "assessment", a.id, interview_id=iv.id, risk_class=a.risk_class)
    audit.record(out, system, "decision.create", "decision", d.id, interview_id=iv.id, application_id=app.id,
                 outcome=ev.outcome, approved_amount_kes=ev.amount_kes, policy_version=ev.policy_version)
    return run


@dataclass
class PaidOut:
    loan: LoanAccount
    entry: AccountEntry
    guarantors: list[str]


def accept_guarantors_and_pay(out: Batch, ev: Evaluation, app: LoanApplication, member: Member, system,
                              locked: ledger.Locked, snap: Snapshot) -> PaidOut:
    """Standing guarantors become guarantors rows accepted under their pledge, holding
    what is needed of the loan, and the loan is paid out. The caller has locked them all,
    and an application held by an automatic offer has no other guarantors to release."""
    now, shares = utcnow(), ev.guarantor_shares()
    short = [g for g, amount in shares if amount > snap.capacity(g.member_id).available_kes]
    if short:
        raise ledger.LedgerError(f"guarantor {short[0].member_no} no longer has the capacity for this loan")
    term = app.term_months
    loan = LoanAccount(member_id=member.id, application_id=app.id, principal_kes=ev.amount_kes, disbursed_on=nairobi_today(),
                       term_months=term, monthly_instalment_kes=ledger.instalment_kes(ev.amount_kes, term),
                       status="active", created_by=system.id)
    out.give_id(loan)
    for g, amount in shares:
        row = Guarantor(application_id=app.id, full_name=g.full_name, member_no=g.member_no, phone=g.phone,
                        relationship_=STANDING_GUARANTOR, amount_guaranteed_kes=amount, status="verified",
                        verified_by=system.id, verified_at=now, member_id=g.member_id, pledge_id=g.pledge_id,
                        accepted_under_pledge=True, loan_account_id=loan.id)
        out.give_id(row)
        out.add(row)
        audit.record(out, system, "guarantor.accept_pledge", "guarantor", row.id, application_id=app.id,
                     pledge_id=g.pledge_id)
    entry = AccountEntry(account_id=ledger.account_id_in(out, locked, member.id, "transactional"),
                         account_kind="transactional", entry_type="loan_disbursement", amount_kes=loan.principal_kes,
                         posted_at=now, reference=f"LOAN-{loan.id}", created_by=system.id, loan_account_id=loan.id)
    out.give_id(entry)
    out.add(loan)
    out.add(entry)
    audit.record(out, system, "loan.pay_out", "loan_account", loan.id, application_id=app.id, automatic=True)
    for g, _ in shares:
        out.add(MemberNotice(member_id=g.member_id, kind="guarantee_started", loan_account_id=loan.id,
                             text=f"You are now guaranteeing {member.full_name}'s loan of KSh {loan.principal_kes:,}."))
    return PaidOut(loan, entry, [g.full_name for g, _ in shares])


def committed_reply(ev: Evaluation, app: LoanApplication, loan: LoanAccount | None) -> s.SelfServiceCommitted:
    return s.SelfServiceCommitted(
        application_id=app.id, outcome=ev.outcome, status=app.status, status_label=member_text.STATUS_LABEL[app.status],
        message=ev.reason, amount_kes=ev.amount_kes, term_months=app.term_months,
        monthly_instalment_kes=ev.instalment_kes if ev.amount_kes else None, loan_id=loan.id if loan else None,
        can_book_interview=ev.outcome == "refer", can_accept=ev.outcome == "approve_reduced",
        policy_version=ev.policy_version)


@dataclass
class Recorded:
    """What record() wrote. reply is what an API caller is given and what its key keeps."""
    reply: dict
    application_id: int
    run_id: int | None = None
    paid: PaidOut | None = None
    snapshot: Snapshot | None = None
    final: Evaluation | None = None


def apply_outcome(out: Batch, ev: Evaluation, app: LoanApplication, member: Member, trigger: str, locked: ledger.Locked,
                  snap: Snapshot) -> tuple[s.SelfServiceCommitted, SelfServiceRun, PaidOut | None]:
    """Record the decision, move the application, and pay out if it says so."""
    if any(g.member_id not in locked.members for g in ev.worked.chosen):
        raise DecisionChanged(ev)       # a pledge made since the locks: start again
    system = SystemActor(snap.system_user_id)
    run = record_run(out, ev, app, member, system, trigger)
    loans.set_status(out, app, STATUS_AFTER[ev.outcome], system, automatic=True)
    paid = accept_guarantors_and_pay(out, ev, app, member, system, locked, snap) if ev.outcome == "approve" else None
    return committed_reply(ev, app, paid.loan if paid else None), run, paid


def stored_reply(db: Session, actor_id: int, key: str, wanted: str) -> dict:
    row = db.scalar(select(IdempotencyKey).where(IdempotencyKey.actor_user_id == actor_id, IdempotencyKey.key == key))
    try:
        return idempotency.stored_reply(db, row, wanted)
    except idempotency.KeyReused as e:
        raise CannotCommit(str(e)) from None


def key_row(actor_id: int, key: str, wanted: str, reply) -> IdempotencyKey:
    row = IdempotencyKey(actor_user_id=actor_id, key=key, request_hash=wanted)
    idempotency.finish(row, reply)
    return row


def accepted_as_well(db: Session, member: Member, fresh: Evaluation, snap: Snapshot) -> Evaluation:
    """Taking a reduced offer at once: the engine again at that amount, with no more questions."""
    request = fresh.request
    overrides = {**fresh.overrides, "accepted_amount_kes": fresh.amount_kes}
    return decisions.evaluate(db, member, LoanRequest(request.amount_kes, request.purpose,
                                                      fresh.facts.term_months or TERM_FOR_THE_RECORD),
                              overrides, final=True, snapshot=snap, reuse=fresh)


def record(db: Session, evaluation: Evaluation, idempotency_key: str, actor: User, expected: tuple[str, int | None] | None = None,
           accept_key: str | None = None, accepted: Evaluation | None = None,
           along: Callable[[Batch, Recorded], Any] | None = None) -> Recorded:
    """Write the decision, once per key: a repeat gets the first reply and pays out nothing.
    expected is (outcome, amount) as the member was told, by default the evaluation's own.

    accept_key: a reduced offer is taken in the same breath, and accepted is that evaluation as
    the member was told it. along: anything else to keep with it, added to the batch.

    Commits, or rolls back and raises CannotCommit, having written nothing."""
    request, overrides = evaluation.request, evaluation.overrides
    wanted_hash = idempotency.request_hash("self_service.commit",
                                           {"member": evaluation.member_id, "amount_kes": request.amount_kes,
                                            "purpose": request.purpose, "term_months": request.term_months,
                                            "overrides": overrides})
    try:
        member = db.get(Member, evaluation.member_id)
        locked = ledger.lock_for_decision(db, member.id, {"loan_applications": 1, **rows_for(*(e for e in (evaluation, accepted) if e))})
        keys = (idempotency_key,) if accept_key is None else (idempotency_key, accept_key)
        snap = decisions.read_snapshot(db, member, keys=keys, key_owner_id=actor.id)
        if idempotency_key in snap.keys_used:
            reply = stored_reply(db, actor.id, idempotency_key, wanted_hash)
            db.rollback()
            return Recorded(reply, reply["application_id"])
        fresh = decisions.evaluate(db, member, request, overrides, refer_reason=evaluation.facts.refer_reason, snapshot=snap,
                                   reuse=evaluation)
        wanted = expected or (evaluation.outcome, evaluation.amount_kes)
        if (fresh.outcome, fresh.amount_kes) != wanted:
            raise DecisionChanged(fresh)
        if fresh.outcome == "clarify":
            raise CannotCommit("There are questions still to answer before this can be decided.")
        if snap.open_application:
            raise CannotCommit("You already have an application being decided. Please finish that one first.")
        taken = accepted_as_well(db, member, fresh, snap) if accept_key and fresh.outcome == "approve_reduced" else None
        if taken is not None and accepted is not None and (taken.outcome, taken.amount_kes) != (accepted.outcome, accepted.amount_kes):
            raise DecisionChanged(fresh)

        out = Batch(db, locked.ids)
        term = fresh.facts.term_months or TERM_FOR_THE_RECORD
        savings = fresh.facts.deposits_kes if fresh.facts.deposits_kes is not None else fresh.facts.declared_savings_kes
        app = LoanApplication(member_id=member.id, amount_requested_kes=request.amount_kes, purpose=request.purpose,
                              term_months=term, sacco_savings_kes=max(savings, 0),
                              savings_self_declared=fresh.facts.deposits_kes is None, channel="self_service",
                              status="draft", created_by=actor.id)
        out.give_id(app)
        audit.record(out, actor, "application.create", "loan_application", app.id, status="draft", member_id=member.id,
                     amount_requested_kes=request.amount_kes, via="self_service")
        made, run, paid = apply_outcome(out, fresh, app, member, "commit", locked, snap)
        out.add(key_row(actor.id, idempotency_key, wanted_hash, made))
        reply, final = made, fresh
        if taken is not None:
            reply, run, paid = apply_outcome(out, taken, app, member, "acceptance", locked, snap)
            out.add(key_row(actor.id, accept_key, idempotency.request_hash("self_service.accept", {"application": app.id}),
                            reply))
            final = taken
        out.add(app)        # last, holding where it ended up: a row cannot be written twice in one statement
        done = Recorded(jsonable_encoder(reply), app.id, run.id, paid, snap, final)
        if along is not None:
            along(out, done)
        out.send()
        db.commit()
        return done
    except IntegrityError as e:
        db.rollback()
        # A second request with this key, for someone else's locks: it came first, and stands.
        if db.scalar(select(IdempotencyKey.id).where(IdempotencyKey.actor_user_id == actor.id,
                                                     IdempotencyKey.key == idempotency_key)) is not None:
            reply = stored_reply(db, actor.id, idempotency_key, wanted_hash)
            db.rollback()
            return Recorded(reply, reply["application_id"])
        raise CannotCommit("That could not be saved just now. Please try again.") from e
    except ledger.LedgerError as e:
        db.rollback()
        raise CannotCommit("That could not be saved just now. Please try again.") from e
    except CannotCommit:
        db.rollback()
        raise


def commit(db: Session, evaluation: Evaluation, idempotency_key: str, actor: User,
           expected: tuple[str, int | None] | None = None) -> dict:
    """record(), for a caller that only wants the reply."""
    return record(db, evaluation, idempotency_key, actor, expected).reply


def accept_offer(db: Session, app: LoanApplication, idempotency_key: str, actor: User) -> dict:
    """The member takes the reduced offer. The engine runs again at that amount, with
    no more questions: an approval pays out; anything else goes where it says, recorded
    the same way, because a capacity can have been spent since the offer was made."""
    wanted = idempotency.request_hash("self_service.accept", {"application": app.id})
    try:
        member = db.get(Member, app.member_id)
        previous = answers_on_record(app.interview.assessment)
        offered = app.interview.decision.approved_amount_kes
        overrides = {**previous, "accepted_amount_kes": offered}
        db.commit()     # what was read so far was only to find the application: nothing is held across this
        locked = ledger.lock_for_decision(db, member.id)
        snap = decisions.read_snapshot(db, member, keys=(idempotency_key,), key_owner_id=actor.id)
        if idempotency_key in snap.keys_used:
            reply = stored_reply(db, actor.id, idempotency_key, wanted)
            db.rollback()
            return reply
        db.refresh(app)
        if app.status != "offered":
            raise CannotCommit("This offer is no longer open.")
        request = LoanRequest(app.amount_requested_kes, app.purpose, app.term_months)
        fresh = decisions.evaluate(db, member, request, overrides, final=True, snapshot=snap)
        out = Batch(db, reserve_ids(db, rows_for(fresh)))
        made, _, _ = apply_outcome(out, fresh, app, member, "acceptance", locked, snap)
        out.add(key_row(actor.id, idempotency_key, wanted, made))
        out.send()
        db.commit()
        return jsonable_encoder(made)
    except (CannotCommit, ledger.LedgerError, IntegrityError) as e:
        db.rollback()
        if isinstance(e, CannotCommit):
            raise
        raise CannotCommit("That could not be saved just now. Please try again.") from e


def request_review(db: Session, app: LoanApplication, idempotency_key: str, actor: User) -> dict:
    """"Ask an officer to review this": a referral, recorded like any automatic decision,
    with the model scored afresh on the same answers. A loan already out stays out, and
    the application still points at the decision that paid it, so its reversal window is
    as it was; an officer can reverse or call the member from the new row. A reduced offer
    closes, and an application that was turned away is open again, with an officer."""
    try:
        row, stored = idempotency.claim(db, actor, idempotency_key, "self_service.review", {"application": app.id})
    except idempotency.KeyReused as e:
        raise CannotCommit(str(e)) from None
    if row is None:
        return stored
    try:
        member = db.get(Member, app.member_id)
        db.refresh(app)
        if app.status == "reversed":
            raise CannotCommit("This loan has been reversed, so there is nothing left to review.")
        d = app.interview.decision if app.interview is not None else None
        asked_before = db.scalar(select(SelfServiceRun.id).where(SelfServiceRun.application_id == app.id,
                                                                 SelfServiceRun.trigger == "review").limit(1))
        if (d is None or d.outcome == "refer" or asked_before is not None or app.status == "interview_pending"
                or not loans.held_by_automatic_decision(app)):
            raise CannotCommit("This application is already with a loan officer.")
        paid_out = db.scalar(select(LoanAccount.id).where(LoanAccount.application_id == app.id)) is not None
        overrides = answers_on_record(app.interview.assessment)
        request = LoanRequest(app.amount_requested_kes, app.purpose, app.term_months)
        fresh = decisions.evaluate(db, member, request, overrides, refer_reason="review_requested")
        # The reasons a member cannot apply yet come first in the policy; this is a person looking anyway.
        settled = decisions.Settled("refer", "review_requested")
        ev = replace(fresh, settled=settled, questions=[],
                     reason=member_text.decision_reason("review_requested", {}),
                     trace={**fresh.trace, "outcome": "refer", "reason_code": "review_requested", "amount_kes": None})
        out = Batch(db, reserve_ids(db, rows_for(ev)))
        record_run(out, ev, app, member, SystemActor(fresh.snapshot.system_user_id), "review", move_application=not paid_out)
        out.send()
        if not paid_out:
            loans.set_status(db, app, "decided", actor, review_requested=True)
        audit.record(db, actor, "self_service.review_request", "loan_application", app.id, loan_paid_out=paid_out)
        # The loan already out has an officer's reversal, not an interview, ahead of it.
        reply = idempotency.finish(row, committed_reply(ev, app, None).model_copy(update={"can_book_interview": not paid_out}))
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
        reasons=member_text.reasons(ev.risk_class, ev.contributions) if final else [],
        policy_version=ev.policy_version, consent_version=templates.consent_version(),
        consent_text=templates.text_of("CONSENT"))


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
    if body.consent_version != templates.consent_version():
        raise HTTPException(422, "consent_version: an automatic decision needs consent to the current wording; "
                                 "it comes with an evaluation")
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


@router.post("/self-service/applications/{application_id}/review", status_code=201,
             response_model=s.SelfServiceCommitted)
def self_service_review(application_id: int, key: IdemKey, db: Session = Depends(get_db),
                        user: User = Depends(require_member)):
    """"Ask an officer to review this": on any automatic outcome but a referral, which is
    already with an officer."""
    app = my_offer(db, user, application_id)
    limited(commits, f"member:{app.member_id}")
    try:
        return JSONResponse(request_review(db, app, key, user), status_code=201)
    except decisions.ClassifierMissing:
        raise HTTPException(503, "We could not look at this just now. Please try again later.") from None
    except CannotCommit as e:
        raise HTTPException(409, str(e)) from None


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
