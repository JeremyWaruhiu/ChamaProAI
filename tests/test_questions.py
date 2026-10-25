"""GET /api/questions, the question sets and the single source v1 is built from."""
import csv
import json
import subprocess
import sys
from collections import Counter

import build_questions  # scripts/ is on sys.path via chamapro.api.pipeline
import pytest
import score_interview
from chamapro import config

from conftest import new_interview

FIELDS = {"id", "version", "topic", "order", "text_en", "text_kik", "features"}
# The classifier features the applicant form fills (score_interview.build_vector).
FORM_FEATURES = ["age", "is_female", "education", "marital_married", "marital_single",
                 "marital_widowed", "marital_divorced"]


def all_questions():
    return json.loads(config.QUESTIONS_PATH.read_text(encoding="utf-8"))


def feature_order():
    meta = json.loads(config.CLASSIFIER_META_PATH.read_text(encoding="utf-8"))
    return meta["feature_order"]


def test_questions_endpoint_serves_v2_by_default(client):
    r = client.get("/api/questions")
    assert r.status_code == 200
    qs = r.json()
    assert [q["order"] for q in qs] == list(range(1, 9))
    assert all(set(q) == FIELDS and q["version"] == "v2" for q in qs)
    assert all(q["text_en"].strip() and q["text_kik"] == "" and q["features"] for q in qs)
    assert [q["topic"] for q in qs] == ["household", "income", "income_sources", "savings_in_kind",
                                        "purchases", "guarantorship", "sacco_borrowing",
                                        "chama_borrowing"]


def test_v1_is_still_served(client):
    qs = client.get("/api/questions", params={"version": "v1"}).json()
    assert [q["order"] for q in qs] == list(range(1, 41))
    assert all(set(q) == FIELDS and q["version"] == "v1" for q in qs)
    assert client.get("/api/questions", params={"version": "v9"}).status_code == 422


def test_v2_wording_is_as_specified():
    v2 = {q["order"]: q for q in all_questions() if q["version"] == "v2"}
    assert v2[7]["text_en"] == "Have you ever taken a loan from a SACCO?"
    assert v2[8]["text_en"] == "Have you ever borrowed from your chama?"
    assert v2[1]["features"] == ["household_size", "children", "children_under5", "children_in_school"]
    assert v2[3]["features"] == [f"B3A__{i}" for i in range(1, 12)] + ["log_agri_income"]
    assert v2[6]["features"] == ["E3B__3", "E3B__7"]


def test_ids_are_unique():
    ids = [q["id"] for q in all_questions()]
    assert len(ids) == len(set(ids))


def test_form_and_v2_cover_every_classifier_feature_exactly_once():
    asked = [f for q in all_questions() if q["version"] == "v2" for f in q["features"]]
    counts = Counter(FORM_FEATURES + asked)
    assert {f: n for f, n in counts.items() if n != 1} == {}            # none twice
    assert sorted(counts) == sorted(score_interview.FEATURE_FIELD)     # none missing, none extra
    assert len(counts) == 40


@pytest.mark.skipif(not config.CLASSIFIER_META_PATH.exists(), reason="needs models/classifier_meta.json")
def test_feature_mapping_is_the_trained_classifiers_feature_set():
    assert sorted(score_interview.FEATURE_FIELD) == sorted(feature_order())


def test_form_features_are_what_the_form_fills():
    form = score_interview.form_values(42, "female", 4, "married")
    built = {f for f in score_interview.FEATURE_FIELD
             if score_interview.FEATURE_FIELD[f] in score_interview.FORM_FIELDS}
    assert set(form) == set(score_interview.FORM_FIELDS)
    assert built == set(FORM_FEATURES)


def test_every_question_feature_is_one_the_extraction_can_build():
    for q in all_questions():
        assert set(q["features"]) <= set(score_interview.FEATURE_FIELD), q["id"]


def test_v1_topics_follow_the_manifest():
    with (config.DATA_DIR / "manifest.csv").open(newline="", encoding="utf-8") as fh:
        manifest = {int(r["sentence_no"]): r["domain"] for r in csv.DictReader(fh)}
    assert {q["order"]: q["topic"] for q in all_questions() if q["version"] == "v1"} == manifest


def test_list_counts_out_of_the_interview_set(client):
    v2 = new_interview(client)
    v1 = client.post("/api/interviews", json={"question_set": "v1"}).json()["id"]
    totals = {x["id"]: x["questions_total"] for x in client.get("/api/interviews").json()}
    assert (totals[v2], totals[v1]) == (8, 40)


def test_questions_json_is_up_to_date_with_the_text_file():
    r = subprocess.run([sys.executable, str(config.SCRIPTS_DIR / "build_questions.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


V2_Q = {"id": "v2-q1", "version": "v2", "topic": "household", "order": 1,
        "text_en": "How many people live in your household?", "text_kik": "", "features": ["household_size"]}


def test_rebuild_keeps_existing_kikuyu_and_later_sets(tmp_path):
    src = tmp_path / "q.txt"
    src.write_text("Header line\n## Household\n1. How old are you?\n2. Where do you live?\n")
    manifest = tmp_path / "m.csv"
    manifest.write_text("sentence_no,domain\n1,household\n2,household\n")
    existing = tmp_path / "q.json"
    existing.write_text(json.dumps([
        {"id": "v1-q01", "version": "v1", "topic": "household", "order": 1,
         "text_en": "old wording", "text_kik": "Ũrĩ na mĩaka ĩigana?", "features": []},
        V2_Q]))

    out = build_questions.build(src, manifest, existing)

    assert out == [
        {"id": "v1-q01", "version": "v1", "topic": "household", "order": 1,
         "text_en": "How old are you?", "text_kik": "Ũrĩ na mĩaka ĩigana?", "features": []},
        {"id": "v1-q02", "version": "v1", "topic": "household", "order": 2,
         "text_en": "Where do you live?", "text_kik": "", "features": []},
        V2_Q]


@pytest.mark.parametrize("text, message", [
    ("1. A?\n1. B?\n", "appears twice"),
    ("1. A?\n", "do not match"),
    ("1. A?\n2. B?\n3. C?\n", "do not match"),
])
def test_build_rejects_numbering_that_does_not_match(tmp_path, text, message):
    (tmp_path / "q.txt").write_text(text)
    (tmp_path / "m.csv").write_text("sentence_no,domain\n1,household\n2,household\n")
    with pytest.raises(ValueError, match=message):
        build_questions.build(tmp_path / "q.txt", tmp_path / "m.csv", tmp_path / "none.json")
