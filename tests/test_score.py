"""scripts/score.py: chrF++ and BLEU against the worksheet references."""
import csv

import pytest
import score  # scripts/ is on sys.path via chamapro.api.pipeline

from chamapro import config


def write(path, fields, rows):
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    return path


@pytest.fixture
def manifest(tmp_path):
    rows = [{"id": f"s{n}", "domain": d, "english_ref": ref} for n, d, ref in [
        (1, "household", "I am forty-two years old."),
        (2, "household", "There are six people in my household."),
        (3, "income", "I sell milk from my cows every morning.")]]
    return write(tmp_path / "manifest.csv", ["id", "domain", "english_ref"], rows)


def translations(tmp_path, outs):
    return write(tmp_path / "t.csv", ["id", "english_out"],
                 [{"id": f"s{i}", "english_out": o} for i, o in enumerate(outs, 1)])


def test_perfect_translations_score_100(tmp_path, manifest):
    refs = ["I am forty-two years old.", "There are six people in my household.",
            "I sell milk from my cows every morning."]
    res = score.score(score.load(translations(tmp_path, refs), manifest))
    assert res["corpus"] == {"n": 3, "translated": 3, "chrf++": 100.0, "bleu": 100.0}
    assert list(res["domains"]) == ["household", "income"]
    assert res["domains"]["household"]["n"] == 2


def test_blank_output_counts_as_untranslated_and_scores_zero(tmp_path, manifest):
    outs = ["I am forty-two years old.", "", ""]
    res = score.score(score.load(translations(tmp_path, outs), manifest))
    assert res["corpus"]["translated"] == 1
    assert res["domains"]["income"] == {"n": 1, "translated": 0, "chrf++": 0.0, "bleu": 0.0}
    assert 0 < res["corpus"]["chrf++"] < 100


def test_missing_references_are_refused(tmp_path):
    m = write(tmp_path / "m.csv", ["id", "domain", "english_ref"],
              [{"id": "s1", "domain": "household", "english_ref": ""}])
    with pytest.raises(ValueError, match="no english_ref"):
        score.load(translations(tmp_path, ["x"]), m)


def test_manifest_has_all_40_references():
    with (config.DATA_DIR / "manifest.csv").open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 40 and all(r["english_ref"].strip() for r in rows)
