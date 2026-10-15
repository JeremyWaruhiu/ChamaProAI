"""Assess: translate what is untranslated, extract features, score, store."""
import hashlib
import json

import numpy as np
import pandas as pd

from chamapro import config
from chamapro.api import pipeline as pl

from conftest import needs_classifier, wait_until


def assess(client, interview_id):
    return client.post(f"/api/interviews/{interview_id}/assess")


@needs_classifier
def test_assess_matches_the_pipeline_script(client, gemini, ready_interview):
    r = assess(client, ready_interview)
    assert r.status_code == 201, r.text
    a = r.json()

    expected = pl.score_interview.assess(gemini.features)   # the CLI's code path
    assert a["risk_class"] == expected["risk_class"]
    assert a["probabilities"] == expected["probabilities"]
    assert a["contributions"] == expected["top_contributions"]
    assert a["extracted"] == expected["extracted"] == gemini.features
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


def test_feature_extraction_receives_numbered_english(client, gemini, classifier_stub,
                                                      ready_interview, monkeypatch):
    seen = []

    def spy(prompt, key, model, **kwargs):
        if "JSON array" not in prompt:
            seen.append(prompt.split("Interview:\n")[1])
            return json.dumps([])                            # not an object -> 502
        return gemini(prompt, key, model, **kwargs)

    monkeypatch.setattr(pl.translate_extract, "call", spy)
    monkeypatch.setattr(pl.score_interview, "call", spy)

    assert assess(client, ready_interview).status_code == 502
    assert seen == ["\n".join(f"{n}. english of kikuyu response_{rid}_s{n:02d}"
                              for rid, n in zip(_ids(client, ready_interview), (2, 6, 7)))]


def _ids(client, interview_id):
    return [x["id"] for x in client.get(f"/api/interviews/{interview_id}").json()["responses"]]
