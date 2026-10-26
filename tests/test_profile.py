"""Your own account: the profile, changing your password, signing out everywhere;
and the practice flag on application lists."""
import secrets

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from chamapro.api import auth
from chamapro.api.db import AuditLog, AuthSession, SessionLocal, User
from chamapro.api.main import app

from conftest import (BASE_URL, PASSWORDS, add_user, assessed, new_application, new_member,
                      signed_in)

PROFILE, PASSWORD, LOGOUT_ALL = "/api/auth/profile", "/api/auth/password", "/api/auth/logout-all"


@pytest.fixture
def me(client):
    """(username, password, two signed-in clients) for a user of its own."""
    name, pw = f"p_{secrets.token_hex(4)}", secrets.token_urlsafe(16)
    add_user(name, pw)
    PASSWORDS[name] = pw
    return name, pw, signed_in(name), signed_in(name)


def sessions_of(name):
    with SessionLocal() as db:
        uid = db.scalar(select(User.id).where(User.username == name))
        return len(db.scalars(select(AuthSession).where(AuthSession.user_id == uid)).all())


def actions_for(name):
    with SessionLocal() as db:
        uid = db.scalar(select(User.id).where(User.username == name))
        return [a.action for a in db.scalars(select(AuditLog).where(AuditLog.entity == "user",
                                                                    AuditLog.entity_id == uid))]


# --- Profile ----------------------------------------------------------------------

def test_profile_describes_the_signed_in_officer(me):
    name, _, c, _ = me
    body = c.get(PROFILE).json()
    assert body["username"] == name and body["role"] == "officer"
    assert body["email"] is None and body["member"] is None
    assert body["signed_in_with"] == "password"
    assert body["active_sessions"] == 2
    assert body["google_sign_in_available"] is False      # no client ID in the test env
    assert set(body) == {"username", "role", "email", "google_sign_in_available", "member",
                         "signed_in_with", "active_sessions", "created_at"}   # never a hash


def test_profile_shows_a_members_own_record(client):
    _, no, mc = new_member()
    body = mc.get(PROFILE).json()
    assert body["role"] == "member"
    assert body["member"] == {"member_no": no, "full_name": f"Fictional {no}"}


def test_profile_needs_sign_in(anon_client):
    assert anon_client.get(PROFILE).status_code == 401


# --- Change password --------------------------------------------------------------

def test_change_password_keeps_this_session_and_ends_the_others(me):
    name, pw, c, other = me
    new = secrets.token_urlsafe(16)
    r = c.post(PASSWORD, json={"current_password": pw, "new_password": new})
    assert r.status_code == 204, r.text
    assert c.get("/api/auth/me").status_code == 200          # still signed in here
    assert other.get("/api/auth/me").status_code == 401      # the other browser is out
    assert sessions_of(name) == 1
    fresh = TestClient(app, base_url=BASE_URL)
    assert fresh.post("/api/auth/login", json={"username": name, "password": pw}).status_code == 401
    assert fresh.post("/api/auth/login", json={"username": name, "password": new}).status_code == 200
    assert "user.change_password" in actions_for(name)


def test_change_password_refuses_a_wrong_current_password(me):
    name, pw, c, other = me
    r = c.post(PASSWORD, json={"current_password": "not-it", "new_password": "x" * 12})
    assert r.status_code == 403
    assert r.json() == {"detail": "your current password is not correct"}
    assert other.get("/api/auth/me").status_code == 200      # nothing ended
    assert "user.change_password" not in actions_for(name)


def test_change_password_is_rate_limited(me):
    _, pw, c, _ = me
    for _ in range(auth.limiter.max_failures):
        c.post(PASSWORD, json={"current_password": "wrong", "new_password": "x" * 12})
    r = c.post(PASSWORD, json={"current_password": pw, "new_password": "y" * 12})
    assert r.status_code == 429 and "Retry-After" in r.headers


@pytest.mark.parametrize("new,why", [("short", "at least 10"), (None, "same")])
def test_change_password_validates_the_new_one(me, new, why):
    _, pw, c, _ = me
    r = c.post(PASSWORD, json={"current_password": pw, "new_password": new or pw})
    assert r.status_code == 422
    assert ("at least 10" in r.json()["detail"]) if why == "at least 10" \
        else r.json()["detail"] == "new_password: must differ from your current password"


# --- Sign out everywhere --------------------------------------------------------------

def test_logout_all_ends_every_session(me):
    name, _, c, other = me
    r = c.post(LOGOUT_ALL)
    assert r.status_code == 204
    assert auth.COOKIE in r.headers.get("set-cookie", "")
    assert c.get("/api/auth/me").status_code == 401
    assert other.get("/api/auth/me").status_code == 401
    assert sessions_of(name) == 0
    assert "user.logout_all" in actions_for(name)


# --- Practice flag on application lists -------------------------------------------------

def test_application_lists_say_which_are_practice(client):
    mid, _, mc = new_member()
    live = new_application(client, mid, assessed(client))
    practice = new_application(client, mid, assessed(client, mode="practice"))
    draft = new_application(client, mid)
    staff = {a["id"]: a["mode"] for a in client.get(f"/api/applications?member_id={mid}").json()}
    assert staff == {live["id"]: "live", practice["id"]: "practice", draft["id"]: None}
    assert client.get(f"/api/applications/{practice['id']}").json()["mode"] == "practice"
    mine = {a["id"]: a["mode"] for a in mc.get("/api/me/applications").json()}
    assert mine == {live["id"]: "live", practice["id"]: "practice", draft["id"]: "live"}
    assert mc.get(f"/api/me/applications/{practice['id']}").json()["mode"] == "practice"
