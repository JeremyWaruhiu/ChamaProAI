"""Whether Supabase's Data API can read anything. It serves the public schema to anyone holding
the project's publishable (anon) key; a table with row-level security on and no policy for those
roles gives them nothing, while the backend, which connects as the table owner, is unaffected.

    python scripts/check_rls.py

Reads the catalogue at DATABASE_URL and changes nothing. Prints each table with RLS off and each
policy that lets anon or authenticated in, and exits 1 if there is any.
"""
from __future__ import annotations

import sys

from sqlalchemy import create_engine, text

from chamapro import config

TABLES = text("""
    SELECT c.relname AS name, c.relrowsecurity AS on_
    FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p') ORDER BY c.relname""")
# A policy with no roles named applies to everyone (PUBLIC), anon and authenticated with them.
POLICIES = text("""
    SELECT tablename, policyname, roles::text AS roles FROM pg_policies
    WHERE schemaname = 'public'
      AND (roles && ARRAY['anon', 'authenticated', 'public']::name[]) ORDER BY tablename, policyname""")


def findings(bind) -> tuple[list[str], list[str], list[str]]:
    """(every table, tables with RLS off, policies letting the Data API's roles in)."""
    with bind.connect() as c:
        rows = c.execute(TABLES).all()
        policies = c.execute(POLICIES).all()
    return ([r.name for r in rows], [r.name for r in rows if not r.on_],
            [f"{p.tablename}: {p.policyname} ({p.roles})" for p in policies])


def main() -> int:
    if not config.DATABASE_URL.startswith("postgresql"):
        print(f"DATABASE_URL is not PostgreSQL ({config.DATABASE_URL.split(':')[0]}): there is no Data API to check.")
        return 2
    bind = create_engine(config.DATABASE_URL, connect_args={"connect_timeout": 10})
    try:
        tables, off, letting_in = findings(bind)
    finally:
        bind.dispose()
    print(f"{bind.url.host}: {len(tables)} tables in public")
    for name in off:
        print(f"  RLS OFF   {name}")
    for line in letting_in:
        print(f"  POLICY    {line}")
    if off or letting_in:
        print(f"{len(off)} without RLS and {len(letting_in)} policies open to anon or authenticated: the publishable key can read these.")
        return 1
    print("All have RLS on, with no policy for anon or authenticated: the publishable key reads nothing.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
