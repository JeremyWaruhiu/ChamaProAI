"""The number to quote: a member's wait on the database, per turn, with each round trip costing
what it costs from Nairobi. tests/latency_demo.py runs both demo conversations over HTTP on a
scratch database on CHAMAPRO_TEST_POSTGRES_URL, with a hook that sleeps 200 ms per statement and a
TCP proxy that counts what the hook cannot see. It runs in a process of its own, since the app's
engine is chosen at import and this run's is SQLite.

    CHAMAPRO_TEST_POSTGRES_URL=postgresql://postgres:pw@localhost:5432/postgres pytest tests/test_latency.py -s
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from chamapro import config

SERVER = os.getenv("CHAMAPRO_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not (SERVER and config.CLASSIFIER_PATH.exists()),
                                reason="set CHAMAPRO_TEST_POSTGRES_URL, and needs models/classifier.joblib")
ROOT = Path(__file__).resolve().parents[1]
UNDER_SECONDS = 2.0


@pytest.fixture(scope="module")
def figures(tmp_path_factory):
    out = tmp_path_factory.mktemp("latency") / "figures.json"
    done = subprocess.run([sys.executable, str(ROOT / "tests" / "latency_demo.py"), "--delay", "0.2", "--json", str(out)],
                          env={**os.environ, "HF_HUB_OFFLINE": "1"}, capture_output=True, text=True, timeout=600)
    assert done.returncode == 0, done.stdout[-3000:] + done.stderr[-3000:]
    print(done.stdout[done.stdout.index("Wanjiru Kamau (en)"):])
    return json.loads(out.read_text(encoding="utf-8"))


def test_both_conversations_in_both_languages_ran(figures):
    assert set(figures["conversations"]) == {"Wanjiru Kamau (en)", "Wanjiru Kamau (kik)", "Njeri Mwangi (en)", "Njeri Mwangi (kik)"}


def test_every_turn_is_within_its_round_trips(figures):
    for name, rows in figures["conversations"].items():
        for row in rows:
            # The limit is 15 on the reply that pays out; it comes to the same 8 as any other now.
            assert row["round_trips"] <= 8, (name, row)


def test_every_turn_waits_under_two_seconds_on_the_database(figures):
    for name, rows in figures["conversations"].items():
        for row in rows:
            assert row["database_s"] < UNDER_SECONDS, (name, row)


def test_a_poll_costs_three_at_most_and_one_when_nothing_moved(figures):
    polls = figures["polls"]
    assert polls["/present one, unchanged"] == {**polls["/present one, unchanged"], "status": 304, "round_trips": 1}
    for label in ("/present list", "/present one, changed", "chat stage poll", "chat transcript", "chat carry on"):
        assert polls[label]["round_trips"] <= 3, (label, polls[label])
