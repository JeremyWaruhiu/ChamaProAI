"""A member's standing with the SACCO: "My SACCO" for the member, the same page
for an officer, the profile's edit, confirm and verify, and standing guarantors
offered when an application needs guarantors.

A member's page is built field by field. It says whether each of their guarantors
has capacity, never how much: that would show one member another's savings. Staff
see the figures. A fixed number of queries per page, however many rows there are.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from . import audit, comparator, ledger, loans, profiles
from . import schemas as s
from .auth import require_member, require_officer
from .db import (PROFILE_GROUPS, Guarantor, GuarantorPledge, LoanAccount, LoanApplication, Member,
                 MemberProfile, User, get_db)
from .pilot import required_member

ERRORS = {code: {"model": s.Error} for code in (401, 403, 404, 409, 422)}
router = APIRouter(prefix="/api", responses=ERRORS)

STANDING_GUARANTOR = "standing guarantor"


# --- The page ---------------------------------------------------------------------------

def profile_out(db: Session, m: Member, staff: bool) -> s.ProfileOut | None:
    p: MemberProfile | None = m.profile
    known = profiles.profile_features(db, m)
    provenance = known.provenance if staff else None
    if p is None:
        return s.ProfileOut(age=profiles.age_of(m), sex=m.sex, education=m.education,
                            marital_status=m.marital_status, provenance=provenance, groups={})
    groups = {g: s.ProfileGroupOut(source=getattr(p, f"{g}_source"), updated_at=getattr(p, f"{g}_updated_at"),
                                   verified=getattr(p, f"{g}_verified_at") is not None)
              for g in PROFILE_GROUPS}
    checks = None if not staff else {
        g: s.ProfileCheck(by=getattr(p, f"{g}_verified_by"), at=getattr(p, f"{g}_verified_at"))
        for g in PROFILE_GROUPS if getattr(p, f"{g}_verified_at") is not None}
    return s.ProfileOut(
        **{f: getattr(p, f) for g in PROFILE_GROUPS.values() for f in g}, age=profiles.age_of(m),
        confirmed_at=p.confirmed_at, days_since_confirmed=known.days_since_confirmed,
        provenance=provenance, groups=groups, checks=checks)


def accounts_out(db: Session, m: Member) -> list[s.AccountOut]:
    balances, entries = ledger.balances(db, m.id), ledger.last_entries(db, m.id)
    return [s.AccountOut(kind=kind, balance_kes=balance,
                         entries=[s.EntryOut.model_validate(e) for e in entries[kind]])
            for kind, balance in balances.items()]


def loans_out(db: Session, m: Member) -> list[s.LoanOut]:
    rows = db.scalars(select(LoanAccount).where(LoanAccount.member_id == m.id)
                      .order_by(LoanAccount.disbursed_on.desc(), LoanAccount.id.desc())).all()
    paid = ledger.paid_on_loans(db, [x.id for x in rows])
    return [s.LoanOut(id=x.id, application_id=x.application_id, principal_kes=x.principal_kes,
                      disbursed_on=x.disbursed_on, term_months=x.term_months,
                      monthly_instalment_kes=x.monthly_instalment_kes, status=x.status,
                      paid_kes=paid.get(x.id, 0),
                      days_in_arrears=ledger.days_in_arrears(x, paid.get(x.id, 0)))
            for x in rows]


def sacco_view(db: Session, m: Member, staff: bool) -> s.SaccoView:
    """A fixed number of queries, none per row: the pledges come with their members,
    and capacity is asked for everyone at once."""
    mine = db.scalars(select(GuarantorPledge).where(GuarantorPledge.borrower_member_id == m.id,
                                                    GuarantorPledge.status == "active")
                      .options(joinedload(GuarantorPledge.guarantor))
                      .order_by(GuarantorPledge.id)).all()
    theirs = db.scalars(select(GuarantorPledge).where(GuarantorPledge.guarantor_member_id == m.id,
                                                      GuarantorPledge.status == "active")
                        .options(joinedload(GuarantorPledge.borrower))
                        .order_by(GuarantorPledge.id)).all()
    caps = ledger.capacities(db, {m.id, *(p.guarantor_member_id for p in mine)})
    guaranteed = ledger.active_guarantees(db, m.id)
    own = caps[m.id]
    return s.SaccoView(
        member_id=m.id, member_no=m.member_no, full_name=m.full_name, joined_on=m.joined_on,
        profile=profile_out(db, m, staff), accounts=accounts_out(db, m),
        guarantee=s.GuaranteeOut(deposits_kes=own.deposits_kes, guaranteed_kes=own.guaranteed_kes,
                                 committed_kes=own.committed_kes, capacity_kes=own.capacity_kes),
        my_guarantors=[s.PledgeOut(
            id=p.id, member_no=p.guarantor.member_no, full_name=p.guarantor.full_name,
            created_at=p.created_at, has_capacity=caps[p.guarantor_member_id].available_kes > 0,
            capacity_kes=caps[p.guarantor_member_id].capacity_kes if staff else None) for p in mine],
        i_guarantee=[s.PledgeOut(
            id=p.id, member_no=p.borrower.member_no, full_name=p.borrower.full_name,
            created_at=p.created_at, guaranteed_kes=guaranteed.get(p.borrower_member_id, 0)) for p in theirs],
        loans=loans_out(db, m))


def member_or_404(db: Session, member_id: int) -> Member:
    return loans.get_or_404(db, Member, member_id, "member")


@router.get("/me/sacco", response_model=s.SaccoView)
def my_sacco(db: Session = Depends(get_db), user: User = Depends(require_member)):
    return sacco_view(db, required_member(db, user), staff=False)


@router.get("/members/{member_id}/sacco", response_model=s.SaccoView)
def member_sacco(member_id: int, db: Session = Depends(get_db), _: User = Depends(require_officer)):
    return sacco_view(db, member_or_404(db, member_id), staff=True)


# --- The profile ------------------------------------------------------------------------

@router.post("/me/profile", status_code=201, response_model=s.SaccoView)
def register_profile(body: s.ProfileFields, db: Session = Depends(get_db),
                     user: User = Depends(require_member)):
    """The registration form, shown once after sign-up. Later changes are edits."""
    m = required_member(db, user)
    if m.profile is not None:
        raise HTTPException(409, "your profile already exists; send changes as an edit")
    profiles.save_profile(db, m, body.model_dump(exclude_unset=True), "registration", user)
    db.commit()
    return sacco_view(db, m, staff=False)


@router.patch("/me/profile", response_model=s.SaccoView)
def edit_my_profile(body: s.ProfileFields, db: Session = Depends(get_db),
                    user: User = Depends(require_member)):
    """Saved straight away as member_update, unverified, until an officer verifies it."""
    m = required_member(db, user)
    profiles.save_profile(db, m, body.model_dump(exclude_unset=True), "member_update", user)
    db.commit()
    return sacco_view(db, m, staff=False)


@router.post("/me/profile/confirm", response_model=s.SaccoView)
def confirm_my_profile(db: Session = Depends(get_db), user: User = Depends(require_member)):
    m = required_member(db, user)
    profiles.confirm_profile(db, m, user)
    db.commit()
    return sacco_view(db, m, staff=False)


@router.post("/members/{member_id}/profile/verify", response_model=s.SaccoView)
def verify_member_profile(member_id: int, body: s.ProfileVerify | None = None, db: Session = Depends(get_db),
                          user: User = Depends(require_officer)):
    m = member_or_404(db, member_id)
    profiles.verify_profile(db, m, user, body.groups if body else None)
    db.commit()
    return sacco_view(db, m, staff=True)


# --- Standing guarantors for an application --------------------------------------------------

def share_of(app: LoanApplication) -> int:
    """What each guarantor is asked to cover: the loan split evenly, rounded up."""
    d = app.interview.decision
    required = d.guarantors_required or comparator.MIN_GUARANTORS
    return -(-(d.approved_amount_kes or app.amount_requested_kes) // required)


def offers_for(db: Session, app: LoanApplication) -> tuple[int, list[GuarantorPledge]]:
    """(the share, the borrower's active pledges from members who can cover it and
    are not already on this application)."""
    share = share_of(app)
    pledges = db.scalars(select(GuarantorPledge).where(GuarantorPledge.borrower_member_id == app.member_id,
                                                       GuarantorPledge.status == "active")
                         .options(joinedload(GuarantorPledge.guarantor))
                         .order_by(GuarantorPledge.id)).all()
    caps = ledger.capacities(db, {p.guarantor_member_id for p in pledges})
    taken = {g.member_id for g in app.guarantors if g.status != "rejected"}
    return share, [p for p in pledges if p.guarantor_member_id not in taken and p.guarantor.phone
                   and caps[p.guarantor_member_id].available_kes >= share]


@router.get("/me/applications/{application_id}/guarantor-offers", response_model=s.GuarantorOffers)
def guarantor_offers(application_id: int, db: Session = Depends(get_db),
                     user: User = Depends(require_member)):
    app = loans.own_application(db, user, application_id)
    if app.status != "guarantor_required":
        return s.GuarantorOffers(share_kes=0, needed=0, offers=[])
    share, pledges = offers_for(db, app)
    d = app.interview.decision
    needed = (d.guarantors_required or comparator.MIN_GUARANTORS) - loans.counting(app)
    return s.GuarantorOffers(share_kes=share, needed=needed, offers=[
        s.GuarantorOffer(pledge_id=p.id, full_name=p.guarantor.full_name,
                         member_no=p.guarantor.member_no) for p in pledges])


@router.post("/me/applications/{application_id}/guarantors/pledged", status_code=201,
             response_model=s.MyApplication)
def use_pledges(application_id: int, body: s.UsePledges, db: Session = Depends(get_db),
                user: User = Depends(require_member)):
    """Turn offered pledges into the ordinary guarantor rows, for the same review
    as typed ones. Fewer than needed is fine: the rest can be pledged or typed."""
    app = loans.own_application(db, user, application_id)
    if app.status != "guarantor_required":
        raise HTTPException(409, "guarantors can be added only when the application asks for them")
    d = app.interview.decision
    required = d.guarantors_required or comparator.MIN_GUARANTORS
    if len(set(body.pledge_ids)) != len(body.pledge_ids):
        raise HTTPException(422, "pledge_ids: each guarantor can be used once")
    if len(body.pledge_ids) > required - loans.counting(app):
        raise HTTPException(422, f"pledge_ids: {required - loans.counting(app)} guarantor(s) needed")
    ledger.lock_members(db, db.scalars(select(GuarantorPledge.guarantor_member_id)
                                       .where(GuarantorPledge.id.in_(body.pledge_ids))))
    share, offers = offers_for(db, app)
    offered = {p.id: p for p in offers}
    if any(i not in offered for i in body.pledge_ids):
        raise HTTPException(409, "one of those guarantors can no longer cover this loan; "
                                 "choose again or add another guarantor")
    for pledge_id in body.pledge_ids:
        g = offered[pledge_id].guarantor
        row = Guarantor(application=app, full_name=g.full_name, member_no=g.member_no, phone=g.phone,
                        relationship_=STANDING_GUARANTOR, amount_guaranteed_kes=share, status="pending",
                        member_id=g.id, pledge_id=pledge_id)
        db.add(row)
        db.flush()
        audit.record(db, user, "guarantor.submit", "guarantor", row.id, application_id=app.id,
                     pledge_id=pledge_id)
    db.flush()
    db.refresh(app)
    if loans.counting(app) >= required:
        loans.set_status(db, app, "guarantor_submitted", user)
    db.commit()
    db.refresh(app)
    return loans.my_view(db, app)


