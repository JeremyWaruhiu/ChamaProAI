"""Interview bookings: half-hour slots at the one branch, in Nairobi time.

Stored in UTC, computed and shown in Africa/Nairobi. A slot is free unless a
requested, confirmed or started booking holds it; a partial unique index makes
that true whatever two requests do at once. Weekends, public holidays
(config.PUBLIC_HOLIDAYS) and past times cannot be booked, on the server as on
the date picker.

    requested -> confirmed -> started (opens the live interview)
    requested | confirmed -> cancelled (the application goes back to draft)

A rescheduled booking counts as confirmed: the officer chose the new time. Every
change is an audit row on the application, which is also where the member's
history comes from (loans.history).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from chamapro import config

from . import audit, loans
from . import schemas as s
from .auth import current_user, require_officer
from .db import (Applicant, Interview, InterviewBooking, LoanApplication, Member, User, get_db,
                 nairobi_today, utcnow)
from .questions import CURRENT_SET

ERRORS = {code: {"model": s.Error} for code in (401, 403, 404, 409, 422)}
router = APIRouter(prefix="/api", responses=ERRORS)

SLOT_TIMES = tuple(s.SlotTime.__args__)     # 08:30 to 16:00: the last one ends at 16:30
OPEN = ("requested", "confirmed")
HOLDING = ("requested", "confirmed", "started")
SLOT_TAKEN = "that interview time has just been taken; please choose another"


def slot_start(day: date, hhmm: str) -> datetime:
    """A slot's start as an aware UTC time."""
    hour, minute = hhmm.split(":")
    local = datetime.combine(day, time(int(hour), int(minute)), tzinfo=config.NAIROBI)
    return local.astimezone(timezone.utc)


def last_bookable() -> date:
    return nairobi_today() + timedelta(days=config.BOOKING_WINDOW_DAYS)


def day_problem(day: date) -> str | None:
    """Why this date cannot be booked at all, or None."""
    if day < nairobi_today():
        return "this date has passed"
    if day > last_bookable():
        return f"interviews can be booked up to {config.BOOKING_WINDOW_DAYS} days ahead"
    if day.weekday() >= 5:
        return "the branch holds interviews on weekdays only"
    if day in config.PUBLIC_HOLIDAYS:
        return f"{config.PUBLIC_HOLIDAYS[day]} is a public holiday"
    if day.year not in {d.year for d in config.PUBLIC_HOLIDAYS}:
        return f"public holidays for {day.year} have not been set up yet"
    return None


def checked_slot(day: date, hhmm: str) -> datetime:
    """The slot's start, or 422 if it could never be booked. Whether someone has
    it is left to the unique index."""
    problem = day_problem(day)
    if problem is not None:
        raise HTTPException(422, f"date: {problem}")
    start = slot_start(day, hhmm)
    if start <= utcnow():
        raise HTTPException(422, "time: this time has passed")
    return start


def add_booking(db: Session, app: LoanApplication, start: datetime, language: str,
                actor: User) -> InterviewBooking:
    """Book the slot and move the application to interview_pending. The caller
    commits, and answers IntegrityError with slot_conflict()."""
    b = InterviewBooking(application_id=app.id, member_id=app.member_id, starts_at=start,
                         language=language, status="requested")
    db.add(b)
    db.flush()
    audit.record(db, actor, "booking.create", "loan_application", app.id, booking_id=b.id,
                 starts_at=start.isoformat(), language=language)
    loans.set_status(db, app, "interview_pending", actor, booking_id=b.id)
    return b


def slot_conflict() -> HTTPException:
    return HTTPException(409, SLOT_TAKEN)


def my_upcoming(db: Session, member_id: int) -> InterviewBooking | None:
    return db.scalar(select(InterviewBooking)
                     .where(InterviewBooking.member_id == member_id,
                            InterviewBooking.status.in_(OPEN),
                            InterviewBooking.starts_at >= utcnow())
                     .order_by(InterviewBooking.starts_at).limit(1))


def refuse_second_booking(db: Session, member_id: int) -> None:
    """One upcoming interview per member, so nobody can hold every slot."""
    current = my_upcoming(db, member_id)
    if current is not None:
        raise HTTPException(409, f"you already have an interview booked on "
                                 f"{loans.local_label(current.starts_at)}")


def retire_missed(db: Session, app: LoanApplication, actor: User) -> None:
    """A slot that passed without its interview no longer stands in the way."""
    for b in db.scalars(select(InterviewBooking).where(InterviewBooking.application_id == app.id,
                                                       InterviewBooking.status.in_(OPEN))):
        b.status, b.updated_at = "cancelled", utcnow()
        audit.record(db, actor, "booking.cancel", "loan_application", app.id, booking_id=b.id,
                     starts_at=b.starts_at.isoformat(), missed=True)
    db.flush()


LOAD = (joinedload(InterviewBooking.application), joinedload(InterviewBooking.member))


# --- The calendar (every signed-in role) ------------------------------------------

@router.get("/booking/calendar", response_model=s.BookingCalendar)
def calendar(_: User = Depends(current_user)):
    today, last = nairobi_today(), last_bookable()
    return s.BookingCalendar(
        today=today, last_date=last, times=list(SLOT_TIMES), timezone="Africa/Nairobi",
        holidays=[s.Holiday(date=d, name=n) for d, n in sorted(config.PUBLIC_HOLIDAYS.items())
                  if today <= d <= last])


@router.get("/booking/slots", response_model=s.DaySlots)
def slots(day: date = Query(alias="date"), db: Session = Depends(get_db),
          _: User = Depends(current_user)):
    """Every slot of a day and whether it is free. Says nobody's name."""
    problem = day_problem(day)
    if problem is not None:
        return s.DaySlots(date=day, blocked_reason=problem, slots=[])
    starts = [slot_start(day, t) for t in SLOT_TIMES]
    taken = set(db.scalars(select(InterviewBooking.starts_at)
                           .where(InterviewBooking.status.in_(HOLDING),
                                  InterviewBooking.starts_at >= starts[0],
                                  InterviewBooking.starts_at <= starts[-1])))
    now = utcnow()
    out = []
    for hhmm, start in zip(SLOT_TIMES, starts):
        reason = "booked" if start in taken else "past" if start <= now else None
        out.append(s.SlotOut(time=hhmm, starts_at=start, available=reason is None, reason=reason))
    return s.DaySlots(date=day, blocked_reason=None, slots=out)


# --- Staff --------------------------------------------------------------------------

def get_booking(db: Session, booking_id: int) -> InterviewBooking:
    b = db.get(InterviewBooking, booking_id, options=LOAD)
    if b is None:
        raise HTTPException(404, f"booking {booking_id} not found")
    return b


def require_status(b: InterviewBooking, *allowed: str) -> None:
    if b.status not in allowed:
        raise HTTPException(409, f"booking {b.id} is {b.status}")


def record(db: Session, actor: User, action: str, b: InterviewBooking, **details) -> None:
    audit.record(db, actor, action, "loan_application", b.application_id, booking_id=b.id,
                 starts_at=b.starts_at.isoformat(), **details)


@router.get("/bookings", response_model=list[s.BookingOut])
def list_bookings(start: date | None = Query(None, description="From this Nairobi date; default today"),
                  end: date | None = Query(None, description="To this Nairobi date, inclusive"),
                  include_cancelled: bool = False, limit: int = Query(200, ge=1, le=500),
                  db: Session = Depends(get_db), _: User = Depends(require_officer)):
    """Soonest first. Today's stay on the list until the day is over, so an
    interview running late can still be opened."""
    first = slot_start(start or nairobi_today(), "00:00")
    stmt = (select(InterviewBooking).options(*LOAD).where(InterviewBooking.starts_at >= first)
            .order_by(InterviewBooking.starts_at).limit(limit))
    if end is not None:
        stmt = stmt.where(InterviewBooking.starts_at < slot_start(end + timedelta(days=1), "00:00"))
    if not include_cancelled:
        stmt = stmt.where(InterviewBooking.status != "cancelled")
    return [loans.booking_out(b) for b in db.scalars(stmt)]


@router.post("/bookings/{booking_id}/confirm", response_model=s.BookingOut)
def confirm_booking(booking_id: int, db: Session = Depends(get_db),
                    user: User = Depends(require_officer)):
    b = get_booking(db, booking_id)
    require_status(b, "requested")
    b.status, b.updated_at = "confirmed", utcnow()
    record(db, user, "booking.confirm", b)
    db.commit()
    return loans.booking_out(b)


@router.post("/bookings/{booking_id}/reschedule", response_model=s.BookingOut)
def reschedule_booking(booking_id: int, body: s.Slot, db: Session = Depends(get_db),
                       user: User = Depends(require_officer)):
    b = get_booking(db, booking_id)
    require_status(b, *OPEN)
    b.starts_at, b.status, b.updated_at = checked_slot(body.date, body.time), "confirmed", utcnow()
    record(db, user, "booking.reschedule", b)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise slot_conflict()
    return loans.booking_out(b)


@router.post("/bookings/{booking_id}/cancel", response_model=s.BookingOut)
def cancel_booking(booking_id: int, db: Session = Depends(get_db),
                   user: User = Depends(require_officer)):
    b = get_booking(db, booking_id)
    require_status(b, *OPEN)
    b.status, b.updated_at = "cancelled", utcnow()
    record(db, user, "booking.cancel", b)
    if b.application.status == "interview_pending" and b.application.interview_id is None:
        loans.set_status(db, b.application, "draft", user, booking_id=b.id)
    db.commit()
    return loans.booking_out(b)


@router.post("/bookings/{booking_id}/start", response_model=s.BookingOut)
def start_booked_interview(booking_id: int, db: Session = Depends(get_db),
                           user: User = Depends(require_officer)):
    """Open the live interview of a confirmed booking, with the application and
    the member's applicant form attached. Pressing it twice opens the same one."""
    b = get_booking(db, booking_id)
    if b.status == "started":
        return loans.booking_out(b)
    require_status(b, "confirmed")
    m: Member = b.member
    if m.birth_year is None or m.sex is None or m.education is None or m.marital_status is None:
        raise HTTPException(409, f"member {m.member_no} has not completed the applicant form")
    iv = Interview(applicant=Applicant(name=m.full_name, age=nairobi_today().year - m.birth_year,
                                       sex=m.sex, education=m.education,
                                       marital_status=m.marital_status),
                   question_set=CURRENT_SET, language=b.language, mode="live")
    db.add(iv)
    db.flush()
    audit.record(db, user, "interview.create", "interview", iv.id, question_set=iv.question_set,
                 language=iv.language, mode=iv.mode, booking_id=b.id)
    loans.link_interview(db, b.application, iv.id, user)
    b.status, b.interview_id, b.updated_at = "started", iv.id, utcnow()
    record(db, user, "booking.start", b, interview_id=iv.id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"application {b.application_id} already has an interview")
    return loans.booking_out(b)
