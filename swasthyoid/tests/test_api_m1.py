"""M1 over HTTP: login, credentials, Consent Center. Synthetic people only."""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from swasthyoid import pii
from swasthyoid.api import deps
from swasthyoid.api.main import app
from swasthyoid.core import consent_authz as c1
from swasthyoid.identity import accounts, otp

V1 = "/api/v1"
PATIENT, DOCTOR, ADMIN = "+8801700000001", "+8801900000002", "+8801900000001"
PROFILE = {"name": "Synthetic Patient 1", "dob": "1990-01-01", "sex": "F"}


@pytest.fixture
def api(connect, monkeypatch):
    conn = connect()
    conn.autocommit = True
    codes = {}
    app.dependency_overrides[deps.get_conn] = lambda: conn
    app.dependency_overrides[deps.get_code_sender] = lambda: codes.__setitem__
    monkeypatch.setenv("TIMELINE_CONSENT_HOURS", "24")
    yield SimpleNamespace(http=TestClient(app), conn=conn, codes=codes)
    app.dependency_overrides.clear()


def login(api, phone, **extra):
    assert api.http.post(f"{V1}/auth/otp/request", json={"phone": phone}).status_code == 204
    r = api.http.post(f"{V1}/auth/otp/verify",
                      json={"phone": phone, "code": api.codes[pii.normalize_phone(phone)], "device_id": "dev-1", **extra})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def audit_reasons(api, action):
    return [r[0] for r in api.conn.execute("SELECT reason FROM audit_logs WHERE action = %s ORDER BY seq", [action])]


@pytest.fixture
def people(api):
    """A registered patient, a verified doctor and an admin, each logged in."""
    patient = login(api, PATIENT, profile=PROFILE)
    doctor = login(api, DOCTOR, account="staff", staff={"role": "doctor", "name": "Synthetic Doctor"})
    accounts.seed_admin(api.conn, phone=ADMIN, name="Synthetic Admin")
    admin = login(api, ADMIN, account="staff")
    cred = api.http.post(f"{V1}/credentials", headers=doctor, json={"type": "BMDC", "number": "SYNTH-BMDC-0001"})
    assert cred.status_code == 201
    health_id = api.conn.execute("SELECT health_id FROM patients").fetchone()[0]
    return SimpleNamespace(patient=patient, doctor=doctor, admin=admin, credential=cred.json()["id"],
                           health_id=health_id)


def approve(api, people):
    r = api.http.post(f"{V1}/credentials/{people.credential}/approve", headers=people.admin)
    assert r.status_code == 200, r.text


def request_consent(api, people, **over):
    body = {"health_id": people.health_id, "categories": ["timeline"], **over}
    return api.http.post(f"{V1}/consents/requests", headers=people.doctor, json=body)


# ---- login

def test_patient_registers_logs_in_and_refreshes(api):
    api.http.post(f"{V1}/auth/otp/request", json={"phone": PATIENT})
    r = api.http.post(f"{V1}/auth/otp/verify", json={"phone": PATIENT, "code": api.codes[PATIENT], "device_id": "d"})
    assert (r.status_code, r.json()["code"]) == (409, "registration_required")

    headers = login(api, PATIENT, profile=PROFILE)
    assert api.http.get(f"{V1}/consents", headers=headers).json() == []
    login(api, "01700000001")  # returning patient needs no profile

    api.http.post(f"{V1}/auth/otp/request", json={"phone": PATIENT})
    tokens = api.http.post(f"{V1}/auth/otp/verify",
                           json={"phone": PATIENT, "code": api.codes[PATIENT], "device_id": "d"}).json()
    again = api.http.post(f"{V1}/auth/refresh", json={"refresh_token": tokens["refresh_token"], "device_id": "d"})
    assert again.status_code == 200 and "access_token" in again.json()
    reused = api.http.post(f"{V1}/auth/refresh", json={"refresh_token": tokens["refresh_token"], "device_id": "d"})
    assert (reused.status_code, reused.json()["code"]) == (401, "invalid_session")


def test_login_failures(api):
    assert api.http.post(f"{V1}/auth/otp/request", json={"phone": "12345"}).json()["code"] == "invalid_phone"
    api.http.post(f"{V1}/auth/otp/request", json={"phone": PATIENT})
    wrong = "000000" if api.codes[PATIENT] != "000000" else "111111"
    r = api.http.post(f"{V1}/auth/otp/verify", json={"phone": PATIENT, "code": wrong, "device_id": "d"})
    assert r.status_code == 401
    assert r.json() == {"code": "invalid_code", "message": "The code is wrong or has expired.", "details": {}}
    assert audit_reasons(api, "auth.otp_failed") == ["wrong_code"]

    for _ in range(otp.MAX_REQUESTS - 1):
        api.http.post(f"{V1}/auth/otp/request", json={"phone": PATIENT})
    assert api.http.post(f"{V1}/auth/otp/request", json={"phone": PATIENT}).status_code == 429


def test_requests_without_a_valid_token_are_rejected_and_audited(api):
    for headers in ({}, {"Authorization": "Bearer garbage"}, {"Authorization": "Basic abc"}):
        r = api.http.get(f"{V1}/consents", headers=headers)
        assert (r.status_code, r.json()["code"]) == (401, "unauthenticated")
    assert audit_reasons(api, "auth.token_rejected") == ["invalid_token"] * 3


def test_nobody_can_register_as_admin(api):
    api.http.post(f"{V1}/auth/otp/request", json={"phone": ADMIN})
    r = api.http.post(f"{V1}/auth/otp/verify", json={
        "phone": ADMIN, "code": api.codes[ADMIN], "device_id": "d", "account": "staff",
        "staff": {"role": "admin", "name": "Sneaky"}})
    assert r.status_code == 422
    assert api.conn.execute("SELECT count(*) FROM users").fetchone()[0] == 0


# ---- roles and credentials

def test_unverified_doctor_cannot_request_consent(api, people):
    r = request_consent(api, people)
    assert (r.status_code, r.json()["code"]) == (403, "user_not_verified")
    assert audit_reasons(api, "rbac.deny") == ["user_not_verified: POST /consents/requests"]
    assert api.conn.execute("SELECT count(*) FROM consents").fetchone()[0] == 0


def test_role_checks(api, people):
    approve(api, people)
    denied = [
        api.http.get(f"{V1}/consents", headers=people.doctor),
        api.http.get(f"{V1}/me/access-history", headers=people.admin),
        request_consent(SimpleNamespace(http=api.http), SimpleNamespace(doctor=people.patient, health_id=people.health_id)),
        api.http.post(f"{V1}/credentials/{people.credential}/approve", headers=people.doctor),
        api.http.post(f"{V1}/credentials", headers=people.patient, json={"type": "BMDC", "number": "X"}),
    ]
    assert [(r.status_code, r.json()["code"]) for r in denied] == [(403, "role_not_allowed")] * 5
    assert len(audit_reasons(api, "rbac.deny")) == 5


def test_credential_approval_over_http(api, people):
    dup = api.http.post(f"{V1}/credentials", headers=people.doctor, json={"type": "BMDC", "number": "SYNTH-BMDC-0001"})
    assert (dup.status_code, dup.json()["code"]) == (409, "credential_exists")
    approve(api, people)
    again = api.http.post(f"{V1}/credentials/{people.credential}/approve", headers=people.admin)
    assert again.status_code == 404
    assert request_consent(api, people).status_code == 201


def test_suspended_user_is_locked_out_at_once(api, people):
    approve(api, people)
    doctor_id, admin_id = (api.conn.execute("SELECT id FROM users WHERE role = %s", [r]).fetchone()[0]
                           for r in ("doctor", "admin"))
    accounts.suspend_user(api.conn, doctor_id, admin_id=admin_id)
    r = request_consent(api, people)  # the old access token no longer works
    assert (r.status_code, r.json()["code"]) == (401, "unauthenticated")
    assert audit_reasons(api, "auth.token_rejected") == ["account_not_active"]

    api.http.post(f"{V1}/auth/otp/request", json={"phone": DOCTOR})
    again = api.http.post(f"{V1}/auth/otp/verify", json={
        "phone": DOCTOR, "code": api.codes[DOCTOR], "device_id": "d", "account": "staff"})
    assert (again.status_code, again.json()["code"]) == (403, "user_suspended")


# ---- Consent Center

def test_consent_request_confirm_list_revoke(api, people):
    approve(api, people)
    r = request_consent(api, people, categories=["timeline", "safety"])
    assert r.status_code == 201 and r.json()["status"] == "pending"
    consent_id, code = r.json()["id"], api.codes[PATIENT]
    confirm = f"{V1}/consents/requests/{consent_id}/confirm"

    wrong = "000000" if code != "000000" else "111111"
    bad = api.http.post(confirm, headers=people.doctor, json={"code": wrong})
    assert (bad.status_code, bad.json()["code"]) == (403, "invalid_code")
    ok = api.http.post(confirm, headers=people.doctor, json={"code": code})
    assert ok.status_code == 200 and ok.json()["status"] == "active" and ok.json()["expires_at"]
    assert api.http.post(confirm, headers=people.doctor, json={"code": code}).status_code == 404  # not pending now

    listed = api.http.get(f"{V1}/consents", headers=people.patient).json()
    assert [(c["id"], c["status"], c["grantee_name"], c["purpose"]) for c in listed] == [
        (consent_id, "active", "Synthetic Doctor", "TIMELINE")]
    assert sorted(listed[0]["allowed_categories"]) == ["safety", "timeline"]
    assert api.conn.execute("SELECT template_id FROM notifications").fetchall() == [("CONSENT_GRANTED_PLACEHOLDER",)]

    history = api.http.get(f"{V1}/me/access-history", headers=people.patient).json()
    assert [h["action"] for h in history] == ["consent.activate", "consent.create"]
    assert history[1]["actor_name"] == "Synthetic Doctor"

    doctor_id, patient_id = api.conn.execute("SELECT grantee_id, patient_id FROM consents").fetchone()

    def next_request():
        consent = c1.find(api.conn, grantee_id=doctor_id, patient_id=patient_id, purpose="TIMELINE")
        now = api.conn.execute("SELECT clock_timestamp()").fetchone()[0]
        return c1.authorize_access(c1.AccessRequest("TIMELINE", frozenset({"timeline"})),
                                   SimpleNamespace(id=doctor_id, is_verified=True, is_active=True),
                                   SimpleNamespace(id=patient_id), consent, now)

    assert next_request().allowed
    revoked = api.http.post(f"{V1}/consents/{consent_id}/revoke", headers=people.patient)
    assert revoked.status_code == 200 and revoked.json()["status"] == "revoked"
    assert next_request().reason == "not_active"  # revoke blocks the very next request
    again = api.http.post(f"{V1}/consents/{consent_id}/revoke", headers=people.patient)
    assert (again.status_code, again.json()["code"]) == (409, "not_revocable")


def test_a_consent_code_cannot_log_in_and_a_login_code_cannot_confirm(api, people):
    approve(api, people)
    consent_id = request_consent(api, people).json()["id"]
    consent_code = api.codes[PATIENT]
    stolen = api.http.post(f"{V1}/auth/otp/verify", json={"phone": PATIENT, "code": consent_code, "device_id": "evil"})
    assert stolen.status_code == 401  # the doctor cannot become the patient

    api.http.post(f"{V1}/auth/otp/request", json={"phone": PATIENT})
    login_code = api.codes[PATIENT]
    if login_code != consent_code:
        r = api.http.post(f"{V1}/consents/requests/{consent_id}/confirm", headers=people.doctor, json={"code": login_code})
        assert r.status_code == 403
    assert api.conn.execute("SELECT status FROM consents").fetchone()[0] == "pending"


def test_consent_requests_are_private_to_their_doctor_and_patient(api, people):
    approve(api, people)
    consent_id = request_consent(api, people).json()["id"]
    code = api.codes[PATIENT]

    other_phone = "+8801900000003"
    other = login(api, other_phone, account="staff", staff={"role": "doctor", "name": "Synthetic Doctor 2"})
    cred = api.http.post(f"{V1}/credentials", headers=other, json={"type": "BMDC", "number": "SYNTH-BMDC-0002"}).json()
    api.http.post(f"{V1}/credentials/{cred['id']}/approve", headers=people.admin)
    hijack = api.http.post(f"{V1}/consents/requests/{consent_id}/confirm", headers=other, json={"code": code})
    assert hijack.status_code == 404

    assert api.http.post(f"{V1}/consents/requests/{consent_id}/confirm", headers=people.doctor,
                         json={"code": code}).status_code == 200
    stranger = login(api, "+8801700000002", profile=PROFILE)
    assert api.http.post(f"{V1}/consents/{consent_id}/revoke", headers=stranger).status_code == 404
    assert api.http.get(f"{V1}/consents", headers=stranger).json() == []
    assert api.http.get(f"{V1}/me/access-history", headers=stranger).json() == []
    assert api.conn.execute("SELECT status FROM consents").fetchone()[0] == "active"


def test_consent_request_edge_cases(api, people, monkeypatch):
    approve(api, people)
    assert request_consent(api, people, health_id="SID-0000000000").status_code == 404
    assert request_consent(api, people, categories=[]).status_code == 422
    assert request_consent(api, people, categories=["everything"]).status_code == 422
    monkeypatch.delenv("TIMELINE_CONSENT_HOURS")
    r = request_consent(api, people)
    assert (r.status_code, r.json()["code"]) == (503, "not_configured")
    assert api.conn.execute("SELECT count(*) FROM consents").fetchone()[0] == 0
