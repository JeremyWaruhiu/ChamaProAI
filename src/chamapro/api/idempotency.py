"""One request per key. A money-moving request claims its key first, in its own
transaction; a second request with that key waits on the database's unique index
until the first commits, and then gets the first one's reply.

    claim -> the work, in the same transaction -> finish -> commit

A refused request rolls back and leaves no key, so it can be sent again once what
stopped it has changed. The same key on a different request is refused.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .db import IdempotencyKey, User
from .ledger import LedgerError


class KeyReused(ValueError):
    """This key already went with a different request."""


def request_hash(scope: str, payload: dict) -> str:
    text = json.dumps([scope, jsonable_encoder(payload)], sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(text.encode()).hexdigest()


def stored_reply(db: Session, row: IdempotencyKey, wanted_hash: str) -> dict | list:
    if row.request_hash != wanted_hash:
        raise KeyReused("this idempotency key was already used for a different request")
    return row.response


def claim(db: Session, actor: User, key: str, scope: str, payload: dict) -> tuple[IdempotencyKey | None, dict | list | None]:
    """(the new row, None) to go ahead, or (None, the stored reply) if already done.
    On SQLite this is also what takes the write lock (ledger.lock_members)."""
    wanted = request_hash(scope, payload)
    actor_id = actor.id
    row = IdempotencyKey(actor_user_id=actor_id, key=key, request_hash=wanted)
    db.add(row)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        done = db.scalar(select(IdempotencyKey).where(IdempotencyKey.actor_user_id == actor_id,
                                                      IdempotencyKey.key == key))
        return None, stored_reply(db, done, wanted)
    return row, None


def finish(row: IdempotencyKey, reply, status_code: int = 200) -> dict | list:
    """Store the reply as the JSON it will be sent as. The caller commits."""
    row.status_code = status_code
    row.response = jsonable_encoder(reply)
    return row.response


def run_once(db: Session, actor: User, key: str, scope: str, payload: dict, work: Callable[[IdempotencyKey], object],
             status_code: int = 201) -> JSONResponse:
    """An endpoint's write, once per key. work may raise LedgerError for what the
    ledger will not take: nothing is kept, and the key stays free to be sent again."""
    try:
        row, stored = claim(db, actor, key, scope, payload)
    except KeyReused as e:
        raise HTTPException(409, str(e)) from None
    if row is None:
        return JSONResponse(stored, status_code=status_code)
    try:
        reply = finish(row, work(row), status_code)
    except LedgerError as e:
        db.rollback()
        raise HTTPException(409, str(e)) from None
    except HTTPException:
        db.rollback()
        raise
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "that conflicts with a record already saved; nothing was changed") from None
    return JSONResponse(reply, status_code=status_code)
