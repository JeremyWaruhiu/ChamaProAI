"""Members, loan applications, decisions, guarantors, and a member's own view.

An application moves through these statuses; every move is an audit row,
which is also where a member's timeline comes from:

    draft -> interview_pending -> interview_complete -> assessed      (follows its interview)
    assessed -> approved | declined | decided (referred) | guarantor_required
    guarantor_required -> guarantor_submitted                         (the member submits)
    guarantor_submitted -> approved (enough verified) | guarantor_required (too many rejected)

Staff (officers and admins) see every application. A member sees only the
applications of the member record linked to their login; anyone else's is a
404, never a 403, so ids cannot be probed.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response as HTTPResponse
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import audit, comparator, member_text
from . import schemas as s
from .auth import require_member, require_officer
from .db import (AuditLog, Decision, Guarantor, Interview, LoanApplication, Member, Response,
                 User, get_db, utcnow)
from .questions import QUESTION_SETS

ERRORS = {code: {"model": s.Error} for code in (401, 403, 404, 409, 422)}
router = APIRouter(prefix="/api", responses=ERRORS)

BEFORE_ASSESSMENT = ("draft", "interview_pending", "interview_complete")
# Every outcome also has the coarse decision older rows and the statistics use.
COARSE = {"approve": "approve", "approve_with_guarantor": "approve", "approve_reduced": "approve",
          "refer": "refer", "decline": "decline"}
STATUS_AFTER = {"approve": "approved", "approve_reduced": "approved",
                "approve_with_guarantor": "guarantor_required", "refer": "decided",
                "decline": "declined"}


def get_or_404(db: Session, model, ident: int, what: str):
    row = db.get(model, ident)
    if row is None:
        raise HTTPException(404, f"{what} {ident} not found")
    return row


# --- Lifecycle -----------------------------------------------------------------

def set_status(db: Session, app: LoanApplication, new: str, actor: User | None, **details) -> None:
    if app.status == new:
        return
    audit.record(db, actor, "application.status", "loan_application", app.id,
                 **{"from": app.status, "to": new}, **details)
    app.status, app.updated_at = new, utcnow()


def application_of(db: Session, iv: Interview) -> LoanApplication | None:
    return db.scalar(select(LoanApplication).where(LoanApplication.interview_id == iv.id))


def interview_stage(db: Session, iv: Interview) -> str:
    """Where an application stands because of its interview alone."""
    if iv.status == "assessed":
        return "assessed"
    answered = db.scalar(select(func.count(Response.id)).where(Response.interview_id == iv.id)) or 0
    return "interview_complete" if answered >= len(QUESTION_SETS[iv.question_set]) \
        else "interview_pending"


def sync_with_interview(db: Session, iv: Interview, actor: User | None) -> None:
    """Move the interview's application along with it (answers recorded or
    deleted, assessment made). The caller commits."""
    app = application_of(db, iv)
    if app is not None and app.status in BEFORE_ASSESSMENT:
        set_status(db, app, interview_stage(db, iv), actor, interview_id=iv.id)


def decide(db: Session, iv: Interview, body: s.DecisionCreate, user: User) -> Decision:
    """Record the officer's decision on an interview, and move its application,
    if it has one. Only after assessment, and only once. Commits."""
    if iv.assessment is None:
        raise HTTPException(409, f"interview {iv.id} has no assessment yet; "
                                 "the decision is recorded after the officer has seen it")
    if iv.decision is not None:
        raise HTTPException(409, f"interview {iv.id} already has a decision; it is immutable")
    app = application_of(db, iv)
    outcome, amount, needed = body.chosen, body.approved_amount_kes, body.guarantors_required
    if needed is not None and outcome != "approve_with_guarantor":
        raise HTTPException(422, "guarantors_required: only used with approve_with_guarantor")
    if app is None:
        if outcome in ("approve_reduced", "approve_with_guarantor"):
            raise HTTPException(422, f"outcome: {outcome} needs a loan application; "
                                     f"interview {iv.id} has none")
        if amount is not None:
            raise HTTPException(422, f"approved_amount_kes: interview {iv.id} has no loan application")
    else:
        if app.status != "assessed":
            raise HTTPException(409, f"application {app.id} is {app.status}; "
                                     "a decision needs it assessed")
        asked = app.amount_requested_kes
        if outcome == "approve":
            if amount not in (None, asked):
                raise HTTPException(422, f"approved_amount_kes: approve is for the KSh {asked:,} "
                                         "requested; use approve_reduced for less")
            amount = asked
        elif outcome == "approve_reduced":
            if amount is None:
                raise HTTPException(422, "approved_amount_kes: required for approve_reduced")
            if amount >= asked:
                raise HTTPException(422, f"approved_amount_kes: must be below the KSh {asked:,} "
                                         "requested")
        elif outcome == "approve_with_guarantor":
            if amount is not None and amount > asked:
                raise HTTPException(422, f"approved_amount_kes: cannot exceed the KSh {asked:,} "
                                         "requested")
            amount = amount or asked
            needed = needed or comparator.MIN_GUARANTORS
        elif amount is not None:
            raise HTTPException(422, f"approved_amount_kes: not used with {outcome}")

    d = Decision(interview=iv, decision=COARSE[outcome], outcome=outcome,
                 approved_amount_kes=amount, guarantors_required=needed,
                 officer_notes=body.notes,
                 member_message=(body.member_message or "").strip() or None,
                 decided_by=user.username)
    try:
        db.add(d)
        db.flush()
        audit.record(db, user, "decision.create", "decision", d.id, interview_id=iv.id,
                     application_id=app and app.id, outcome=outcome,
                     approved_amount_kes=amount, guarantors_required=needed)
        if app is not None:
            set_status(db, app, STATUS_AFTER[outcome], user, decision_id=d.id)
        db.commit()
    except IntegrityError:  # a concurrent request recorded one first
        db.rollback()
        raise HTTPException(409, f"interview {iv.id} already has a decision; it is immutable")
    return d


def link_interview(db: Session, app: LoanApplication, interview_id: int, user: User) -> None:
    if app.status not in BEFORE_ASSESSMENT:
        raise HTTPException(409, f"application {app.id} is {app.status}; "
                                 "its interview can no longer change")
    iv = get_or_404(db, Interview, interview_id, "interview")
    other = application_of(db, iv)
    if other is not None and other.id != app.id:
        raise HTTPException(409, f"interview {iv.id} already belongs to application {other.id}")
    if iv.decision is not None:
        raise HTTPException(409, f"interview {iv.id} already has a decision of its own")
    previous, app.interview = app.interview_id, iv
    audit.record(db, user, "application.link_interview", "loan_application", app.id,
                 interview_id=iv.id, previous_interview_id=previous)
    db.flush()
    set_status(db, app, interview_stage(db, iv), user, interview_id=iv.id)


# --- Views -------------------------------------------------------------------------

def comparator_of(app: LoanApplication) -> s.Comparator | None:
    a = app.interview and app.interview.assessment
    return comparator.evaluate(app, a.risk_class) if a else None


def timeline(db: Session, app: LoanApplication) -> list[s.TimelineEntry]:
    rows = db.scalars(select(AuditLog)
                      .where(AuditLog.entity == "loan_application", AuditLog.entity_id == app.id,
                             AuditLog.action.in_(("application.create", "application.status")))
                      .order_by(AuditLog.id))
    out = []
    for r in rows:
        status = r.details.get("status" if r.action == "application.create" else "to")
        if status in member_text.STATUS_LABEL:
            out.append(s.TimelineEntry(status=status, label=member_text.STATUS_LABEL[status],
                                       at=r.created_at))
    return out


def summary(app: LoanApplication) -> s.ApplicationSummary:
    iv = app.interview
    return s.ApplicationSummary(
        id=app.id, member_id=app.member_id, member_no=app.member.member_no,
        member_name=app.member.full_name, amount_requested_kes=app.amount_requested_kes,
        term_months=app.term_months, status=app.status, interview_id=app.interview_id,
        risk_class=iv.assessment.risk_class if iv and iv.assessment else None,
        outcome=iv.decision.effective_outcome if iv and iv.decision else None,
        created_at=app.created_at, updated_at=app.updated_at)


def guarantor_out(g: Guarantor) -> s.GuarantorOut:
    return s.GuarantorOut(id=g.id, full_name=g.full_name, member_no=g.member_no, phone=g.phone,
                          relationship=g.relationship_,
                          amount_guaranteed_kes=g.amount_guaranteed_kes, status=g.status,
                          submitted_at=g.submitted_at,
                          verified_by=g.verifier.username if g.verifier else None,
                          verified_at=g.verified_at)


def detail(db: Session, app: LoanApplication) -> s.ApplicationDetail:
    iv = app.interview
    assessment = None
    if iv and iv.assessment:
        assessment = s.AssessmentOut.model_validate(iv.assessment)
        assessment.comparator = comparator_of(app)
    return s.ApplicationDetail(
        **summary(app).model_dump(), purpose=app.purpose, sacco_savings_kes=app.sacco_savings_kes,
        created_by=app.creator.username, member=s.MemberOut.model_validate(app.member),
        interview=s.InterviewBrief.model_validate(iv, from_attributes=True) if iv else None,
        assessment=assessment,
        decision=s.DecisionOut.model_validate(iv.decision) if iv and iv.decision else None,
        comparator=assessment.comparator if assessment else None,
        guarantors=[guarantor_out(g) for g in app.guarantors], timeline=timeline(db, app))


def counting(app: LoanApplication) -> int:
    """Guarantors that still count towards the requirement."""
    return sum(g.status in ("pending", "verified") for g in app.guarantors)


def my_view(db: Session, app: LoanApplication) -> s.MyApplication:
    """What a member may see of their own application. Built field by field:
    nothing from the assessment but the wording of its top reasons."""
    iv = app.interview
    d = iv.decision if iv else None
    still = 0
    if d is not None and app.status == "guarantor_required":
        still = max((d.guarantors_required or 0) - counting(app), 0)
    reasons = []
    if d is not None and iv.assessment is not None:
        reasons = member_text.reasons(iv.assessment.risk_class, iv.assessment.contributions)
    outcome = d.effective_outcome if d else None
    message = None
    if d is not None:
        message = d.member_message or member_text.default_message(
            outcome, d.approved_amount_kes, d.guarantors_required)
    return s.MyApplication(
        id=app.id, amount_requested_kes=app.amount_requested_kes, purpose=app.purpose,
        term_months=app.term_months, status=app.status,
        status_label=member_text.STATUS_LABEL[app.status], created_at=app.created_at,
        updated_at=app.updated_at, timeline=timeline(db, app), outcome=outcome,
        approved_amount_kes=d.approved_amount_kes if d else None,
        guarantors_required=d.guarantors_required if d else None,
        guarantors_still_needed=still, member_message=message, reasons=reasons,
        guarantors=[s.MemberGuarantorOut(full_name=g.full_name, member_no=g.member_no,
                                         phone=g.phone, relationship=g.relationship_,
                                         amount_guaranteed_kes=g.amount_guaranteed_kes,
                                         status=g.status, submitted_at=g.submitted_at)
                    for g in app.guarantors])


# --- Members (staff) ---------------------------------------------------------------

@router.get("/members", response_model=list[s.MemberOut])
def list_members(q: str | None = Query(None, max_length=200, description="Name or member number"),
                 limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0),
                 db: Session = Depends(get_db), _: User = Depends(require_officer)):
    stmt = select(Member).order_by(Member.full_name, Member.id).limit(limit).offset(offset)
    if q and q.strip():
        term = q.strip().lower()
        stmt = stmt.where(or_(func.lower(Member.full_name).contains(term, autoescape=True),
                              func.lower(Member.member_no).contains(term, autoescape=True)))
    return [s.MemberOut.model_validate(m) for m in db.scalars(stmt)]


@router.post("/members", status_code=201, response_model=s.MemberOut)
def create_member(body: s.MemberCreate, db: Session = Depends(get_db),
                  user: User = Depends(require_officer)):
    m = Member(**body.model_dump())
    try:
        db.add(m)
        db.flush()
        # ids and field names only: the audit log cannot be erased, personal data can
        audit.record(db, user, "member.create", "member", m.id)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"member number {body.member_no} already exists")
    return s.MemberOut.model_validate(m)


@router.get("/members/{member_id}", response_model=s.MemberOut)
def get_member(member_id: int, db: Session = Depends(get_db), _: User = Depends(require_officer)):
    return s.MemberOut.model_validate(get_or_404(db, Member, member_id, "member"))


@router.patch("/members/{member_id}", response_model=s.MemberOut)
def update_member(member_id: int, body: s.MemberUpdate, db: Session = Depends(get_db),
                  user: User = Depends(require_officer)):
    m = get_or_404(db, Member, member_id, "member")
    changes = body.model_dump(exclude_unset=True)
    for field in ("member_no", "full_name", "joined_on"):
        if field in changes and changes[field] is None:
            raise HTTPException(422, f"{field}: cannot be removed")
    changed = sorted(k for k, v in changes.items() if getattr(m, k) != v)
    for k in changed:
        setattr(m, k, changes[k])
    if changed:
        audit.record(db, user, "member.update", "member", m.id, fields=changed)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"member number {changes.get('member_no')} already exists")
    return s.MemberOut.model_validate(m)


@router.delete("/members/{member_id}", status_code=204)
def delete_member(member_id: int, db: Session = Depends(get_db),
                  user: User = Depends(require_officer)):
    m = get_or_404(db, Member, member_id, "member")
    if m.applications:
        raise HTTPException(409, f"member {member_id} has loan applications; they are kept")
    db.delete(m)
    audit.record(db, user, "member.delete", "member", member_id)
    db.commit()
    return HTTPResponse(status_code=204)


# --- Applications (staff) ------------------------------------------------------------

@router.post("/applications", status_code=201, response_model=s.ApplicationDetail)
def create_application(body: s.ApplicationCreate, db: Session = Depends(get_db),
                       user: User = Depends(require_officer)):
    member = db.get(Member, body.member_id)
    if member is None:
        raise HTTPException(422, f"member_id: member {body.member_id} not found")
    app = LoanApplication(member_id=member.id, amount_requested_kes=body.amount_requested_kes,
                          purpose=body.purpose, term_months=body.term_months,
                          sacco_savings_kes=body.sacco_savings_kes, status="draft",
                          created_by=user.id)
    db.add(app)
    db.flush()
    audit.record(db, user, "application.create", "loan_application", app.id, status="draft",
                 member_id=member.id, amount_requested_kes=app.amount_requested_kes)
    if body.interview_id is not None:
        link_interview(db, app, body.interview_id, user)
    try:
        db.commit()
    except IntegrityError:  # the interview was linked elsewhere meanwhile
        db.rollback()
        raise HTTPException(409, f"interview {body.interview_id} already belongs to an application")
    return detail(db, app)


@router.get("/applications", response_model=list[s.ApplicationSummary])
def list_applications(status: s.ApplicationStatus | None = None, member_id: int | None = None,
                      limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
                      db: Session = Depends(get_db), _: User = Depends(require_officer)):
    stmt = select(LoanApplication).order_by(LoanApplication.created_at.desc(),
                                            LoanApplication.id.desc()).limit(limit).offset(offset)
    if status is not None:
        stmt = stmt.where(LoanApplication.status == status)
    if member_id is not None:
        stmt = stmt.where(LoanApplication.member_id == member_id)
    return [summary(a) for a in db.scalars(stmt)]


@router.get("/applications/{application_id}", response_model=s.ApplicationDetail)
def get_application(application_id: int, db: Session = Depends(get_db),
                    _: User = Depends(require_officer)):
    return detail(db, get_or_404(db, LoanApplication, application_id, "application"))


@router.put("/applications/{application_id}/interview", response_model=s.ApplicationDetail)
def set_interview(application_id: int, body: s.LinkInterview, db: Session = Depends(get_db),
                  user: User = Depends(require_officer)):
    app = get_or_404(db, LoanApplication, application_id, "application")
    link_interview(db, app, body.interview_id, user)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"interview {body.interview_id} already belongs to an application")
    return detail(db, app)


@router.post("/applications/{application_id}/decision", status_code=201,
             response_model=s.ApplicationDetail)
def decide_application(application_id: int, body: s.DecisionCreate,
                       db: Session = Depends(get_db), user: User = Depends(require_officer)):
    app = get_or_404(db, LoanApplication, application_id, "application")
    if app.interview is None:
        raise HTTPException(409, f"application {app.id} has no interview yet")
    decide(db, app.interview, body, user)
    db.refresh(app)
    return detail(db, app)


# --- Guarantors (staff review) -------------------------------------------------------

def review(db: Session, g: Guarantor, verdict: str, user: User, reason: str | None) -> s.GuarantorOut:
    if g.status != "pending":
        raise HTTPException(409, f"guarantor {g.id} is already {g.status}")
    app = g.application
    if app.status not in ("guarantor_submitted", "guarantor_required"):
        raise HTTPException(409, f"application {app.id} is {app.status}; "
                                 "its guarantors are no longer reviewed")
    g.status, g.verified_by, g.verified_at = verdict, user.id, utcnow()
    audit.record(db, user, f"guarantor.{'verify' if verdict == 'verified' else 'reject'}",
                 "guarantor", g.id, application_id=app.id,
                 **({"reason": reason.strip()} if reason and reason.strip() else {}))
    required = app.interview.decision.guarantors_required or comparator.MIN_GUARANTORS
    verified = sum(x.status == "verified" for x in app.guarantors)
    if verified >= required:
        set_status(db, app, "approved", user, verified_guarantors=verified)
    elif counting(app) < required:
        set_status(db, app, "guarantor_required", user, verified_guarantors=verified)
    db.commit()
    db.refresh(g)
    return guarantor_out(g)


@router.post("/guarantors/{guarantor_id}/verify", response_model=s.GuarantorOut)
def verify_guarantor(guarantor_id: int, db: Session = Depends(get_db),
                     user: User = Depends(require_officer)):
    return review(db, get_or_404(db, Guarantor, guarantor_id, "guarantor"), "verified", user, None)


@router.post("/guarantors/{guarantor_id}/reject", response_model=s.GuarantorOut)
def reject_guarantor(guarantor_id: int, body: s.GuarantorReview | None = None,
                     db: Session = Depends(get_db), user: User = Depends(require_officer)):
    g = get_or_404(db, Guarantor, guarantor_id, "guarantor")
    return review(db, g, "rejected", user, body.reason if body else None)


# --- A member's own applications -------------------------------------------------------

def my_member(db: Session, user: User) -> Member | None:
    return db.scalar(select(Member).where(Member.user_id == user.id))


def own_application(db: Session, user: User, application_id: int) -> LoanApplication:
    app, member = db.get(LoanApplication, application_id), my_member(db, user)
    if app is None or member is None or app.member_id != member.id:
        raise HTTPException(404, f"application {application_id} not found")
    return app


@router.get("/me/applications", response_model=list[s.MyApplicationSummary])
def my_applications(db: Session = Depends(get_db), user: User = Depends(require_member)):
    member = my_member(db, user)
    if member is None:
        return []
    apps = db.scalars(select(LoanApplication).where(LoanApplication.member_id == member.id)
                      .order_by(LoanApplication.created_at.desc(), LoanApplication.id.desc()))
    return [s.MyApplicationSummary(id=a.id, amount_requested_kes=a.amount_requested_kes,
                                   purpose=a.purpose, term_months=a.term_months, status=a.status,
                                   status_label=member_text.STATUS_LABEL[a.status],
                                   created_at=a.created_at, updated_at=a.updated_at)
            for a in apps]


@router.get("/me/applications/{application_id}", response_model=s.MyApplication)
def my_application(application_id: int, db: Session = Depends(get_db),
                   user: User = Depends(require_member)):
    return my_view(db, own_application(db, user, application_id))


@router.post("/me/applications/{application_id}/guarantors", status_code=201,
             response_model=s.MyApplication)
def submit_guarantors(application_id: int, body: s.GuarantorSubmit,
                      db: Session = Depends(get_db), user: User = Depends(require_member)):
    app = own_application(db, user, application_id)
    if app.status != "guarantor_required":
        raise HTTPException(409, "guarantors can be added only when the application asks for "
                                 f"them; it is: {member_text.STATUS_LABEL[app.status]}")
    d = app.interview.decision
    needed = (d.guarantors_required or comparator.MIN_GUARANTORS) - counting(app)
    if len(body.guarantors) != needed:
        raise HTTPException(422, f"guarantors: submit exactly {needed} guarantor(s)")
    numbers = [g.member_no.upper() for g in body.guarantors]
    if app.member.member_no.upper() in numbers:
        raise HTTPException(422, "guarantors: you cannot guarantee your own loan")
    taken = {g.member_no.upper() for g in app.guarantors if g.status != "rejected"}
    if len(set(numbers)) != len(numbers) or taken & set(numbers):
        raise HTTPException(422, "guarantors: each guarantor must be a different member")
    cap = d.approved_amount_kes or app.amount_requested_kes
    if any(g.amount_guaranteed_kes > cap for g in body.guarantors):
        raise HTTPException(422, f"guarantors: amount_guaranteed_kes cannot exceed the loan "
                                 f"(KSh {cap:,})")
    for g in body.guarantors:
        row = Guarantor(application=app, full_name=g.full_name, member_no=g.member_no,
                        phone=g.phone, relationship_=g.relationship,
                        amount_guaranteed_kes=g.amount_guaranteed_kes, status="pending")
        db.add(row)
        db.flush()
        audit.record(db, user, "guarantor.submit", "guarantor", row.id, application_id=app.id)
    set_status(db, app, "guarantor_submitted", user)
    db.commit()
    db.refresh(app)
    return my_view(db, app)
