"""Round trips: against Supabase each query costs ~200 ms, so the slow pages'
endpoints issue a fixed number of queries however many rows there are, and
the live statistics are cached for a minute (live_cache.py)."""
import logging
import re
import secrets

import pytest
from sqlalchemy import event, select

from conftest import QUERIES, assessed, guarantor, new_application, new_interview, new_member
from chamapro.api import decisions, ledger, live_cache, self_service
from chamapro.api.db import Applicant, Interview, Member, SessionLocal, make_engine
from test_conversation import begin, say
from test_decisions import age_income, borrower, model, post_entry  # noqa: F401  (model is a fixture)


@pytest.fixture
def summary(monkeypatch, tmp_path):
    from chamapro import config
    path = tmp_path / "summary.json"
    path.write_text('{"generated_at": "2026-10-19T00:00:00+00:00"}', encoding="utf-8")
    monkeypatch.setattr(config, "RESULTS_SUMMARY_PATH", path)


def more_rows(client, n):
    """n more live assessed interviews, each with an application, guarantors and a decision."""
    mid, _, member = new_member()
    for i in range(n):
        iid = assessed(client, "Low")
        app = new_application(client, mid, iid)
        r = client.post(f"/api/applications/{app['id']}/decision",
                        json={"outcome": "approve_with_guarantor", "guarantors_required": 2})
        assert r.status_code == 201, r.text
        r = member.post(f"/api/me/applications/{app['id']}/guarantors",
                        json={"guarantors": [guarantor(1), guarantor(2)]})
        assert r.status_code == 201, r.text
    return member


@pytest.mark.parametrize("path, admin", [
    ("/api/results", True), ("/api/applications?limit=500", False), ("/api/interviews", False),
    ("/api/admin/users", True), ("/api/members?limit=500", False),
])
def test_list_endpoints_do_not_query_per_row(client, admin_client, queries, summary, path, admin):
    c = admin_client if admin else client
    more_rows(client, 1)
    live_cache.invalidate()
    _, before = queries(c, path)
    more_rows(client, 3)
    live_cache.invalidate()
    r, after = queries(c, path)
    assert after == before, f"{path}: {before} queries, then {after} with three more rows"
    assert len(r.json()) > 0


def test_live_stats_are_five_queries_and_signing_in_is_one(admin_client, queries, summary):
    more_rows(admin_client, 1)
    live_cache.invalidate()
    _, n = queries(admin_client, "/api/results")
    assert n == 1 + 5   # session and user; counts and mean; groups; applications; guarantors; savings


def test_the_overview_list_of_applications_is_one_query(client, queries):
    more_rows(client, 2)
    _, n = queries(client, "/api/applications?limit=500")
    assert n == 1 + 1


def test_a_member_lists_their_own_applications_in_two_queries(client, queries):
    member = more_rows(client, 3)
    r, n = queries(member, "/api/me/applications")
    assert len(r.json()) == 3 and n == 2   # who is asking, with their member record; the applications


def full_sacco(member_id, others, entries=12, loans_n=1):
    """A member with entries on every account, loans, and pledges both ways."""
    with SessionLocal() as db:
        for i in range(entries):
            stamp = secrets.token_hex(4)
            ledger.post_entry(db, member_id, "deposits", "deposit", 100 + i, f"D-{stamp}")
            ledger.post_entry(db, member_id, "share_capital", "deposit", 50, f"S-{stamp}")
            ledger.post_entry(db, member_id, "transactional", "deposit", 75, f"T-{stamp}")
        for _ in range(loans_n):
            loan = ledger.issue_loan(db, member_id, 1000, 6, 200)
            ledger.record_repayment(db, loan, 200, f"R-{secrets.token_hex(4)}")
        for other in others:
            ledger.add_pledge(db, member_id, other)
            ledger.add_pledge(db, other, member_id)
            ledger.post_entry(db, other, "deposits", "deposit", 500, f"O-{secrets.token_hex(4)}")
        db.commit()


@pytest.mark.parametrize("staff", [False, True])
def test_the_sacco_page_does_not_query_per_row(client, queries, staff):
    mid, _, member = new_member()
    c = client if staff else member
    path = f"/api/members/{mid}/sacco" if staff else "/api/me/sacco"
    full_sacco(mid, [new_member(login=False)[0]])
    _, before = queries(c, path)
    full_sacco(mid, [new_member(login=False)[0] for _ in range(4)], entries=5, loans_n=3)
    r, after = queries(c, path)
    assert after == before, f"{path}: {before} queries, then {after} with more rows"
    body = r.json()
    assert len(body["my_guarantors"]) == 5 and len(body["i_guarantee"]) == 5 and len(body["loans"]) == 4
    assert [len(a["entries"]) for a in body["accounts"]] == [10, 10, 10]   # 17 of each; the newest ten
    assert after <= 17


def test_guarantor_offers_do_not_query_per_pledge(client, queries):
    mid, _, member = new_member()
    iid = assessed(client, "Low")
    app = new_application(client, mid, iid, amount=2000)
    r = client.post(f"/api/applications/{app['id']}/decision",
                    json={"outcome": "approve_with_guarantor", "guarantors_required": 2})
    assert r.status_code == 201, r.text
    path = f"/api/me/applications/{app['id']}/guarantor-offers"
    full_sacco(mid, [new_member(login=False)[0]], entries=1)
    _, before = queries(member, path)
    full_sacco(mid, [new_member(login=False)[0] for _ in range(4)], entries=1)
    r, after = queries(member, path)
    assert after == before and len(r.json()["offers"]) == 0   # KSh 500 each; KSh 1,000 is the share


# --- The cache -----------------------------------------------------------------------

def test_live_stats_are_served_from_the_cache_for_a_minute(admin_client, queries, summary):
    first, n_first = queries(admin_client, "/api/results")
    second, n_second = queries(admin_client, "/api/results")
    assert n_second == 1 < n_first           # only the sign-in check
    assert second.json()["live"] == first.json()["live"]
    assert re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(\.\d+)?\+00:00",
                        first.json()["live"]["computed_at"])


def test_an_expired_cache_is_computed_again(admin_client, summary, monkeypatch):
    first = admin_client.get("/api/results").json()["live"]
    monkeypatch.setattr(live_cache, "TTL_SECONDS", 0)
    live_cache.invalidate()
    admin_client.get("/api/results")
    assert admin_client.get("/api/results").json()["live"]["computed_at"] > first["computed_at"]


def test_an_assessment_drops_the_cache(admin_client, summary):
    before = admin_client.get("/api/results").json()["live"]
    assessed(admin_client, "High")
    after = admin_client.get("/api/results").json()["live"]
    assert after["assessment_count"] == before["assessment_count"] + 1
    assert after["computed_at"] > before["computed_at"]


def test_a_decision_drops_the_cache(admin_client, summary):
    iid = assessed(admin_client, "High")
    before = admin_client.get("/api/results").json()["live"]["decision_agreement"]
    r = admin_client.post(f"/api/interviews/{iid}/decision", json={"decision": "decline"})
    assert r.status_code == 201, r.text
    after = admin_client.get("/api/results").json()["live"]["decision_agreement"]
    assert (after["decisions"], after["agreements"]) == (before["decisions"] + 1,
                                                         before["agreements"] + 1)


def test_reads_and_rolled_back_writes_keep_the_cache(admin_client, client, summary):
    new_interview(client)
    computed = admin_client.get("/api/results").json()["live"]["computed_at"]
    client.get("/api/interviews")
    client.get("/api/applications")
    with SessionLocal() as db:
        iv = db.scalar(select(Interview).order_by(Interview.id.desc()))
        iv.mode = "practice" if iv.mode == "live" else "live"
        db.flush()
        db.rollback()
    assert admin_client.get("/api/results").json()["live"]["computed_at"] == computed


def test_a_commit_while_computing_is_not_cached(admin_client, summary, monkeypatch):
    from chamapro.api import main
    real = main.live_stats

    def slow(db):
        figures = real(db)
        with SessionLocal() as other:  # committed after the read, before it is cached
            other.add(Interview(applicant=Applicant(name=None)))
            other.commit()
        return figures
    monkeypatch.setattr(main, "live_stats", slow)
    stale = admin_client.get("/api/results").json()["live"]
    monkeypatch.setattr(main, "live_stats", real)
    fresh = admin_client.get("/api/results").json()["live"]
    assert fresh["interview_count"] == stale["interview_count"] + 1


# --- The PostgreSQL engine -----------------------------------------------------------

def test_postgres_connections_time_out_and_a_used_one_goes_out_first():
    eng = make_engine("postgresql+psycopg://u:p@db.example.invalid:5432/x")
    seen = {}

    @event.listens_for(eng, "do_connect")
    def _instead_of_connecting(dialect, conn_rec, cargs, cparams):
        seen.update(cparams)
        raise ConnectionAbortedError("not connecting in a test")
    try:
        assert eng.pool._pre_ping is False and eng.pool._pool.use_lifo     # pinged only when idle: test_postgres.py
        assert (eng.pool._recycle, eng.pool.size(), eng.pool._max_overflow) == (240, 5, 5)
        with pytest.raises(Exception, match="not connecting"):
            eng.connect()
        assert seen["connect_timeout"] == 10
    finally:
        eng.dispose()


# --- The conversation ----------------------------------------------------------------------

# Statements, as the request log counts them: on PostgreSQL what batch.py sends as one counts as
# one here too, on either database. A reply that writes a decision also has a BEGIN and a COMMIT,
# which no statement count sees; test_latency.py counts those on the wire. So: at most 8 round
# trips means at most 6 statements here for a decision and 8 for anything else.
ORDINARY, WITH_A_DECISION = 4, 6


@pytest.fixture
def replies(caplog):
    """replies(member, cid, words) -> (the reply's JSON, statements it ran)."""
    def run(member, cid, words):
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="chamapro.requests"):
            r = member.post(f"/api/conversations/{cid}/reply", data={"text": words})
        assert r.status_code == 200, r.text
        lines = [m for rec in caplog.records if rec.name == "chamapro.requests" and (m := QUERIES.match(rec.getMessage()))]
        assert len(lines) == 1, caplog.text
        return r.json(), int(lines[0][4])
    return run


@pytest.fixture
def started(caplog):
    def run(member, language="en"):
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="chamapro.requests"):
            r = member.post("/api/conversations", json={"language": language})
        assert r.status_code == 201, r.text
        lines = [m for rec in caplog.records if rec.name == "chamapro.requests" and (m := QUERIES.match(rec.getMessage()))]
        return r.json(), int(lines[0][4])
    return run


def test_every_step_of_a_conversation_to_a_payout(client, model, started, replies):
    _, member, _ = borrower()
    body, n = started(member)
    assert n <= 5
    cid = body["conversation"]["id"]
    for words, want in [("yes", "G2"), ("yes", "R1"), ("Forty thousand for school fees", "C1"), ("twelve months", "CONFIRM")]:
        out, n = replies(member, cid, words)
        assert out["bot_turns"][0]["template_id"] == want
        assert n <= ORDINARY, f"{want}: {n} statements"
    out, n = replies(member, cid, "yes")
    assert out["bot_turns"][0]["template_id"] == "O1" and out["outcome"]["decision"] == "approved"
    assert n <= WITH_A_DECISION, f"the payout: {n} statements"


def test_a_re_ask_a_correction_and_a_second_question_are_ordinary_replies(client, model, replies):
    mid, member, _ = borrower()
    age_income(mid, 300)
    cid = begin(member)["conversation"]["id"]
    for words, want in [("banana", "REASK"), ("yes", "G2_NO_INCOME"), ("No, we are 6 people at home now", "R1"),
                        ("Forty thousand for school fees", "C1"), ("twelve months", "C2"), ("yes that is right", "CONFIRM")]:
        out, n = replies(member, cid, words)
        assert out["bot_turns"][0]["template_id"] == want
        assert n <= ORDINARY, f"{want}: {n} statements"


def test_an_offer_the_guarantors_limit_stays_within_the_limit_to_the_end(client, model, replies):
    mid, member, gs = borrower(free=2000)
    cid = begin(member)["conversation"]["id"]
    for words, want in [("yes", "G2"), ("yes", "R1"), ("Forty thousand for school fees", "C1"), ("twelve months", "C6"), ("yes", "CONFIRM")]:
        out, n = replies(member, cid, words)
        assert out["bot_turns"][0]["template_id"] == want
        assert n <= ORDINARY, f"{want}: {n} statements"
    out, n = replies(member, cid, "yes")
    assert out["bot_turns"][0]["template_id"] == "O2" and n <= WITH_A_DECISION, f"{n} statements"


@pytest.mark.parametrize("risk, joined, want", [("High", "2020-01-01", "O3"), ("Low", "2026-09-01", "O4")])
def test_a_referral_and_a_not_now_are_within_the_limit(client, model, replies, risk, joined, want):
    model["risk"] = risk
    _, member, _ = borrower(joined=joined)
    cid = begin(member)["conversation"]["id"]
    for words in ("yes", "yes", "Forty thousand for school fees", "twelve months"):
        out, n = replies(member, cid, words)
        if out["conversation"]["status"] != "open":
            break
    assert out["bot_turns"][0]["template_id"] == want
    assert out["outcome"]["decision"] == ("referred" if want == "O3" else "not_now")
    assert n <= WITH_A_DECISION, f"{n} statements"


def test_the_reply_that_says_how_it_came_out_says_what_the_transcript_says(client, model):
    """The reply works it out from what it wrote, at no further cost; the transcript reads it back."""
    for answers in (("yes", "yes", "Forty thousand for school fees", "twelve months", "yes"),   # paid out
                    ("no",)):                                                                   # nothing decided
        _, member, _ = borrower()
        cid = begin(member)["conversation"]["id"]
        for words in answers:
            out = say(member, cid, words)
        assert out["outcome"] == member.get(f"/api/conversations/{cid}").json()["outcome"], answers


def test_the_snapshot_reads_what_the_ledgers_own_functions_read(client, model):
    mid, member, gs = borrower(deposits=30000, free=30000)
    conversation = begin(member)["conversation"]["id"]
    for words in ("yes", "yes", "Forty thousand for school fees", "twelve months", "yes"):
        say(member, conversation, words)
    with SessionLocal() as db:
        ledger.post_entry(db, gs[0], "deposits", "deposit", 1234, f"T-{secrets.token_hex(3)}")
        loan = ledger.issue_loan(db, mid, 12000, 12, ledger.instalment_kes(12000, 12))
        ledger.record_repayment(db, loan, 500, f"T-{secrets.token_hex(3)}")
        db.commit()
        m = db.get(Member, mid)
        snap = decisions.read_snapshot(db, m)
        everyone = {mid, *gs}
        assert {i: snap.capacity(i) for i in everyone} == ledger.capacities(db, everyone)
        assert snap.deposits.get(mid) == ledger.deposits_balance(db, mid)
        statuses, entries, lost = ledger.known_to_the_sacco(db, mid)
        assert sorted(snap.records[0]) == sorted(statuses) and snap.records[1:] == (entries, lost)
        assert snap.paid == ledger.paid_on_loans(db, [loan.id, *(x.id for x in snap.loans if x.status in ledger.STILL_OWED)])
        assert snap.transactional_kes == ledger.balances(db, mid)["transactional"]
        assert snap.held == ledger.held_under_pledges(db, [p[0] for p in snap.pledges])
        assert sorted(a for a, _ in snap.confirmed) == sorted(a for a, _ in decisions.confirmations(db, mid))
        assert snap.open_application is self_service.has_open_application(db, mid)
        assert snap.system_user_id == self_service.system_user(db).id


# --- What a screen polls -------------------------------------------------------------------

def test_the_presenter_poll_is_three_at_most_and_one_if_nothing_moved(client, model, queries, caplog):
    _, member, _ = borrower()
    cid = begin(member)["conversation"]["id"]
    say(member, cid, "yes")
    path = f"/api/present/conversations/{cid}"
    first, n = queries(client, path)
    assert n <= 3
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="chamapro.requests"):
        again = client.get(path, headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304 and again.content == b""
    assert next(int(m[4]) for rec in caplog.records if (m := QUERIES.match(rec.getMessage()))) == 1
    say(member, cid, "yes")
    moved, n = queries(client, path)     # sent without the tag it holds, the same answer as with it
    assert moved.headers["etag"] != first.headers["etag"] and n <= 3
    _, n = queries(client, "/api/present/conversations")
    assert n <= 3


def test_what_the_chat_polls_is_cheap(client, model, queries):
    _, member, _ = borrower()
    cid = begin(member)["conversation"]["id"]
    say(member, cid, "yes")
    assert queries(member, f"/api/conversations/{cid}/stage")[1] == 2
    assert queries(member, f"/api/conversations/{cid}")[1] <= 3
    assert queries(member, "/api/conversations/current")[1] == 2
