"""GET /api/questions and the single source it is built from."""
import csv
import subprocess
import sys

import build_questions  # scripts/ is on sys.path via chamapro.api.pipeline
import pytest
from chamapro import config


def test_questions_endpoint_returns_the_script(client):
    r = client.get("/api/questions")
    assert r.status_code == 200
    qs = r.json()
    assert [q["sentence_no"] for q in qs] == list(range(1, 41))
    assert all(set(q) == {"sentence_no", "domain", "english", "kikuyu"} for q in qs)
    assert all(q["english"].strip() and isinstance(q["kikuyu"], str) for q in qs)


def test_domains_follow_the_manifest(client):
    with (config.DATA_DIR / "manifest.csv").open(newline="", encoding="utf-8") as fh:
        manifest = {int(r["sentence_no"]): r["domain"] for r in csv.DictReader(fh)}
    assert {q["sentence_no"]: q["domain"] for q in client.get("/api/questions").json()} == manifest


def test_list_counts_out_of_the_question_total(client):
    iid = client.post("/api/interviews").json()["id"]
    item = next(x for x in client.get("/api/interviews").json() if x["id"] == iid)
    assert item["questions_total"] == len(client.get("/api/questions").json()) == 40


def test_questions_json_is_up_to_date_with_the_text_file():
    r = subprocess.run([sys.executable, str(config.SCRIPTS_DIR / "build_questions.py"), "--check"],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_rebuild_keeps_existing_kikuyu(tmp_path):
    src = tmp_path / "q.txt"
    src.write_text("Header line\n## Household\n1. How old are you?\n2. Where do you live?\n")
    manifest = tmp_path / "m.csv"
    manifest.write_text("sentence_no,domain\n1,household\n2,household\n")
    existing = tmp_path / "q.json"
    existing.write_text('[{"sentence_no": 1, "domain": "household", '
                        '"english": "old wording", "kikuyu": "Ũrĩ na mĩaka ĩigana?"}]')

    out = build_questions.build(src, manifest, existing)

    assert out == [
        {"sentence_no": 1, "domain": "household", "english": "How old are you?",
         "kikuyu": "Ũrĩ na mĩaka ĩigana?"},
        {"sentence_no": 2, "domain": "household", "english": "Where do you live?", "kikuyu": ""}]


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
