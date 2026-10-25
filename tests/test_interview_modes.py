"""Typed answers, English interviews, practice mode, the applicant form, and
the migration that keeps rows from before them."""
import json

import pytest
from sqlalchemy import create_engine, text

from chamapro import config
from chamapro.api import pipeline as pl
from chamapro.api.db import init_db

from conftest import FORM, needs_classifier, new_interview, wait_until
from legacy_schema import make_legacy_db


def typed(client, interview_id, n, words):
    return client.post(f"/api/interviews/{interview_id}/responses/typed",
                       json={"sentence_no": n, "text": words})


# --- Typed answers -------------------------------------------------------------

def test_typed_answer_skips_asr_and_is_ready_for_review(client, asr, interview, state):
    r = typed(client, interview, 3, "  We farm maize and keep goats.  ")
    assert r.status_code == 201, r.text
    out = r.json()
    assert out["source"] == "typed" and out["status"] == "transcribed"
    assert out["transcript"] == "We farm maize and keep goats."
    assert out["transcript_asr"] is None and out["asr_model"] is None and out["duration_s"] is None
    assert out["domain"] == "income_sources"
    assert asr.calls == []                                    # never queued
    assert state(interview)["counts"] == {"queued": 0, "transcribing": 0, "transcribed": 1, "failed": 0}


def test_typed_answer_has_no_audio(client, interview):
    rid = typed(client, interview, 1, "Five of us.").json()["id"]
    r = client.get(f"/api/responses/{rid}/audio")
    assert r.status_code == 404 and "typed" in r.json()["detail"]


def test_typed_answer_can_be_corrected_and_removed(client, interview, state):
    rid = typed(client, interview, 1, "Five of us.").json()["id"]
    r = client.patch(f"/api/responses/{rid}", json={"transcript": "Six of us."})
    assert r.status_code == 200 and r.json()["edited"] is True and r.json()["source"] == "typed"
    assert client.delete(f"/api/responses/{rid}").status_code == 200
    assert state(interview)["responses"] == []


@pytest.mark.parametrize("n, words, code", [(1, "   ", 422), (9, "x", 422), (0, "x", 422)])
def test_typed_answer_is_validated(client, interview, n, words, code):
    assert typed(client, interview, n, words).status_code == code


def test_a_question_takes_one_answer_typed_or_recorded(client, interview, upload):
    assert typed(client, interview, 2, "About 18,000.").status_code == 201
    assert typed(client, interview, 2, "again").status_code == 409
    assert upload(interview, 2).status_code == 409


def test_typed_answer_refused_once_assessed(client, assessed_interview):
    assert typed(client, assessed_interview, 1, "late").status_code == 409


# --- English interviews --------------------------------------------------------

def test_english_answers_use_the_english_model(client, asr, asr_en, upload, state):
    iid = new_interview(client, language="en")
    upload(iid, 1)
    wait_until(lambda: state(iid)["counts"]["transcribed"] == 1)
    resp = state(iid)["responses"][0]
    assert resp["transcript"].startswith("english response_")
    assert resp["asr_model"] == config.ASR_EN_MODEL
    assert asr.calls == [] and len(asr_en.calls) == 1
    assert asr_en.kwargs[0]["generate_kwargs"]["language"] == "en"


def test_kikuyu_answers_keep_the_kikuyu_model(client, asr, asr_en, interview, upload, state):
    upload(interview, 1)
    wait_until(lambda: state(interview)["counts"]["transcribed"] == 1)
    assert len(asr.calls) == 1 and asr_en.calls == []
    assert asr.kwargs[0]["generate_kwargs"]["language"] == config.ASR_LANGUAGE


def test_english_model_loads_on_first_use(client, monkeypatch):
    calls = []
    monkeypatch.setattr(pl, "_asr_en", None)
    monkeypatch.setattr(pl.transcribe, "load_asr",
                        lambda name, *a, **k: calls.append((name, a)) or pl.transcribe.ASR(
                            object(), "openvino", "GPU", str(a[2]), "openai/whisper-large-v3-turbo"))
    assert client.get("/api/health").json()["asr"]["en"]["loaded"] is False

    first, second = pl.english_asr(), pl.english_asr()

    assert first is second and len(calls) == 1
    assert calls[0] == (config.ASR_EN_MODEL, (config.ASR_ENGINE, config.ASR_DEVICE,
                                              config.ASR_EN_OV_MODEL_DIR))
    en = client.get("/api/health").json()["asr"]["en"]
    assert en["loaded"] and (en["engine"], en["device"]) == ("openvino", "GPU")


def test_english_load_failure_fails_the_answer_not_the_server(client, asr, upload, state, monkeypatch):
    monkeypatch.setattr(pl, "_asr_en", None)
    monkeypatch.setattr(pl, "_asr_en_error", None)

    def broken(*a, **k):
        raise OSError("no English model offline")

    monkeypatch.setattr(pl.transcribe, "load_asr", broken)
    iid = new_interview(client, language="en")
    upload(iid, 1)
    wait_until(lambda: state(iid)["counts"]["failed"] == 1)
    assert "no English model" in state(iid)["responses"][0]["error"]
    assert client.get("/api/health").json()["asr"]["en"]["error"] == "OSError: no English model offline"


def test_english_interview_skips_translation(client, gemini, classifier_stub, monkeypatch):
    iid = new_interview(client, language="en")
    typed(client, iid, 2, "I sell milk and earn about 18,000 shillings a month.")
    seen = []
    monkeypatch.setattr(pl.score_interview, "call",
                        lambda prompt, *a, **k: seen.append(prompt) or json.dumps([]))

    assert client.post(f"/api/interviews/{iid}/assess").status_code == 502   # stops after extraction

    assert gemini.translated == []
    assert "Answer: I sell milk and earn about 18,000 shillings a month." in seen[0]
    resp = client.get(f"/api/interviews/{iid}").json()["responses"][0]
    assert resp["translation"] is None


# --- Practice mode -------------------------------------------------------------

def test_practice_interviews_are_left_out_of_live_stats(admin_client, client, monkeypatch, tmp_path):
    path = tmp_path / "summary.json"
    path.write_text(json.dumps({"generated_at": "2026-10-23T00:00:00+00:00"}))
    monkeypatch.setattr(config, "RESULTS_SUMMARY_PATH", path)
    from test_results import seed
    before = admin_client.get("/api/results").json()["live"]

    seed("High", "decline", mode="practice")
    seed("High", mode="practice")
    new_interview(client, mode="practice")
    after = admin_client.get("/api/results").json()["live"]

    for k in ("interview_count", "assessment_count", "risk_class_distribution",
              "mean_extraction_completeness", "decision_agreement"):
        assert after[k] == before[k], k
    assert after["practice_interview_count"] - before["practice_interview_count"] == 3
    assert "practice interviews excluded" in after["source"]


def test_practice_mode_is_reported(client):
    iid = new_interview(client, mode="practice")
    item = next(x for x in client.get("/api/interviews").json() if x["id"] == iid)
    assert item["mode"] == "practice"
    assert client.get(f"/api/interviews/{iid}").json()["mode"] == "practice"


# --- Applicant form ------------------------------------------------------------

def test_form_options_are_the_classifier_encoding(client):
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "classifier_model", config.EXPERIMENTS_DIR / "03_classifier" / "model.py")
    model = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(model)

    opts = client.get("/api/applicant-form").json()
    assert [(o["label"], o["value"]) for o in opts["education"]] == list(model.EDU_LADDER.items())
    assert pl.score_interview.EDU_LADDER == model.EDU_LADDER
    assert [o["value"] for o in opts["marital_status"]] == ["married", "single", "widowed", "divorced"]
    assert [o["value"] for o in opts["sex"]] == ["female", "male"]


@needs_classifier
def test_form_values_go_straight_into_the_vector(client, gemini, interview):
    typed(client, interview, 1, "Six of us.")
    gemini.features = {"age": 99, "household_size": 6}      # an extracted age is overridden

    a = client.post(f"/api/interviews/{interview}/assess").json()

    v = a["feature_vector"]
    assert (v["age"], v["is_female"], v["education"]) == (42.0, 1.0, 4.0)
    assert (v["marital_married"], v["marital_single"], v["marital_widowed"],
            v["marital_divorced"]) == (1.0, 0.0, 0.0, 0.0)
    assert a["applicant_form"] == {"age": 42, "is_female": 1, "education_level": 4,
                                   "marital_status": "married"}
    assert a["extracted"] == gemini.features                 # the model's reply, as given


@needs_classifier
@pytest.mark.parametrize("sex, marital, female, flag", [("male", "widowed", 0.0, "marital_widowed"),
                                                        ("female", "divorced", 1.0, "marital_divorced"),
                                                        ("male", "single", 0.0, "marital_single")])
def test_form_encodes_sex_and_marital_status(client, gemini, sex, marital, female, flag):
    iid = new_interview(client, applicant={**FORM, "sex": sex, "marital_status": marital})
    typed(client, iid, 1, "Six of us.")
    v = client.post(f"/api/interviews/{iid}/assess").json()["feature_vector"]
    assert v["is_female"] == female and v[flag] == 1.0
    assert sum(v[f"marital_{m}"] for m in ("married", "single", "widowed", "divorced")) == 1.0


# --- Migration -----------------------------------------------------------------

NEW_COLUMNS = {"interviews": ["question_set", "language", "mode"],
               "applicants": ["age", "sex", "education", "marital_status"],
               "responses": ["source"], "assessments": ["applicant_form"]}


def test_migration_keeps_existing_rows(tmp_path):
    make_legacy_db(tmp_path / "old.db")
    engine = create_engine(f"sqlite:///{tmp_path / 'old.db'}")
    with engine.begin() as c:                   # back to the schema before this change
        for table, cols in NEW_COLUMNS.items():
            for col in cols:
                c.exec_driver_sql(f"ALTER TABLE {table} DROP COLUMN {col}")
        c.exec_driver_sql("INSERT INTO applicants (id, name, created_at) VALUES (1, 'Old', '2026-10-01')")
        c.exec_driver_sql("INSERT INTO interviews (id, applicant_id, status, created_at) "
                          "VALUES (1, 1, 'assessed', '2026-10-01')")
        c.exec_driver_sql("INSERT INTO responses (id, interview_id, sentence_no, audio_path, status, "
                          "edited, created_at) VALUES (1, 1, 1, 'a.wav', 'transcribed', 0, '2026-10-01')")
        c.exec_driver_sql(
            "INSERT INTO assessments (id, interview_id, risk_class, probabilities, feature_vector, "
            "contributions, extracted, extraction_completeness, features_populated, features_total, "
            "features_not_extractable, extraction_model, model_file, model_sha256, created_at) VALUES "
            "(1, 1, 'Low', '{}', '{}', '[]', '{}', 0.5, 1, 2, '[]', 'g', 'c.joblib', 'x', '2026-10-01')")

    init_db(engine)
    init_db(engine)                             # and again: a no-op

    with engine.connect() as c:
        assert c.execute(text("SELECT question_set, language, mode FROM interviews")).one() == \
            ("v1", "kik", "live")
        assert c.execute(text("SELECT name, age, sex, education, marital_status FROM applicants")).one() == \
            ("Old", None, None, None, None)
        assert c.execute(text("SELECT source, audio_path FROM responses")).one() == ("audio", "a.wav")
        assert c.execute(text("SELECT risk_class, applicant_form FROM assessments")).one() == ("Low", None)
    with pytest.raises(Exception, match="immutable"):        # triggers still guard the old row
        with engine.begin() as c:
            c.exec_driver_sql("UPDATE assessments SET risk_class = 'High'")
