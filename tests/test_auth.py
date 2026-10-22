"""Sign-in, sessions, roles and the login rate limit."""
import hashlib
import secrets
import subprocess
import sys
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from chamapro import config
from chamapro.api import auth
from chamapro.api.db import AuthSession, Decision, SessionLocal, User, utcnow
from chamapro.api.main import app

from conftest import BASE_URL, PASSWORDS, add_user, needs_classifier, signed_in

LOGIN = "/api/auth/login"


def login(c, username, password):
    return c.post(LOGIN, json={"username": username, "password": password})


@pytest.fixture
def fresh_user(client):
    """A user of its own, so tests that lock or sign out leave the shared ones alone."""
    name, pw = f"user_{secrets.token_hex(4)}", secrets.token_urlsafe(16)
    add_user(name, pw)
    return name, pw


# --- Login ------------------------------------------------------------------------

def test_login_success_sets_a_protected_cookie(anon_client, fresh_user):
    name, pw = fresh_user
    r = login(anon_client, name, pw)
    assert r.status_code == 200
    assert r.json() == {"username": name, "role": "officer"}
    cookie = r.headers["set-cookie"]
    assert cookie.startswith(f"{auth.COOKIE}=")
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie and "Path=/api" in cookie
    assert "Secure" not in cookie                              # localhost
    assert anon_client.get("/api/auth/me").json() == {"username": name, "role": "officer"}


def test_cookie_is_secure_off_localhost(fresh_user):
    name, pw = fresh_user
    c = TestClient(app, base_url="http://branch-server.example")
    r = login(c, name, pw)
    assert r.status_code == 200 and "Secure" in r.headers["set-cookie"]


def test_only_the_token_hash_is_stored(anon_client, fresh_user):
    name, pw = fresh_user
    token = login(anon_client, name, pw).cookies[auth.COOKIE]
    with SessionLocal() as db:
        row = db.get(AuthSession, hashlib.sha256(token.encode()).hexdigest())
        assert row is not None
        assert db.scalar(select(AuthSession).where(AuthSession.token_hash == token)) is None
        assert row.expires_at - row.created_at == timedelta(hours=config.SESSION_HOURS)


def test_password_is_stored_as_salted_scrypt(fresh_user):
    name, pw = fresh_user
    with SessionLocal() as db:
        stored = db.scalar(select(User.password_hash).where(User.username == name))
    assert stored.startswith("scrypt$") and pw not in stored
    assert auth.verify_password(pw, stored)
    assert auth.hash_password(pw) != auth.hash_password(pw)    # fresh salt each time


def test_wrong_password_and_unknown_user_get_the_same_401(anon_client, fresh_user):
    name, _ = fresh_user
    wrong = login(anon_client, name, "not-the-password")
    unknown = login(anon_client, "nobody_" + secrets.token_hex(4), "whatever-it-is")
    assert wrong.status_code == unknown.status_code == 401
    assert wrong.json() == unknown.json() == {"detail": auth.BAD_LOGIN}
    assert auth.COOKIE not in wrong.cookies


def test_inactive_user_cannot_sign_in(anon_client):
    name, pw = "gone_" + secrets.token_hex(4), secrets.token_urlsafe(16)
    add_user(name, pw, active=False)
    r = login(anon_client, name, pw)
    assert r.status_code == 401 and r.json() == {"detail": auth.BAD_LOGIN}


def test_rate_limit_after_five_failures(anon_client, fresh_user):
    name, pw = fresh_user
    for _ in range(config.LOGIN_MAX_FAILURES):
        assert login(anon_client, name, "wrong-password").status_code == 401
    r = login(anon_client, name, pw)                   # even the right password
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) > 0
    # another username is not affected
    assert login(anon_client, "officer1", PASSWORDS["officer1"]).status_code == 200


def test_rate_limit_window_expires(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(auth.time, "monotonic", lambda: now[0])
    lim = auth.LoginLimiter(5, 900)
    for _ in range(5):
        lim.fail("Wanjiru")
    assert lim.retry_after("wanjiru") is not None      # case-insensitive
    now[0] += 900
    assert lim.retry_after("wanjiru") is None


def test_success_resets_the_failure_count(anon_client, fresh_user):
    name, pw = fresh_user
    for _ in range(config.LOGIN_MAX_FAILURES - 1):
        login(anon_client, name, "wrong-password")
    assert login(anon_client, name, pw).status_code == 200
    for _ in range(config.LOGIN_MAX_FAILURES - 1):
        assert login(anon_client, name, "wrong-password").status_code == 401


# --- Sessions ------------------------------------------------------------------------

def test_me_without_a_session_is_401(anon_client):
    assert anon_client.get("/api/auth/me").status_code == 401


def test_expired_session_is_401(anon_client, fresh_user):
    name, pw = fresh_user
    token = login(anon_client, name, pw).cookies[auth.COOKIE]
    with SessionLocal() as db:
        db.execute(update(AuthSession)
                   .where(AuthSession.token_hash == auth.token_hash(token))
                   .values(expires_at=utcnow() - timedelta(seconds=1)))
        db.commit()
    r = anon_client.get("/api/interviews")
    assert r.status_code == 401 and "expired" in r.json()["detail"]
    with SessionLocal() as db:                         # and the stale row is gone
        assert db.get(AuthSession, auth.token_hash(token)) is None


def test_logout_ends_the_session(anon_client, fresh_user):
    name, pw = fresh_user
    token = login(anon_client, name, pw).cookies[auth.COOKIE]
    r = anon_client.post("/api/auth/logout")
    assert r.status_code == 204
    assert f'{auth.COOKIE}=""' in r.headers["set-cookie"] or "Max-Age=0" in r.headers["set-cookie"]
    with SessionLocal() as db:
        assert db.get(AuthSession, auth.token_hash(token)) is None
    # the old token no longer works even if replayed
    replay = TestClient(app, base_url=BASE_URL, cookies={auth.COOKIE: token})
    assert replay.get("/api/auth/me").status_code == 401
    assert anon_client.get("/api/auth/me").status_code == 401


def test_logout_without_a_session_is_harmless(anon_client):
    assert anon_client.post("/api/auth/logout").status_code == 204


def test_forged_token_is_401():
    c = TestClient(app, base_url=BASE_URL, cookies={auth.COOKIE: secrets.token_urlsafe(32)})
    assert c.get("/api/interviews").status_code == 401


# --- Protection and roles ----------------------------------------------------------------

PUBLIC = {("GET", "/api/health"), ("POST", "/api/auth/login"), ("POST", "/api/auth/logout"),
          ("GET", "/api/auth/config"), ("POST", "/api/auth/google")}


def api_routes():
    for r in app.routes:
        path = getattr(r, "path", "")
        for m in getattr(r, "methods", set()) - {"HEAD", "OPTIONS"}:
            if path.startswith("/api/") and (m, path) not in PUBLIC:
                yield m, path


@pytest.mark.parametrize("method,path", sorted(api_routes()))
def test_protected_endpoints_need_sign_in(anon_client, method, path):
    url = path.replace("{interview_id}", "1").replace("{response_id}", "1")
    r = anon_client.request(method, url)
    assert r.status_code == 401, f"{method} {path} -> {r.status_code}"


def test_every_existing_endpoint_is_covered():
    covered = set(api_routes())
    for expected in [("GET", "/api/interviews"), ("POST", "/api/interviews"),
                     ("GET", "/api/questions"), ("GET", "/api/results"),
                     ("GET", "/api/interviews/{interview_id}"),
                     ("POST", "/api/interviews/{interview_id}/responses"),
                     ("POST", "/api/interviews/{interview_id}/assess"),
                     ("POST", "/api/interviews/{interview_id}/decision"),
                     ("GET", "/api/responses/{response_id}/audio"),
                     ("PATCH", "/api/responses/{response_id}"),
                     ("DELETE", "/api/responses/{response_id}"),
                     ("GET", "/api/auth/me")]:
        assert expected in covered


def test_health_stays_public(anon_client):
    assert anon_client.get("/api/health").status_code == 200


def test_officer_is_blocked_from_results(client):
    r = client.get("/api/results")
    assert r.status_code == 403 and r.json() == {"detail": "administrators only"}


def test_admin_reaches_results(admin_client, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "RESULTS_SUMMARY_PATH", tmp_path / "missing.json")
    assert admin_client.get("/api/results").status_code == 404   # past the role check


def test_admin_may_use_officer_endpoints(admin_client):
    assert admin_client.get("/api/interviews").status_code == 200


# --- Who did it ---------------------------------------------------------------------------

def test_decision_records_the_username(client, assessed_interview):
    r = client.post(f"/api/interviews/{assessed_interview}/decision", json={"decision": "refer"})
    assert r.status_code == 201 and r.json()["decided_by"] == "officer1"
    with SessionLocal() as db:
        d = db.scalar(select(Decision).where(Decision.interview_id == assessed_interview))
        assert d.decided_by == "officer1"


def test_admin_decision_records_the_admin(assessed_interview):
    c = signed_in("admin1")
    r = c.post(f"/api/interviews/{assessed_interview}/decision", json={"decision": "approve"})
    assert r.json()["decided_by"] == "admin1"


@needs_classifier
def test_assessment_records_the_username(client, gemini, ready_interview):
    r = client.post(f"/api/interviews/{ready_interview}/assess")
    assert r.status_code == 201, r.text
    assert r.json()["assessed_by"] == "officer1"


def test_rows_from_before_sign_in_read_as_null(client, assessed_interview, state):
    # assessed_interview writes its assessment directly, as an old row would be
    assert state(assessed_interview)["assessment"]["assessed_by"] is None


# --- scripts/create_user.py ---------------------------------------------------------------

def run_create_user(*args, stdin):
    """Run the script with getpass reading stdin (no terminal) and the test database."""
    code = ("import getpass, sys, runpy; getpass.getpass = lambda p='': (print(p, end=''), "
            "sys.stdin.readline().rstrip('\\n'))[1]; sys.argv = ['create_user.py', *sys.argv[1:]]; "
            f"runpy.run_path({str(config.SCRIPTS_DIR / 'create_user.py')!r}, run_name='__main__')")
    return subprocess.run([sys.executable, "-c", code, *args], input=stdin, text=True,
                          capture_output=True)  # inherits CHAMAPRO_DB from conftest


def test_create_user_script(client):
    name, pw = "made_" + secrets.token_hex(4), secrets.token_urlsafe(16)
    r = run_create_user(name, "--role", "admin", stdin=f"{pw}\n{pw}\n")
    assert r.returncode == 0, r.stderr
    assert pw not in r.stdout and pw not in r.stderr
    with SessionLocal() as db:
        u = db.scalar(select(User).where(User.username == name))
    assert u.role == "admin" and u.is_active and auth.verify_password(pw, u.password_hash)

    again = run_create_user(name, stdin=f"{pw}\n{pw}\n")
    assert again.returncode != 0 and "already exists" in again.stderr


def test_create_user_rejects_mismatch_and_short_passwords(client):
    name = "bad_" + secrets.token_hex(4)
    assert run_create_user(name, stdin="abcdefghijkl\nabcdefghijkX\n").returncode != 0
    assert run_create_user(name, stdin="short\nshort\n").returncode != 0
    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.username == name)) is None
