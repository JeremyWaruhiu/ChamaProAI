"""The presenter view and the things around it: staff see the whole record and members see
none of it; how a conversation came out; the audio a browser records; the session cookie on
a tunnel and on localhost; the stage of a reply; carrying on after a reload; warming the ASR;
and resetting the demo's two members. Real classifier for the seed's people, as in
test_conversation; no Gemini, no voice model."""
import hashlib
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest
from sqlalchemy import select

from chamapro import config
from chamapro.api import auth, ledger
from chamapro.api import pipeline as pl
from chamapro.api.db import AuditLog, LoanAccount, Member, SessionLocal, User
from chamapro.api.main import app
from chamapro.conversation import service
from conftest import needs_classifier, needs_ffmpeg
from fastapi.testclient import TestClient
from test_conversation import (WANJIRU_EN, begin, conversation_with, ears, people, recorded, said,  # noqa: F401
                               say, transactional)
from test_decisions import borrower, model  # noqa: F401  (model is a fixture)


def wanjiru_through(member, script=WANJIRU_EN):
    cid = begin(member)["conversation"]["id"]
    out = None
    for words, _ in script:
        out = say(member, cid, words)
    return cid, out


# --- Who sees what --------------------------------------------------------------------------

def test_only_staff_reach_the_presenter_view(client, admin_client, anon_client, model):
    mid, member, _ = borrower()
    cid, _ = conversation_with(member, "yes", "yes", "Forty thousand for school fees", "twelve months")
    url = f"/api/present/conversations/{cid}"
    assert client.get(url).status_code == 200 and admin_client.get(url).status_code == 200
    assert client.get("/api/present/conversations").status_code == 200
    assert member.get(url).status_code == 403 and member.get("/api/present/conversations").status_code == 403
    assert member.get(f"{url}/turns/1/audio").status_code == 403
    assert anon_client.get(url).status_code == 401
    assert client.get("/api/present/conversations/999999").status_code == 404


def test_staff_see_the_class_the_probabilities_the_shap_values_and_the_trace(client, model):
    mid, member, guarantors = borrower()
    cid, out = conversation_with(member, "yes", "yes", "Forty thousand for school fees", "twelve months")
    detail = client.get(f"/api/present/conversations/{cid}").json()
    explained = [t["explain"] for t in detail["turns"] if t["explain"]]
    assert len(explained) == 2 and explained[-1] == recorded(out)
    last = explained[-1]
    assert last["risk_class"] == "Low" and set(last["probabilities"]) == {"Low", "Medium", "High"}
    assert last["contributions"] and {"feature", "value", "shap", "in_favour"} <= set(last["contributions"][0])
    assert last["trace"]["policy_version"] == config.POLICY_BASE_VERSION
    assert last["features"]["monthly_income_kes"] is not None
    assert last["provenance"]["term_months"] == "conversation"
    capacity = next(c for c in last["trace"]["checks"] if c["check"] == "guarantor_capacity")
    assert len(capacity["values"]["guarantors"]) == len(guarantors)     # a guarantor's figures: staff only


@needs_classifier
def test_the_top_ten_are_kept_and_the_c2_moment_moves_the_bars(client, people):
    ids, clients = people
    member = clients["njeri"]
    cid = begin(member)["conversation"]["id"]
    for words in ("Yes I agree", "Yes it is", "Sixty thousand for school fees", "Twelve months"):
        before = say(member, cid, words)
    after = say(member, cid, "No, it is twenty two thousand now")
    was, now = recorded(before), recorded(after)
    assert was["risk_class"] == "Medium" and now["risk_class"] == "Low"
    assert len(was["contributions"]) == 10 and len(now["contributions"]) == 10
    assert was["provenance"]["monthly_income_kes"] == "declared" and now["provenance"]["monthly_income_kes"] == "conversation"
    assert {c["feature"]: c["shap"] for c in was["contributions"]} != {c["feature"]: c["shap"] for c in now["contributions"]}


# --- How it came out ------------------------------------------------------------------------

@needs_classifier
def test_the_outcome_gives_the_loan_and_the_balance_around_it(client, people):
    ids, clients = people
    member = clients["wanjiru"]
    with SessionLocal() as db:
        before = ledger.balances(db, ids["wanjiru"])["transactional"]
    cid, end = wanjiru_through(member)
    outcome = end["outcome"]
    assert outcome["decision"] == "approved" and outcome["amount_kes"] == 40000 and outcome["term_months"] == 12
    assert outcome["instalment_kes"] == 3554 and outcome["guarantors"] == ["Lucy Nduta", "Anne Wairimu"]
    assert outcome["balance_before_kes"] == before and outcome["balance_after_kes"] == before + 40000
    assert "ledger" not in outcome      # the entry itself is for staff
    assert member.get(f"/api/conversations/{cid}").json()["outcome"] == outcome
    staff = client.get(f"/api/present/conversations/{cid}").json()["outcome"]
    assert staff["ledger"]["reference"] and staff["ledger"]["amount_kes"] == 40000
    assert staff["ledger"]["entry_type"] == "loan_disbursement"


def test_an_open_conversation_has_no_outcome_and_one_with_nothing_decided_says_so(client, model):
    _, member, _ = borrower()
    start = begin(member)
    cid = start["conversation"]["id"]
    assert member.get(f"/api/conversations/{cid}").json()["outcome"] is None
    out = say(member, cid, "no")
    assert out["outcome"]["decision"] == "none" and out["outcome"]["application_id"] is None


def test_a_referral_says_referred_with_no_loan_figures(client, model):
    model["risk"] = "High"
    _, member, _ = borrower()
    _, out = conversation_with(member, "yes", "yes", "Forty thousand for school fees", "twelve months")
    assert out["outcome"]["decision"] == "referred" and out["outcome"]["requested_kes"] == 40000
    assert out["outcome"]["amount_kes"] is None and out["outcome"]["balance_after_kes"] is None


# --- Carrying on, and what a reply is doing ---------------------------------------------------

def test_the_current_conversation_is_found_after_a_reload(client, model):
    _, member, _ = borrower()
    assert member.get("/api/conversations/current").json() is None
    cid, _ = conversation_with(member, "yes")
    current = member.get("/api/conversations/current").json()
    assert current["conversation"]["id"] == cid and current["conversation"]["state"] == "G2"
    assert [t["speaker"] for t in current["turns"]] == ["bot", "bot", "member", "bot"]
    assert member.get("/api/conversations/current").json()["conversation"]["busy"] is False
    say(member, cid, "no")      # a bare no: asked again, so it is still open
    assert member.get("/api/conversations/current").json() is not None
    other = borrower()[1]
    assert other.get("/api/conversations/current").json() is None
    assert other.get(f"/api/conversations/{cid}/stage").status_code == 404


def test_stages_come_and_go_with_a_reply(client, model, monkeypatch):
    _, member, _ = borrower()
    cid = begin(member)["conversation"]["id"]
    assert member.get(f"/api/conversations/{cid}/stage").json() == {"stage": None, "busy": False}
    seen = []
    real = service.machine.advance

    def spy(db, conv, *a, **k):
        seen.append(service.stage_of(conv.id))
        return real(db, conv, *a, **k)
    monkeypatch.setattr(service.machine, "advance", spy)
    say(member, cid, "yes")
    assert seen == ["deciding"] and service.stage_of(cid) is None


# --- What a browser records --------------------------------------------------------------------

@needs_ffmpeg
@pytest.mark.parametrize("args, name, content_type", [
    (["-c:a", "libopus", "-f", "webm"], "reply.webm", "audio/webm;codecs=opus"),
    (["-c:a", "aac", "-f", "mp4", "-movflags", "+faststart"], "reply.m4a", "audio/mp4"),
])
def test_the_browsers_formats_are_converted(client, model, ears, tmp_path, args, name, content_type):  # noqa: F811
    src = tmp_path / name
    subprocess.run(["ffmpeg", "-nostdin", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=220:duration=1", *args,
                    str(src)], check=True)
    _, member, _ = borrower()
    cid = begin(member, "kik")["conversation"]["id"]
    with src.open("rb") as f:
        r = member.post(f"/api/conversations/{cid}/reply", files={"audio": (name, f, content_type)})
    assert r.status_code == 200, r.text
    turn = r.json()["member_turn"]
    assert turn["input_mode"] == "voice" and turn["latency_ms"]["asr"] is not None
    detail = client.get(f"/api/present/conversations/{cid}").json()
    heard = next(t for t in detail["turns"] if t["speaker"] == "member")
    audio = client.get(heard["audio_url"])
    assert audio.status_code == 200 and audio.headers["content-type"] == "audio/wav" and audio.content[:4] == b"RIFF"


def test_with_speech_off_there_is_no_audio_for_a_bot_turn(client, model):
    _, member, _ = borrower()
    cid = begin(member)["conversation"]["id"]
    bot = client.get(f"/api/present/conversations/{cid}").json()["turns"][0]
    assert bot["audio_url"] is None
    assert client.get(f"/api/present/conversations/{cid}/turns/1/audio").status_code == 404


# --- The session cookie ---------------------------------------------------------------------

def cookie_of(response) -> str:
    return next(v for k, v in response.headers.multi_items() if k == "set-cookie" and v.startswith(auth.COOKIE))


def sign_in(c):
    from conftest import PASSWORDS
    return c.post("/api/auth/login", json={"username": "officer1", "password": PASSWORDS["officer1"]})


def test_the_cookie_on_plain_localhost_works_without_https(client):
    c = TestClient(app, base_url="http://localhost:8000")   # no "with": that would run the app's shutdown, and stop the worker
    r = sign_in(c)
    assert r.status_code == 200
    cookie = cookie_of(r).lower()
    assert "secure" not in cookie and "samesite=strict" in cookie and "httponly" in cookie and "path=/api" in cookie
    assert c.get("/api/auth/me").status_code == 200


def test_the_cookie_behind_the_tunnel_is_secure_and_is_sent_back(client):
    """As uvicorn sees a request from cloudflared: its Host, and https in X-Forwarded-Proto."""
    c = TestClient(app, base_url="https://quick-demo.trycloudflare.com", headers={"X-Forwarded-Proto": "https"})
    r = sign_in(c)
    assert r.status_code == 200
    cookie = cookie_of(r).lower()
    assert "secure" in cookie and "samesite=strict" in cookie and "httponly" in cookie
    assert c.get("/api/auth/me").status_code == 200


# --- Warming the ASR ---------------------------------------------------------------------------

def test_warming_transcribes_a_clip_and_says_so(client, monkeypatch, tmp_path, ears):  # noqa: F811
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)       # no corpus here: it makes its own clip
    pl._warmed.clear()
    assert pl.asr_status()["kik"]["warmed"] is False
    assert list(pl.warm_asr()) == ["kik"]
    assert pl.asr_status()["kik"]["warmed"] is True
    assert client.get("/api/health").json()["asr"]["kik"]["warmed"] is True
    pl._warmed.clear()


def test_a_warming_failure_is_only_logged(monkeypatch, caplog):
    def fails(*a, **k):
        raise RuntimeError("no GPU")
    monkeypatch.setattr(pl, "warm_asr", fails)
    monkeypatch.setattr(config, "ASR_WARM", True)
    threads = []
    real = pl.threading.Thread

    def keep(*a, **k):
        t = real(*a, **k)
        threads.append(t)
        return t
    monkeypatch.setattr(pl.threading, "Thread", keep)
    pl.warm_asr_in_background()
    threads[0].join(5)
    assert "could not be warmed" in caplog.text


# --- Rehearsing again ---------------------------------------------------------------------------

def tag_as_demo(ids):
    with SessionLocal() as db:
        for key, tag in (("wanjiru", "demo-db:wanjiru"), ("njeri", "demo-db:njeri")):
            db.get(Member, ids[key]).seed_tag = tag
        db.commit()


@pytest.fixture
def demo_people(people):
    """Only one set of demo tags at a time; these tests clear theirs."""
    ids, clients = people
    tag_as_demo(ids)
    yield ids, clients
    with SessionLocal() as db:
        for key in ("wanjiru", "njeri"):
            db.get(Member, ids[key]).seed_tag = None
        db.commit()


def test_without_demo_members_there_is_nothing_to_reset(admin_client):
    assert admin_client.get("/api/admin/demo-reset").json() == {"available": False, "people": []}
    assert admin_client.post("/api/admin/demo-reset").status_code == 404


def test_only_an_admin_can_reset(client, anon_client):
    assert client.post("/api/admin/demo-reset").status_code == 403
    assert client.get("/api/admin/demo-reset").status_code == 403
    assert anon_client.post("/api/admin/demo-reset").status_code == 401


@needs_classifier
def test_the_demo_can_be_rehearsed_again_and_again(admin_client, client, demo_people):
    ids, clients = demo_people
    wanjiru, njeri = clients["wanjiru"], clients["njeri"]
    for _ in range(2):
        cid, end = wanjiru_through(wanjiru)
        assert end["outcome"]["decision"] == "approved" and end["outcome"]["balance_before_kes"] == 0
        assert transactional(ids["wanjiru"]) == 40000
        left_open = begin(njeri)["conversation"]["id"]      # Njeri left mid-way

        status = admin_client.get("/api/admin/demo-reset").json()
        people_now = {p["full_name"]: p for p in status["people"]}
        assert status["available"] and people_now["Wanjiru Kamau"]["active_loans"] == 1
        assert people_now["Njeri Mwangi"]["open_conversations"] == 1

        r = admin_client.post("/api/admin/demo-reset")
        assert r.status_code == 200, r.text
        result = r.json()
        assert result["loans_reversed"] == 1 and result["conversations_closed"] == 1 and result["problems"] == []
        assert transactional(ids["wanjiru"]) == 0
        assert njeri.get(f"/api/conversations/{left_open}").json()["conversation"]["status"] == "abandoned"
        assert wanjiru.get(f"/api/conversations/{cid}").json()["outcome"]["decision"] == "reversed"
        assert all(p["active_loans"] == 0 and p["open_conversations"] == 0 for p in result["people"])

        again = admin_client.post("/api/admin/demo-reset").json()      # harmless
        assert again["loans_reversed"] == 0 and again["conversations_closed"] == 0
    with SessionLocal() as db:
        assert db.scalar(select(AuditLog).where(AuditLog.action == "demo.reset").order_by(AuditLog.id.desc())) is not None
        lucy = db.get(Member, ids["lucy"])
        assert ledger.capacities(db, {lucy.id})[lucy.id].guaranteed_kes == 0


@needs_classifier
def test_a_referral_and_its_booking_are_closed_too(admin_client, demo_people):
    ids, clients = demo_people
    njeri = clients["njeri"]
    cid = begin(njeri)["conversation"]["id"]
    for words in ("Yes I agree", "Yes it is", "Sixty thousand for school fees", "Twelve months"):
        say(njeri, cid, words)
    out = say(njeri, cid, "No, it is thirty thousand now")
    assert said(out) == ["O3", "END"]
    assert begin(njeri, status=409)
    result = admin_client.post("/api/admin/demo-reset").json()
    assert result["applications_closed"] == 1
    assert begin(njeri)["conversation"]["state"] == "CONSENT"     # free to start again


@needs_classifier
def test_a_loan_whose_money_has_gone_is_reported_not_forced(admin_client, client, demo_people):
    ids, clients = demo_people
    wanjiru_through(clients["wanjiru"])
    with SessionLocal() as db:
        ledger.post_entry(db, ids["wanjiru"], "transactional", "withdrawal", -40000, "DRAWN-1")
        db.commit()
    result = admin_client.post("/api/admin/demo-reset").json()
    assert result["loans_reversed"] == 0 and "no longer in the transactional account" in result["problems"][0]
    with SessionLocal() as db:
        assert db.scalar(select(LoanAccount).where(LoanAccount.member_id == ids["wanjiru"])
                         .order_by(LoanAccount.id.desc()).limit(1)).status == "active"


# --- Watching a reply being worked on -------------------------------------------------------------

def test_staff_and_the_member_see_a_reply_while_it_is_worked_on(client, model, monkeypatch):
    _, member, _ = borrower()
    cid = begin(member)["conversation"]["id"]
    entered, go_on = threading.Event(), threading.Event()
    real = service.machine.advance

    def waits(*a, **k):
        entered.set()
        assert go_on.wait(10)
        return real(*a, **k)
    monkeypatch.setattr(service.machine, "advance", waits)
    worker = threading.Thread(target=say, args=(member, cid, "yes"))
    worker.start()
    try:
        assert entered.wait(10)
        row = client.get(f"/api/present/conversations/{cid}").json()["row"]
        assert row["busy"] is True and row["stage"] == "deciding"
        listed = next(r for r in client.get("/api/present/conversations").json() if r["id"] == cid)
        assert listed["busy"] is True
        assert member.get(f"/api/conversations/{cid}/stage").json() == {"stage": "deciding", "busy": True}
    finally:
        go_on.set()
        worker.join(10)
    assert client.get(f"/api/present/conversations/{cid}").json()["row"]["busy"] is False


# --- Warming the demo -----------------------------------------------------------------------------

@needs_classifier
def test_warm_demo_runs_the_exact_answers_on_a_copy_and_leaves_the_source_alone(tmp_path):
    """Both conversations in both languages, on a real --demo-db build: what the script
    expects the bot to say has to be what it says. No speech and no ASR here."""
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    source = tmp_path / "demo.db"
    env = {**os.environ, "STORAGE_BACKEND": "local", "CHAMAPRO_UPLOADS": str(tmp_path / "uploads")}
    for name in ("DATABASE_URL", "CHAMAPRO_DB"):
        env.pop(name, None)
    subprocess.run([sys.executable, str(scripts / "seed_demo.py"), "--demo-db", str(source)], check=True, env=env,
                   capture_output=True, timeout=300)
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    done = subprocess.run([sys.executable, str(scripts / "warm_demo.py"), "--source", str(source), "--no-speech", "--no-asr"],
                          env={**env, "TTS_CACHE_DIR": str(tmp_path / "tts")}, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stdout + done.stderr
    for line in ("Wanjiru Kamau, en", "Wanjiru Kamau, kik", "Njeri Mwangi, en", "Njeri Mwangi, kik", "is as it was"):
        assert line in done.stdout
    assert hashlib.sha256(source.read_bytes()).hexdigest() == before


@needs_classifier
def test_warm_demo_builds_its_own_database_and_never_opens_the_one_in_the_environment(tmp_path):
    """DATABASE_URL here is what .env holds on the day: nothing is listening at it, and it must not matter."""
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    env = {**os.environ, "DATABASE_URL": "postgresql://nobody:secret@127.0.0.1:1/supabase", "STORAGE_BACKEND": "supabase",
           "TTS_CACHE_DIR": str(tmp_path / "tts")}
    done = subprocess.run([sys.executable, str(scripts / "warm_demo.py"), "--no-speech", "--no-asr"], env=env, capture_output=True,
                          text=True, timeout=300)
    assert done.returncode == 0, done.stdout + done.stderr
    assert "built from the seed" in done.stdout
    for line in ("Wanjiru Kamau, en", "Wanjiru Kamau, kik", "Njeri Mwangi, en", "Njeri Mwangi, kik"):
        assert line in done.stdout


def test_warm_demo_stops_with_an_instruction_on_a_missing_database(tmp_path):
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    done = subprocess.run([sys.executable, str(scripts / "warm_demo.py"), "--source", str(tmp_path / "none.db")],
                          capture_output=True, text=True, timeout=120)
    assert done.returncode != 0 and "seed_demo.py --demo-db" in done.stderr


# --- The poll, and its tag -------------------------------------------------------------------

def test_the_presenter_poll_makes_the_refusals_it_always_made(client, anon_client, model):
    _, member, _ = borrower()
    cid = begin(member)["conversation"]["id"]
    url = f"/api/present/conversations/{cid}"
    assert anon_client.get(url).status_code == 401
    assert member.get(url).status_code == 403
    assert client.get("/api/present/conversations/999999").status_code == 404
    r = client.get(url)
    assert r.status_code == 200 and r.headers["etag"] and "no-cache" in r.headers["cache-control"]
    assert member.get(url, headers={"If-None-Match": r.headers["etag"]}).status_code == 403
    assert anon_client.get(url, headers={"If-None-Match": r.headers["etag"]}).status_code == 401


def test_an_expired_session_gets_no_poll(client, model):
    from chamapro.api.db import AuthSession
    from chamapro.api.db import utcnow as now
    _, member, _ = borrower()
    cid = begin(member)["conversation"]["id"]
    from conftest import add_user, signed_in, PASSWORDS
    PASSWORDS["expiring"] = "x" * 20
    add_user("expiring", PASSWORDS["expiring"])
    who = signed_in("expiring")
    with SessionLocal() as db:
        for row in db.scalars(select(AuthSession).where(AuthSession.user_id == db.scalar(select(User.id).where(User.username == "expiring")))):
            row.expires_at = now()
        db.commit()
    assert who.get(f"/api/present/conversations/{cid}").status_code == 401


def test_the_tag_moves_with_anything_that_changes_what_the_screen_shows(client, model):
    mid, member, _ = borrower()
    cid = begin(member)["conversation"]["id"]
    url = f"/api/present/conversations/{cid}"
    tag = lambda: client.get(url).headers["etag"]     # noqa: E731
    first = tag()
    assert tag() == first
    for words in ("yes", "yes", "Forty thousand for school fees", "twelve months", "yes"):
        say(member, cid, words)
        assert tag() != first
        first = tag()
    done = client.get(url).json()
    assert done["outcome"]["decision"] == "approved" and not done["outcome"]["review_requested"]
    from test_decisions import key
    r = member.post(f"/api/self-service/applications/{done['application_id']}/review", headers=key())
    assert r.status_code == 201, r.text
    assert tag() != first               # asked for a review: the card says so, and nothing else about it moved
    first = tag()
    assert client.get(url).json()["outcome"]["review_requested"] is True
    with SessionLocal() as db:
        loan = db.scalar(select(LoanAccount).where(LoanAccount.member_id == mid))
    r = client.post(f"/api/loans/{loan.id}/reverse", headers=key(), json={"reason": "asked by the member"})
    assert r.status_code == 200, r.text
    assert tag() != first
    assert client.get(url).json()["outcome"]["decision"] == "reversed"


def test_the_tag_moves_while_a_reply_is_worked_on(client, model, monkeypatch):
    _, member, _ = borrower()
    cid = begin(member)["conversation"]["id"]
    url = f"/api/present/conversations/{cid}"
    before = client.get(url).headers["etag"]
    entered, go_on = threading.Event(), threading.Event()
    real = service.machine.advance

    def waits(*a, **k):
        entered.set()
        assert go_on.wait(10)
        return real(*a, **k)
    monkeypatch.setattr(service.machine, "advance", waits)
    worker = threading.Thread(target=say, args=(member, cid, "yes"))
    worker.start()
    try:
        assert entered.wait(10)
        during = client.get(url, headers={"If-None-Match": before})
        assert during.status_code == 200 and during.json()["row"]["busy"] is True and during.json()["row"]["stage"] == "deciding"
    finally:
        go_on.set()
        worker.join(10)


# --- If the database is not there ---------------------------------------------------------------

@pytest.mark.parametrize("url, words", [("postgresql://u:secret@127.0.0.1:1/x", "cannot reach its database")])
def test_a_server_with_no_database_says_so_in_one_line_and_stops(url, words, tmp_path):
    env = {**os.environ, "DATABASE_URL": url, "STORAGE_BACKEND": "local", "CHAMAPRO_UPLOADS": str(tmp_path), "TTS_ENABLED": "0",
           "ASR_WARM": "0", "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")}
    done = subprocess.run([sys.executable, "-m", "uvicorn", "chamapro.api.main:app", "--port", "0"], env=env, capture_output=True,
                          text=True, timeout=120)
    assert done.returncode == 1
    assert "Traceback" not in done.stderr and "Traceback" not in done.stdout
    lines = [line for line in done.stderr.splitlines() if words in line]
    assert len(lines) == 1 and "127.0.0.1" in lines[0] and "secret" not in done.stderr + done.stdout
