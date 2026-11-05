"""One statement instead of one per table. Writing a decision touches about a dozen tables,
and through the ORM each is its own round trip to Supabase, ~200 ms from Nairobi. So rows are
gathered here, as ordinary mapped objects that stay out of the session, and sent together:

    batch = Batch(db, reserved_ids)     # ids come first, so that rows can point at each other
    batch.give_id(application)
    batch.add(application, ...)
    batch.update(conversation, state="END")
    batch.send()                        # the caller commits, unless it runs in autocommit

On PostgreSQL send() is one statement, a WITH of one INSERT or UPDATE per table, so it is atomic
on its own, and foreign keys are checked at its end, whatever order the rows are in. SQLite cannot
write inside a WITH, so there it is one statement per table, inside the caller's transaction.

An object's values are read at send(), so it can still change until then. A row cannot be both
added and updated in one batch, or updated twice: within one statement neither would see the other.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping

from sqlalchemy import func, insert, inspect, literal, literal_column, select, text, union_all, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value
from sqlalchemy.orm.session import make_transient_to_detached

from .db import one_round_trip


def table_of(obj_or_class) -> str:
    return inspect(obj_or_class if isinstance(obj_or_class, type) else type(obj_or_class)).local_table.name


def sequence_values(table: str, count: int):
    """count new ids for this table, as (table, id) rows to go in a PostgreSQL statement."""
    return select(literal(table).label("t"), func.nextval(f"{table}_id_seq").label("id")) \
        .select_from(func.generate_series(1, count))


def _reserve_sqlite(db: Session, counts: Mapping[str, int]) -> dict[str, list[int]]:
    """Ids past the highest. It holds because the caller has the one write lock (ledger.py)."""
    out = {}
    for table, count in counts.items():
        top = db.execute(text(f'SELECT COALESCE(MAX(id), 0) FROM "{table}"')).scalar()
        out[table] = list(range(top + 1, top + 1 + count))
    return out


def reserve(db: Session, counts: Mapping[str, int]) -> dict[str, list[int]]:
    """counts ids for each table, in one round trip. On PostgreSQL an id reserved and not used is
    simply skipped, as one is after a rollback."""
    wanted = {t: n for t, n in counts.items() if n > 0}
    if not wanted:
        return {}
    if db.get_bind().dialect.name != "postgresql":
        with one_round_trip():
            return _reserve_sqlite(db, wanted)
    rows = db.execute(union_all(*(sequence_values(t, n) for t, n in wanted.items()))).all()
    out: dict[str, list[int]] = {t: [] for t in wanted}
    for table, new_id in rows:
        out[table].append(new_id)
    return out


class Batch:
    def __init__(self, db: Session, ids: Mapping[str, Iterable[int]] | None = None):
        self.db = db
        self.ids = {t: list(v) for t, v in (ids or {}).items()}
        self.rows: list = []
        self.updates: list = []
        self.given: dict[str, int] = {}

    # --- Rows --------------------------------------------------------------------------------

    def give_id(self, obj) -> int:
        """Its primary key now, from what was reserved. More than was reserved costs a round trip."""
        table = table_of(obj)
        if self.ids.get(table):
            obj.id = self.ids[table].pop(0)
        else:   # SQLite cannot see the ones given so far: nothing has been written yet
            with self.db.no_autoflush:
                obj.id = max(reserve(self.db, {table: 1})[table][0], self.given.get(table, 0) + 1)
        self.given[table] = obj.id
        return obj.id

    def add(self, obj) -> None:
        self.rows.append(obj)

    def update(self, obj, **values) -> None:
        """Change an object already in the database. It holds the new values at once, and the
        session will not write them again."""
        mapper = inspect(type(obj))
        for key, value in values.items():
            set_committed_value(obj, key, value)
        key = {column: getattr(obj, mapper.get_property_by_column(column).key) for column in mapper.primary_key}
        self.updates.append(update(mapper.local_table).where(*(column == value for column, value in key.items()))
                            .values({mapper.get_property(k).columns[0].key: v for k, v in values.items()}))

    # --- Sending -----------------------------------------------------------------------------

    def _row(self, obj) -> dict:
        """Every column of it, with the defaults the ORM would have filled in, so that the
        object can be read afterwards as if it had been flushed."""
        clock = self.db.info.get("clock")
        if clock is not None:
            clock.stamp(obj)
        mapper, row = inspect(type(obj)), {}
        for attr in mapper.column_attrs:
            column = attr.columns[0]
            value = getattr(obj, attr.key)
            if value is None and column.default is not None and column.default.is_scalar:
                value = column.default.arg
            elif value is None and column.default is not None and column.default.is_callable:
                value = column.default.arg(None)
            setattr(obj, attr.key, value)
            if value is None and column.primary_key:
                continue        # no id given: the database's own
            row[column.key] = value
        return row

    def _statements(self) -> list:
        tables: dict = {}
        for obj in self.rows:
            tables.setdefault(inspect(type(obj)).local_table, []).append(self._row(obj))
        return [insert(table).values(rows) for table, rows in tables.items()] + self.updates

    def send(self) -> None:
        statements = self._statements()
        self.rows, self.updates = [], []
        if not statements:
            return
        with self.db.no_autoflush:
            if self.db.get_bind().dialect.name == "postgresql" and len(statements) > 1:
                parts = [s.returning(literal_column("1")).cte(f"w{i}") for i, s in enumerate(statements)]
                self.db.execute(select(literal(1)).add_cte(*parts))
                return
            with one_round_trip():
                if self.db.get_bind().dialect.name == "sqlite":
                    # To the commit, as PostgreSQL's are to the end of the statement. Lasts this transaction.
                    self.db.execute(text("PRAGMA defer_foreign_keys = ON"))
                for statement in statements:
                    self.db.execute(statement)

    def attach(self, obj) -> None:
        """Bring a row this batch sent into the session, without asking the database for it."""
        make_transient_to_detached(obj)
        self.db.add(obj)
