"""Round trips: against Supabase each query costs ~200 ms, so the slow pages'
endpoints issue a fixed number of queries however many rows there are, and
the live statistics are cached for a minute (live_cache.py)."""
import logging
import re
import secrets

import pytest
from sqlalchemy import event, select

from conftest import assessed, guarantor, new_application, new_interview, new_member
from chamapro.api import ledger, live_cache
from chamapro.api.db import Applicant, Interview, SessionLocal, make_engine

QUERIES = re.compile(r"^(\w+) (\S+) (\d+): (\d+) queries, \d+ ms$")


@pytest.fixture
def summary(monkeypatch, tmp_path):
    from chamapro import config
    path = tmp_path / "summary.json"
    path.write_text('{"generated_at": "2026-10-19T00:00:00+00:00"}', encoding="utf-8")
    monkeypatch.setattr(config, "RESULTS_SUMMARY_PATH", path)


@pytest.fixture
def queries(caplog):
    """queries(client, path) -> (response, statements the request ran), from its log line."""
    def run(client, path):
        caplog.clear()
        with caplog.at_level(logging.INFO, logger="chamapro.requests"):
            r = client.get(path)
        assert r.status_code == 200, r.text
        lines = [m for rec in caplog.records if rec.name == "chamapro.requests"
                 if (m := QUERIES.match(rec.getMessage())) and m[2] == path.split("?")[0]]
        assert len(lines) == 1, caplog.text
        assert (lines[0][1], lines[0][3]) == ("GET", "200")
        return r, int(lines[0][4])
    return run


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
    assert len(r.json()) == 3 and n == 1 + 2   # their member record; the applications


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

def test_postgres_connections_are_pinged_and_time_out():
    eng = make_engine("postgresql+psycopg://u:p@db.example.invalid:5432/x")
    seen = {}

    @event.listens_for(eng, "do_connect")
    def _instead_of_connecting(dialect, conn_rec, cargs, cparams):
        seen.update(cparams)
        raise ConnectionAbortedError("not connecting in a test")
    try:
        assert eng.pool._pre_ping is True
        assert (eng.pool._recycle, eng.pool.size(), eng.pool._max_overflow) == (240, 5, 5)
        with pytest.raises(Exception, match="not connecting"):
            eng.connect()
        assert seen["connect_timeout"] == 10
    finally:
        eng.dispose()
