"""scripts/seed_demo.py: a complete demo interview without running Whisper."""
import csv
import subprocess
import sys
import uuid

import numpy as np
import pytest
import soundfile as sf

import seed_demo  # scripts/ is on sys.path via chamapro.api.pipeline
from chamapro import config

from conftest import uploads


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
    assert st["counts"] == {"queued": 0, "transcribing": 0, "transcribed": 5, "failed": 0}
    for resp, row in zip(st["responses"], rows):
        assert resp["sentence_no"] == row["sentence_no"]
        assert resp["domain"] == row["domain"]
        assert resp["transcript"] == resp["transcript_asr"] == row["hypothesis"]
        assert resp["asr_model"] == seed_demo.CSV_ASR_MODEL
        assert resp["asr_seconds"] == 35.5 and resp["duration_s"] == 0.5
        assert resp["edited"] is False and resp["translation"] is None


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
