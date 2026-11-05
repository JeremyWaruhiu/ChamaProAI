"""The member's conversation: start one, reply by text or voice, read it back, hear it.

Member role, their own conversations only: anyone else's is the same 404 as none at all.
Replies and starts are rate limited per member, since each can run the classifier. A
member sees plain language only: each check in their own figures and the three largest
drivers as sentences. The class, the probabilities, the SHAP values and the policy trace
stay on the turn's record, for officers and admins (presenter.py).
"""
from __future__ import annotations

import logging
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from chamapro import config
from chamapro.conversation import service, tts

from . import decisions, member_text
from . import pipeline as pl
from . import schemas as s
from .auth import LoginLimiter, require_member
from .db import Conversation, ConversationTurn, Member, User, get_db
from .pilot import required_member
from .self_service import limited

log = logging.getLogger("chamapro.api")

ERRORS = {code: {"model": s.Error} for code in (401, 403, 404, 409, 413, 415, 422, 429, 503)}
router = APIRouter(prefix="/api", responses=ERRORS)

starts = LoginLimiter(config.CONVERSATION_STARTS_PER_HOUR, 3600)
replies = LoginLimiter(config.CONVERSATION_REPLIES_PER_HOUR, 3600)


def own(db: Session, member: Member, conversation_id: int, with_turns: bool = False) -> Conversation:
    conv = service.with_turns(db, conversation_id) if with_turns else db.get(Conversation, conversation_id)
    if conv is None or conv.member_id != member.id:
        raise HTTPException(404, f"conversation {conversation_id} not found")
    return conv


def turn_out(t: ConversationTurn, language: str = "en") -> s.TurnOut:
    return s.TurnOut(
        seq=t.seq, speaker=t.speaker, template_id=t.template_id, text=t.text, text_en=t.text_en, kik_pending=t.kik_pending,
        audio_url=f"/api/conversations/{t.conversation_id}/turns/{t.seq}/audio" if t.speaker == "bot" and t.audio_ref else None,
        input_mode=t.input_mode, asr_transcript=t.asr_transcript, asr_model=t.asr_model, translation=t.translation,
        extraction=t.extraction, explain=member_text.plain_explain(t.explain, language) if t.explain else None, actions=t.actions or [],
        latency_ms=s.TurnLatency(asr=t.asr_ms, translate_extract=t.extract_ms, evaluate=t.evaluate_ms, tts=t.tts_ms),
        created_at=t.created_at)


def conversation_out(conv: Conversation) -> s.ConversationBrief:
    return s.ConversationBrief(id=conv.id, language=conv.language, status=conv.status, state=conv.state,
                               consent_given=conv.consent_given, consent_version=conv.consent_version,
                               policy_version=conv.policy_version, application_id=conv.application_id,
                               self_service_run_id=conv.self_service_run_id, started_at=conv.started_at,
                               ended_at=conv.ended_at, busy=service.is_busy(conv))


def received_voice(file: UploadFile, folder: Path) -> service.Spoken:
    """The same checks and conversion as an interview's audio, and a limit on length: a
    reply is a few words, and the member waits while it is transcribed."""
    suffix = Path(file.filename or "").suffix.lower()
    ctype = (file.content_type or "").split(";")[0].strip().lower()
    if not (ctype.startswith("audio/") or suffix in pl.AUDIO_SUFFIXES):
        raise HTTPException(415, f"not an audio file (content type {ctype or 'unknown'!r})")
    incoming, wav = folder / f"incoming{suffix}", folder / "reply.wav"
    size = 0
    with incoming.open("wb") as out:
        while chunk := file.file.read(1024 * 1024):
            size += len(chunk)
            if size > config.MAX_UPLOAD_BYTES:
                raise HTTPException(413, f"audio exceeds {config.MAX_UPLOAD_BYTES // 2**20} MB")
            out.write(chunk)
    if size == 0:
        raise HTTPException(415, "empty upload")
    try:
        duration = pl.convert_upload(incoming, wav)
    except pl.NotAudio as e:
        raise HTTPException(415, str(e)) from None
    if duration > config.CONVERSATION_MAX_AUDIO_SECONDS:
        raise HTTPException(413, f"a reply can be up to {config.CONVERSATION_MAX_AUDIO_SECONDS} seconds")
    return service.Spoken(wav, duration)


@router.get("/conversations/current", response_model=s.ConversationDetail | None)
def current_conversation(db: Session = Depends(get_db), user: User = Depends(require_member)):
    """The unfinished conversation to carry on after a page reload, or null. Starts nothing."""
    member = required_member(db, user)
    conv = service.open_conversation(db, member)
    if conv is None:
        return None
    return s.ConversationDetail(conversation=conversation_out(conv), turns=[turn_out(t, conv.language) for t in conv.turns], outcome=None)


@router.post("/conversations", status_code=201, response_model=s.ConversationStarted)
def start_conversation(body: s.ConversationCreate, db: Session = Depends(get_db), user: User = Depends(require_member)):
    """The first bot turns. An unfinished conversation in this language carries on."""
    member = required_member(db, user)
    limited(starts, f"member:{member.id}")
    try:
        conv, resumed = service.start(db, member, body.language)
    except service.ConversationClosed as e:
        raise HTTPException(409, str(e)) from None
    return s.ConversationStarted(conversation=conversation_out(conv), resumed=resumed,
                                 turns=[turn_out(t, conv.language) for t in conv.turns])


@router.post("/conversations/{conversation_id}/reply", response_model=s.ConversationReply)
def reply_to_conversation(conversation_id: int, text: str | None = Form(None, max_length=1000),
                          audio: UploadFile | None = File(None), db: Session = Depends(get_db),
                          user: User = Depends(require_member)):
    """Text or an audio upload, not both. Comes back with what was understood, the next
    bot turns, and how it was worked out if this reply was evaluated."""
    member = required_member(db, user)
    has_text = text is not None and bool(text.strip())
    if has_text == (audio is not None):
        raise HTTPException(422, "send either text or audio")
    limited(replies, f"member:{member.id}")
    folder = Path(tempfile.mkdtemp(prefix="chamapro-reply-"))
    try:
        voice = received_voice(audio, folder) if audio is not None else None
        done = service.reply_to(db, conversation_id, member, user, text.strip() if has_text else None, voice)
    except service.ConversationMissing as e:
        raise HTTPException(404, str(e)) from None
    except (service.ConversationClosed, service.ConversationBusy) as e:
        raise HTTPException(409, str(e)) from None
    except service.SpeechUnavailable as e:
        raise HTTPException(503, str(e)) from None
    except decisions.ClassifierMissing:
        raise HTTPException(503, "We could not look at this just now. Please try again later.") from None
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    language = done.conversation.language
    return s.ConversationReply(conversation=conversation_out(done.conversation), member_turn=turn_out(done.member_turn, language),
                               bot_turns=[turn_out(t, language) for t in done.bot_turns],
                               explain=member_text.plain_explain(done.explain, language) if done.explain else None,
                               outcome=done.outcome)


@router.get("/conversations/{conversation_id}", response_model=s.ConversationDetail)
def get_conversation(conversation_id: int, db: Session = Depends(get_db), user: User = Depends(require_member)):
    """The whole transcript, in the detail each turn came back with. Three queries however long."""
    member = required_member(db, user)
    conv = own(db, member, conversation_id, with_turns=True)
    service.abandon_if_idle(db, conv)
    return s.ConversationDetail(conversation=conversation_out(conv), turns=[turn_out(t, conv.language) for t in conv.turns],
                                outcome=service.outcome_of(db, conv))


@router.get("/conversations/{conversation_id}/stage", response_model=s.ConversationStage)
def conversation_stage(conversation_id: int, db: Session = Depends(get_db), user: User = Depends(require_member)):
    """What the reply in flight is doing, for the stage indicator."""
    conv = own(db, required_member(db, user), conversation_id)
    return s.ConversationStage(stage=service.stage_of(conv.id), busy=service.is_busy(conv))


@router.get("/conversations/{conversation_id}/turns/{seq}/audio", response_class=FileResponse,
            responses={200: {"content": {tts.MEDIA_TYPE: {}}}})
def conversation_audio(conversation_id: int, seq: int, db: Session = Depends(get_db), user: User = Depends(require_member)):
    """What a bot turn said. If the cache has lost it, it is made again from the turn's record."""
    member = required_member(db, user)
    turn = db.scalar(select(ConversationTurn).join(Conversation, Conversation.id == ConversationTurn.conversation_id)
                     .where(ConversationTurn.conversation_id == conversation_id, ConversationTurn.seq == seq,
                            Conversation.member_id == member.id))
    if turn is None or turn.speaker != "bot" or not turn.audio_ref:
        raise HTTPException(404, "there is no audio for this turn")
    speech = tts.audio_for(turn.tts_model, turn.spoken_text or "")
    if speech is None:
        raise HTTPException(404, "there is no audio for this turn")
    return FileResponse(speech.path, media_type=tts.MEDIA_TYPE, headers={"Cache-Control": "private, max-age=86400"})
