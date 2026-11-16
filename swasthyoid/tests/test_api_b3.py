"""B3 over HTTP: the patient's C3 inbox. Synthetic people only."""
import json

from swasthyoid.core import notification
from swasthyoid.tests.test_api_b2 import cast, qr_request  # noqa: F401
from swasthyoid.tests.test_api_m1 import PATIENT, PROFILE, V1, api, login, people, request_consent  # noqa: F401

CAREGIVER = "+8801700000005"


def inbox(api, headers):  # noqa: F811
    r = api.http.get(f"{V1}/notifications", headers=headers)
    assert r.status_code == 200, r.text
    return r.json()


def test_requests_and_grants_reach_the_inbox_with_names_and_categories_but_no_secrets(api, cast):  # noqa: F811
    otp_req = request_consent(api, cast, categories=["timeline", "documents"]).json()
    qr = qr_request(api, cast)
    api.http.post(f"{V1}/consents/requests/{otp_req['id']}/confirm", headers=cast.doctor, json={"code": api.codes[PATIENT]})
    carer = login(api, CAREGIVER, profile={**PROFILE, "name": "Synthetic Carer"})
    r = api.http.post(f"{V1}/caregiver-authorizations", headers=carer,
                      json={"patient_health_id": cast.health_id, "scopes": ["view_timeline"]})
    assert r.status_code == 202, r.text

    items = inbox(api, cast.patient)
    kinds = [i["kind"] for i in items]
    assert kinds == ["caregiver_request", "consent_granted", "consent_request", "consent_request"]  # newest first
    by_kind = {i["kind"]: i for i in reversed(items)}
    assert (by_kind["caregiver_request"]["actor_name"], by_kind["caregiver_request"]["categories"]) == \
        ("Synthetic Carer", ["view_timeline"])
    assert (by_kind["consent_granted"]["actor_name"], by_kind["consent_granted"]["categories"]) == \
        ("Synthetic Doctor", ["documents", "timeline"])
    assert all(i["read_at"] is None and i["facility"] is None for i in items)

    stored = json.dumps([list(r) for r in api.conn.execute("SELECT template_id, payload FROM notifications").fetchall()])
    for secret in (qr["qr"]["token"], qr["qr"]["short_code"], api.codes[PATIENT], "Synthetic Doctor", "Synthetic Carer"):
        assert secret not in stored  # a notice holds a template and the consent id only

    # the caregiver's own inbox is theirs alone
    assert inbox(api, carer) == []


def test_a_notice_stays_after_delivery_and_after_its_request_closes(api, cast):  # noqa: F811
    req = qr_request(api, cast)
    notification.deliver_due(api.conn, [("push", lambda n: None)])
    api.http.post(f"{V1}/consents/qr/{req['qr']['token']}/decline", headers=cast.patient)
    assert [i["kind"] for i in inbox(api, cast.patient)] == ["consent_request"]  # history, no open marker


def test_mark_read_is_the_patients_own_and_repeats_safely(api, cast):  # noqa: F811
    request_consent(api, cast)
    item = inbox(api, cast.patient)[0]
    first = api.http.post(f"{V1}/notifications/{item['id']}/read", headers=cast.patient).json()
    assert first["read_at"] is not None and first["id"] == item["id"]
    again = api.http.post(f"{V1}/notifications/{item['id']}/read", headers=cast.patient).json()
    assert again["read_at"] == first["read_at"]
    stranger = login(api, "+8801700000009", profile={**PROFILE, "name": "Synthetic Patient 9"})
    assert api.http.post(f"{V1}/notifications/{item['id']}/read", headers=stranger).status_code == 404
    assert api.http.post(f"{V1}/notifications/00000000-0000-4000-8000-000000000000/read",
                         headers=cast.patient).status_code == 404


def test_unknown_templates_stay_out_of_the_inbox(api, cast):  # noqa: F811
    notification.enqueue(api.conn, recipient_id=cast.patient_id, template_id="SOMETHING_ELSE", payload={})
    assert inbox(api, cast.patient) == []


def test_staff_never_read_an_inbox(api, cast):  # noqa: F811
    for headers in (cast.doctor, cast.verifier, cast.reviewer, cast.admin):
        r = api.http.get(f"{V1}/notifications", headers=headers)
        assert (r.status_code, r.json()["code"]) == (403, "role_not_allowed")
    assert api.http.get(f"{V1}/notifications").status_code == 401
