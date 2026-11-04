"""Self sign-up, a member's own record and loan application, interview bookings,
practice interviews with their daily caps, SUS, SACCO events and the pilot page."""
import csv
import io
import secrets
import threading
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from chamapro import config
from chamapro.api import auth, bookings, main, member_text, pilot
from chamapro.api.db import (Assessment, AuditLog, Interview, InterviewBooking, Member,
                             PilotDailyUsage, SaccoEvent, SessionLocal, SusResponse, nairobi_today,
                             normalise_phone, utcnow)
from chamapro.api.main import app
from chamapro.api.questions import QUESTION_SETS
from conftest import BASE_URL, CONTRIBUTIONS, FORM, fresh_phone, needs_classifier, new_member, wait_until
from test_member_access import leaks

INVITE = "test-invite-" + secrets.token_hex(4)
PASSWORD = "correct horse battery"
EIGHT = len(QUESTION_SETS["v2"])


@pytest.fixture
def invite(monkeypatch, client):
    monkeypatch.setattr(config, "PILOT_INVITE_CODE", INVITE)
    return INVITE


def signup_body(**over):
    body = {"full_name": "Fictional Volunteer", "phone": fresh_phone(), "password": PASSWORD,
            "password_confirm": PASSWORD, "invite_code": INVITE, "consent": True,
            "consent_version": pilot.CONSENT_VERSION}
    return {**body, **over}


def volunteer(**over):
    """A signed-up member: (their client, the sign-up reply, the request body)."""
    c = TestClient(app, base_url=BASE_URL)
    body = signup_body(**over)
    r = c.post("/api/auth/signup", json=body)
    assert r.status_code == 201, r.text
    return c, r.json(), body


def weekdays(start=1):
    """Bookable dates, soonest first."""
    d = nairobi_today() + timedelta(days=start)
    while d <= bookings.last_bookable():
        if bookings.day_problem(d) is None:
            yield d
        d += timedelta(days=1)


def free_slot(client):
    """The first slot nobody holds, as a request body. The tests share a database."""
    for d in weekdays():
        for slot in client.get("/api/booking/slots", params={"date": d.isoformat()}).json()["slots"]:
            if slot["available"]:
                return {"date": d.isoformat(), "time": slot["time"]}
    raise AssertionError("no free slot left in the window")


def application_body(client, **over):
    return {"amount_requested_kes": 30000, "purpose": "School fees", "term_months": 12,
            "language": "kik", "applicant": FORM, "declared_savings_kes": 20000,
            **free_slot(client), **over}


def applied(**over):
    """A volunteer with an application: (client, application, the member's id)."""
    c, me, _ = volunteer()
    r = c.post("/api/me/applications", json=application_body(c, **over))
    assert r.status_code == 201, r.text
    with SessionLocal() as db:
        mid = db.scalar(select(Member.id).where(Member.member_no == me["member_no"]))
    return c, r.json(), mid


@pytest.fixture
def fake_assess(monkeypatch):
    """submit without Gemini or the classifier: main.assess writes the assessment
    the real one would. One test below runs the real pipeline."""
    def run(interview_id, db, user):
        iv = db.get(Interview, interview_id)
        db.add(Assessment(
            interview=iv, risk_class=run.risk, probabilities={"Low": 0.2, "Medium": 0.5, "High": 0.3},
            feature_vector={"B3A__1": 1.0}, contributions=CONTRIBUTIONS, extracted={},
            extraction_completeness=0.5, features_populated=1, features_total=2,
            features_not_extractable=[], extraction_model="fake", model_file="classifier.joblib",
            model_sha256="0" * 64, assessed_by=user.username))
        iv.status = "assessed"
        db.commit()
    run.risk = "Medium"
    monkeypatch.setattr(main, "assess", run)
    return run


def start_practice(c, app_id, language="kik"):
    r = c.post(f"/api/me/applications/{app_id}/practice", json={"language": language})
    assert r.status_code == 201, r.text
    return r.json()


def answer_all(c, practice_id):
    for q in QUESTION_SETS["v2"]:
        r = c.post(f"/api/me/practice/{practice_id}/responses/typed",
                   json={"sentence_no": q.order, "text": f"answer {q.order}"})
        assert r.status_code == 201, r.text


def ready_practice(**over):
    """A volunteer's practice interview with all eight questions answered."""
    c, a, mid = applied(**over)
    p = start_practice(c, a["id"])
    answer_all(c, p["id"])
    return c, a, p, mid


# --- Phone numbers -----------------------------------------------------------------

@pytest.mark.parametrize("typed", ["0712345678", "0712 345 678", "+254712345678", "254712345678",
                                   "+254 712 345 678", "(0712) 345-678"])
def test_mobile_forms_become_one(typed):
    assert normalise_phone(typed) == "+254712345678"


@pytest.mark.parametrize("typed, want", [("0112345678", "+254112345678"),
                                         ("+254112345678", "+254112345678"),
                                         ("254112345678", "+254112345678")])
def test_01_numbers_too(typed, want):
    assert normalise_phone(typed) == want


@pytest.mark.parametrize("bad", ["12345", "0812345678", "071234567", "07123456789", "+255712345678",
                                 "2540712345678", "0712345abc", "٠٧١٢٣٤٥٦٧٨"])
def test_not_a_kenyan_mobile(bad):
    with pytest.raises(ValueError):
        normalise_phone(bad)


@pytest.mark.parametrize("blank", [None, "", "   "])
def test_blank_is_no_number(blank):
    assert normalise_phone(blank) is None


def test_signup_stores_the_one_form_and_refuses_duplicates_in_any_form(invite):
    phone = fresh_phone()                                       # 07XXXXXXXX
    canonical = "+254" + phone[1:]
    _, me, _ = volunteer(phone=phone)
    with SessionLocal() as db:
        assert db.scalar(select(Member.phone).where(Member.member_no == me["member_no"])) == canonical
    for again in (phone, canonical, canonical[1:], f"{phone[:4]} {phone[4:]}"):
        r = TestClient(app, base_url=BASE_URL).post("/api/auth/signup", json=signup_body(phone=again))
        assert r.status_code == 409 and "already registered" in r.json()["detail"], again


def test_phone_is_required_at_signup(invite, anon_client):
    assert anon_client.post("/api/auth/signup", json=signup_body(phone="")).status_code == 422
    body = signup_body()
    del body["phone"]
    assert anon_client.post("/api/auth/signup", json=body).status_code == 422


def test_staff_members_may_have_no_phone_but_never_a_shared_one(client):
    def create(**extra):
        return client.post("/api/members", json={"member_no": "P-" + secrets.token_hex(4),
                                                 "full_name": "F", "joined_on": "2020-01-01", **extra})
    assert create().status_code == create().status_code == 201     # none, twice
    phone = fresh_phone()
    first = create(phone=phone)
    assert first.status_code == 201 and first.json()["phone"] == "+254" + phone[1:]
    r = create(phone="254" + phone[1:])
    assert r.status_code == 409 and "phone number" in r.json()["detail"]
    other = create().json()
    r = client.patch(f"/api/members/{other['id']}", json={"phone": phone})
    assert r.status_code == 409 and "phone number" in r.json()["detail"]
    r = client.post("/api/members", json={"member_no": first.json()["member_no"], "full_name": "F",
                                          "joined_on": "2020-01-01"})
    assert r.status_code == 409 and "member number" in r.json()["detail"]


# --- Sign-up: invite code, consent, limits --------------------------------------------

def test_signup_is_off_without_an_invite_code(anon_client, monkeypatch):
    monkeypatch.setattr(config, "PILOT_INVITE_CODE", None)
    assert anon_client.get("/api/auth/signup").json()["enabled"] is False
    assert anon_client.post("/api/auth/signup", json=signup_body()).status_code == 404


def test_signup_says_what_people_are_agreeing_to(anon_client, invite):
    info = anon_client.get("/api/auth/signup").json()
    text = " ".join(info["consent_text"])
    assert info["enabled"] is True and info["consent_version"] == pilot.CONSENT_VERSION
    for words in ("recorded", "stored on Supabase", "Google's Gemini", "translates", "extracts",
                  "fictional applicant", "evaluate"):
        assert words in text, words


@pytest.mark.parametrize("over, status, field", [
    ({"invite_code": "not-the-code"}, 403, "invite"), ({"consent": False}, 422, "consent"),
    ({"consent_version": "old"}, 422, "consent_version"),
    ({"password_confirm": "something else entirely"}, 422, "do not match"),
    ({"password": "short", "password_confirm": "short"}, 422, "password"),
    ({"email": "not an email"}, 422, "email"), ({"full_name": "   "}, 422, "full_name")])
def test_signup_refusals_create_nothing(anon_client, invite, over, status, field):
    phone = fresh_phone()
    r = anon_client.post("/api/auth/signup", json=signup_body(phone=phone, **over))
    assert r.status_code == status and field in r.json()["detail"]
    with SessionLocal() as db:
        assert db.scalar(select(Member.id).where(Member.phone == "+254" + phone[1:])) is None
    assert anon_client.get("/api/auth/me").status_code == 401


def test_a_wrong_invite_does_not_reveal_who_is_registered(anon_client, invite):
    _, _, body = volunteer()
    r = anon_client.post("/api/auth/signup", json=signup_body(phone=body["phone"], invite_code="wrong"))
    assert r.status_code == 403


def test_signup_makes_a_member_a_login_and_a_session(invite):
    c, me, body = volunteer(email=" Someone@Example.com ")
    assert me["role"] == "member" and me["member_no"].startswith("V-")
    assert c.get("/api/auth/me").json()["username"] == me["member_no"]
    with SessionLocal() as db:
        m = db.scalar(select(Member).where(Member.member_no == me["member_no"]))
        assert m.user.role == "member" and m.self_signed_up is True
        assert m.consent_version == pilot.CONSENT_VERSION and m.consent_at is not None
        assert m.joined_on == nairobi_today() and m.email == "someone@example.com"
        assert m.savings_kes is None and m.savings_verified_at is None
        # Not users.email: an unverified address must not be able to claim Google sign-in.
        assert m.user.email is None
        assert db.scalar(select(AuditLog).where(AuditLog.action == "member.signup",
                                                AuditLog.entity_id == m.id)) is not None


@pytest.mark.parametrize("typed", ["national", "international", "bare"])
def test_volunteers_sign_in_with_their_phone_in_any_form(invite, anon_client, typed):
    _, _, body = volunteer()
    national = body["phone"]
    form = {"national": national, "international": "+254" + national[1:], "bare": "254" + national[1:]}
    r = anon_client.post("/api/auth/login", json={"username": form[typed], "password": PASSWORD})
    assert r.status_code == 200 and r.json()["role"] == "member"


def test_retyping_a_phone_another_way_earns_no_more_login_attempts(invite, anon_client):
    _, _, body = volunteer()
    national = body["phone"]
    forms = [national, "+254" + national[1:], "254" + national[1:]]
    for i in range(config.LOGIN_MAX_FAILURES):
        anon_client.post("/api/auth/login", json={"username": forms[i % 3], "password": "wrong-password"})
    r = anon_client.post("/api/auth/login", json={"username": forms[0], "password": PASSWORD})
    assert r.status_code == 429


def test_signup_is_limited_per_address(invite, anon_client, monkeypatch):
    monkeypatch.setattr(auth, "signup_limiter", auth.LoginLimiter(3, 3600))
    for _ in range(3):
        assert anon_client.post("/api/auth/signup",
                                json=signup_body(invite_code="wrong")).status_code == 403
    r = anon_client.post("/api/auth/signup", json=signup_body())
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
    # A forwarded-for header from the client changes nothing: only uvicorn may believe one.
    r = anon_client.post("/api/auth/signup", json=signup_body(), headers={"X-Forwarded-For": "203.0.113.9"})
    assert r.status_code == 429


# --- A member's own record ---------------------------------------------------------------

def test_savings_are_self_declared_until_staff_verify_them(invite, client):
    c, me, _ = volunteer()
    assert c.get("/api/me/member").json()["savings_status"] == "none"
    r = c.patch("/api/me/member", json={"savings_kes": 40000})
    assert r.status_code == 200
    body = r.json()
    assert body["savings_status"] == "self_declared"
    assert body["savings_label"] == "Self-declared, pending verification"
    assert body["savings_limit_kes"] == 120000

    mid = client.get("/api/members", params={"q": me["member_no"]}).json()[0]["id"]
    v = client.post(f"/api/members/{mid}/verify", json={"savings_kes": 35000, "joined_on": "2020-02-03"})
    assert v.status_code == 200 and v.json()["savings_verified_by"] == "officer1"
    body = c.get("/api/me/member").json()
    assert (body["savings_kes"], body["savings_status"]) == (35000, "verified")
    assert body["joined_on"] == "2020-02-03" and body["tenure_months"] > 60

    r = c.patch("/api/me/member", json={"savings_kes": 90000})
    assert r.status_code == 409 and "verified" in r.json()["detail"]
    assert c.get("/api/me/member").json()["savings_kes"] == 35000
    with SessionLocal() as db:
        row = db.scalar(select(AuditLog).where(AuditLog.action == "member.verify_savings",
                                               AuditLog.entity_id == mid))
        assert sorted(row.details["edited"]) == ["joined_on", "savings_kes"]
        assert "35000" not in str(row.details)                  # field names, not figures


def test_verifying_with_nothing_entered_needs_a_figure(client):
    mid, _, _ = new_member()
    assert client.post(f"/api/members/{mid}/verify", json={}).status_code == 422
    assert client.post(f"/api/members/{mid}/verify", json={"savings_kes": 100}).status_code == 200


@pytest.mark.parametrize("field, value", [
    ("full_name", "Someone Else"), ("member_no", "M-1"), ("joined_on", "2010-01-01"),
    ("savings_verified_at", "2026-01-01T00:00:00Z"), ("savings_verified_by", "me"),
    ("self_signed_up", False), ("user_id", 1), ("consent_version", "x")])
def test_a_member_cannot_edit_read_only_fields(invite, field, value):
    c, _, _ = volunteer()
    before = c.get("/api/me/member").json()
    r = c.patch("/api/me/member", json={field: value})
    assert r.status_code == 422 and field in r.json()["detail"]
    assert c.get("/api/me/member").json() == before


def test_a_member_edits_their_phone_and_email(invite):
    c, _, _ = volunteer()
    new = fresh_phone()
    r = c.patch("/api/me/member", json={"phone": new, "email": "New@Example.com"})
    assert r.status_code == 200
    assert r.json()["phone"] == "+254" + new[1:] and r.json()["email"] == "new@example.com"
    assert c.patch("/api/me/member", json={"phone": None}).status_code == 422
    assert c.patch("/api/me/member", json={"email": None}).json()["email"] is None
    other, _, taken = volunteer()
    assert c.patch("/api/me/member", json={"phone": taken["phone"]}).status_code == 409
    assert c.patch("/api/me/member", json={"phone": "123"}).status_code == 422


def test_age_comes_back_from_a_birth_year_not_a_stored_age(invite):
    c, _, _ = volunteer()
    assert c.patch("/api/me/member", json={"applicant": FORM}).json()["age"] == FORM["age"]
    with SessionLocal() as db:
        m = db.scalar(select(Member).where(Member.birth_year == nairobi_today().year - FORM["age"]))
        assert m is not None and not hasattr(m, "age")


# --- Applying: pre-filled, read-only fields ---------------------------------------------

@pytest.mark.parametrize("field, value", [
    ("full_name", "Someone Else"), ("member_no", "M-1"), ("phone", "0700000000"),
    ("sacco_savings_kes", 9_000_000), ("savings_kes", 9_000_000), ("savings_status", "verified"),
    ("savings_self_declared", False), ("joined_on", "2000-01-01"), ("tenure_months", 200),
    ("member_id", 1), ("status", "approved"), ("mode", "practice"), ("interview_id", 1)])
def test_read_only_fields_cannot_be_sent_with_an_application(invite, field, value):
    c, _, _ = volunteer()
    r = c.post("/api/me/applications", json=application_body(c, **{field: value}))
    assert r.status_code == 422 and field in r.json()["detail"]
    assert c.get("/api/me/applications").json() == []


def test_an_application_takes_what_is_known_from_the_record(invite, client):
    c, a, mid = applied()
    assert a["status"] == "interview_pending" and a["mode"] == "live" and a["purpose"] == "School fees"
    staff = client.get(f"/api/applications/{a['id']}").json()
    assert staff["member"]["id"] == mid and staff["sacco_savings_kes"] == 20000
    assert staff["savings_self_declared"] is True
    me = c.get("/api/me/member").json()
    assert me["age"] == FORM["age"] and me["sex"] == FORM["sex"] and me["applicant_complete"] is True


def test_known_savings_and_form_are_not_entered_twice(invite):
    c, a, _ = applied()
    r = c.post("/api/me/applications", json=application_body(c))
    assert r.status_code == 422                                  # already on the record
    with SessionLocal() as db:
        db.get(InterviewBooking, a["booking"]["id"]).status = "cancelled"
        db.commit()
    body = application_body(c)
    del body["declared_savings_kes"], body["applicant"]
    assert c.post("/api/me/applications", json=body).status_code == 201


def test_a_first_application_needs_savings_and_the_form(invite):
    c, _, _ = volunteer()
    body = application_body(c)
    del body["declared_savings_kes"]
    r = c.post("/api/me/applications", json=body)
    assert r.status_code == 422 and "savings" in r.json()["detail"]
    body = application_body(c)
    del body["applicant"]
    r = c.post("/api/me/applications", json=body)
    assert r.status_code == 422 and "applicant" in r.json()["detail"]
    assert c.get("/api/me/member").json()["savings_kes"] is None    # a refused request saved nothing


def test_the_savings_limit_and_tenure_warn_but_never_block(invite):
    c, a, _ = applied(amount_requested_kes=9_000_000, declared_savings_kes=100)
    assert a["amount_requested_kes"] == 9_000_000
    assert c.get("/api/me/member").json()["tenure_months"] == 0


@pytest.mark.parametrize("over, ok", [({"purpose": "Other", "purpose_other": "Roof repairs"}, True),
                                      ({"purpose": "Other"}, False),
                                      ({"purpose": "Other", "purpose_other": "   "}, False),
                                      ({"purpose": "Not on the list"}, False)])
def test_purpose_is_from_the_list_or_other_with_text(invite, over, ok):
    c, _, _ = volunteer()
    r = c.post("/api/me/applications", json=application_body(c, **over))
    assert (r.status_code == 201) is ok, r.text
    if ok:
        assert r.json()["purpose"] == "Roof repairs"


def test_verifying_savings_reaches_undecided_applications_only(invite, client):
    c, a, mid = applied(declared_savings_kes=20000)
    assert client.post(f"/api/members/{mid}/verify", json={"savings_kes": 50000}).status_code == 200
    staff = client.get(f"/api/applications/{a['id']}").json()
    assert staff["sacco_savings_kes"] == 50000 and staff["savings_self_declared"] is False


# --- Slots and bookings -------------------------------------------------------------------

def test_slots_run_half_hourly_from_0830_to_1630():
    assert bookings.SLOT_TIMES[0] == "08:30" and bookings.SLOT_TIMES[-1] == "16:00"
    assert len(bookings.SLOT_TIMES) == 16


def test_times_are_nairobi_and_stored_in_utc(invite):
    c, _, _ = volunteer()
    d = next(weekdays(5))
    start = bookings.slot_start(d, "08:30")
    assert start == datetime(d.year, d.month, d.day, 5, 30, tzinfo=timezone.utc)
    body = c.get("/api/booking/slots", params={"date": d.isoformat()}).json()
    assert body["slots"][0]["time"] == "08:30"
    assert datetime.fromisoformat(body["slots"][0]["starts_at"]) == start


def test_a_booking_is_stored_in_utc_and_read_back_the_same(invite):
    c, a, _ = applied()
    with SessionLocal() as db:
        row = db.get(InterviewBooking, a["booking"]["id"])
        raw = db.execute(select(InterviewBooking.__table__.c.starts_at)
                         .where(InterviewBooking.id == row.id)).scalar_one()
    local = row.starts_at.astimezone(config.NAIROBI)
    assert (raw.hour, raw.minute) == ((local.hour - 3) % 24, local.minute)
    assert f"{local:%H:%M}" in bookings.SLOT_TIMES


def test_the_calendar_gives_the_rules_and_the_holiday_names(invite, monkeypatch):
    c, _, _ = volunteer()
    holiday = next(weekdays(10))
    monkeypatch.setitem(config.PUBLIC_HOLIDAYS, holiday, "Test Holiday")
    cal = c.get("/api/booking/calendar").json()
    assert cal["today"] == nairobi_today().isoformat() and cal["timezone"] == "Africa/Nairobi"
    assert {"date": holiday.isoformat(), "name": "Test Holiday"} in cal["holidays"]
    assert cal["times"] == list(bookings.SLOT_TIMES)
    day = c.get("/api/booking/slots", params={"date": holiday.isoformat()}).json()
    assert day["slots"] == [] and day["blocked_reason"] == "Test Holiday is a public holiday"
    r = c.post("/api/me/applications", json=application_body(c, date=holiday.isoformat(), time="09:00"))
    assert r.status_code == 422 and "Test Holiday is a public holiday" in r.json()["detail"]


def test_holiday_list_covers_both_years_with_observed_mondays():
    h = config.PUBLIC_HOLIDAYS
    assert {d.year for d in h} == {2026, 2027}
    assert h[date(2026, 12, 12)] == "Jamhuri Day" and h[date(2027, 3, 26)] == "Good Friday"
    assert "observed" in h[date(2027, 12, 13)] and "observed" in h[date(2027, 12, 27)]


def test_holidays_can_be_replaced_from_the_environment():
    assert config._public_holidays("2030-01-01:One, 2030-06-02:Two Words") == \
        {date(2030, 1, 1): "One", date(2030, 6, 2): "Two Words"}
    with pytest.raises(ValueError, match="PUBLIC_HOLIDAYS"):
        config._public_holidays("2030-01-01")
    with pytest.raises(ValueError):
        config._public_holidays("not-a-date:Name")


def test_dates_that_cannot_be_booked(invite):
    c, _, _ = volunteer()
    today = nairobi_today()
    saturday = today + timedelta(days=(5 - today.weekday()) % 7 or 7)
    too_far = bookings.last_bookable() + timedelta(days=1)
    for day, why in [(today - timedelta(days=1), "passed"), (saturday, "weekdays"),
                     (saturday + timedelta(days=1), "weekdays"), (too_far, "days ahead")]:
        r = c.post("/api/me/applications", json=application_body(c, date=day.isoformat(), time="09:00"))
        assert r.status_code == 422 and why in r.json()["detail"], day
        assert why in c.get("/api/booking/slots", params={"date": day.isoformat()}).json()["blocked_reason"]
    assert c.get("/api/me/applications").json() == []


def test_a_year_without_a_holiday_list_is_refused(monkeypatch):
    # Booking blind would let a holiday through.
    monkeypatch.setattr(config, "BOOKING_WINDOW_DAYS", 3650)
    monkeypatch.setattr(config, "PUBLIC_HOLIDAYS", {date(1999, 1, 1): "Old"})
    assert "have not been set up" in bookings.day_problem(next(
        d for d in (nairobi_today() + timedelta(days=i) for i in range(1, 9)) if d.weekday() < 5))


@pytest.mark.parametrize("time", ["08:00", "16:30", "17:00", "09:15", "nonsense"])
def test_times_outside_the_slots_are_refused(invite, time):
    c, _, _ = volunteer()
    r = c.post("/api/me/applications", json=application_body(c, time=time))
    assert r.status_code == 422


def test_a_slot_earlier_today_shows_as_past(monkeypatch, invite):
    c, _, _ = volunteer()
    d = list(weekdays())[-1]        # a day the other tests' bookings have not reached
    monkeypatch.setattr(bookings, "utcnow", lambda: bookings.slot_start(d, "10:00") + timedelta(minutes=1))
    monkeypatch.setattr(bookings, "nairobi_today", lambda: d)
    slots = c.get("/api/booking/slots", params={"date": d.isoformat()}).json()["slots"]
    by_time = {x["time"]: x for x in slots}
    assert by_time["09:30"]["available"] is False and by_time["09:30"]["reason"] == "past"
    assert by_time["10:00"]["reason"] == "past"
    assert by_time["10:30"]["available"] is True
    r = c.post("/api/me/applications", json=application_body(c, date=d.isoformat(), time="09:30"))
    assert r.status_code == 422 and "has passed" in r.json()["detail"]


def test_no_double_booking(invite):
    first, a, _ = applied()
    other, _, _ = volunteer()
    with SessionLocal() as db:
        taken = db.get(InterviewBooking, a["booking"]["id"]).starts_at.astimezone(config.NAIROBI)
    slot = {"date": taken.date().isoformat(), "time": f"{taken:%H:%M}"}
    r = other.post("/api/me/applications", json=application_body(other, **slot))
    assert r.status_code == 409 and "taken" in r.json()["detail"]
    assert other.get("/api/me/applications").json() == []        # and no application left behind
    assert other.get("/api/me/member").json()["savings_kes"] is None
    day = other.get("/api/booking/slots", params={"date": slot["date"]}).json()
    held = next(s for s in day["slots"] if s["time"] == slot["time"])
    assert held["available"] is False and held["reason"] == "booked"
    assert set(held) == {"time", "starts_at", "available", "reason"}     # never who holds it


def test_the_database_itself_refuses_a_second_booking_of_a_slot(invite):
    _, a, _ = applied()
    with SessionLocal() as db:
        held = db.get(InterviewBooking, a["booking"]["id"])
        db.add(InterviewBooking(application_id=held.application_id, member_id=held.member_id,
                                starts_at=held.starts_at, language="en", status="cancelled"))
        db.commit()                                              # a cancelled row holds nothing
        db.add(InterviewBooking(application_id=held.application_id, member_id=held.member_id,
                                starts_at=held.starts_at, language="en", status="started"))
        with pytest.raises(IntegrityError):
            db.commit()


def test_two_requests_for_one_slot_at_once(invite):
    a, _, _ = volunteer()
    b, _, _ = volunteer()
    slot = free_slot(a)
    replies, gate = [], threading.Barrier(2)

    def go(c):
        gate.wait()
        replies.append(c.post("/api/me/applications", json=application_body(c, **slot)).status_code)
    threads = [threading.Thread(target=go, args=(c,)) for c in (a, b)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(replies) == [201, 409]


def test_one_upcoming_interview_per_member(invite):
    c, _, _ = applied()
    r = c.post("/api/me/applications", json={**application_body(c), "declared_savings_kes": None,
                                             "applicant": None})
    assert r.status_code == 409 and "already have an interview" in r.json()["detail"]


# --- The officer's side ----------------------------------------------------------------------

def booked(client):
    """(member client, application, booking as staff see it)."""
    c, a, mid = applied()
    rows = client.get("/api/bookings", params={"limit": 500}).json()
    return c, a, next(b for b in rows if b["id"] == a["booking"]["id"])


def test_officers_see_upcoming_interviews_soonest_first(invite, client):
    _, a, b = booked(client)
    assert b["status"] == "requested" and b["application_id"] == a["id"]
    assert b["member_phone"].startswith("+254")
    starts = [r["starts_at"] for r in client.get("/api/bookings", params={"limit": 500}).json()]
    assert starts == sorted(starts)


def test_week_view_filters_by_nairobi_dates(invite, client):
    c, a, b = booked(client)
    day = datetime.fromisoformat(b["starts_at"]).astimezone(config.NAIROBI).date()
    inside = client.get("/api/bookings", params={"start": day.isoformat(), "end": day.isoformat()}).json()
    assert b["id"] in {r["id"] for r in inside}
    before = client.get("/api/bookings", params={"start": (day - timedelta(days=3)).isoformat(),
                                                 "end": (day - timedelta(days=1)).isoformat()}).json()
    assert b["id"] not in {r["id"] for r in before}


def test_confirm_and_the_member_sees_it(invite, client):
    c, a, b = booked(client)
    r = client.post(f"/api/bookings/{b['id']}/confirm")
    assert r.status_code == 200 and r.json()["status"] == "confirmed"
    assert client.post(f"/api/bookings/{b['id']}/confirm").status_code == 409
    mine = c.get(f"/api/me/applications/{a['id']}").json()
    assert mine["booking"]["status"] == "confirmed"
    assert mine["history"][-1]["label"].startswith("Interview confirmed for ")


def test_reschedule_shows_the_member_the_new_time(invite, client):
    c, a, b = booked(client)
    slot = free_slot(client)
    r = client.post(f"/api/bookings/{b['id']}/reschedule", json=slot)
    assert r.status_code == 200 and r.json()["status"] == "confirmed"
    new = bookings.slot_start(date.fromisoformat(slot["date"]), slot["time"])
    mine = c.get(f"/api/me/applications/{a['id']}").json()
    assert datetime.fromisoformat(mine["booking"]["starts_at"]) == new
    local = new.astimezone(config.NAIROBI)
    assert mine["history"][-1]["label"] == f"Interview moved to {local:%a} {local.day} {local:%b %Y} at {slot['time']}"
    home = c.get("/api/me/home").json()
    assert datetime.fromisoformat(home["next_interview"]["starts_at"]) == new


def test_reschedule_onto_a_taken_slot_or_a_holiday_is_refused(invite, client, monkeypatch):
    _, _, first = booked(client)
    _, _, second = booked(client)
    taken = datetime.fromisoformat(first["starts_at"]).astimezone(config.NAIROBI)
    r = client.post(f"/api/bookings/{second['id']}/reschedule",
                    json={"date": taken.date().isoformat(), "time": f"{taken:%H:%M}"})
    assert r.status_code == 409 and "taken" in r.json()["detail"]
    holiday = next(weekdays(20))
    monkeypatch.setitem(config.PUBLIC_HOLIDAYS, holiday, "Test Holiday")
    r = client.post(f"/api/bookings/{second['id']}/reschedule",
                    json={"date": holiday.isoformat(), "time": "09:00"})
    assert r.status_code == 422 and "Test Holiday" in r.json()["detail"]


def test_cancel_frees_the_slot_and_the_member_can_book_again(invite, client):
    c, a, b = booked(client)
    r = client.post(f"/api/bookings/{b['id']}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "cancelled"
    assert client.post(f"/api/bookings/{b['id']}/cancel").status_code == 409
    mine = c.get(f"/api/me/applications/{a['id']}").json()
    assert mine["status"] == "draft" and mine["booking"] is None
    assert "cancelled" in mine["history"][-1]["label"]
    assert c.get("/api/me/home").json()["next_interview"] is None
    # the same time is free for anyone, this member included
    local = datetime.fromisoformat(b["starts_at"]).astimezone(config.NAIROBI)
    slot = {"date": local.date().isoformat(), "time": f"{local:%H:%M}", "language": "en"}
    r = c.post(f"/api/me/applications/{a['id']}/booking", json=slot)
    assert r.status_code == 201, r.text
    assert r.json()["booking"]["language"] == "en" and r.json()["status"] == "interview_pending"


def test_a_slot_that_passed_does_not_block_booking_again(invite, client):
    c, a, b = booked(client)
    with SessionLocal() as db:
        db.get(InterviewBooking, b["id"]).starts_at = utcnow() - timedelta(days=1)
        db.commit()
    r = c.post(f"/api/me/applications/{a['id']}/booking", json={**free_slot(c), "language": "kik"})
    assert r.status_code == 201, r.text
    assert r.json()["booking"]["id"] != b["id"]


def test_a_confirmed_booking_opens_the_interview_with_everything_attached(invite, client):
    c, a, b = booked(client)
    assert client.post(f"/api/bookings/{b['id']}/start").status_code == 409     # not confirmed yet
    client.post(f"/api/bookings/{b['id']}/confirm")
    r = client.post(f"/api/bookings/{b['id']}/start")
    assert r.status_code == 200 and r.json()["status"] == "started"
    iid = r.json()["interview_id"]
    iv = client.get(f"/api/interviews/{iid}").json()
    assert iv["mode"] == "live" and iv["language"] == "kik" and iv["application_id"] == a["id"]
    assert iv["question_set"] == "v2" and iv["applicant"]["age"] == FORM["age"]
    assert iv["applicant"]["sex"] == FORM["sex"] and iv["applicant"]["education"] == FORM["education"]
    assert iv["applicant"]["name"] == "Fictional Volunteer"
    assert client.post(f"/api/bookings/{b['id']}/start").json()["interview_id"] == iid    # the same one
    assert client.get(f"/api/applications/{a['id']}").json()["interview_id"] == iid
    assert c.get(f"/api/me/applications/{a['id']}").json()["history"][-1]["label"] == "Interview started"


def test_status_changes_reach_the_members_timeline(invite, client):
    c, a, b = booked(client)
    client.post(f"/api/bookings/{b['id']}/confirm")
    iid = client.post(f"/api/bookings/{b['id']}/start").json()["interview_id"]
    answer = {"sentence_no": 1, "text": "Five of us."}
    assert client.post(f"/api/interviews/{iid}/responses/typed", json=answer).status_code == 201
    mine = c.get(f"/api/me/applications/{a['id']}").json()
    assert [t["status"] for t in mine["timeline"]] == ["draft", "interview_pending"]
    labels = [h["label"] for h in mine["history"]]
    assert labels[0] == "Application started" and labels[1].startswith("Interview booked for ")
    assert labels[2].startswith("Interview confirmed") and labels[3] == "Interview started"


def test_members_cannot_use_the_officer_booking_actions(invite, client):
    c, _, b = booked(client)
    for action in ("confirm", "cancel", "start"):
        assert c.post(f"/api/bookings/{b['id']}/{action}").status_code == 403
    assert c.get("/api/bookings").status_code == 403


# --- Practice interviews -----------------------------------------------------------------------

def test_practice_is_always_practice_and_never_the_applications_interview(invite, client, fake_assess):
    c, a, p, _ = ready_practice()
    assert p["mode"] == "practice" and p["language"] == "kik" and p["application_id"] == a["id"]
    assert len(p["questions"]) == EIGHT and client.get(f"/api/interviews/{p['id']}").json()["mode"] == "practice"
    assert c.post(f"/api/me/practice/{p['id']}/submit").status_code == 200
    mine = c.get(f"/api/me/applications/{a['id']}").json()
    assert mine["status"] == "interview_pending"                # the application did not move
    assert mine["mode"] == "live" and mine["outcome"] is None
    staff = client.get(f"/api/applications/{a['id']}").json()
    assert staff["interview_id"] is None and staff["assessment"] is None
    assert staff["practice_interviews"][0]["interview_id"] == p["id"]
    assert staff["practice_interviews"][0]["risk_class"] == "Medium"
    assert client.get(f"/api/interviews/{p['id']}").json()["application_id"] is None


def test_the_body_cannot_choose_live_mode(invite):
    c, a, _ = applied()
    r = c.post(f"/api/me/applications/{a['id']}/practice", json={"language": "kik", "mode": "live"})
    assert r.status_code == 422


def test_practice_stays_out_of_the_live_statistics(invite, admin_client, fake_assess):
    from chamapro.api import live_cache
    from chamapro.api.main import live_stats
    with SessionLocal() as db:
        before = live_stats(db)
    c, _, p, _ = ready_practice()
    c.post(f"/api/me/practice/{p['id']}/submit")
    live_cache.invalidate()
    with SessionLocal() as db:
        after = live_stats(db)
    assert after["interview_count"] == before["interview_count"]
    assert after["assessment_count"] == before["assessment_count"]
    assert after["practice_interview_count"] == before["practice_interview_count"] + 1


def test_starting_again_resumes_the_unfinished_one(invite, fake_assess):
    c, a, _ = applied()
    first = start_practice(c, a["id"], "en")
    assert start_practice(c, a["id"], "kik")["id"] == first["id"]
    assert c.get(f"/api/me/applications/{a['id']}").json()["practice"][0]["language"] == "en"
    answer_all(c, first["id"])
    c.post(f"/api/me/practice/{first['id']}/submit")
    assert start_practice(c, a["id"])["id"] != first["id"]


@pytest.mark.parametrize("language", ["kik", "en"])
def test_the_eight_questions_are_there_with_kikuyu_left_to_the_screen(invite, language):
    c, a, _ = applied()
    p = start_practice(c, a["id"], language)
    assert [q["order"] for q in p["questions"]] == list(range(1, EIGHT + 1))
    assert all(q["text_en"] and q["text_kik"] == "" for q in p["questions"])     # v2 has no Kikuyu yet
    assert all("features" not in q for q in p["questions"])


def test_consent_is_needed_before_a_practice_interview(client):
    """A member staff created has not read the consent text; a volunteer has."""
    mid, _, mc = new_member()
    with SessionLocal() as db:
        db.get(Member, mid).birth_year, db.get(Member, mid).sex = 1980, "female"
        m = db.get(Member, mid)
        m.education, m.marital_status = 4, "married"
        db.commit()
    a = client.post("/api/applications", json={"member_id": mid, "amount_requested_kes": 1000,
                                               "purpose": "x", "term_months": 6,
                                               "sacco_savings_kes": 500}).json()
    r = mc.post(f"/api/me/applications/{a['id']}/practice", json={"language": "en"})
    assert r.status_code == 409 and "consent" in r.json()["detail"]
    assert mc.post("/api/me/consent", json={"consent": False,
                                            "consent_version": pilot.CONSENT_VERSION}).status_code == 422
    assert mc.post("/api/me/consent", json={"consent": True,
                                            "consent_version": pilot.CONSENT_VERSION}).status_code == 200
    assert mc.post(f"/api/me/applications/{a['id']}/practice", json={"language": "en"}).status_code == 201


def test_a_member_cannot_touch_another_members_practice(invite, client, fake_assess):
    a_client, a_app, p, _ = ready_practice()
    rid = a_client.get(f"/api/me/practice/{p['id']}").json()["responses"][0]["id"]
    other, _, _ = volunteer()
    for method, url, kw in [
            ("GET", f"/api/me/practice/{p['id']}", {}),
            ("POST", f"/api/me/practice/{p['id']}/submit", {}),
            ("POST", f"/api/me/practice/{p['id']}/responses/typed", {"json": {"sentence_no": 1, "text": "x"}}),
            ("POST", f"/api/me/practice/{p['id']}/sus", {"json": {"answers": [3] * 10}}),
            ("PATCH", f"/api/me/practice/responses/{rid}", {"json": {"transcript": "x"}}),
            ("DELETE", f"/api/me/practice/responses/{rid}", {}),
            ("GET", f"/api/me/practice/responses/{rid}/audio", {}),
            ("POST", f"/api/me/applications/{a_app['id']}/practice", {"json": {"language": "en"}})]:
        assert other.request(method, url, **kw).status_code == 404, url


def test_a_live_interview_is_not_a_members_to_touch(invite, client):
    c, a, b = booked(client)
    client.post(f"/api/bookings/{b['id']}/confirm")
    iid = client.post(f"/api/bookings/{b['id']}/start").json()["interview_id"]
    assert c.get(f"/api/me/practice/{iid}").status_code == 404
    assert c.post(f"/api/me/practice/{iid}/responses/typed",
                  json={"sentence_no": 1, "text": "x"}).status_code == 404
    assert c.post(f"/api/me/practice/{iid}/submit").status_code == 404
    assert c.get(f"/api/interviews/{iid}").status_code == 403


def test_record_upload_and_correct_with_the_existing_pipeline(invite, audio, asr):
    c, a, _ = applied()
    p = start_practice(c, a["id"])
    with audio["wav"].open("rb") as f:
        r = c.post(f"/api/me/practice/{p['id']}/responses", data={"sentence_no": "1"},
                   files={"file": ("a.wav", f, "audio/wav")})
    assert r.status_code == 202 and r.json()["status"] == "queued"
    rid = r.json()["id"]

    def transcribed():
        return c.get(f"/api/me/practice/{p['id']}").json()["responses"][0]["status"] == "transcribed"
    wait_until(transcribed)
    body = c.get(f"/api/me/practice/{p['id']}").json()
    assert body["responses"][0]["transcript"].startswith("kikuyu")
    assert set(body["responses"][0]) == {"id", "sentence_no", "source", "status", "transcript",
                                         "edited", "duration_s"}
    assert c.get(f"/api/me/practice/responses/{rid}/audio").status_code == 200
    r = c.patch(f"/api/me/practice/responses/{rid}", json={"transcript": "corrected"})
    assert r.status_code == 200 and r.json()["transcript"] == "corrected" and r.json()["edited"] is True
    assert c.delete(f"/api/me/practice/responses/{rid}").status_code == 200
    assert c.get(f"/api/me/practice/{p['id']}").json()["responses"] == []


def test_a_transcript_is_length_limited_for_members(invite):
    c, a, _ = applied()
    p = start_practice(c, a["id"])
    c.post(f"/api/me/practice/{p['id']}/responses/typed", json={"sentence_no": 1, "text": "x"})
    rid = c.get(f"/api/me/practice/{p['id']}").json()["responses"][0]["id"]
    assert c.patch(f"/api/me/practice/responses/{rid}", json={"transcript": "x" * 5001}).status_code == 422


def test_submit_needs_every_answer_ready(invite, fake_assess):
    c, a, mid = applied()
    p = start_practice(c, a["id"])
    r = c.post(f"/api/me/practice/{p['id']}/submit")
    assert r.status_code == 409 and f"all {EIGHT} questions" in r.json()["detail"]
    answer_all(c, p["id"])
    with SessionLocal() as db:
        iv = db.get(Interview, p["id"])
        iv.responses[0].status, iv.responses[0].transcript = "failed", None
        db.commit()
    r = c.post(f"/api/me/practice/{p['id']}/submit")
    assert r.status_code == 409 and "no text" in r.json()["detail"]
    with SessionLocal() as db:
        assert db.scalar(select(PilotDailyUsage.used).where(
            PilotDailyUsage.scope == f"member:{mid}")) is None   # nothing was counted


def test_a_submitted_interview_is_closed(invite, fake_assess):
    c, _, p, _ = ready_practice()
    assert c.post(f"/api/me/practice/{p['id']}/submit").status_code == 200
    assert c.post(f"/api/me/practice/{p['id']}/submit").status_code == 409
    rid = c.get(f"/api/me/practice/{p['id']}").json()["responses"][0]["id"]
    assert c.patch(f"/api/me/practice/responses/{rid}", json={"transcript": "x"}).status_code == 409
    assert c.delete(f"/api/me/practice/responses/{rid}").status_code == 409


# --- Members never see scores --------------------------------------------------------------------

@pytest.mark.parametrize("risk", ["Low", "Medium", "High"])
def test_the_member_sees_words_and_staff_see_the_numbers(invite, client, fake_assess, risk):
    fake_assess.risk = risk
    c, a, p, _ = ready_practice()
    r = c.post(f"/api/me/practice/{p['id']}/submit")
    assert r.status_code == 200
    for body in (r.json(), c.get(f"/api/me/practice/{p['id']}").json(),
                 c.get(f"/api/me/applications/{a['id']}").json(), c.get("/api/me/home").json()):
        assert leaks(body) == [], body
    result = r.json()["result"]
    assert result["message"] == member_text.practice_result(risk)
    assert "practice only" in result["message"] and "not a loan decision" in result["message"]
    assert result["reasons"] == member_text.reasons(risk, CONTRIBUTIONS)
    text = str(r.json())
    for word in ("Low", "Medium", "High", "risk", "probabilit", "shap", "SHAP", "fake", "translation",
                 "signals", "assessed_by", "classifier"):
        assert word not in text, word

    staff = client.get(f"/api/interviews/{p['id']}").json()
    assert staff["assessment"]["risk_class"] == risk
    assert staff["assessment"]["probabilities"]["Medium"] == 0.5
    assert staff["assessment"]["contributions"][0]["shap"] == CONTRIBUTIONS[0]["shap"]


def test_a_failed_assessment_says_nothing_of_the_services_behind_it(invite, monkeypatch):
    def down(*a):
        raise main.HTTPException(503, "translation: extraction service unavailable after retries "
                                      "(https://gemini.example?key=SECRET)")
    monkeypatch.setattr(main, "assess", down)
    c, _, p, mid = ready_practice()
    r = c.post(f"/api/me/practice/{p['id']}/submit")
    assert r.status_code == 503 and "SECRET" not in r.text and "extraction" not in r.text
    assert "saved" in r.json()["detail"]
    limits = c.get(f"/api/me/practice/{p['id']}").json()["limits"]
    assert limits["remaining_today"] == config.PILOT_MAX_SUBMISSIONS_PER_MEMBER     # cost nothing
    with SessionLocal() as db:
        assert db.scalar(select(PilotDailyUsage.used).where(
            PilotDailyUsage.scope == f"member:{mid}", PilotDailyUsage.day == nairobi_today())) == 0


@needs_classifier
def test_the_real_pipeline_runs_unchanged_for_a_member(invite, client, gemini):
    c, _, p, _ = ready_practice()
    r = c.post(f"/api/me/practice/{p['id']}/submit")
    assert r.status_code == 200, r.text
    assert leaks(r.json()) == []
    a = client.get(f"/api/interviews/{p['id']}").json()["assessment"]
    assert a["risk_class"] in ("Low", "Medium", "High") and a["extraction_model"]
    assert a["applicant_form"] is not None and a["model_sha256"]
    assert r.json()["result"]["message"] == member_text.practice_result(a["risk_class"])
    assert len(gemini.translated) > 0                            # Kikuyu answers were translated


# --- Daily caps -------------------------------------------------------------------------------------

@pytest.fixture
def clean_usage(client):
    """Today's pilot total starts from zero, whatever other tests used."""
    with SessionLocal() as db:
        db.query(PilotDailyUsage).delete()
        db.commit()


def test_per_member_cap(invite, fake_assess, monkeypatch, clean_usage):
    monkeypatch.setattr(config, "PILOT_MAX_SUBMISSIONS_PER_MEMBER", 2)
    c, a, mid = applied()
    for used in (1, 2):
        p = start_practice(c, a["id"])
        answer_all(c, p["id"])
        r = c.post(f"/api/me/practice/{p['id']}/submit")
        assert r.status_code == 200, r.text
        assert r.json()["limits"]["remaining_today"] == 2 - used
    r = c.post(f"/api/me/applications/{a['id']}/practice", json={"language": "kik"})
    assert r.status_code == 429 and "today's limit of 2" in r.json()["detail"]
    assert int(r.headers["Retry-After"]) <= 86400


def test_cap_message_at_submit_keeps_the_answers(invite, fake_assess, monkeypatch, clean_usage):
    c, a, p, mid = ready_practice()
    monkeypatch.setattr(config, "PILOT_MAX_SUBMISSIONS_PER_MEMBER", 0)
    r = c.post(f"/api/me/practice/{p['id']}/submit")
    assert r.status_code == 429 and "Your answers are saved" in r.json()["detail"]
    body = c.get(f"/api/me/practice/{p['id']}").json()
    assert len(body["responses"]) == EIGHT and body["status"] == "open"


def test_daily_total_cap_across_members(invite, fake_assess, monkeypatch, clean_usage):
    monkeypatch.setattr(config, "PILOT_MAX_ASSESSMENTS_PER_DAY", 1)
    c1, _, p1, _ = ready_practice()
    c2, _, p2, mid2 = ready_practice()
    assert c1.post(f"/api/me/practice/{p1['id']}/submit").status_code == 200
    r = c2.post(f"/api/me/practice/{p2['id']}/submit")
    assert r.status_code == 429 and "The pilot has reached today's limit of 1" in r.json()["detail"]
    assert c2.get(f"/api/me/practice/{p2['id']}").json()["limits"]["pilot_full_today"] is True
    with SessionLocal() as db:           # refused by the total, so it cost them none of their own
        assert db.scalar(select(PilotDailyUsage.used).where(
            PilotDailyUsage.scope == f"member:{mid2}")) in (None, 0)


def test_defaults_are_five_and_twenty():
    assert config.PILOT_MAX_SUBMISSIONS_PER_MEMBER == 5 and config.PILOT_MAX_ASSESSMENTS_PER_DAY == 20


def test_staff_assessments_are_not_capped(client, monkeypatch, gemini, classifier_stub):
    """The caps are the pilot's: an officer's interview still reaches the pipeline."""
    monkeypatch.setattr(config, "PILOT_MAX_ASSESSMENTS_PER_DAY", 0)
    from conftest import new_interview
    iid = new_interview(client)
    client.post(f"/api/interviews/{iid}/responses/typed", json={"sentence_no": 1, "text": "x"})
    gemini.extraction = "down"
    r = client.post(f"/api/interviews/{iid}/assess")
    assert r.status_code == 503 and "limit" not in r.json()["detail"]       # got past any cap


def test_the_day_turns_over_at_midnight_in_nairobi(invite, fake_assess, monkeypatch, clean_usage):
    monkeypatch.setattr(config, "PILOT_MAX_SUBMISSIONS_PER_MEMBER", 1)
    c, a, mid = applied()
    p = start_practice(c, a["id"])
    answer_all(c, p["id"])
    assert c.post(f"/api/me/practice/{p['id']}/submit").status_code == 200
    assert c.post(f"/api/me/applications/{a['id']}/practice", json={"language": "kik"}).status_code == 429
    monkeypatch.setattr(pilot, "nairobi_today", lambda: nairobi_today() + timedelta(days=1))
    assert c.post(f"/api/me/applications/{a['id']}/practice", json={"language": "kik"}).status_code == 201


def test_nairobi_day_is_not_the_utc_day(monkeypatch):
    """At 22:30 UTC it is already tomorrow at the branch."""
    import chamapro.api.db as dbmod

    class Late(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 11, 4, 22, 30, tzinfo=timezone.utc).astimezone(tz)
    monkeypatch.setattr(dbmod, "datetime", Late)
    assert dbmod.nairobi_today() == date(2026, 11, 5)


def test_the_cap_holds_when_requests_arrive_together(monkeypatch, clean_usage):
    monkeypatch.setattr(config, "PILOT_MAX_SUBMISSIONS_PER_MEMBER", 3)
    monkeypatch.setattr(config, "PILOT_MAX_ASSESSMENTS_PER_DAY", 100)
    ok, gate = [], threading.Barrier(8)

    def take():
        gate.wait()
        with SessionLocal() as db:
            try:
                pilot.reserve_submission(db, 999_000)
                ok.append(True)
            except main.HTTPException:
                pass
    threads = [threading.Thread(target=take) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(ok) == 3


def test_release_gives_both_allowances_back(monkeypatch, clean_usage):
    with SessionLocal() as db:
        day = pilot.reserve_submission(db, 999_001)
        assert pilot.used_today(db, "all") == 1
        pilot.release_submission(db, 999_001, day)
        assert pilot.used_today(db, "all") == 0
        assert pilot.used_today(db, "member:999001") == 0


# --- System Usability Scale ----------------------------------------------------------------------------

@pytest.mark.parametrize("answers, score", [
    ([3] * 10, 50.0), ([5, 1] * 5, 100.0), ([1, 5] * 5, 0.0), ([5] * 10, 50.0), ([1] * 10, 50.0),
    ([4, 2, 4, 2, 4, 2, 4, 2, 4, 2], 75.0), ([5, 2, 4, 1, 4, 2, 5, 1, 4, 2], 85.0)])
def test_sus_scoring(answers, score):
    assert pilot.sus_score(answers) == score


def test_sus_is_stored_with_its_score_after_submitting(invite, fake_assess):
    c, _, p, mid = ready_practice()
    r = c.post(f"/api/me/practice/{p['id']}/sus", json={"answers": [3] * 10})
    assert r.status_code == 409 and "after" in r.json()["detail"]
    c.post(f"/api/me/practice/{p['id']}/submit")
    answers = [5, 2, 4, 1, 4, 2, 5, 1, 4, 2]
    r = c.post(f"/api/me/practice/{p['id']}/sus", json={"answers": answers, "comment": " Easy enough. "})
    assert r.status_code == 204 and r.content == b""               # the score goes to no member
    assert c.get(f"/api/me/practice/{p['id']}").json()["sus_answered"] is True
    assert c.post(f"/api/me/practice/{p['id']}/sus", json={"answers": answers}).status_code == 409
    with SessionLocal() as db:
        row = db.scalar(select(SusResponse).where(SusResponse.interview_id == p["id"]))
        assert (row.answers, row.score, row.comment, row.member_id) == (answers, 85.0, "Easy enough.", mid)


@pytest.mark.parametrize("answers", [[3] * 9, [3] * 11, [0] + [3] * 9, [6] + [3] * 9, []])
def test_sus_needs_ten_answers_on_the_scale(invite, fake_assess, answers):
    c, _, p, _ = ready_practice()
    c.post(f"/api/me/practice/{p['id']}/submit")
    assert c.post(f"/api/me/practice/{p['id']}/sus", json={"answers": answers}).status_code == 422


def test_sus_is_optional(invite, fake_assess):
    c, _, p, _ = ready_practice()
    assert c.post(f"/api/me/practice/{p['id']}/submit").json()["sus_answered"] is False


# --- SACCO events -------------------------------------------------------------------------------------------

def event_body(**over):
    d = nairobi_today() + timedelta(days=5)
    return {"title": "Annual General Meeting", "event_type": "agm", "date": d.isoformat(),
            "time": "10:00", "location": "Branch hall", "description": "Bring your passbook.", **over}


def test_staff_create_change_and_delete_events_and_each_is_audited(client):
    r = client.post("/api/events", json=event_body())
    assert r.status_code == 201, r.text
    e = r.json()
    assert datetime.fromisoformat(e["starts_at"]).astimezone(config.NAIROBI).hour == 10
    r = client.put(f"/api/events/{e['id']}", json=event_body(title="AGM 2026", time="11:30"))
    assert r.status_code == 200 and r.json()["title"] == "AGM 2026"
    assert client.delete(f"/api/events/{e['id']}").status_code == 204
    assert e["id"] not in {x["id"] for x in client.get("/api/events").json()}
    with SessionLocal() as db:
        rows = db.scalars(select(AuditLog).where(AuditLog.entity == "sacco_event",
                                                 AuditLog.entity_id == e["id"]).order_by(AuditLog.id)).all()
    assert [r.action for r in rows] == ["event.create", "event.update", "event.delete"]
    assert sorted(rows[1].details["fields"]) == ["starts_at", "title"]


def test_past_events_drop_off_by_themselves(client, invite):
    c, _, _ = volunteer()
    e = client.post("/api/events", json=event_body()).json()
    assert e["id"] in {x["id"] for x in client.get("/api/events").json()}
    assert e["id"] in {x["id"] for x in c.get("/api/me/home").json()["events"]}
    with SessionLocal() as db:
        db.get(SaccoEvent, e["id"]).starts_at = utcnow() - timedelta(minutes=1)
        db.commit()
    assert e["id"] not in {x["id"] for x in client.get("/api/events").json()}
    assert e["id"] not in {x["id"] for x in c.get("/api/me/home").json()["events"]}


@pytest.mark.parametrize("over", [
    {"online_link": "javascript:alert(1)"}, {"online_link": "data:text/html,hi"},
    {"online_link": "example.com"}, {"event_type": "party"}, {"title": "  "}, {"time": "25:00"},
    {"date": "2020-01-01"}])
def test_bad_events_are_refused(client, over):
    assert client.post("/api/events", json=event_body(**over)).status_code == 422


def test_online_links_may_be_https(client):
    r = client.post("/api/events", json=event_body(online_link="https://meet.example/agm", location=None))
    assert r.status_code == 201 and r.json()["online_link"] == "https://meet.example/agm"


def test_members_read_events_but_cannot_change_them(client, invite):
    c, _, _ = volunteer()
    e = client.post("/api/events", json=event_body()).json()
    assert c.get("/api/events").status_code == 200
    assert c.post("/api/events", json=event_body()).status_code == 403
    assert c.put(f"/api/events/{e['id']}", json=event_body()).status_code == 403
    assert c.delete(f"/api/events/{e['id']}").status_code == 403


def test_member_home_brings_the_three_together(invite, client):
    c, a, _ = applied()
    client.post("/api/events", json=event_body(title="Member meeting", event_type="member_meeting"))
    home = c.get("/api/me/home").json()
    assert home["next_interview"]["application_id"] == a["id"]
    assert [x["id"] for x in home["applications"]] == [a["id"]]
    assert len(home["events"]) <= 5 and home["events"]


# --- The admin's pilot page -------------------------------------------------------------------------------------

def read_csv(r):
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/csv")
    return list(csv.reader(io.StringIO(r.content.decode("utf-8-sig"))))


def test_pilot_figures(invite, admin_client, fake_assess):
    before = admin_client.get("/api/admin/pilot").json()
    c, a, p, _ = ready_practice()
    me = c.get("/api/me/member").json()
    c.post(f"/api/me/practice/{p['id']}/submit")
    c.post(f"/api/me/practice/{p['id']}/sus", json={"answers": [5, 1] * 5, "comment": "Very clear."})
    start_practice(c, a["id"], "en")
    st = admin_client.get("/api/admin/pilot").json()
    assert st["volunteers"] == before["volunteers"] + 1
    assert st["practice_by_language"]["kik"] == before["practice_by_language"]["kik"] + 1
    assert st["practice_by_language"]["en"] == before["practice_by_language"]["en"] + 1
    assert st["completed_assessments"] == before["completed_assessments"] + 1
    assert st["answers_total"] == before["answers_total"] + EIGHT
    row = next(m for m in st["answers_per_member"] if m["member_no"] == me["member_no"])
    assert (row["answers"], row["interviews"]) == (EIGHT, 2)
    assert st["sus_n"] == before["sus_n"] + 1 and st["sus_mean"] is not None
    assert st["comments"][0]["comment"] == "Very clear." and st["comments"][0]["member_no"] == me["member_no"]


def test_staff_practice_interviews_and_seeded_members_are_not_volunteers(invite, admin_client, client):
    from conftest import new_interview
    before = admin_client.get("/api/admin/pilot").json()
    new_interview(client, mode="practice")
    new_member()
    assert admin_client.get("/api/admin/pilot").json() == before


def test_pilot_exports(invite, admin_client, fake_assess):
    c, _, p, _ = ready_practice()
    me = c.get("/api/me/member").json()
    c.post(f"/api/me/practice/{p['id']}/submit")
    c.post(f"/api/me/practice/{p['id']}/sus", json={"answers": [3] * 10, "comment": "=HYPERLINK(\"x\")"})

    rows = read_csv(admin_client.get("/api/admin/pilot/export/aggregates.csv"))
    assert rows[0] == ["section", "key", "value"]
    assert ["answers_per_member", me["member_no"], str(EIGHT)] in rows
    assert ["comment", me["member_no"], "'=HYPERLINK(\"x\")"] in rows        # never a live formula

    r = admin_client.get("/api/admin/pilot/export/transcripts.csv")
    assert "attachment" in r.headers["content-disposition"]
    rows = read_csv(r)
    header, body = rows[0], [x for x in rows[1:] if x[2] == str(p["id"])]
    assert len(body) == EIGHT and body[0][header.index("transcript")] == "answer 1"
    assert not any("audio" in h for h in header)
    assert ".wav" not in r.text and "+254" not in r.text and me["full_name"] not in r.text
    with SessionLocal() as db:
        exported = db.scalars(select(AuditLog).where(AuditLog.action == "pilot.export")).all()
    assert {e.details["export"] for e in exported} == {"aggregates", "transcripts"}


@pytest.mark.parametrize("cell, want", [("=1+1", "'=1+1"), ("+254", "'+254"), ("-1", "'-1"), ("@x", "'@x"),
                                        ("plain", "plain"), (3, 3), ("", "")])
def test_csv_cells_cannot_become_formulas(cell, want):
    assert pilot.csv_cell(cell) == want


@pytest.mark.parametrize("path", ["/api/admin/pilot", "/api/admin/pilot/export/aggregates.csv",
                                  "/api/admin/pilot/export/transcripts.csv"])
def test_the_pilot_page_is_for_admins(client, path, invite):
    assert client.get(path).status_code == 403
    c, _, _ = volunteer()
    assert c.get(path).status_code == 403
