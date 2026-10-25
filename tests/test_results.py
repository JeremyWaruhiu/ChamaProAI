"""GET /api/results: the exported evaluation summary plus live database stats."""
import json

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from chamapro import config
from chamapro.api import main
from chamapro.api.db import Applicant, Assessment, Base, Decision, Interview, SessionLocal


@pytest.fixture
def summary_path(monkeypatch, tmp_path):
    path = tmp_path / "results" / "summary.json"
    monkeypatch.setattr(config, "RESULTS_SUMMARY_PATH", path)
    return path


def write_summary(path, **extra):
    path.parent.mkdir(parents=True, exist_ok=True)
    body = {"generated_at": "2026-10-19T00:00:00+00:00",
            "held_out": {"source": "test", "macro_f1": 0.37, "auc_macro_ovr": None}, **extra}
    path.write_text(json.dumps(body), encoding="utf-8")
    return body


def seed(risk_class, decision=None, completeness=0.5, mode="live"):
    """An assessed interview, optionally with the officer's decision."""
    with SessionLocal() as db:
        iv = Interview(applicant=Applicant(name=None), status="assessed", mode=mode)
        db.add(iv)
        db.flush()
        db.add(Assessment(
            interview_id=iv.id, risk_class=risk_class,
            probabilities={"Low": 0.2, "Medium": 0.5, "High": 0.3}, feature_vector={},
            contributions=[], extracted={}, extraction_completeness=completeness,
            features_populated=1, features_total=2, features_not_extractable=[],
            extraction_model="fake", model_file="classifier.joblib", model_sha256="0" * 64))
        if decision:
            db.add(Decision(interview_id=iv.id, decision=decision))
        db.commit()


def test_missing_summary_is_404(admin_client, summary_path):
    r = admin_client.get("/api/results")
    assert r.status_code == 404
    assert "scripts/export_results.py" in r.json()["detail"]


def test_summary_is_returned_with_live_stats(admin_client, summary_path):
    body = write_summary(summary_path)
    r = admin_client.get("/api/results")
    assert r.status_code == 200
    out = r.json()
    for k, v in body.items():
        assert out[k] == v
    assert out["held_out"]["auc_macro_ovr"] is None  # nulls pass through untouched
    live = out["live"]
    assert set(live["risk_class_distribution"]) >= {"Low", "Medium", "High"}
    assert set(live["decision_agreement"]) == {"rule", "decisions", "agreements", "rate"}


def test_live_stats_count_seeded_data(admin_client, summary_path):
    client = admin_client
    write_summary(summary_path)
    # The test database is shared across the session, so compare before and after.
    before = client.get("/api/results").json()["live"]
    seed("Low", "approve", completeness=1.0)    # agrees
    seed("High", "decline", completeness=1.0)   # agrees
    seed("Medium", "approve", completeness=1.0)  # disagrees
    seed("High")                                # no decision yet
    after = client.get("/api/results").json()["live"]

    assert after["interview_count"] - before["interview_count"] == 4
    assert after["assessment_count"] - before["assessment_count"] == 4
    d0, d1 = before["risk_class_distribution"], after["risk_class_distribution"]
    assert {k: d1[k] - d0[k] for k in ("Low", "Medium", "High")} == {"Low": 1, "Medium": 1, "High": 2}
    a0, a1 = before["decision_agreement"], after["decision_agreement"]
    assert a1["decisions"] - a0["decisions"] == 3
    assert a1["agreements"] - a0["agreements"] == 2
    assert a1["rate"] == round(a1["agreements"] / a1["decisions"], 4)
    assert 0 < after["mean_extraction_completeness"] <= 1
    assert after["mean_extraction_completeness"] >= (before["mean_extraction_completeness"] or 0)


def test_live_stats_on_empty_database_are_null_not_zero():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with sessionmaker(engine)() as db:
        live = main.live_stats(db)
    assert live["interview_count"] == 0 and live["assessment_count"] == 0
    assert live["mean_extraction_completeness"] is None
    assert live["decision_agreement"]["rate"] is None
