"""The audit log: one append-only row per create, state change, decision,
guarantor action and user change, written in the same transaction as the
change itself, so neither can be committed without the other."""
from __future__ import annotations

from sqlalchemy.orm import Session

from .db import AuditLog, User


def record(db: Session, actor: User | None, action: str, entity: str, entity_id: int | None,
           **details) -> AuditLog:
    """Add an audit row to the session; the caller commits. `actor` is None
    only for scripts run from the shell. Never put secrets in details."""
    row = AuditLog(actor_user_id=actor.id if actor is not None else None, action=action,
                   entity=entity, entity_id=entity_id, details=details)
    db.add(row)
    return row
