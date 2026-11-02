"""The suite refuses to run anywhere but scratch space (tests/safety.py, conftest.py)."""
import os
import subprocess
import sys
from pathlib import Path

import pytest

from chamapro import config
from safety import unsafe_target

TESTS = Path(__file__).resolve().parent
SCRATCH = "sqlite:////tmp/chamapro-test-x/test.db"
SUPABASE = "postgresql://postgres.abc:secret@aws-0-eu-west-1.pooler.supabase.com:5432/postgres"
LOCAL_PG = "postgresql://postgres:pw@127.0.0.1:55432/postgres"


def check(urls=None, storage=None, test_postgres=None, production=SUPABASE):
    return unsafe_target(urls=urls or {"env": SCRATCH, "config": SCRATCH},
                         storage=storage or {"env": "local", "config": "local"},
                         test_postgres=test_postgres, production=production, data_dir=config.DATA_DIR)


def test_scratch_sqlite_and_local_storage_are_fine():
    assert check() is None
    assert check(urls={"env": ""}) is None                  # empty: the SQLite file at CHAMAPRO_DB
    assert check(urls={"env": LOCAL_PG}, test_postgres=LOCAL_PG) is None


@pytest.mark.parametrize("kwargs, reason", [
    ({"urls": {"env": SUPABASE}}, "env points at postgresql+psycopg://postgres.abc:***@aws-0"),
    ({"urls": {"env": SCRATCH, "the app's database engine": SUPABASE}}, "the app's database engine points at"),
    ({"urls": {"env": f"sqlite:///{config.DATA_DIR / 'chamapro.db'}"}}, "a working database in data/"),
    ({"urls": {"env": LOCAL_PG}}, "not SQLite or CHAMAPRO_TEST_POSTGRES_URL"),
    ({"storage": {"env": "local", "config": "supabase"}}, "config is 'supabase'"),
    ({"test_postgres": SUPABASE.replace("pooler.supabase.com", "db.x.supabase.co")}, "points at Supabase"),
    ({"test_postgres": "postgresql://other:pw@db.example.org:5432/x",
      "production": "postgresql://prod:pw@db.example.org:5432/app"}, "the server DATABASE_URL in .env"),
])
def test_anything_else_is_refused(kwargs, reason):
    why = check(**kwargs)
    assert why is not None and reason in why
    assert "secret" not in why                               # never prints a password


def run_pytest(*args, env=None):
    return subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args],
                          capture_output=True, text=True, cwd=TESTS.parent, env={**os.environ, **(env or {})})


def test_a_production_test_postgres_url_stops_the_run_before_anything_connects():
    r = run_pytest("tests/test_environment.py",
                   env={"CHAMAPRO_TEST_POSTGRES_URL": SUPABASE.replace("pooler.supabase.com", "db.x.supabase.co")})
    assert r.returncode != 0, r.stdout + r.stderr    # 4: pytest reports it while loading conftest
    assert "test run stopped before anything ran" in r.stdout + r.stderr
    assert " passed" not in r.stdout


def test_a_test_that_repoints_the_database_stops_the_run(tmp_path):
    """As if a script run in-process had called load_dotenv(override=True)."""
    (tmp_path / "test_drift.py").write_text(
        "import os\n"
        f"def test_drifts():\n    os.environ['DATABASE_URL'] = {SUPABASE!r}\n"
        "def test_never_runs():\n    pass\n")
    r = run_pytest("-p", "conftest", "--rootdir", str(tmp_path), str(tmp_path / "test_drift.py"),
                   env={"PYTHONPATH": os.pathsep.join([str(TESTS), os.environ.get("PYTHONPATH", "")])})
    out = r.stdout + r.stderr
    assert r.returncode == 3, out
    assert "test run stopped after" in out and "test_drifts" in out and "secret" not in out
    assert "1 passed" in out and "2 passed" not in out       # the second test never ran
