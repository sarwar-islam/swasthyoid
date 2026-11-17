"""W2 logout over HTTP: one device, every device, and the access token stops at once. Synthetic people only."""
from swasthyoid.tests.test_api_m1 import ADMIN, PATIENT, PROFILE, V1, api, audit_reasons, login  # noqa: F401  (fixture)
from swasthyoid import pii
from swasthyoid.identity import accounts


def device(api, phone, device_id):
    assert api.http.post(f"{V1}/auth/otp/request", json={"phone": phone}).status_code == 204
    r = api.http.post(f"{V1}/auth/otp/verify",
                      json={"phone": phone, "code": api.codes[pii.normalize_phone(phone)], "device_id": device_id})
    assert r.status_code == 200, r.text
    return r.json()


def bearer(tokens):
    return {"Authorization": f"Bearer {tokens['access_token']}"}


def actions(api, action):
    return api.conn.execute("SELECT count(*) FROM audit_logs WHERE action = %s", [action]).fetchone()[0]


def test_logout_ends_this_device_at_once_and_keeps_the_others(api):
    login(api, PATIENT, profile=PROFILE)
    phone, laptop = device(api, PATIENT, "phone"), device(api, PATIENT, "laptop")
    assert api.http.get(f"{V1}/me", headers=bearer(phone)).status_code == 200
    assert api.http.post(f"{V1}/auth/logout", headers=bearer(phone)).status_code == 204
    r = api.http.get(f"{V1}/me", headers=bearer(phone))  # within the 15 minutes, still refused
    assert (r.status_code, r.json()["code"]) == (401, "unauthenticated")
    assert "session_ended" in audit_reasons(api, "auth.token_rejected")
    refused = api.http.post(f"{V1}/auth/refresh", json={"refresh_token": phone["refresh_token"], "device_id": "phone"})
    assert refused.status_code == 401
    assert api.http.get(f"{V1}/me", headers=bearer(laptop)).status_code == 200
    assert actions(api, "auth.logout") == 1


def test_logout_all_ends_every_device(api):
    login(api, PATIENT, profile=PROFILE)
    phone, laptop = device(api, PATIENT, "phone"), device(api, PATIENT, "laptop")
    assert api.http.post(f"{V1}/auth/logout-all", headers=bearer(laptop)).status_code == 204
    for tokens in (phone, laptop):
        assert api.http.get(f"{V1}/me", headers=bearer(tokens)).status_code == 401
    assert actions(api, "auth.logout_all") == 1
    again = device(api, PATIENT, "phone")  # logging in again works
    assert api.http.get(f"{V1}/me", headers=bearer(again)).status_code == 200


def test_logout_needs_a_live_session_and_touches_no_one_else(api):
    assert api.http.post(f"{V1}/auth/logout").status_code == 401
    patient = login(api, PATIENT, profile=PROFILE)
    accounts.seed_admin(api.conn, phone=ADMIN, name="Synthetic Admin")
    admin = login(api, ADMIN, account="staff")  # same device id "dev-1", another account
    assert api.http.post(f"{V1}/auth/logout", headers=patient).status_code == 204
    assert api.http.post(f"{V1}/auth/logout", headers=patient).status_code == 401
    assert api.http.get(f"{V1}/me", headers=admin).status_code == 200


def test_a_refreshed_session_stays_live(api):
    login(api, PATIENT, profile=PROFILE)
    first = device(api, PATIENT, "phone")
    second = api.http.post(f"{V1}/auth/refresh", json={"refresh_token": first["refresh_token"], "device_id": "phone"}).json()
    for tokens in (first, second):  # the old access token runs out on its own; the device's session is still live
        assert api.http.get(f"{V1}/me", headers=bearer(tokens)).status_code == 200
