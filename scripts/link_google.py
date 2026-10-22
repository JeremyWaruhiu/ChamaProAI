"""Link or unlink a Google account (email) on an existing dashboard user.

    python scripts/link_google.py admin you@example.com    # link
    python scripts/link_google.py admin --clear            # unlink
    python scripts/link_google.py admin                    # show the current link

A linked user may "Sign in with Google" with that account. Google sign-in only
signs in users who already exist; it never creates one. Unlinking does not end
sessions already signed in; they expire within 8 hours.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import select

from chamapro.api.db import SessionLocal, User, init_db

sys.path.insert(0, str(Path(__file__).resolve().parent))
from create_user import check_email  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("username")
    ap.add_argument("email", nargs="?", help="Google account email to link")
    ap.add_argument("--clear", action="store_true", help="remove the linked email")
    a = ap.parse_args()
    if a.clear and a.email:
        ap.error("give an email or --clear, not both")

    init_db()
    with SessionLocal() as db:
        user = db.scalar(select(User).where(User.username == a.username))
        if user is None:
            sys.exit(f"no user {a.username!r}; create it first with scripts/create_user.py")
        if a.clear:
            user.email = None
            db.commit()
            print(f"unlinked Google sign-in from {user.username!r}")
        elif a.email:
            user.email = check_email(db, a.email, user.username)
            db.commit()
            print(f"linked {user.username!r} ({user.role}) to Google account {user.email}")
        else:
            print(f"{user.username!r} ({user.role}): "
                  + (f"linked to {user.email}" if user.email else "no Google account linked"))


if __name__ == "__main__":
    main()
