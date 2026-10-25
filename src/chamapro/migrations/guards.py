"""Dialect-specific SQL shared by the migrations: tables the database itself
refuses to change, and row-level security on PostgreSQL.

SQLite: a BEFORE UPDATE and a BEFORE DELETE trigger that RAISE(ABORT).
PostgreSQL: the same two row triggers plus one BEFORE TRUNCATE (which skips
row triggers), all calling one function that raises with SQLSTATE 23000, so
both databases surface it as an IntegrityError carrying the same message.
"""
from __future__ import annotations

from alembic import op

PG_FUNCTION = """
CREATE OR REPLACE FUNCTION chamapro_reject_change() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION '%', TG_ARGV[0] USING ERRCODE = 'integrity_constraint_violation';
END
$$
"""


def _dialect() -> str:
    return op.get_context().dialect.name


def reject_changes(table: str, message: str) -> None:
    """Make `table` append-only: UPDATE and DELETE (and TRUNCATE) fail with `message`."""
    assert "'" not in message
    if _dialect() == "sqlite":
        for when in ("UPDATE", "DELETE"):
            op.execute(f"CREATE TRIGGER IF NOT EXISTS {table}_no_{when.lower()} "
                       f"BEFORE {when} ON {table} "
                       f"BEGIN SELECT RAISE(ABORT, '{message}'); END")
        return
    op.execute(PG_FUNCTION)
    for when, level in (("UPDATE", "ROW"), ("DELETE", "ROW"), ("TRUNCATE", "STATEMENT")):
        name = f"{table}_no_{when.lower()}"
        op.execute(f"DROP TRIGGER IF EXISTS {name} ON {table}")
        op.execute(f"CREATE TRIGGER {name} BEFORE {when} ON {table} FOR EACH {level} "
                   f"EXECUTE FUNCTION chamapro_reject_change('{message}')")


def allow_changes(table: str) -> None:
    """Undo reject_changes (downgrades only)."""
    whens = ("update", "delete") if _dialect() == "sqlite" else ("update", "delete", "truncate")
    for when in whens:
        on = "" if _dialect() == "sqlite" else f" ON {table}"
        op.execute(f"DROP TRIGGER IF EXISTS {table}_no_{when}{on}")


def private_table(table: str) -> None:
    """PostgreSQL: enable row-level security with no policies. Supabase
    publishes the public schema through its Data API to anyone holding the
    project's anon key; with RLS on and no policy, those roles see nothing.
    The backend connects as the table owner, which RLS does not restrict."""
    if _dialect() == "postgresql":
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
