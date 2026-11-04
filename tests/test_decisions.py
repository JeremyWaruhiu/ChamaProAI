"""The decision engine and the ledger operations: the policy table, clarification
priority and cap, the instalment and affordability arithmetic, that the model never
declines and self-declared savings always refer, committing, reversal, the endpoints'
permissions and idempotency, the officers' page, and the two demo members.

The policy runs without a database or a model, from Facts. Everything after it scores
with a stand-in classifier unless it says needs_classifier: outcomes here depend on
what a class means, not on which class the real model would give."""
import random
import secrets
import threading
from datetime import date, timedelta

import pandas as pd
import pytest
from sqlalchemy import create_engine, event, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import score_interview
import seed_demo
import seed_members
from chamapro import config
from chamapro.api import decisions, ledger, member_text, profiles, self_service
from chamapro.api.db import (AccountEntry, Assessment, AuditLog, Decision, Guarantor, GuarantorPledge, IdempotencyKey,
                             Interview, LoanAccount, LoanApplication, Member, MemberProfileHistory, SelfServiceRun,
                             SessionLocal, User, engine, init_db, nairobi_today, utcnow)
from chamapro.api.decisions import Facts, GuarantorOption, LoanRequest
from conftest import assessed, needs_classifier, new_application, new_member
from test_member_access import leaks
from test_query_counts import queries  # noqa: F401  (a fixture)


def pledged(n=2, free=30000):
    return tuple(GuarantorOption(i, f"G-{i}", f"Guarantor {i}", "0712345678", free, pledge_id=i) for i in range(1, n + 1))


def facts(**over) -> Facts:
    """Everything passes: Low, on record, well inside every limit."""
    base = dict(requested_kes=40000, purpose="School fees", amount_kes=40000, term_months=12, income_kes=45000,
                deposits_kes=30000, declared_savings_kes=0, own_free_kes=30000, months_member=60, risk_class="Low",
                contributions=[], guarantors=pledged(), any_guarantor=True)
    return Facts(**{**base, **over})


def settled(**over):
    f = facts(**over)
    w = decisions.work_out(f)
    return decisions.settle(f, w, decisions.clarifications(f, w, decisions.question_triggers(f, w)))


def asked_list(**over):
    f = facts(**over)
    w = decisions.work_out(f)
    return decisions.clarifications(f, w, decisions.question_triggers(f, w))


ANSWERED = dict(asked=frozenset({"C1"}), answered=frozenset({"C1"}))

# (case, facts, outcome, reason code, amount). Every outcome, and every way to each.
POLICY_TABLE = [
    ("all pass, Low", {}, "approve", "approve", 40000),
    ("exactly at the auto limit", dict(requested_kes=50000, amount_kes=50000), "approve", "approve", 50000),
    ("Medium with a clarification answered", dict(risk_class="Medium", **ANSWERED), "approve", "approve", 40000),
    ("own deposits cover it", dict(amount_kes=20000, requested_kes=20000), "approve", "approve", 20000),
    ("reduced to the savings rule", dict(requested_kes=45000, amount_kes=45000, deposits_kes=10000, own_free_kes=10000),
     "approve_reduced", "reduced_rule", 30000),
    ("reduced to what income allows", dict(income_kes=20000, requested_kes=60000, amount_kes=60000, term_months=6),
     "approve_reduced", "reduced_affordability", 38632),
    ("exactly half the request is still offered", dict(requested_kes=60000, amount_kes=60000, deposits_kes=10000,
                                                       own_free_kes=10000), "approve_reduced", "reduced_rule", 30000),
    ("Medium with an answer gets the offer too", dict(risk_class="Medium", requested_kes=45000, amount_kes=45000,
                                                      deposits_kes=10000, own_free_kes=10000, **ANSWERED),
     "approve_reduced", "reduced_rule", 30000),
    ("High risk", dict(risk_class="High"), "refer", "officer_review", None),
    ("Medium with nothing left to ask", dict(risk_class="Medium"), "refer", "officer_review", None),
    ("self-declared savings", dict(deposits_kes=None, declared_savings_kes=90000), "refer", "self_declared", None),
    ("above the auto limit, within both maximums", dict(requested_kes=60000, amount_kes=60000), "refer", "above_limit", None),
    ("offer still above the auto limit", dict(requested_kes=100000, amount_kes=100000), "refer", "above_limit", None),
    ("offer under half the request", dict(requested_kes=100000, amount_kes=100000, deposits_kes=10000, own_free_kes=10000,
                                          asked=frozenset({"C6"}), declined=frozenset({"C6"})), "refer", "offer_too_small", None),
    ("in arrears", dict(in_arrears=True), "refer", "arrears", None),
    ("gave no term", dict(term_months=None, asked=frozenset({"C1"}), declined=frozenset({"C1"})), "refer", "details_missing", None),
    ("income unknown and not given", dict(income_kes=None, asked=frozenset({"C2"}), declined=frozenset({"C2"})), "refer",
     "details_missing", None),
    ("would not confirm stale income", dict(income_age_days=400, asked=frozenset({"C2"}), declined=frozenset({"C2"})),
     "refer", "details_missing", None),
    ("guarantors do not cover it", dict(guarantors=pledged(free=2000), own_free_kes=30000,
                                        asked=frozenset({"C5"}), declined=frozenset({"C5"})), "refer", "guarantors_short", None),
    ("one guarantor only", dict(guarantors=pledged(n=1), asked=frozenset({"C5"}), declined=frozenset({"C5"})), "refer",
     "guarantors_short", None),
    ("a named guarantor is needed", dict(guarantors=(*pledged(n=1), GuarantorOption(9, "G-9", "Named", "07", 30000)),
                                         asked=frozenset({"C5"}), answered=frozenset({"C5"})), "refer", "named_guarantor", None),
    ("membership under six months", dict(months_member=5), "not_now", "membership", None),
    ("no guarantors at all", dict(guarantors=(), any_guarantor=False), "not_now", "no_guarantors", None),
    ("a question to ask first", dict(term_months=None), "clarify", "clarify", None),
]


@pytest.mark.parametrize("over, outcome, code, amount", [c[1:] for c in POLICY_TABLE], ids=[c[0] for c in POLICY_TABLE])
def test_policy_table(over, outcome, code, amount):
    s = settled(**over)
    assert (s.outcome, s.reason_code, s.amount_kes) == (outcome, code, amount)


def test_the_table_covers_every_outcome_and_reason():
    outcomes = {c[2] for c in POLICY_TABLE}
    assert outcomes == {"approve", "approve_reduced", "refer", "not_now", "clarify"}
    assert {c[3] for c in POLICY_TABLE} == set(member_text.DECISION_REASONS["en"])


def test_not_now_says_how_many_months_are_left():
    s = settled(months_member=2)
    assert s.months_left == 4
    words = member_text.decision_reason(s.reason_code, {"months_left": 4, "min_months": 6})
    assert "4 more months" in words
    assert "1 more month to" in member_text.decision_reason("membership", {"months_left": 1, "min_months": 6})


@pytest.mark.parametrize("risk", ["Low", "Medium", "High"])
@pytest.mark.parametrize("over", [dict(in_arrears=True), dict(requested_kes=90000, amount_kes=90000),
                                  dict(deposits_kes=1000, own_free_kes=1000), dict(income_kes=1000),
                                  dict(guarantors=pledged(free=1), own_free_kes=0), {}])
def test_the_model_alone_never_declines(risk, over):
    """not_now needs a rule the member has not met; no class and no failed check here
    produces it, and High with every rule met is a referral."""
    for answered in (frozenset(), frozenset({"C1"})):
        s = settled(risk_class=risk, answered=answered, asked=answered, **over)
        assert s.outcome != "not_now"
    assert settled(risk_class="High").outcome == "refer"


@pytest.mark.parametrize("risk", ["Low", "Medium", "High"])
@pytest.mark.parametrize("months, any_g, amount", [(60, True, 1000), (60, True, 49000), (2, True, 1000), (60, False, 1000),
                                                   (2, False, 1000), (60, True, 900000)])
def test_self_declared_savings_always_refer(risk, months, any_g, amount):
    """Whatever else is true, even a member who would otherwise hear "not now": nobody
    has checked the figure, so a person decides."""
    f = dict(deposits_kes=None, declared_savings_kes=500000, risk_class=risk, months_member=months, any_guarantor=any_g,
             requested_kes=amount, amount_kes=amount)
    s = settled(**f)
    assert (s.outcome, s.reason_code) == ("refer", "self_declared")


# --- Clarifications -----------------------------------------------------------------

TOP_INCOME = [{"feature": "log_monthly_income", "value": 10.0, "shap": 0.5}, {"feature": "age", "value": 40.0, "shap": 0.1}]
LOW_INCOME = [{"feature": f"B3A__{i}", "value": 1.0, "shap": 0.5} for i in range(1, 5)] + \
             [{"feature": "log_monthly_income", "value": 10.0, "shap": 0.01}]


@pytest.mark.parametrize("over, want", [
    (dict(term_months=None), ["C1"]),
    (dict(income_age_days=181), ["C2"]),
    (dict(income_age_days=180), []),
    (dict(income_age_days=None), ["C2"]),
    (dict(income_kes=None), ["C2"]),
    (dict(income_verified=False, contributions=TOP_INCOME), ["C2"]),
    (dict(income_verified=False, contributions=LOW_INCOME), []),
    (dict(income_verified=True, contributions=TOP_INCOME), []),
    (dict(purpose="A dairy cow", income_kes=12000, requested_kes=12000, amount_kes=12000, term_months=3), ["C3"]),
    (dict(purpose="School fees", income_kes=12000, requested_kes=12000, amount_kes=12000, term_months=3), []),
    (dict(purpose="A dairy cow"), []),
    (dict(chama_use_known=False), ["C4"]),
    (dict(credit_age_days=181), ["C4"]),
    (dict(guarantors=pledged(free=1000), own_free_kes=0), ["C5"]),
    (dict(guarantors=pledged(n=1)), ["C5"]),
    (dict(requested_kes=40000, amount_kes=40000, deposits_kes=5000, own_free_kes=5000, income_kes=6000, term_months=6), ["C6"]),
])
def test_each_question_fires_on_its_own_condition(over, want):
    assert asked_list(**over) == want


def test_priority_order_and_the_two_question_cap():
    over = dict(term_months=None, income_age_days=999, chama_use_known=False, guarantors=pledged(free=1), own_free_kes=0)
    assert asked_list(**over) == ["C1", "C2"]
    assert asked_list(**over, asked=frozenset({"C1"})) == ["C2", "C4"]
    assert asked_list(**over, asked=frozenset({"C1", "C2"})) == ["C4", "C5"]
    assert asked_list(**over, asked=frozenset({"C1", "C2", "C4"})) == ["C5"]


def test_a_question_is_never_asked_twice_even_when_its_condition_still_holds():
    f = dict(guarantors=pledged(free=1000), own_free_kes=0, asked=frozenset({"C5"}), declined=frozenset({"C5"}))
    assert asked_list(**f) == []
    assert settled(**f).outcome == "refer"


def test_no_question_for_what_an_answer_cannot_change():
    assert asked_list(deposits_kes=None, income_age_days=999) == []                 # self-declared
    assert asked_list(deposits_kes=None, term_months=None) == ["C1"]                # but the record needs a term
    assert asked_list(months_member=1, term_months=None) == []                      # not now
    assert asked_list(guarantors=(), any_guarantor=False, term_months=None) == []
    assert asked_list(risk_class="High", guarantors=pledged(free=1), own_free_kes=0) == []
    assert asked_list(risk_class="High", income_age_days=999) == ["C2"]             # this one can move the score
    assert asked_list(requested_kes=60000, amount_kes=60000, income_age_days=999) == []     # an officer's either way
    assert asked_list(final=True, term_months=None, income_age_days=999) == []


def test_affordability_questions_wait_while_their_inputs_may_change():
    over = dict(requested_kes=40000, amount_kes=40000, deposits_kes=5000, own_free_kes=5000, income_kes=6000, term_months=6)
    assert asked_list(**over, income_age_days=999) == ["C2"]    # C6 is above both too, but income is about to move
    assert asked_list(**over, income_age_days=999, asked=frozenset({"C2"}), answered=frozenset({"C2"})) == ["C6"]


def test_c3_counts_the_expected_return_for_affordability_only():
    f = facts(purpose="A dairy cow", income_kes=12000, requested_kes=12000, amount_kes=12000, term_months=3)
    w = decisions.work_out(f)
    assert w.instalment_kes == 4081 and round(w.limit_kes) == 4000 and w.affordability_passes is False and w.affordability_near
    with_return = facts(purpose="A dairy cow", income_kes=12000, requested_kes=12000, amount_kes=12000, term_months=3,
                        expected_return_kes=3000, asked=frozenset({"C3"}), answered=frozenset({"C3"}))
    w = decisions.work_out(with_return)
    assert round(w.limit_kes) == 5000 and w.affordability_passes is True
    assert with_return.income_kes == 12000


# --- The arithmetic ---------------------------------------------------------------------

@pytest.mark.parametrize("principal, term, want", [
    (40000, 12, 3554),      # 40,000 x 0.01 / (1 - 1.01^-12) = 3,553.95
    (45000, 12, 3999),      # 3,998.2
    (60000, 12, 5331),      # 5,330.93
    (12000, 3, 4081),       # 4,080.27
    (100000, 24, 4708),     # 4,707.35
    (1000, 1, 1010),        # one month: principal and one month's interest
])
def test_the_instalment_on_a_reducing_balance(principal, term, want):
    assert ledger.instalment_kes(principal, term) == want


def test_the_instalment_with_no_interest_and_term_times_instalment_clears_the_loan():
    assert ledger.instalment_kes(1000, 3, rate=0) == 334
    for principal, term in ((40000, 12), (45000, 12), (999, 7)):
        i, balance = ledger.instalment_kes(principal, term), float(principal)
        for _ in range(term):
            balance = balance * 1.01 - i
        assert balance <= 0.01


@pytest.mark.parametrize("limit, term", [(10000, 12), (3333.33, 12), (15000, 24), (1, 1), (0.5, 6), (0, 12), (7321.5, 18)])
def test_the_largest_principal_is_exactly_the_most_the_limit_allows(limit, term):
    p = ledger.largest_principal(limit, term)
    assert p == 0 or ledger.instalment_kes(p, term) <= limit
    assert ledger.instalment_kes(p + 1, term) > limit


def test_affordability_is_a_third_of_income_less_known_obligations():
    w = decisions.work_out(facts(income_kes=30000, loan_instalments_kes=3000, chama_instalment_kes=3000))
    assert w.obligations_kes == 6000 and w.disposable_kes == 24000 and w.limit_kes == pytest.approx(8000)
    assert w.affordable_max_kes == 90040 and w.instalment_kes == 3554 and w.affordability_passes
    w = decisions.work_out(facts(income_kes=5000, loan_instalments_kes=9000))
    assert w.disposable_kes == -4000 and w.limit_kes == 0 and w.affordable_max_kes == 0 and w.affordability_passes is False


def test_the_rule_is_three_times_deposits_and_capacity_covers_the_rest():
    w = decisions.work_out(facts(deposits_kes=10000, own_free_kes=10000, requested_kes=30000, amount_kes=30000))
    assert w.rule_max_kes == 30000 and w.capacity_need_kes == 20000 and w.capacity_passes
    w = decisions.work_out(facts(deposits_kes=10000, own_free_kes=4000, requested_kes=30000, amount_kes=30000,
                                 guarantors=pledged(free=10000)))
    assert w.capacity_need_kes == 26000 and not w.capacity_passes     # the rest of her deposits back someone else


def test_standing_pledges_come_first_and_more_only_as_needed():
    named = GuarantorOption(9, "G-9", "Named", "07", 90000)
    a, b, c = pledged(n=3, free=1000)
    big = GuarantorOption(5, "G-5", "Big", "07", 8000, pledge_id=5)
    assert decisions.choose_guarantors((named, a, b), 500) == (a, b)
    assert decisions.choose_guarantors((a, b, c, big), 8000) == (big, a)
    assert [g.member_no for g in decisions.choose_guarantors((a, b, c, big), 9500)] == ["G-5", "G-1", "G-2"]
    assert decisions.choose_guarantors((GuarantorOption(1, "x", "x", "x", 0, 1), a), 0) == (a,)


def test_the_shares_add_up_and_stay_within_capacity():
    small = GuarantorOption(1, "A", "A", "07", 1000, pledge_id=1)
    big = GuarantorOption(2, "B", "B", "07", 50000, pledge_id=2)
    assert {g.member_no: v for g, v in decisions.allocate((small, big), 10000)} == {"A": 1000, "B": 9000}
    assert {g.member_no: v for g, v in decisions.allocate((small, big), 0)} == {"A": 1, "B": 1}
    assert {g.member_no: v for g, v in decisions.allocate((small, big), 1)} == {"A": 1, "B": 1}


def test_the_purpose_decides_only_whether_c3_is_asked():
    assert all(decisions.income_generating(p) for p in ("A dairy cow", "Stock for my shop", "Farm inputs", "Boda boda"))
    assert not any(decisions.income_generating(p) for p in ("School fees", "Medical bills", "Roof repairs"))


def test_the_version_names_its_thresholds(monkeypatch):
    assert decisions.policy_version() == config.POLICY_BASE_VERSION
    monkeypatch.setattr(config, "AUTO_APPROVE_LIMIT_KES", 60000)
    other = decisions.policy_version()
    assert other.startswith(config.POLICY_BASE_VERSION + "+") and len(other) <= 32


# --- With a database: a stand-in classifier ------------------------------------------------

CONTRIBUTIONS = [{"feature": "age", "value": 40.0, "shap": 0.3}, {"feature": "education", "value": 4.0, "shap": 0.2},
                 {"feature": "household_size", "value": 5.0, "shap": 0.1}, {"feature": "log_monthly_income", "value": 10.0, "shap": 0.05}]
TOP_DRIVER = [{"feature": "log_monthly_income", "value": 10.0, "shap": 0.4}, *CONTRIBUTIONS]


@pytest.fixture
def model(monkeypatch):
    """The class, by default Low, or by the income it was given. Replaces the classifier
    alone: everything around it is the real engine."""
    box = {"risk": "Low", "contributions": CONTRIBUTIONS, "seen": []}

    def score(features):
        box["seen"].append(features)
        risk = box["risk"](features) if callable(box["risk"]) else box["risk"]
        return score_interview.Scored(
            {"risk_class": risk, "probabilities": {"Low": 0.5, "Medium": 0.3, "High": 0.2},
             "top_contributions": box["contributions"], "extraction_completeness": 0.9, "features_populated": 30,
             "features_total": 35}, pd.DataFrame([{"age": 40.0, "log_monthly_income": 10.0, "children": float("nan")}]),
            "classifier.joblib", "0" * 64)
    monkeypatch.setattr(decisions, "score_features", score)
    self_service.evaluations.clear()
    self_service.commits.clear()
    yield box
    self_service.evaluations.clear()
    self_service.commits.clear()


PROFILE = {"date_of_birth": date(1982, 3, 1), "sex": "female", "education": 4, "marital_status": "married",
           "household_size": 5, "children": 3, "children_under5": 0, "children_in_school": 2,
           "monthly_income_kes": 45000, "agri_income_kes": 6000, "income_sources": {"own_business": 1},
           "non_monetary_savings": {"livestock": 1}, "purchases_last_12m": {}, "chama_loan_use": 0,
           "lost_as_guarantor_chama": 0}


def post_entry(member_id, amount, kind="deposits", entry_type="deposit"):
    with SessionLocal() as db:
        ledger.post_entry(db, member_id, kind, entry_type, amount, f"T-{secrets.token_hex(6)}")
        db.commit()


def add_guarantor(borrower_id, free=30000):
    gid, _, _ = new_member(login=False)
    if free:
        post_entry(gid, free)
    with SessionLocal() as db:
        ledger.add_pledge(db, borrower_id, gid)
        db.commit()
    return gid


def borrower(deposits=30000, joined="2020-01-01", guarantors=2, free=30000, verified=True, **profile):
    """(member id, signed-in client, guarantor ids): on the ledger, profile saved today."""
    mid, _, member = new_member(joined_on=joined)
    with SessionLocal() as db:
        m = db.get(Member, mid)
        profiles.save_profile(db, m, {**PROFILE, **profile}, "registration", None)
        if verified:
            profiles.verify_profile(db, m, db.scalar(select(User).where(User.username == "officer1")))
        db.commit()
    if deposits is not None:
        post_entry(mid, deposits)
    return mid, member, [add_guarantor(mid, free) for _ in range(guarantors)]


REQUEST = LoanRequest(40000, "School fees", 12)
BODY = {"amount_kes": 40000, "purpose": "School fees", "term_months": 12}


def evaluate(mid, request=REQUEST, overrides=None, **kw):
    with SessionLocal() as db:
        return decisions.evaluate(db, db.get(Member, mid), request, overrides, **kw)


def commit_it(mid, request=REQUEST, overrides=None, key=None):
    with SessionLocal() as db:
        ev = decisions.evaluate(db, db.get(Member, mid), request, overrides)
        actor = db.get(Member, mid).user or db.scalar(select(User).where(User.username == "officer1"))
        return self_service.commit(db, ev, key or secrets.token_hex(8), actor)


def key():
    return {"Idempotency-Key": secrets.token_hex(8)}


def committed_body(ev_outcome, amount=None, **over):
    return {**BODY, "expected_outcome": ev_outcome, "expected_amount_kes": amount, **over}


def age_income(mid, days):
    """Their income was last set this long ago, and nothing has confirmed it since."""
    with SessionLocal() as db:
        p = db.get(Member, mid).profile
        then = utcnow() - timedelta(days=days)
        p.income_updated_at, p.income_verified_at, p.income_verified_by = then, None, None
        p.income_source = "member_update"
        db.commit()


def client_writes(fn):
    """fn's statements on the app's engine that change anything."""
    seen = []

    def watch(conn, cursor, statement, *_):
        if not statement.lstrip().upper().startswith(("SELECT", "PRAGMA")):
            seen.append(statement)
    event.listen(engine, "before_cursor_execute", watch)
    try:
        fn()
    finally:
        event.remove(engine, "before_cursor_execute", watch)
    return seen


def test_evaluate_writes_nothing_and_leaves_the_profile_alone(client, model):
    mid, _, _ = borrower()
    with SessionLocal() as db:
        before = db.scalar(select(func.count(MemberProfileHistory.id)))
    writes = client_writes(lambda: evaluate(mid, overrides={"monthly_income_kes": 90000, "term_months": 6}))
    assert writes == []
    with SessionLocal() as db:
        m = db.get(Member, mid)
        assert m.profile.monthly_income_kes == 45000
        assert db.scalar(select(func.count(MemberProfileHistory.id))) == before


def test_overrides_replace_the_profile_for_this_evaluation_and_say_so(client, model):
    mid, _, _ = borrower(chama_loan_use=None)
    ev = evaluate(mid, overrides={"monthly_income_kes": 90000, "chama_loan_use": 2, "chama_instalment_kes": 1500})
    assert model["seen"][-1]["monthly_income_kes"] == 90000 and model["seen"][-1]["chama_loan_use"] == 2
    assert ev.provenance["monthly_income_kes"] == "conversation" and ev.provenance["chama_instalment_kes"] == "conversation"
    assert ev.provenance["household_size"] == "verified" and ev.provenance["sacco_loan_use"] == "records"
    assert ev.worked.obligations_kes == 1500 and ev.trace["clarifications"]["answered"] == ["C2", "C4"]
    assert "chama_instalment_kes" not in model["seen"][-1]


@pytest.mark.parametrize("bad, words", [({"age": 30}, "age cannot be given"), ({"sacco_loan_use": 0}, "cannot be given"),
                                        ({"chama_instalment_kes": 10}, "comes with chama_loan_use"),
                                        ({"accepted_amount_kes": 40001}, "cannot exceed")])
def test_overrides_are_only_what_a_question_sets(client, model, bad, words):
    mid, _, _ = borrower()
    with pytest.raises(decisions.BadOverride, match=words):
        evaluate(mid, overrides=bad)


def test_the_trace_has_every_check_with_its_values(client, model):
    mid, _, gs = borrower(deposits=10000)
    ev = evaluate(mid, LoanRequest(30000, "School fees", 12))
    t = ev.trace
    assert ev.outcome == "approve" and t["policy_version"] == config.POLICY_BASE_VERSION
    assert [c["check"] for c in t["checks"]] == ["deposits_on_record", "membership", "savings_multiple", "guarantors",
                                                 "guarantor_capacity", "affordability", "auto_limit", "risk", "no_arrears"]
    assert all(c["passed"] for c in t["checks"])
    by = {c["check"]: c["values"] for c in t["checks"]}
    assert by["savings_multiple"] == {"amount_kes": 30000, "maximum_kes": 30000, "multiplier": 3}
    assert by["affordability"]["instalment_kes"] == 2666 and by["affordability"]["limit_kes"] == 15000
    assert by["guarantor_capacity"]["need_kes"] == 20000
    assert t["thresholds"]["AUTO_APPROVE_LIMIT_KES"] == 50000 and t["model"]["risk_class"] == "Low"
    assert t["maximums"] == {"rule_kes": 30000, "affordable_kes": 168826}


def test_income_age_counts_a_real_confirmation_but_not_an_edit_elsewhere(client, model):
    mid, member, _ = borrower()
    age_income(mid, 200)
    assert evaluate(mid).questions == ["C2"]
    # Another group's check moves confirmed_at, and says nothing of income.
    r = client.post(f"/api/members/{mid}/profile/verify", json={"groups": ["household"]})
    assert r.status_code == 200, r.text
    assert evaluate(mid).questions == ["C2"]
    assert member.post("/api/me/profile/confirm").status_code == 200
    assert evaluate(mid).questions == []


def test_unverified_income_is_asked_only_while_it_drives_the_score(client, model):
    mid, _, _ = borrower(verified=False)
    assert evaluate(mid).questions == []                # fresh, and not among the top three
    model["contributions"] = TOP_DRIVER
    assert evaluate(mid).questions == ["C2"]
    assert evaluate(mid, overrides={"monthly_income_kes": 45000}).questions == []


def test_loans_count_as_obligations_and_arrears_are_for_an_officer(client, model):
    mid, _, _ = borrower()
    with SessionLocal() as db:
        ledger.issue_loan(db, mid, 12000, 12, 2000, nairobi_today() - timedelta(days=5))
        db.commit()
    ev = evaluate(mid)
    assert ev.outcome == "approve" and ev.worked.obligations_kes == 2000
    assert ev.worked.limit_kes == pytest.approx(43000 / 3)
    with SessionLocal() as db:
        loan = db.scalar(select(LoanAccount).where(LoanAccount.member_id == mid))
        loan.disbursed_on = nairobi_today() - timedelta(days=60)
        db.commit()
    ev = evaluate(mid)
    assert (ev.outcome, ev.settled.reason_code) == ("refer", "arrears") and ev.facts.in_arrears


def test_guarantee_capacity_already_spent_is_not_counted_twice(client, model):
    mid, _, gs = borrower(deposits=10000, free=12000)
    assert evaluate(mid, LoanRequest(30000, "School fees", 12)).outcome == "approve"
    # One guarantor now holds most of theirs against someone else's active loan.
    other, _, _ = new_member(login=False)
    with SessionLocal() as db:
        loan = ledger.issue_loan(db, other, 11000, 12, 1000)
        g = db.get(Member, gs[0])
        db.add(Guarantor(loan_account_id=loan.id, member_id=g.id, full_name=g.full_name, member_no=g.member_no,
                         phone=g.phone, relationship_="x", amount_guaranteed_kes=11000, status="verified"))
        db.commit()
    ev = evaluate(mid, LoanRequest(30000, "School fees", 12))
    assert ev.outcome == "clarify" and ev.questions == ["C5"]


def test_c5_looks_the_guarantor_up_by_name_and_number(client, model):
    mid, _, _ = borrower(guarantors=1)
    gid, no, _ = new_member(login=False)
    post_entry(gid, 30000)
    with SessionLocal() as db:
        name = db.get(Member, gid).full_name
    assert evaluate(mid).questions == ["C5"]
    for wrong in ({"full_name": "Someone Else", "member_no": no}, {"full_name": name, "member_no": "NOPE"}, None):
        ev = evaluate(mid, overrides={"extra_guarantor": wrong})
        assert ev.outcome == "refer" and ev.settled.reason_code == "guarantors_short"
        assert ev.extra_guarantor_found is False
    # Someone who has only been named has agreed to nothing: never automatic.
    ev = evaluate(mid, overrides={"extra_guarantor": {"full_name": f"  {name.upper()} ", "member_no": no.lower()}})
    assert ev.extra_guarantor_found is True and ev.worked.capacity_passes
    assert (ev.outcome, ev.settled.reason_code) == ("refer", "named_guarantor")


def test_a_member_cannot_name_themselves(client, model):
    mid, _, _ = borrower(guarantors=1)
    with SessionLocal() as db:
        me = db.get(Member, mid)
        named = {"full_name": me.full_name, "member_no": me.member_no}
    assert evaluate(mid, overrides={"extra_guarantor": named}).extra_guarantor_found is False


def test_medium_needs_an_answered_clarification(client, model):
    model["risk"] = "Medium"
    mid, _, _ = borrower()
    ev = evaluate(mid)
    assert (ev.outcome, ev.settled.reason_code) == ("refer", "officer_review")
    ev = evaluate(mid, LoanRequest(40000, "School fees"))
    assert ev.outcome == "clarify" and ev.questions == ["C1"]
    assert evaluate(mid, LoanRequest(40000, "School fees"), {"term_months": 12}).outcome == "approve"
    assert evaluate(mid, LoanRequest(40000, "School fees"), {"term_months": None}).outcome == "refer"


def test_the_model_rescoring_on_an_answer_moves_the_outcome(client, model):
    model["risk"] = lambda f: "High" if f["monthly_income_kes"] < 20000 else "Low"
    mid, _, _ = borrower(monthly_income_kes=10000)
    age_income(mid, 300)
    ev = evaluate(mid)
    assert ev.risk_class == "High" and ev.outcome == "clarify" and ev.questions == ["C2"]
    ev = evaluate(mid, overrides={"monthly_income_kes": 45000})
    assert ev.risk_class == "Low" and ev.outcome == "approve"
    ev = evaluate(mid, overrides={"monthly_income_kes": 12000})
    assert (ev.outcome, ev.risk_class) == ("refer", "High")


def test_no_ledger_is_no_record_whatever_the_member_declares(client, model):
    mid, member, _ = borrower(deposits=None)
    with SessionLocal() as db:
        db.get(Member, mid).savings_kes = 900000
        db.commit()
    ev = evaluate(mid)
    assert ev.settled.reason_code == "self_declared" and ev.facts.deposits_kes is None
    checks = {c["check"]: c for c in ev.trace["checks"]}
    assert checks["deposits_on_record"]["passed"] is False
    assert checks["deposits_on_record"]["values"]["declared_savings_kes"] == 900000
    assert [c for c, row in checks.items() if row["passed"] is False] == ["deposits_on_record"]
    r = member.post("/api/self-service/commit", headers=key(), json=committed_body("refer"))
    assert r.status_code == 201 and r.json()["status"] == "decided"
    with SessionLocal() as db:
        app = db.get(LoanApplication, r.json()["application_id"])
        assert app.savings_self_declared and app.sacco_savings_kes == 900000


def test_a_verified_figure_without_a_ledger_still_goes_to_an_officer(client, model):
    mid, _, _ = borrower(deposits=None)
    with SessionLocal() as db:
        m = db.get(Member, mid)
        m.savings_kes, m.savings_verified_by, m.savings_verified_at = 50000, "officer1", utcnow()
        db.commit()
    assert evaluate(mid).settled.reason_code == "self_declared"


def test_a_missing_classifier_decides_nothing(client, monkeypatch, tmp_path):
    mid, member, _ = borrower()
    self_service.evaluations.clear()
    monkeypatch.setattr(config, "CLASSIFIER_PATH", tmp_path / "gone.joblib")
    assert member.post("/api/self-service/evaluate", json=BODY).status_code == 503
    r = member.post("/api/self-service/commit", headers=key(), json=committed_body("approve", 40000))
    assert r.status_code == 503
    self_service.evaluations.clear()
    self_service.commits.clear()


# --- Committing -----------------------------------------------------------------------

def test_an_automatic_approval_writes_everything_and_pays_out(client, model):
    mid, member, gs = borrower(deposits=30000)
    r = member.post("/api/self-service/commit", headers=key(), json=committed_body("approve", 40000))
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["outcome"] == "approve" and out["status"] == "approved" and out["monthly_instalment_kes"] == 3554
    assert not out["can_book_interview"] and not out["can_accept"]
    with SessionLocal() as db:
        app = db.get(LoanApplication, out["application_id"])
        assert app.channel == "self_service" and not app.savings_self_declared and app.sacco_savings_kes == 30000
        iv = app.interview
        assert iv.mode == "self_service" and iv.status == "assessed" and iv.responses == []
        a, d = iv.assessment, iv.decision
        assert a.risk_class == "Low" and a.assessed_by == "system" and a.contributions == CONTRIBUTIONS
        assert a.feature_vector == {"age": 40.0, "log_monthly_income": 10.0, "children": None}
        assert a.provenance["monthly_income_kes"] == "verified" and a.overrides == {}
        assert a.policy_trace["outcome"] == "approve" and len(a.policy_trace["checks"]) == 9
        assert d.decided_by == "system" and d.policy_version == config.POLICY_BASE_VERSION
        assert d.outcome == "approve" and d.approved_amount_kes == 40000 and d.guarantors_required == 2
        assert d.member_message.startswith("You can have KSh 40,000 now")
        loan = db.get(LoanAccount, out["loan_id"])
        assert (loan.status, loan.principal_kes, loan.monthly_instalment_kes, loan.term_months) == ("active", 40000, 3554, 12)
        assert ledger.balances(db, mid)["transactional"] == 40000
        rows = app.guarantors
        assert {g.member_id for g in rows} == set(gs)
        assert all(g.status == "verified" and g.accepted_under_pledge and g.pledge_id and g.loan_account_id == loan.id
                   and g.verified_by == self_service.system_user(db).id for g in rows)
        assert sum(g.amount_guaranteed_kes for g in rows) == 10000      # 40,000 less her own 30,000
        caps = ledger.capacities(db, gs)
        assert sorted(c.guaranteed_kes for c in caps.values()) == [5000, 5000]
        assert all(c.committed_kes == 0 for c in caps.values())
        run = db.scalar(select(SelfServiceRun).where(SelfServiceRun.application_id == app.id))
        assert run.interview_id == iv.id and run.trigger == "commit"
        actions = set(db.scalars(select(AuditLog.action).where(AuditLog.actor_user_id == self_service.system_user(db).id,
                                                               AuditLog.details["application_id"].as_integer() == app.id)))
        assert {"decision.create", "guarantor.accept_pledge", "loan.pay_out"} <= actions


def test_the_member_sees_the_outcome_in_their_own_view_and_no_more(client, model):
    mid, member, _ = borrower()
    out = member.post("/api/self-service/commit", headers=key(), json=committed_body("approve", 40000)).json()
    r = member.get(f"/api/me/applications/{out['application_id']}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["outcome"] == "approve" and body["mode"] == "self_service" and body["status_label"] == "Approved"
    assert body["member_message"].startswith("You can have KSh 40,000 now")
    assert leaks(body) == []
    # What the officer sees of the same application keeps working.
    detail = client.get(f"/api/applications/{out['application_id']}")
    assert detail.status_code == 200 and detail.json()["decision"]["policy_version"] == config.POLICY_BASE_VERSION
    assert detail.json()["decision"]["decided_by"] == "system"


def test_a_double_submit_pays_out_once(client, model):
    mid, member, gs = borrower()
    k = key()
    first = member.post("/api/self-service/commit", headers=k, json=committed_body("approve", 40000))
    second = member.post("/api/self-service/commit", headers=k, json=committed_body("approve", 40000))
    assert first.status_code == second.status_code == 201 and first.json() == second.json()
    with SessionLocal() as db:
        assert ledger.balances(db, mid)["transactional"] == 40000
        assert db.scalar(select(func.count(LoanAccount.id)).where(LoanAccount.member_id == mid)) == 1
        assert db.scalar(select(func.count(LoanApplication.id)).where(LoanApplication.member_id == mid)) == 1


def test_two_submits_at_once_on_sqlite_pay_out_once(client, model):
    mid, _, gs = borrower()
    k, replies, gate = secrets.token_hex(8), [], threading.Barrier(2)

    def go():
        gate.wait()
        try:
            replies.append(commit_it(mid, key=k))
        except Exception as e:
            replies.append(e)
    threads = [threading.Thread(target=go) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(replies) == 2 and replies[0] == replies[1], replies
    with SessionLocal() as db:
        assert ledger.balances(db, mid)["transactional"] == 40000


def test_a_key_used_for_something_else_is_refused(client, model):
    mid, member, _ = borrower()
    k = key()
    assert member.post("/api/self-service/commit", headers=k, json=committed_body("approve", 40000)).status_code == 201
    r = member.post("/api/self-service/commit", headers=k,
                    json=committed_body("approve", 30000, amount_kes=30000))
    assert r.status_code == 409 and "different request" in r.json()["detail"]


def test_a_change_since_the_member_was_told_writes_nothing(client, model):
    mid, member, gs = borrower(deposits=10000)
    body = committed_body("approve", 30000, amount_kes=30000)
    assert member.post("/api/self-service/evaluate", json={**BODY, "amount_kes": 30000}).json()["outcome"] == "approve"
    with SessionLocal() as db:
        pledge = db.scalar(select(GuarantorPledge).where(GuarantorPledge.guarantor_member_id == gs[0]))
        ledger.withdraw_pledge(pledge)
        db.commit()
    k = key()
    r = member.post("/api/self-service/commit", headers=k, json=body)
    assert r.status_code == 409 and "changed" in r.json()["detail"]
    with SessionLocal() as db:
        assert db.scalar(select(func.count(LoanApplication.id)).where(LoanApplication.member_id == mid)) == 0
        assert db.scalar(select(IdempotencyKey.id).where(IdempotencyKey.key == k["Idempotency-Key"])) is None


def test_questions_outstanding_cannot_be_committed(client, model):
    _, member, _ = borrower()
    r = member.post("/api/self-service/commit", headers=key(),
                    json=committed_body("clarify", term_months=None))
    assert r.status_code == 409 and "questions" in r.json()["detail"]


def test_commit_needs_a_key(client, model):
    _, member, _ = borrower()
    assert member.post("/api/self-service/commit", json=committed_body("approve", 40000)).status_code == 422


def test_one_open_self_service_application_at_a_time(client, model):
    model["risk"] = "High"
    mid, member, _ = borrower()
    assert member.post("/api/self-service/commit", headers=key(), json=committed_body("refer")).status_code == 201
    r = member.post("/api/self-service/commit", headers=key(), json=committed_body("refer"))
    assert r.status_code == 409 and "already have" in r.json()["detail"]


def test_a_second_loan_after_a_payout_sees_the_first(client, model):
    mid, member, _ = borrower()
    assert member.post("/api/self-service/commit", headers=key(), json=committed_body("approve", 40000)).status_code == 201
    ev = evaluate(mid, LoanRequest(10000, "School fees", 12))
    assert ev.worked.obligations_kes == 3554 and ev.facts.loan_instalments_kes == 3554


def test_a_referral_offers_the_booking_flow_and_the_officers_interview_takes_over(client, model):
    model["risk"] = "High"
    mid, member, _ = borrower(sex="female", education=4)
    out = member.post("/api/self-service/commit", headers=key(), json=committed_body("refer")).json()
    assert out["can_book_interview"] and out["status"] == "decided" and out["loan_id"] is None
    day = next(d for d in (nairobi_today() + timedelta(days=i) for i in range(1, 30))
               if d.weekday() < 5 and d not in config.PUBLIC_HOLIDAYS)
    r = member.post(f"/api/me/applications/{out['application_id']}/booking",
                    json={"date": day.isoformat(), "time": "09:00", "language": "en"})
    assert r.status_code == 201, r.text
    booking = r.json()["booking"]["id"]
    assert r.json()["status"] == "interview_pending"

    # Cancelled: back to the referral, and it can be booked again.
    assert client.post(f"/api/bookings/{booking}/cancel").status_code == 200
    assert client.get(f"/api/applications/{out['application_id']}").json()["status"] == "decided"
    r = member.post(f"/api/me/applications/{out['application_id']}/booking",
                    json={"date": day.isoformat(), "time": "09:30", "language": "en"})
    assert r.status_code == 201, r.text
    booking = r.json()["booking"]["id"]
    assert client.post(f"/api/bookings/{booking}/confirm").status_code == 200
    r = client.post(f"/api/bookings/{booking}/start")
    assert r.status_code == 200, r.text
    live = r.json()["interview_id"]
    detail = client.get(f"/api/applications/{out['application_id']}").json()
    assert detail["interview"]["id"] == live and detail["interview"]["mode"] == "live" and detail["status"] == "interview_pending"
    # The system's record stays where the officers' page finds it.
    runs = client.get("/api/automatic-decisions?limit=500").json()
    assert [x["outcome"] for x in runs if x["application_id"] == out["application_id"]] == ["refer"]


def test_a_not_now_is_recorded_and_says_so(client, model):
    mid, member, _ = borrower(joined=(nairobi_today() - timedelta(days=70)).isoformat())
    r = member.post("/api/self-service/evaluate", json=BODY).json()
    assert r["outcome"] == "not_now" and "more month" in r["reason"] and r["questions"] == []
    out = member.post("/api/self-service/commit", headers=key(), json=committed_body("not_now")).json()
    assert out["status"] == "declined" and out["outcome"] == "not_now" and "more month" in out["message"]
    with SessionLocal() as db:
        d = db.scalar(select(Decision).join(LoanApplication, LoanApplication.interview_id == Decision.interview_id)
                      .where(LoanApplication.id == out["application_id"]))
        assert (d.decision, d.outcome) == ("decline", "not_now")
    body = member.get(f"/api/me/applications/{out['application_id']}").json()
    assert body["outcome"] == "not_now" and body["status_label"] == "Not approved"


def test_no_term_is_recorded_on_a_referral_and_the_trace_says_none_was_given(client, model):
    mid, member, _ = borrower(deposits=None)
    body = {"amount_kes": 40000, "purpose": "School fees", "overrides": {"term_months": None},
            "expected_outcome": "refer", "expected_amount_kes": None}
    out = member.post("/api/self-service/commit", headers=key(), json=body).json()
    assert out["term_months"] == self_service.TERM_FOR_THE_RECORD
    with SessionLocal() as db:
        a = db.get(LoanApplication, out["application_id"]).interview.assessment
        assert a.policy_trace["effective"]["term_months"] is None and a.overrides == {"term_months": None}


# --- A reduced offer ----------------------------------------------------------------------

OVER_RULE = {"amount_kes": 45000, "purpose": "School fees", "term_months": 12}


def offered(deposits=10000):
    mid, member, gs = borrower(deposits=deposits)
    r = member.post("/api/self-service/commit", headers=key(),
                    json={**OVER_RULE, "expected_outcome": "approve_reduced", "expected_amount_kes": deposits * 3})
    assert r.status_code == 201, r.text
    return mid, member, gs, r.json()


def test_an_offer_waits_for_the_member_and_holds_nothing(client, model):
    mid, member, gs, out = offered()
    assert out["status"] == "offered" and out["can_accept"] and out["amount_kes"] == 30000 and out["loan_id"] is None
    assert out["monthly_instalment_kes"] == 2666
    with SessionLocal() as db:
        assert db.scalar(select(func.count(LoanAccount.id)).where(LoanAccount.member_id == mid)) == 0
        assert all(c.committed_kes == 0 for c in ledger.capacities(db, gs).values())
        assert db.get(LoanApplication, out["application_id"]).guarantors == []
    assert member.get(f"/api/me/applications/{out['application_id']}").json()["status_label"].startswith("A smaller")


def test_accepting_pays_out_the_offer_and_records_a_second_decision(client, model):
    mid, member, gs, out = offered()
    k = key()
    r = member.post(f"/api/self-service/applications/{out['application_id']}/accept", headers=k)
    assert r.status_code == 201, r.text
    done = r.json()
    assert done["outcome"] == "approve" and done["status"] == "approved" and done["amount_kes"] == 30000
    again = member.post(f"/api/self-service/applications/{out['application_id']}/accept", headers=k)
    assert again.json() == done
    with SessionLocal() as db:
        assert ledger.balances(db, mid)["transactional"] == 30000
        loan = db.get(LoanAccount, done["loan_id"])
        assert loan.principal_kes == 30000 and loan.monthly_instalment_kes == 2666
        runs = db.scalars(select(SelfServiceRun).where(SelfServiceRun.application_id == out["application_id"])
                          .order_by(SelfServiceRun.id)).all()
        assert [r.trigger for r in runs] == ["commit", "acceptance"]
        assert [r.interview.decision.outcome for r in runs] == ["approve_reduced", "approve"]
        assert runs[1].interview.assessment.overrides == {"accepted_amount_kes": 30000}


def test_accepting_after_capacity_went_elsewhere_goes_to_an_officer(client, model):
    mid, member, gs, out = offered()
    with SessionLocal() as db:
        for gid in gs:
            db.execute(select(GuarantorPledge).where(GuarantorPledge.guarantor_member_id == gid))
            ledger.withdraw_pledge(db.scalar(select(GuarantorPledge).where(GuarantorPledge.guarantor_member_id == gid)))
        db.commit()
    r = member.post(f"/api/self-service/applications/{out['application_id']}/accept", headers=key())
    assert r.status_code == 201, r.text
    assert (r.json()["outcome"], r.json()["status"]) == ("not_now", "declined")
    with SessionLocal() as db:
        assert db.scalar(select(func.count(LoanAccount.id)).where(LoanAccount.member_id == mid)) == 0


def test_an_offer_can_be_turned_down_once(client, model):
    mid, member, _, out = offered()
    url = f"/api/self-service/applications/{out['application_id']}"
    r = member.post(f"{url}/decline", headers=key())
    assert r.status_code == 200 and r.json()["status"] == "declined"
    assert member.post(f"{url}/accept", headers=key()).status_code == 409
    assert member.post(f"{url}/decline", headers=key()).status_code == 409


def test_nobody_else_can_touch_an_offer(client, model):
    _, _, _, out = offered()
    _, other, _ = borrower()
    for action in ("accept", "decline"):
        assert other.post(f"/api/self-service/applications/{out['application_id']}/{action}", headers=key()).status_code == 404


def test_c6_lets_the_member_choose_a_smaller_amount_up_front(client, model):
    mid, member, _ = borrower(deposits=5000, monthly_income_kes=6000)
    body = {"amount_kes": 40000, "purpose": "School fees", "term_months": 6}
    r = member.post("/api/self-service/evaluate", json=body).json()
    assert [q["id"] for q in r["questions"]] == ["C6"] and r["outcome"] == "clarify"
    assert r["maximum_by_savings_kes"] == 15000 and r["maximum_affordable_kes"] == 11590
    assert r["questions"][0]["sets"] == ["accepted_amount_kes"]
    r = member.post("/api/self-service/evaluate", json={**body, "overrides": {"accepted_amount_kes": 11000}}).json()
    assert r["outcome"] == "approve" and r["amount_on_offer_kes"] == 11000


# --- Reversal -------------------------------------------------------------------------------

def paid(member=None):
    mid, member, gs = borrower()
    out = member.post("/api/self-service/commit", headers=key(), json=committed_body("approve", 40000)).json()
    return mid, member, gs, out


def test_a_reversal_compensates_and_deletes_nothing(client, model):
    mid, member, gs, out = paid()
    with SessionLocal() as db:
        ids_before = set(db.scalars(select(AccountEntry.id)))
    r = client.post(f"/api/loans/{out['loan_id']}/reverse", headers=key(), json={"reason": "Wrong account"})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "reversed"
    with SessionLocal() as db:
        assert ids_before <= set(db.scalars(select(AccountEntry.id)))
        loan = db.get(LoanAccount, out["loan_id"])
        assert loan.status == "reversed" and ledger.balances(db, mid)["transactional"] == 0
        new = db.scalars(select(AccountEntry).where(AccountEntry.id.not_in(ids_before))).all()
        assert [(e.entry_type, e.amount_kes, e.loan_account_id) for e in new] == [("loan_reversal", -40000, loan.id)]
        assert db.get(LoanApplication, out["application_id"]).status == "reversed"
        assert all(c.guaranteed_kes == 0 for c in ledger.capacities(db, gs).values())
        assert ledger.sacco_loan_use(["reversed"]) == 0
        row = db.scalar(select(AuditLog).where(AuditLog.action == "loan.reverse", AuditLog.entity_id == loan.id))
        assert row.details["reason"] == "Wrong account" and len(row.details["entry_ids"]) == 1
    with pytest.raises(IntegrityError):
        with SessionLocal() as db:
            db.execute(text("DELETE FROM account_entries WHERE id = :i"), {"i": min(ids_before)})
    page = client.get(f"/api/members/{mid}/sacco").json()
    assert page["loans"][0]["status"] == "reversed" and page["loans"][0]["days_in_arrears"] == 0


def test_reversing_twice_and_replaying_a_key(client, model):
    _, _, _, out = paid()
    k = key()
    url = f"/api/loans/{out['loan_id']}/reverse"
    first = client.post(url, headers=k, json={"reason": "Wrong account"})
    assert client.post(url, headers=k, json={"reason": "Wrong account"}).json() == first.json()
    r = client.post(url, headers=key(), json={"reason": "Wrong account"})
    assert r.status_code == 409 and "only an active loan" in r.json()["detail"]


def test_repayments_are_given_back_by_a_reversal(client, model):
    mid, _, _, out = paid()
    assert client.post(f"/api/members/{mid}/deposits", headers=key(),
                       json={"account": "transactional", "amount_kes": 1000}).status_code == 201
    assert client.post(f"/api/loans/{out['loan_id']}/repayments", headers=key(), json={"amount_kes": 3554}).status_code == 201
    r = client.post(f"/api/loans/{out['loan_id']}/reverse", headers=key(), json={"reason": "Wrong account"})
    assert r.status_code == 200, r.text
    with SessionLocal() as db:
        assert ledger.balances(db, mid)["transactional"] == 1000      # just what they paid in of their own


def test_money_already_drawn_cannot_be_reversed(client, model):
    mid, _, _, out = paid()
    assert client.post(f"/api/members/{mid}/withdrawals", headers=key(),
                       json={"account": "transactional", "amount_kes": 40000}).status_code == 201
    r = client.post(f"/api/loans/{out['loan_id']}/reverse", headers=key(), json={"reason": "Wrong account"})
    assert r.status_code == 409 and "no longer in the transactional account" in r.json()["detail"]
    with SessionLocal() as db:
        assert db.get(LoanAccount, out["loan_id"]).status == "active"
        assert db.scalar(select(AccountEntry.id).where(AccountEntry.entry_type == "loan_reversal",
                                                       AccountEntry.loan_account_id == out["loan_id"])) is None


def test_an_automatic_payout_can_be_reversed_only_in_time(client, model):
    _, _, _, out = paid()
    with SessionLocal() as db:
        loan = db.get(LoanAccount, out["loan_id"])
        loan.created_at = utcnow() - timedelta(hours=config.REVERSAL_HOURS, minutes=1)
        db.commit()
    r = client.post(f"/api/loans/{out['loan_id']}/reverse", headers=key(), json={"reason": "Wrong account"})
    assert r.status_code == 409 and "24 hours" in r.json()["detail"]
    row = client.get("/api/automatic-decisions?limit=500").json()
    assert next(x for x in row if x["loan_id"] == out["loan_id"])["reversible_until"] is None


def test_an_officers_payout_has_no_such_window_but_the_same_rules(client):
    mid, _, member = new_member()
    iid = assessed(client)
    app = new_application(client, mid, iid, amount=20000)
    assert client.post(f"/api/applications/{app['id']}/decision", json={"outcome": "approve"}).status_code == 201
    loan = client.post(f"/api/applications/{app['id']}/payout", headers=key()).json()
    with SessionLocal() as db:
        db.get(LoanAccount, loan["id"]).created_at = utcnow() - timedelta(days=40)
        db.commit()
    assert client.post(f"/api/loans/{loan['id']}/reverse", headers=key(), json={"reason": "Wrong account"}).status_code == 200
    assert client.get(f"/api/applications/{app['id']}").json()["status"] == "reversed"
    # Its application is finished with: it cannot be paid out a second time.
    assert client.post(f"/api/applications/{app['id']}/payout", headers=key()).status_code == 409


def test_a_recovery_stops_a_reversal(client):
    mid, _, _ = new_member(login=False)
    gid, _, _ = new_member(login=False)
    post_entry(gid, 5000)
    with SessionLocal() as db:
        loan = ledger.issue_loan(db, mid, 1000, 5, 210)
        ledger.recover_guarantee(db, gid, loan, 100, "REC-1")
        db.commit()
        loan_id = loan.id
    r = client.post(f"/api/loans/{loan_id}/reverse", headers=key(), json={"reason": "Wrong account"})
    assert r.status_code == 409 and "recoveries" in r.json()["detail"]


# --- Ledger endpoints ----------------------------------------------------------------------

def test_deposits_and_withdrawals_post_with_balances_and_audit(client):
    mid, _, _ = new_member(login=False)
    r = client.post(f"/api/members/{mid}/deposits", headers=key(), json={"amount_kes": 5000})
    assert r.status_code == 201 and r.json()["balance_kes"] == 5000 and r.json()["account"] == "deposits"
    r = client.post(f"/api/members/{mid}/deposits", headers=key(), json={"account": "share_capital", "amount_kes": 800})
    assert r.json()["balance_kes"] == 800
    r = client.post(f"/api/members/{mid}/withdrawals", headers=key(), json={"account": "share_capital", "amount_kes": 300})
    assert r.status_code == 201 and r.json()["balance_kes"] == 500 and r.json()["entry"]["amount_kes"] == -300
    with SessionLocal() as db:
        row = db.scalar(select(AuditLog).where(AuditLog.action == "ledger.withdrawal", AuditLog.entity_id == mid))
        assert row.details["account"] == "share_capital" and "amount_kes" not in row.details


def test_withdrawing_from_deposits_is_refused_at_every_level(client):
    mid, _, _ = new_member(login=False)
    post_entry(mid, 5000)
    assert client.post(f"/api/members/{mid}/withdrawals", headers=key(),
                       json={"account": "deposits", "amount_kes": 100}).status_code == 422
    with SessionLocal() as db, pytest.raises(IntegrityError):
        ledger.post_entry(db, mid, "deposits", "withdrawal", -100, "X-1")


@pytest.mark.parametrize("over, status", [(dict(amount_kes=0), 422), (dict(amount_kes=-5), 422), (dict(amount_kes=10 ** 9), 422),
                                          (dict(account="savings"), 422), (dict(extra=1), 422)])
def test_bad_ledger_bodies_are_refused(client, over, status):
    mid, _, _ = new_member(login=False)
    body = {"amount_kes": 100, "account": "deposits", **over}
    assert client.post(f"/api/members/{mid}/deposits", headers=key(), json=body).status_code == status


def test_an_overdraft_is_a_409_and_leaves_no_key(client):
    mid, _, _ = new_member(login=False)
    post_entry(mid, 100, "transactional")
    k = key()
    r = client.post(f"/api/members/{mid}/withdrawals", headers=k, json={"account": "transactional", "amount_kes": 500})
    assert r.status_code == 409 and "overdraw" in r.json()["detail"]
    with SessionLocal() as db:
        assert db.scalar(select(IdempotencyKey.id).where(IdempotencyKey.key == k["Idempotency-Key"])) is None
    post_entry(mid, 400, "transactional")
    assert client.post(f"/api/members/{mid}/withdrawals", headers=k,
                       json={"account": "transactional", "amount_kes": 500}).status_code == 201


def test_a_repeated_key_posts_once_and_a_repeated_reference_is_refused(client):
    mid, _, _ = new_member(login=False)
    k = key()
    a = client.post(f"/api/members/{mid}/deposits", headers=k, json={"amount_kes": 500, "reference": "RCPT-77"})
    b = client.post(f"/api/members/{mid}/deposits", headers=k, json={"amount_kes": 500, "reference": "RCPT-77"})
    assert a.status_code == b.status_code == 201 and a.json() == b.json()
    with SessionLocal() as db:
        assert ledger.balances(db, mid)["deposits"] == 500
    r = client.post(f"/api/members/{mid}/deposits", headers=key(), json={"amount_kes": 500, "reference": "RCPT-77"})
    assert r.status_code == 409 and "RCPT-77" in r.json()["detail"]
    with SessionLocal() as db:
        assert ledger.balances(db, mid)["deposits"] == 500


def test_keys_belong_to_their_user(client, admin_client):
    mid, _, _ = new_member(login=False)
    k = key()
    assert client.post(f"/api/members/{mid}/deposits", headers=k, json={"amount_kes": 500}).status_code == 201
    assert admin_client.post(f"/api/members/{mid}/deposits", headers=k, json={"amount_kes": 500}).status_code == 201
    with SessionLocal() as db:
        assert ledger.balances(db, mid)["deposits"] == 1000


def test_pledges_add_and_withdraw(client):
    mid, _, _ = new_member(login=False)
    gid, gno, _ = new_member(login=False)
    k = key()
    r = client.post(f"/api/members/{mid}/pledges", headers=k, json={"guarantor_member_no": gno.lower()})
    assert r.status_code == 201 and r.json()["status"] == "active" and r.json()["guarantor_member_id"] == gid
    pledge = r.json()["id"]
    assert client.post(f"/api/members/{mid}/pledges", headers=k, json={"guarantor_member_no": gno.lower()}).json()["id"] == pledge
    r = client.post(f"/api/members/{mid}/pledges", headers=key(), json={"guarantor_member_no": gno})
    assert r.status_code == 409 and "already" in r.json()["detail"]
    assert client.post(f"/api/members/{mid}/pledges", headers=key(), json={"guarantor_member_no": "NOPE"}).status_code == 422
    r = client.post(f"/api/pledges/{pledge}/withdraw", headers=key())
    assert r.status_code == 200 and r.json()["status"] == "withdrawn"
    assert client.post(f"/api/pledges/{pledge}/withdraw", headers=key()).status_code == 409
    assert client.post(f"/api/members/{mid}/pledges", headers=key(), json={"guarantor_member_no": gno}).status_code == 201
    with SessionLocal() as db:
        actions = list(db.scalars(select(AuditLog.action).where(AuditLog.entity == "guarantor_pledge", AuditLog.entity_id == pledge)))
        assert actions == ["pledge.create", "pledge.withdraw"]
        me = db.get(Member, mid).member_no
    assert client.post(f"/api/members/{mid}/pledges", headers=key(), json={"guarantor_member_no": me}).status_code == 422


def approved_with_guarantors(client, member_id, g_ids, amount=20000, share=10000):
    iid = assessed(client)
    app = new_application(client, member_id, iid, amount=amount)
    r = client.post(f"/api/applications/{app['id']}/decision",
                    json={"outcome": "approve_with_guarantor", "guarantors_required": 2})
    assert r.status_code == 201, r.text
    with SessionLocal() as db:
        for gid in g_ids:
            g = db.get(Member, gid)
            db.add(Guarantor(application_id=app["id"], member_id=gid, full_name=g.full_name, member_no=g.member_no,
                             phone=g.phone, relationship_="x", amount_guaranteed_kes=share, status="verified",
                             verified_at=utcnow()))
        a = db.get(LoanApplication, app["id"])
        a.status = "approved"
        db.commit()
    return app["id"]


def test_paying_out_moves_guarantors_to_the_loan_and_cannot_happen_twice(client):
    mid, _, _ = new_member(login=False)
    gs = [new_member(login=False)[0] for _ in range(2)]
    [post_entry(g, 15000) for g in gs]
    app = approved_with_guarantors(client, mid, gs)
    with SessionLocal() as db:
        assert all(c.committed_kes == 10000 and c.guaranteed_kes == 0 for c in ledger.capacities(db, gs).values())
    k = key()
    r = client.post(f"/api/applications/{app}/payout", headers=k)
    assert r.status_code == 201, r.text
    loan = r.json()
    assert loan["principal_kes"] == 20000 and loan["monthly_instalment_kes"] == 1777 and loan["term_months"] == 12
    assert client.post(f"/api/applications/{app}/payout", headers=k).json() == loan
    r = client.post(f"/api/applications/{app}/payout", headers=key())
    assert r.status_code == 409 and "already been paid out" in r.json()["detail"]
    with SessionLocal() as db:
        assert ledger.balances(db, mid)["transactional"] == 20000
        assert all(c.committed_kes == 0 and c.guaranteed_kes == 10000 for c in ledger.capacities(db, gs).values())


def test_a_payout_a_guarantor_can_no_longer_back_is_refused(client):
    mid, _, _ = new_member(login=False)
    gs = [new_member(login=False)[0] for _ in range(2)]
    post_entry(gs[0], 15000)
    post_entry(gs[1], 5000)                 # verified for 10,000 it does not have
    app = approved_with_guarantors(client, mid, gs)
    r = client.post(f"/api/applications/{app}/payout", headers=key())
    assert r.status_code == 409 and "no longer has the capacity" in r.json()["detail"]
    with SessionLocal() as db:
        assert db.scalar(select(LoanAccount.id).where(LoanAccount.application_id == app)) is None


def test_the_same_capacity_cannot_be_paid_out_twice(client):
    """Two applications, each verified against one balance: the second is stopped."""
    gs = [new_member(login=False)[0] for _ in range(2)]
    [post_entry(g, 10000) for g in gs]
    a, _, _ = new_member(login=False)
    b, _, _ = new_member(login=False)
    first = approved_with_guarantors(client, a, gs, amount=20000, share=8000)
    second = approved_with_guarantors(client, b, gs, amount=20000, share=8000)
    assert client.post(f"/api/applications/{first}/payout", headers=key()).status_code == 409   # 16,000 committed of 10,000
    with SessionLocal() as db:
        for g in db.scalars(select(Guarantor).where(Guarantor.application_id == second)):
            g.status = "rejected"
        db.commit()
    assert client.post(f"/api/applications/{first}/payout", headers=key()).status_code == 201


def test_a_pending_guarantor_stops_holding_capacity_at_payout(client):
    mid, _, _ = new_member(login=False)
    gs = [new_member(login=False)[0] for _ in range(3)]
    [post_entry(g, 15000) for g in gs]
    app = approved_with_guarantors(client, mid, gs[:2])
    with SessionLocal() as db:
        g = db.get(Member, gs[2])
        pledge = ledger.add_pledge(db, mid, g.id)
        db.add(Guarantor(application_id=app, member_id=g.id, full_name=g.full_name, member_no=g.member_no, phone=g.phone,
                         relationship_="x", amount_guaranteed_kes=10000, status="pending", pledge_id=pledge.id))
        db.commit()
        assert ledger.capacities(db, [g.id])[g.id].committed_kes == 10000
    assert client.post(f"/api/applications/{app}/payout", headers=key()).status_code == 201
    with SessionLocal() as db:
        assert ledger.capacities(db, [gs[2]])[gs[2]].committed_kes == 0


@pytest.mark.parametrize("state", ["not_approved", "practice", "short_of_guarantors"])
def test_what_cannot_be_paid_out(client, state):
    mid, _, _ = new_member(login=False)
    iid = assessed(client, mode="practice" if state == "practice" else "live")
    app = new_application(client, mid, iid, amount=20000)
    if state == "practice":
        client.post(f"/api/applications/{app['id']}/decision", json={"outcome": "approve"})
    if state == "short_of_guarantors":
        client.post(f"/api/applications/{app['id']}/decision",
                    json={"outcome": "approve_with_guarantor", "guarantors_required": 2})
        with SessionLocal() as db:
            db.get(LoanApplication, app["id"]).status = "approved"
            db.commit()
    assert client.post(f"/api/applications/{app['id']}/payout", headers=key()).status_code == 409


def test_a_repayment_is_within_what_is_owed_and_the_last_closes_the_loan(client):
    mid, _, _ = new_member(login=False)
    with SessionLocal() as db:
        loan = ledger.issue_loan(db, mid, 1000, 2, 510)
        db.commit()
        loan_id = loan.id
    url = f"/api/loans/{loan_id}/repayments"
    assert client.post(url, headers=key(), json={"amount_kes": 1021}).status_code == 422
    r = client.post(url, headers=key(), json={"amount_kes": 510})
    assert r.status_code == 201 and r.json()["paid_kes"] == 510 and r.json()["status"] == "active"
    r = client.post(url, headers=key(), json={"amount_kes": 510})
    assert r.status_code == 409 and "overdraw" in r.json()["detail"]    # only the paid-out 1,000 is there
    post_entry(mid, 100, "transactional")
    r = client.post(url, headers=key(), json={"amount_kes": 510})
    assert r.status_code == 201 and r.json()["status"] == "repaid"
    r = client.post(url, headers=key(), json={"amount_kes": 1})
    assert r.status_code == 409 and "nothing is owed" in r.json()["detail"]


def test_refunding_a_departing_member(client):
    mid, _, _ = new_member(login=False)
    post_entry(mid, 7000)
    other, other_no, _ = new_member(login=False)
    with SessionLocal() as db:
        no = db.get(Member, mid).member_no
    pledge_for = client.post(f"/api/members/{other}/pledges", headers=key(), json={"guarantor_member_no": no}).json()["id"]
    k = key()
    r = client.post(f"/api/members/{mid}/refund-deposits", headers=k)
    assert r.status_code == 201, r.text
    assert r.json()["entry"]["entry_type"] == "deposit_refund" and r.json()["entry"]["amount_kes"] == -7000
    assert r.json()["pledges_ended"] == 1
    assert client.post(f"/api/members/{mid}/refund-deposits", headers=k).json() == r.json()
    with SessionLocal() as db:
        assert ledger.balances(db, mid)["deposits"] == 0
        assert db.get(GuarantorPledge, pledge_for).status == "withdrawn"
    r = client.post(f"/api/members/{mid}/refund-deposits", headers=key())
    assert r.status_code == 409 and "no deposits" in r.json()["detail"]


@pytest.mark.parametrize("case, words", [("owes", "still owes"), ("defaulted", "still owes"), ("guarantees", "still guarantees"),
                                         ("committed", "still guarantees"), ("answerable", "still guarantees"),
                                         ("open", "still open")])
def test_a_refund_is_refused_while_anything_is_owed_or_guaranteed(client, case, words):
    mid, _, _ = new_member(login=False)
    post_entry(mid, 7000)
    other, _, _ = new_member(login=False)
    with SessionLocal() as db:
        m = db.get(Member, mid)
        row = dict(member_id=mid, full_name=m.full_name, member_no=m.member_no, phone=m.phone, relationship_="x",
                   amount_guaranteed_kes=2000, status="verified")
        if case in ("owes", "defaulted"):
            loan = ledger.issue_loan(db, mid, 1000, 5, 210)
            loan.status = "active" if case == "owes" else "defaulted"
        elif case in ("guarantees", "answerable"):
            loan = ledger.issue_loan(db, other, 1000, 5, 210)
            loan.status = "active" if case == "guarantees" else "defaulted"
            db.add(Guarantor(loan_account_id=loan.id, **row))
    if case == "committed":
        app_id = new_application(client, other)["id"]
        with SessionLocal() as db:
            m = db.get(Member, mid)
            db.get(LoanApplication, app_id).status = "guarantor_submitted"
            db.add(Guarantor(application_id=app_id, member_id=mid, full_name=m.full_name, member_no=m.member_no, phone=m.phone,
                             relationship_="x", amount_guaranteed_kes=2000, status="verified"))
            db.commit()
    elif case == "open":
        app_id = new_application(client, mid)["id"]
        with SessionLocal() as db:
            db.get(LoanApplication, app_id).status = "approved"
            db.commit()
    else:
        with SessionLocal() as db:
            m = db.get(Member, mid)
            target = other if case in ("guarantees", "answerable") else mid
            loan = ledger.issue_loan(db, target, 1000, 5, 210)
            loan.status = {"owes": "active", "defaulted": "defaulted", "guarantees": "active", "answerable": "defaulted"}[case]
            if target == other:
                db.add(Guarantor(loan_account_id=loan.id, member_id=mid, full_name=m.full_name, member_no=m.member_no,
                                 phone=m.phone, relationship_="x", amount_guaranteed_kes=2000, status="verified"))
            db.commit()
    r = client.post(f"/api/members/{mid}/refund-deposits", headers=key())
    assert r.status_code == 409 and words in r.json()["detail"], r.text
    with SessionLocal() as db:
        assert ledger.balances(db, mid)["deposits"] == 7000


def test_a_guarantor_recovered_in_full_can_leave(client):
    mid, _, _ = new_member(login=False)
    post_entry(mid, 7000)
    other, _, _ = new_member(login=False)
    with SessionLocal() as db:
        m = db.get(Member, mid)
        loan = ledger.issue_loan(db, other, 1000, 5, 210)
        loan.status = "defaulted"
        db.add(Guarantor(loan_account_id=loan.id, member_id=mid, full_name=m.full_name, member_no=m.member_no, phone=m.phone,
                         relationship_="x", amount_guaranteed_kes=2000, status="verified"))
        ledger.recover_guarantee(db, mid, loan, 2000, "REC-FULL")
        db.commit()
    r = client.post(f"/api/members/{mid}/refund-deposits", headers=key())
    assert r.status_code == 201 and r.json()["entry"]["amount_kes"] == -5000


LEDGER_ROUTES = [("POST", "/api/members/{id}/deposits", {"amount_kes": 1}), ("POST", "/api/members/{id}/withdrawals",
                 {"account": "transactional", "amount_kes": 1}), ("POST", "/api/members/{id}/refund-deposits", None),
                 ("POST", "/api/members/{id}/pledges", {"guarantor_member_no": "X"}), ("POST", "/api/pledges/{id}/withdraw", None),
                 ("POST", "/api/applications/{id}/payout", None), ("POST", "/api/loans/{id}/repayments", {"amount_kes": 1}),
                 ("POST", "/api/loans/{id}/reverse", {"reason": "because"})]


@pytest.mark.parametrize("method, path, body", LEDGER_ROUTES)
def test_ledger_endpoints_are_for_officers_and_admins(client, admin_client, anon_client, method, path, body):
    mid, _, member = new_member()
    url = path.replace("{id}", str(mid))
    assert member.request(method, url, json=body, headers=key()).status_code == 403
    assert anon_client.request(method, url, json=body, headers=key()).status_code == 401
    # Staff get past the role, and then to a real answer about the row.
    assert admin_client.request(method, url.replace(str(mid), "99999999"), json=body, headers=key()).status_code == 404
    assert client.request(method, url.replace(str(mid), "99999999"), json=body, headers=key()).status_code == 404


@pytest.mark.parametrize("method, path, body", LEDGER_ROUTES)
def test_ledger_endpoints_need_a_key(client, method, path, body):
    mid, _, _ = new_member(login=False)
    assert client.request(method, path.replace("{id}", str(mid)), json=body).status_code == 422


# --- The member's endpoints ---------------------------------------------------------------

def test_evaluate_gives_a_member_only_what_they_may_see(client, model):
    model["contributions"] = TOP_DRIVER
    mid, member, gs = borrower(deposits=10000, guarantors=1, free=12345)
    r = member.post("/api/self-service/evaluate", json={**BODY, "amount_kes": 30000})
    assert r.status_code == 200, r.text
    body = r.json()
    assert leaks(body) == [] and body["outcome"] == "clarify" and [q["id"] for q in body["questions"]] == ["C5"]
    assert body["questions"][0]["sets"] == ["extra_guarantor"] and body["reasons"] == []
    text_of = str(body)
    assert "12345" not in text_of and "risk" not in text_of.lower()
    final = member.post("/api/self-service/evaluate", json=BODY).json()
    assert final["outcome"] != "clarify" or final["questions"]
    assert leaks(final) == []


def test_referral_wording_never_gives_the_class_away(client, model):
    words = {}
    for risk in ("High", "Medium"):
        model["risk"] = risk
        _, member, _ = borrower()
        words[risk] = member.post("/api/self-service/evaluate", json=BODY).json()["reason"]
    assert words["High"] == words["Medium"]
    assert not {"risk", "high", "medium", "model", "score"} & set(words["High"].lower().replace(".", "").split())


def test_a_member_acts_only_on_their_own_record(client, model):
    a, member_a, _ = borrower()
    b, member_b, _ = borrower(deposits=5000)
    # The body has nowhere to put a member id.
    assert member_a.post("/api/self-service/evaluate", json={**BODY, "member_id": b}).status_code == 422
    out = member_b.post("/api/self-service/evaluate", json=BODY).json()
    assert out["maximum_by_savings_kes"] == 15000
    assert member_a.post("/api/self-service/evaluate", json=BODY).json()["maximum_by_savings_kes"] == 90000


def test_staff_and_strangers_cannot_use_a_members_endpoints(client, admin_client, anon_client, model):
    for path in ("/api/self-service/evaluate", "/api/self-service/commit"):
        assert client.post(path, json=BODY, headers=key()).status_code == 403
        assert admin_client.post(path, json=BODY, headers=key()).status_code == 403
        assert anon_client.post(path, json=BODY, headers=key()).status_code == 401


def test_only_what_a_question_sets_can_come_from_the_conversation(client, model):
    _, member, _ = borrower()
    for bad in ({"age": 30}, {"sacco_loan_use": 0}, {"lost_as_guarantor": {"sacco": 0}}):
        assert member.post("/api/self-service/evaluate", json={**BODY, "overrides": bad}).status_code == 422
    r = member.post("/api/self-service/evaluate", json={**BODY, "overrides": {"chama_instalment_kes": 500}})
    assert r.status_code == 422 and "chama_loan_use" in r.json()["detail"]


def test_evaluations_and_commits_are_rate_limited(client, model, monkeypatch):
    monkeypatch.setattr(self_service, "evaluations", self_service.LoginLimiter(2, 3600))
    monkeypatch.setattr(self_service, "commits", self_service.LoginLimiter(1, 3600))
    _, member, _ = borrower()
    assert member.post("/api/self-service/evaluate", json=BODY).status_code == 200
    assert member.post("/api/self-service/evaluate", json=BODY).status_code == 200
    r = member.post("/api/self-service/evaluate", json=BODY)
    assert r.status_code == 429 and int(r.headers["Retry-After"]) > 0
    # One member's limit is theirs alone.
    _, other, _ = borrower()
    assert other.post("/api/self-service/evaluate", json=BODY).status_code == 200
    k = key()
    assert member.post("/api/self-service/commit", headers=k, json=committed_body("approve", 40000)).status_code == 201
    assert member.post("/api/self-service/commit", headers=k, json=committed_body("approve", 40000)).status_code == 429


# --- The system user ----------------------------------------------------------------------

def test_nobody_can_sign_in_as_the_system_or_administer_it(client, admin_client, anon_client):
    with SessionLocal() as db:
        system = self_service.system_user(db)
        assert (system.role, system.is_active, system.password_hash) == ("system", False, "!")
        sid = system.id
    for password in ("!", "", "system"):
        r = anon_client.post("/api/auth/login", json={"username": "system", "password": password or "x"})
        assert r.status_code == 401
    assert "system" not in [u["username"] for u in admin_client.get("/api/admin/users").json()]
    assert admin_client.post(f"/api/admin/users/{sid}/activate").status_code == 404
    assert admin_client.put(f"/api/admin/users/{sid}/password", json={"password": "a long new password"}).status_code == 404
    assert admin_client.put(f"/api/admin/users/{sid}/role", json={"role": "admin"}).status_code == 404


def test_an_officer_cannot_choose_the_new_mode_or_outcome(client):
    r = client.post("/api/interviews", json={"applicant": {"age": 40, "sex": "male", "education": 2, "marital_status": "single"},
                                             "mode": "self_service"})
    assert r.status_code == 422
    iid = assessed(client)
    assert client.post(f"/api/interviews/{iid}/decision", json={"outcome": "not_now"}).status_code == 422


def test_automatic_decisions_stay_out_of_the_interviews_list_and_the_statistics(client, admin_client, model):
    mid, member, _, out = paid()
    with SessionLocal() as db:
        iv = db.get(LoanApplication, out["application_id"]).interview_id
    assert iv not in [x["id"] for x in client.get("/api/interviews").json()]
    from chamapro.api.main import live_stats
    with SessionLocal() as db:
        before = live_stats(db)
        assert before["interview_count"] == db.scalar(select(func.count(Interview.id)).where(Interview.mode == "live"))
        # Its record still reads as an interview for whoever follows the link.
    assert client.get(f"/api/interviews/{iv}").json()["mode"] == "self_service"


# --- The officers' page -------------------------------------------------------------------

def test_the_page_lists_outcome_amount_risk_and_version(client, model):
    mid, member, _, out = paid()
    rows = client.get("/api/automatic-decisions?limit=500").json()
    row = next(r for r in rows if r["application_id"] == out["application_id"])
    assert row["outcome"] == "approve" and row["amount_kes"] == 40000 and row["risk_class"] == "Low"
    assert row["policy_version"] == config.POLICY_BASE_VERSION and row["loan_status"] == "active"
    assert row["reversible_until"] is not None and row["member_id"] == mid
    assert all(r["outcome"] == "approve" for r in client.get("/api/automatic-decisions?outcome=approve&limit=500").json())
    assert client.get("/api/automatic-decisions?outcome=nonsense").status_code == 422


def test_opening_one_gives_the_trace_and_shap(client, model):
    _, _, _, out = paid()
    rows = client.get("/api/automatic-decisions?limit=500").json()
    row = next(r for r in rows if r["application_id"] == out["application_id"])
    d = client.get(f"/api/automatic-decisions/{row['id']}").json()
    assert d["contributions"] == CONTRIBUTIONS and d["probabilities"]["Low"] == 0.5
    assert len(d["trace"]["checks"]) == 9 and d["trace"]["maximums"]["rule_kes"] == 90000
    assert d["provenance"]["monthly_income_kes"] == "verified" and d["overrides"] == {}
    assert d["member_message"].startswith("You can have") and d["model_sha256"] == "0" * 64
    assert d["features"]["monthly_income_kes"] == 45000
    assert client.get("/api/automatic-decisions/99999999").status_code == 404


def test_the_page_is_for_staff(client, anon_client, model):
    _, member, _, _ = paid()
    assert member.get("/api/automatic-decisions").status_code == 403
    assert member.get("/api/automatic-decisions/1").status_code == 403
    assert anon_client.get("/api/automatic-decisions").status_code == 401


def test_a_reversed_decision_cannot_be_reversed_from_the_page(client, model):
    _, _, _, out = paid()
    client.post(f"/api/loans/{out['loan_id']}/reverse", headers=key(), json={"reason": "Wrong account"})
    row = next(r for r in client.get("/api/automatic-decisions?limit=500").json() if r["application_id"] == out["application_id"])
    assert row["application_status"] == "reversed" and row["loan_status"] == "reversed" and row["reversible_until"] is None


def test_an_offer_and_its_acceptance_are_two_rows_and_only_the_approval_shows_the_loan(client, model):
    _, member, _, out = offered()
    member.post(f"/api/self-service/applications/{out['application_id']}/accept", headers=key())
    rows = [r for r in client.get("/api/automatic-decisions?limit=500").json() if r["application_id"] == out["application_id"]]
    assert [(r["trigger"], r["outcome"], r["loan_id"] is not None) for r in rows] == [("acceptance", "approve", True),
                                                                                      ("commit", "approve_reduced", False)]


def test_the_page_does_not_query_per_row(client, model, queries):  # noqa: F811
    paid()
    _, before = queries(client, "/api/automatic-decisions?limit=500")
    for _ in range(3):
        paid()
        offered()
    r, after = queries(client, "/api/automatic-decisions?limit=500")
    assert after == before, f"{before} queries, then {after} with more rows"
    assert len(r.json()) >= 7
    run = r.json()[0]["id"]
    _, one = queries(client, f"/api/automatic-decisions/{run}")
    assert one <= before + 2


# --- Seeding --------------------------------------------------------------------------------

def pool(n=600, seed=7):
    return seed_members.synthetic_respondents(n, random.Random(seed))


def test_no_composed_member_copies_a_respondent():
    everyone = pool()
    members = seed_members.compose_members(everyone, 120, random.Random(1))
    real = {seed_members.row_key(r) for r in everyone}
    assert len(members) == 120 and not any(seed_members.row_key(m) in real for m in members)


def test_each_group_comes_from_a_different_respondent_of_one_stratum():
    everyone = pool()
    for i, r in enumerate(everyone):        # a marker in each group says who gave it
        r["form"] = {**r["form"], "age": 1000 + i}
        r["features"].update(children_under5=i, agri_income_kes=i, non_monetary_savings={"who": i},
                             purchases_last_12m={"who": i}, chama_loan_use=i)
    by_id = dict(enumerate(everyone))
    for m in seed_members.compose_members(everyone, 80, random.Random(2)):
        f = m["features"]
        donors = [m["form"]["age"] - 1000, f["children_under5"], f["agri_income_kes"], f["non_monetary_savings"]["who"],
                  f["purchases_last_12m"]["who"], f["chama_loan_use"]]
        assert len(set(donors)) == 6
        assert len({seed_members.stratum(by_id[d]) for d in donors}) == 1
        # And the stratum is the member's own: their income and household are from it.
        assert seed_members.stratum(m) == seed_members.stratum(by_id[donors[0]])


def test_composing_is_deterministic_and_keeps_the_proportions():
    everyone = pool(n=2000)
    a = seed_members.compose_members(everyone, 500, random.Random(3))
    assert a == seed_members.compose_members(everyone, 500, random.Random(3))
    assert a != seed_members.compose_members(everyone, 500, random.Random(4))
    share = lambda rows, band: sum(seed_members.stratum(r)[0] == band for r in rows) / len(rows)  # noqa: E731
    for band in ("5,000-14,999", "15,000-29,999"):
        assert abs(share(a, band) - share(everyone, band)) < 0.08


def test_a_stratum_too_small_to_compose_from_is_left_out():
    everyone = pool(n=400)
    few = [r for r in everyone if seed_members.stratum(r)[0] == "unknown"][:5]
    rest = [r for r in everyone if seed_members.stratum(r)[0] != "unknown"]
    members = seed_members.compose_members(rest + few, 60, random.Random(5))
    assert not any(seed_members.stratum(m)[0] == "unknown" for m in members)
    with pytest.raises(ValueError, match="no stratum"):
        seed_members.compose_members(few, 1, random.Random(5))


def test_the_real_survey_path_composes_too(monkeypatch):
    everyone = pool()
    monkeypatch.setattr(seed_members, "load_central_respondents", lambda: everyone)
    members, source = seed_members.choose_respondents(50, random.Random(6), log=lambda _: None)
    real = {seed_members.row_key(r) for r in everyone}
    assert source == "finaccess" and len(members) == 50 and not any(seed_members.row_key(m) in real for m in members)


@pytest.mark.skipif(not (config.EXPERIMENTS_DIR / "02_finaccess_prep/results/modelling_frame.csv").exists(),
                    reason="needs the licensed FinAccess frame")
def test_no_member_built_from_finaccess_copies_a_row():
    everyone = seed_members.load_central_respondents()
    real = {seed_members.row_key(r) for r in everyone}
    members, source = seed_members.choose_respondents(seed_members.MEMBERS, random.Random(seed_members.SEED), log=lambda _: None)
    assert source == "finaccess" and len(members) == seed_members.MEMBERS
    assert not any(seed_members.row_key(m) in real for m in members)


# --- The two demo members, on the real classifier -------------------------------------------

@pytest.fixture(scope="module")
def demo(tmp_path_factory):
    """A scratch database of the four self-service people, through the seed's own code."""
    path = tmp_path_factory.mktemp("demo") / "demo.db"
    eng = create_engine(f"sqlite:///{path}", connect_args={"timeout": 30})
    init_db(eng)
    with Session(eng, expire_on_commit=False) as db:
        actor = User(username="demo.officer", password_hash="!", role="officer", is_active=False)
        db.add(actor)
        db.flush()
        today, now = nairobi_today(), utcnow()
        people = {k: {**p, "joined_on": seed_demo.months_ago(p["joined"])} for k, p in seed_demo.SELF_SERVICE_PEOPLE.items()}
        plan = seed_members.generate([], "fixed", people, [], today, now, random.Random(seed_members.SEED))
        members = {}
        seed_members.write_plan(db, plan, members, {"officer1": actor, "officer2": actor}, None, actor, now, "demo",
                                seed_demo.ensure_member)
        yield db, members, actor
    eng.dispose()


DAIRY = LoanRequest(40000, "A dairy cow")
SCHOOL = LoanRequest(60000, "School fees", 12)
FEES_INCOME = {"monthly_income_kes": 30000}


@needs_classifier
def test_wanjiru_is_asked_the_term_and_then_approved(demo):
    db, members, _ = demo
    first = decisions.evaluate(db, members["wanjiru"], DAIRY)
    assert first.risk_class == "Low" and first.outcome == "clarify" and first.questions == ["C1"]
    assert first.worked.instalment_kes is None and first.worked.affordable_max_kes is None
    after = decisions.evaluate(db, members["wanjiru"], DAIRY, {"term_months": 12})
    assert after.outcome == "approve" and after.amount_kes == 40000 and after.questions == []
    assert after.risk_class == "Low" and after.instalment_kes == 3554
    assert all(c["passed"] for c in after.trace["checks"])
    assert after.worked.rule_max_kes == 90000 and after.worked.affordable_max_kes == 168826
    assert [g.pledge_id is not None for g in after.worked.chosen] == [True, True]
    assert len(after.worked.chosen) == 2 and after.worked.capacity_need_kes == 10000


@needs_classifier
def test_njeri_is_asked_her_income_and_is_rescored(demo):
    db, members, _ = demo
    before = decisions.evaluate(db, members["njeri"], SCHOOL)
    assert before.outcome == "clarify" and before.questions == ["C2"] and before.risk_class == "Medium"
    assert before.facts.income_kes == 10000 and before.provenance["monthly_income_kes"] == "declared"
    assert before.trace["clarifications"]["income_age_days"] == 240
    assert before.trace["clarifications"]["income_top_three_driver"] is True
    drivers = [c["feature"] for c in before.contributions]
    assert "log_monthly_income" in drivers[:3]

    after = decisions.evaluate(db, members["njeri"], SCHOOL, FEES_INCOME)
    assert after.risk_class == "Low" and after.provenance["monthly_income_kes"] == "conversation"
    assert (after.outcome, after.amount_kes, after.settled.reason_code) == ("approve_reduced", 45000, "reduced_rule")
    assert after.worked.rule_max_kes == 45000 and after.worked.affordable_max_kes == 112550
    # The answer moved the income's own attribution, in the model's own numbers.
    shap = lambda ev: next(c["shap"] for c in ev.contributions if c["feature"] == "log_monthly_income")  # noqa: E731
    assert shap(after) != shap(before)
    assert before.feature_vector["log_monthly_income"] != after.feature_vector["log_monthly_income"]
    assert db.get(Member, members["njeri"].id).profile.monthly_income_kes == 10000


@needs_classifier
def test_wanjiru_and_njeri_end_to_end(demo):
    db, members, actor = demo
    ev = decisions.evaluate(db, members["wanjiru"], DAIRY, {"term_months": 12})
    out = self_service.commit(db, ev, "wanjiru-commit", actor)
    assert out["outcome"] == "approve" and out["status"] == "approved" and out["loan_id"]
    assert self_service.commit(db, ev, "wanjiru-commit", actor) == out
    assert ledger.balances(db, members["wanjiru"].id)["transactional"] == 40000

    ev = decisions.evaluate(db, members["njeri"], SCHOOL, FEES_INCOME)
    offer = self_service.commit(db, ev, "njeri-commit", actor)
    assert offer["status"] == "offered" and offer["amount_kes"] == 45000
    app = db.get(LoanApplication, offer["application_id"])
    done = self_service.accept_offer(db, app, "njeri-accept", actor)
    assert done["outcome"] == "approve" and done["amount_kes"] == 45000 and done["monthly_instalment_kes"] == 3999
    assert ledger.balances(db, members["njeri"].id)["transactional"] == 45000
    assert app.interview.assessment.overrides == {"monthly_income_kes": 30000, "accepted_amount_kes": 45000}
    assert app.interview.assessment.risk_class == "Low"
    assert db.scalar(select(func.count(Assessment.id))) == 3
