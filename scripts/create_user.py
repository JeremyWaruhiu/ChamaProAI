"""Create a dashboard user. The password is asked for, never taken as an argument.

    python scripts/create_user.py admin --role admin
    python scripts/create_user.py wanjiru            # role defaults to officer
    python scripts/create_user.py admin --role admin --email you@example.com

--email links a Google account for "Sign in with Google" (also settable later
with scripts/link_google.py). The password is still required: Google sign-in
is an alternative, never the only way in.

There are no default users: the first admin must be created this way.
"""
from __future__ import annotations

import argparse
import getpass
import re
import sys

from sqlalchemy import select

from chamapro.api.auth import ROLES, hash_password
from chamapro.api.db import SessionLocal, User, init_db, normalise_email

MIN_LENGTH = 10
USERNAME = re.compile(r"^[A-Za-z0-9._@-]{3,64}$")
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def check_email(db, email: str | None, username: str) -> str | None:
    """Normalised email, or exit if it is malformed or linked to someone else."""
    email = normalise_email(email)
    if email is None:
        return None
    if len(email) > 254 or not EMAIL.match(email):
        sys.exit(f"not an email address: {email!r}")
    other = db.scalar(select(User.username).where(User.email == email))
    if other is not None and other != username:
        sys.exit(f"{email} is already linked to user {other!r}")
    return email


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("username")
    ap.add_argument("--role", choices=ROLES, default="officer")
    ap.add_argument("--email", help="Google account email to link for Sign in with Google")
    a = ap.parse_args()

    if not USERNAME.match(a.username):
        sys.exit("username: 3-64 characters, letters, digits and . _ @ - only")
    init_db()
    with SessionLocal() as db:
        if db.scalar(select(User.id).where(User.username == a.username)):
            sys.exit(f"user {a.username!r} already exists")
        email = check_email(db, a.email, a.username)

        password = getpass.getpass(f"Password for {a.username} (at least {MIN_LENGTH} characters): ")
        if len(password) < MIN_LENGTH:
            sys.exit(f"password must be at least {MIN_LENGTH} characters; no user created")
        if getpass.getpass("Repeat the password: ") != password:
            sys.exit("passwords do not match; no user created")

        db.add(User(username=a.username, password_hash=hash_password(password), role=a.role,
                    email=email))
        db.commit()
    print(f"created {a.role} {a.username!r}" + (f" linked to Google account {email}" if email else ""))


if __name__ == "__main__":
    main()
