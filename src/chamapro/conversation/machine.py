"""The conversation as a deterministic state machine. Each state is the question last
asked; advance() takes the member's answer as extraction read it and says what comes next.

    G1 -> CONSENT -> G2 -> R1 -> [CHECK_AMOUNT] -> evaluate
       -> C1, C2, C3, C4 and C6, as the engine asks, at most config.CONVERSATION_MAX_QUESTIONS in all
       -> CONFIRM on an approval or a reduced offer -> commit -> O1..O4 -> END

The language model writes nothing here and decides nothing: the engine decides, and every
line comes from templates.yaml. Three rules hold throughout: nothing is evaluated without
the member's consent; an answer that cannot be understood gets REASK once, and then a
person; a yes to CONSENT or CONFIRM is never assumed from silence or confusion.

advance() only reads. A decision to record is left on the Step as a ToRecord, with the words
that announce it already chosen, so that they can be spoken with nothing locked; service.py
writes it, the engine runs again under the locks, and if the answer has changed changed() or
cannot_record() says what to tell the member instead.
"""
from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from chamapro import config
from chamapro.api import decisions, member_text, profiles, self_service
from chamapro.api.db import Conversation, Member, User
from chamapro.api.decisions import Evaluation, LoanRequest, Snapshot

from . import templates
from .extract import Extracted
from .templates import Rendered

REVIEW, BOOK = "request_review", "book_interview"
ACTION_LABEL = {REVIEW: "ACTION_REVIEW", BOOK: "ACTION_BOOK"}
CLOSED = "END"
# Stands in on the record when a member gave an amount and nothing we could read as a purpose.
PURPOSE_NOT_GIVEN = "Not given"
# A conversation's own keys: asking again after a dropped connection pays out nothing new.
COMMIT_KEY, ACCEPT_KEY = "conversation-{}-commit", "conversation-{}-accept"
# Stands in an action until the application it belongs to has its id.
THIS_APPLICATION = -1


def first_name(member: Member) -> str:
    return member.full_name.split()[0]


def and_join(names: list[str]) -> str:
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]


def explain(ev: Evaluation) -> dict:
    """How this was worked out, whole: the turn's record, for officers and admins. The
    class, the probabilities, the SHAP values and the policy trace are in it, so a member
    never gets this: they get member_text.plain_explain of it."""
    sources: dict[str, list[str]] = {"records": [], "profile": [], "conversation": [], "missing": []}
    for name, source in sorted(ev.provenance.items()):
        sources[{"declared": "profile", "verified": "profile"}.get(source, source)].append(name)
    contributions = ev.contributions if isinstance(ev.contributions, list) else []
    return {"outcome": ev.outcome, "reason_code": ev.settled.reason_code, "reason": ev.reason,
            "reason_values": decisions.reason_values(ev.facts, ev.worked, ev.settled), "risk_class": ev.risk_class,
            "probabilities": ev.probabilities,
            "contributions": [{**c, "in_favour": member_text.in_favour(ev.risk_class, c["shap"])} for c in contributions],
            "shap_error": ev.contributions if isinstance(ev.contributions, str) else None,
            "features": ev.features, "provenance": ev.provenance, "sources": sources, "overrides": ev.overrides,
            "questions": ev.questions,
            "amount_kes": ev.amount_kes, "term_months": ev.facts.term_months, "instalment_kes": ev.instalment_kes,
            "policy_version": ev.policy_version, "trace": ev.trace}


@dataclass
class ToRecord:
    """A decision to write, and how far the Step had got before the lines announcing it."""
    evaluation: Evaluation
    accepted: Evaluation | None
    commit_key: str
    accept_key: str
    said: int
    acted: int
    state: str
    status: str


@dataclass
class Step:
    """What one answer leads to. Nothing here has been written yet."""
    lines: list[Rendered] = field(default_factory=list)
    state: str = ""
    context: dict = field(default_factory=dict)
    status: str = "open"
    explain: dict | None = None
    actions: list[dict] = field(default_factory=list)
    consent: bool | None = None
    corrections: dict | None = None
    confirmed_groups: list[str] | None = None
    evaluated: bool = False
    to_record: ToRecord | None = None
    turn: Turn | None = None


class Turn:
    def __init__(self, db: Session, conv: Conversation, member: Member, actor: User, today: date | None = None):
        self.db, self.conv, self.member, self.actor, self.today = db, conv, member, actor, today
        # A copy to the bottom: the row's own dict must still say what it said, or the
        # new state can compare equal to it and never be written.
        self.ctx = copy.deepcopy(conv.context or {})
        self.step = Step(state=conv.state, context=self.ctx, turn=self)
        self._snapshot: Snapshot | None = None
        self._last: Evaluation | None = None

    # --- Saying ---------------------------------------------------------------------------

    def say(self, template_id: str, **slots) -> Rendered:
        line = templates.render(template_id, self.conv.language, **slots)
        self.step.lines.append(line)
        return line

    def ask(self, state: str, template_id: str | None = None, **slots) -> None:
        """Move to a new question: the one-reask allowance starts again."""
        line = self.say(template_id or state, **slots)
        self.step.state = state
        self.ctx.update(reasks=0, question_id=template_id or state, question_en=line.text_en)

    def action(self, action_id: str, application_id: int | None = None) -> None:
        label = templates.render(ACTION_LABEL[action_id], self.conv.language)
        self.step.actions.append({"id": action_id, "label": label.text, "kik_pending": label.kik_pending,
                                  "application_id": application_id})

    def finish(self, *actions: tuple[str, int | None]) -> None:
        for action_id, application_id in actions:
            self.action(action_id, application_id)
        self.say("END", sacco_name=config.SACCO_NAME)
        self.step.state, self.step.status = CLOSED, "completed"

    def officer_can_help(self) -> None:
        """Nothing to decide on yet: no application to refer, so no O3."""
        self.say("OFFICER_HELP")
        self.finish((BOOK, None))

    def reask_or(self, otherwise) -> None:
        if self.ctx.get("reasks", 0) < 1:
            self.ctx["reasks"] = self.ctx.get("reasks", 0) + 1
            self.say("REASK")
        else:
            otherwise()

    # --- The engine -----------------------------------------------------------------------

    @property
    def overrides(self) -> dict:
        return self.ctx.setdefault("overrides", {})

    @property
    def snapshot(self) -> Snapshot:
        """What the database says, read once in a reply."""
        if self._snapshot is None:
            self._snapshot = decisions.read_snapshot(self.db, self.member)
        return self._snapshot

    def features(self) -> dict:
        return profiles.profile_features(self.db, self.member, self.today, records=self.snapshot.records).features

    def evaluate(self, refer_reason: str | None = None) -> Evaluation:
        if not self.conv.consent_given:
            raise RuntimeError("nothing is evaluated without the member's consent")
        self.step.evaluated = True
        request = LoanRequest(self.ctx["amount_kes"], self.ctx["purpose"])
        reason = refer_reason or self.ctx.get("refer_reason")
        self._last = decisions.evaluate(self.db, self.member, request, self.overrides, today=self.today, refer_reason=reason,
                                        snapshot=self.snapshot, reuse=self._last)
        self.step.explain = explain(self._last)
        return self._last

    def decide(self, refer_reason: str | None = None) -> None:
        self.route(self.evaluate(refer_reason))

    def route(self, ev: Evaluation) -> None:
        if ev.outcome == "clarify":
            if self.ctx.get("asked", 0) >= config.CONVERSATION_MAX_QUESTIONS:
                ev = self.evaluate("question_cap")
            else:
                self.ask_clarification(ev)
                return
        if ev.outcome in ("approve", "approve_reduced"):
            self.ctx["expected"] = [ev.outcome, ev.amount_kes]
            self.ask("CONFIRM", amount=ev.amount_kes, term=ev.facts.term_months, instalment=ev.instalment_kes,
                     guarantors=and_join([g.full_name for g in ev.worked.chosen]))
            return
        self.commit_and_tell(ev)

    def ask_clarification(self, ev: Evaluation) -> None:
        question = ev.questions[0]
        self.ctx["asked"] = self.ctx.get("asked", 0) + 1
        if question == "C2":
            if ev.facts.profile_income_kes is None:
                self.ask("C2", "C2_NEW")
            else:
                self.ask("C2", monthly_income=ev.facts.profile_income_kes)
        elif question == "C3":
            self.ask("C3", purpose=self.ctx["purpose"])
        elif question == "C6":
            self.ctx["offer_kes"] = ev.worked.offer_kes
            # Turned down, an offer their guarantors limit still leaves them short of a guarantor.
            self.ctx["if_declined"] = "offer_declined" if ev.worked.capacity_passes else "guarantors_short"
            self.ask("C6", max_amount=ev.worked.offer_kes)
        else:
            self.ask(question)

    def commit_and_tell(self, ev: Evaluation) -> None:
        """Choose the words for this decision and leave it to be written. A reduced offer the
        member has said yes to is taken at once: what they hear is how that comes out."""
        cid = self.conv.id
        accepted = None
        if ev.outcome == "approve_reduced":
            accepted = self_service.accepted_as_well(self.db, self.member, ev, self.snapshot)
            # What they took is what is recorded and told: the Why sheet and /present explain that.
            self.step.explain = explain(accepted)
        self.step.to_record = ToRecord(ev, accepted, COMMIT_KEY.format(cid), ACCEPT_KEY.format(cid), len(self.step.lines),
                                       len(self.step.actions), self.step.state, self.step.status)
        self.tell(accepted or ev)

    def tell(self, ev: Evaluation) -> None:
        outcome = ev.outcome
        if outcome == "approve":
            if ev.amount_kes < self.ctx["amount_kes"]:
                self.say("O2", amount=ev.amount_kes, term=ev.facts.term_months or self_service.TERM_FOR_THE_RECORD,
                         instalment=ev.instalment_kes)
            else:
                self.say("O1", first_name=first_name(self.member), amount=ev.amount_kes)
            self.finish((REVIEW, THIS_APPLICATION))
        elif outcome == "not_now":
            if ev.settled.months_left:
                self.say("O4", months=ev.settled.months_left)
            else:
                self.say("O4_GUARANTORS", min_guarantors=decisions.comparator.MIN_GUARANTORS)
            self.finish((REVIEW, THIS_APPLICATION), (BOOK, THIS_APPLICATION))
        else:
            # A referral is already with an officer: there is nothing further to ask for.
            self.say("O3")
            self.finish((BOOK, THIS_APPLICATION))

    def _take_back(self) -> None:
        """The lines announcing a decision that was not written."""
        record = self.step.to_record
        del self.step.lines[record.said:], self.step.actions[record.acted:]
        self.step.state, self.step.status, self.step.to_record = record.state, record.status, None

    def changed(self, fresh: Evaluation) -> None:
        """Something moved in the moment before: once, tell them what is true now."""
        self._take_back()
        if self.ctx.get("changed"):
            self.officer_can_help()
            return
        self.ctx["changed"] = True
        self.step.explain = explain(fresh)
        self._snapshot, self._last = fresh.snapshot, fresh
        self.route(fresh)

    def cannot_record(self) -> None:
        self._take_back()
        self.officer_can_help()

    # --- Applying answers -----------------------------------------------------------------

    def give_up_on(self, question: str) -> None:
        """Asked twice and still not understood: a person takes it from here."""
        if question in ("CONSENT", "G2", "R1"):
            self.officer_can_help()
            return
        key = decisions.ANSWER_KEY.get(question)
        if key is not None:
            self.overrides.setdefault(key, None)
        self.ctx["refer_reason"] = "not_understood"
        self.decide()

    def take(self, question: str, fields: dict) -> None:
        """A question has its answer, checked if it needed to be."""
        if question == "R1":
            self.ctx.update(amount_kes=fields["amount_kes"], purpose=fields["purpose"])
        elif question == "C1":
            self.overrides["term_months"] = fields["term_months"]
        elif question == "C2":
            self.overrides["monthly_income_kes"] = fields["monthly_income_kes"]
        elif question == "C3":
            self.overrides["expected_monthly_return_kes"] = fields["expected_monthly_return_kes"]
        elif question == "C4":
            self.overrides["chama_loan_use"] = fields["chama_loan_use"]
            if fields.get("chama_instalment_kes") is not None:
                self.overrides["chama_instalment_kes"] = fields["chama_instalment_kes"]
        self.decide()

    def check_amount_or_take(self, question: str, fields: dict, a: Extracted) -> None:
        """The model and the parser read different money: the member settles it."""
        conflict = a.amount_conflict
        if conflict is None:
            self.take(question, fields)
            return
        self.ctx["pending"] = {"question": question, "fields": fields, "field": conflict["field"],
                               "question_en": self.ctx.get("question_en")}
        self.ask("CHECK_AMOUNT", amount=conflict["model"])


# --- One handler per state ------------------------------------------------------------------

def _consent(t: Turn, a: Extracted) -> None:
    answer = a.fields.get("answer")
    if answer == "yes":
        t.step.consent = True
        _ask_profile_check(t)
    elif answer == "no":
        t.step.consent = False
        t.finish((BOOK, None))
    else:
        # Never taken as a yes. Twice unclear is the same as not given.
        t.reask_or(lambda: _no_consent(t))


def _no_consent(t: Turn) -> None:
    t.step.consent = False
    t.officer_can_help()


def _ask_profile_check(t: Turn) -> None:
    """The summary from profile_features. A member whose profile cannot fill it has nothing
    to check: the engine will ask what it needs."""
    features = t.features()
    wanted = {"household_size": features["household_size"], "children": features["children"],
              "monthly_income": features["monthly_income_kes"]}
    if any(v is None for v in wanted.values()):
        t.ask("R1")
    elif decisions.income_is_stale(t.db, t.member, t.today, seen=t.snapshot.confirmed):
        # Left out rather than read back as fact: C2 asks about it, once, if it comes to that.
        t.ctx["read_out"] = ["household"]
        wanted.pop("monthly_income")
        t.ask("G2", "G2_NO_INCOME", **wanted)
    else:
        t.ctx["read_out"] = ["household", "income"]
        t.ask("G2", **wanted)


def _profile_check(t: Turn, a: Extracted) -> None:
    corrections = a.fields.get("corrections")
    if corrections:
        t.overrides.update(corrections)
        t.step.corrections = corrections
        t.ask("R1")
    elif a.fields.get("answer") == "yes":
        t.step.confirmed_groups = t.ctx.pop("read_out", None)
        t.ask("R1")
    else:
        # A bare "no" says something is wrong and not what.
        t.reask_or(lambda: t.give_up_on("G2"))


def _request(t: Turn, a: Extracted) -> None:
    amount, purpose = a.fields.get("amount_kes"), a.fields.get("purpose_text")
    if amount is None:
        t.reask_or(lambda: t.give_up_on("R1"))
    elif not purpose:
        def refer_without_a_purpose():
            t.ctx.update(amount_kes=amount, purpose=PURPOSE_NOT_GIVEN, refer_reason="not_understood")
            t.decide()
        t.reask_or(refer_without_a_purpose)
    else:
        t.check_amount_or_take("R1", {"amount_kes": amount, "purpose": purpose}, a)


def _check_amount(t: Turn, a: Extracted) -> None:
    pending = t.ctx["pending"]
    question, fields, money = pending["question"], dict(pending["fields"]), pending["field"]
    answer, corrected = a.fields.get("answer"), a.fields.get("amount_kes")
    if answer == "yes" and corrected is None:
        t.ctx.pop("pending")
        t.take(question, fields)
    elif corrected is not None:
        t.ctx.pop("pending")
        fields[money] = corrected
        t.take(question, fields)
    elif answer == "no":
        # Back to the question itself, with its one re-ask already spent.
        t.ctx.pop("pending")
        t.step.state = question
        t.ctx.update(question_id=question, question_en=pending["question_en"], reasks=1)
        t.say("REASK")
    else:
        t.reask_or(lambda: t.give_up_on(question))


def _term(t: Turn, a: Extracted) -> None:
    term = a.fields.get("term_months")
    if term is None:
        t.reask_or(lambda: t.give_up_on("C1"))
    else:
        t.take("C1", {"term_months": term})


def _income(t: Turn, a: Extracted) -> None:
    income = a.fields.get("monthly_income_kes")
    if income is None and a.fields.get("answer") == "yes":
        income = t.features()["monthly_income_kes"]
    if income is None:
        t.reask_or(lambda: t.give_up_on("C2"))
    else:
        t.check_amount_or_take("C2", {"monthly_income_kes": income}, a)


def _expected_return(t: Turn, a: Extracted) -> None:
    value = a.fields.get("expected_monthly_return_kes")
    if value is None:
        t.reask_or(lambda: t.give_up_on("C3"))
    else:
        t.check_amount_or_take("C3", {"expected_monthly_return_kes": value}, a)


def _chama(t: Turn, a: Extracted) -> None:
    active, instalment = a.fields.get("chama_loan_active"), a.fields.get("chama_instalment_kes")
    if active is True and instalment is None or active is None:
        t.reask_or(lambda: t.give_up_on("C4"))
    elif active:
        t.check_amount_or_take("C4", {"chama_loan_use": 2, "chama_instalment_kes": instalment}, a)
    else:
        # Not now: what the profile says of before stands, except that a current loan is now a past one.
        before = t.features()["chama_loan_use"]
        t.take("C4", {"chama_loan_use": 1 if before in (1, 2) else 0})


def _smaller_amount(t: Turn, a: Extracted) -> None:
    answer = a.fields.get("answer")
    if answer == "yes":
        t.overrides["accepted_amount_kes"] = t.ctx["offer_kes"]
        t.decide()
    elif answer == "no":
        # They have said no to this figure: a person, rather than offering it again.
        t.overrides["accepted_amount_kes"] = None
        t.ctx["refer_reason"] = t.ctx.get("if_declined", "offer_declined")
        t.decide()
    else:
        t.reask_or(lambda: t.give_up_on("C6"))


def _confirm(t: Turn, a: Extracted) -> None:
    answer = a.fields.get("answer")
    if answer == "yes":
        ev = t.evaluate()
        if [ev.outcome, ev.amount_kes] != t.ctx.get("expected"):
            t.route(ev)     # not what they said yes to: they hear what is true now
        else:
            t.commit_and_tell(ev)
    elif answer == "no":
        # No decision has been recorded, so there is nothing to review.
        t.finish((BOOK, None))
    else:
        t.reask_or(t.officer_can_help)


HANDLERS = {"CONSENT": _consent, "G2": _profile_check, "R1": _request, "CHECK_AMOUNT": _check_amount, "C1": _term,
            "C2": _income, "C3": _expected_return, "C4": _chama, "C6": _smaller_amount,
            "CONFIRM": _confirm}


def opening(conv: Conversation, member: Member) -> tuple[list[Rendered], dict]:
    """The first bot turns, and the context they leave."""
    g1 = templates.render("G1", conv.language, first_name=first_name(member), sacco_name=config.SACCO_NAME)
    consent = templates.render("CONSENT", conv.language)
    return [g1, consent], {"reasks": 0, "asked": 0, "overrides": {}, "question_id": "CONSENT",
                           "question_en": consent.text_en}


def advance(db: Session, conv: Conversation, member: Member, actor: User, answer: Extracted,
            today: date | None = None) -> Step:
    turn = Turn(db, conv, member, actor, today)
    HANDLERS[conv.state](turn, answer)
    return turn.step
