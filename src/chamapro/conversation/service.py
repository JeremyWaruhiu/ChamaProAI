"""Running a conversation: start one, take a reply, keep the record. The API and
scripts/converse.py both call this.

A reply does its slow work with no transaction open. busy_until is taken first, in its
own commit, so a second reply to the same conversation is refused rather than worked on
at the same time. Then: speech to text, extraction, the machine (a decision commits in
its own transaction, under its own idempotency key), speech, and last of all one commit
holding the member's turn, the bot's turns and the new state. If anything fails on the
way, nothing about the conversation has changed, and answering again is safe: a decision
already made is found by its key and not made twice.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from sqlalchemy import or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from chamapro import config
from chamapro.api import decisions, ledger, pipeline, profiles, self_service, storage
from chamapro.api.db import (Conversation, ConversationTurn, Guarantor, LoanAccount, LoanApplication, Member, SelfServiceRun,
                            SessionLocal, User, utcnow)

from . import extract, machine, templates, tts

log = logging.getLogger("chamapro.conversation")

LEASE = timedelta(minutes=3)
# What each reply is doing right now, by conversation id, for the screens to show. In this
# process only: with more than one worker a screen sees no stage, and nothing else changes.
_stages: dict[int, str] = {}


def stage_of(conversation_id: int) -> str | None:
    """transcribing | understanding | deciding | speaking, while a reply is worked on."""
    return _stages.get(conversation_id)


class ConversationClosed(Exception):
    """It has ended, or cannot begin. str(e) is for the member."""


class ConversationBusy(Exception):
    """Another reply to it is still being worked on."""


class SpeechUnavailable(Exception):
    """The audio could not be turned into text. Nothing changed: they can type, or try again."""


@dataclass
class Spoken:
    """A member's voice reply, already converted to 16 kHz WAV."""
    wav: Path
    duration_s: float


def ms_since(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


def idle_cutoff():
    return utcnow() - timedelta(minutes=config.CONVERSATION_IDLE_MINUTES)


def abandon_if_idle(db: Session, conv: Conversation) -> None:
    """Close it if it has sat past the limit and no reply is being worked on. Nothing is
    written otherwise: reading a transcript is only a read."""
    now = utcnow()
    if conv.status == "open" and conv.last_activity_at < idle_cutoff() and (conv.busy_until is None or conv.busy_until < now):
        conv.status, conv.ended_at = "abandoned", now
        db.commit()


def abandon_idle_at_startup() -> None:
    """Whatever a previous process left open: otherwise each waits for its member to come back."""
    with SessionLocal() as db:
        db.execute(update(Conversation).where(Conversation.status == "open", Conversation.last_activity_at < idle_cutoff())
                   .values(status="abandoned", ended_at=utcnow(), busy_until=None))
        db.commit()


def bot_turn(conv: Conversation, seq: int, line: templates.Rendered, speech: tts.Speech | None, explain: dict | None,
             actions: list | None) -> ConversationTurn:
    return ConversationTurn(conversation_id=conv.id, seq=seq, speaker="bot", template_id=line.template_id, text=line.text,
                            text_en=line.text_en, kik_pending=line.kik_pending, spoken_text=line.spoken,
                            audio_ref=speech.key if speech else None, tts_model=speech.model if speech else None,
                            tts_ms=speech.ms if speech else None, explain=explain, actions=actions)


def turns_of(db: Session, conv: Conversation, after_seq: int = 0) -> list[ConversationTurn]:
    return list(db.scalars(select(ConversationTurn).where(ConversationTurn.conversation_id == conv.id,
                                                          ConversationTurn.seq > after_seq)
                           .order_by(ConversationTurn.seq)))


def start(db: Session, member: Member, language: str) -> tuple[Conversation, bool]:
    """(the conversation, whether it was already under way). An unfinished one in this
    language carries on; in another it is abandoned, since nothing has been decided."""
    now = utcnow()
    held = db.scalar(select(Conversation).where(Conversation.member_id == member.id, Conversation.status == "open"))
    if held is not None:
        abandon_if_idle(db, held)
    if held is not None and held.status == "open":
        if held.language == language:
            return held, True
        held.status, held.ended_at = "abandoned", now
        db.flush()
    if self_service.has_open_application(db, member.id):
        db.rollback()
        raise ConversationClosed("You already have an application being decided. Please finish that one first.")
    conv = Conversation(member_id=member.id, language=language, status="open", state="CONSENT",
                        policy_version=decisions.policy_version(), context={}, turn_count=0, last_activity_at=now,
                        started_at=now)
    lines, conv.context = machine.opening(conv, member)
    db.commit()     # nothing is held while speech is made
    spoken = [tts.speak(line) for line in lines]
    try:
        db.add(conv)
        db.flush()
        db.add_all([bot_turn(conv, i, line, speech, None, None)
                    for i, (line, speech) in enumerate(zip(lines, spoken), 1)])
        conv.turn_count = len(lines)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ConversationClosed("A conversation has just been started. Please go back to it.") from None
    return conv, False


def _take_lease(db: Session, conv: Conversation) -> None:
    now = utcnow()
    taken = db.execute(update(Conversation)
                       .where(Conversation.id == conv.id, Conversation.status == "open",
                              or_(Conversation.busy_until.is_(None), Conversation.busy_until < now))
                       .values(busy_until=now + LEASE)).rowcount
    db.commit()
    if not taken:
        raise ConversationBusy("We are still working on your last answer.")


def _release_lease(db: Session, conv: Conversation) -> None:
    db.rollback()
    db.execute(update(Conversation).where(Conversation.id == conv.id).values(busy_until=None))
    db.commit()


def _transcribed(conv: Conversation, voice: Spoken) -> tuple[str, str, str, int]:
    """(the text, its storage reference, the ASR model, milliseconds)."""
    key = f"conversations/{conv.id}/{uuid.uuid4().hex}.wav"
    store = storage.backend()
    ref = store.save(voice.wav, key)
    started = time.perf_counter()
    try:
        heard = store.local_path(ref)
        text, label = pipeline.transcribe_now(heard, conv.language, voice.duration_s)
    except Exception as e:
        log.exception("could not transcribe a reply in conversation %s", conv.id)
        _forget_audio(ref)
        raise SpeechUnavailable("We could not hear that just now. Please try again, or type your answer.") from e
    finally:
        try:
            store.release(ref)
        except Exception:
            log.exception("could not release the local copy of a reply")
    return text, ref, label, ms_since(started)


def reply(db: Session, conv: Conversation, member: Member, actor: User, text: str | None = None,
          voice: Spoken | None = None) -> tuple[ConversationTurn, list[ConversationTurn], dict | None]:
    """(the member's turn, the bot's turns, the explain object if this reply was evaluated)."""
    db.refresh(conv)
    abandon_if_idle(db, conv)
    if conv.status != "open":
        raise ConversationClosed({"abandoned": "This conversation was left too long, so it has ended. "
                                               "Please start again."}.get(conv.status, "This conversation has ended."))
    _take_lease(db, conv)
    audio_ref = None
    try:
        answer, asr_model, asr_ms = text or "", None, None
        if voice is not None:
            _stages[conv.id] = "transcribing"
            answer, audio_ref, asr_model, asr_ms = _transcribed(conv, voice)

        _stages[conv.id] = "understanding"
        started = time.perf_counter()
        question_id = conv.context["question_id"]
        read = extract.extract(question_id, conv.context["question_en"], answer, conv.language)
        extract_ms = ms_since(started)

        _stages[conv.id] = "deciding"
        started = time.perf_counter()
        step = machine.advance(db, conv, member, actor, read)
        evaluate_ms = ms_since(started) if step.evaluated else None
        db.commit()     # the decision, if any, is safely in; nothing is held while speech is made

        _stages[conv.id] = "speaking"
        spoken = [tts.speak(line) for line in step.lines]
        tts_ms = sum(s.ms for s in spoken if s is not None)

        now = utcnow()
        seq = conv.turn_count + 1
        member_turn = ConversationTurn(
            conversation_id=conv.id, seq=seq, speaker="member", template_id=question_id, text=answer, text_en=read.translation,
            audio_ref=audio_ref, input_mode="voice" if voice is not None else "text", asr_transcript=answer if voice else None,
            asr_model=asr_model, translation=read.translation, extraction=read.record, asr_ms=asr_ms, extract_ms=extract_ms,
            evaluate_ms=evaluate_ms, tts_ms=tts_ms)
        bots = [bot_turn(conv, seq + i, line, speech, step.explain if i == 1 else None,
                         step.actions if i == len(step.lines) else None)
                for i, (line, speech) in enumerate(zip(step.lines, spoken), 1)]
        db.add_all([member_turn, *bots])
        if step.corrections:
            profiles.request_update(db, member, _profile_fields(step.corrections), conv.id, actor)
        if step.confirmed_groups:
            profiles.confirm_groups(db, member, step.confirmed_groups, actor)
        if step.consent is not None:
            conv.consent_given, conv.consent_version, conv.consent_at = step.consent, templates.consent_version(), now
        if step.application_id is not None:
            conv.application_id, conv.self_service_run_id = step.application_id, step.run_id
        conv.state, conv.context, conv.status = step.state, step.context, step.status
        conv.turn_count = seq + len(bots)
        conv.last_activity_at, conv.busy_until = now, None
        if step.status != "open":
            conv.ended_at = now
        db.commit()
        return member_turn, bots, step.explain
    except Exception:
        _release_lease(db, conv)
        _forget_audio(audio_ref)
        raise
    finally:
        _stages.pop(conv.id, None)


def _forget_audio(ref: str | None) -> None:
    """A recording whose turn was never written would be nobody's: answering again records it anew."""
    if ref is not None:
        try:
            storage.for_ref(ref).delete(ref)
        except Exception:
            log.exception("could not delete the audio of a reply that failed")


def _profile_fields(corrections: dict) -> dict:
    """The conversation's names for these are already the profile's."""
    return {k: v for k, v in corrections.items() if k in profiles.FIELD_GROUP}


def is_busy(conv: Conversation) -> bool:
    return conv.busy_until is not None and conv.busy_until >= utcnow()


def open_conversation(db: Session, member: Member) -> Conversation | None:
    """The member's unfinished conversation, if there is one to carry on."""
    conv = db.scalar(select(Conversation).where(Conversation.member_id == member.id, Conversation.status == "open"))
    if conv is not None:
        abandon_if_idle(db, conv)
    return conv if conv is not None and conv.status == "open" else None


def outcome_of(db: Session, conv: Conversation) -> dict | None:
    """How it came out, from the ledger and the application as they stand now, or None
    while it is under way or if it was abandoned. decision: approved (the money was paid
    out), reversed, referred, not_now, or none when it ended with nothing decided."""
    if conv.status != "completed":
        return None
    out = {"decision": "none", "application_id": conv.application_id, "requested_kes": conv.context.get("amount_kes"),
           "amount_kes": None, "term_months": conv.context.get("overrides", {}).get("term_months"),
           "instalment_kes": None, "guarantors": [], "balance_before_kes": None, "balance_after_kes": None,
           "review_requested": False, "ledger": None}
    app = db.get(LoanApplication, conv.application_id) if conv.application_id else None
    if app is None:
        return out
    out["requested_kes"] = app.amount_requested_kes
    out["review_requested"] = db.scalar(select(SelfServiceRun.id).where(SelfServiceRun.application_id == app.id,
                                                                        SelfServiceRun.trigger == "review").limit(1)) is not None
    loan = db.scalar(select(LoanAccount).where(LoanAccount.application_id == app.id).order_by(LoanAccount.id.desc()).limit(1))
    if loan is None:
        out["decision"] = "not_now" if app.status == "declined" else "referred"
        return out
    entry, before = ledger.disbursement_of(db, loan)
    out.update(decision="reversed" if loan.status == "reversed" else "approved", amount_kes=loan.principal_kes,
               term_months=loan.term_months, instalment_kes=loan.monthly_instalment_kes,
               guarantors=list(db.scalars(select(Guarantor.full_name).where(Guarantor.application_id == app.id,
                                                                            Guarantor.status == "verified")
                                          .order_by(Guarantor.id))),
               balance_before_kes=before, balance_after_kes=before + entry.amount_kes,
               ledger={"entry_id": entry.id, "reference": entry.reference, "posted_at": entry.posted_at,
                       "amount_kes": entry.amount_kes, "entry_type": entry.entry_type, "loan_id": loan.id})
    return out


__all__ = ["ConversationBusy", "ConversationClosed", "Spoken", "SpeechUnavailable", "abandon_if_idle",
           "abandon_idle_at_startup", "is_busy", "open_conversation", "outcome_of", "reply", "stage_of", "start", "turns_of"]
