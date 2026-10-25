"""scripts/seed_demo.py: a complete demo interview without running Whisper."""
import csv
import re
import subprocess
import sys
import uuid

import numpy as np
import pytest
import soundfile as sf
from fastapi.testclient import TestClient

import seed_demo  # scripts/ is on sys.path via chamapro.api.pipeline
from chamapro import config
from chamapro.api.main import app

from conftest import BASE_URL, needs_classifier, uploads


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
    return f"Demo {uuid.uuid4().hex[:8]}"   # tests share a database


def test_seed_creates_a_transcribed_interview(client, corpus, name, state):
    csv_path, audio, rows = corpus

    res = seed_demo.seed(csv_path, audio, name)

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
    res = seed_demo.seed(csv_path, audio, name)
    ids = [r["id"] for r in state(res.interview_id)["responses"]]
    assert uploads(res.interview_id) == sorted(
        f"response_{i}_s{n:02d}.wav" for i, n in zip(ids, (1, 2, 6, 7, 16)))


def test_seed_is_idempotent(client, corpus, name, state):
    csv_path, audio, _ = corpus
    first = seed_demo.seed(csv_path, audio, name)
    before = state(first.interview_id)

    again = seed_demo.seed(csv_path, audio, name)

    assert (again.interview_id, again.created, again.added, again.total) == \
        (first.interview_id, False, 0, 5)
    assert state(first.interview_id) == before
    assert len(uploads(first.interview_id)) == 5
    assert sum(x["applicant_name"] == name for x in client.get("/api/interviews").json()) == 1


def test_seed_keeps_reviewer_edits(client, corpus, name, state):
    csv_path, audio, _ = corpus
    res = seed_demo.seed(csv_path, audio, name)
    rid = state(res.interview_id)["responses"][3]["id"]          # the blank one
    client.patch(f"/api/responses/{rid}", json={"transcript": "typed by officer"})

    seed_demo.seed(csv_path, audio, name)

    assert state(res.interview_id)["responses"][3]["transcript"] == "typed by officer"


def test_rerecord_deletes_the_copy_and_reseed_restores_it(client, corpus, name, state):
    csv_path, audio, _ = corpus
    res = seed_demo.seed(csv_path, audio, name)
    rid = state(res.interview_id)["responses"][0]["id"]

    assert client.delete(f"/api/responses/{rid}").status_code == 200
    assert (audio / "S01_clean_001.wav").exists()                 # corpus untouched
    assert len(uploads(res.interview_id)) == 4

    again = seed_demo.seed(csv_path, audio, name)

    assert (again.interview_id, again.created, again.added, again.total) == \
        (res.interview_id, False, 1, 5)
    assert [x["sentence_no"] for x in state(res.interview_id)["responses"]] == [1, 2, 6, 7, 16]
    assert len(uploads(res.interview_id)) == 5


def test_seed_after_assessment_starts_a_fresh_demo(client, corpus, name, monkeypatch):
    from chamapro.api.db import Interview, SessionLocal
    csv_path, audio, _ = corpus
    first = seed_demo.seed(csv_path, audio, name)
    with SessionLocal() as db:                       # as if assessed during a rehearsal
        db.get(Interview, first.interview_id).status = "assessed"
        db.commit()

    fresh = seed_demo.seed(csv_path, audio, name)

    assert fresh.created and fresh.interview_id != first.interview_id
    assert (fresh.added, fresh.total) == (5, 5)
    assert seed_demo.seed(csv_path, audio, name).interview_id == fresh.interview_id


def test_missing_clip_writes_nothing(client, corpus, name):
    csv_path, audio, _ = corpus
    (audio / "S01_clean_006.wav").unlink()
    before = client.get("/api/interviews").json()

    with pytest.raises(FileNotFoundError, match="S01_clean_006.wav"):
        seed_demo.seed(csv_path, audio, name)

    assert client.get("/api/interviews").json() == before


def test_cli_reports_and_is_idempotent(client, corpus, name):
    csv_path, audio, _ = corpus
    cmd = [sys.executable, str(config.SCRIPTS_DIR / "seed_demo.py"),
           "--csv", str(csv_path), "--audio", str(audio), "--name", name]
    first = subprocess.run(cmd, capture_output=True, text=True, check=True)
    second = subprocess.run(cmd, capture_output=True, text=True, check=True)
    assert "created demo interview" in first.stdout and "with 5 responses" in first.stdout
    assert "already complete; nothing to do" in second.stdout
    assert str(config.DB_PATH) in second.stdout              # wrote to the test database

    bad = subprocess.run(cmd[:2] + ["--csv", str(csv_path.with_name("nope.csv")),
                                    "--name", name], capture_output=True, text=True)
    assert bad.returncode != 0 and "nothing written" in bad.stderr


REAL_CSV = config.DATA_DIR / "asr_paza.csv"
REAL_AUDIO = config.DATA_DIR / "audio_16k"


@pytest.mark.skipif(not (REAL_CSV.exists() and REAL_AUDIO.exists()),
                    reason="needs data/asr_paza.csv and data/audio_16k/ (not in the repo)")
def test_real_corpus_seeds_all_40(client, name, state):
    res = seed_demo.seed(REAL_CSV, REAL_AUDIO, name)
    st = state(res.interview_id)
    assert res.total == 40 and st["counts"]["transcribed"] == 40
    assert [x["sentence_no"] for x in st["responses"]] == list(range(1, 41))
    assert len(uploads(res.interview_id)) == 40


# --- English practice interview ----------------------------------------------

def test_seed_practice_creates_an_english_practice_interview(client, name, state):
    res = seed_demo.seed_practice(name)

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
    first = seed_demo.seed_practice(name)
    before = state(first.interview_id)
    again = seed_demo.seed_practice(name)
    assert (again.interview_id, again.created, again.added) == (first.interview_id, False, 0)
    assert state(first.interview_id) == before


def test_practice_applicant_is_fictional():
    assert "fictional" in seed_demo.PRACTICE_NAME.lower()
    assert seed_demo.PRACTICE_NAME.lower().startswith("practice")


@needs_classifier
def test_seeded_practice_interview_is_fully_assessable(client, gemini, name):
    res = seed_demo.seed_practice(name)
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
    assert "practice interview" in out.stdout and "demo interview" not in out.stdout


# --- Demo accounts and loan applications -------------------------------------------

def accounts(tag):
    """seed_demo's demo people with names unique to this test (tests share a database)."""
    members = []
    for spec in seed_demo.MEMBERS:
        members.append({**spec, "login": f"{spec['login']}.{tag}",
                        "member_no": f"{spec['member_no']}-{tag}"})
    return f"demo.officer.{tag}", members


def test_accounts_are_fictional():
    for spec in seed_demo.MEMBERS:
        assert "(fictional)" in spec["full_name"]
        assert "id_number" not in spec and "national_id" not in spec


@needs_classifier
def test_seed_accounts_creates_logins_and_decided_applications(client, admin_client, capsys):
    officer, members = accounts(uuid.uuid4().hex[:6])
    res = seed_demo.seed_accounts(officer, members)

    assert set(res.passwords) == {officer, *(m["login"] for m in members)}
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
    assert len(detail["reasons"]) == 3 and "Demo record" not in str(detail)

    app_id = res.applications[1][1]
    staff = client.get(f"/api/applications/{app_id}").json()
    assert staff["interview"]["mode"] == "practice"                 # out of live statistics
    assert staff["assessment"]["extraction_model"] == seed_demo.SEED_EXTRACTION
    assert staff["decision"]["decided_by"] == officer
    assert staff["comparator"]["conditions"][1]["result"] == "pending"
    st = client.get(f"/api/interviews/{staff['interview_id']}").json()
    assert st["counts"]["transcribed"] == 8 and st["applicant"]["age"] == 35


@needs_classifier
def test_seed_accounts_is_idempotent_and_keeps_passwords(client):
    officer, members = accounts(uuid.uuid4().hex[:6])
    first = seed_demo.seed_accounts(officer, members)
    again = seed_demo.seed_accounts(officer, members)
    assert again.passwords == {} and set(again.existing) == set(first.passwords)
    assert [(a[1], a[3]) for a in again.applications] == [(a[1], False) for a in first.applications]


def test_seed_accounts_without_classifier_waits_for_the_dashboard(client, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "CLASSIFIER_PATH", tmp_path / "missing.joblib")
    officer, members = accounts(uuid.uuid4().hex[:6])
    res = seed_demo.seed_accounts(officer, members)
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
    stored = b"".join(p.read_bytes() for p in config.DB_PATH.parent.glob(config.DB_PATH.name + "*"))
    for pw in re.findall(r"^  demo\.\S+\s+(\S+)$", first.stdout, flags=re.M):
        assert pw not in second.stdout
        assert pw.encode() not in stored                            # only its scrypt hash is
