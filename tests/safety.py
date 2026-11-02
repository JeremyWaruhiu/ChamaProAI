"""Where the test suite may write: a scratch SQLite file and local storage, or
the explicit CHAMAPRO_TEST_POSTGRES_URL server. conftest.py checks this before
any test runs and after every test, and stops the whole run otherwise, so a
.env pointing at Supabase fails the run instead of filling production."""
from __future__ import annotations

from pathlib import Path

from sqlalchemy.engine import make_url

from chamapro.config import _database_url

SUPABASE_HOSTS = (".supabase.co", ".supabase.com")


def _server(url: str) -> tuple:
    u = make_url(_database_url(url))
    return (u.host, u.port or 5432)


def unsafe_target(urls: dict[str, str], storage: dict[str, str | None], test_postgres: str | None,
                  production: str | None, data_dir: Path) -> str | None:
    """Why these settings could write outside scratch space, or None.

    urls: where-it-came-from -> database URL (an empty one means the SQLite file);
    storage: where-it-came-from -> STORAGE_BACKEND; production: DATABASE_URL in .env."""
    if test_postgres:
        host = make_url(_database_url(test_postgres)).host or ""
        if host.endswith(SUPABASE_HOSTS):
            return f"CHAMAPRO_TEST_POSTGRES_URL points at Supabase ({host})"
        if production and not make_url(_database_url(production)).get_backend_name() == "sqlite" \
                and _server(test_postgres) == _server(production):
            return "CHAMAPRO_TEST_POSTGRES_URL is the server DATABASE_URL in .env points at"
    for where, url in urls.items():
        u = make_url(_database_url(url))
        if u.get_backend_name() == "sqlite":
            if u.database and u.database != ":memory:" \
                    and Path(u.database).resolve().is_relative_to(data_dir.resolve()):
                return f"{where} is {u.database}, a working database in data/"
            continue
        if test_postgres and u == make_url(_database_url(test_postgres)):
            continue
        return (f"{where} points at {u.render_as_string(hide_password=True)}, "
                f"not SQLite or CHAMAPRO_TEST_POSTGRES_URL")
    for where, value in storage.items():
        if value != "local":
            return f"{where} is {value!r}, not 'local'"
    return None
