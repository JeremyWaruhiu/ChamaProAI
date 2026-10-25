"""Members see only their own applications and guarantors, never a staff
endpoint, and never what the officer wrote for staff or the model's numbers."""
import json
import re

import pytest

from conftest import api_operations, assessed, guarantor, new_application, new_member

OFFICER_NOTE = "Officer-only: brother is in arrears, keep an eye on it"
MESSAGE = "You need two guarantors before we can pay out."
MEMBER_ROUTES = {("GET", "/api/me/applications"), ("GET", "/api/me/applications/{application_id}"),
                 ("POST", "/api/me/applications/{application_id}/guarantors"),
                 ("GET", "/api/auth/me"), ("POST", "/api/auth/logout")}
PUBLIC = {("GET", "/api/health"), ("POST", "/api/auth/login"), ("GET", "/api/auth/config"),
          ("POST", "/api/auth/google")}


@pytest.fixture
def two_members(client):
    """Two members, each with a decided application needing guarantors; the
    first has submitted theirs."""
    out = []
    for _ in range(2):
        mid, no, mc = new_member()
        app_ = new_application(client, mid, assessed(client))
        r = client.post(f"/api/applications/{app_['id']}/decision",
                        json={"outcome": "approve_with_guarantor", "officer_notes": OFFICER_NOTE,
                              "member_message": MESSAGE})
        assert r.status_code == 201, r.text
        out.append({"member_id": mid, "member_no": no, "client": mc, "app_id": app_["id"]})
    a = out[0]
    r = a["client"].post(f"/api/me/applications/{a['app_id']}/guarantors",
                         json={"guarantors": [guarantor(1), guarantor(2)]})
    assert r.status_code == 201, r.text
    return out


def staff_routes():
    return ((m, path) for m, path in api_operations() if (m, path) not in MEMBER_ROUTES | PUBLIC)


def test_member_sees_only_their_own_list(two_members):
    a, b = two_members
    assert [x["id"] for x in a["client"].get("/api/me/applications").json()] == [a["app_id"]]
    assert [x["id"] for x in b["client"].get("/api/me/applications").json()] == [b["app_id"]]


def test_member_cannot_read_another_members_application(two_members):
    a, b = two_members
    r = b["client"].get(f"/api/me/applications/{a['app_id']}")
    assert r.status_code == 404 and r.json() == {"detail": f"application {a['app_id']} not found"}
    assert b["client"].get("/api/me/applications/999999").json() == \
        {"detail": "application 999999 not found"}                # same answer: no probing


def test_member_cannot_see_or_add_another_members_guarantors(two_members):
    a, b = two_members
    r = b["client"].post(f"/api/me/applications/{a['app_id']}/guarantors",
                         json={"guarantors": [guarantor(3)]})
    assert r.status_code == 404
    own = json.dumps(b["client"].get(f"/api/me/applications/{b['app_id']}").json())
    theirs = a["client"].get(f"/api/me/applications/{a['app_id']}").json()["guarantors"]
    assert len(theirs) == 2 and all(g["member_no"] not in own for g in theirs)


@pytest.mark.parametrize("method,path", sorted(staff_routes()))
def test_member_is_refused_every_staff_endpoint(two_members, method, path):
    url = re.sub(r"\{[a-z_]+\}", str(two_members[0]["app_id"]), path)
    r = two_members[0]["client"].request(method, url)
    assert r.status_code == 403, f"{method} {path} -> {r.status_code}"


def test_staff_routes_include_the_obvious_ones():
    routes = set(staff_routes())
    for expected in [("GET", "/api/applications/{application_id}"), ("GET", "/api/members"),
                     ("POST", "/api/guarantors/{guarantor_id}/verify"),
                     ("GET", "/api/interviews"), ("GET", "/api/admin/users"),
                     ("GET", "/api/admin/audit"), ("GET", "/api/results")]:
        assert expected in routes


def test_staff_are_refused_member_endpoints(client, admin_client):
    for c in (client, admin_client):
        assert c.get("/api/me/applications").status_code == 403


def test_member_without_a_record_sees_nothing(client):
    from conftest import PASSWORDS, add_user, signed_in
    PASSWORDS["m_unlinked"] = "unlinked-password-123"
    add_user("m_unlinked", PASSWORDS["m_unlinked"], role="member")
    c = signed_in("m_unlinked")
    assert c.get("/api/me/applications").json() == []
    assert c.get("/api/auth/me").json() == {"username": "m_unlinked", "role": "member"}


def test_member_view_has_no_notes_numbers_or_feature_names(two_members):
    a = two_members[0]
    r = a["client"].get(f"/api/me/applications/{a['app_id']}")
    body = r.json()
    text = r.text
    assert OFFICER_NOTE not in text
    for word in ("officer_notes", "note", "probabilit", "risk_class", "shap", "feature",
                 "B3A__", "E3B__", "log_monthly_income", "is_female", "Medium", "0.5",
                 "decided_by", "verified_by", "model"):
        assert word not in text, word
    assert body["member_message"] == MESSAGE
    assert body["outcome"] == "approve_with_guarantor" and body["guarantors_required"] == 2
    assert body["reasons"] == [
        "Your regular farm income counted in your favour.",
        "Your monthly household income counted in your favour.",
        "Having lost money as a SACCO guarantor before counted against your application.",
    ]                                     # sex and age, though large, are never given as reasons
    assert [t["status"] for t in body["timeline"]] == ["draft", "assessed", "guarantor_required",
                                                       "guarantor_submitted"]
    assert all(set(t) == {"status", "label", "at"} for t in body["timeline"])


def test_guarantor_submission_response_has_no_notes(client):
    mid, _, mc = new_member()
    app_ = new_application(client, mid, assessed(client))
    client.post(f"/api/applications/{app_['id']}/decision",
                json={"outcome": "approve_with_guarantor", "officer_notes": OFFICER_NOTE})
    r = mc.post(f"/api/me/applications/{app_['id']}/guarantors",
                json={"guarantors": [guarantor(1), guarantor(2)]})
    assert r.status_code == 201 and OFFICER_NOTE not in r.text and "officer_notes" not in r.text
    assert r.json()["member_message"].startswith("Your loan can be approved once 2 guarantor")


def test_officer_sees_the_notes(client, two_members):
    d = client.get(f"/api/applications/{two_members[0]['app_id']}").json()["decision"]
    assert d["officer_notes"] == OFFICER_NOTE and d["member_message"] == MESSAGE


def test_no_reasons_before_a_decision(client):
    mid, _, mc = new_member()
    app_ = new_application(client, mid, assessed(client))
    body = mc.get(f"/api/me/applications/{app_['id']}").json()
    assert body["status"] == "assessed" and body["reasons"] == [] and body["outcome"] is None
    assert body["status_label"] == "Being reviewed by a loan officer"
