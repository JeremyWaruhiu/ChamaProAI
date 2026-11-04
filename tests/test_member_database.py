"""The member database: profiles and their history, the savings ledger, loan
history, standing guarantors, profile_features, sign-up claiming a member, the
generated members, and what all of it changes in the 0004 flows."""
import json
import random
import re
import secrets
import sqlite3
import subprocess
import sys
from datetime import date, datetime, timedelta

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

import score_interview
import seed_demo
import seed_members
from chamapro import config
from chamapro.api import comparator, ledger, pilot, profiles
from chamapro.api.db import (AccountEntry, AuditLog, Guarantor, GuarantorPledge, LoanAccount, LoanApplication, Member,
                             MemberAccount, MemberProfile, MemberProfileHistory, SessionLocal, User, init_db,
                             nairobi_today, normalise_phone, utcnow)
from chamapro.api.main import app
from conftest import (BASE_URL, assessed, fresh_phone, guarantor, needs_classifier, new_application, new_member)
from test_member_access import leaks

INVITE = "test-invite-" + secrets.token_hex(4)
PASSWORD = "correct horse battery"
TODAY = date(2026, 11, 4)

# What the eight v2 questions and the form would have produced, as extraction
# returns it and as the form gives it.
FORM = {"age": 44, "sex": "female", "education": 4, "marital_status": "married"}
EXTRACTED = {"household_size": 5, "children": 3, "children_under5": 1, "children_in_school": 2,
             "monthly_income_kes": 18000, "agri_income_kes": 6000,
             "income_sources": {"farming": 1, "own_business": 1},
             "non_monetary_savings": {"land_or_buildings": 1, "livestock": 1},
             "purchases_last_12m": {"house_materials": 1},
             "lost_as_guarantor": {"sacco": 1, "chama": 1}, "sacco_loan_use": 2, "chama_loan_use": 1}
PROFILE = {"date_of_birth": date(1982, 3, 1), "sex": "female", "education": 4, "marital_status": "married",
           "household_size": 5, "children": 3, "children_under5": 1, "children_in_school": 2,
           "monthly_income_kes": 18000, "agri_income_kes": 6000,
           "income_sources": {"farming": 1, "own_business": 1},
           "non_monetary_savings": {"land_or_buildings": 1, "livestock": 1},
           "purchases_last_12m": {"house_materials": 1}, "chama_loan_use": 1, "lost_as_guarantor_chama": 1}


def body(**over):
    out = {**PROFILE, **over}
    return {k: v.isoformat() if isinstance(v, date) else v for k, v in out.items()}


def ref():
    return f"T-{secrets.token_hex(6)}"


def deposit(member_id, amount=1000, kind="deposits", when=None):
    with SessionLocal() as db:
        e = ledger.post_entry(db, member_id, kind, "deposit", amount, ref(), posted_at=when)
        db.commit()
        return e.id


def get(model, ident):
    with SessionLocal() as db:
        return db.get(model, ident)


def issue(member_id, principal=1000, term=5, instalment=200, status=None, disbursed_on=None):
    with SessionLocal() as db:
        loan = ledger.issue_loan(db, member_id, principal, term, instalment, disbursed_on)
        if status:
            loan.status = status
        db.commit()
        return loan.id


def guarantee(loan_id, guarantor_id, amount):
    with SessionLocal() as db:
        g = db.get(Member, guarantor_id)
        db.add(Guarantor(loan_account_id=loan_id, member_id=g.id, full_name=g.full_name, member_no=g.member_no,
                         phone=g.phone or "0", relationship_="x", amount_guaranteed_kes=amount, status="verified"))
        db.commit()


def pledge(borrower, guarantor_id):
    with SessionLocal() as db:
        p = ledger.add_pledge(db, borrower, guarantor_id)
        db.commit()
        return p.id


@pytest.fixture
def invite(monkeypatch, client):
    monkeypatch.setattr(config, "PILOT_INVITE_CODE", INVITE)


def signup_body(**over):
    out = {"full_name": "Fictional Volunteer", "phone": fresh_phone(), "password": PASSWORD,
           "password_confirm": PASSWORD, "invite_code": INVITE, "consent": True,
           "consent_version": pilot.CONSENT_VERSION}
    return {**out, **over}


def needing_guarantors(client, member_id, amount=10000, required=2):
    """An application at guarantor_required."""
    application = new_application(client, member_id, assessed(client, "Medium"), amount=amount)
    r = client.post(f"/api/applications/{application['id']}/decision",
                    json={"outcome": "approve_with_guarantor", "guarantors_required": required})
    assert r.status_code == 201, r.text
    return application["id"]


# --- The profile --------------------------------------------------------------------------

def test_registration_saves_once_and_records_who_said_what(client):
    mid, _, member = new_member()
    r = member.post("/api/me/profile", json=body())
    assert r.status_code == 201, r.text
    p = r.json()["profile"]
    assert p["monthly_income_kes"] == 18000
    assert p["income_sources"]["farming"] == 1 and p["income_sources"]["pension"] == 0
    assert p["groups"]["income"]["source"] == "registration" and p["groups"]["income"]["verified"] is False
    assert p["days_since_confirmed"] == 0

    assert member.post("/api/me/profile", json=body()).status_code == 409


def test_an_edit_is_saved_at_once_as_member_update_and_unverified(client):
    mid, _, member = new_member()
    member.post("/api/me/profile", json=body())
    assert client.post(f"/api/members/{mid}/profile/verify").status_code == 200

    p = member.patch("/api/me/profile", json={"monthly_income_kes": 25000}).json()["profile"]

    assert p["monthly_income_kes"] == 25000
    assert p["groups"]["income"] == {**p["groups"]["income"], "source": "member_update", "verified": False}
    # The groups it did not touch keep their verification.
    assert p["groups"]["household"]["source"] == "officer_verified" and p["groups"]["household"]["verified"] is True


def test_an_officer_verifies_and_the_page_says_by_whom(client):
    mid, _, member = new_member()
    member.post("/api/me/profile", json={"household_size": 3})
    v = client.post(f"/api/members/{mid}/profile/verify").json()["profile"]
    assert v["groups"]["household"]["source"] == "officer_verified"
    assert v["checks"]["household"]["by"] == "officer1"
    assert v["provenance"]["household_size"] == "verified"
    assert v["provenance"]["monthly_income_kes"] == "missing"
    # Groups holding nothing are not verified: nobody has checked nothing.
    assert v["groups"]["income"]["source"] is None and v["groups"]["income"]["verified"] is False
    r = client.post(f"/api/members/{mid}/profile/verify", json={"groups": ["income"]})
    assert r.status_code == 409


def test_verify_needs_staff_and_a_profile(client):
    mid, _, member = new_member()
    assert client.post(f"/api/members/{mid}/profile/verify").status_code == 409
    assert member.post(f"/api/members/{mid}/profile/verify").status_code == 403
    assert client.post("/api/members/99999999/profile/verify").status_code == 404


def test_every_change_writes_a_history_snapshot(client):
    mid, _, member = new_member()
    member.post("/api/me/profile", json=body())
    member.patch("/api/me/profile", json={"monthly_income_kes": 25000})
    member.post("/api/me/profile/confirm")
    client.post(f"/api/members/{mid}/profile/verify")
    with SessionLocal() as db:
        rows = db.scalars(select(MemberProfileHistory).where(MemberProfileHistory.member_id == mid)
                          .order_by(MemberProfileHistory.id)).all()
        assert [r.change for r in rows] == ["registration", "member_update", "confirm", "officer_verified"]
        assert rows[0].snapshot["monthly_income_kes"] == 18000 and rows[1].snapshot["monthly_income_kes"] == 25000
        assert rows[0].snapshot["date_of_birth"] == "1982-03-01"
        assert rows[1].groups == ["income"]
        # The log that cannot be erased holds group names, no values.
        log = db.scalars(select(AuditLog).where(AuditLog.entity == "member", AuditLog.entity_id == mid,
                                                AuditLog.action.like("profile.%"))).all()
        assert len(log) == 4 and not any("25000" in json.dumps(x.details) for x in log)


def test_sending_the_same_values_is_a_confirmation(client):
    mid, _, member = new_member()
    member.post("/api/me/profile", json=body())
    client.post(f"/api/members/{mid}/profile/verify")
    p = member.patch("/api/me/profile", json={"household_size": 5}).json()["profile"]
    assert p["groups"]["household"]["source"] == "officer_verified"
    with SessionLocal() as db:
        last = db.scalar(select(MemberProfileHistory).where(MemberProfileHistory.member_id == mid)
                         .order_by(MemberProfileHistory.id.desc()))
        assert (last.change, last.groups) == ("confirm", [])


@pytest.mark.parametrize("sql, message", [("UPDATE member_profile_history SET change = 'x'", "member_profile_history"),
                                          ("DELETE FROM member_profile_history", "member_profile_history"),
                                          ("UPDATE account_entries SET amount_kes = 1", "account_entries"),
                                          ("DELETE FROM account_entries", "account_entries")])
def test_history_and_ledger_refuse_changes_on_sqlite_too(client, sql, message):
    mid, _, member = new_member()
    member.post("/api/me/profile", json=body())
    deposit(mid)
    from sqlalchemy import text
    with SessionLocal() as db:
        with pytest.raises(IntegrityError, match=f"{message} is append-only"):
            db.execute(text(sql))
        db.rollback()


@pytest.mark.parametrize("field, value", [("sacco_loan_use", 2), ("lost_as_guarantor", {"sacco": 0}),
                                          ("lost_as_guarantor_sacco", 0), ("sacco_savings_kes", 1)])
def test_what_the_sacco_knows_cannot_be_declared(client, field, value):
    _, _, member = new_member()
    assert member.post("/api/me/profile", json=body(**{field: value})).status_code == 422
    assert member.patch("/api/me/profile", json={field: value}).status_code == 422


@pytest.mark.parametrize("over", [{"income_sources": {"lottery": 1}}, {"income_sources": {"farming": 2}},
                                  {"non_monetary_savings": {"farming": 1}}, {"chama_loan_use": 3},
                                  {"education": 9}, {"date_of_birth": "2020-01-01"}, {"household_size": 0}])
def test_bad_profile_values_are_refused(client, over):
    _, _, member = new_member()
    assert member.post("/api/me/profile", json=body(**over)).status_code == 422


def test_the_profile_fills_the_applicant_form_of_the_0004_flows(client):
    mid, _, member = new_member()
    assert member.get("/api/me/member").json()["applicant_complete"] is False
    member.post("/api/me/profile", json=body())
    me = member.get("/api/me/member").json()
    assert me["applicant_complete"] is True
    assert (me["sex"], me["education"], me["marital_status"]) == ("female", 4, "married")
    today = nairobi_today()
    assert me["age"] == today.year - 1982 - ((today.month, today.day) < (3, 1))


def test_the_0004_form_follows_into_the_profile_and_a_contradicted_birth_date_goes(client):
    mid, _, member = new_member()
    member.post("/api/me/profile", json=body())
    age = member.get("/api/me/member").json()["age"]

    same = {"age": age, "sex": "male", "education": 2, "marital_status": "single"}
    assert member.patch("/api/me/member", json={"applicant": same}).status_code == 200
    p = member.get("/api/me/sacco").json()["profile"]
    assert (p["sex"], p["education"], p["date_of_birth"]) == ("male", 2, "1982-03-01")
    assert p["groups"]["personal"]["source"] == "member_update"

    assert member.patch("/api/me/member", json={"applicant": {**same, "age": age + 5}}).status_code == 200
    p = member.get("/api/me/sacco").json()["profile"]
    assert p["date_of_birth"] is None and p["age"] == age + 5


# --- The ledger --------------------------------------------------------------------------

def test_a_balance_is_the_sum_of_its_entries_per_account(client):
    mid, *_ = new_member(login=False)
    deposit(mid, 1000)
    deposit(mid, 500)
    deposit(mid, 200, "share_capital")
    deposit(mid, 3000, "transactional")
    with SessionLocal() as db:
        ledger.post_entry(db, mid, "transactional", "withdrawal", -1000, ref())
        ledger.post_entry(db, mid, "share_capital", "dividend", 20, ref())
        db.commit()
        assert ledger.balances(db, mid) == {"deposits": 1500, "share_capital": 220, "transactional": 2000}
        assert ledger.deposits_balance(db, mid) == 1500


def test_a_member_with_no_entries_has_no_balance_to_read(client):
    mid, *_ = new_member(login=False)
    with SessionLocal() as db:
        assert ledger.deposits_balance(db, mid) is None
        assert ledger.balances(db, mid) == {"deposits": 0, "share_capital": 0, "transactional": 0}


@pytest.mark.parametrize("kind, entry_type, amount, constraint", [
    ("deposits", "withdrawal", -100, "ck_account_entries_no_deposit_withdrawal"),
    ("deposits", "deposit", -100, "ck_account_entries_sign"),
    ("transactional", "withdrawal", 100, "ck_account_entries_sign"),
    ("deposits", "loan_disbursement", 100, "ck_account_entries_disbursed_to_transactional"),
    ("share_capital", "loan_repayment", -100, "ck_account_entries_disbursed_to_transactional"),
    ("transactional", "guarantee_recovery", -100, "ck_account_entries_recovered_from_deposits"),
    ("deposits", "bonus", 100, "ck_account_entries_type"),
])
def test_the_database_refuses_an_entry_against_the_rules(client, kind, entry_type, amount, constraint):
    """Deposits are not withdrawable even from outside this code: the constraints hold it."""
    mid, *_ = new_member(login=False)
    with SessionLocal() as db:
        account = ledger.account_of(db, mid, kind)
        db.add(AccountEntry(account_id=account.id, account_kind=kind, entry_type=entry_type, amount_kes=amount,
                            posted_at=utcnow(), reference=ref()))
        with pytest.raises(IntegrityError, match=constraint):
            db.commit()


def test_an_entry_cannot_claim_another_kind_of_account(client):
    mid, *_ = new_member(login=False)
    with SessionLocal() as db:
        account = ledger.account_of(db, mid, "deposits")
        db.add(AccountEntry(account_id=account.id, account_kind="transactional", entry_type="withdrawal",
                            amount_kes=-5, posted_at=utcnow(), reference=ref()))
        with pytest.raises(IntegrityError, match="FOREIGN KEY"):
            db.commit()


def test_an_entry_cannot_overdraw_and_a_reference_is_used_once(client):
    mid, *_ = new_member(login=False)
    deposit(mid, 100, "transactional")
    with SessionLocal() as db:
        with pytest.raises(ledger.LedgerError, match="overdraw"):
            ledger.post_entry(db, mid, "transactional", "withdrawal", -101, ref())
        ledger.post_entry(db, mid, "transactional", "withdrawal", -100, "SAME")
        db.commit()
        with pytest.raises(IntegrityError, match="uq_account_entries_reference|UNIQUE"):
            ledger.post_entry(db, mid, "transactional", "dividend", 5, "SAME")


def test_last_entries_are_ten_per_account_newest_first(client):
    mid, *_ = new_member(login=False)
    start = utcnow() - timedelta(days=30)
    for i in range(12):
        deposit(mid, 100 + i, when=start + timedelta(days=i))
    deposit(mid, 7, "share_capital")
    with SessionLocal() as db:
        got = ledger.last_entries(db, mid)
    assert [e.amount_kes for e in got["deposits"]] == [111 - i for i in range(10)]
    assert [e.amount_kes for e in got["share_capital"]] == [7] and got["transactional"] == []


def test_my_sacco_shows_balances_entries_and_loans_and_nothing_of_the_officer(client):
    mid, _, member = new_member()
    other, *_ = new_member(login=False)
    deposit(mid, 5000)
    deposit(other, 9000)
    pledge(mid, other)
    pledge(other, mid)
    member.post("/api/me/profile", json=body())
    client.post(f"/api/members/{mid}/profile/verify")
    view = member.get("/api/me/sacco").json()
    assert {a["kind"]: a["balance_kes"] for a in view["accounts"]} == \
        {"deposits": 5000, "share_capital": 0, "transactional": 0}
    assert view["guarantee"]["capacity_kes"] == 5000
    assert view["my_guarantors"][0]["has_capacity"] is True
    assert view["i_guarantee"][0]["guaranteed_kes"] == 0
    assert leaks(view) == []
    assert "provenance" not in json.dumps({k: v for k, v in view["profile"].items() if v is not None})


def test_a_member_never_sees_a_guarantors_figures_but_an_officer_does(client):
    mid, _, member = new_member()
    other, *_ = new_member(login=False)
    deposit(other, 9000)
    pledge(mid, other)
    assert member.get("/api/me/sacco").json()["my_guarantors"][0]["capacity_kes"] is None
    assert client.get(f"/api/members/{mid}/sacco").json()["my_guarantors"][0]["capacity_kes"] == 9000
    assert "9000" not in member.get("/api/me/sacco").text


def test_members_cannot_read_each_others_page(client):
    mid, _, member = new_member()
    assert member.get(f"/api/members/{mid}/sacco").status_code == 403
    assert client.get("/api/members/99999999/sacco").status_code == 404
    assert TestClient(app, base_url=BASE_URL).get("/api/me/sacco").status_code == 401


def test_a_member_with_records_cannot_be_deleted_but_one_without_can(client):
    bare, *_ = new_member(login=False)
    assert client.delete(f"/api/members/{bare}").status_code == 204
    saver, *_ = new_member(login=False)
    deposit(saver)
    r = client.delete(f"/api/members/{saver}")
    assert r.status_code == 409 and "ledger" in r.json()["detail"]
    pledger, *_ = new_member(login=False)
    pledge(saver, pledger)
    assert client.delete(f"/api/members/{pledger}").status_code == 409


# --- The SACCO rule reads the deposits balance ------------------------------------------------

def test_the_rule_reads_the_ledger_not_the_figure_on_the_application(client):
    mid, *_ = new_member()
    deposit(mid, 20000)
    iid = assessed(client, "Low")
    application = new_application(client, mid, iid, amount=50000, savings=1)    # typed: ignored
    assert application["sacco_savings_kes"] == 20000 and application["savings_from_ledger"] is True
    max_ = application["assessment"]["comparator"]["max_borrowable_kes"]
    assert max_ == 60000
    with SessionLocal() as db:
        assert db.get(LoanApplication, application["id"]).sacco_savings_kes == 20000  # stored too


def test_an_application_follows_the_ledger_until_it_is_decided(client):
    mid, *_ = new_member()
    deposit(mid, 20000)
    application = new_application(client, mid, assessed(client, "Low"), amount=50000)
    deposit(mid, 5000)
    assert client.get(f"/api/applications/{application['id']}").json()["sacco_savings_kes"] == 25000
    r = client.post(f"/api/applications/{application['id']}/decision", json={"outcome": "approve"})
    assert r.status_code == 201, r.text
    deposit(mid, 7000)
    got = client.get(f"/api/applications/{application['id']}").json()
    assert got["sacco_savings_kes"] == 25000
    assert got["comparator"]["max_borrowable_kes"] == 75000


def test_a_member_with_no_ledger_keeps_the_figure_on_the_application(client):
    mid, *_ = new_member()
    application = new_application(client, mid, assessed(client, "Low"), amount=30000, savings=15000)
    assert application["sacco_savings_kes"] == 15000 and application["savings_from_ledger"] is False
    assert application["comparator"]["max_borrowable_kes"] == 45000


def test_entries_after_a_decision_do_not_replace_the_figure_it_was_decided_on(client):
    mid, *_ = new_member()
    application = new_application(client, mid, assessed(client, "Low"), amount=30000, savings=15000)
    client.post(f"/api/applications/{application['id']}/decision", json={"outcome": "approve"})
    deposit(mid, 1)                                 # the member joins the ledger later
    got = client.get(f"/api/applications/{application['id']}").json()
    assert got["sacco_savings_kes"] == 15000 and got["savings_from_ledger"] is False


def test_the_statistics_read_the_same_figure_as_the_page(admin_client, client):
    from chamapro.api import main
    mid, *_ = new_member()
    deposit(mid, 1000)
    app_id = new_application(client, mid, assessed(client, "Low"), amount=50000, savings=99999)["id"]
    detail = client.get(f"/api/applications/{app_id}").json()
    assert next(c for c in detail["comparator"]["conditions"] if c["name"] == "savings_multiple")["result"] == "fail"
    with SessionLocal() as db:
        a = db.get(LoanApplication, app_id)
        assert ledger.rule_savings(db, [a])[app_id].kes == 1000
        before = main.live_stats(db)["rule_agreement"]
    deposit(mid, 50000)
    with SessionLocal() as db:
        after = main.live_stats(db)["rule_agreement"]
    assert before["applications"] == after["applications"]
    assert before != after          # the one application's savings condition moved


def test_a_member_on_the_ledger_applies_without_declaring_anything(client):
    mid, _, member = new_member()
    deposit(mid, 12000)
    me = member.get("/api/me/member").json()
    assert (me["savings_kes"], me["savings_status"], me["from_ledger"]) == (12000, "ledger", True)
    assert me["savings_limit_kes"] == 36000
    assert member.patch("/api/me/member", json={"savings_kes": 500}).status_code == 409
    assert client.post(f"/api/members/{mid}/verify", json={"savings_kes": 500}).status_code == 409
    # Correcting the membership date still works, and needs no savings figure.
    assert client.post(f"/api/members/{mid}/verify", json={"joined_on": "2020-02-01"}).status_code == 200
    with SessionLocal() as db:
        assert db.get(Member, mid).savings_kes is None     # nothing was typed over the ledger


def test_the_member_application_stores_the_balance_and_says_it_is_not_declared(client):
    from test_pilot import free_slot
    mid, _, member = new_member()
    deposit(mid, 12000)
    member.post("/api/me/profile", json=body())
    apply_body = {"amount_requested_kes": 1000, "purpose": "School fees", "term_months": 6, "language": "en",
                  **free_slot(member)}
    assert member.post("/api/me/applications",
                       json={**apply_body, "declared_savings_kes": 500}).status_code == 422
    r = member.post("/api/me/applications", json=apply_body)
    assert r.status_code == 201, r.text
    with SessionLocal() as db:
        a = db.get(LoanApplication, r.json()["id"])
        assert (a.sacco_savings_kes, a.savings_self_declared) == (12000, False)


def test_a_new_volunteer_with_no_ledger_still_declares_as_before(client, invite):
    c = TestClient(app, base_url=BASE_URL)
    assert c.post("/api/auth/signup", json=signup_body()).status_code == 201
    me = c.get("/api/me/member").json()
    assert (me["savings_kes"], me["savings_status"], me["from_ledger"]) == (None, "none", False)
    assert c.patch("/api/me/member", json={"savings_kes": 900}).json()["savings_status"] == "self_declared"


# --- Loan history ---------------------------------------------------------------------------

def test_a_loan_pays_out_to_the_transactional_account_and_is_repaid_from_it(client):
    mid, *_ = new_member(login=False)
    loan_id = issue(mid, 1000, 5, 200)
    with SessionLocal() as db:
        assert ledger.balances(db, mid)["transactional"] == 1000
        loan = db.get(LoanAccount, loan_id)
        for _ in range(4):
            ledger.record_repayment(db, loan, 200, ref())
        assert loan.status == "active"
        ledger.record_repayment(db, loan, 200, ref())
        db.commit()
        assert loan.status == "repaid"
        assert ledger.paid_on_loans(db, [loan_id]) == {loan_id: 1000}
        with pytest.raises(ledger.LedgerError):
            ledger.record_repayment(db, loan, 1, ref())


@pytest.mark.parametrize("paid, today, want", [
    (0, date(2026, 2, 1), 0),      # the first instalment falls due on 1 February
    (0, date(2026, 2, 11), 10),
    (199, date(2026, 2, 11), 10),  # part of one does not clear it
    (200, date(2026, 2, 11), 0),
    (200, date(2026, 3, 4), 3),    # the second fell due on 1 March
    (400, date(2026, 3, 4), 0),
    (1000, date(2027, 1, 1), 0),   # all paid
    (800, date(2027, 1, 1), 214),  # the last fell due on 1 June 2026
])
def test_days_in_arrears_count_from_the_oldest_unpaid_instalment(paid, today, want):
    loan = LoanAccount(principal_kes=1000, disbursed_on=date(2026, 1, 1), term_months=5,
                       monthly_instalment_kes=200, status="active")
    assert ledger.days_in_arrears(loan, paid, today) == want


def test_a_repaid_loan_has_no_arrears_and_month_ends_clamp():
    assert ledger.days_in_arrears(LoanAccount(disbursed_on=date(2026, 1, 1), term_months=5, monthly_instalment_kes=200,
                                              status="repaid"), 0, date(2030, 1, 1)) == 0
    assert ledger.add_months(date(2026, 1, 31), 1) == date(2026, 2, 28)


def test_the_page_computes_paid_and_arrears_and_links_the_application(client):
    mid, _, member = new_member()
    aid = new_application(client, mid, assessed(client, "Low"), amount=1000)["id"]
    client.post(f"/api/applications/{aid}/decision", json={"outcome": "approve"})
    with SessionLocal() as db:
        a = db.get(LoanApplication, aid)
        loan = ledger.issue_loan(db, mid, 1000, 5, 200, nairobi_today() - timedelta(days=70), a)
        ledger.record_repayment(db, loan, 200, ref())
        db.commit()
    (out,) = member.get("/api/me/sacco").json()["loans"]
    assert (out["application_id"], out["principal_kes"], out["paid_kes"], out["status"]) == (aid, 1000, 200, "active")
    assert out["days_in_arrears"] > 0


def test_only_an_approved_application_is_paid_out(client):
    mid, *_ = new_member()
    aid = new_application(client, mid, assessed(client, "Low"), amount=1000)["id"]
    with SessionLocal() as db:
        with pytest.raises(ledger.LedgerError, match="only an approved"):
            ledger.issue_loan(db, mid, 1000, 5, 200, application=db.get(LoanApplication, aid))


# --- Derived features --------------------------------------------------------------------

@pytest.mark.parametrize("statuses, want", [([], 0), (["repaid"], 1), (["repaid", "repaid"], 1), (["active"], 2),
                                            (["repaid", "active"], 2), (["defaulted"], 2), (["repaid", "defaulted"], 2)])
def test_sacco_loan_use_from_loan_statuses(statuses, want):
    assert ledger.sacco_loan_use(statuses) == want


def features_of(member_id, **kw):
    with SessionLocal() as db:
        return profiles.profile_features(db, db.get(Member, member_id), **kw)


def test_derived_features_come_from_the_records_not_the_profile(client):
    mid, *_ = new_member(login=False)
    deposit(mid)
    got = features_of(mid)
    assert got.features["sacco_loan_use"] == 0 and got.features["lost_as_guarantor"]["sacco"] == 0
    assert got.provenance["sacco_loan_use"] == got.provenance["lost_as_guarantor.sacco"] == "records"

    loan_id = issue(mid, status="repaid")
    assert features_of(mid).features["sacco_loan_use"] == 1
    issue(mid)
    assert features_of(mid).features["sacco_loan_use"] == 2

    with SessionLocal() as db:
        borrower, *_ = new_member(login=False)
        ledger.recover_guarantee(db, mid, db.get(LoanAccount, loan_id), 100, ref())
        db.commit()
    assert features_of(mid).features["lost_as_guarantor"]["sacco"] == 1


def test_no_records_at_all_is_missing_not_a_false_never(client):
    mid, *_ = new_member(login=False)
    got = features_of(mid)
    assert got.features["sacco_loan_use"] is None and got.features["lost_as_guarantor"]["sacco"] is None
    assert got.provenance["sacco_loan_use"] == got.provenance["lost_as_guarantor.sacco"] == "missing"
    assert got.days_since_confirmed is None


# --- profile_features ---------------------------------------------------------------------

def saved_profile(member_id, **over):
    with SessionLocal() as db:
        profiles.save_profile(db, db.get(Member, member_id), {**PROFILE, **over}, "registration", None)
        db.commit()


def with_loan_and_loss(mid):
    """Enough records for the derived features to read sacco_loan_use 2 and a loss."""
    deposit(mid, 1000)
    loan_id = issue(mid)
    with SessionLocal() as db:
        ledger.recover_guarantee(db, mid, db.get(LoanAccount, loan_id), 100, ref())
        db.commit()


def test_profile_features_has_exactly_the_keys_score_takes(client):
    mid, *_ = new_member(login=False)
    saved_profile(mid)
    got = features_of(mid)
    assert set(got.features) == set(score_interview.FIELDS)
    want = set(score_interview.FIELDS) - {"lost_as_guarantor"} | {"lost_as_guarantor.sacco", "lost_as_guarantor.chama"}
    assert set(got.provenance) == want
    assert set(got.features["income_sources"]) == set(score_interview.INCOME_SOURCES)


def test_provenance_says_declared_verified_records_or_missing(client):
    mid, *_ = new_member(login=False)
    saved_profile(mid, children=None)
    with_loan_and_loss(mid)
    with SessionLocal() as db:
        officer = db.scalar(select(User).where(User.username == "officer1"))
        profiles.verify_profile(db, db.get(Member, mid), officer, ["income"])
        db.commit()
    p = features_of(mid).provenance
    assert p["household_size"] == "declared" and p["children"] == "missing"
    assert p["monthly_income_kes"] == p["income_sources"] == "verified"
    assert p["sacco_loan_use"] == "records" and p["lost_as_guarantor.chama"] == "declared"


def test_the_0004_form_on_the_member_record_fills_in_and_is_declared(client):
    mid, *_ = new_member(login=False)
    with SessionLocal() as db:
        m = db.get(Member, mid)
        m.birth_year, m.sex, m.education, m.marital_status = 1980, "male", 3, "single"
        db.commit()
    got = features_of(mid, today=TODAY)
    assert (got.features["age"], got.features["is_female"], got.features["education_level"],
            got.features["marital_status"]) == (46, 0, 3, "single")
    assert got.provenance["age"] == got.provenance["is_female"] == "declared"
    assert got.provenance["household_size"] == "missing"


def test_days_since_confirmed_counts_from_the_last_confirmation(client):
    mid, *_ = new_member(login=False)
    saved_profile(mid)
    assert features_of(mid).days_since_confirmed == 0
    assert features_of(mid, today=nairobi_today() + timedelta(days=30)).days_since_confirmed == 30


def test_age_comes_from_the_date_of_birth_exactly(client):
    mid, *_ = new_member(login=False)
    saved_profile(mid, date_of_birth=date(1982, 11, 5))
    assert features_of(mid, today=date(2026, 11, 4)).features["age"] == 43     # the day before
    assert features_of(mid, today=date(2026, 11, 5)).features["age"] == 44


def old_v2_path(score=score_interview.build_vector, order=None):
    """As main.assess calls it: what extraction returned, and the form merged over."""
    form = score_interview.form_values(**FORM)
    return score(EXTRACTED, order, form)


def test_the_profile_and_the_v2_path_build_the_same_vector(client):
    """Runs everywhere: the classifier's own vector, without the classifier."""
    mid, *_ = new_member(login=False)
    saved_profile(mid)
    with_loan_and_loss(mid)
    order = list(score_interview.FEATURE_FIELD)
    got = features_of(mid, today=TODAY).features
    assert got["age"] == FORM["age"]
    from_profile, _ = score_interview.build_vector(got, order)
    from_v2, _ = old_v2_path(order=order)
    pd.testing.assert_frame_equal(from_profile, from_v2)


@needs_classifier
def test_scoring_from_the_profile_gives_the_same_result_as_the_v2_path(client):
    mid, *_ = new_member(login=False)
    saved_profile(mid)
    with_loan_and_loss(mid)
    from_profile = score_interview.score(features_of(mid, today=TODAY).features)
    from_v2 = score_interview.score(EXTRACTED, form=score_interview.form_values(**FORM))
    pd.testing.assert_frame_equal(from_profile.vector, from_v2.vector)
    for key in ("risk_class", "probabilities", "extraction_completeness", "features_populated", "top_contributions"):
        assert from_profile.assessment[key] == from_v2.assessment[key], key
    assert from_profile.model_sha256 == from_v2.model_sha256


# --- Guarantee capacity and standing guarantors --------------------------------------------------

def test_capacity_is_deposits_minus_guarantees_on_active_loans(client):
    g, *_ = new_member(login=False)
    b, *_ = new_member(login=False)
    deposit(g, 10000)
    active = issue(b)
    repaid = issue(b, status="repaid")
    defaulted = issue(b, status="defaulted")
    guarantee(active, g, 3000)
    guarantee(repaid, g, 1000)
    guarantee(defaulted, g, 500)
    with SessionLocal() as db:
        cap = ledger.capacities(db, [g])[g]
        assert (cap.deposits_kes, cap.guaranteed_kes, cap.capacity_kes) == (10000, 3000, 7000)
        assert ledger.active_guarantees(db, g) == {b: 3000}
        db.get(LoanAccount, active).status = "repaid"
        db.commit()
        assert ledger.capacities(db, [g])[g].capacity_kes == 10000


def test_capacity_is_never_below_zero(client):
    g, *_ = new_member(login=False)
    b, *_ = new_member(login=False)
    deposit(g, 1000)
    guarantee(issue(b), g, 5000)
    with SessionLocal() as db:
        assert ledger.capacities(db, [g])[g].capacity_kes == 0


def test_a_rejected_or_unverified_guarantee_on_a_loan_holds_nothing(client):
    g, *_ = new_member(login=False)
    b, *_ = new_member(login=False)
    deposit(g, 1000)
    guarantee(issue(b), g, 400)
    with SessionLocal() as db:
        row = db.scalar(select(Guarantor).where(Guarantor.member_id == g))
        row.status = "rejected"
        db.commit()
        assert ledger.capacities(db, [g])[g].guaranteed_kes == 0


def offers_of(member, application_id):
    r = member.get(f"/api/me/applications/{application_id}/guarantor-offers")
    assert r.status_code == 200, r.text
    return r.json()


def test_offers_are_standing_pledges_with_enough_capacity(client):
    mid, _, member = new_member()
    rich, *_ = new_member(login=False)
    exact, *_ = new_member(login=False)
    poor, *_ = new_member(login=False)
    tied_up, *_ = new_member(login=False)
    gone, *_ = new_member(login=False)
    stranger, *_ = new_member(login=False)
    for who, amount in ((rich, 50000), (exact, 5000), (poor, 4999), (tied_up, 9000), (gone, 50000), (stranger, 50000)):
        deposit(who, amount)
    other_borrower, *_ = new_member(login=False)
    guarantee(issue(other_borrower), tied_up, 8000)
    ids = {who: pledge(mid, who) for who in (rich, exact, poor, tied_up, gone)}
    pledge(other_borrower, stranger)             # someone else's guarantor
    with SessionLocal() as db:
        ledger.withdraw_pledge(db.get(GuarantorPledge, ids[gone]))
        db.commit()

    aid = needing_guarantors(client, mid, amount=10000, required=2)
    out = offers_of(member, aid)
    assert (out["share_kes"], out["needed"]) == (5000, 2)
    assert [o["pledge_id"] for o in out["offers"]] == [ids[rich], ids[exact]]
    assert "capacity" not in json.dumps(out)


def test_the_share_rounds_up_and_follows_a_reduced_amount(client):
    mid, _, member = new_member()
    aid = needing_guarantors(client, mid, amount=10001, required=2)
    assert offers_of(member, aid)["share_kes"] == 5001


def test_no_offers_unless_the_application_needs_guarantors(client):
    mid, _, member = new_member()
    aid = new_application(client, mid, assessed(client, "Low"))["id"]
    assert offers_of(member, aid) == {"share_kes": 0, "needed": 0, "offers": []}


def test_pledges_become_ordinary_guarantors_and_the_existing_review_approves(client):
    mid, _, member = new_member()
    a, *_ = new_member(login=False)
    b, *_ = new_member(login=False)
    deposit(a, 6000)
    deposit(b, 6000)
    pa, pb = pledge(mid, a), pledge(mid, b)
    aid = needing_guarantors(client, mid, amount=10000)

    r = member.post(f"/api/me/applications/{aid}/guarantors/pledged", json={"pledge_ids": [pa, pb]})
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "guarantor_submitted"
    staff = client.get(f"/api/applications/{aid}").json()
    assert {g["status"] for g in staff["guarantors"]} == {"pending"}
    assert {g["amount_guaranteed_kes"] for g in staff["guarantors"]} == {5000}
    with SessionLocal() as db:
        rows = db.scalars(select(Guarantor).where(Guarantor.application_id == aid)).all()
        assert {g.member_id for g in rows} == {a, b} and {g.pledge_id for g in rows} == {pa, pb}
        # Held against both while the application is open, but not yet on an active loan.
        cap = ledger.capacities(db, [a])[a]
        assert (cap.capacity_kes, cap.committed_kes, cap.available_kes) == (6000, 5000, 1000)

    for g in staff["guarantors"]:
        assert client.post(f"/api/guarantors/{g['id']}/verify").status_code == 200
    assert client.get(f"/api/applications/{aid}").json()["status"] == "approved"


def test_the_same_money_cannot_back_two_applications_at_once(client):
    g, *_ = new_member(login=False)
    deposit(g, 6000)
    first, _, first_client = new_member()
    second, _, second_client = new_member()
    p1, p2 = pledge(first, g), pledge(second, g)
    a1 = needing_guarantors(client, first, amount=10000)
    a2 = needing_guarantors(client, second, amount=10000)
    assert [o["pledge_id"] for o in offers_of(second_client, a2)["offers"]] == [p2]
    assert first_client.post(f"/api/me/applications/{a1}/guarantors/pledged", json={"pledge_ids": [p1]}).status_code == 201
    assert offers_of(second_client, a2)["offers"] == []
    r = second_client.post(f"/api/me/applications/{a2}/guarantors/pledged", json={"pledge_ids": [p2]})
    assert r.status_code == 409


def test_typing_a_members_number_holds_none_of_their_capacity_until_verified(client):
    mid, _, member = new_member()
    other, no, _ = new_member(login=False)
    deposit(other, 6000)
    aid = needing_guarantors(client, mid, amount=2000)
    member.post(f"/api/me/applications/{aid}/guarantors",
                json={"guarantors": [{**guarantor(1, 1000), "member_no": no}, guarantor(2, 1000)]})
    with SessionLocal() as db:
        assert ledger.capacities(db, [other])[other].committed_kes == 0
    row = next(g for g in client.get(f"/api/applications/{aid}").json()["guarantors"] if g["member_no"] == no)
    assert client.post(f"/api/guarantors/{row['id']}/verify").status_code == 200
    with SessionLocal() as db:
        assert ledger.capacities(db, [other])[other].committed_kes == 1000


def test_paying_out_the_loan_moves_the_guarantee_onto_it(client):
    mid, _, member = new_member()
    a, *_ = new_member(login=False)
    b, *_ = new_member(login=False)
    deposit(a, 6000)
    deposit(b, 6000)
    aid = needing_guarantors(client, mid, amount=10000)
    member.post(f"/api/me/applications/{aid}/guarantors/pledged", json={"pledge_ids": [pledge(mid, a), pledge(mid, b)]})
    for g in client.get(f"/api/applications/{aid}").json()["guarantors"]:
        client.post(f"/api/guarantors/{g['id']}/verify")
    with SessionLocal() as db:
        ledger.issue_loan(db, mid, 10000, 12, 1000, application=db.get(LoanApplication, aid))
        db.commit()
        cap = ledger.capacities(db, [a])[a]
        assert (cap.guaranteed_kes, cap.committed_kes, cap.capacity_kes) == (5000, 0, 1000)
    view = client.get(f"/api/members/{a}/sacco").json()
    assert view["guarantee"]["guaranteed_kes"] == 5000


def test_one_pledge_now_and_a_typed_guarantor_after(client):
    mid, _, member = new_member()
    a, *_ = new_member(login=False)
    deposit(a, 6000)
    pa = pledge(mid, a)
    aid = needing_guarantors(client, mid, amount=10000)
    r = member.post(f"/api/me/applications/{aid}/guarantors/pledged", json={"pledge_ids": [pa]})
    assert r.status_code == 201 and r.json()["status"] == "guarantor_required"
    assert r.json()["guarantors_still_needed"] == 1
    assert offers_of(member, aid)["offers"] == []       # not offered twice
    r = member.post(f"/api/me/applications/{aid}/guarantors", json={"guarantors": [guarantor(2, 5000)]})
    assert r.status_code == 201 and r.json()["status"] == "guarantor_submitted"


@pytest.mark.parametrize("case", ["duplicate", "too_many", "someone_elses", "unknown"])
def test_pledges_that_cannot_be_used(client, case):
    mid, _, member = new_member()
    a, *_ = new_member(login=False)
    b, *_ = new_member(login=False)
    c, *_ = new_member(login=False)
    other, *_ = new_member(login=False)
    for who in (a, b, c):
        deposit(who, 50000)
    pa, pb, pc = pledge(mid, a), pledge(mid, b), pledge(mid, c)
    theirs = pledge(other, a)
    aid = needing_guarantors(client, mid, amount=10000)
    ids = {"duplicate": [pa, pa], "too_many": [pa, pb, pc], "someone_elses": [theirs], "unknown": [99999999]}[case]
    r = member.post(f"/api/me/applications/{aid}/guarantors/pledged", json={"pledge_ids": ids})
    assert r.status_code == (422 if case in ("duplicate", "too_many") else 409), r.text
    assert client.get(f"/api/applications/{aid}").json()["guarantors"] == []


def test_another_members_application_is_a_404(client):
    mid, _, member = new_member()
    _, _, stranger = new_member()
    aid = needing_guarantors(client, mid)
    assert stranger.get(f"/api/me/applications/{aid}/guarantor-offers").status_code == 404
    assert stranger.post(f"/api/me/applications/{aid}/guarantors/pledged", json={"pledge_ids": [1]}).status_code == 404


def test_a_typed_guarantor_number_that_is_a_member_counts_as_that_member(client):
    mid, _, member = new_member()
    other, no, _ = new_member(login=False)
    aid = needing_guarantors(client, mid, amount=2000)
    r = member.post(f"/api/me/applications/{aid}/guarantors",
                    json={"guarantors": [{**guarantor(1, 500), "member_no": no.lower()}, guarantor(2, 500)]})
    assert r.status_code == 201, r.text
    with SessionLocal() as db:
        rows = db.scalars(select(Guarantor).where(Guarantor.application_id == aid).order_by(Guarantor.id)).all()
        assert [g.member_id for g in rows] == [other, None]
        assert rows[0].member_no == no.lower()      # stays as it was typed


def test_a_member_cannot_pledge_to_themselves(client):
    mid, *_ = new_member(login=False)
    with SessionLocal() as db:
        with pytest.raises(ledger.LedgerError):
            ledger.add_pledge(db, mid, mid)
        db.add(GuarantorPledge(borrower_member_id=mid, guarantor_member_id=mid, status="active"))
        with pytest.raises(IntegrityError, match="ck_guarantor_pledges_self"):
            db.commit()


def test_one_active_pledge_per_pair_but_a_withdrawn_one_can_be_made_again(client):
    a, *_ = new_member(login=False)
    b, *_ = new_member(login=False)
    p = pledge(a, b)
    with SessionLocal() as db:
        with pytest.raises(IntegrityError, match="uq_guarantor_pledges_active|UNIQUE"):
            ledger.add_pledge(db, a, b)
    with SessionLocal() as db:
        ledger.withdraw_pledge(db.get(GuarantorPledge, p))
        db.commit()
    assert pledge(a, b) != p


# --- Sign-up: claiming an existing member ---------------------------------------------------

def existing(joined_on="2020-01-01"):
    mid, no, _ = new_member(joined_on=joined_on, login=False)
    with SessionLocal() as db:
        return mid, no, db.get(Member, mid).phone


def test_phone_and_member_number_claim_the_member(invite, client):
    mid, no, phone = existing()
    c = TestClient(app, base_url=BASE_URL)
    deposit(mid, 4000)
    r = c.post("/api/auth/signup", json=signup_body(phone=phone, member_no=no, full_name="Someone Else",
                                                    email="claimer@example.invalid"))
    assert r.status_code == 201, r.text
    out = r.json()
    assert (out["claimed"], out["profile_due"], out["member_no"], out["role"]) == (True, False, no, "member")
    with SessionLocal() as db:
        m = db.get(Member, mid)
        assert m.user_id is not None and m.member_no == no
        assert m.full_name == f"Fictional {no}"          # the SACCO's record stands
        assert m.email == "claimer@example.invalid" and m.consent_version == pilot.CONSENT_VERSION
        assert m.self_signed_up is False
        assert db.scalar(select(Member.id).where(Member.phone == phone)) == mid
        assert db.scalar(select(AuditLog).where(AuditLog.action == "member.claim", AuditLog.entity_id == mid))
    assert c.get("/api/me/sacco").json()["guarantee"]["deposits_kes"] == 4000


def test_a_claim_accepts_the_number_in_any_form(invite, client):
    mid, no, phone = existing()
    national = "0" + phone[4:]
    r = TestClient(app, base_url=BASE_URL).post("/api/auth/signup",
                                                json=signup_body(phone=national, member_no=f"  {no.lower()} "))
    assert r.status_code == 201, r.text
    assert r.json()["claimed"] is True
    # They can sign in by the member number, and by phone.
    for name in (no, national):
        again = TestClient(app, base_url=BASE_URL).post("/api/auth/login", json={"username": name, "password": PASSWORD})
        assert again.status_code == 200, again.text


def test_a_username_already_taken_is_not_taken_over(invite, client):
    mid, no, phone = existing()
    with SessionLocal() as db:
        db.add(User(username=no, password_hash="x", role="officer"))
        db.commit()
    r = TestClient(app, base_url=BASE_URL).post("/api/auth/signup", json=signup_body(phone=phone, member_no=no))
    assert r.status_code == 201 and r.json()["username"] == f"{no}-2"


@pytest.mark.parametrize("case", ["wrong_number", "wrong_phone", "both_unknown", "already_linked"])
def test_a_failed_claim_says_the_same_thing_whatever_is_wrong(invite, client, case):
    mid, no, phone = existing()
    linked, linked_no, _ = new_member()
    with SessionLocal() as db:
        linked_phone = db.get(Member, linked).phone
        before = db.scalar(select(Member).where(Member.id == mid)).user_id
    over = {"wrong_number": {"phone": phone, "member_no": "M-NOT-A-MEMBER"},
            "wrong_phone": {"phone": fresh_phone(), "member_no": no},
            "both_unknown": {"phone": fresh_phone(), "member_no": "M-NOT-A-MEMBER"},
            "already_linked": {"phone": linked_phone, "member_no": linked_no}}[case]
    r = TestClient(app, base_url=BASE_URL).post("/api/auth/signup", json=signup_body(**over))
    assert r.status_code == 409 and r.json()["detail"] == pilot.CLAIM_REFUSED
    with SessionLocal() as db:
        assert db.get(Member, mid).user_id == before
        assert db.scalar(select(Member.id).where(Member.phone == normalise_phone(over["phone"]))) in (None, mid, linked)


def test_a_claim_needs_the_invite_and_consent_like_any_sign_up(invite, client):
    _, no, phone = existing()
    c = TestClient(app, base_url=BASE_URL)
    assert c.post("/api/auth/signup", json=signup_body(phone=phone, member_no=no, invite_code="wrong")).status_code == 403
    assert c.post("/api/auth/signup", json=signup_body(phone=phone, member_no=no, consent=False)).status_code == 422


def test_a_second_claim_of_the_same_member_loses(invite, client):
    mid, no, phone = existing()
    first = TestClient(app, base_url=BASE_URL).post("/api/auth/signup", json=signup_body(phone=phone, member_no=no))
    assert first.status_code == 201
    second = TestClient(app, base_url=BASE_URL).post("/api/auth/signup", json=signup_body(phone=phone, member_no=no))
    assert second.status_code == 409


def test_someone_new_gets_a_new_member_and_the_registration_form(invite, client):
    r = TestClient(app, base_url=BASE_URL).post("/api/auth/signup", json=signup_body())
    assert r.status_code == 201, r.text
    assert (r.json()["claimed"], r.json()["profile_due"]) == (False, True)


def test_a_known_phone_without_a_member_number_is_refused_as_before(invite, client):
    _, _, phone = existing()
    r = TestClient(app, base_url=BASE_URL).post("/api/auth/signup", json=signup_body(phone=phone))
    assert r.status_code == 409 and "already registered" in r.json()["detail"]


# --- The generated members --------------------------------------------------------------------

PEOPLE = {key: {**p, "joined_on": date(2026, 11, 1) - timedelta(days=30 * p["joined"])}
          for key, p in seed_demo.DEMO_PEOPLE.items()}
NOW = datetime(2026, 11, 4, 9, tzinfo=config.NAIROBI)


def plan_from(respondents, seed=seed_members.SEED):
    return seed_members.generate(respondents, "synthetic", PEOPLE, seed_demo.DEMO_APPLICATIONS, TODAY, NOW,
                                 random.Random(seed))


def synthetic(n=40, seed=7):
    return seed_members.synthetic_respondents(n, random.Random(seed))


def test_the_same_seed_gives_the_same_members():
    assert plan_from(synthetic()) == plan_from(synthetic())


def test_another_seed_gives_other_members():
    assert plan_from(synthetic()) != plan_from(synthetic(), seed=1)


def test_absent_files_fall_back_and_say_so(monkeypatch):
    monkeypatch.setattr(seed_members, "load_central_respondents", lambda: None)
    said = []
    people, source = seed_members.choose_respondents(25, random.Random(1), said.append)
    assert source == "synthetic" and len(people) == 25
    assert "synthetic" in said[0] and "absent" in said[0]


def test_no_frame_and_no_survey_file_means_no_respondents(monkeypatch, tmp_path):
    _, prep, model = seed_members._experiments()
    monkeypatch.setattr(model, "DEFAULT_FRAME", tmp_path / "absent.csv")
    monkeypatch.setattr(prep, "DTA", tmp_path / "absent.dta")
    assert seed_members.load_central_respondents() is None


def test_only_feature_columns_are_ever_read(monkeypatch, tmp_path):
    """Whatever the frame holds, the outcome is not in what comes back."""
    features, _, model = seed_members._experiments()
    columns = [*features.FEATURES, "county", "risk_class", "risk_label", "E2E", "is_central", "indWeight"]
    row = {c: 0 for c in columns} | {"A18": 40, "Sex": "Female", "A20": '"None "', "A21": "Widowed", "NHM": 3,
                                     "county": "Nyeri", "B3Ii": 9000, "risk_class": 2, "risk_label": "High",
                                     "E2E": "Didn't pay at all", "C1_17": "Currently use", "C1_21": "Never used"}
    frame = tmp_path / "frame.csv"
    pd.DataFrame([row, {**row, "county": "Kisumu"}]).to_csv(frame, index=False)
    monkeypatch.setattr(model, "DEFAULT_FRAME", frame)
    read = []
    real = pd.read_csv

    def spying(path, **kw):
        read.append(kw["usecols"])
        return real(path, **kw)
    monkeypatch.setattr(pd, "read_csv", spying)

    got = seed_members.load_central_respondents()

    assert not {"risk_class", "risk_label", "E2E"} & set(read[0])
    assert len(got) == 1                                     # the Kisumu row is not Central Kenya
    assert got[0]["form"] == {"age": 40, "sex": "female", "education": 0, "marital_status": "widowed"}
    assert got[0]["features"]["monthly_income_kes"] == 9000 and got[0]["features"]["sacco_loan_use"] == 2
    assert set(got[0]) == {"form", "features"}
    assert "county" not in json.dumps(got[0])


@pytest.mark.skipif(not (config.EXPERIMENTS_DIR / "02_finaccess_prep/results/modelling_frame.csv").exists(),
                    reason="needs the licensed FinAccess frame")
def test_real_respondents_are_central_kenya_and_faithful():
    everyone = seed_members.load_central_respondents()
    assert len(everyone) == 1685        # prep_profile.json: eval_rows_central
    assert all(16 <= r["form"]["age"] <= 110 for r in everyone)
    assert {r["features"]["sacco_loan_use"] for r in everyone} == {0, 1, 2}
    assert all(r["features"]["monthly_income_kes"] is None or r["features"]["monthly_income_kes"] >= 0 for r in everyone)


def test_loans_and_ledgers_agree_with_each_respondents_answers():
    plan = plan_from(synthetic(150))
    for p in plan.people:
        if not p.key.startswith("finaccess"):
            continue
        statuses = [x.status for x in p.loans]
        assert ledger.sacco_loan_use(statuses) == p.features["sacco_loan_use"]
        recovered = any(e[1] == "guarantee_recovery" for e in p.entries)
        assert recovered == bool(p.features["lost_as_guarantor"]["sacco"]), p.key


def test_generated_people_are_invented_in_the_unused_block():
    plan = plan_from(synthetic(150))
    names = [p.full_name for p in plan.people]
    assert len(set(names)) == len(names)
    assert not set(names) & {"Demo", "Test"}
    assert all(not re.search(r"demo|fictional|practice|test", n, re.I) for n in names)
    assert all(re.fullmatch(r"0700000\d{3}", p.phone) for p in plan.people)
    assert len({p.phone for p in plan.people}) == len(plan.people)
    assert len({p.member_no for p in plan.people}) == len(plan.people)


def test_deposit_histories_follow_income_with_gaps():
    def person(income):
        p = seed_members.Person("k", "M", "N", "0", date(2016, 1, 1), date(1980, 1, 1), {}, {"monthly_income_kes": income})
        seed_members.add_deposits(p, random.Random(11), TODAY)
        return p
    rich, poor = person(100000), person(3000)
    assert rich.deposits() > poor.deposits() * 5
    months = (TODAY.year - 2016) * 12 + TODAY.month
    assert 0 < len(poor.entries) < months                   # there are gaps
    assert all(e[2] > 0 and e[2] % 50 == 0 for e in rich.entries)


def test_every_pledge_comes_from_someone_with_capacity():
    plan = plan_from(synthetic(150))
    people = plan.by_key()
    guaranteed = {}
    for x in plan.loans():
        if x.status == "active":
            for key, amount in x.guarantors:
                guaranteed[key] = guaranteed.get(key, 0) + amount
    for p in plan.people:
        if p.key.startswith("finaccess"):
            assert 2 <= len(p.pledges) <= 3 and p.key not in p.pledges
            for key in p.pledges:
                assert people[key].deposits() - guaranteed.get(key, 0) >= seed_members.MIN_PLEDGE_CAPACITY


def test_every_named_application_reads_its_own_savings_figure_from_the_ledger():
    """The named people's applications say the same as before, because the balance
    on the day each was decided is the figure it was decided on."""
    plan = plan_from(synthetic())
    people = plan.by_key()
    for key in PEOPLE:
        for point in seed_members.checkpoints(key, seed_demo.DEMO_APPLICATIONS, NOW):
            assert people[key].deposits(point.day) == point.kes, (key, point)


@pytest.fixture
def scratch(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'plan.db'}")
    init_db(engine)
    with Session(engine) as db:
        officer = User(username="o1", password_hash="x", role="officer")
        db.add(officer)
        db.flush()
        yield db, officer
    engine.dispose()


def written(db, officer, n=60):
    def ensure(session, spec, actor, user, tag):
        m = Member(member_no=spec["member_no"], full_name=spec["full_name"], phone=spec["phone"],
                   joined_on=spec["joined_on"], seed_tag=tag)
        session.add(m)
        session.flush()
        return m
    plan = plan_from(synthetic(n))
    res = seed_members.write_plan(db, plan, {}, {"officer1": officer, "officer2": officer}, None, officer,
                                  utcnow(), "test", ensure)
    return plan, res


def test_a_written_plan_reads_back_as_the_respondents_answers(scratch):
    db, officer = scratch
    plan, res = written(db, officer)
    assert res["members"] == len(plan.people) and res["entries"] > 1000
    tags = {m.seed_tag.split(":")[1]: m for m in db.scalars(select(Member))}
    for p in plan.people:
        if not p.key.startswith("finaccess"):
            continue
        got = profiles.profile_features(db, tags[p.key], today=TODAY)
        f = p.features
        assert got.features["age"] == p.form["age"], p.key
        for key in ("household_size", "children", "monthly_income_kes", "agri_income_kes", "chama_loan_use"):
            assert got.features[key] == f[key], (p.key, key)
        assert got.features["sacco_loan_use"] == f["sacco_loan_use"], p.key
        assert got.features["lost_as_guarantor"] == f["lost_as_guarantor"], p.key
        assert got.provenance["sacco_loan_use"] == "records"


def test_no_written_account_ever_goes_negative(scratch):
    db, officer = scratch
    written(db, officer)
    running: dict[int, int] = {}
    entries = db.execute(select(AccountEntry.account_id, AccountEntry.amount_kes)
                         .order_by(AccountEntry.account_id, AccountEntry.posted_at, AccountEntry.amount_kes.desc()))
    for account, amount in entries:
        running[account] = running.get(account, 0) + amount
        assert running[account] >= 0, account
    assert db.scalar(select(MemberAccount.id)) is not None


def test_a_written_profile_has_a_seed_history_and_source(scratch):
    db, officer = scratch
    plan, _ = written(db, officer)
    profile = db.scalars(select(MemberProfile)).first()
    assert {getattr(profile, f"{g}_source") for g in ("personal", "income")} <= {"seed", "officer_verified"}
    assert db.scalar(select(MemberProfileHistory).where(MemberProfileHistory.member_id == profile.member_id)).change == "seed"
    assert len(db.scalars(select(MemberProfile)).all()) == len(plan.people)


def build_demo(path, cwd):
    r = subprocess.run([sys.executable, str(config.SCRIPTS_DIR / "seed_demo.py"), "--demo-db", str(path)],
                       capture_output=True, text=True, cwd=cwd)
    assert r.returncode == 0, r.stderr
    return r.stdout


def dump(path):
    """Everything generated, without the moments the two builds really ran at."""
    con = sqlite3.connect(path)
    out = {
        "members": con.execute("SELECT member_no, full_name, phone, joined_on, seed_tag FROM members ORDER BY id").fetchall(),
        "profiles": con.execute("SELECT member_id, date_of_birth, sex, education, marital_status, household_size, "
                                "children, monthly_income_kes, agri_income_kes, income_sources, chama_loan_use, "
                                "lost_as_guarantor_chama, income_source FROM member_profiles ORDER BY member_id").fetchall(),
        "entries": con.execute("SELECT account_id, entry_type, amount_kes, date(posted_at), reference FROM account_entries "
                               "ORDER BY account_id, reference").fetchall(),
        "loans": con.execute("SELECT member_id, application_id, principal_kes, disbursed_on, term_months, "
                             "monthly_instalment_kes, status FROM loan_accounts ORDER BY id").fetchall(),
        "pledges": con.execute("SELECT borrower_member_id, guarantor_member_id, status FROM guarantor_pledges ORDER BY id").fetchall(),
    }
    con.close()
    return out


@needs_classifier
def test_two_demo_builds_hold_the_same_members_and_the_rule_is_unchanged(tmp_path):
    out = build_demo(tmp_path / "a.db", tmp_path)
    build_demo(tmp_path / "b.db", tmp_path)
    assert "159 members with profiles" in out
    a = dump(tmp_path / "a.db")
    assert a == dump(tmp_path / "b.db")
    assert len(a["members"]) == 159 and len(a["pledges"]) >= 2 * 150

    engine = create_engine(f"sqlite:///{tmp_path / 'a.db'}")
    with Session(engine) as db:
        apps = db.scalars(select(LoanApplication)).all()
        savings = ledger.rule_savings(db, apps)
        assert all(savings[x.id].from_ledger and savings[x.id].kes == x.sacco_savings_kes for x in apps)
        # Each named person's stored features agree with what the records now derive,
        # bar Peter, whose loan was paid out after the interview that recorded 0.
        tags = {m.seed_tag.split(":")[1]: m for m in db.scalars(select(Member))}
        for key, p in seed_demo.DEMO_PEOPLE.items():
            got = profiles.profile_features(db, tags[key]).features
            assert got["lost_as_guarantor"] == p["features"]["lost_as_guarantor"], key
            assert got["sacco_loan_use"] == (2 if key == "peter" else p["features"]["sacco_loan_use"]), key
        linked = db.scalar(select(LoanAccount).where(LoanAccount.application_id.is_not(None)))
        assert linked.member_id == tags["peter"].id and comparator.MIN_GUARANTORS == 2
        caps = ledger.capacities(db, [tags["john"].id, tags["david"].id])
        assert caps[tags["john"].id].guaranteed_kes == 30000    # half of Peter's loan
        assert caps[tags["david"].id].guaranteed_kes == 40000   # and half of John's old one too
    engine.dispose()
