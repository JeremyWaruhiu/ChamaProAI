"""Pin the search path of the trigger function behind the append-only tables.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-09

PostgreSQL only. Supabase's linter flags chamapro_reject_change() as having a mutable
search path ("function_search_path_mutable"): a function that resolves names through the
caller's search_path can be steered to another schema's objects. Its body names nothing
but TG_ARGV and RAISE, so an empty search path changes nothing it does; the function
itself is named with its schema here. guards.PG_FUNCTION now creates it the same way,
so a fresh database, and any later migration that guards another table, keep the setting.

SQLite has no such functions: nothing to do there, and the revision only moves forward.
"""
from __future__ import annotations

from alembic import op

revision = "0008"
down_revision = "0007"
branch_labels = None
depends_on = None

FUNCTION = "public.chamapro_reject_change()"


def upgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        op.execute(f"ALTER FUNCTION {FUNCTION} SET search_path = ''")


def downgrade() -> None:
    if op.get_context().dialect.name == "postgresql":
        op.execute(f"ALTER FUNCTION {FUNCTION} RESET search_path")
