"""scripts/seed_demo.py: a complete demo interview without running Whisper."""
import csv
import json
import re
import secrets
import sqlite3
import subprocess
import sys
import uuid
from datetime import date
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient
from sqlalchemy import select

import seed_demo  # scripts/ is on sys.path via chamapro.api.pipeline
from chamapro import config
from chamapro.api import auth
from chamapro.api import self_service
from chamapro.api.db import (APPLICATION_STATUSES, Applicant, AuditLog, Interview, LoanApplication,
                             Member, Response, SessionLocal, User)
from chamapro.api.main import app

from conftest import BASE_URL, fresh_phone, needs_classifier, uploads


@pytest.fixture
def corpus(tmp_path):
    """A 5-clip stand-in for data/asr_paza.csv + data/audio_16k/."""
    audio = tmp_path / "audio_16k"
    audio.mkdir()
    rows = []
    for n, domain, text in [(1, "household", "njeka kwa wanjiru"),
                            (2, "household", "ndi wa miaka mirongo ina"),
                            (6, "income", "njendagia iria"),
                            (7, "income", ""),            # ASR produced nothing
                            (16, "assets", "ndi na ng'ombe igiri")]:
        cid = f"S01_clean_{n:03d}"
        sf.write(str(audio / f"{cid}.wav"), np.zeros(8000), 16000, subtype="PCM_16")
        rows.append({"id": cid, "sentence_no": n, "domain": domain,
                     "hypothesis": text, "asr_seconds": 35.5})
    path = tmp_path / "asr.csv"
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return path, audio, rows


@pytest.fixture
def name():
    """Applicant name and seed tag in one (tests share a database)."""
    return f"Applicant {uuid.uuid4().hex[:8]}"


def test_seed_creates_a_transcribed_interview(client, corpus, name, state):
    csv_path, audio, rows = corpus

    res = seed_demo.seed(csv_path, audio, name, tag=name)

    assert (res.created, res.added, res.total) == (True, 5, 5)
    st = state(res.interview_id)
    assert st["applicant"]["name"] == name and st["status"] == "open"
    assert (st["question_set"], st["language"], st["mode"]) == ("v1", "kik", "live")
    assert st["counts"] == {"queued": 0, "transcribing": 0, "transcribed": 5, "failed": 0}
    for resp, row in zip(st["responses"], rows):
        assert resp["sentence_no"] == row["sentence_no"]
        assert resp["domain"] == row["domain"]
        assert resp["transcript"] == resp["transcript_asr"] == row["hypothesis"]
        assert resp["asr_model"] == seed_demo.CSV_ASR_MODEL
        assert resp["asr_seconds"] == 35.5 and resp["duration_s"] == 0.5
        assert resp["edited"] is False and resp["translation"] is None
        assert resp["source"] == "audio"


def test_seed_copies_audio_into_uploads(client, corpus, name, state):
    csv_path, audio, _ = corpus
    res = seed_demo.seed(csv_path, audio, name, tag=name)
    ids = [r["id"] for r in state(res.interview_id)["responses"]]
    assert uploads(res.interview_id) == sorted(
        f"response_{i}_s{n:02d}.wav" for i, n in zip(ids, (1, 2, 6, 7, 16)))


def test_seed_is_idempotent(client, corpus, name, state):
    csv_path, audio, _ = corpus
    first = seed_demo.seed(csv_path, audio, name, tag=name)
    before = state(first.interview_id)

    again = seed_demo.seed(csv_path, audio, name, tag=name)

    assert (again.interview_id, again.created, again.added, again.total) == \
        (first.interview_id, False, 0, 5)
    assert state(first.interview_id) == before
    assert len(uploads(first.interview_id)) == 5
    assert sum(x["applicant_name"] == name for x in client.get("/api/interviews").json()) == 1


def test_seed_keeps_reviewer_edits(client, corpus, name, state):
    csv_path, audio, _ = corpus
    res = seed_demo.seed(csv_path, audio, name, tag=name)
    rid = state(res.interview_id)["responses"][3]["id"]          # the blank one
    client.patch(f"/api/responses/{rid}", json={"transcript": "typed by officer"})

    seed_demo.seed(csv_path, audio, name, tag=name)

    assert state(res.interview_id)["responses"][3]["transcript"] == "typed by officer"


def test_rerecord_deletes_the_copy_and_reseed_restores_it(client, corpus, name, state):
    csv_path, audio, _ = corpus
    res = seed_demo.seed(csv_path, audio, name, tag=name)
    rid = state(res.interview_id)["responses"][0]["id"]

    assert client.delete(f"/api/responses/{rid}").status_code == 200
    assert (audio / "S01_clean_001.wav").exists()                 # corpus untouched
    assert len(uploads(res.interview_id)) == 4

    again = seed_demo.seed(csv_path, audio, name, tag=name)

    assert (again.interview_id, again.created, again.added, again.total) == \
        (res.interview_id, False, 1, 5)
    assert [x["sentence_no"] for x in state(res.interview_id)["responses"]] == [1, 2, 6, 7, 16]
    assert len(uploads(res.interview_id)) == 5


def test_seed_after_assessment_starts_a_fresh_demo(client, corpus, name, monkeypatch):
    from chamapro.api.db import Interview, SessionLocal
    csv_path, audio, _ = corpus
    first = seed_demo.seed(csv_path, audio, name, tag=name)
    with SessionLocal() as db:                       # as if assessed during a rehearsal
        db.get(Interview, first.interview_id).status = "assessed"
        db.commit()

    fresh = seed_demo.seed(csv_path, audio, name, tag=name)

    assert fresh.created and fresh.interview_id != first.interview_id
    assert (fresh.added, fresh.total) == (5, 5)
    assert seed_demo.seed(csv_path, audio, name, tag=name).interview_id == fresh.interview_id


def test_missing_clip_writes_nothing(client, corpus, name):
    csv_path, audio, _ = corpus
    (audio / "S01_clean_006.wav").unlink()
    before = client.get("/api/interviews").json()

    with pytest.raises(FileNotFoundError, match="S01_clean_006.wav"):
        seed_demo.seed(csv_path, audio, name, tag=name)

    assert client.get("/api/interviews").json() == before


def test_cli_reports_and_is_idempotent(client, corpus, name):
    csv_path, audio, _ = corpus
    cmd = [sys.executable, str(config.SCRIPTS_DIR / "seed_demo.py"),
           "--csv", str(csv_path), "--audio", str(audio), "--name", name, "--tag", name]
    first = subprocess.run(cmd, capture_output=True, text=True, check=True)
    second = subprocess.run(cmd, capture_output=True, text=True, check=True)
    assert "created Kikuyu interview" in first.stdout and "with 5 responses" in first.stdout
    assert "already complete; nothing to do" in second.stdout
    assert str(config.DB_PATH) in second.stdout              # wrote to the test database

    bad = subprocess.run(cmd[:2] + ["--csv", str(csv_path.with_name("nope.csv")),
                                    "--name", name, "--tag", name], capture_output=True, text=True)
    assert bad.returncode != 0 and "nothing written" in bad.stderr


# "  <login> <password>" as the seeder prints each new login.
LOGIN_LINE = r"^  ([a-z]\.[a-z]+\S*)\s+(\S+)$"

REAL_CSV = config.DATA_DIR / "asr_paza.csv"
REAL_AUDIO = config.DATA_DIR / "audio_16k"


@pytest.mark.skipif(not (REAL_CSV.exists() and REAL_AUDIO.exists()),
                    reason="needs data/asr_paza.csv and data/audio_16k/ (not in the repo)")
def test_real_corpus_seeds_all_40(client, name, state):
    res = seed_demo.seed(REAL_CSV, REAL_AUDIO, name, tag=name)
    st = state(res.interview_id)
    assert res.total == 40 and st["counts"]["transcribed"] == 40
    assert [x["sentence_no"] for x in st["responses"]] == list(range(1, 41))
    assert len(uploads(res.interview_id)) == 40


# --- English practice interview ----------------------------------------------

def test_seed_practice_creates_an_english_practice_interview(client, name, state):
    res = seed_demo.seed_practice(name, tag=name)

    assert (res.created, res.added, res.total) == (True, 8, 8)
    st = state(res.interview_id)
    assert (st["question_set"], st["language"], st["mode"], st["status"]) == ("v2", "en", "practice", "open")
    assert st["applicant"] == {"id": st["applicant"]["id"], "name": name, **seed_demo.PRACTICE_FORM}
    assert st["counts"] == {"queued": 0, "transcribing": 0, "transcribed": 8, "failed": 0}
    assert [r["sentence_no"] for r in st["responses"]] == list(range(1, 9))
    assert all(r["source"] == "typed" and r["transcript"] == seed_demo.PRACTICE_ANSWERS[r["sentence_no"]]
               for r in st["responses"])
    assert uploads(res.interview_id) == []                     # no audio at all


def test_seed_practice_is_idempotent(client, name, state):
    first = seed_demo.seed_practice(name, tag=name)
    before = state(first.interview_id)
    again = seed_demo.seed_practice(name, tag=name)
    assert (again.interview_id, again.created, again.added) == (first.interview_id, False, 0)
    assert state(first.interview_id) == before


# What a seeded name must not say; API replies may say "practice" (the mode).
NAME_MARKERS = re.compile(r"demo|fictional|practice|test", re.I)
VISIBLE_MARKERS = re.compile(r"demo|fictional", re.I)


def test_seeded_names_carry_no_visible_marker():
    """Nothing a user sees says demo; the seed tags, never shown, mark the rows."""
    names = [seed_demo.KIKUYU_NAME, seed_demo.PRACTICE_NAME, seed_demo.OFFICER["login"],
             seed_demo.OFFICER["display_name"], seed_demo.SEED_EXTRACTION]
    for spec in seed_demo.MEMBERS:
        names += [spec["login"], spec["full_name"], spec["member_no"],
                  spec["decision"]["officer_notes"], spec["decision"]["member_message"]]
    for p in seed_demo.DEMO_PEOPLE.values():
        names += [p["full_name"], p["member_no"], p.get("login", "")]
    for login, _, display in seed_demo.DEMO_STAFF.values():
        names += [login, display]
    for spec in seed_demo.DEMO_APPLICATIONS:
        names += [str(spec.get("decision", {}).get("officer_notes", ""))]
    assert not [n for n in names if NAME_MARKERS.search(n)]
    assert seed_demo.KIKUYU_TAG != seed_demo.PRACTICE_TAG


@needs_classifier
def test_seeded_practice_interview_is_fully_assessable(client, gemini, name):
    res = seed_demo.seed_practice(name, tag=name)
    r = client.post(f"/api/interviews/{res.interview_id}/assess")
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["applicant_form"]["age"] == seed_demo.PRACTICE_FORM["age"]
    assert gemini.translated == []                             # English: nothing translated
    d = client.post(f"/api/interviews/{res.interview_id}/decision", json={"decision": "refer"})
    assert d.status_code == 201


def test_cli_practice_only_needs_no_corpus(client, tmp_path):
    cmd = [sys.executable, str(config.SCRIPTS_DIR / "seed_demo.py"), "--practice-only",
           "--csv", str(tmp_path / "missing.csv")]
    out = subprocess.run(cmd, capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert "practice interview" in out.stdout and "Kikuyu interview" not in out.stdout


# --- Demo accounts and loan applications -------------------------------------------

def accounts(tag, legacy=False):
    """seed_demo's people with logins, member numbers and seed tags unique to
    this test (tests share a database); legacy ones only if asked for."""
    def own(spec):
        spec = {**spec, "login": f"{spec['login']}.{tag}"}
        for k in ("legacy_login", "legacy_member_no"):
            spec.pop(k, None)
            if legacy:
                spec[k] = f"old.{k}.{spec['key']}.{tag}"
        return spec
    members = [{**own(m), "member_no": f"{m['member_no']}-{tag}", "phone": fresh_phone()}
               for m in seed_demo.MEMBERS]
    return own(seed_demo.OFFICER), members, f"t{tag}"


def test_accounts_hold_no_identity_numbers():
    for spec in seed_demo.MEMBERS:
        assert "id_number" not in spec and "national_id" not in spec


@needs_classifier
def test_seed_accounts_creates_logins_and_decided_applications(client, admin_client, capsys):
    officer, members, prefix = accounts(uuid.uuid4().hex[:6])
    res = seed_demo.seed_accounts(officer, members, prefix)

    assert set(res.passwords) == {officer["login"], *(m["login"] for m in members)}
    assert all(len(pw) >= 10 for pw in res.passwords.values())
    statuses = {no: status for no, _, status, new in res.applications}
    assert statuses == {members[0]["member_no"]: "approved",
                        members[1]["member_no"]: "guarantor_required"}

    grace = TestClient(app, base_url=BASE_URL)
    assert grace.post("/api/auth/login", json={"username": members[0]["login"],
                                               "password": res.passwords[members[0]["login"]]}
                      ).status_code == 200
    (mine,) = grace.get("/api/me/applications").json()
    detail = grace.get(f"/api/me/applications/{mine['id']}").json()
    assert detail["status"] == "approved" and detail["approved_amount_kes"] == 40000
    assert len(detail["reasons"]) == 3 and not VISIBLE_MARKERS.search(str(detail))

    app_id = res.applications[1][1]
    staff = client.get(f"/api/applications/{app_id}").json()
    assert staff["interview"]["mode"] == "practice"                 # out of live statistics
    assert staff["assessment"]["extraction_model"] == seed_demo.SEED_EXTRACTION
    assert staff["decision"]["decided_by"] == officer["login"]
    assert not VISIBLE_MARKERS.search(staff["decision"]["officer_notes"])
    assert staff["comparator"]["conditions"][1]["result"] == "pending"
    st = client.get(f"/api/interviews/{staff['interview_id']}").json()
    assert st["counts"]["transcribed"] == 8 and st["applicant"]["age"] == 35


@needs_classifier
def test_seed_accounts_is_idempotent_and_keeps_passwords(client):
    officer, members, prefix = accounts(uuid.uuid4().hex[:6])
    first = seed_demo.seed_accounts(officer, members, prefix)
    again = seed_demo.seed_accounts(officer, members, prefix)
    assert again.passwords == {} and set(again.existing) == set(first.passwords)
    assert [(a[1], a[3]) for a in again.applications] == [(a[1], False) for a in first.applications]


def test_seed_accounts_without_classifier_waits_for_the_dashboard(client, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CLASSIFIER_PATH", tmp_path / "missing.joblib")
    officer, members, prefix = accounts(uuid.uuid4().hex[:6])
    res = seed_demo.seed_accounts(officer, members, prefix)
    assert not res.assessed
    assert {status for _, _, status, _ in res.applications} == {"interview_complete"}


def test_passwords_are_printed_once_and_never_written(client, tmp_path):
    cmd = [sys.executable, str(config.SCRIPTS_DIR / "seed_demo.py"), "--practice-only"]
    first = subprocess.run(cmd, capture_output=True, text=True, cwd=tmp_path)
    second = subprocess.run(cmd, capture_output=True, text=True, cwd=tmp_path)
    assert first.returncode == 0, first.stderr
    assert "shown once and not saved" in first.stdout or "already exists" in first.stdout
    assert "already exists; password unchanged" in second.stdout
    assert list(tmp_path.iterdir()) == []                          # nothing written to cwd
    printed = [pw for _, pw in re.findall(LOGIN_LINE, first.stdout, flags=re.M)]
    assert not [pw for pw in printed if pw in second.stdout]
    assert found_in_files(config.DB_PATH, printed) == []           # only their scrypt hashes are
    login = seed_demo.OFFICER["login"]
    assert found_in_files(config.DB_PATH, [login]) == [login]      # the scan does read the files


def found_in_files(db: Path, needles: list[str]) -> list[str]:
    """Which needles occur in the bytes of db and its -wal and -shm files.

    Read by a child process, never this one: on Linux, closing any descriptor
    on a file drops every POSIX lock this process holds on it, SQLAlchemy's
    SQLite locks included. A later writer in another process could then
    checkpoint the WAL under this process's pooled connection, which goes on
    reading a stale snapshot ("disk I/O error", or an update it never sees)."""
    code = ("import json, pathlib, sys; db = pathlib.Path(sys.argv[1]); "
            "data = b''.join(p.read_bytes() for p in db.parent.glob(db.name + '*')); "
            "print(json.dumps([n for n in json.loads(sys.stdin.read()) if n.encode() in data]))")
    r = subprocess.run([sys.executable, "-c", code, str(db)], input=json.dumps(needles),
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout)


def test_admin_sees_display_names_and_roles(client, admin_client):
    officer, members, prefix = accounts(uuid.uuid4().hex[:6])
    seed_demo.seed_accounts(officer, members, prefix)
    users = {u["username"]: u for u in admin_client.get("/api/admin/users").json()}
    assert (users[officer["login"]]["display_name"], users[officer["login"]]["role"]) == \
        ("Joseph Mwangi", "officer")
    assert (users[members[0]["login"]]["display_name"], users[members[0]["login"]]["role"]) == \
        ("Grace Wanjiku", "member")
    assert all("seed_tag" not in u for u in users.values())          # the marker stays server-side


def test_seeder_refuses_a_login_it_did_not_create(client):
    from conftest import add_user
    officer, members, prefix = accounts(uuid.uuid4().hex[:6])
    add_user(officer["login"], secrets.token_urlsafe(12))             # a real officer by that name
    with pytest.raises(ValueError, match="did not create"):
        seed_demo.seed_accounts(officer, members, prefix)
    with SessionLocal() as db:
        assert db.scalar(select(User).where(User.seed_tag.startswith(prefix))) is None


def test_earlier_rows_are_renamed_in_place(client, monkeypatch):
    """Rows from before seed_tag (demo. logins, DEMO- numbers, "(fictional)"
    names) are adopted: renamed, tagged, passwords and applications kept."""
    from conftest import add_user
    tag = uuid.uuid4().hex[:6]
    officer, members, prefix = accounts(tag, legacy=True)
    old_kikuyu = f"Demo applicant {tag}"
    monkeypatch.setitem(seed_demo.LEGACY_APPLICANTS, f"{prefix}:kikuyu", old_kikuyu)
    add_user(officer["legacy_login"], "old-password-1", "officer")
    with SessionLocal() as db:
        old = User(username=members[0]["legacy_login"], password_hash="scrypt$x", role="member")
        db.add(old)
        db.flush()
        m = Member(member_no=members[0]["legacy_member_no"], full_name="Grace Njeri (fictional)",
                   joined_on=date(2019, 3, 1), user_id=old.id)
        iv = Interview(applicant=Applicant(name="Grace Njeri (fictional)"), mode="practice")
        db.add_all([m, iv, Interview(applicant=Applicant(name=old_kikuyu), question_set="v1")])
        db.flush()
        db.add(LoanApplication(member=m, created_by=old.id, amount_requested_kes=1000, purpose="x",
                               term_months=6, sacco_savings_kes=500, interview_id=iv.id))
        db.commit()
        old_id, member_id, iv_id = old.id, m.id, iv.id

    res = seed_demo.seed_accounts(officer, members[:1], prefix)
    seed_demo.seed_practice(seed_demo.PRACTICE_NAME, tag=f"{prefix}:practice")
    with SessionLocal() as db:
        adopted = seed_demo.open_interview(db, f"{prefix}:kikuyu", seed_demo.KIKUYU_NAME)
        db.commit()
        assert adopted is not None and adopted.applicant.name == seed_demo.KIKUYU_NAME

    assert officer["login"] not in res.passwords and members[0]["login"] not in res.passwords
    assert res.applications == [(members[0]["member_no"], res.applications[0][1], "draft", False)]
    with SessionLocal() as db:
        u = db.get(User, old_id)
        assert (u.username, u.display_name, u.seed_tag) == \
            (members[0]["login"], "Grace Wanjiku", f"{prefix}:grace")
        m = db.get(Member, member_id)
        assert (m.member_no, m.full_name, m.user_id) == (members[0]["member_no"], "Grace Wanjiku", old_id)
        assert db.get(Interview, iv_id).applicant.name == "Grace Wanjiku"
        o = db.scalar(select(User).where(User.username == officer["login"]))
        assert (o.display_name, o.role, auth.verify_password("old-password-1", o.password_hash)) == \
            ("Joseph Mwangi", "officer", True)
        renames = db.scalars(select(AuditLog).where(AuditLog.action == "user.rename",
                                                    AuditLog.entity_id == old_id)).all()
        assert [r.details["from"] for r in renames] == [members[0]["legacy_login"]]


# --- Self-contained demo database (--demo-db) ----------------------------------------

def demo_cmd(path, *extra):
    return [sys.executable, str(config.SCRIPTS_DIR / "seed_demo.py"), "--demo-db", str(path), *extra]


def test_demo_people_have_placeholder_phones():
    for p in seed_demo.DEMO_PEOPLE.values():
        assert re.fullmatch(r"0700000\d{3}", p["phone"])
    assert len({p["member_no"] for p in seed_demo.DEMO_PEOPLE.values()}) == len(seed_demo.DEMO_PEOPLE)


def test_demo_answers_say_what_was_scored():
    answers = seed_demo.demo_answers(seed_demo.DEMO_PEOPLE["john"]["features"])
    assert sorted(answers) == list(range(1, 9))
    assert "I have no children" in answers[1]
    assert "30,000 shillings" in answers[2] and "10,000 shillings" in answers[3]
    assert "my pension, farming and renting out rooms" in answers[3]
    assert answers[7] == "Yes, I am repaying one now." and answers[8] == "No, never."


def test_demo_db_refuses_the_working_database():
    # Only paths are compared; nothing is opened.
    for path in (config.DATA_DIR / "chamapro.db", config.DB_PATH):
        assert "is the working database" in seed_demo.demo_db_refusal(path, replace=True)


def test_demo_db_refuses_a_file_the_engine_is_not_on(tmp_path):
    # In-process the engine is on the test database, set at import.
    assert "DATABASE_URL" in seed_demo.demo_db_refusal(tmp_path / "demo.db", replace=False)


@pytest.mark.parametrize("sql, demo", [
    ("CREATE TABLE users (username TEXT, seed_tag TEXT); "
     "INSERT INTO users VALUES ('s.achieng', 'demo-db:admin')", True),
    ("CREATE TABLE users (username TEXT); INSERT INTO users VALUES ('demo.admin')", True),  # pre-seed_tag
    ("CREATE TABLE users (username TEXT, seed_tag TEXT); "
     "INSERT INTO users VALUES ('j.mwangi', 'seed:officer')", False),   # the working database's seed
    ("CREATE TABLE users (username TEXT, seed_tag TEXT); INSERT INTO users VALUES ('admin', NULL)", False),
    ("CREATE TABLE notes (x)", False),
])
def test_a_demo_database_is_recognised_by_its_marker(tmp_path, sql, demo):
    con = sqlite3.connect(tmp_path / "x.db")
    con.executescript(sql)
    assert seed_demo.is_demo_db(con) is demo
    con.close()


def test_demo_db_refuses_a_database_that_is_not_a_demo(tmp_path):
    other = tmp_path / "other.db"
    sqlite3.connect(other).execute("CREATE TABLE notes (x)").connection.close()
    before = other.read_bytes()
    r = subprocess.run(demo_cmd(other, "--replace"), capture_output=True, text=True)
    assert r.returncode != 0 and "is not a demo database" in r.stderr
    assert other.read_bytes() == before


@needs_classifier
def test_demo_db_covers_every_status_and_outcome(tmp_path):
    path = tmp_path / "demo.db"
    r = subprocess.run(demo_cmd(path), capture_output=True, text=True, cwd=tmp_path)
    assert r.returncode == 0, r.stderr
    logins = dict(re.findall(LOGIN_LINE, r.stdout, flags=re.M))
    assert set(logins) == {"s.achieng", "j.mwangi", "a.chebet", "g.wanjiku",
                           "p.kamau", "m.wanjiru", "e.nyambura", "w.kamau", "n.mwangi"}

    con = sqlite3.connect(path)
    col = lambda sql: [v for (v,) in con.execute(sql)]  # noqa: E731
    assert set(col("SELECT status FROM loan_applications")) == set(APPLICATION_STATUSES)
    assert set(col("SELECT outcome FROM decisions")) == {
        "approve", "approve_with_guarantor", "approve_reduced", "refer", "decline", "not_now"}
    assert set(col("SELECT status FROM guarantors")) == {"verified", "pending", "rejected"}
    assert set(col("SELECT risk_class FROM assessments")) == {"Low", "Medium", "High"}
    assert set(col("SELECT mode FROM interviews")) == {"live", "self_service"}
    assert set(col("SELECT role FROM users")) == {"admin", "officer", "member", "system"}
    assert not [n for n in col("SELECT full_name FROM members") + col("SELECT name FROM applicants")
                + col("SELECT officer_notes FROM decisions WHERE officer_notes IS NOT NULL")
                if NAME_MARKERS.search(n)]
    assert all(t.startswith("demo-db:") for t in col("SELECT seed_tag FROM users WHERE role != 'system'")
               + col("SELECT seed_tag FROM members"))
    assert dict(con.execute("SELECT username, display_name FROM users WHERE role IN ('admin', 'officer')")) == {
        "s.achieng": "Susan Achieng", "j.mwangi": "Joseph Mwangi", "a.chebet": "Alice Chebet"}
    assert set(col("SELECT extraction_model FROM assessments")) == \
        {seed_demo.SEED_EXTRACTION, self_service.PROFILE_NOT_EXTRACTED}
    days = col("SELECT DISTINCT date(created_at) FROM loan_applications")
    assert len(days) >= 8                                   # spread over weeks, not one moment
    con.close()

    stored = b"".join(p.read_bytes() for p in tmp_path.glob("demo.db*"))
    for pw in logins.values():
        assert pw.encode() not in stored                    # printed once, never written
    assert {p.name for p in tmp_path.iterdir()} <= {"demo.db", "demo.db-wal", "demo.db-shm"}

    again = subprocess.run(demo_cmd(path), capture_output=True, text=True)
    assert again.returncode != 0 and "--replace" in again.stderr
    rebuilt = subprocess.run(demo_cmd(path, "--replace"), capture_output=True, text=True)
    assert rebuilt.returncode == 0, rebuilt.stderr
    fresh = dict(re.findall(LOGIN_LINE, rebuilt.stdout, flags=re.M))
    assert set(fresh) == set(logins) and not set(fresh.values()) & set(logins.values())
    assert sqlite3.connect(path).execute("SELECT count(*) FROM loan_applications").fetchone() \
        == (len(seed_demo.DEMO_APPLICATIONS) + len(seed_demo.SEEDED_DECISIONS),)


def test_the_kikuyu_clips_go_through_a_supabase_backend_in_a_folder_of_their_own(client, corpus, name, monkeypatch, tmp_path):
    """--demo-postgres, as far as the bucket: every clip uploaded, under the build's own folder, so
    that the numbering starting again cannot collide with what is already there (uploads never overwrite)."""
    from chamapro.api import storage
    from test_storage import FakeSupabase
    csv_path, audio, rows = corpus
    fake = FakeSupabase()
    store = storage.SupabaseStorage(fake, "interview-audio", tmp_path / "cache", signed_url_seconds=60)
    monkeypatch.setitem(storage._backends, "supabase", store)
    monkeypatch.setattr(config, "STORAGE_BACKEND", "supabase")
    monkeypatch.setattr(config, "UPLOADS_DIR", tmp_path / "uploads")
    res = seed_demo.seed(csv_path, audio, name, tag=name, folder="demo-20261105")
    monkeypatch.setattr(config, "STORAGE_BACKEND", "local")
    assert res.total == len(rows)
    with SessionLocal() as db:
        refs = db.scalars(select(Response.audio_path).where(Response.interview_id == res.interview_id)).all()
    assert len(refs) == len(rows) and all(r.startswith("supabase://interview-audio/demo-20261105/") for r in refs)
    assert sorted(path for _, path in fake.objects) == sorted(r.split("supabase://interview-audio/")[1] for r in refs)
