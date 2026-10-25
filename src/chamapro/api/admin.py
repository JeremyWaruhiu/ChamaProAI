"""Administration: users and the audit log. Admins only.

An admin cannot deactivate themselves or change their own role, so there is
always at least one active admin. Deactivating a user, resetting their
password or changing their role ends every session they have. No endpoint
returns a password or a hash; audit rows record who changed what, never the
new password.
"""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import audit
from . import schemas as s
from .auth import hash_password, require_admin
from .db import AuditLog, AuthSession, Member, User, get_db, normalise_email

ERRORS = {code: {"model": s.Error} for code in (401, 403, 404, 409, 422)}
router = APIRouter(prefix="/api/admin", responses=ERRORS)


def user_out(db: Session, u: User) -> s.UserOut:
    m = db.scalar(select(Member).where(Member.user_id == u.id))
    return s.UserOut(id=u.id, username=u.username, role=u.role, email=u.email,
                     is_active=u.is_active, created_at=u.created_at,
                     member_id=m.id if m else None, member_no=m.member_no if m else None)


def get_user(db: Session, user_id: int) -> User:
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(404, f"user {user_id} not found")
    return u


def not_self(actor: User, target: User, what: str) -> None:
    if actor.id == target.id:
        raise HTTPException(409, f"you cannot {what} your own account; ask another administrator")


def end_sessions(db: Session, u: User) -> None:
    db.execute(delete(AuthSession).where(AuthSession.user_id == u.id))


def checked_email(db: Session, email: str | None, user_id: int | None) -> str | None:
    email = normalise_email(email)
    if email is None:
        return None
    if not s.EMAIL.match(email):
        raise HTTPException(422, f"email: not an email address: {email!r}")
    other = db.scalar(select(User).where(User.email == email))
    if other is not None and other.id != user_id:
        raise HTTPException(409, f"{email} is already linked to user {other.username!r}")
    return email


def link_member(db: Session, u: User, member_id: int | None, actor: User) -> None:
    current = db.scalar(select(Member).where(Member.user_id == u.id))
    if member_id is None:
        if current is not None:
            current.user_id = None
            audit.record(db, actor, "user.unlink_member", "user", u.id, member_id=current.id)
        return
    if u.role != "member":
        raise HTTPException(422, f"member_id: only a member login can be linked; {u.username!r} "
                                 f"is {u.role}")
    m = db.get(Member, member_id)
    if m is None:
        raise HTTPException(404, f"member {member_id} not found")
    if m.user_id == u.id:
        return
    if m.user_id is not None:
        raise HTTPException(409, f"member {member_id} is already linked to another login")
    if current is not None and current.id != m.id:
        current.user_id = None
        db.flush()
    m.user_id = u.id
    audit.record(db, actor, "user.link_member", "user", u.id, member_id=m.id)


@router.get("/users", response_model=list[s.UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return [user_out(db, u) for u in db.scalars(select(User).order_by(User.username))]


@router.post("/users", status_code=201, response_model=s.UserOut)
def create_user(body: s.UserCreate, db: Session = Depends(get_db),
                actor: User = Depends(require_admin)):
    if db.scalar(select(User.id).where(User.username == body.username)):
        raise HTTPException(409, f"user {body.username!r} already exists")
    u = User(username=body.username, password_hash=hash_password(body.password), role=body.role,
             email=checked_email(db, body.email, None), is_active=True)
    try:
        db.add(u)
        db.flush()
        audit.record(db, actor, "user.create", "user", u.id, role=u.role,
                     google_linked=u.email is not None)
        if body.member_id is not None:
            link_member(db, u, body.member_id, actor)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"user {body.username!r} already exists")
    return user_out(db, u)


@router.post("/users/{user_id}/deactivate", response_model=s.UserOut)
def deactivate_user(user_id: int, db: Session = Depends(get_db),
                    actor: User = Depends(require_admin)):
    u = get_user(db, user_id)
    not_self(actor, u, "deactivate")
    if u.is_active:
        u.is_active = False
        end_sessions(db, u)
        audit.record(db, actor, "user.deactivate", "user", u.id)
        db.commit()
    return user_out(db, u)


@router.post("/users/{user_id}/activate", response_model=s.UserOut)
def activate_user(user_id: int, db: Session = Depends(get_db),
                  actor: User = Depends(require_admin)):
    u = get_user(db, user_id)
    if not u.is_active:
        u.is_active = True
        audit.record(db, actor, "user.activate", "user", u.id)
        db.commit()
    return user_out(db, u)


@router.put("/users/{user_id}/password", response_model=s.UserOut)
def reset_password(user_id: int, body: s.PasswordReset, db: Session = Depends(get_db),
                   actor: User = Depends(require_admin)):
    u = get_user(db, user_id)
    u.password_hash = hash_password(body.password)
    end_sessions(db, u)
    audit.record(db, actor, "user.reset_password", "user", u.id)
    db.commit()
    return user_out(db, u)


@router.put("/users/{user_id}/role", response_model=s.UserOut)
def change_role(user_id: int, body: s.RoleChange, db: Session = Depends(get_db),
                actor: User = Depends(require_admin)):
    u = get_user(db, user_id)
    not_self(actor, u, "change the role of")
    if u.role != body.role:
        audit.record(db, actor, "user.change_role", "user", u.id, **{"from": u.role, "to": body.role})
        u.role = body.role
        end_sessions(db, u)
        db.commit()
    return user_out(db, u)


@router.put("/users/{user_id}/google-email", response_model=s.UserOut)
def link_google_email(user_id: int, body: s.EmailLink, db: Session = Depends(get_db),
                      actor: User = Depends(require_admin)):
    u = get_user(db, user_id)
    email = checked_email(db, body.email, u.id)
    if u.email != email:
        u.email = email
        audit.record(db, actor, "user.google_email", "user", u.id, linked=email is not None)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, f"{email} is already linked to another user")
    return user_out(db, u)


@router.put("/users/{user_id}/member", response_model=s.UserOut)
def set_member(user_id: int, body: s.MemberLink, db: Session = Depends(get_db),
               actor: User = Depends(require_admin)):
    u = get_user(db, user_id)
    link_member(db, u, body.member_id, actor)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, f"member {body.member_id} is already linked to another login")
    return user_out(db, u)


def as_utc(t: datetime | None) -> datetime | None:
    """A time without a zone is taken as UTC, like every stored time."""
    return t.replace(tzinfo=timezone.utc) if t is not None and t.tzinfo is None else t


@router.get("/audit", response_model=list[s.AuditOut])
def audit_log(actor_user_id: int | None = None, action: str | None = Query(None, max_length=64),
              entity: str | None = Query(None, max_length=40), entity_id: int | None = None,
              since: datetime | None = None, until: datetime | None = None,
              limit: int = Query(100, ge=1, le=500), offset: int = Query(0, ge=0),
              db: Session = Depends(get_db), _: User = Depends(require_admin)):
    """Newest first. `action` matches exactly, or by prefix when it ends in a
    dot (e.g. `guarantor.`)."""
    stmt = (select(AuditLog, User.username).outerjoin(User, User.id == AuditLog.actor_user_id)
            .order_by(AuditLog.id.desc()).limit(limit).offset(offset))
    if actor_user_id is not None:
        stmt = stmt.where(AuditLog.actor_user_id == actor_user_id)
    if action:
        stmt = stmt.where(AuditLog.action.startswith(action, autoescape=True)
                          if action.endswith(".")
                          else AuditLog.action == action)
    if entity:
        stmt = stmt.where(AuditLog.entity == entity)
    if entity_id is not None:
        stmt = stmt.where(AuditLog.entity_id == entity_id)
    if since is not None:
        stmt = stmt.where(AuditLog.created_at >= as_utc(since))
    if until is not None:
        stmt = stmt.where(AuditLog.created_at < as_utc(until))
    return [s.AuditOut(id=row.id, actor_user_id=row.actor_user_id, actor=username,
                       action=row.action, entity=row.entity, entity_id=row.entity_id,
                       details=row.details, created_at=row.created_at)
            for row, username in db.execute(stmt)]
