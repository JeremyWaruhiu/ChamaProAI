"""Give users new random passwords, print them once, and sign them out everywhere.

    python scripts/reset_passwords.py wanjiru njeri officer1
    python scripts/reset_passwords.py --seeded        # every user the seeders made

The database is the one in DATABASE_URL (from the environment, else .env, else the
SQLite file), the same one the API uses. The script names it and asks you to type its
host back before changing anything; nothing changes if the input is not a terminal.

Each password is made here with the secrets module and hashed with the API's own
hash_password. It is printed once, after the change is committed, and stored nowhere:
not in a file, not in the audit log, not in the database. Copy them as they appear.

All of it is one transaction: every named user exists or nothing changes. Each reset
user's sessions end, so anyone signed in with an old password is signed out, and the
audit log gets one user.reset_password row per user (no password in it).

--seeded means every user with a seed_tag (scripts/seed_demo.py and seed_members.py set
it), whatever its prefix. The system user, who has no password, is never touched.
The schema needs no particular revision: only users, sessions and audit_log are used.
"""
from __future__ import annotations

import argparse
import secrets
import sys

from sqlalchemy import delete, select

from chamapro.api import audit
from chamapro.api.auth import hash_password
from chamapro.api.db import SYSTEM_ROLE, AuthSession, SessionLocal, User, engine

PASSWORD_BYTES = 15       # 20 URL-safe characters


def target() -> str:
    """What to type back: the host for a server, the file for SQLite."""
    return engine.url.host or engine.url.database or str(engine.url)


def chosen_users(db, names: list[str], seeded: bool) -> list[User]:
    if seeded:
        users = db.scalars(select(User).where(User.seed_tag.is_not(None), User.role != SYSTEM_ROLE)
                           .order_by(User.username)).all()
        if not users:
            sys.exit("no seeded users in this database; nothing changed")
        return list(users)
    users = db.scalars(select(User).where(User.username.in_(names))).all()
    missing = sorted(set(names) - {u.username for u in users})
    if missing:
        sys.exit(f"no such user: {', '.join(missing)}; nothing changed")
    if system := [u.username for u in users if u.role == SYSTEM_ROLE]:
        sys.exit(f"{', '.join(system)} is the system user, who never signs in; nothing changed")
    return sorted(users, key=lambda u: u.username)


def confirmed(where: str, users: list[User]) -> bool:
    print(f"Database: {engine.url.render_as_string(hide_password=True)}\n")
    print(f"New passwords for {len(users)} user(s), each signed out everywhere:")
    for u in users:
        print(f"    {u.username:<24} {u.role:<8}" + ("" if u.is_active else " (deactivated)"))
    print()
    if not sys.stdin.isatty():
        print("not a terminal: nothing changed", file=sys.stderr)
        return False
    try:
        return input(f"Type {where!r} to go on: ").strip() == where
    except EOFError:
        return False


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("usernames", nargs="*", help="the users to reset")
    ap.add_argument("--seeded", action="store_true", help="every user with a seed_tag")
    a = ap.parse_args()
    if bool(a.usernames) == a.seeded:
        ap.error("name the users, or give --seeded, not both")

    with SessionLocal() as db:
        users = chosen_users(db, list(dict.fromkeys(a.usernames)), a.seeded)
        if not confirmed(target(), users):
            sys.exit("nothing changed")
        passwords = {}
        for u in users:
            passwords[u.username] = secrets.token_urlsafe(PASSWORD_BYTES)
            u.password_hash = hash_password(passwords[u.username])
            db.execute(delete(AuthSession).where(AuthSession.user_id == u.id))
            audit.record(db, None, "user.reset_password", "user", u.id, via="reset_passwords.py")
        db.commit()

    print("\nNew passwords, shown once and saved nowhere:\n")
    for name, password in passwords.items():
        print(f"    {name:<24} {password}")
    print()


if __name__ == "__main__":
    main()
