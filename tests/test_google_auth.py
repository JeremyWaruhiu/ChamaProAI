"""Sign in with Google: linked users only, never account creation.

Google's verifier is replaced by FakeGoogle, so nothing touches the network.
FakeGoogle behaves like google.oauth2.id_token.verify_oauth2_token: it raises
ValueError for an unknown token or a wrong audience and returns the claims
otherwise.
"""
import os
import secrets
import sqlite3
import subprocess
import sys

import pytest
from google.auth import exceptions as gexc
from google.oauth2 import id_token
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from chamapro import config
from chamapro.api import auth
from chamapro.api.db import AuthSession, SessionLocal, User

from conftest import PASSWORDS, add_user
from test_auth import run_create_user

CLIENT_ID = "test-client.apps.googleusercontent.com"   # a fake, for these tests only
GOOGLE = "/api/auth/google"


class FakeGoogle:
    def __init__(self):
        self.tokens: dict[str, dict] = {}
        self.calls = 0
        self.down = False

    def token(self, email, **claims):
        cred = secrets.token_urlsafe(24)
        self.tokens[cred] = {"iss": "https://accounts.google.com", "aud": CLIENT_ID,
                             "email": email, "email_verified": True, "sub": secrets.token_hex(8),
                             **claims}
        return cred

    def __call__(self, credential, request, audience=None, clock_skew_in_seconds=0):
        self.calls += 1
        if self.down:
            raise gexc.TransportError("Could not fetch certificates")
        claims = self.tokens.get(credential)
        if claims is None:
            raise ValueError("Could not verify token signature")
        if audience is not None and claims["aud"] != audience:
            raise ValueError(f"Token has wrong audience {claims['aud']}, expected {audience}")
        return dict(claims)


@pytest.fixture
def google(monkeypatch):
    fake = FakeGoogle()
    monkeypatch.setattr(id_token, "verify_oauth2_token", fake)
    monkeypatch.setattr(config, "GOOGLE_CLIENT_ID", CLIENT_ID)
    return fake


@pytest.fixture
def linked(client):
    """An officer with a linked Google email, stored in mixed case on purpose."""
    name = "g_" + secrets.token_hex(4)
    email = f"{name}@Example.org"
    add_user(name, secrets.token_urlsafe(16))
    with SessionLocal() as db:
        db.scalar(select(User).where(User.username == name)).email = email
        db.commit()
    return name, email.lower()


def user_count():
    with SessionLocal() as db:
        return db.scalar(select(func.count(User.id)))


def assert_generic_401(r):
    assert r.status_code == 401
    assert r.json() == {"detail": auth.BAD_LOGIN}
    assert auth.COOKIE not in r.cookies


# --- Configuration -------------------------------------------------------------------

def test_config_reports_the_client_id(anon_client, monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_CLIENT_ID", CLIENT_ID)
    assert anon_client.get("/api/auth/config").json() == {"google_client_id": CLIENT_ID}


def test_config_is_null_when_not_configured(anon_client, monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_CLIENT_ID", None)
    assert anon_client.get("/api/auth/config").json() == {"google_client_id": None}


def test_google_disabled_without_client_id(anon_client, google, linked, monkeypatch):
    monkeypatch.setattr(config, "GOOGLE_CLIENT_ID", None)
    r = anon_client.post(GOOGLE, json={"credential": google.token(linked[1])})
    assert r.status_code == 404
    assert "not configured" in r.json()["detail"] and "GOOGLE_CLIENT_ID" in r.json()["detail"]
    assert google.calls == 0


# --- Signing in -------------------------------------------------------------------------

def test_linked_user_signs_in(anon_client, google, linked):
    name, email = linked
    r = anon_client.post(GOOGLE, json={"credential": google.token(email)})
    assert r.status_code == 200
    assert r.json() == {"username": name, "role": "officer"}
    cookie = r.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/api" in cookie
    assert f"Max-Age={config.SESSION_HOURS * 3600}" in cookie
    assert anon_client.get("/api/auth/me").json() == {"username": name, "role": "officer"}
    assert anon_client.get("/api/interviews").status_code == 200


def test_email_match_ignores_case(anon_client, google, linked):
    name, email = linked
    r = anon_client.post(GOOGLE, json={"credential": google.token(email.upper())})
    assert r.status_code == 200 and r.json()["username"] == name


def test_session_records_the_method(anon_client, google, linked):
    token = anon_client.post(GOOGLE, json={"credential": google.token(linked[1])}).cookies[auth.COOKIE]
    with SessionLocal() as db:
        s = db.get(AuthSession, auth.token_hash(token))
        assert s.auth_method == "google"
        assert (s.expires_at - s.created_at).total_seconds() == config.SESSION_HOURS * 3600


def test_password_session_records_its_method(anon_client):
    token = anon_client.post("/api/auth/login", json={
        "username": "officer1", "password": PASSWORDS["officer1"]}).cookies[auth.COOKIE]
    with SessionLocal() as db:
        assert db.get(AuthSession, auth.token_hash(token)).auth_method == "password"


def test_role_comes_from_the_linked_user(anon_client, google):
    name, email = "gadmin_" + secrets.token_hex(4), f"boss{secrets.token_hex(3)}@example.org"
    add_user(name, secrets.token_urlsafe(16), role="admin")
    with SessionLocal() as db:
        db.scalar(select(User).where(User.username == name)).email = email
        db.commit()
    r = anon_client.post(GOOGLE, json={"credential": google.token(email)})
    assert r.json() == {"username": name, "role": "admin"}


# --- Refusals: all the same generic 401, and no account is ever created --------------------

def test_unlinked_email_is_401_and_creates_nobody(anon_client, google):
    before = user_count()
    r = anon_client.post(GOOGLE, json={"credential": google.token("stranger@example.org")})
    assert_generic_401(r)
    assert user_count() == before
    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.email == "stranger@example.org")) is None


def test_same_message_as_a_wrong_password(anon_client, google):
    google_401 = anon_client.post(GOOGLE, json={"credential": google.token("nobody@example.org")})
    password_401 = anon_client.post("/api/auth/login", json={"username": "officer1", "password": "wrong-one"})
    assert google_401.json() == password_401.json()


def test_unverified_email_is_401(anon_client, google, linked):
    assert_generic_401(anon_client.post(
        GOOGLE, json={"credential": google.token(linked[1], email_verified=False)}))


def test_missing_email_verified_claim_is_401(anon_client, google, linked):
    cred = google.token(linked[1])
    del google.tokens[cred]["email_verified"]
    assert_generic_401(anon_client.post(GOOGLE, json={"credential": cred}))


def test_wrong_audience_is_401(anon_client, google, linked):
    cred = google.token(linked[1], aud="someone-elses-app.apps.googleusercontent.com")
    assert_generic_401(anon_client.post(GOOGLE, json={"credential": cred}))


def test_wrong_audience_is_401_even_if_the_verifier_lets_it_through(anon_client, linked, monkeypatch):
    """Defence in depth: the claims are re-checked after verification."""
    monkeypatch.setattr(config, "GOOGLE_CLIENT_ID", CLIENT_ID)
    monkeypatch.setattr(id_token, "verify_oauth2_token", lambda *a, **k: {
        "iss": "accounts.google.com", "aud": "other-app", "email": linked[1], "email_verified": True})
    assert_generic_401(anon_client.post(GOOGLE, json={"credential": "x"}))


def test_wrong_issuer_is_401(anon_client, google, linked):
    assert_generic_401(anon_client.post(
        GOOGLE, json={"credential": google.token(linked[1], iss="https://evil.example")}))


def test_forged_token_is_401(anon_client, google):
    assert_generic_401(anon_client.post(GOOGLE, json={"credential": "not-a-real-token"}))


def test_inactive_user_is_401(anon_client, google):
    name, email = "gone_" + secrets.token_hex(4), f"gone{secrets.token_hex(3)}@example.org"
    add_user(name, secrets.token_urlsafe(16), active=False)
    with SessionLocal() as db:
        db.scalar(select(User).where(User.username == name)).email = email
        db.commit()
    assert_generic_401(anon_client.post(GOOGLE, json={"credential": google.token(email)}))


def test_google_unreachable_is_503(anon_client, google, linked):
    google.down = True
    r = anon_client.post(GOOGLE, json={"credential": google.token(linked[1])})
    assert r.status_code == 503 and "username and password" in r.json()["detail"]


def test_empty_credential_is_422(anon_client, google):
    assert anon_client.post(GOOGLE, json={"credential": ""}).status_code == 422


# --- Rate limit ------------------------------------------------------------------------------

def test_rate_limited_per_email(anon_client, google, linked):
    _, email = linked
    stranger = "lockme@example.org"
    for _ in range(config.LOGIN_MAX_FAILURES):
        assert anon_client.post(GOOGLE, json={"credential": google.token(stranger)}).status_code == 401
    r = anon_client.post(GOOGLE, json={"credential": google.token(stranger)})
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
    # another email, and password sign-in, are unaffected
    assert anon_client.post(GOOGLE, json={"credential": google.token(email)}).status_code == 200
    assert anon_client.post("/api/auth/login", json={
        "username": "officer1", "password": PASSWORDS["officer1"]}).status_code == 200


def test_locked_email_stays_locked_even_once_linked(anon_client, google):
    name, email = "late_" + secrets.token_hex(4), f"late{secrets.token_hex(3)}@example.org"
    for _ in range(config.LOGIN_MAX_FAILURES):
        anon_client.post(GOOGLE, json={"credential": google.token(email)})
    add_user(name, secrets.token_urlsafe(16))
    with SessionLocal() as db:
        db.scalar(select(User).where(User.username == name)).email = email
        db.commit()
    assert anon_client.post(GOOGLE, json={"credential": google.token(email)}).status_code == 429


# --- Storage -------------------------------------------------------------------------------------

def test_email_is_unique_and_lower_cased(client):
    a, b = "u_" + secrets.token_hex(4), "u_" + secrets.token_hex(4)
    email = f"Same{secrets.token_hex(3)}@Example.org"
    add_user(a, secrets.token_urlsafe(16))
    add_user(b, secrets.token_urlsafe(16))
    with SessionLocal() as db:
        ua = db.scalar(select(User).where(User.username == a))
        ua.email = email
        db.commit()
        assert ua.email == email.lower()
        db.scalar(select(User).where(User.username == b)).email = email.upper()
        with pytest.raises(IntegrityError):
            db.commit()


def test_migration_adds_email_and_keeps_rows(tmp_path):
    """An older database (users without email, sessions without auth_method) is upgraded in place."""
    db_file = tmp_path / "old.db"
    con = sqlite3.connect(db_file)
    con.executescript("""
        CREATE TABLE users (id INTEGER PRIMARY KEY, username VARCHAR(64) UNIQUE,
            password_hash VARCHAR(255), role VARCHAR(20), is_active BOOLEAN, created_at DATETIME);
        CREATE TABLE sessions (token_hash VARCHAR(64) PRIMARY KEY, user_id INTEGER,
            created_at DATETIME, expires_at DATETIME);
        INSERT INTO users VALUES (1, 'old_admin', 'scrypt$x', 'admin', 1, '2026-10-01 00:00:00');
    """)
    con.commit()
    con.close()
    code = "from chamapro.api.db import init_db; init_db(); init_db()"
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                       env={**os.environ, "CHAMAPRO_DB": str(db_file)})
    assert r.returncode == 0, r.stderr
    con = sqlite3.connect(db_file)
    assert "email" in {c[1] for c in con.execute("PRAGMA table_info(users)")}
    assert "auth_method" in {c[1] for c in con.execute("PRAGMA table_info(sessions)")}
    assert con.execute("SELECT username, role, email FROM users").fetchall() == [("old_admin", "admin", None)]
    idx = {row[1]: row[2] for row in con.execute("PRAGMA index_list(users)")}
    assert idx.get("ix_users_email") == 1          # unique
    con.close()


# --- Scripts -----------------------------------------------------------------------------------

def run_link(*args):
    return subprocess.run([sys.executable, str(config.SCRIPTS_DIR / "link_google.py"), *args],
                          capture_output=True, text=True)


def test_link_google_sets_shows_and_clears(client):
    name = "l_" + secrets.token_hex(4)
    email = f"{name}@example.org"
    add_user(name, secrets.token_urlsafe(16))

    r = run_link(name, email.upper())
    assert r.returncode == 0, r.stderr
    with SessionLocal() as db:
        assert db.scalar(select(User.email).where(User.username == name)) == email
    assert email in run_link(name).stdout

    assert run_link(name, "--clear").returncode == 0
    with SessionLocal() as db:
        assert db.scalar(select(User.email).where(User.username == name)) is None


def test_link_google_refuses_bad_input(client):
    name, other = "l_" + secrets.token_hex(4), "l_" + secrets.token_hex(4)
    email = f"{other}@example.org"
    add_user(name, secrets.token_urlsafe(16))
    add_user(other, secrets.token_urlsafe(16))
    assert run_link(other, email).returncode == 0

    taken = run_link(name, email)
    assert taken.returncode != 0 and "already linked" in taken.stderr
    assert run_link(name, "not-an-email").returncode != 0
    missing = run_link("no_such_user_" + secrets.token_hex(3), "x@example.org")
    assert missing.returncode != 0 and "create it first" in missing.stderr
    before = user_count()
    run_link("no_such_user_" + secrets.token_hex(3), "y@example.org")
    assert user_count() == before                    # linking never creates a user


def test_create_user_with_email(client):
    name, pw = "c_" + secrets.token_hex(4), secrets.token_urlsafe(16)
    r = run_create_user(name, "--email", f"{name.upper()}@Example.org", stdin=f"{pw}\n{pw}\n")
    assert r.returncode == 0, r.stderr
    with SessionLocal() as db:
        assert db.scalar(select(User.email).where(User.username == name)) == f"{name}@example.org"
