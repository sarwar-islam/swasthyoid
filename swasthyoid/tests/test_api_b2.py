"""B2 over HTTP: GET /me, consent responses, consent by QR, and the admin staff and credential routes.

Synthetic people only. Every refusal of a role is checked over HTTP, so nothing passes only because a screen hid a button.
"""
import pytest

from swasthyoid.identity import accounts
from swasthyoid.tests.test_api_m1 import (  # noqa: F401
    ADMIN, DOCTOR, PATIENT, PROFILE, V1, api, approve, login, people, request_consent,
)

VERIFIER, REVIEWER = "+8801900000011", "+8801900000012"


@pytest.fixture
def cast(api, people):  # noqa: F811
    """The M1 cast with the doctor approved, plus an admin-created verifier and clinical reviewer, all logged in."""
    approve(api, people)
    for phone, role in ((VERIFIER, "verifier"), (REVIEWER, "clinical_reviewer")):
        r = api.http.post(f"{V1}/admin/staff", headers=people.admin, json={"role": role, "name": f"Synthetic {role}", "phone": phone})
        assert r.status_code == 201, r.text
    people.verifier = login(api, VERIFIER, account="staff")
    people.reviewer = login(api, REVIEWER, account="staff")
    people.patient_id = api.conn.execute("SELECT id FROM patients").fetchone()[0]
    return people


def qr_request(api, people, categories=("timeline", "safety")):
    r = api.http.post(f"{V1}/consents/requests", headers=people.doctor,
                      json={"health_id": people.health_id, "categories": list(categories), "method": "qr"})
    assert r.status_code == 201, r.text
    return r.json()


def denied_roles(api, cast, method, path, json=None):
    """Every non-admin role is refused with 403 role_not_allowed, and each refusal is audited."""
    before = api.conn.execute("SELECT count(*) FROM audit_logs WHERE action = 'rbac.deny'").fetchone()[0]
    for headers in (cast.patient, cast.doctor, cast.verifier, cast.reviewer):
        r = api.http.request(method, f"{V1}{path}", headers=headers, json=json)
        assert (r.status_code, r.json()["code"]) == (403, "role_not_allowed"), (path, r.text)
    after = api.conn.execute("SELECT count(*) FROM audit_logs WHERE action = 'rbac.deny'").fetchone()[0]
    assert after - before == 4


# ---- GET /me

def test_me_for_the_patient_and_every_staff_role(api, cast):
    me = api.http.get(f"{V1}/me", headers=cast.patient).json()
    assert me["health_id"] == cast.health_id and me["name"] == PROFILE["name"]
    assert (me["language"], me["cloud_ai_opt_in"]) == ("bn", False)
    # UX-1 profile: date of birth, sex, account date, and only the last four digits of the phone
    assert (me["dob"], me["sex"], me["phone_tail"]) == (PROFILE["dob"], PROFILE["sex"], PATIENT[-4:]) and me["created_at"]
    assert PATIENT not in str(me)
    doctor = api.http.get(f"{V1}/me", headers=cast.doctor).json()
    assert (doctor["role"], doctor["status"]) == ("doctor", "verified")
    assert doctor["credential"] == {"id": doctor["credential"]["id"], "type": "BMDC", "number": "SYNTH-BMDC-0001",
                                    "status": "verified", "has_document": False}
    for headers, role in ((cast.verifier, "verifier"), (cast.reviewer, "clinical_reviewer"), (cast.admin, "admin")):
        body = api.http.get(f"{V1}/me", headers=headers).json()
        assert (body["role"], body["status"], body["credential"]) == (role, "verified", None)
    assert api.http.get(f"{V1}/me").status_code == 401


def test_a_pending_doctor_reads_their_own_status(api):  # noqa: F811
    doctor = login(api, DOCTOR, account="staff", staff={"role": "doctor", "name": "Synthetic Doctor"})
    assert api.http.get(f"{V1}/me", headers=doctor).json()["credential"] is None
    api.http.post(f"{V1}/credentials", headers=doctor, json={"type": "BMDC", "number": "SYNTH-BMDC-0009"})
    body = api.http.get(f"{V1}/me", headers=doctor).json()
    assert (body["status"], body["credential"]["status"]) == ("pending", "pending")


# ---- consent responses

def test_consent_responses_name_the_patient_and_the_method(api, cast):
    created = request_consent(api, cast).json()
    assert (created["patient_id"], created["health_id"]) == (str(cast.patient_id), cast.health_id)
    confirmed = api.http.post(f"{V1}/consents/requests/{created['id']}/confirm", headers=cast.doctor,
                              json={"code": api.codes[PATIENT]}).json()
    assert (confirmed["status"], confirmed["health_id"]) == ("active", cast.health_id)
    qr_request(api, cast)
    methods = {c["id"]: c["method"] for c in api.http.get(f"{V1}/consents", headers=cast.patient).json()}
    assert methods[created["id"]] == "otp" and "qr" in methods.values()


def test_a_doctor_reads_only_their_own_request(api, cast):
    created = request_consent(api, cast).json()
    assert api.http.get(f"{V1}/consents/requests/{created['id']}", headers=cast.doctor).json()["status"] == "pending"
    other = login(api, "+8801900000013", account="staff", staff={"role": "doctor", "name": "Synthetic Doctor 2"})
    api.conn.execute("UPDATE users SET status = 'verified' WHERE name = 'Synthetic Doctor 2'")
    assert api.http.get(f"{V1}/consents/requests/{created['id']}", headers=other).status_code == 404
    assert api.http.get(f"{V1}/consents/requests/{created['id']}", headers=cast.patient).status_code == 403


# ---- consent by QR

def test_qr_only_the_named_patient_approves_once_in_their_own_app(api, cast):
    sent_before = dict(api.codes)
    req = qr_request(api, cast)
    assert api.codes == sent_before  # no SMS code for a QR request
    token, code = req["qr"]["token"], req["qr"]["short_code"]
    assert len(code) == 8 and set(code) <= set("ABCDEFGHJKMNPQRSTUVWXYZ23456789")
    stored = api.conn.execute("SELECT token_hash, code_hash FROM consent_qr").fetchone()
    assert token not in stored and code not in stored  # only keyed hashes are kept
    assert api.conn.execute("SELECT count(*) FROM idempotency_keys").fetchone()[0] == 0

    # no code can confirm it, and nobody but the named patient can see or answer it
    r = api.http.post(f"{V1}/consents/requests/{req['id']}/confirm", headers=cast.doctor, json={"code": "123456"})
    assert (r.status_code, r.json()["code"]) == (403, "invalid_code")
    for headers in (cast.doctor, cast.verifier, cast.admin):
        assert api.http.get(f"{V1}/consents/qr/{token}", headers=headers).status_code == 403
    stranger = login(api, "+8801700000009", profile={**PROFILE, "name": "Synthetic Patient 9"})
    for path in (f"/consents/qr/{token}", f"/consents/qr/{code}"):
        assert api.http.get(f"{V1}{path}", headers=stranger).status_code == 404
    assert api.http.post(f"{V1}/consents/qr/{token}/approve", headers=stranger).status_code == 404

    seen = api.http.get(f"{V1}/consents/qr/{code.lower()}", headers=cast.patient).json()  # any case
    assert (seen["consent_id"], seen["status"], seen["doctor_name"]) == (req["id"], "pending", "Synthetic Doctor")
    assert seen["categories"] == ["safety", "timeline"] and seen["access_hours"] == 24
    answered = api.http.post(f"{V1}/consents/qr/{token}/approve", headers=cast.patient)
    assert answered.status_code == 200 and answered.json()["status"] == "active"
    assert api.http.post(f"{V1}/consents/qr/{token}/approve", headers=cast.patient).status_code == 404  # single use
    assert api.http.get(f"{V1}/consents/requests/{req['id']}", headers=cast.doctor).json()["status"] == "active"
    method = api.conn.execute("SELECT method FROM consents WHERE id = %s", [req["id"]]).fetchone()[0]
    assert method == "QR"
    trail = api.conn.execute(
        "SELECT action, result, reason FROM audit_logs WHERE consent_id = %s ORDER BY seq", [req["id"]]).fetchall()
    assert ("consent.activate", "allow", None) in trail  # the approval, by C1
    assert trail[-1] == ("consent.qr.approve", "deny", "not_open")  # the second try, refused and audited
    assert ("consent.qr.read", "deny", "not_found") in api.conn.execute(
        "SELECT action, result, reason FROM audit_logs WHERE action = 'consent.qr.read'").fetchall()  # the stranger


def test_qr_expires_with_the_otp_lifetime_and_a_decline_grants_nothing(api, cast):
    late = qr_request(api, cast)
    api.conn.execute("UPDATE consent_qr SET expires_at = clock_timestamp() - interval '1 second' WHERE consent_id = %s",
                     [late["id"]])
    assert api.http.get(f"{V1}/consents/qr/{late['qr']['token']}", headers=cast.patient).json()["status"] == "expired"
    assert api.http.post(f"{V1}/consents/qr/{late['qr']['token']}/approve", headers=cast.patient).status_code == 404
    req = qr_request(api, cast)
    r = api.http.post(f"{V1}/consents/qr/{req['qr']['short_code']}/decline", headers=cast.patient)
    assert r.json()["status"] == "declined"
    assert api.http.get(f"{V1}/consents/requests/{req['id']}", headers=cast.doctor).json()["status"] == "declined"


# ---- admin: credentials

def test_credential_list_reject_and_resubmit(api, people):  # noqa: F811
    listed = api.http.get(f"{V1}/credentials?status=pending", headers=people.admin).json()
    assert [(c["number"], c["name"], c["user_status"]) for c in listed] == [("SYNTH-BMDC-0001", "Synthetic Doctor", "pending")]
    r = api.http.post(f"{V1}/credentials/{people.credential}/reject", headers=people.admin, json={"reason": " "})
    assert r.json()["code"] == "reason_required"
    r = api.http.post(f"{V1}/credentials/{people.credential}/reject", headers=people.admin,
                      json={"reason": "SYNTH number does not match the register"})
    assert r.status_code == 200 and r.json()["status"] == "rejected"
    assert api.http.post(f"{V1}/credentials/{people.credential}/reject", headers=people.admin,
                         json={"reason": "again"}).status_code == 404
    row = api.conn.execute("SELECT status, review_reason FROM credentials").fetchone()
    assert row == ("rejected", "SYNTH number does not match the register")
    logged = api.conn.execute("SELECT reason FROM audit_logs WHERE action = 'credential.reject'").fetchone()[0]
    assert logged == "reason_given"  # never the free text
    assert api.http.get(f"{V1}/me", headers=people.doctor).json()["credential"] is None
    again = api.http.post(f"{V1}/credentials", headers=people.doctor, json={"type": "BMDC", "number": "SYNTH-BMDC-0001"})
    assert again.status_code == 201  # the same number may be submitted again


def test_credential_document_is_admin_only_and_typed_by_its_bytes(api, people, tmp_path, monkeypatch):  # noqa: F811
    from cryptography.fernet import Fernet

    from swasthyoid.capture import storage
    monkeypatch.setenv("DOCUMENT_STORE", str(tmp_path))
    monkeypatch.setenv("DOCUMENT_KEY", Fernet.generate_key().decode())
    storage.put("credentials/synthetic.pdf", b"%PDF-1.7 synthetic")
    api.conn.execute("UPDATE credentials SET doc_key = 'credentials/synthetic.pdf'")
    r = api.http.get(f"{V1}/credentials/{people.credential}/document", headers=people.admin)
    assert (r.status_code, r.headers["content-type"], r.content) == (200, "application/pdf", b"%PDF-1.7 synthetic")
    assert api.http.get(f"{V1}/credentials/{people.credential}/document", headers=people.doctor).status_code == 403
    api.conn.execute("UPDATE credentials SET doc_key = NULL")
    assert api.http.get(f"{V1}/credentials/{people.credential}/document", headers=people.admin).status_code == 404


# ---- admin: staff accounts and suspension

def test_staff_creation_listing_and_verifier_approval(api, cast):
    listed = api.http.get(f"{V1}/admin/staff?status=verified", headers=cast.admin).json()
    assert sorted((s["role"], s["phone_tail"]) for s in listed) == [("clinical_reviewer", "0012"), ("verifier", "0011")]
    for body, code in (({"role": "doctor", "name": "X", "phone": "+8801900000020"}, "invalid_role"),
                       ({"role": "admin", "name": "X", "phone": "+8801900000020"}, "invalid_role"),
                       ({"role": "verifier", "name": " ", "phone": "+8801900000020"}, "invalid_name"),
                       ({"role": "verifier", "name": "X", "phone": "12"}, "invalid_phone"),
                       ({"role": "verifier", "name": "X", "phone": VERIFIER}, "phone_exists")):
        r = api.http.post(f"{V1}/admin/staff", headers=cast.admin, json=body)
        assert r.json()["code"] == code, body
    pending = login(api, "+8801900000021", account="staff", staff={"role": "verifier", "name": "Synthetic CHW"})
    assert api.http.get(f"{V1}/me", headers=pending).json()["status"] == "pending"
    waiting = api.http.get(f"{V1}/admin/staff?status=pending", headers=cast.admin).json()
    assert [w["name"] for w in waiting] == ["Synthetic CHW"]
    assert api.http.post(f"{V1}/admin/staff/{waiting[0]['id']}/approve", headers=cast.admin).json()["status"] == "verified"
    assert api.http.post(f"{V1}/admin/staff/{waiting[0]['id']}/approve", headers=cast.admin).status_code == 404


def test_suspension_covers_staff_but_never_an_admin(api, cast):
    created = request_consent(api, cast).json()
    api.http.post(f"{V1}/consents/requests/{created['id']}/confirm", headers=cast.doctor, json={"code": api.codes[PATIENT]})
    doctor_id = api.conn.execute("SELECT id FROM users WHERE role = 'doctor'").fetchone()[0]
    assert api.http.post(f"{V1}/admin/users/{doctor_id}/suspend", headers=cast.admin, json={}).json()["code"] == "reason_required"
    r = api.http.post(f"{V1}/admin/users/{doctor_id}/suspend", headers=cast.admin, json={"reason": "SYNTH review"})
    assert r.json()["status"] == "suspended"
    assert api.conn.execute("SELECT status FROM consents WHERE id = %s", [created["id"]]).fetchone()[0] == "suspended"
    assert api.http.get(f"{V1}/me", headers=cast.doctor).status_code == 401  # the account no longer works
    reviewer_id = api.conn.execute("SELECT id FROM users WHERE role = 'clinical_reviewer'").fetchone()[0]
    assert api.http.post(f"{V1}/admin/users/{reviewer_id}/suspend", headers=cast.admin, json={"reason": "SYNTH"}).status_code == 200
    accounts.seed_admin(api.conn, phone="+8801900000022", name="Synthetic Admin 2")
    other_admin = api.conn.execute("SELECT id FROM users WHERE name = 'Synthetic Admin 2'").fetchone()[0]
    assert api.http.post(f"{V1}/admin/users/{other_admin}/suspend", headers=cast.admin, json={"reason": "x"}).status_code == 404
    reasons = {r[0] for r in api.conn.execute("SELECT reason FROM audit_logs WHERE action = 'credential.suspend'")}
    assert reasons == {"reason_given"}


@pytest.mark.parametrize("method,path,json", [
    ("GET", "/credentials", None),
    ("POST", "/credentials/00000000-0000-4000-8000-000000000000/reject", {"reason": "x"}),
    ("GET", "/credentials/00000000-0000-4000-8000-000000000000/document", None),
    ("GET", "/admin/staff", None),
    ("POST", "/admin/staff", {"role": "verifier", "name": "X", "phone": "+8801900000023"}),
    ("POST", "/admin/staff/00000000-0000-4000-8000-000000000000/approve", None),
    ("POST", "/admin/users/00000000-0000-4000-8000-000000000000/suspend", {"reason": "x"}),
])
def test_every_admin_route_refuses_every_other_role(api, cast, method, path, json):
    denied_roles(api, cast, method, path, json)
