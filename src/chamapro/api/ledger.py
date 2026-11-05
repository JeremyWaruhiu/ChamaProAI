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

Writing: post_entry, issue_loan, pay_out, record_repayment, reverse_loan,
refund_deposits and recover_guarantee. The caller commits. ledger_api.py and
self_service.py call them over HTTP, the seed script directly.

Whoever is about to spend capacity or overdraw an account calls lock_members first,
so that what it reads next cannot change before it commits.
"""
from __future__ import annotations

import calendar
import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time, timezone

from sqlalchemy import Integer, String, and_, cast, func, literal, null, or_, select, text, union_all
from sqlalchemy.orm import Session

from chamapro import config

from . import audit, batch
from .db import (AccountEntry, Decision, Guarantor, GuarantorPledge, LoanAccount, LoanApplication,
                 Member, MemberAccount, User, nairobi_today, one_round_trip, utcnow)

ENTRIES_SHOWN = 10
# A guarantee stops holding capacity when its application ends without a loan.
# An offer holds nothing until it is accepted, and its guarantors are chosen then.
OPEN_APPLICATION = ("guarantor_required", "guarantor_submitted", "approved")
PAID_INTO_LOAN = ("loan_repayment", "guarantee_recovery")
STILL_OWED = ("active", "defaulted")


class LedgerError(ValueError):
    """An entry the ledger will not take; nothing was written."""


def day_stamp(day: date) -> datetime:
    """09:00 at the branch on that day: the time of an entry known only by its date."""
    return datetime.combine(day, time(9), tzinfo=config.NAIROBI).astimezone(timezone.utc)


def lock_members(db: Session, member_ids: Iterable[int]) -> None:
    """Hold these members and their accounts until the transaction ends: lowest id
    first, members before accounts, always, so two requests cannot wait on each other.
    A balance is a sum of rows that are only ever added, so the member row is what
    anyone spending it queues on. The accounts go too, for anyone opening or reading
    one directly. Take everything needed in one call.

    SQLite has no row locks and SQLAlchemy leaves FOR UPDATE out there; its one writer
    at a time is what serialises these (idempotency.claim has taken the write lock)."""
    ids = sorted(set(member_ids))
    db.execute(select(Member.id).where(Member.id.in_(ids)).order_by(Member.id).with_for_update())
    db.execute(select(MemberAccount.id).where(MemberAccount.member_id.in_(ids))
               .order_by(MemberAccount.id).with_for_update())


@dataclass
class Locked:
    members: set[int]
    accounts: dict[tuple[int, str], int]    # (member id, kind) -> account id
    ids: dict[str, list[int]]               # reserved for a Batch, by table


def _everyone_behind(borrower_id: int):
    """The borrower, and everyone with a standing pledge to them."""
    return or_(Member.id == borrower_id,
               Member.id.in_(select(GuarantorPledge.guarantor_member_id)
                             .where(GuarantorPledge.borrower_member_id == borrower_id, GuarantorPledge.status == "active")))


def lock_for_decision(db: Session, borrower_id: int, reserve: dict[str, int] | None = None) -> Locked:
    """lock_members for a decision, in one round trip: the same order and the same rows, found in
    the same statement that locks them, with its accounts and the ids it will write under.

    A statement sees the database as it was when it began, whatever it waited for, so what is
    read to decide on has to be read after this returns (decisions.read_snapshot)."""
    reserve = {t: n for t, n in (reserve or {}).items() if n > 0}
    if db.get_bind().dialect.name != "postgresql":
        with one_round_trip():
            # The write lock: SQLite's one writer at a time is what serialises these.
            db.execute(text("UPDATE members SET id = id WHERE id = :m"), {"m": borrower_id})
            members = set(db.scalars(select(Member.id).where(_everyone_behind(borrower_id))))
            accounts = db.execute(select(MemberAccount.member_id, MemberAccount.kind, MemberAccount.id)
                                  .where(MemberAccount.member_id.in_(members))).all()
            ids = batch.reserve(db, reserve)
        return Locked(members, {(m, kind): a for m, kind, a in accounts}, ids)
    who = (select(Member.id.label("id")).where(_everyone_behind(borrower_id)).order_by(Member.id)
           .with_for_update(of=Member).cte("who"))
    theirs = (select(MemberAccount.id.label("id"), MemberAccount.member_id.label("member_id"), MemberAccount.kind.label("kind"))
              .where(MemberAccount.member_id.in_(select(who.c.id))).order_by(MemberAccount.id)
              .with_for_update(of=MemberAccount).cte("theirs"))
    none_int, none_str = cast(null(), Integer), cast(null(), String)
    parts = [select(literal("member").label("what"), who.c.id.label("id"), none_int.label("member_id"), none_str.label("name")),
             select(literal("account"), theirs.c.id, theirs.c.member_id, theirs.c.kind)]
    parts += [select(literal("id"), func.nextval(f"{table}_id_seq"), none_int, literal(table))
              .select_from(func.generate_series(1, count)) for table, count in reserve.items()]
    out = Locked(set(), {}, {table: [] for table in reserve})
    for what, row_id, member_id, name in db.execute(union_all(*parts)):
        if what == "member":
            out.members.add(row_id)
        elif what == "account":
            out.accounts[member_id, name] = row_id
        else:
            out.ids[name].append(row_id)
    return out


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


def held_under_pledges(db: Session, pledge_ids: Iterable[int]) -> dict[int, int]:
    """What each pledge is already holding, on loans still owed and on applications not
    yet issued, for its ceiling. One query."""
    ids = set(pledge_ids)
    if not ids:
        return {}
    return dict(db.execute(select(Guarantor.pledge_id, func.sum(Guarantor.amount_guaranteed_kes))
                           .outerjoin(LoanAccount, LoanAccount.id == Guarantor.loan_account_id)
                           .outerjoin(LoanApplication, LoanApplication.id == Guarantor.application_id)
                           .where(Guarantor.pledge_id.in_(ids), Guarantor.status != "rejected",
                                  or_(LoanAccount.status.in_(STILL_OWED),
                                      and_(Guarantor.loan_account_id.is_(None),
                                           LoanApplication.status.in_(OPEN_APPLICATION))))
                           .group_by(Guarantor.pledge_id)).all())


def add_pledge(db: Session, borrower_id: int, guarantor_id: int, max_amount_kes: int | None = None) -> GuarantorPledge:
    if borrower_id == guarantor_id:
        raise LedgerError("a member cannot pledge to guarantee their own loans")
    pledge = GuarantorPledge(borrower_member_id=borrower_id, guarantor_member_id=guarantor_id,
                             status="active", max_amount_kes=max_amount_kes)
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


def account_id_in(out: batch.Batch, locked: Locked, member_id: int, kind: str) -> int:
    """For a Batch: the account a lock_for_decision found, or a new one in the same batch."""
    if (member_id, kind) not in locked.accounts:
        account = MemberAccount(member_id=member_id, kind=kind)
        locked.accounts[member_id, kind] = out.give_id(account)
        out.add(account)
    return locked.accounts[member_id, kind]


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


def instalment_kes(principal_kes: int, term_months: int, rate: float | None = None) -> int:
    """The monthly instalment on a reducing balance, rounded up to a shilling so that
    term x instalment always clears the loan."""
    rate = config.LOAN_INTEREST_MONTHLY if rate is None else rate
    if rate == 0:
        return math.ceil(principal_kes / term_months)
    return math.ceil(round(principal_kes * rate / (1 - (1 + rate) ** -term_months), 6))


def largest_principal(instalment_limit_kes: float, term_months: int, rate: float | None = None) -> int:
    """The largest whole-shilling loan whose instalment is within the limit."""
    rate = config.LOAN_INTEREST_MONTHLY if rate is None else rate
    if instalment_limit_kes < 1:
        return 0
    factor = term_months if rate == 0 else (1 - (1 + rate) ** -term_months) / rate
    principal = int(instalment_limit_kes * factor) + 1
    while principal > 0 and instalment_kes(principal, term_months, rate) > instalment_limit_kes:
        principal -= 1
    return principal


def issue_loan(db: Session, member_id: int, principal_kes: int, term_months: int,
               monthly_instalment_kes: int, disbursed_on: date | None = None,
               application: LoanApplication | None = None, actor: User | None = None) -> LoanAccount:
    """The loan and its payout to the transactional account. From here on the
    application's verified guarantors hold capacity on an active loan."""
    if application is not None and application.status != "approved":
        raise LedgerError(f"application {application.id} is {application.status}; only an approved "
                          "application is paid out")
    on = disbursed_on or nairobi_today()
    # A payout happening now is stamped now: 09:00 could be later today.
    stamp = day_stamp(on) if disbursed_on else utcnow()
    loan = LoanAccount(member_id=member_id, application_id=application.id if application else None,
                       principal_kes=principal_kes, disbursed_on=on, term_months=term_months,
                       monthly_instalment_kes=monthly_instalment_kes, status="active",
                       created_by=actor.id if actor else None)
    db.add(loan)
    db.flush()
    post_entry(db, member_id, "transactional", "loan_disbursement", principal_kes, f"LOAN-{loan.id}",
               actor, stamp, loan)
    if application is not None:
        for g in application.guarantors:
            if g.status == "verified":
                g.loan_account_id = loan.id
    return loan


def over_capacity(db: Session, guarantors: Iterable[Guarantor]) -> list[Guarantor]:
    """Those whose guarantee on this application their capacity cannot carry. It is
    already among what they have committed, so it is taken out before comparing:
    verifying a guarantee does not check capacity, and paying out must. A guarantor
    who is not one of our members has no ledger here to check."""
    rows = [g for g in guarantors if g.member_id is not None]
    caps = capacities(db, {g.member_id for g in rows})
    return [g for g in rows
            if g.amount_guaranteed_kes > caps[g.member_id].capacity_kes
            - (caps[g.member_id].committed_kes - g.amount_guaranteed_kes)]


def pay_out(db: Session, application: LoanApplication, principal_kes: int, actor: User | None) -> LoanAccount:
    """An approved application's loan, on the terms of the application. Its verified
    guarantors move from holding capacity on the application to holding it on the loan;
    any still pending stop holding capacity, since they are no longer needed. The
    caller has locked the borrower and the guarantors."""
    verified = [g for g in application.guarantors if g.status == "verified"]
    short = over_capacity(db, verified)
    if short:
        raise LedgerError(f"guarantor {short[0].member_no} no longer has the capacity for this loan")
    loan = issue_loan(db, application.member_id, principal_kes, application.term_months,
                      instalment_kes(principal_kes, application.term_months), application=application, actor=actor)
    now = utcnow()
    for g in application.guarantors:
        if g.status == "pending":
            g.status, g.verified_at = "rejected", now
            audit.record(db, actor, "guarantor.release", "guarantor", g.id, application_id=application.id,
                         loan_id=loan.id)
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


def reverse_loan(db: Session, loan: LoanAccount, actor: User | None) -> list[AccountEntry]:
    """Undo a payout with compensating entries and mark the loan reversed: any repayment
    goes back to the transactional account, then the principal comes out of it. Nothing
    is deleted or changed, and the guarantors' capacity is free again because the loan
    is no longer active. Refused if the money has been drawn out, or a guarantor has
    already paid towards the loan: those need a person, not an entry."""
    if loan.status != "active":
        raise LedgerError(f"loan {loan.id} is {loan.status}; only an active loan can be reversed")
    types = dict(db.execute(select(AccountEntry.entry_type, func.sum(AccountEntry.amount_kes))
                            .where(AccountEntry.loan_account_id == loan.id)
                            .group_by(AccountEntry.entry_type)).all())
    if types.get("guarantee_recovery"):
        raise LedgerError(f"loan {loan.id} has guarantee recoveries against it; it cannot be reversed")
    entries = []
    repaid = -types.get("loan_repayment", 0)
    if repaid:
        entries.append(post_entry(db, loan.member_id, "transactional", "loan_reversal", repaid,
                                  f"REV-LOAN-{loan.id}-RPY", actor, loan=loan))
    try:
        entries.append(post_entry(db, loan.member_id, "transactional", "loan_reversal", -loan.principal_kes,
                                  f"REV-LOAN-{loan.id}", actor, loan=loan))
    except LedgerError:
        raise LedgerError(f"KSh {loan.principal_kes:,} is no longer in the transactional account, so the "
                          "payout cannot be reversed; recover it through the loan") from None
    loan.status, loan.updated_at = "reversed", utcnow()
    return entries


def disbursement_of(db: Session, loan: LoanAccount) -> tuple[AccountEntry, int]:
    """(the entry that paid this loan out, the account's balance just before it)."""
    entry = db.scalar(select(AccountEntry).where(AccountEntry.loan_account_id == loan.id,
                                                 AccountEntry.entry_type == "loan_disbursement")
                      .order_by(AccountEntry.id).limit(1))
    before = db.scalar(select(func.coalesce(func.sum(AccountEntry.amount_kes), 0))
                       .where(AccountEntry.account_id == entry.account_id, AccountEntry.id < entry.id))
    return entry, before


def still_guarantees(db: Session, member_id: int) -> bool:
    """Backing an active loan or an open application, or still answerable for a
    defaulted loan beyond what has been recovered from them."""
    cap = capacities(db, [member_id])[member_id]
    if cap.guaranteed_kes or cap.committed_kes:
        return True
    owing = dict(db.execute(select(Guarantor.loan_account_id, func.sum(Guarantor.amount_guaranteed_kes))
                            .join(LoanAccount, LoanAccount.id == Guarantor.loan_account_id)
                            .where(Guarantor.member_id == member_id, Guarantor.status == "verified",
                                   LoanAccount.status == "defaulted")
                            .group_by(Guarantor.loan_account_id)).all())
    if not owing:
        return False
    recovered = dict(db.execute(select(AccountEntry.loan_account_id, -func.sum(AccountEntry.amount_kes))
                                .join(MemberAccount, MemberAccount.id == AccountEntry.account_id)
                                .where(MemberAccount.member_id == member_id,
                                       AccountEntry.entry_type == "guarantee_recovery",
                                       AccountEntry.loan_account_id.in_(owing))
                                .group_by(AccountEntry.loan_account_id)).all())
    return any(amount > recovered.get(loan_id, 0) for loan_id, amount in owing.items())


def refund_deposits(db: Session, member_id: int, reference: str, actor: User | None) -> AccountEntry:
    """A departing member's whole deposits balance, only when they guarantee nothing
    and owe nothing, and no application could still be paid out against it. Pledges
    in either direction stop: a member who has left backs nobody and needs no backing."""
    balance = deposits_balance(db, member_id) or 0
    if balance <= 0:
        raise LedgerError("this member has no deposits to refund")
    if db.scalar(select(LoanAccount.id).where(LoanAccount.member_id == member_id,
                                              LoanAccount.status.in_(STILL_OWED)).limit(1)) is not None:
        raise LedgerError("this member still owes on a loan")
    if still_guarantees(db, member_id):
        raise LedgerError("this member still guarantees another member's loan")
    if db.scalar(select(LoanApplication.id).where(LoanApplication.member_id == member_id,
                                                  LoanApplication.status.in_(OPEN_APPLICATION))
                 .outerjoin(LoanAccount, LoanAccount.application_id == LoanApplication.id)
                 .where(LoanAccount.id.is_(None)).limit(1)) is not None:
        raise LedgerError("this member has an application still open")
    entry = post_entry(db, member_id, "deposits", "deposit_refund", -balance, reference, actor)
    for pledge in db.scalars(select(GuarantorPledge).where(
            or_(GuarantorPledge.borrower_member_id == member_id, GuarantorPledge.guarantor_member_id == member_id),
            GuarantorPledge.status == "active")):
        withdraw_pledge(pledge)
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


def outstanding_principal(loan: LoanAccount, paid_kes: int, rate: float | None = None) -> int:
    """The principal left on a reducing balance after this much has been paid: each full
    instalment first pays the month's interest, and a part-paid one comes off the principal."""
    rate = config.LOAN_INTEREST_MONTHLY if rate is None else rate
    covered, part = divmod(paid_kes, loan.monthly_instalment_kes)
    if covered >= loan.term_months:
        return 0
    balance = float(loan.principal_kes)
    for _ in range(covered):
        balance = balance * (1 + rate) - loan.monthly_instalment_kes
    return min(max(math.ceil(round(balance - part, 6)), 0), loan.principal_kes)


def days_in_arrears(loan: LoanAccount, paid_kes: int, today: date | None = None) -> int:
    """Days since the oldest instalment not fully paid fell due; 0 when up to date
    or repaid. An instalment falls due each month after disbursement, and money
    received pays the oldest first."""
    today = today or nairobi_today()
    if loan.status in ("repaid", "reversed"):
        return 0
    covered = paid_kes // loan.monthly_instalment_kes
    if covered >= loan.term_months:
        return 0
    due = add_months(loan.disbursed_on, covered + 1)
    return max((today - due).days, 0)


def sacco_loan_use(statuses: Iterable[str]) -> int:
    """The classifier's sacco_loan_use from a member's loan accounts: 0 never, 1
    all repaid, 2 still owing. A defaulted loan is still owed, not repaid; a reversed
    one never really happened."""
    statuses = set(statuses) - {"reversed"}
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
