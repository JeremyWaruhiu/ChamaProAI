"""Members, loan applications, decisions with outcomes, guarantors, and the
application status following its interview."""
import pytest

from conftest import assessed, guarantor, new_application, new_interview, new_member


def typed(client, interview_id, n, text="An answer."):
    r = client.post(f"/api/interviews/{interview_id}/responses/typed",
                    json={"sentence_no": n, "text": text})
    assert r.status_code == 201, r.text
    return r.json()


def decide(client, app_id, outcome, **fields):
    return client.post(f"/api/applications/{app_id}/decision", json={"outcome": outcome, **fields})


# --- Members ------------------------------------------------------------------------

def test_member_crud_and_search(client):
    body = {"member_no": "CRUD-001", "full_name": "Wanjiku Kamau (fictional)",
            "phone": "0712 345 678", "joined_on": "2021-03-01"}
    r = client.post("/api/members", json=body)
    assert r.status_code == 201, r.text
    m = r.json()
    assert m["phone"] == "0712345678" and m["user_id"] is None
    assert "national_id" not in m and "id_number" not in m           # never collected

    assert client.post("/api/members", json=body).status_code == 409   # member_no unique
    assert [x["id"] for x in client.get("/api/members", params={"q": "wanjiku"}).json()] == [m["id"]]
    assert [x["id"] for x in client.get("/api/members", params={"q": "crud-0"}).json()] == [m["id"]]
    assert client.get("/api/members", params={"q": "nobody-like-this"}).json() == []
    assert client.get("/api/members", params={"q": "%"}).json() == []      # literal, not a wildcard

    r = client.patch(f"/api/members/{m['id']}", json={"full_name": "Wanjiku K. (fictional)"})
    assert r.status_code == 200 and r.json()["full_name"] == "Wanjiku K. (fictional)"
    assert client.patch(f"/api/members/{m['id']}", json={"joined_on": None}).status_code == 422
    assert client.get(f"/api/members/{m['id']}").json()["joined_on"] == "2021-03-01"

    assert client.delete(f"/api/members/{m['id']}").status_code == 204
    assert client.get(f"/api/members/{m['id']}").status_code == 404


@pytest.mark.parametrize("bad", [{"phone": "12345"}, {"joined_on": "2999-01-01"},
                                 {"member_no": "has space"}, {"full_name": "  "},
                                 {"national_id": "12345678"}])
def test_member_validation(client, bad):
    body = {"member_no": "VAL-1", "full_name": "A", "joined_on": "2020-01-01", **bad}
    assert client.post("/api/members", json=body).status_code == 422


def test_member_with_applications_cannot_be_deleted(client):
    mid, _, _ = new_member(login=False)
    new_application(client, mid)
    assert client.delete(f"/api/members/{mid}").status_code == 409


# --- Applications --------------------------------------------------------------------

def test_application_follows_its_interview(client):
    mid, _, _ = new_member(login=False)
    app = new_application(client, mid)
    assert app["status"] == "draft" and app["comparator"] is None

    iid = new_interview(client)
    r = client.put(f"/api/applications/{app['id']}/interview", json={"interview_id": iid})
    assert r.status_code == 200 and r.json()["status"] == "interview_pending"

    for n in range(1, 9):                                  # all eight v2 questions answered
        typed(client, iid, n)
    detail = client.get(f"/api/applications/{app['id']}").json()
    assert detail["status"] == "interview_complete"
    assert [t["status"] for t in detail["timeline"]] == ["draft", "interview_pending",
                                                         "interview_complete"]
    rid = client.get(f"/api/interviews/{iid}").json()["responses"][0]["id"]
    assert client.delete(f"/api/responses/{rid}").status_code == 200   # re-record: back a step
    assert client.get(f"/api/applications/{app['id']}").json()["status"] == "interview_pending"
    assert client.get(f"/api/interviews/{iid}").json()["application_id"] == app["id"]


def test_linking_an_assessed_interview_marks_it_assessed_with_comparator(client):
    mid, _, _ = new_member(login=False)
    app = new_application(client, mid, assessed(client), amount=30000, savings=15000)
    assert app["status"] == "assessed"
    c = app["comparator"]
    assert c is not None and app["assessment"]["comparator"] == c
    assert c["max_borrowable_kes"] == 45000
    by = {x["name"]: x for x in c["conditions"]}
    assert by["savings_multiple"]["result"] == "pass"
    assert by["guarantors"]["result"] == "pending"           # none submitted yet: not failed
    assert by["tenure"]["result"] == "pass"
    assert c["rule_recommendation"] == "approve_with_guarantors"
    assert c["model_recommendation"] == "refer" and c["agreement"] == "undetermined"


def test_interview_state_carries_the_comparator(client):
    mid, _, _ = new_member(login=False)
    iid = assessed(client, risk_class="Low")
    app = new_application(client, mid, iid, amount=100000, savings=10000)
    st = client.get(f"/api/interviews/{iid}").json()
    c = st["assessment"]["comparator"]
    assert st["application_id"] == app["id"] and c["result"] == "fail"
    assert c["rule_recommendation"] == "decline" and c["agreement"] == "diverge"


def test_legacy_interview_has_no_comparator(client):
    st = client.get(f"/api/interviews/{assessed(client)}").json()
    assert st["application_id"] is None and st["assessment"]["comparator"] is None


def test_one_interview_one_application(client):
    mid, _, _ = new_member(login=False)
    iid = new_interview(client)
    new_application(client, mid, iid)
    r = client.post("/api/applications", json={"member_id": mid, "amount_requested_kes": 1000,
                                               "purpose": "x", "term_months": 3,
                                               "sacco_savings_kes": 0, "interview_id": iid})
    assert r.status_code == 409 and "already belongs" in r.json()["detail"]


def test_interview_cannot_change_after_assessment(client):
    mid, _, _ = new_member(login=False)
    app = new_application(client, mid, assessed(client))
    r = client.put(f"/api/applications/{app['id']}/interview",
                   json={"interview_id": new_interview(client)})
    assert r.status_code == 409


def test_list_and_filter(client):
    mid, _, _ = new_member(login=False)
    a = new_application(client, mid)
    b = new_application(client, mid, assessed(client))
    mine = client.get("/api/applications", params={"member_id": mid}).json()
    assert [x["id"] for x in mine] == [b["id"], a["id"]]           # newest first
    drafts = client.get("/api/applications", params={"status": "draft", "member_id": mid}).json()
    assert [x["id"] for x in drafts] == [a["id"]]
    assert client.get("/api/applications", params={"status": "nonsense"}).status_code == 422


def test_create_application_validation(client):
    mid, _, _ = new_member(login=False)
    base = {"member_id": mid, "amount_requested_kes": 1000, "purpose": "x", "term_months": 3,
            "sacco_savings_kes": 0}
    for bad in ({"amount_requested_kes": 0}, {"term_months": 0}, {"sacco_savings_kes": -1},
                {"purpose": " "}, {"member_id": 999999}):
        assert client.post("/api/applications", json={**base, **bad}).status_code == 422, bad


# --- Decisions ------------------------------------------------------------------------

def test_approve_sets_amount_and_status(client):
    mid, _, _ = new_member(login=False)
    app = new_application(client, mid, assessed(client), amount=30000)
    r = decide(client, app["id"], "approve", officer_notes="Known member.",
               member_message="Approved. Collect at the branch.")
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["status"] == "approved" and d["outcome"] == "approve"
    assert d["decision"]["approved_amount_kes"] == 30000
    assert d["decision"]["decision"] == "approve" and d["decision"]["officer_notes"] == "Known member."


def test_approve_with_guarantor_sets_status_and_count(client):
    mid, _, _ = new_member(login=False)
    app = new_application(client, mid, assessed(client))
    d = decide(client, app["id"], "approve_with_guarantor", guarantors_required=3).json()
    assert d["status"] == "guarantor_required"
    assert d["decision"]["guarantors_required"] == 3 and d["decision"]["decision"] == "approve"


def test_approve_with_guarantor_defaults_to_two(client):
    mid, _, _ = new_member(login=False)
    app = new_application(client, mid, assessed(client))
    assert decide(client, app["id"], "approve_with_guarantor").json()["decision"][
        "guarantors_required"] == 2


@pytest.mark.parametrize("amount, code", [(None, 422), (30000, 422), (40000, 422), (20000, 201)])
def test_approve_reduced_needs_an_amount_below_the_request(client, amount, code):
    mid, _, _ = new_member(login=False)
    app = new_application(client, mid, assessed(client), amount=30000)
    r = decide(client, app["id"], "approve_reduced",
               **({} if amount is None else {"approved_amount_kes": amount}))
    assert r.status_code == code, r.text
    if code == 201:
        assert r.json()["status"] == "approved"
        assert r.json()["decision"]["approved_amount_kes"] == 20000


@pytest.mark.parametrize("outcome, status", [("refer", "decided"), ("decline", "declined")])
def test_refer_and_decline(client, outcome, status):
    mid, _, _ = new_member(login=False)
    app = new_application(client, mid, assessed(client))
    r = decide(client, app["id"], outcome)
    assert r.status_code == 201 and r.json()["status"] == status


@pytest.mark.parametrize("fields", [{"outcome": "refer", "approved_amount_kes": 100},
                                    {"outcome": "approve", "guarantors_required": 2},
                                    {"outcome": "approve", "approved_amount_kes": 1},
                                    {"outcome": "approve", "decision": "decline"}])
def test_inconsistent_decisions_are_422(client, fields):
    mid, _, _ = new_member(login=False)
    app = new_application(client, mid, assessed(client))
    assert client.post(f"/api/applications/{app['id']}/decision", json=fields).status_code == 422


def test_decision_needs_an_assessed_application(client):
    mid, _, _ = new_member(login=False)
    app = new_application(client, mid, new_interview(client))
    assert decide(client, app["id"], "approve").status_code == 409
    assert decide(client, new_application(client, mid)["id"], "approve").status_code == 409


def test_interview_endpoint_moves_the_application_too(client):
    mid, _, _ = new_member(login=False)
    iid = assessed(client)
    app = new_application(client, mid, iid)
    r = client.post(f"/api/interviews/{iid}/decision", json={"decision": "decline", "note": "n"})
    assert r.status_code == 201 and r.json()["outcome"] == "decline"
    assert client.get(f"/api/applications/{app['id']}").json()["status"] == "declined"


def test_reduced_and_guarantor_outcomes_need_an_application(client):
    iid = assessed(client)
    for body in ({"outcome": "approve_reduced", "approved_amount_kes": 5},
                 {"outcome": "approve_with_guarantor"}):
        assert client.post(f"/api/interviews/{iid}/decision", json=body).status_code == 422


def test_second_decision_is_409(client):
    mid, _, _ = new_member(login=False)
    app = new_application(client, mid, assessed(client))
    assert decide(client, app["id"], "refer").status_code == 201
    assert decide(client, app["id"], "approve").status_code == 409


# --- Guarantors --------------------------------------------------------------------------

@pytest.fixture
def needs_guarantors(client):
    """(application id, member_no, member client) awaiting two guarantors."""
    mid, no, mc = new_member()
    app = new_application(client, mid, assessed(client), amount=30000)
    assert decide(client, app["id"], "approve_with_guarantor").status_code == 201
    return app["id"], no, mc


def submit(mc, app_id, *gs):
    return mc.post(f"/api/me/applications/{app_id}/guarantors", json={"guarantors": list(gs)})


def test_guarantor_flow_to_approval(client, needs_guarantors):
    app_id, _, mc = needs_guarantors
    r = submit(mc, app_id, guarantor(1), guarantor(2))
    assert r.status_code == 201, r.text
    assert r.json()["status"] == "guarantor_submitted"

    detail = client.get(f"/api/applications/{app_id}").json()
    g1, g2 = detail["guarantors"]
    assert detail["comparator"]["conditions"][1]["result"] == "pending"
    v = client.post(f"/api/guarantors/{g1['id']}/verify")
    assert v.status_code == 200 and v.json()["status"] == "verified"
    assert v.json()["verified_by"] == "officer1"
    assert client.get(f"/api/applications/{app_id}").json()["status"] == "guarantor_submitted"

    assert client.post(f"/api/guarantors/{g2['id']}/verify").status_code == 200
    detail = client.get(f"/api/applications/{app_id}").json()
    assert detail["status"] == "approved"
    assert detail["comparator"]["conditions"][1]["result"] == "pass"
    assert [t["status"] for t in detail["timeline"]][-3:] == ["guarantor_required",
                                                             "guarantor_submitted", "approved"]
    assert client.post(f"/api/guarantors/{g2['id']}/verify").status_code == 409   # once


def test_rejected_guarantor_is_replaced(client, needs_guarantors):
    app_id, _, mc = needs_guarantors
    submit(mc, app_id, guarantor(1), guarantor(2))
    g1, g2 = client.get(f"/api/applications/{app_id}").json()["guarantors"]
    client.post(f"/api/guarantors/{g1['id']}/verify")
    r = client.post(f"/api/guarantors/{g2['id']}/reject", json={"reason": "phone unreachable"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    mine = mc.get(f"/api/me/applications/{app_id}").json()
    assert mine["status"] == "guarantor_required" and mine["guarantors_still_needed"] == 1

    assert submit(mc, app_id, guarantor(3), guarantor(4)).status_code == 422   # exactly one
    assert submit(mc, app_id, guarantor(3)).status_code == 201
    g3 = client.get(f"/api/applications/{app_id}").json()["guarantors"][-1]
    client.post(f"/api/guarantors/{g3['id']}/verify")
    assert client.get(f"/api/applications/{app_id}").json()["status"] == "approved"


def test_guarantors_only_when_required(client):
    mid, _, mc = new_member()
    app = new_application(client, mid, assessed(client))
    assert submit(mc, app["id"], guarantor(1), guarantor(2)).status_code == 409   # assessed
    decide(client, app["id"], "approve")
    assert submit(mc, app["id"], guarantor(1), guarantor(2)).status_code == 409   # approved


@pytest.mark.parametrize("problem", ["count", "self", "duplicate", "amount", "phone", "blank"])
def test_guarantor_validation(client, needs_guarantors, problem):
    app_id, own_no, mc = needs_guarantors
    a, b = guarantor(1), guarantor(2)
    gs = {"count": [a],
          "self": [a, {**b, "member_no": own_no}],
          "duplicate": [a, {**b, "member_no": a["member_no"]}],
          "amount": [a, {**b, "amount_guaranteed_kes": 30001}],
          "phone": [a, {**b, "phone": "999"}],
          "blank": [a, {**b, "relationship": "  "}]}[problem]
    assert submit(mc, app_id, *gs).status_code == 422
    assert mc.get(f"/api/me/applications/{app_id}").json()["status"] == "guarantor_required"


def test_pending_guarantor_can_be_verified_while_a_replacement_is_awaited(client, needs_guarantors):
    app_id, _, mc = needs_guarantors
    submit(mc, app_id, guarantor(1), guarantor(2))
    g1, g2 = client.get(f"/api/applications/{app_id}").json()["guarantors"]
    client.post(f"/api/guarantors/{g1['id']}/reject")       # 1 left, 2 needed: back to required
    assert client.post(f"/api/guarantors/{g2['id']}/verify").status_code == 200
    assert client.get(f"/api/applications/{app_id}").json()["status"] == "guarantor_required"
    assert mc.get(f"/api/me/applications/{app_id}").json()["guarantors_still_needed"] == 1
    assert client.post("/api/guarantors/999999/verify").status_code == 404

