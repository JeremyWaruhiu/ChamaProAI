"""The built dashboard served by the API at /, beside /api on one origin."""
import pytest

from chamapro import config


@pytest.fixture
def dist(monkeypatch, tmp_path):
    """A stand-in for frontend/dist after npm run build."""
    d = tmp_path / "dist"
    (d / "assets").mkdir(parents=True)
    (d / "index.html").write_text("<!doctype html><div id=root></div>")
    (d / "assets" / "index-abc123.js").write_text("console.log('app')")
    (d / "favicon.svg").write_text("<svg/>")
    (tmp_path / "secret.txt").write_text("not for the web")
    monkeypatch.setattr(config, "FRONTEND_DIST", d)
    return d


def test_root_and_client_routes_get_the_app(anon_client, dist):
    for path in ("/", "/login", "/applications/12", "/me/applications/3/guarantors"):
        r = anon_client.get(path)
        assert r.status_code == 200, path
        assert "id=root" in r.text and r.headers["cache-control"] == "no-cache"


def test_files_are_served_and_hashed_assets_cached(anon_client, dist):
    r = anon_client.get("/assets/index-abc123.js")
    assert r.status_code == 200 and r.text == "console.log('app')"
    assert "immutable" in r.headers["cache-control"]
    r = anon_client.get("/favicon.svg")
    assert r.status_code == 200 and r.headers["cache-control"] == "no-cache"


def test_api_paths_are_never_the_app(anon_client, dist):
    for path in ("/api", "/api/", "/api/nope", "/api/interviews/1/nope"):
        r = anon_client.get(path)
        assert r.status_code == 404, path
        assert r.json() == {"detail": "Not Found"}
    assert anon_client.get("/api/health").json()["status"] in ("ok", "degraded")
    assert anon_client.get("/api/auth/me").status_code == 401


def test_nothing_outside_dist_is_served(anon_client, dist):
    for path in ("/../secret.txt", "/%2e%2e/secret.txt", "/assets/..%2f..%2fsecret.txt"):
        assert "not for the web" not in anon_client.get(path).text, path


def test_without_a_build_there_is_no_app(anon_client, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "FRONTEND_DIST", tmp_path / "missing")
    assert anon_client.get("/").status_code == 404
    assert anon_client.get("/login").status_code == 404


def test_the_app_is_not_in_the_api_schema(anon_client, dist):
    assert not [p for p in anon_client.get("/openapi.json").json()["paths"]
                if not p.startswith("/api/")]
