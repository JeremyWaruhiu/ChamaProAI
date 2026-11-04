"""Ledger operations over HTTP, for officers and admins. Every write is audited and
needs an Idempotency-Key header, and a repeat of the key gets the first reply and moves
nothing. What the rules are is in ledger.py; this is who may ask, and in what order the
rows are locked. The audit log gets ids and field names: it cannot be erased, and the
entry itself says the amount.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from chamapro import config

from . import audit, idempotency, ledger, loans
from . import schemas as s
from .auth import require_officer
from .db import AccountEntry, GuarantorPledge, LoanAccount, LoanApplication, Member, User, get_db, utcnow

ERRORS = {code: {"model": s.Error} for code in (401, 403, 404, 409, 422)}
router = APIRouter(prefix="/api", responses=ERRORS)

IdemKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=64,
                                description="The same key sends the same request once: use a new one per action")]


def entry_posted(db: Session, member_id: int, kind: str, entry: AccountEntry) -> s.EntryPosted:
    return s.EntryPosted(entry=s.EntryOut.model_validate(entry), account=kind,
                         balance_kes=ledger.balances(db, member_id)[kind])


def loan_out(db: Session, loan: LoanAccount) -> s.LoanOut:
    paid = ledger.paid_on_loans(db, [loan.id]).get(loan.id, 0)
    return s.LoanOut(id=loan.id, application_id=loan.application_id, principal_kes=loan.principal_kes,
                     disbursed_on=loan.disbursed_on, term_months=loan.term_months,
                     monthly_instalment_kes=loan.monthly_instalment_kes, status=loan.status, paid_kes=paid,
                     days_in_arrears=ledger.days_in_arrears(loan, paid))


def member_or_404(db: Session, member_id: int) -> Member:
    return loans.get_or_404(db, Member, member_id, "member")


# --- Deposits and withdrawals -----------------------------------------------------------

def post(db: Session, user: User, member: Member, kind: str, entry_type: str, amount: int, reference: str) -> s.EntryPosted:
    ledger.lock_members(db, [member.id])
    try:
        entry = ledger.post_entry(db, member.id, kind, entry_type, amount, reference, user)
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"reference {reference} has already been used on this account") from None
    audit.record(db, user, f"ledger.{entry_type}", "member", member.id, entry_id=entry.id, account=kind)
    return entry_posted(db, member.id, kind, entry)


@router.post("/members/{member_id}/deposits", status_code=201, response_model=s.EntryPosted)
def post_deposit(member_id: int, body: s.DepositPost, key: IdemKey, db: Session = Depends(get_db),
                 user: User = Depends(require_officer)):
    m = member_or_404(db, member_id)
    return idempotency.run_once(db, user, key, f"deposit:{member_id}", body.model_dump(), lambda row: post(
        db, user, m, body.account, "deposit", body.amount_kes, body.reference or f"DEP-{row.id}"))


@router.post("/members/{member_id}/withdrawals", status_code=201, response_model=s.EntryPosted)
def post_withdrawal(member_id: int, body: s.WithdrawalPost, key: IdemKey, db: Session = Depends(get_db),
                    user: User = Depends(require_officer)):
    """From share capital or the transactional account. Deposits back loans: they
    leave only as a departing member's refund."""
    m = member_or_404(db, member_id)
    return idempotency.run_once(db, user, key, f"withdrawal:{member_id}", body.model_dump(), lambda row: post(
        db, user, m, body.account, "withdrawal", -body.amount_kes, body.reference or f"WDL-{row.id}"))


@router.post("/members/{member_id}/refund-deposits", status_code=201, response_model=s.Refunded)
def refund_deposits(member_id: int, key: IdemKey, db: Session = Depends(get_db), user: User = Depends(require_officer)):
    """A departing member's whole deposits balance; refused while they guarantee or owe anything."""
    m = member_or_404(db, member_id)

    def work(row) -> s.Refunded:
        ledger.lock_members(db, [m.id])
        before = db.scalar(select(func.count(GuarantorPledge.id)).where(
            (GuarantorPledge.borrower_member_id == m.id) | (GuarantorPledge.guarantor_member_id == m.id),
            GuarantorPledge.status == "active"))
        entry = ledger.refund_deposits(db, m.id, f"REFUND-{row.id}", user)
        audit.record(db, user, "ledger.deposit_refund", "member", m.id, entry_id=entry.id, pledges_ended=before)
        return s.Refunded(entry=s.EntryOut.model_validate(entry), pledges_ended=before)
    return idempotency.run_once(db, user, key, f"refund:{member_id}", {}, work)


# --- Standing guarantors ---------------------------------------------------------------

@router.post("/members/{member_id}/pledges", status_code=201, response_model=s.PledgeState)
def add_pledge(member_id: int, body: s.PledgeCreate, key: IdemKey, db: Session = Depends(get_db),
               user: User = Depends(require_officer)):
    """The officer records that the guarantor has agreed to stand behind this member."""
    m = member_or_404(db, member_id)
    guarantor = db.scalar(select(Member).where(func.upper(Member.member_no) == body.guarantor_member_no.strip().upper()))
    if guarantor is None:
        raise HTTPException(422, f"guarantor_member_no: no member {body.guarantor_member_no}")
    if guarantor.id == m.id:
        raise HTTPException(422, "guarantor_member_no: a member cannot pledge to guarantee their own loans")

    def work(_) -> s.PledgeState:
        try:
            pledge = ledger.add_pledge(db, m.id, guarantor.id)
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, f"{guarantor.member_no} already stands as this member's guarantor") from None
        audit.record(db, user, "pledge.create", "guarantor_pledge", pledge.id, borrower_member_id=m.id,
                     guarantor_member_id=guarantor.id)
        return s.PledgeState(id=pledge.id, borrower_member_id=m.id, guarantor_member_id=guarantor.id, status="active")
    return idempotency.run_once(db, user, key, f"pledge:{member_id}", body.model_dump(), work)


@router.post("/pledges/{pledge_id}/withdraw", response_model=s.PledgeState)
def withdraw_pledge(pledge_id: int, key: IdemKey, db: Session = Depends(get_db), user: User = Depends(require_officer)):
    """Only future offers: a guarantee already given stands until its loan ends."""
    pledge = loans.get_or_404(db, GuarantorPledge, pledge_id, "pledge")

    def work(_) -> s.PledgeState:
        ledger.lock_members(db, [pledge.guarantor_member_id])
        db.refresh(pledge)
        if pledge.status != "active":
            raise HTTPException(409, f"pledge {pledge_id} has already been withdrawn")
        ledger.withdraw_pledge(pledge)
        audit.record(db, user, "pledge.withdraw", "guarantor_pledge", pledge.id)
        return s.PledgeState(id=pledge.id, borrower_member_id=pledge.borrower_member_id,
                             guarantor_member_id=pledge.guarantor_member_id, status="withdrawn")
    return idempotency.run_once(db, user, key, f"pledge-withdraw:{pledge_id}", {}, work, status_code=200)


# --- Loans ---------------------------------------------------------------------------

def locked_guarantors(db: Session, app: LoanApplication) -> None:
    """The borrower and everyone verified on the application, in the fixed order."""
    ledger.lock_members(db, {app.member_id, *(g.member_id for g in app.guarantors
                                              if g.member_id is not None and g.status == "verified")})
    db.refresh(app)


@router.post("/applications/{application_id}/payout", status_code=201, response_model=s.LoanOut)
def pay_out(application_id: int, key: IdemKey, db: Session = Depends(get_db), user: User = Depends(require_officer)):
    """Pay out an approved application to the member's transactional account."""
    app = loans.get_or_404(db, LoanApplication, application_id, "application")

    def work(_) -> s.LoanOut:
        locked_guarantors(db, app)
        if loans.mode_of(app) == "practice":
            raise HTTPException(409, f"application {app.id} is practice: a training record, no real loan")
        if db.scalar(select(LoanAccount.id).where(LoanAccount.application_id == app.id)) is not None:
            raise HTTPException(409, f"application {app.id} has already been paid out")
        d = app.interview.decision if app.interview else None
        if d is None:
            raise HTTPException(409, f"application {app.id} has no decision")
        verified = sum(g.status == "verified" for g in app.guarantors)
        if verified < (d.guarantors_required or 0):
            raise HTTPException(409, f"application {app.id} has {verified} verified guarantor(s) of "
                                     f"{d.guarantors_required} required")
        loan = ledger.pay_out(db, app, d.approved_amount_kes or app.amount_requested_kes, user)
        audit.record(db, user, "loan.pay_out", "loan_account", loan.id, application_id=app.id,
                     guarantors=verified)
        return loan_out(db, loan)
    return idempotency.run_once(db, user, key, f"payout:{application_id}", {}, work)


@router.post("/loans/{loan_id}/repayments", status_code=201, response_model=s.LoanOut)
def post_repayment(loan_id: int, body: s.RepaymentPost, key: IdemKey, db: Session = Depends(get_db),
                   user: User = Depends(require_officer)):
    """From the member's transactional account; money paid in over the counter is
    posted there as a deposit first. The last one closes the loan."""
    loan = loans.get_or_404(db, LoanAccount, loan_id, "loan")

    def work(row) -> s.LoanOut:
        ledger.lock_members(db, [loan.member_id])
        db.refresh(loan)
        if loan.status not in ledger.STILL_OWED:
            raise HTTPException(409, f"loan {loan.id} is {loan.status}; nothing is owed on it")
        left = ledger.total_due(loan) - ledger.paid_on_loans(db, [loan.id]).get(loan.id, 0)
        if body.amount_kes > left:
            raise HTTPException(422, f"amount_kes: only KSh {left:,} is left to pay on this loan")
        entry = ledger.record_repayment(db, loan, body.amount_kes, body.reference or f"RPY-{row.id}", user)
        audit.record(db, user, "ledger.loan_repayment", "loan_account", loan.id, entry_id=entry.id)
        return loan_out(db, loan)
    return idempotency.run_once(db, user, key, f"repayment:{loan_id}", body.model_dump(), work)


def reversal_deadline(loan: LoanAccount, app: LoanApplication | None) -> datetime | None:
    """Until when an automatic payout can be undone; None for one an officer made."""
    if app is None or app.channel != "self_service":
        return None
    return loan.created_at + timedelta(hours=config.REVERSAL_HOURS)


@router.post("/loans/{loan_id}/reverse", response_model=s.LoanOut)
def reverse_loan(loan_id: int, body: s.ReversalPost, key: IdemKey, db: Session = Depends(get_db),
                 user: User = Depends(require_officer)):
    """Undo a payout with compensating entries. An automatic payout only within
    REVERSAL_HOURS: after that it is a loan like any other."""
    loan = loans.get_or_404(db, LoanAccount, loan_id, "loan")

    def work(_) -> s.LoanOut:
        ledger.lock_members(db, [loan.member_id])
        db.refresh(loan)
        app = db.get(LoanApplication, loan.application_id) if loan.application_id else None
        deadline = reversal_deadline(loan, app)
        if deadline is not None and utcnow() > deadline:
            raise HTTPException(409, f"this automatic payout can be reversed for {config.REVERSAL_HOURS} hours, "
                                     "and that time has passed")
        entries = ledger.reverse_loan(db, loan, user)
        audit.record(db, user, "loan.reverse", "loan_account", loan.id, entry_ids=[e.id for e in entries],
                     application_id=loan.application_id, reason=body.reason.strip())
        if app is not None:
            loans.set_status(db, app, "reversed", user, loan_id=loan.id)
        return loan_out(db, loan)
    return idempotency.run_once(db, user, key, f"reverse:{loan_id}", body.model_dump(), work, status_code=200)
