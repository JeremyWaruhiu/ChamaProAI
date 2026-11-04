"""SACCO activities: AGMs, meetings, training, loan deadlines. Staff create and
change them; everyone signed in sees the upcoming ones. An event drops off by
itself when its time has passed: the list only ever asks for later ones. Every
change is an audit row (ids and field names only, as for members)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Response as HTTPResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit
from . import schemas as s
from .auth import current_user, require_officer
from .bookings import slot_start
from .db import SaccoEvent, User, get_db, utcnow

ERRORS = {code: {"model": s.Error} for code in (401, 403, 404, 422)}
router = APIRouter(prefix="/api/events", responses=ERRORS)

FIELDS = ("title", "event_type", "starts_at", "location", "online_link", "description")


def upcoming(db: Session, limit: int = 50) -> list[SaccoEvent]:
    return list(db.scalars(select(SaccoEvent).where(SaccoEvent.starts_at >= utcnow())
                           .order_by(SaccoEvent.starts_at, SaccoEvent.id).limit(limit)))


def values(body: s.EventIn) -> dict:
    start = slot_start(body.date, body.time)
    if start <= utcnow():
        raise HTTPException(422, "date: an event cannot be set in the past")
    return {"title": body.title, "event_type": body.event_type, "starts_at": start,
            "location": body.location, "online_link": body.online_link,
            "description": body.description}


@router.get("", response_model=list[s.EventOut])
def list_events(limit: int = Query(50, ge=1, le=200), db: Session = Depends(get_db),
                _: User = Depends(current_user)):
    return upcoming(db, limit)


@router.post("", status_code=201, response_model=s.EventOut)
def create_event(body: s.EventIn, db: Session = Depends(get_db),
                 user: User = Depends(require_officer)):
    e = SaccoEvent(**values(body), created_by=user.id)
    db.add(e)
    db.flush()
    audit.record(db, user, "event.create", "sacco_event", e.id, event_type=e.event_type)
    db.commit()
    return e


def get_event(db: Session, event_id: int) -> SaccoEvent:
    e = db.get(SaccoEvent, event_id)
    if e is None:
        raise HTTPException(404, f"event {event_id} not found")
    return e


@router.put("/{event_id}", response_model=s.EventOut)
def update_event(event_id: int, body: s.EventIn, db: Session = Depends(get_db),
                 user: User = Depends(require_officer)):
    e = get_event(db, event_id)
    new = values(body)
    changed = sorted(k for k in FIELDS if getattr(e, k) != new[k])
    if changed:
        for k in changed:
            setattr(e, k, new[k])
        e.updated_at = utcnow()
        audit.record(db, user, "event.update", "sacco_event", e.id, fields=changed)
        db.commit()
    return e


@router.delete("/{event_id}", status_code=204)
def delete_event(event_id: int, db: Session = Depends(get_db),
                 user: User = Depends(require_officer)):
    e = get_event(db, event_id)
    db.delete(e)
    audit.record(db, user, "event.delete", "sacco_event", event_id, event_type=e.event_type)
    db.commit()
    return HTTPResponse(status_code=204)
