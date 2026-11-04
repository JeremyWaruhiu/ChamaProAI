"""The savings ledger, issued loans and guarantee capacity.

Every figure here is computed from account_entries, which is append-only: a
balance is a sum, what a loan has been repaid is a sum, and because each entry
has its time, so is a balance on any past date. Nothing is stored that could
disagree. Each function takes many members at once where a page needs many, and
runs a fixed number of queries however many rows there are.

Three rules this module holds:

    savings for the SACCO rule  = deposits balance when the application was decided,
                                  or now if it is not decided yet; a member with no
                                  entries by then keeps the application's own figure
    guarantee capacity          = deposits balance - what they guarantee on active
                                  loans, never below zero
    available to guarantee      = capacity - guarantees on applications not yet
                                  issued, so one balance cannot back two at once. A
                                  pending row counts only if it came from the member's
                                  own pledge: anyone can type a member's number, and
                                  that must not use up their capacity

Writing: post_entry, issue_loan, record_repayment and recover_guarantee. The
caller commits. No endpoint calls them yet: the ledger is filled by the seed
script until the SACCO's own records are connected.
"""
from __future__ import annotations

import calendar
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timezone

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from chamapro import config

from .db import (AccountEntry, Decision, Guarantor, GuarantorPledge, LoanAccount, LoanApplication,
                 MemberAccount, User, nairobi_today, utcnow)

ENTRIES_SHOWN = 10
# A guarantee stops holding capacity when its application ends without a loan.
OPEN_APPLICATION = ("guarantor_required", "guarantor_submitted", "approved")
PAID_INTO_LOAN = ("loan_repayment", "guarantee_recovery")


class LedgerError(ValueError):
    """An entry the ledger will not take; nothing was written."""


def day_stamp(day: date) -> datetime:
    """09:00 at the branch on that day: the time of an entry known only by its date."""
    return datetime.combine(day, time(9), tzinfo=config.NAIROBI).astimezone(timezone.utc)


# --- Balances --------------------------------------------------------------------------

def balances(db: Session, member_id: int) -> dict[str, int]:
    """Each account's balance; an account with no entries is 0."""
    rows = db.execute(select(MemberAccount.kind, func.coalesce(func.sum(AccountEntry.amount_kes), 0))
                      .outerjoin(AccountEntry, AccountEntry.account_id == MemberAccount.id)
                      .where(MemberAccount.member_id == member_id).group_by(MemberAccount.kind))
    return {"deposits": 0, "share_capital": 0, "transactional": 0, **dict(rows.all())}


def deposits_balances(db: Session, member_ids: Iterable[int]) -> dict[int, int]:
    """Deposits balance per member; only members who have a deposits entry appear,
    which is how "this member has a ledger" is told from "this member has nothing"."""
    rows = db.execute(select(MemberAccount.member_id, func.sum(AccountEntry.amount_kes))
                      .join(AccountEntry, AccountEntry.account_id == MemberAccount.id)
                      .where(MemberAccount.member_id.in_(set(member_ids)),
                             MemberAccount.kind == "deposits")
                      .group_by(MemberAccount.member_id))
    return dict(rows.all())


def deposits_balance(db: Session, member_id: int) -> int | None:
    """The member's deposits balance; None when they have no deposits entries."""
    return deposits_balances(db, [member_id]).get(member_id)


def last_entries(db: Session, member_id: int, n: int = ENTRIES_SHOWN) -> dict[str, list[AccountEntry]]:
    """The newest n entries of each of the member's accounts, newest first: one query."""
    rank = func.row_number().over(partition_by=AccountEntry.account_id,
                                  order_by=(AccountEntry.posted_at.desc(), AccountEntry.id.desc()))
    ranked = (select(AccountEntry.id.label("id"), rank.label("rank"))
              .join(MemberAccount, MemberAccount.id == AccountEntry.account_id)
              .where(MemberAccount.member_id == member_id).subquery())
    rows = db.scalars(select(AccountEntry).join(ranked, ranked.c.id == AccountEntry.id)
                      .where(ranked.c.rank <= n)
                      .order_by(AccountEntry.posted_at.desc(), AccountEntry.id.desc()))
    out: dict[str, list[AccountEntry]] = {"deposits": [], "share_capital": [], "transactional": []}
    for e in rows:
        out[e.account_kind].append(e)
    return out


# --- The savings the SACCO rule reads --------------------------------------------------

@dataclass(frozen=True)
class RuleSavings:
    kes: int
    from_ledger: bool


def rule_savings(db: Session, apps: Iterable[LoanApplication]) -> dict[int, RuleSavings]:
    """What each application's SACCO rule reads, by application id: one query.

    An application follows the ledger until it is decided, and stays with the
    balance it was decided on, so a member's later deposits do not rewrite the
    rule beside a past decision. With no deposits entries by that time the
    member has no ledger to read, and the application's own sacco_savings_kes
    stands: all rows from before the ledger, and members not yet on it."""
    apps = list(apps)
    if not apps:
        return {}
    rows = db.execute(select(LoanApplication.id, func.sum(AccountEntry.amount_kes))
                      .join(MemberAccount, MemberAccount.member_id == LoanApplication.member_id)
                      .join(AccountEntry, AccountEntry.account_id == MemberAccount.id)
                      .outerjoin(Decision, Decision.interview_id == LoanApplication.interview_id)
                      .where(LoanApplication.id.in_([a.id for a in apps]),
                             MemberAccount.kind == "deposits",
                             Decision.id.is_(None) | (AccountEntry.posted_at <= Decision.created_at))
                      .group_by(LoanApplication.id))
    found = dict(rows.all())
    return {a.id: RuleSavings(found[a.id], True) if a.id in found
            else RuleSavings(a.sacco_savings_kes, False) for a in apps}


# --- Guarantee capacity ----------------------------------------------------------------

@dataclass(frozen=True)
class Capacity:
    deposits_kes: int
    guaranteed_kes: int     # on active loans
    committed_kes: int      # on applications not yet issued

    @property
    def capacity_kes(self) -> int:
        return max(self.deposits_kes - self.guaranteed_kes, 0)

    @property
    def available_kes(self) -> int:
        return max(self.capacity_kes - self.committed_kes, 0)


def capacities(db: Session, member_ids: Iterable[int]) -> dict[int, Capacity]:
    """Every given member's capacity: three queries."""
    ids = set(member_ids)
    if not ids:
        return {}
    deposits = deposits_balances(db, ids)
    active = dict(db.execute(select(Guarantor.member_id, func.sum(Guarantor.amount_guaranteed_kes))
                             .join(LoanAccount, LoanAccount.id == Guarantor.loan_account_id)
                             .where(Guarantor.member_id.in_(ids), Guarantor.status == "verified",
                                    LoanAccount.status == "active")
                             .group_by(Guarantor.member_id)).all())
    committed = dict(db.execute(select(Guarantor.member_id, func.sum(Guarantor.amount_guaranteed_kes))
                                .join(LoanApplication, LoanApplication.id == Guarantor.application_id)
                                .where(Guarantor.member_id.in_(ids), Guarantor.loan_account_id.is_(None),
                                       or_(Guarantor.status == "verified",
                                           and_(Guarantor.status == "pending", Guarantor.pledge_id.is_not(None))),
                                       LoanApplication.status.in_(OPEN_APPLICATION))
                                .group_by(Guarantor.member_id)).all())
    return {i: Capacity(deposits.get(i, 0), active.get(i, 0), committed.get(i, 0)) for i in ids}


def active_guarantees(db: Session, guarantor_id: int) -> dict[int, int]:
    """Borrower member id -> what this member guarantees them on active loans."""
    return dict(db.execute(select(LoanAccount.member_id, func.sum(Guarantor.amount_guaranteed_kes))
                           .join(LoanAccount, LoanAccount.id == Guarantor.loan_account_id)
                           .where(Guarantor.member_id == guarantor_id, Guarantor.status == "verified",
                                  LoanAccount.status == "active")
                           .group_by(LoanAccount.member_id)).all())


def add_pledge(db: Session, borrower_id: int, guarantor_id: int) -> GuarantorPledge:
    if borrower_id == guarantor_id:
        raise LedgerError("a member cannot pledge to guarantee their own loans")
    pledge = GuarantorPledge(borrower_member_id=borrower_id, guarantor_member_id=guarantor_id,
                             status="active")
    db.add(pledge)
    db.flush()
    return pledge


def withdraw_pledge(pledge: GuarantorPledge) -> None:
    """Only future offers: a guarantee already given stands until its loan ends."""
    pledge.status = "withdrawn"


# --- Writing -------------------------------------------------------------------------

def account_of(db: Session, member_id: int, kind: str) -> MemberAccount:
    """The member's account of this kind, opened on first use."""
    account = db.scalar(select(MemberAccount).where(MemberAccount.member_id == member_id,
                                                    MemberAccount.kind == kind))
    if account is None:
        account = MemberAccount(member_id=member_id, kind=kind)
        db.add(account)
        db.flush()
    return account


def post_entry(db: Session, member_id: int, kind: str, entry_type: str, amount_kes: int, reference: str,
               actor: User | None = None, posted_at: datetime | None = None,
               loan: LoanAccount | None = None) -> AccountEntry:
    """One entry. The database refuses a wrong sign, a withdrawal from deposits or
    a repeated reference; this refuses an entry that overdraws the account."""
    account = account_of(db, member_id, kind)
    if amount_kes < 0:
        balance = db.scalar(select(func.coalesce(func.sum(AccountEntry.amount_kes), 0))
                            .where(AccountEntry.account_id == account.id))
        if balance + amount_kes < 0:
            raise LedgerError(f"{entry_type} of KSh {-amount_kes:,} would overdraw {kind} "
                              f"(balance KSh {balance:,})")
    entry = AccountEntry(account_id=account.id, account_kind=kind, entry_type=entry_type,
                         amount_kes=amount_kes, posted_at=posted_at or utcnow(), reference=reference,
                         created_by=actor.id if actor else None, loan_account_id=loan.id if loan else None)
    db.add(entry)
    db.flush()
    return entry


def issue_loan(db: Session, member_id: int, principal_kes: int, term_months: int,
               monthly_instalment_kes: int, disbursed_on: date | None = None,
               application: LoanApplication | None = None, actor: User | None = None) -> LoanAccount:
    """The loan and its payout to the transactional account. From here on the
    application's verified guarantors hold capacity on an active loan."""
    if application is not None and application.status != "approved":
        raise LedgerError(f"application {application.id} is {application.status}; only an approved "
                          "application is paid out")
    on = disbursed_on or nairobi_today()
    loan = LoanAccount(member_id=member_id, application_id=application.id if application else None,
                       principal_kes=principal_kes, disbursed_on=on, term_months=term_months,
                       monthly_instalment_kes=monthly_instalment_kes, status="active",
                       created_by=actor.id if actor else None)
    db.add(loan)
    db.flush()
    post_entry(db, member_id, "transactional", "loan_disbursement", principal_kes, f"LOAN-{loan.id}",
               actor, day_stamp(on), loan)
    if application is not None:
        for g in application.guarantors:
            if g.status == "verified":
                g.loan_account_id = loan.id
    return loan


def paid_on_loans(db: Session, loan_ids: Iterable[int]) -> dict[int, int]:
    """What has been paid towards each loan: repayments and recoveries alike."""
    ids = set(loan_ids)
    if not ids:
        return {}
    rows = db.execute(select(AccountEntry.loan_account_id, -func.sum(AccountEntry.amount_kes))
                      .where(AccountEntry.loan_account_id.in_(ids),
                             AccountEntry.entry_type.in_(PAID_INTO_LOAN))
                      .group_by(AccountEntry.loan_account_id))
    return dict(rows.all())


def record_repayment(db: Session, loan: LoanAccount, amount_kes: int, reference: str,
                     actor: User | None = None, posted_at: datetime | None = None) -> AccountEntry:
    """A repayment from the transactional account; the last one closes the loan."""
    entry = post_entry(db, loan.member_id, "transactional", "loan_repayment", -amount_kes, reference,
                       actor, posted_at, loan)
    if paid_on_loans(db, [loan.id]).get(loan.id, 0) >= total_due(loan):
        loan.status, loan.updated_at = "repaid", utcnow()
    return entry


def recover_guarantee(db: Session, guarantor_id: int, loan: LoanAccount, amount_kes: int, reference: str,
                      actor: User | None = None, posted_at: datetime | None = None) -> AccountEntry:
    """Take a defaulted loan's shortfall from a guarantor's deposits."""
    return post_entry(db, guarantor_id, "deposits", "guarantee_recovery", -amount_kes, reference,
                      actor, posted_at, loan)


# --- Loans: computed figures ---------------------------------------------------------

def add_months(day: date, months: int) -> date:
    y, m = divmod(day.year * 12 + day.month - 1 + months, 12)
    return date(y, m + 1, min(day.day, calendar.monthrange(y, m + 1)[1]))


def total_due(loan: LoanAccount) -> int:
    return loan.monthly_instalment_kes * loan.term_months


def days_in_arrears(loan: LoanAccount, paid_kes: int, today: date | None = None) -> int:
    """Days since the oldest instalment not fully paid fell due; 0 when up to date
    or repaid. An instalment falls due each month after disbursement, and money
    received pays the oldest first."""
    today = today or nairobi_today()
    if loan.status == "repaid":
        return 0
    covered = paid_kes // loan.monthly_instalment_kes
    if covered >= loan.term_months:
        return 0
    due = add_months(loan.disbursed_on, covered + 1)
    return max((today - due).days, 0)


def sacco_loan_use(statuses: Iterable[str]) -> int:
    """The classifier's sacco_loan_use from a member's loan accounts: 0 never, 1
    all repaid, 2 still owing. A defaulted loan is still owed, not repaid."""
    statuses = set(statuses)
    if not statuses:
        return 0
    return 1 if statuses == {"repaid"} else 2


def known_to_the_sacco(db: Session, member_id: int) -> tuple[list[str], bool, bool]:
    """(loan statuses, has any ledger entry, has lost a guarantee) for the features
    the SACCO derives, in one query each for loans and entries."""
    statuses = list(db.scalars(select(LoanAccount.status).where(LoanAccount.member_id == member_id)))
    has_entry, lost = db.execute(
        select(func.count(AccountEntry.id),
               func.count(AccountEntry.id).filter(AccountEntry.entry_type == "guarantee_recovery"))
        .join(MemberAccount, MemberAccount.id == AccountEntry.account_id)
        .where(MemberAccount.member_id == member_id)).one()
    return statuses, has_entry > 0, lost > 0
