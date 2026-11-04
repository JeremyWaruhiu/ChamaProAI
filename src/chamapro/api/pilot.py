"""The volunteer pilot: self sign-up, a member's own record and loan application,
their practice interviews, the daily caps, the SUS questionnaire, and the admin's
pilot figures and exports.

The practice interview itself runs the existing pipeline through main.py's
endpoints; everything here that a member reads is built field by field, so
nothing from an assessment reaches them but the wording of its result and reasons.
"""
from __future__ import annotations

import csv
import hmac
import io
import secrets
from datetime import datetime, time, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response as HTTPResponse
from sqlalchemy import Date, bindparam, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload

from chamapro import config

from . import audit, auth, bookings, comparator, events, loans, member_text
from . import pipeline as pl
from . import schemas as s
from .auth import require_admin, require_member
from .db import (Applicant, Assessment, Interview, LoanApplication, Member,
                 PilotDailyUsage, PracticeInterview, Response, SusResponse, User, get_db,
                 nairobi_today, utcnow)
from .questions import CURRENT_SET, QUESTION_SETS

ERRORS = {code: {"model": s.Error} for code in (401, 403, 404, 409, 422, 429)}
router = APIRouter(prefix="/api", responses=ERRORS)

CONSENT_VERSION = "pilot-2026-11"
CONSENT_TEXT = [
    "Your interview answers are recorded and stored on Supabase, a cloud database and file store.",
    "Your answers are processed by Google's Gemini service, which translates them and extracts "
    "facts from them.",
    "Please invent a fictional applicant. Do not give your real finances, or anyone else's.",
    "The recordings are used to evaluate this system.",
]
SAVINGS_LABEL = {"none": "Not entered yet", "self_declared": "Self-declared, pending verification",
                 "verified": "Verified by the SACCO"}


def signup_info() -> s.SignupInfo:
    return s.SignupInfo(enabled=bool(config.PILOT_INVITE_CODE), consent_version=CONSENT_VERSION,
                        consent_text=CONSENT_TEXT)


# --- Sign-up ------------------------------------------------------------------------

def client_address(request: Request) -> str:
    """The address uvicorn settled on: behind a proxy, --proxy-headers takes it
    from X-Forwarded-For, but only from peers in FORWARDED_ALLOW_IPS. The header
    is never read here, or anyone could reset their own limit by changing it."""
    return request.client.host if request.client else "unknown"


def check_signup_allowed(request: Request) -> None:
    """404 while sign-up is off; 429 past the limit. Counts this attempt."""
    if not config.PILOT_INVITE_CODE:
        raise HTTPException(404, "self sign-up is not open")
    ip = client_address(request)
    wait = auth.signup_limiter.retry_after(ip)
    if wait is not None:
        raise HTTPException(429, "too many sign-up attempts from this address; try again later",
                            headers={"Retry-After": str(wait)})
    auth.signup_limiter.fail(ip)


def phone_taken(db: Session, phone: str, member_id: int | None = None) -> bool:
    other = db.scalar(select(Member.id).where(Member.phone == phone))
    return other is not None and other != member_id


def free_member_no(db: Session, member_id: int) -> str:
    """V-00042, from the record's id; a staff-chosen number or username is never reused."""
    base = no = f"V-{member_id:05d}"
    n = 1
    while db.scalar(select(Member.id).where(Member.member_no == no)) \
            or db.scalar(select(User.id).where(User.username == no)):
        n += 1
        no = f"{base}-{n}"
    return no


def create_volunteer(db: Session, body: s.Signup) -> tuple[User, Member]:
    """The member record and its login. They sign in with their phone number or
    member number. Their email stays on the member record: users.email signs in
    with Google, and an address nobody has verified must not be able to claim that."""
    if not hmac.compare_digest(body.invite_code.strip().encode(), config.PILOT_INVITE_CODE.encode()):
        raise HTTPException(403, "that invite code is not valid")
    if body.consent_version != CONSENT_VERSION:
        raise HTTPException(422, "consent_version: the consent text has changed; please read it again")
    if phone_taken(db, body.phone):
        raise HTTPException(409, "that phone number is already registered")
    placeholder = "pending-" + secrets.token_hex(8)
    user = User(username=placeholder, password_hash=auth.hash_password(body.password), role="member",
                display_name=body.full_name[:120])
    m = Member(member_no=placeholder, full_name=body.full_name, phone=body.phone, email=body.email,
               joined_on=nairobi_today(), user=user, consent_version=body.consent_version,
               consent_at=utcnow(), self_signed_up=True)
    try:
        db.add(m)
        db.flush()
        m.member_no = user.username = free_member_no(db, m.id)
        audit.record(db, user, "member.signup", "member", m.id, user_id=user.id,
                     consent_version=m.consent_version)
        db.commit()
    except IntegrityError:      # lost a race for the same number
        db.rollback()
        raise HTTPException(409, "that phone number is already registered")
    return user, m


# --- A member's own record ------------------------------------------------------------

def required_member(db: Session, user: User) -> Member:
    member = loans.my_member(db, user)
    if member is None:
        raise HTTPException(404, "your login is not linked to a member record; ask the SACCO")
    return member


def savings_status(m: Member) -> str:
    if m.savings_kes is None:
        return "none"
    return "verified" if m.savings_verified_at is not None else "self_declared"


def applicant_complete(m: Member) -> bool:
    return None not in (m.birth_year, m.sex, m.education, m.marital_status)


def age_of(m: Member) -> int | None:
    return None if m.birth_year is None else nairobi_today().year - m.birth_year


def save_applicant_form(m: Member, form: s.ApplicantForm) -> None:
    m.birth_year, m.sex = nairobi_today().year - form.age, form.sex
    m.education, m.marital_status = form.education, form.marital_status


def my_member_view(m: Member) -> s.MyMember:
    status = savings_status(m)
    return s.MyMember(
        member_no=m.member_no, full_name=m.full_name, phone=m.phone, email=m.email,
        savings_kes=m.savings_kes, savings_status=status, savings_label=SAVINGS_LABEL[status],
        savings_limit_kes=None if m.savings_kes is None
        else m.savings_kes * comparator.SAVINGS_MULTIPLIER,
        joined_on=m.joined_on, tenure_months=comparator.months_between(m.joined_on, nairobi_today()),
        age=age_of(m), sex=m.sex, education=m.education, marital_status=m.marital_status,
        applicant_complete=applicant_complete(m), consent_current=m.consent_version == CONSENT_VERSION)


@router.get("/me/member", response_model=s.MyMember)
def get_my_member(db: Session = Depends(get_db), user: User = Depends(require_member)):
    return my_member_view(required_member(db, user))


@router.patch("/me/member", response_model=s.MyMember)
def update_my_member(body: s.MyMemberUpdate, db: Session = Depends(get_db),
                     user: User = Depends(require_member)):
    """Phone, email, savings until an officer has verified them, and the
    applicant form. schemas.MyMemberUpdate refuses every other field."""
    m = required_member(db, user)
    given, changed = body.model_fields_set, []
    if "phone" in given:
        if body.phone is None:
            raise HTTPException(422, "phone: a phone number is required")
        if body.phone != m.phone:
            if phone_taken(db, body.phone, m.id):
                raise HTTPException(409, "that phone number is already registered")
            m.phone = body.phone
            changed.append("phone")
    if "email" in given and body.email != m.email:
        m.email = body.email
        changed.append("email")
    if body.savings_kes is not None and body.savings_kes != m.savings_kes:
        if m.savings_verified_at is not None:
            raise HTTPException(409, "your savings have been verified; ask the SACCO to change them")
        m.savings_kes = body.savings_kes
        loans.refresh_open_applications(db, m)
        changed.append("savings_kes")
    if body.applicant is not None:
        save_applicant_form(m, body.applicant)
        changed.append("applicant_form")
    if changed:
        audit.record(db, user, "member.self_update", "member", m.id, fields=changed)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "that phone number is already registered")
    return my_member_view(m)


@router.post("/me/consent", response_model=s.MyMember)
def give_consent(body: s.ConsentIn, db: Session = Depends(get_db),
                 user: User = Depends(require_member)):
    """For members staff created: they agree here before their first practice interview."""
    m = required_member(db, user)
    if not body.consent or body.consent_version != CONSENT_VERSION:
        raise HTTPException(422, "consent: please read the current text and agree to it")
    m.consent_version, m.consent_at = body.consent_version, utcnow()
    audit.record(db, user, "member.consent", "member", m.id, consent_version=m.consent_version)
    db.commit()
    return my_member_view(m)


@router.get("/me/home", response_model=s.MemberHome)
def member_home(db: Session = Depends(get_db), user: User = Depends(require_member)):
    member = loans.my_member(db, user)
    booking = bookings.my_upcoming(db, member.id) if member else None
    return s.MemberHome(events=[s.EventOut.model_validate(e) for e in events.upcoming(db, 5)],
                        next_interview=loans.my_booking(booking) if booking else None,
                        applications=loans.my_summaries(db, member) if member else [])


# --- Applying for a loan --------------------------------------------------------------

@router.post("/me/applications", status_code=201, response_model=s.MyApplication)
def apply_for_loan(body: s.MyApplicationCreate, db: Session = Depends(get_db),
                   user: User = Depends(require_member)):
    """Everything already known comes from the member's record, never the request.
    Exceeding the savings limit or the tenure rule is the form's warning, not a
    refusal: the officer decides."""
    m = required_member(db, user)
    if m.savings_kes is None:
        if body.declared_savings_kes is None:
            raise HTTPException(422, "declared_savings_kes: enter your savings")
        m.savings_kes = body.declared_savings_kes
    elif body.declared_savings_kes is not None:
        raise HTTPException(422, "declared_savings_kes: your savings are already on your record")
    if applicant_complete(m):
        if body.applicant is not None:
            raise HTTPException(422, "applicant: already on your record; change it on your profile")
    elif body.applicant is None:
        raise HTTPException(422, "applicant: the applicant form is required")
    else:
        save_applicant_form(m, body.applicant)
    bookings.refuse_second_booking(db, m.id)
    start = bookings.checked_slot(body.date, body.time)

    app = LoanApplication(member_id=m.id, amount_requested_kes=body.amount_requested_kes,
                          purpose=body.purpose_text, term_months=body.term_months,
                          sacco_savings_kes=m.savings_kes,
                          savings_self_declared=m.savings_verified_at is None,
                          status="draft", created_by=user.id)
    db.add(app)
    db.flush()
    audit.record(db, user, "application.create", "loan_application", app.id, status="draft",
                 member_id=m.id, amount_requested_kes=app.amount_requested_kes, via="member")
    try:
        bookings.add_booking(db, app, start, body.language, user)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise bookings.slot_conflict()
    return loans.my_view(db, app)


@router.post("/me/applications/{application_id}/booking", status_code=201,
             response_model=s.MyApplication)
def book_interview(application_id: int, body: s.BookingRequest, db: Session = Depends(get_db),
                   user: User = Depends(require_member)):
    """Book again, after a cancellation or a slot that passed."""
    app = loans.own_application(db, user, application_id)
    if app.interview_id is not None or app.status not in ("draft", "interview_pending"):
        raise HTTPException(409, "this application's interview has already been held")
    bookings.refuse_second_booking(db, app.member_id)
    start = bookings.checked_slot(body.date, body.time)
    bookings.retire_missed(db, app, user)
    try:
        bookings.add_booking(db, app, start, body.language, user)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise bookings.slot_conflict()
    return loans.my_view(db, app)


# --- Practice interviews: what the member may see ----------------------------------------

def own_practice(db: Session, user: User, interview_id: int) -> PracticeInterview:
    """The member's own practice run; anyone else's is the same 404 as none at all."""
    member = loans.my_member(db, user)
    p = db.scalar(select(PracticeInterview).where(PracticeInterview.interview_id == interview_id)
                  .options(joinedload(PracticeInterview.interview)))
    if p is None or member is None or p.member_id != member.id:
        raise HTTPException(404, f"practice interview {interview_id} not found")
    return p


def own_practice_response(db: Session, user: User, response_id: int) -> Response:
    r = db.get(Response, response_id)
    if r is None:
        raise HTTPException(404, f"response {response_id} not found")
    try:
        own_practice(db, user, r.interview_id)
    except HTTPException:
        raise HTTPException(404, f"response {response_id} not found")
    return r


def my_response(r: Response, busy: int | None) -> s.MyResponse:
    return s.MyResponse(id=r.id, sentence_no=r.sentence_no, source=r.source,
                        status="transcribing" if r.id == busy else r.status,
                        transcript=r.transcript, edited=r.edited,
                        duration_s=None if r.duration_s is None else round(r.duration_s))


def my_practice_view(db: Session, p: PracticeInterview) -> s.MyPractice:
    iv: Interview = p.interview
    busy = pl.transcribing()
    a: Assessment | None = iv.assessment
    result = None if a is None else s.PracticeResult(
        message=member_text.practice_result(a.risk_class),
        reasons=member_text.reasons(a.risk_class, a.contributions))
    answered_sus = db.scalar(select(SusResponse.id).where(SusResponse.interview_id == iv.id))
    return s.MyPractice(
        id=iv.id, application_id=p.application_id, language=iv.language, status=iv.status,
        created_at=iv.created_at,
        questions=[s.MyQuestion(order=q.order, topic=q.topic, text_en=q.text_en, text_kik=q.text_kik)
                   for q in QUESTION_SETS[iv.question_set]],
        responses=[my_response(r, busy) for r in iv.responses], result=result,
        sus_answered=answered_sus is not None, limits=limits_for(db, p.member_id))


def start_practice(db: Session, app: LoanApplication, language: str, user: User) -> PracticeInterview:
    """Resume the application's unfinished practice run, or start one: always
    mode=practice, never linked as the application's interview."""
    m = app.member
    if m.consent_version != CONSENT_VERSION:
        raise HTTPException(409, "please read and agree to the pilot consent first")
    if not applicant_complete(m):
        raise HTTPException(409, "please complete the applicant form on your profile first")
    existing = db.scalar(select(PracticeInterview)
                         .join(Interview, Interview.id == PracticeInterview.interview_id)
                         .where(PracticeInterview.application_id == app.id,
                                Interview.status == "open")
                         .options(joinedload(PracticeInterview.interview)))
    if existing is not None:
        return existing
    refuse_if_capped(db, m.id)
    iv = Interview(applicant=Applicant(name=m.full_name, age=age_of(m), sex=m.sex,
                                       education=m.education, marital_status=m.marital_status),
                   question_set=CURRENT_SET, language=language, mode="practice")
    db.add(iv)
    db.flush()
    p = PracticeInterview(interview=iv, application_id=app.id, member_id=m.id)
    db.add(p)
    db.flush()
    audit.record(db, user, "interview.create", "interview", iv.id, question_set=iv.question_set,
                 language=iv.language, mode=iv.mode, application_id=app.id, via="member")
    db.commit()
    return p


def refuse_incomplete(iv: Interview) -> None:
    """Every question answered, and every answer ready, before a member submits."""
    total = len(QUESTION_SETS[iv.question_set])
    if iv.status != "open":
        raise HTTPException(409, "this practice interview has already been submitted")
    by_status = [r.status for r in iv.responses]
    if "queued" in by_status:
        raise HTTPException(409, "some answers are still being transcribed; please wait a moment")
    if len(by_status) < total:
        raise HTTPException(409, f"please answer all {total} questions before submitting; "
                                 f"{len(by_status)} answered so far")
    if "failed" in by_status or any(not (r.transcript or "").strip() for r in iv.responses):
        raise HTTPException(409, "some answers have no text; type them or record them again")


# --- The daily caps ------------------------------------------------------------------

ALL = "all"
_ENSURE_USAGE_ROW = text("INSERT INTO pilot_daily_usage (day, scope, used) VALUES (:day, :scope, 0) "
                         "ON CONFLICT (day, scope) DO NOTHING").bindparams(bindparam("day", type_=Date))


def _member_scope(member_id: int) -> str:
    return f"member:{member_id}"


def used_today(db: Session, scope: str) -> int:
    return db.scalar(select(PilotDailyUsage.used).where(PilotDailyUsage.day == nairobi_today(),
                                                        PilotDailyUsage.scope == scope)) or 0


def limits_for(db: Session, member_id: int) -> s.PracticeLimits:
    cap = config.PILOT_MAX_SUBMISSIONS_PER_MEMBER
    return s.PracticeLimits(remaining_today=max(cap - used_today(db, _member_scope(member_id)), 0),
                            allowed_per_day=cap,
                            pilot_full_today=used_today(db, ALL) >= config.PILOT_MAX_ASSESSMENTS_PER_DAY)


def seconds_to_tomorrow() -> int:
    tomorrow = datetime.combine(nairobi_today() + timedelta(days=1), time(), tzinfo=config.NAIROBI)
    return max(int((tomorrow.astimezone(timezone.utc) - utcnow()).total_seconds()), 1)


def member_cap_reached() -> HTTPException:
    n = config.PILOT_MAX_SUBMISSIONS_PER_MEMBER
    return HTTPException(429, f"You have reached today's limit of {n} practice interviews. "
                              "Your answers are saved, and you can submit again tomorrow.",
                         headers={"Retry-After": str(seconds_to_tomorrow())})


def pilot_cap_reached() -> HTTPException:
    return HTTPException(429, "The pilot has reached today's limit of "
                              f"{config.PILOT_MAX_ASSESSMENTS_PER_DAY} assessments. "
                              "Your answers are saved, and you can submit again tomorrow.",
                         headers={"Retry-After": str(seconds_to_tomorrow())})


def refuse_if_capped(db: Session, member_id: int) -> None:
    """Said before anyone records eight answers; submit_practice is what enforces it."""
    limits = limits_for(db, member_id)
    if limits.remaining_today == 0:
        raise member_cap_reached()
    if limits.pilot_full_today:
        raise pilot_cap_reached()


def _take(db: Session, day, scope: str, cap: int) -> bool:
    """One unit of scope's allowance, if any is left. The WHERE clause is the
    check, so two requests at once cannot both take the last one."""
    db.execute(_ENSURE_USAGE_ROW, {"day": day, "scope": scope})
    done = db.execute(update(PilotDailyUsage)
                      .where(PilotDailyUsage.day == day, PilotDailyUsage.scope == scope,
                             PilotDailyUsage.used < cap)
                      .values(used=PilotDailyUsage.used + 1))
    return done.rowcount == 1


def reserve_submission(db: Session, member_id: int):
    """Take one of the member's submissions and one of the day's assessments, or
    raise 429 having taken neither. Committed before the model runs, so a request
    waiting on Gemini holds its place. Returns the day, for release_submission."""
    day = nairobi_today()
    if not _take(db, day, _member_scope(member_id), config.PILOT_MAX_SUBMISSIONS_PER_MEMBER):
        db.rollback()
        raise member_cap_reached()
    if not _take(db, day, ALL, config.PILOT_MAX_ASSESSMENTS_PER_DAY):
        db.rollback()
        raise pilot_cap_reached()
    db.commit()
    return day


def release_submission(db: Session, member_id: int, day) -> None:
    """A submission that produced no assessment costs the member nothing."""
    db.rollback()
    db.execute(update(PilotDailyUsage)
               .where(PilotDailyUsage.day == day,
                      PilotDailyUsage.scope.in_((_member_scope(member_id), ALL)),
                      PilotDailyUsage.used > 0)
               .values(used=PilotDailyUsage.used - 1))
    db.commit()


# --- The System Usability Scale --------------------------------------------------------

def sus_score(answers: list[int]) -> float:
    """Brooke's scoring: odd items a - 1, even items 5 - a, the sum times 2.5."""
    return sum(a - 1 if i % 2 == 0 else 5 - a for i, a in enumerate(answers)) * 2.5


@router.post("/me/practice/{interview_id}/sus", status_code=204)
def answer_sus(interview_id: int, body: s.SusIn, db: Session = Depends(get_db),
               user: User = Depends(require_member)):
    p = own_practice(db, user, interview_id)
    if p.interview.status != "assessed":
        raise HTTPException(409, "the questionnaire comes after you have submitted your interview")
    row = SusResponse(interview_id=interview_id, member_id=p.member_id, answers=body.answers,
                      score=sus_score(body.answers), comment=(body.comment or "").strip() or None)
    try:
        db.add(row)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "you have already answered this questionnaire")
    return HTTPResponse(status_code=204)


# --- Admin: figures and exports -----------------------------------------------------------

def _self_service(stmt):
    return stmt.join(PracticeInterview, PracticeInterview.interview_id == Interview.id)


def answers_per_member(db: Session) -> list[s.MemberAnswers]:
    rows = db.execute(select(Member.member_no, func.count(Response.id),
                             func.count(func.distinct(PracticeInterview.interview_id)))
                      .join(PracticeInterview, PracticeInterview.member_id == Member.id)
                      .outerjoin(Response, Response.interview_id == PracticeInterview.interview_id)
                      .group_by(Member.member_no).order_by(func.count(Response.id).desc(),
                                                           Member.member_no))
    return [s.MemberAnswers(member_no=no, answers=a, interviews=i) for no, a, i in rows]


def comments(db: Session, limit: int | None) -> list[s.PilotComment]:
    stmt = (select(SusResponse, Member.member_no).join(Member, Member.id == SusResponse.member_id)
            .where(SusResponse.comment.is_not(None))
            .order_by(SusResponse.created_at.desc(), SusResponse.id.desc()))
    if limit is not None:
        stmt = stmt.limit(limit)
    return [s.PilotComment(member_no=no, comment=r.comment, score=r.score, created_at=r.created_at)
            for r, no in db.execute(stmt)]


def pilot_stats(db: Session) -> s.PilotStats:
    """Self-service only: interviews staff ran in practice mode, and demo rows,
    are not the volunteers' and are left out. A fixed number of queries."""
    volunteers = db.scalar(select(func.count(Member.id)).where(Member.self_signed_up.is_(True))) or 0
    by_language = dict(db.execute(_self_service(select(Interview.language, func.count(Interview.id)))
                                  .group_by(Interview.language)).all())
    completed = db.scalar(_self_service(select(func.count(Assessment.id))
                                        .join(Interview, Interview.id == Assessment.interview_id))) or 0
    per_member = answers_per_member(db)
    mean, n, members = db.execute(select(func.avg(SusResponse.score), func.count(SusResponse.id),
                                         func.count(func.distinct(SusResponse.member_id)))).one()
    return s.PilotStats(
        volunteers=volunteers, practice_by_language={"kik": 0, "en": 0, **by_language},
        completed_assessments=completed, answers_total=sum(m.answers for m in per_member),
        answers_per_member=per_member, sus_mean=None if mean is None else round(float(mean), 1),
        sus_n=n, sus_members=members, comments=comments(db, 20),
        signup_open=bool(config.PILOT_INVITE_CODE),
        per_member_cap=config.PILOT_MAX_SUBMISSIONS_PER_MEMBER,
        daily_cap=config.PILOT_MAX_ASSESSMENTS_PER_DAY, used_today=used_today(db, ALL))


@router.get("/admin/pilot", response_model=s.PilotStats)
def pilot_view(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return pilot_stats(db)


def csv_cell(value):
    """Spreadsheets run a cell that starts like a formula, and these cells hold
    what volunteers typed. A leading apostrophe makes it plain text."""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def csv_response(filename: str, header: list[str], rows) -> HTTPResponse:
    out = io.StringIO()
    out.write("﻿")     # so Excel reads the Kikuyu letters as UTF-8
    w = csv.writer(out)
    w.writerow(header)
    for row in rows:
        w.writerow([csv_cell(c) for c in row])
    return HTTPResponse(out.getvalue(), media_type="text/csv; charset=utf-8",
                        headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.get("/admin/pilot/export/aggregates.csv", response_class=HTTPResponse)
def export_aggregates(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """One row per figure: section, key, value. Members appear by number only."""
    st = pilot_stats(db)
    rows = [("summary", "volunteers", st.volunteers),
            *(("practice_interviews_by_language", k, v) for k, v in st.practice_by_language.items()),
            ("summary", "completed_assessments", st.completed_assessments),
            ("summary", "answers_recorded", st.answers_total),
            ("sus", "mean", st.sus_mean if st.sus_mean is not None else ""),
            ("sus", "n", st.sus_n), ("sus", "members", st.sus_members),
            *(("answers_per_member", m.member_no, m.answers) for m in st.answers_per_member),
            *(("comment", c.member_no, c.comment) for c in comments(db, None))]
    audit.record(db, user, "pilot.export", "pilot", None, export="aggregates")
    db.commit()
    return csv_response("pilot-aggregates.csv", ["section", "key", "value"], rows)


@router.get("/admin/pilot/export/transcripts.csv", response_class=HTTPResponse)
def export_transcripts(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """One row per answer in a self-service interview. No audio and no audio
    path; members by number, not by name or phone."""
    rows = db.execute(select(Member.member_no, PracticeInterview.application_id, Response.interview_id,
                             Interview.language, Response.sentence_no, Response.domain,
                             Response.source, Response.status, Response.transcript_asr,
                             Response.transcript, Response.edited, Response.translation,
                             Response.asr_model, Response.duration_s, Response.created_at)
                      .join(PracticeInterview, PracticeInterview.interview_id == Response.interview_id)
                      .join(Interview, Interview.id == Response.interview_id)
                      .join(Member, Member.id == PracticeInterview.member_id)
                      .order_by(Response.interview_id, Response.sentence_no)).all()
    audit.record(db, user, "pilot.export", "pilot", None, export="transcripts", rows=len(rows))
    db.commit()
    return csv_response("pilot-transcripts.csv",
                        ["member_no", "application_id", "interview_id", "language", "sentence_no",
                         "topic", "source", "status", "transcript_asr", "transcript", "edited",
                         "translation", "asr_model", "duration_s", "created_at_utc"],
                        [(*r[:-1], r[-1].isoformat()) for r in rows])
