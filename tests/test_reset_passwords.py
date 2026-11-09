"""scripts/reset_passwords.py on the scratch database: new passwords that work, old ones
and old sessions that do not, all or nothing, the system user untouched, nothing stored."""
import io
import secrets
import sys
from contextlib import redirect_stdout
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from chamapro import config
from chamapro.api.auth import hash_password, verify_password
from chamapro.api.db import SYSTEM_USERNAME, AuditLog, AuthSession, SessionLocal, User, utcnow

sys.path.insert(0, str(config.SCRIPTS_DIR))
import reset_passwords  # noqa: E402


def make_user(seed_tag=None, role="officer"):
    name = f"rp_{secrets.token_hex(4)}"
    with SessionLocal() as db:
        u = User(username=name, password_hash=hash_password("old-password-1"), role=role, seed_tag=seed_tag)
        db.add(u)
        db.flush()
        db.add(AuthSession(token_hash=secrets.token_hex(32), user_id=u.id, auth_method="password",
                           created_at=utcnow(), expires_at=utcnow() + timedelta(hours=1)))
        db.commit()
    return name


def run(monkeypatch, *args, typed=None, tty=True):
    monkeypatch.setattr(sys, "argv", ["reset_passwords.py", *args])
    monkeypatch.setattr(sys.stdin, "isatty", lambda: tty)
    monkeypatch.setattr("builtins.input", lambda prompt="": reset_passwords.target() if typed is None else typed)
    out = io.StringIO()
    with redirect_stdout(out):
        reset_passwords.main()
    return out.getvalue()


def printed_passwords(out):
    after = out.split("shown once and saved nowhere:")[1]
    return dict(line.split() for line in after.strip().splitlines())


def user(name):
    with SessionLocal() as db:
        return db.scalar(select(User).where(User.username == name))


def sessions(name):
    with SessionLocal() as db:
        return db.scalar(select(func.count()).select_from(AuthSession).join(User).where(User.username == name))


def test_named_users_get_working_passwords_and_lose_their_sessions(client, monkeypatch):
    a, b, untouched = make_user(), make_user(role="member"), make_user()
    out = run(monkeypatch, a, b)
    new = printed_passwords(out)
    assert set(new) == {a, b}
    for name in (a, b):
        assert verify_password(new[name], user(name).password_hash)
        assert not verify_password("old-password-1", user(name).password_hash)
        assert user(name).password_hash.startswith("scrypt$") and new[name] not in user(name).password_hash
        assert sessions(name) == 0
        assert len(new[name]) >= 20
    assert verify_password("old-password-1", user(untouched).password_hash) and sessions(untouched) == 1
    with SessionLocal() as db:
        rows = db.scalars(select(AuditLog).where(AuditLog.action == "user.reset_password",
                                                 AuditLog.entity_id.in_([user(a).id, user(b).id]))).all()
    assert len(rows) == 2 and all(new[a] not in str(r.details) and new[b] not in str(r.details) for r in rows)


def test_seeded_resets_every_tagged_user_but_not_the_system_user_or_untagged_ones(client, monkeypatch):
    tagged, other_tag, untagged = make_user("demo-db:x"), make_user("seed:discard"), make_user()
    with SessionLocal() as db:
        system_hash = db.scalar(select(User.password_hash).where(User.username == SYSTEM_USERNAME))
    new = printed_passwords(run(monkeypatch, "--seeded"))
    assert {tagged, other_tag} <= set(new) and untagged not in new and SYSTEM_USERNAME not in new
    assert verify_password(new[tagged], user(tagged).password_hash)
    assert verify_password("old-password-1", user(untagged).password_hash)
    with SessionLocal() as db:
        assert db.scalar(select(User.password_hash).where(User.username == SYSTEM_USERNAME)) == system_hash


@pytest.mark.parametrize("args, why", [(["nobody_here"], "no such user"), ([SYSTEM_USERNAME], "system user")])
def test_an_unknown_or_system_name_changes_nothing(client, monkeypatch, args, why):
    real = make_user()
    with pytest.raises(SystemExit, match=why):
        run(monkeypatch, real, *args)
    assert verify_password("old-password-1", user(real).password_hash) and sessions(real) == 1


@pytest.mark.parametrize("typed, tty", [("not-the-target", True), (None, False)])
def test_nothing_changes_unless_the_target_is_typed_back_at_a_terminal(client, monkeypatch, typed, tty):
    real = make_user()
    with pytest.raises(SystemExit, match="nothing changed"):
        out = run(monkeypatch, real, typed=typed, tty=tty)
        assert "shown once" not in out
    assert verify_password("old-password-1", user(real).password_hash) and sessions(real) == 1


def test_names_or_seeded_not_both(monkeypatch):
    for args in ([], ["--seeded", "x"]):
        with pytest.raises(SystemExit):
            run(monkeypatch, *args)
