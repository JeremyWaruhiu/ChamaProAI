"""The presenter view, for officers and admins: every conversation as it happens, with what
a member is never shown: the risk class, the probabilities, the SHAP values and the policy
trace. Also the reset that lets a demonstration be rehearsed again.

Staff read any conversation. The reset acts only on the demo's two members, found by the
seed tag only scripts/seed_demo.py --demo-db writes, so on any other database it has nobody
to act on.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy import case, select
from sqlalchemy.orm import Session, joinedload

from chamapro.conversation import service, tts

from . import audit, conversations, ledger, ledger_api, loans, storage
from . import schemas as s
from .auth import require_admin, require_officer
from .db import (Conversation, ConversationTurn, InterviewBooking, LoanAccount, LoanApplication, Member, User, get_db, utcnow)
from .self_service import FINISHED

log = logging.getLogger("chamapro.api")

ERRORS = {code: {"model": s.Error} for code in (401, 403, 404, 503)}
router = APIRouter(prefix="/api", responses=ERRORS)

DEMO_TAGS = ("demo-db:wanjiru", "demo-db:njeri")
RESET_REASON = "demo reset by an administrator"


def row_out(conv: Conversation) -> s.PresentRow:
    m = conv.member
    return s.PresentRow(id=conv.id, member_id=m.id, member_no=m.member_no, member_name=m.full_name, language=conv.language,
                        status=conv.status, state=conv.state, turn_count=conv.turn_count, busy=service.is_busy(conv),
                        stage=service.stage_of(conv.id), started_at=conv.started_at, last_activity_at=conv.last_activity_at)


def audio_url(t: ConversationTurn) -> str | None:
    return f"/api/present/conversations/{t.conversation_id}/turns/{t.seq}/audio" if t.audio_ref else None


def turn_out(t: ConversationTurn) -> s.PresentTurn:
    return s.PresentTurn(
        seq=t.seq, speaker=t.speaker, template_id=t.template_id, text=t.text, text_en=t.text_en, kik_pending=t.kik_pending,
        audio_url=audio_url(t), input_mode=t.input_mode, asr_transcript=t.asr_transcript, asr_model=t.asr_model,
        translation=t.translation, extraction=t.extraction, explain=t.explain,
        latency_ms=s.TurnLatency(asr=t.asr_ms, translate_extract=t.extract_ms, evaluate=t.evaluate_ms, tts=t.tts_ms),
        created_at=t.created_at)


@router.get("/present/conversations", response_model=list[s.PresentRow])
def present_list(limit: int = Query(30, ge=1, le=200), db: Session = Depends(get_db), _: User = Depends(require_officer)):
    """Open ones first, then the most recent."""
    rows = db.scalars(select(Conversation).options(joinedload(Conversation.member))
                      .order_by(case((Conversation.status == "open", 0), else_=1), Conversation.last_activity_at.desc())
                      .limit(limit)).all()
    for conv in rows:
        service.abandon_if_idle(db, conv)
    return [row_out(c) for c in rows]


def present_conv(db: Session, conversation_id: int) -> Conversation:
    conv = db.scalar(select(Conversation).where(Conversation.id == conversation_id).options(joinedload(Conversation.member)))
    if conv is None:
        raise HTTPException(404, f"conversation {conversation_id} not found")
    return conv


@router.get("/present/conversations/{conversation_id}", response_model=s.PresentDetail)
def present_detail(conversation_id: int, db: Session = Depends(get_db), _: User = Depends(require_officer)):
    """Everything recorded so far, polled while the conversation is followed."""
    conv = present_conv(db, conversation_id)
    service.abandon_if_idle(db, conv)
    return s.PresentDetail(row=row_out(conv), consent_given=conv.consent_given, consent_version=conv.consent_version,
                           policy_version=conv.policy_version, application_id=conv.application_id,
                           turns=[turn_out(t) for t in service.turns_of(db, conv)], outcome=service.outcome_of(db, conv))


@router.get("/present/conversations/{conversation_id}/turns/{seq}/audio", response_class=FileResponse,
            responses={200: {"content": {"audio/wav": {}, tts.MEDIA_TYPE: {}}},
                       307: {"description": "Supabase storage: a short-lived signed URL"}})
def present_audio(conversation_id: int, seq: int, db: Session = Depends(get_db), _: User = Depends(require_officer)):
    """The member's clip, or what the bot said."""
    turn = db.scalar(select(ConversationTurn).where(ConversationTurn.conversation_id == conversation_id, ConversationTurn.seq == seq))
    if turn is None or not turn.audio_ref:
        raise HTTPException(404, "there is no audio for this turn")
    if turn.speaker == "bot":
        speech = tts.audio_for(turn.tts_model, turn.spoken_text or "")
        if speech is None:
            raise HTTPException(404, "there is no audio for this turn")
        return FileResponse(speech.path, media_type=tts.MEDIA_TYPE)
    store = storage.for_ref(turn.audio_ref)
    try:
        url = store.signed_url(turn.audio_ref)
    except Exception:
        log.exception("could not sign the audio URL for a turn of conversation %s", conversation_id)
        raise HTTPException(503, "audio storage is unavailable; try again") from None
    if url is not None:
        return RedirectResponse(url, status_code=307)
    path = store.local_path(turn.audio_ref)
    if not path.is_file():
        raise HTTPException(404, "there is no audio for this turn")
    return FileResponse(path, media_type="audio/wav")


# --- Rehearsing again -----------------------------------------------------------------------

def demo_members(db: Session) -> list[Member]:
    return list(db.scalars(select(Member).where(Member.seed_tag.in_(DEMO_TAGS)).order_by(Member.id)))


def own_applications(db: Session, member: Member) -> list[tuple[LoanApplication, LoanAccount | None]]:
    """What their conversations left: self-service only, so a loan from the seed's history stays."""
    return list(db.execute(select(LoanApplication, LoanAccount)
                           .outerjoin(LoanAccount, LoanAccount.application_id == LoanApplication.id)
                           .where(LoanApplication.member_id == member.id, LoanApplication.channel == "self_service")
                           .order_by(LoanApplication.id)).all())


def person_out(db: Session, member: Member) -> s.DemoPerson:
    held = own_applications(db, member)
    conversations = db.scalars(select(Conversation.id).where(Conversation.member_id == member.id, Conversation.status == "open"))
    return s.DemoPerson(member_id=member.id, full_name=member.full_name, open_conversations=len(conversations.all()),
                        active_loans=sum(1 for _, loan in held if loan is not None and loan.status == "active"),
                        open_applications=sum(1 for app, loan in held if loan is None and app.status not in FINISHED))


@router.get("/admin/demo-reset", response_model=s.DemoStatus)
def demo_status(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    people = demo_members(db)
    return s.DemoStatus(available=bool(people), people=[person_out(db, m) for m in people])


@router.post("/admin/demo-reset", response_model=s.DemoResetResult)
def demo_reset(db: Session = Depends(get_db), user: User = Depends(require_admin)):
    """Close the demo members' open conversations, reverse the loans their conversations
    paid out and close their other applications, so the demonstration can be run again.
    Pressing it twice is harmless. The money goes back by compensating entries, and the
    automatic reversal window is not applied: a rehearsal may be days old."""
    people = demo_members(db)
    if not people:
        raise HTTPException(404, "this database has no demo members; only a seed_demo.py --demo-db build has")
    now, closed, reversed_, finished, problems = utcnow(), 0, 0, 0, []
    ledger.lock_members(db, [m.id for m in people])
    for member in people:
        for conv in db.scalars(select(Conversation).where(Conversation.member_id == member.id, Conversation.status == "open")):
            conv.status, conv.ended_at, conv.busy_until = "abandoned", now, None
            closed += 1
        for app, loan in own_applications(db, member):
            if loan is not None and loan.status == "active":
                try:
                    with db.begin_nested():
                        ledger_api.apply_reversal(db, loan, app, user, RESET_REASON)
                    reversed_ += 1
                except ledger.LedgerError as e:
                    problems.append(f"{member.full_name}: {e}")
            elif loan is None and app.status not in FINISHED:
                for booking in db.scalars(select(InterviewBooking).where(InterviewBooking.application_id == app.id,
                                                                         InterviewBooking.status != "cancelled")):
                    booking.status, booking.updated_at = "cancelled", now
                loans.set_status(db, app, "declined", user, demo_reset=True)
                finished += 1
        key = f"member:{member.id}"
        conversations.starts.clear(key)
        conversations.replies.clear(key)
    audit.record(db, user, "demo.reset", "member", None, conversations_closed=closed, loans_reversed=reversed_,
                 applications_closed=finished)
    db.commit()
    return s.DemoResetResult(conversations_closed=closed, loans_reversed=reversed_, applications_closed=finished,
                             problems=problems, people=[person_out(db, m) for m in people])
