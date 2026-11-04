"""The live statistics of GET /api/results, kept for a minute.

The Model & Evaluation page and the admin overview both load them, and
against Supabase every query is a round trip of ~200 ms or more. A commit that
adds, changes or deletes a row they are counted from (an assessment, a
decision, an interview, a loan application, a guarantor, a member or a ledger
entry) drops the cached copy, so a new assessment or decision shows on the next load. The
figures carry computed_at, the time they were read from the database.

Each uvicorn worker process keeps its own copy; a script writing to the
database from outside the API is seen within TTL_SECONDS.
"""
from __future__ import annotations

import threading
import time
from collections.abc import Callable

from sqlalchemy import event

from .db import (AccountEntry, Assessment, Decision, Guarantor, Interview, LoanApplication, Member,
                 SessionLocal, utcnow)

TTL_SECONDS = 60
COUNTED = (Assessment, Decision, Interview, LoanApplication, Guarantor, Member, AccountEntry)

_lock = threading.Lock()
_cached: tuple[float, dict] | None = None   # (monotonic expiry, figures)
_generation = 0                             # bumped by every invalidate()


def get(compute: Callable[[], dict]) -> dict:
    """The cached figures, or compute()'s with computed_at added."""
    global _cached
    with _lock:
        if _cached is not None and time.monotonic() < _cached[0]:
            return _cached[1]
        generation = _generation
    computed_at = utcnow()
    figures = {**compute(), "computed_at": computed_at.isoformat()}
    with _lock:
        if generation == _generation:   # not if a commit landed while computing
            _cached = (time.monotonic() + TTL_SECONDS, figures)
    return figures


def invalidate() -> None:
    global _cached, _generation
    with _lock:
        _cached, _generation = None, _generation + 1


@event.listens_for(SessionLocal, "after_flush")
def _note_counted_rows(session, _flush_context):
    if any(isinstance(o, COUNTED) for o in (*session.new, *session.dirty, *session.deleted)):
        session.info["live_stats_changed"] = True


@event.listens_for(SessionLocal, "after_commit")
def _drop_after_commit(session):
    if session.info.pop("live_stats_changed", False):
        invalidate()


@event.listens_for(SessionLocal, "after_rollback")
def _nothing_changed(session):
    session.info.pop("live_stats_changed", None)
