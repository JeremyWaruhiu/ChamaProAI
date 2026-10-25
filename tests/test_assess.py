"""Assess: translate what is untranslated, extract features, score, store."""
import hashlib
import json

import numpy as np
import pandas as pd

from chamapro import config
from chamapro.api import pipeline as pl

from conftest import FORM, needs_classifier, wait_until

FORM_VALUES = {"age": 42, "is_female": 1, "education_level": 4, "marital_status": "married"}


def assess(client, interview_id):
    return client.post(f"/api/interviews/{interview_id}/assess")


@needs_classifier
def test_assess_matches_the_pipeline_script(client, gemini, ready_interview):
    r = assess(client, ready_interview)
    assert r.status_code == 201, r.text
    a = r.json()

    form = pl.score_interview.form_values(**FORM)
    assert form == FORM_VALUES
    expected = pl.score_interview.assess(gemini.features, form=form)   # the CLI's code path
    assert a["risk_class"] == expected["risk_class"]
    assert a["probabilities"] == expected["probabilities"]
    assert a["contributions"] == expected["top_contributions"]
    assert a["extracted"] == expected["extracted"] == gemini.features
    assert a["applicant_form"] == expected["applicant_form"] == FORM_VALUES
    assert a["extraction_completeness"] == expected["extraction_completeness"]
    assert a["features_populated"] == expected["features_populated"]
    assert a["features_total"] == expected["features_total"]
    assert a["features_not_extractable"] == expected["features_not_extractable_from_interview"]


@needs_classifier
def test_assessment_records_model_provenance(client, gemini, ready_interview):
    a = assess(client, ready_interview).json()
    assert a["model_file"] == config.CLASSIFIER_PATH.name
    assert a["model_sha256"] == hashlib.sha256(config.CLASSIFIER_PATH.read_bytes()).hexdigest()
    assert a["extraction_model"] == pl.extraction_model()
    assert isinstance(a["contributions"], list) and a["contributions"]
    assert a["created_at"].endswith("Z")


@needs_classifier
def test_stored_vector_is_what_the_classifier_saw(client, gemini, ready_interview):
    a = assess(client, ready_interview).json()
    clf, meta, _ = pl.score_interview.load_classifier(config.CLASSIFIER_PATH,
                                                      config.CLASSIFIER_META_PATH)
    vec = a["feature_vector"]

    assert list(vec) == meta["feature_order"]                # classifier's column order
    assert vec["age"] == 42.0
    assert vec["log_monthly_income"] is None                 # NaN stored as JSON null
    assert vec["income_missing"] == 1.0

    X = pd.DataFrame([{k: np.nan if v is None else v for k, v in vec.items()}],
                     columns=meta["feature_order"])
    proba = clf.predict_proba(X)[0]
    replayed = {meta["classes"][str(i)]: round(float(p), 4) for i, p in enumerate(proba)}
    assert replayed == a["probabilities"]                    # the record replays exactly


@needs_classifier
def test_assess_stores_translations_and_assessment(client, gemini, ready_interview, state):
    a = assess(client, ready_interview).json()
    st = state(ready_interview)
    assert st["status"] == "assessed"
    assert st["assessment"] == a
    assert gemini.translated == [["2", "6", "7"]]
    for x in st["responses"]:
        assert x["translation"] == f"english of {x['transcript']}"
        assert x["signals"] == [f"signal {x['sentence_no']}"]


# The tests below stop at feature extraction (503), so they run without the
# classifier: translation has already happened and been committed by then.

def test_translation_is_batched_in_fives(client, gemini, classifier_stub, interview, upload, state):
    for n in range(1, 8):
        upload(interview, n)
    wait_until(lambda: state(interview)["counts"]["transcribed"] == 7)
    gemini.extraction = "down"

    assert assess(client, interview).status_code == 503

    assert gemini.translated == [["1", "2", "3", "4", "5"], ["6", "7"]]


def test_only_untranslated_responses_are_sent_again(client, gemini, classifier_stub,
                                                    ready_interview, state):
    gemini.extraction = "down"
    assess(client, ready_interview)
    edited = state(ready_interview)["responses"][1]
    client.patch(f"/api/responses/{edited['id']}", json={"transcript": "new words"})
    assert state(ready_interview)["responses"][1]["translation"] is None   # edit cleared it

    assess(client, ready_interview)

    assert gemini.translated == [["2", "6", "7"], [str(edited["sentence_no"])]]
    assert state(ready_interview)["responses"][1]["translation"] == "english of new words"


def spy_extraction(monkeypatch, gemini):
    """Capture the extraction prompts; reply with a non-object so assess stops (502)
    before scoring, which keeps these tests free of the classifier."""
    seen = []

    def spy(prompt, key, model, **kwargs):
        if "JSON array" not in prompt:
            seen.append(prompt)
            return json.dumps([])
        return gemini(prompt, key, model, **kwargs)

    monkeypatch.setattr(pl.translate_extract, "call", spy)
    monkeypatch.setattr(pl.score_interview, "call", spy)
    return seen


def v2_text(n):
    return next(q["text_en"] for q in json.loads(config.QUESTIONS_PATH.read_text(encoding="utf-8"))
                if q["version"] == "v2" and q["order"] == n)


def test_each_answer_goes_with_its_question_and_fields(client, gemini, classifier_stub,
                                                       ready_interview, monkeypatch):
    seen = spy_extraction(monkeypatch, gemini)

    assert assess(client, ready_interview).status_code == 502
    ids = _ids(client, ready_interview)
    fields = {2: "monthly_income_kes", 6: "lost_as_guarantor", 7: "sacco_loan_use"}
    assert seen[0].split("Interview:\n")[1] == "\n\n".join(
        f"Q{n} (fields: {fields[n]})\nQuestion: {v2_text(n)}\n"
        f"Answer: english of kikuyu response_{rid}_s{n:02d}"
        for rid, n in zip(ids, (2, 6, 7)))


def test_form_fields_are_not_asked_for(client, gemini, classifier_stub, ready_interview, monkeypatch):
    seen = spy_extraction(monkeypatch, gemini)
    assess(client, ready_interview)
    prompt = seen[0]
    for field in ("age", "is_female", "education_level", "marital_status"):
        assert f'"{field}"' not in prompt
    assert "Never infer it from a name" not in prompt and "0 none, 1 some primary" not in prompt
    # the rest of the rules stay
    assert "Never infer, estimate or\nguess" in prompt and "Record each fact once." in prompt
    assert "Never duplicate one figure\n    into both fields." in prompt
    assert '"household_size"' in prompt and '"lost_as_guarantor"' in prompt


def test_extraction_runs_at_temperature_zero(monkeypatch):
    sent = {}

    class Reply:
        status_code = 200
        def json(self):
            return {"candidates": [{"content": {"parts": [{"text": "{}"}]}}]}

    monkeypatch.setattr(pl.score_interview.requests, "post",
                        lambda url, **kw: sent.update(kw) or Reply())
    pl.score_interview.extract_features([(1, "I am 42")], key="k", model="m")
    assert sent["json"]["generationConfig"]["temperature"] == 0


def test_v1_interview_without_form_keeps_the_full_prompt(client, gemini, classifier_stub, upload,
                                                         state, monkeypatch):
    iid = client.post("/api/interviews", json={"question_set": "v1"}).json()["id"]
    upload(iid, 2)
    wait_until(lambda: state(iid)["counts"]["transcribed"] == 1)
    seen = spy_extraction(monkeypatch, gemini)

    assess(client, iid)

    assert '"age"' in seen[0] and '"marital_status"' in seen[0] and '"is_female"' in seen[0]
    assert "Question: How old are you?\nAnswer: english of kikuyu" in seen[0]


def _ids(client, interview_id):
    return [x["id"] for x in client.get(f"/api/interviews/{interview_id}").json()["responses"]]
