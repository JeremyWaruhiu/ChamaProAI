"""CORS: open to the dashboard on localhost, closed to everyone else."""
import pytest

PREFLIGHT = {"Access-Control-Request-Method": "POST"}


@pytest.mark.parametrize("origin", ["http://localhost:5173", "http://127.0.0.1:3000",
                                    "http://localhost"])
def test_localhost_origins_are_allowed(client, origin):
    r = client.options("/api/interviews", headers={"Origin": origin, **PREFLIGHT})
    assert r.status_code == 200
    assert r.headers["access-control-allow-origin"] == origin
    assert "POST" in r.headers["access-control-allow-methods"]

    r = client.get("/api/health", headers={"Origin": origin})
    assert r.headers["access-control-allow-origin"] == origin


@pytest.mark.parametrize("origin", ["https://evil.example", "http://localhost.evil.example",
                                    "http://192.168.1.10:5173"])
def test_other_origins_are_refused(client, origin):
    r = client.options("/api/interviews", headers={"Origin": origin, **PREFLIGHT})
    assert r.status_code == 400
    assert "access-control-allow-origin" not in r.headers

    r = client.get("/api/health", headers={"Origin": origin})
    assert "access-control-allow-origin" not in r.headers
