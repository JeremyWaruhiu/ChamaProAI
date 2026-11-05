"""Members see only their own applications and guarantors, never a staff
endpoint, and never what the officer wrote for staff or the model's numbers."""
import re

import pytest

from conftest import api_operations, assessed, guarantor, new_application, new_member

OFFICER_NOTE = "Officer-only: brother is in arrears, keep an eye on it"
MESSAGE = "You need two guarantors before we can pay out."
MEMBER_ROUTES = {("GET", "/api/me/applications"), ("GET", "/api/me/applications/{application_id}"),
                 ("POST", "/api/me/applications/{application_id}/guarantors"),
                 ("GET", "/api/auth/me"), ("POST", "/api/auth/logout"),
                 # your own account: every role
                 ("GET", "/api/auth/profile"), ("POST", "/api/auth/password"),
                 ("POST", "/api/auth/logout-all"),
                 # a member's own record, loan application and practice interviews
                 ("GET", "/api/me/home"), ("GET", "/api/me/member"), ("PATCH", "/api/me/member"),
                 ("POST", "/api/me/consent"), ("GET", "/api/me/apply-options"),
                 ("GET", "/api/me/sacco"), ("POST", "/api/me/profile"), ("PATCH", "/api/me/profile"),
                 ("POST", "/api/me/profile/confirm"),
                 ("GET", "/api/me/applications/{application_id}/guarantor-offers"),
                 ("POST", "/api/me/applications/{application_id}/guarantors/pledged"),
                 ("POST", "/api/me/applications"),
                 ("POST", "/api/me/applications/{application_id}/booking"),
                 ("POST", "/api/me/applications/{application_id}/practice"),
                 ("GET", "/api/me/practice/{interview_id}"),
                 ("POST", "/api/me/practice/{interview_id}/responses"),
                 ("POST", "/api/me/practice/{interview_id}/responses/typed"),
                 ("POST", "/api/me/practice/{interview_id}/submit"),
                 ("POST", "/api/me/practice/{interview_id}/sus"),
                 ("GET", "/api/me/practice/responses/{response_id}/audio"),
                 ("PATCH", "/api/me/practice/responses/{response_id}"),
                 ("DELETE", "/api/me/practice/responses/{response_id}"),
                 # the self-service decision, always on the member's own record
                 ("POST", "/api/self-service/evaluate"), ("POST", "/api/self-service/commit"),
                 ("POST", "/api/self-service/applications/{application_id}/accept"),
                 ("POST", "/api/self-service/applications/{application_id}/decline"),
                 ("POST", "/api/self-service/applications/{application_id}/review"),
                 # the conversation, on the member's own record; and a guarantor's own ceiling
                 ("POST", "/api/conversations"), ("GET", "/api/conversations/{conversation_id}"),
                 ("POST", "/api/conversations/{conversation_id}/reply"), ("GET", "/api/conversations/current"),
                 ("GET", "/api/conversations/{conversation_id}/stage"),
                 ("GET", "/api/conversations/{conversation_id}/turns/{seq}/audio"),
                 ("PATCH", "/api/me/pledges/{pledge_id}"),
                 # the booking calendar and upcoming events: every signed-in role
                 ("GET", "/api/booking/calendar"), ("GET", "/api/booking/slots"),
                 ("GET", "/api/events")}
PUBLIC = {("GET", "/api/health"), ("POST", "/api/auth/login"), ("GET", "/api/auth/config"),
          ("POST", "/api/auth/google"), ("GET", "/api/auth/signup"), ("POST", "/api/auth/signup")}

# Fields of the officer's application view (schemas.ApplicationDetail and what it
# nests) that carry the model's numbers, what staff wrote, or who did what. Each
# must exist in the officer payload (so this list cannot go stale) and nowhere in
# the member's, at any depth.
OFFICER_ONLY = {
    # the assessment
    "assessment", "risk_class", "probabilities", "feature_vector", "contributions", "feature", "shap",
    "extracted", "applicant_form", "extraction_completeness", "features_populated", "features_total",
    "features_not_extractable", "extraction_model", "model_file", "model_sha256", "assessed_by",
    # the SACCO rule beside it
    "comparator", "conditions", "agreement",
    # the decision and the guarantor checks
    "officer_notes", "note", "decided_by", "verified_by", "verified_at", "created_by",
}
# Feature names as the classifier stores them: distinctive enough to search for in text.
FEATURE_SENTINELS = ("B3A__", "E3B__", "log_monthly_income", "is_female")


def walk(obj, path="$", key=None):
    """Every (path, key, value) in a parsed JSON body, the body itself and every
    nested object, list and list item included; key is None for those without one."""
    yield path, key, obj
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from walk(v, f"{path}.{k}", k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            yield from walk(v, f"{path}[{i}]")


def keys(obj) -> set[str]:
    return {k for _, k, _ in walk(obj) if k is not None}


def leaks(body) -> list[str]:
    """What in a member-facing body should only ever be shown to staff."""
    out = [f"{p}: officer-only field" for p, k, _ in walk(body) if k in OFFICER_ONLY]
    for p, _, v in walk(body):
        # Scores, probabilities and SHAP values are floats; every number a member
        # sees (amounts, counts, ids) is a whole number.
        if isinstance(v, float):
            out.append(f"{p}: number {v}")
        if isinstance(v, str) and (OFFICER_NOTE in v or any(f in v for f in FEATURE_SENTINELS)):
            out.append(f"{p}: {v!r}")
    return out


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
    own = b["client"].get(f"/api/me/applications/{b['app_id']}").json()
    theirs = a["client"].get(f"/api/me/applications/{a['app_id']}").json()["guarantors"]
    seen = {v for _, k, v in walk(own) if k == "member_no"}
    assert len(theirs) == 2 and own["guarantors"] == []
    assert not seen & {g["member_no"] for g in theirs}


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
    assert c.get("/api/auth/me").json() == {"username": "m_unlinked", "role": "member",
                                                 "display_name": None}


def test_member_view_has_no_notes_numbers_or_feature_names(client, two_members):
    a = two_members[0]
    staff = client.get(f"/api/applications/{a['app_id']}").json()
    assert OFFICER_ONLY <= keys(staff), OFFICER_ONLY - keys(staff)      # the list is real
    assert staff["decision"]["officer_notes"] == OFFICER_NOTE

    for body in (a["client"].get(f"/api/me/applications/{a['app_id']}").json(),
                 a["client"].get("/api/me/applications").json()):
        assert leaks(body) == []
    body = a["client"].get(f"/api/me/applications/{a['app_id']}").json()
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
    assert r.status_code == 201 and leaks(r.json()) == []
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


def test_the_leak_check_catches_what_it_is_for():
    """leaks() itself: officer fields at any depth, any float, the note, feature names."""
    assert leaks({"id": 3, "created_at": "2026-10-27T02:16:50.507010Z", "amount": 30000}) == []
    found = leaks({"timeline": [{"status": "assessed", "extra": {"probabilities": {"Low": 0.2}}}],
                   "score": 0.37, "reasons": [f"see {OFFICER_NOTE}", "is_female counted"]})
    assert found == ["$.timeline[0].extra.probabilities: officer-only field",
                     "$.timeline[0].extra.probabilities.Low: number 0.2", "$.score: number 0.37",
                     f"$.reasons[0]: {f'see {OFFICER_NOTE}'!r}", "$.reasons[1]: 'is_female counted'"]
