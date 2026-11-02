"""Users' display names; a seed tag on the rows scripts/seed_demo.py creates.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-02

ADD COLUMN only, every column nullable: existing rows keep every value and
read with no display name and no seed tag. users.display_name is the name the
dashboard shows beside the role (the username stays the login). seed_tag is
never sent to a browser: it is how the seeder finds its own users, members
and applicants again, so none of them has to carry a name that says "demo".
No table with a trigger is touched.
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None

SEEDED = ("users", "members", "applicants")


def upgrade() -> None:
    op.add_column("users", sa.Column("display_name", sa.String(120)))
    for table in SEEDED:
        op.add_column(table, sa.Column("seed_tag", sa.String(40)))
        op.create_index(f"ix_{table}_seed_tag", table, ["seed_tag"])


def downgrade() -> None:
    # SQLite 3.35+ drops a column in place; no trigger fires, no row changes.
    for table in reversed(SEEDED):
        op.drop_index(f"ix_{table}_seed_tag", table)
        op.drop_column(table, "seed_tag")
    op.drop_column("users", "display_name")
