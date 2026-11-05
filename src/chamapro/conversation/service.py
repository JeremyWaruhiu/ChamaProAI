"""Running a conversation: start one, take a reply, keep the record. The API and
scripts/converse.py both call this.

A reply does its slow work with no transaction open. busy_until is taken first, in the same
statement that reads the conversation, so a second reply to the same conversation is refused
rather than worked on at the same time. Then: speech to text, extraction, the machine (which
only reads), speech, and last of all one write holding the member's turn, the bot's turns, the
new state and any decision, under the row locks if there is a decision. If anything fails on
the way, nothing about the conversation has changed and no money has moved, and answering again
is safe.

Round trips are what a member waits for on Supabase, at ~200 ms each. An ordinary reply takes
four (who is asking, the lease, what the engine reads, the write) and a decision four more
(BEGIN, the locks, what the engine reads under them, COMMIT): see docs/design_changes.md.
"""
from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.orm.attributes import set_committed_value

from chamapro import config
from chamapro.api import decisions, pipeline, profiles, self_service, storage
from chamapro.api.batch import Batch, reserve
from chamapro.api.db import (AccountEntry, Conversation, ConversationTurn, Guarantor, LoanAccount, LoanApplication, Member,
                            SelfServiceRun, SessionLocal, User, use_autocommit, utcnow)

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


class ConversationMissing(Exception):
    """There is no such conversation, or it is someone else's."""


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
    """Whatever a previous process left open: otherwise each waits for its member to come back.
    So too one waiting on a question the machine no longer asks: it could not be answered."""
    with SessionLocal() as db:
        db.execute(update(Conversation).where(Conversation.status == "open",
                                              or_(Conversation.last_activity_at < idle_cutoff(),
                                                  Conversation.state.not_in(tuple(machine.HANDLERS))))
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
    use_autocommit(db)
    held = db.scalar(select(Conversation).where(Conversation.member_id == member.id, Conversation.status == "open"))
    if held is not None:
        abandon_if_idle(db, held)
    if held is not None and held.status == "open":
        if held.language == language:
            return held, True
        held.status, held.ended_at = "abandoned", now
        db.commit()
        use_autocommit(db)
    if self_service.has_open_application(db, member.id):
        db.rollback()
        raise ConversationClosed("You already have an application being decided. Please finish that one first.")
    db.commit()         # nothing is held while speech is made
    conv = Conversation(member_id=member.id, language=language, status="open", state="CONSENT",
                        policy_version=decisions.policy_version(), context={}, turn_count=0, last_activity_at=now,
                        started_at=now)
    lines, conv.context = machine.opening(conv, member)
    spoken = [tts.speak(line) for line in lines]
    conv.turn_count = len(lines)
    use_autocommit(db)
    out = Batch(db, reserve(db, {"conversations": 1}))
    out.give_id(conv)
    out.add(conv)
    turns = [bot_turn(conv, i, line, speech, None, None) for i, (line, speech) in enumerate(zip(lines, spoken), 1)]
    for turn in turns:
        out.add(turn)
    try:
        out.send()
        db.commit()
    except IntegrityError:
        db.rollback()
        raise ConversationClosed("A conversation has just been started. Please go back to it.") from None
    out.attach(conv)
    set_committed_value(conv, "turns", turns)
    return conv, False


def _take_lease(db: Session, conversation_id: int, member: Member) -> Conversation:
    """The conversation, marked busy, or why it cannot be answered. One statement for all of it,
    unless it is refused: it is what every reply starts with, and nearly every one is let through."""
    now = utcnow()
    db.commit()
    use_autocommit(db)
    conv = db.execute(update(Conversation)
                      .where(Conversation.id == conversation_id, Conversation.member_id == member.id,
                             Conversation.status == "open", Conversation.last_activity_at >= idle_cutoff(),
                             or_(Conversation.busy_until.is_(None), Conversation.busy_until < now))
                      .values(busy_until=now + LEASE).returning(Conversation)
                      .execution_options(populate_existing=True, synchronize_session=False)).scalar()
    if conv is not None:
        db.commit()     # nothing is held from here until the write
        return conv
    conv = db.execute(select(Conversation).where(Conversation.id == conversation_id).execution_options(populate_existing=True)).scalar()
    if conv is None or conv.member_id != member.id:
        raise ConversationMissing(f"conversation {conversation_id} not found")
    abandon_if_idle(db, conv)
    if conv.status != "open":
        raise ConversationClosed({"abandoned": "This conversation was left too long, so it has ended. "
                                               "Please start again."}.get(conv.status, "This conversation has ended."))
    raise ConversationBusy("We are still working on your last answer.")


def _release_lease(db: Session, conv: Conversation) -> None:
    db.rollback()
    use_autocommit(db)
    db.execute(update(Conversation).where(Conversation.id == conv.id).values(busy_until=None)
               .execution_options(synchronize_session=False))
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


@dataclass
class Replied:
    conversation: Conversation
    member_turn: ConversationTurn
    bot_turns: list[ConversationTurn]
    explain: dict | None
    outcome: dict | None


def reply(db: Session, conv: Conversation, member: Member, actor: User, text: str | None = None,
          voice: Spoken | None = None) -> tuple[ConversationTurn, list[ConversationTurn], dict | None]:
    """(the member's turn, the bot's turns, the explain object if this reply was evaluated)."""
    done = reply_to(db, conv.id, member, actor, text, voice)
    return done.member_turn, done.bot_turns, done.explain


def reply_to(db: Session, conversation_id: int, member: Member, actor: User, text: str | None = None,
             voice: Spoken | None = None) -> Replied:
    conv = _take_lease(db, conversation_id, member)
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
        use_autocommit(db)
        step = machine.advance(db, conv, member, actor, read)
        evaluate_ms = ms_since(started) if step.evaluated else None
        db.commit()     # nothing is held while speech is made

        _stages[conv.id] = "speaking"
        spoken = [tts.speak(line) for line in step.lines]

        def write(out: Batch, recorded: self_service.Recorded | None) -> tuple[ConversationTurn, list[ConversationTurn]]:
            now = utcnow()
            seq = conv.turn_count + 1
            tts_ms = sum(s.ms for s in spoken if s is not None)
            member_turn = ConversationTurn(
                conversation_id=conv.id, seq=seq, speaker="member", template_id=question_id, text=answer, text_en=read.translation,
                audio_ref=audio_ref, input_mode="voice" if voice is not None else "text", asr_transcript=answer if voice else None,
                asr_model=asr_model, translation=read.translation, extraction=read.record, asr_ms=asr_ms, extract_ms=extract_ms,
                evaluate_ms=evaluate_ms, tts_ms=tts_ms)
            actions = [{**a, "application_id": recorded.application_id if a["application_id"] == machine.THIS_APPLICATION
                        else a["application_id"]} for a in step.actions]
            bots = [bot_turn(conv, seq + i, line, speech, step.explain if i == 1 else None,
                             actions if i == len(step.lines) else None)
                    for i, (line, speech) in enumerate(zip(step.lines, spoken), 1)]
            for row in (member_turn, *bots):
                out.add(row)
            if step.corrections:
                profiles.request_update(out, member, _profile_fields(step.corrections), conv.id, actor)
            if step.confirmed_groups:
                profiles.confirm_groups(out, member, step.confirmed_groups, actor)
            values = dict(state=step.state, context=step.context, status=step.status, turn_count=seq + len(bots),
                          last_activity_at=now, busy_until=None)
            if step.consent is not None:
                values.update(consent_given=step.consent, consent_version=templates.consent_version(), consent_at=now)
            if recorded is not None:
                values.update(application_id=recorded.application_id, self_service_run_id=recorded.run_id)
            if step.status != "open":
                values["ended_at"] = now
            out.update(conv, **values)
            return member_turn, bots

        while step.to_record is not None:
            plan, written = step.to_record, []
            try:
                recorded = self_service.record(db, plan.evaluation, plan.commit_key, actor, accept_key=plan.accept_key,
                                               accepted=plan.accepted, along=lambda out, r: written.extend(write(out, r)))
                if not written:     # its key was already used: a reply that outlived its lease got here first
                    raise ConversationClosed("This conversation has ended.")
                member_turn, bots = written
                return Replied(conv, member_turn, bots, step.explain, _outcome_recorded(recorded, conv))
            except self_service.DecisionChanged as e:
                use_autocommit(db)      # a fresh evaluation needs nothing more unless it names a guarantor
                step.turn.changed(e.fresh)
                db.commit()
            except self_service.CannotCommit:
                step.turn.cannot_record()
            spoken = [tts.speak(line) for line in step.lines]

        use_autocommit(db)
        out = Batch(db)
        member_turn, bots = write(out, None)
        out.send()
        db.commit()
        return Replied(conv, member_turn, bots, step.explain, _outcome_decided_nothing(conv))
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
    """The member's unfinished conversation, if there is one to carry on, with its turns."""
    conv = db.scalar(select(Conversation).where(Conversation.member_id == member.id, Conversation.status == "open")
                     .options(joinedload(Conversation.turns)))
    if conv is not None:
        abandon_if_idle(db, conv)
    return conv if conv is not None and conv.status == "open" else None


def with_turns(db: Session, conversation_id: int) -> Conversation | None:
    """It and its whole transcript, in one statement, however long."""
    return db.scalar(select(Conversation).where(Conversation.id == conversation_id).options(joinedload(Conversation.turns)))


def _blank_outcome(conv: Conversation) -> dict:
    return {"decision": "none", "application_id": conv.application_id, "requested_kes": conv.context.get("amount_kes"),
            "amount_kes": None, "term_months": conv.context.get("overrides", {}).get("term_months"),
            "instalment_kes": None, "guarantors": [], "balance_before_kes": None, "balance_after_kes": None,
            "review_requested": False, "ledger": None}


def _outcome_decided_nothing(conv: Conversation) -> dict | None:
    return _blank_outcome(conv) if conv.status == "completed" else None


def _ledger_part(loan: LoanAccount, entry: AccountEntry, before: int, guarantors: list[str]) -> dict:
    return dict(decision="reversed" if loan.status == "reversed" else "approved", amount_kes=loan.principal_kes,
                term_months=loan.term_months, instalment_kes=loan.monthly_instalment_kes, guarantors=guarantors,
                balance_before_kes=before, balance_after_kes=before + entry.amount_kes,
                ledger={"entry_id": entry.id, "reference": entry.reference, "posted_at": entry.posted_at,
                        "amount_kes": entry.amount_kes, "entry_type": entry.entry_type, "loan_id": loan.id})


def _outcome_recorded(recorded: self_service.Recorded, conv: Conversation) -> dict:
    """outcome_of, from what the reply has just written and read, at no further cost."""
    out = _blank_outcome(conv)
    out["requested_kes"] = recorded.final.request.amount_kes
    if recorded.paid is None:
        out["decision"] = "not_now" if recorded.final.outcome == "not_now" else "referred"
        return out
    out.update(_ledger_part(recorded.paid.loan, recorded.paid.entry, recorded.snapshot.transactional_kes,
                            recorded.paid.guarantors))
    return out


def outcome_of(db: Session, conv: Conversation) -> dict | None:
    """How it came out, from the ledger and the application as they stand now, or None
    while it is under way or if it was abandoned. decision: approved (the money was paid
    out), reversed, referred, not_now, or none when it ended with nothing decided. One
    statement, a row per verified guarantor."""
    if conv.status != "completed":
        return None
    out = _blank_outcome(conv)
    if conv.application_id is None:
        return out
    reviewed = (select(SelfServiceRun.id).where(SelfServiceRun.application_id == LoanApplication.id,
                                                SelfServiceRun.trigger == "review").limit(1).scalar_subquery())
    prior = AccountEntry.__table__.alias("prior")
    before = (select(func.coalesce(func.sum(prior.c.amount_kes), 0))
              .where(prior.c.account_id == AccountEntry.account_id, prior.c.id < AccountEntry.id).scalar_subquery())
    rows = db.execute(select(LoanApplication.amount_requested_kes, LoanApplication.status, reviewed.label("reviewed"),
                             LoanAccount, AccountEntry, before.label("before"), Guarantor.full_name)
                      .select_from(LoanApplication)
                      .outerjoin(LoanAccount, LoanAccount.application_id == LoanApplication.id)
                      .outerjoin(AccountEntry, and_(AccountEntry.loan_account_id == LoanAccount.id,
                                                    AccountEntry.entry_type == "loan_disbursement"))
                      .outerjoin(Guarantor, and_(Guarantor.application_id == LoanApplication.id, Guarantor.status == "verified",
                                                 LoanAccount.id.is_not(None)))
                      .where(LoanApplication.id == conv.application_id).order_by(Guarantor.id)).all()
    if not rows:
        return out
    first = rows[0]
    out["requested_kes"], out["review_requested"] = first.amount_requested_kes, first.reviewed is not None
    if first.LoanAccount is None:
        out["decision"] = "not_now" if first.status == "declined" else "referred"
        return out
    out.update(_ledger_part(first.LoanAccount, first.AccountEntry, first.before, [r.full_name for r in rows if r.full_name]))
    return out


__all__ = ["ConversationBusy", "ConversationClosed", "ConversationMissing", "Replied", "Spoken", "SpeechUnavailable",
           "abandon_if_idle", "abandon_idle_at_startup", "is_busy", "open_conversation", "outcome_of", "reply", "reply_to",
           "stage_of", "start", "turns_of", "with_turns"]
