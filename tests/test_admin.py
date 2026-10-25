"""Administration: users and the audit log."""
import secrets
import sqlite3

import pytest
from fastapi.testclient import TestClient

from chamapro import config
from chamapro.api.main import app

from conftest import BASE_URL, assessed, guarantor, new_application, new_member


def login(username, password):
    c = TestClient(app, base_url=BASE_URL)
    return c, c.post("/api/auth/login", json={"username": username, "password": password})


def create(admin_client, role="officer", **extra):
    name, pw = "u_" + secrets.token_hex(4), secrets.token_urlsafe(16)
    r = admin_client.post("/api/admin/users", json={"username": name, "password": pw,
                                                    "role": role, **extra})
    assert r.status_code == 201, r.text
    return r.json(), pw


def audit(admin_client, **params):
    r = admin_client.get("/api/admin/audit", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_officers_are_refused(client):
    assert client.get("/api/admin/users").status_code == 403
    assert client.get("/api/admin/audit").status_code == 403


def test_create_list_and_sign_in(admin_client):
    u, pw = create(admin_client)
    assert u["role"] == "officer" and u["is_active"] and "password" not in str(u)
    listed = {x["username"]: x for x in admin_client.get("/api/admin/users").json()}
    assert listed[u["username"]]["id"] == u["id"]
    assert all("password" not in k and "hash" not in k for x in listed.values() for k in x)
    assert login(u["username"], pw)[1].status_code == 200


@pytest.mark.parametrize("bad", [{"password": "short"}, {"username": "x"}, {"role": "root"},
                                 {"email": "not-an-email"}])
def test_create_validation(admin_client, bad):
    body = {"username": "u_" + secrets.token_hex(4), "password": secrets.token_urlsafe(16), **bad}
    assert admin_client.post("/api/admin/users", json=body).status_code == 422


def test_duplicate_username_is_409(admin_client):
    u, _ = create(admin_client)
    r = admin_client.post("/api/admin/users", json={"username": u["username"],
                                                    "password": secrets.token_urlsafe(16)})
    assert r.status_code == 409


def test_deactivate_ends_sessions_and_blocks_sign_in(admin_client):
    u, pw = create(admin_client)
    c, _ = login(u["username"], pw)
    assert c.get("/api/interviews").status_code == 200
    r = admin_client.post(f"/api/admin/users/{u['id']}/deactivate")
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert c.get("/api/interviews").status_code == 401
    assert login(u["username"], pw)[1].status_code == 401
    assert admin_client.post(f"/api/admin/users/{u['id']}/activate").json()["is_active"] is True
    assert login(u["username"], pw)[1].status_code == 200


def test_admin_cannot_lock_themselves_out(admin_client):
    me = next(x for x in admin_client.get("/api/admin/users").json() if x["username"] == "admin1")
    assert admin_client.post(f"/api/admin/users/{me['id']}/deactivate").status_code == 409
    r = admin_client.put(f"/api/admin/users/{me['id']}/role", json={"role": "officer"})
    assert r.status_code == 409
    assert admin_client.get("/api/admin/users").status_code == 200


def test_reset_password(admin_client):
    u, old = create(admin_client)
    c, _ = login(u["username"], old)
    new = secrets.token_urlsafe(16)
    assert admin_client.put(f"/api/admin/users/{u['id']}/password",
                            json={"password": new}).status_code == 200
    assert c.get("/api/auth/me").status_code == 401                  # old session ended
    assert login(u["username"], old)[1].status_code == 401
    assert login(u["username"], new)[1].status_code == 200
    assert admin_client.put(f"/api/admin/users/{u['id']}/password",
                            json={"password": "short"}).status_code == 422


def test_change_role(admin_client):
    u, pw = create(admin_client)
    r = admin_client.put(f"/api/admin/users/{u['id']}/role", json={"role": "admin"})
    assert r.status_code == 200 and r.json()["role"] == "admin"
    c, _ = login(u["username"], pw)
    assert c.get("/api/admin/users").status_code == 200
    admin_client.put(f"/api/admin/users/{u['id']}/role", json={"role": "member"})
    c, _ = login(u["username"], pw)
    assert c.get("/api/interviews").status_code == 403


def test_link_google_email(admin_client):
    a, _ = create(admin_client)
    b, _ = create(admin_client)
    email = f"{a['username']}@Example.org"
    r = admin_client.put(f"/api/admin/users/{a['id']}/google-email", json={"email": email})
    assert r.status_code == 200 and r.json()["email"] == email.lower()
    r = admin_client.put(f"/api/admin/users/{b['id']}/google-email", json={"email": email})
    assert r.status_code == 409
    r = admin_client.put(f"/api/admin/users/{a['id']}/google-email", json={"email": None})
    assert r.json()["email"] is None


def test_link_member(admin_client):
    mid, no, _ = new_member(login=False)
    u, pw = create(admin_client, role="member", member_id=mid)
    assert (u["member_id"], u["member_no"]) == (mid, no)
    officer, _ = create(admin_client)
    r = admin_client.put(f"/api/admin/users/{officer['id']}/member", json={"member_id": mid})
    assert r.status_code == 422                                      # only member logins
    other, _ = create(admin_client, role="member")
    r = admin_client.put(f"/api/admin/users/{other['id']}/member", json={"member_id": mid})
    assert r.status_code == 409                                      # already linked
    r = admin_client.put(f"/api/admin/users/{u['id']}/member", json={"member_id": None})
    assert r.json()["member_id"] is None
    r = admin_client.put(f"/api/admin/users/{other['id']}/member", json={"member_id": mid})
    assert r.status_code == 200 and r.json()["member_id"] == mid


def test_unknown_user_is_404(admin_client):
    assert admin_client.post("/api/admin/users/999999/deactivate").status_code == 404


# --- Audit log ------------------------------------------------------------------------

def test_user_changes_are_audited_without_secrets(admin_client):
    u, pw = create(admin_client)
    admin_client.put(f"/api/admin/users/{u['id']}/password", json={"password": pw + "x"})
    admin_client.post(f"/api/admin/users/{u['id']}/deactivate")
    rows = audit(admin_client, entity="user", entity_id=u["id"])
    assert [r["action"] for r in rows] == ["user.deactivate", "user.reset_password", "user.create"]
    assert all(r["actor"] == "admin1" for r in rows)
    assert pw not in str(rows) and "scrypt" not in str(rows)


def test_application_lifecycle_is_audited(client, admin_client):
    mid, _, mc = new_member()
    iid = assessed(client)
    app_ = new_application(client, mid, iid)
    client.post(f"/api/applications/{app_['id']}/decision",
                json={"outcome": "approve_with_guarantor", "officer_notes": "secret note"})
    mc.post(f"/api/me/applications/{app_['id']}/guarantors",
            json={"guarantors": [guarantor(1), guarantor(2)]})
    g = client.get(f"/api/applications/{app_['id']}").json()["guarantors"]
    client.post(f"/api/guarantors/{g[0]['id']}/verify")
    client.post(f"/api/guarantors/{g[1]['id']}/reject", json={"reason": "not a member"})

    rows = audit(admin_client, entity="loan_application", entity_id=app_["id"])
    assert [(r["action"], r["details"].get("to")) for r in reversed(rows)] == [
        ("application.create", None), ("application.link_interview", None),
        ("application.status", "assessed"), ("application.status", "guarantor_required"),
        ("application.status", "guarantor_submitted"), ("application.status", "guarantor_required")]
    decision = audit(admin_client, action="decision.create")
    assert any(r["details"]["application_id"] == app_["id"] for r in decision)
    assert "secret note" not in str(audit(admin_client, limit=500))
    kinds = [r["action"] for r in audit(admin_client, action="guarantor.") if
             r["details"].get("application_id") == app_["id"]]
    assert sorted(kinds) == ["guarantor.reject", "guarantor.submit", "guarantor.submit",
                             "guarantor.verify"]
    reject = next(r for r in audit(admin_client, action="guarantor.reject")
                  if r["entity_id"] == g[1]["id"])
    assert reject["details"]["reason"] == "not a member" and reject["actor"] == "officer1"


def test_interview_and_response_changes_are_audited(client, admin_client):
    iid = assessed(client)
    rows = audit(admin_client, entity="interview", entity_id=iid)
    assert [r["action"] for r in rows] == ["interview.create"]
    resp = [r for r in audit(admin_client, action="response.create")
            if r["details"]["interview_id"] == iid]
    assert len(resp) == 1 and resp[0]["details"]["source"] == "typed"


def test_audit_filters(admin_client):
    u, _ = create(admin_client)
    me = next(x for x in admin_client.get("/api/admin/users").json() if x["username"] == "admin1")
    mine = audit(admin_client, actor_user_id=me["id"], action="user.create")
    assert any(r["entity_id"] == u["id"] for r in mine)
    created = next(r for r in mine if r["entity_id"] == u["id"])["created_at"]
    assert audit(admin_client, since="2999-01-01T00:00:00") == []
    assert any(r["entity_id"] == u["id"] for r in audit(admin_client, since=created[:19]))
    assert len(audit(admin_client, limit=1)) == 1
    assert admin_client.get("/api/admin/audit", params={"limit": 0}).status_code == 422


@pytest.mark.parametrize("sql", ["UPDATE audit_log SET action = 'x'", "DELETE FROM audit_log"])
def test_audit_log_is_append_only_in_the_database(admin_client, sql):
    create(admin_client)
    con = sqlite3.connect(config.DB_PATH, isolation_level=None)
    try:
        before = con.execute("SELECT count(*) FROM audit_log").fetchone()
        with pytest.raises(sqlite3.IntegrityError, match="audit_log is append-only"):
            con.execute(sql)
        assert con.execute("SELECT count(*) FROM audit_log").fetchone() == before
    finally:
        con.close()
