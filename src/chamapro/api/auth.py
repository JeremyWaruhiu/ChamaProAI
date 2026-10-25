"""Sign-in: scrypt password hashes, Google ID tokens, cookie sessions, roles,
a login rate limit.

Passwords use the standard library only. A session cookie carries a random
token; the database keeps only its SHA-256, so a copy of the database cannot be
used to sign in. Google sign-in only signs in users who already exist and have
that email linked: it never creates an account.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import threading
import time
from collections import defaultdict, deque
from datetime import timedelta

from fastapi import Depends, HTTPException, Request
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from chamapro import config

from .db import AuthSession, SessionLocal, User, normalise_email, utcnow

log = logging.getLogger("chamapro.auth")

COOKIE = "chamapro_session"
ROLES = ("admin", "officer", "member")
STAFF_ROLES = ("admin", "officer")
BAD_LOGIN = "incorrect username or password"

# scrypt cost: 16 MiB of memory per hash, about 50 ms on a laptop.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2 ** 14, 8, 1


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P)
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, n, r, p, salt, digest = stored.split("$")
        if scheme != "scrypt":
            return False
        got = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt),
                             n=int(n), r=int(r), p=int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(got.hex(), digest)


# Checked against when the username does not exist, so a wrong username
# takes as long to refuse as a wrong password.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# --- Rate limit -----------------------------------------------------------------

class LoginLimiter:
    """Failed sign-ins per username in a sliding window. In memory: it resets
    when the server restarts, which is acceptable for one branch server."""

    def __init__(self, max_failures: int, window_s: float):
        self.max_failures, self.window_s = max_failures, window_s
        self._fails: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def _prune(self, key: str, now: float) -> deque[float]:
        q = self._fails[key]
        while q and now - q[0] >= self.window_s:
            q.popleft()
        return q

    def retry_after(self, username: str) -> int | None:
        """Seconds until another attempt is allowed, or None if allowed now."""
        key, now = username.lower(), time.monotonic()
        with self._lock:
            q = self._prune(key, now)
            if len(q) < self.max_failures:
                return None
            return max(1, int(self.window_s - (now - q[0])) + 1)

    def fail(self, username: str) -> None:
        with self._lock:
            self._fails[username.lower()].append(time.monotonic())

    def clear(self, username: str | None = None) -> None:
        with self._lock:
            if username is None:
                self._fails.clear()
            else:
                self._fails.pop(username.lower(), None)


limiter = LoginLimiter(config.LOGIN_MAX_FAILURES, config.LOGIN_WINDOW_SECONDS)


# --- Sessions ---------------------------------------------------------------------

def authenticate(db: Session, username: str, password: str) -> User | None:
    user = db.scalar(select(User).where(User.username == username.strip()))
    ok = verify_password(password, user.password_hash if user else _DUMMY_HASH)
    return user if user is not None and ok and user.is_active else None


def start_session(db: Session, user: User, method: str = "password") -> str:
    """Create a session; returns the raw token for the cookie (never stored).
    `method` (password | google) is kept on the session and logged."""
    token = secrets.token_urlsafe(32)
    now = utcnow()
    db.execute(delete(AuthSession).where(AuthSession.expires_at <= now))  # tidy expired ones
    db.add(AuthSession(token_hash=token_hash(token), user_id=user.id, created_at=now,
                       expires_at=now + timedelta(hours=config.SESSION_HOURS), auth_method=method))
    db.commit()
    log.info("sign-in user=%s role=%s method=%s", user.username, user.role, method)
    return token


# --- Google ------------------------------------------------------------------------

GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")


class GoogleTokenRejected(Exception):
    """The credential is not a valid, verified Google ID token for this app."""


class GoogleUnreachable(Exception):
    """Google's signing keys could not be fetched to verify the token."""


def verify_google_credential(credential: str, client_id: str) -> str:
    """The verified, lower-cased email in a Google ID token, or GoogleTokenRejected.

    verify_oauth2_token checks the signature against Google's keys, the expiry,
    the issuer and the audience; the claims are re-checked here so a mocked or
    future-changed verifier cannot loosen them.
    """
    from google.auth import exceptions as gexc
    from google.auth.transport import requests as grequests
    from google.oauth2 import id_token

    try:
        claims = id_token.verify_oauth2_token(credential, grequests.Request(), client_id,
                                              clock_skew_in_seconds=10)
    except gexc.TransportError as e:
        raise GoogleUnreachable(str(e)) from e
    except (ValueError, gexc.GoogleAuthError) as e:
        raise GoogleTokenRejected(str(e)) from e

    aud = claims.get("aud")
    if (aud if isinstance(aud, str) else None) != client_id:
        raise GoogleTokenRejected("wrong audience")
    if claims.get("iss") not in GOOGLE_ISSUERS:
        raise GoogleTokenRejected("wrong issuer")
    if claims.get("email_verified") is not True:
        raise GoogleTokenRejected("email not verified")
    email = normalise_email(claims.get("email"))
    if not email:
        raise GoogleTokenRejected("no email in token")
    return email


def user_by_email(db: Session, email: str) -> User | None:
    """The active user this email is linked to, if any."""
    user = db.scalar(select(User).where(User.email == normalise_email(email)))
    return user if user is not None and user.is_active else None


def end_session(db: Session, token: str | None) -> None:
    if token:
        db.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash(token)))
        db.commit()


def cookie_secure(request: Request) -> bool:
    if config.COOKIE_SECURE is not None:
        return config.COOKIE_SECURE == "1"
    return request.url.hostname not in ("localhost", "127.0.0.1", "::1")


# --- Dependencies ------------------------------------------------------------------

def current_user(request: Request) -> User:
    """The signed-in user, or 401. Its own short database session, so it can be
    used as a route dependency alongside get_db."""
    token = request.cookies.get(COOKIE)
    if not token:
        raise HTTPException(401, "not signed in")
    with SessionLocal() as db:
        s = db.get(AuthSession, token_hash(token))
        if s is None:
            raise HTTPException(401, "not signed in")
        if s.expires_at <= utcnow():
            db.delete(s)
            db.commit()
            raise HTTPException(401, "session expired; sign in again")
        user = s.user
        if not user.is_active:
            raise HTTPException(401, "not signed in")
        db.expunge(user)
        return user


def require_officer(user: User = Depends(current_user)) -> User:
    """Officers and admins: every staff endpoint. Members are refused."""
    if user.role not in STAFF_ROLES:
        raise HTTPException(403, "your account has no role that allows this")
    return user


def require_member(user: User = Depends(current_user)) -> User:
    """A member's own self-service endpoints (/api/me/...)."""
    if user.role != "member":
        raise HTTPException(403, "members only")
    return user


def require_admin(user: User = Depends(current_user)) -> User:
    if user.role != "admin":
        raise HTTPException(403, "administrators only")
    return user
