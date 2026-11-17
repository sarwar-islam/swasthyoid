"""W2 logout over HTTP: one device, every device, and the access token stops at once. Synthetic people only."""
import pytest

from swasthyoid.tests.test_api_m1 import (  # noqa: F401  (fixtures)
    ADMIN, PATIENT, PROFILE, V1, api, audit_reasons, login, people,
)
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


# ---- W2 sessions (owner decisions a and S8, 2026-11-17): refresh cookie for the web, idle timeout

WEB = {"X-SwasthyoID-CSRF": "1"}


def web_login(api, phone, device_id, **extra):
    assert api.http.post(f"{V1}/auth/otp/request", json={"phone": phone}).status_code == 204
    return api.http.post(f"{V1}/auth/otp/verify", headers=WEB, json={
        "phone": phone, "code": api.codes[pii.normalize_phone(phone)], "device_id": device_id, **extra})


def set_cookie(response, account="patient"):
    """The refresh cookie the response sets: (value, attributes). Read from the header, because the test client does not
    send Secure cookies back over http."""
    for line in response.headers.get_list("set-cookie"):
        name, rest = line.split("=", 1)
        if name == f"sw_refresh_{account}":
            value, _, attrs = rest.partition(";")
            return value.strip('"'), attrs.lower()
    return None


def cookie_refresh(api, value, device_id, account="patient", headers=WEB):
    return api.http.post(f"{V1}/auth/refresh", json={"device_id": device_id, "account": account},
                         headers={**headers, "Cookie": f"sw_refresh_{account}={value}"})


def test_the_web_gets_its_refresh_token_only_as_an_httponly_cookie(api):
    login(api, PATIENT, profile=PROFILE)
    r = web_login(api, PATIENT, "tab")
    assert r.status_code == 200 and set(r.json()) == {"access_token"}  # never readable by page scripts
    value, attrs = set_cookie(r)
    for part in ("httponly", "secure", "samesite=strict", "path=/api/v1/auth", "max-age=2592000"):
        assert part in attrs
    rotated = cookie_refresh(api, value, "tab")
    assert rotated.status_code == 200 and set(rotated.json()) == {"access_token"}
    assert api.http.get(f"{V1}/me", headers=bearer(rotated.json())).status_code == 200
    assert set_cookie(rotated)[0] != value
    stale = cookie_refresh(api, value, "tab")  # the old cookie is used up, and coming back ends the device's session
    assert stale.status_code == 401 and "max-age=0" in set_cookie(stale)[1]
    assert api.http.get(f"{V1}/me", headers=bearer(rotated.json())).status_code == 401


def test_a_cookie_refresh_needs_the_web_header(api):
    login(api, PATIENT, profile=PROFILE)
    value, _ = set_cookie(web_login(api, PATIENT, "tab"))
    r = cookie_refresh(api, value, "tab", headers={})
    assert (r.status_code, r.json()["code"]) == (403, "csrf_required")
    assert cookie_refresh(api, "", "tab").status_code == 401  # no cookie at all
    assert cookie_refresh(api, value, "tab").status_code == 200  # the cookie was not used up by the refused call


def test_logout_clears_the_cookie_and_its_token_is_dead(api):
    login(api, PATIENT, profile=PROFILE)
    r = web_login(api, PATIENT, "tab")
    value, _ = set_cookie(r)
    out = api.http.post(f"{V1}/auth/logout", headers=bearer(r.json()))
    assert out.status_code == 204 and "max-age=0" in set_cookie(out)[1]
    assert cookie_refresh(api, value, "tab").status_code == 401


def test_a_patient_and_a_staff_tab_keep_separate_cookies(api):
    accounts.seed_admin(api.conn, phone=ADMIN, name="Synthetic Admin")
    login(api, PATIENT, profile=PROFILE)
    patient, admin = web_login(api, PATIENT, "browser"), web_login(api, ADMIN, "browser", account="staff")
    assert set_cookie(patient, "patient") and set_cookie(admin, "staff") and not set_cookie(admin, "patient")
    for account, r, role in (("patient", patient, "patient"), ("staff", admin, "admin")):
        fresh = cookie_refresh(api, set_cookie(r, account)[0], "browser", account=account)
        assert api.http.get(f"{V1}/me", headers=bearer(fresh.json())).json().get("role", "patient") == role


def idle_for(api, minutes):
    api.conn.execute("UPDATE refresh_tokens SET last_seen_at = clock_timestamp() - make_interval(mins => %s) "
                     "WHERE revoked_at IS NULL", [minutes])


def test_a_patient_session_ends_after_30_idle_minutes(api):
    login(api, PATIENT, profile=PROFILE)
    tokens = device(api, PATIENT, "phone")
    idle_for(api, 29)
    assert api.http.get(f"{V1}/me", headers=bearer(tokens)).status_code == 200  # a request is activity
    idle_for(api, 31)
    r = api.http.get(f"{V1}/me", headers=bearer(tokens))
    assert (r.status_code, r.json()["code"]) == (401, "unauthenticated")
    assert "session_idle" in audit_reasons(api, "auth.token_rejected")
    assert api.http.post(f"{V1}/auth/refresh", json={"refresh_token": tokens["refresh_token"], "device_id": "phone"}
                         ).status_code == 401  # the session is over, not just the access token


def test_staff_sessions_end_after_15_idle_minutes_and_refresh_is_no_activity(api):
    accounts.seed_admin(api.conn, phone=ADMIN, name="Synthetic Admin")
    assert api.http.post(f"{V1}/auth/otp/request", json={"phone": ADMIN}).status_code == 204
    tokens = api.http.post(f"{V1}/auth/otp/verify", json={"phone": ADMIN, "account": "staff", "device_id": "desk",
                                                          "code": api.codes[pii.normalize_phone(ADMIN)]}).json()
    idle_for(api, 14)
    tokens = api.http.post(f"{V1}/auth/refresh", json={"refresh_token": tokens["refresh_token"], "device_id": "desk"}).json()
    assert api.conn.execute("SELECT last_seen_at < clock_timestamp() - interval '13 minutes' FROM refresh_tokens "
                            "WHERE revoked_at IS NULL").fetchone()[0]  # the silent refresh did not count as activity
    idle_for(api, 16)
    r = api.http.post(f"{V1}/auth/refresh", json={"refresh_token": tokens["refresh_token"], "device_id": "desk"})
    assert r.status_code == 401
    assert "session_idle" in audit_reasons(api, "auth.refresh_failed")
    assert api.http.get(f"{V1}/me", headers=bearer(tokens)).status_code == 401


# ---- W2 credential document (owner decision b, 2026-11-17): JPEG or PNG only, stored without metadata

@pytest.fixture
def store(tmp_path, monkeypatch):
    from cryptography.fernet import Fernet
    monkeypatch.setenv("DOCUMENT_STORE", str(tmp_path))
    monkeypatch.setenv("DOCUMENT_KEY", Fernet.generate_key().decode())
    return tmp_path


def send(api, people, data, credential=None, headers=None, name="bmdc.jpg"):
    return api.http.post(f"{V1}/credentials/{credential or people.credential}/document", headers=headers or people.doctor,
                         files={"file": (name, data, "application/octet-stream")})


def test_a_doctor_uploads_a_credential_photo_and_only_a_clean_copy_is_kept(api, people, store):  # noqa: F811
    from swasthyoid.tests import images
    r = send(api, people, images.jpeg_with_metadata())
    assert r.status_code == 201, r.text
    assert r.json() == {"id": people.credential, "status": "pending", "has_document": True}
    assert api.http.get(f"{V1}/me", headers=people.doctor).json()["credential"]["has_document"] is True
    listed = api.http.get(f"{V1}/credentials?status=pending", headers=people.admin).json()
    assert [c["has_document"] for c in listed] == [True]
    served = api.http.get(f"{V1}/credentials/{people.credential}/document", headers=people.admin)
    assert served.headers["content-type"] == "image/jpeg"
    for marker in (b"Exif", b"SYNTHETIC-CAMERA-MAKER", b"SYNTHETIC-COMMENT", b"2026:01:02"):
        assert marker not in served.content
    stored = list(store.rglob("*.jpg"))
    assert len(stored) == 1 and b"SYNTHETIC" not in stored[0].read_bytes()  # encrypted at rest, too
    assert actions(api, "credential.document.upload") == 1
    png = send(api, people, images.png_with_metadata(), name="bmdc.png")  # a newer upload replaces it
    assert png.status_code == 201
    served = api.http.get(f"{V1}/credentials/{people.credential}/document", headers=people.admin)
    assert served.headers["content-type"] == "image/png" and b"SYNTHETIC-PNG-COMMENT" not in served.content


def test_a_credential_document_must_be_a_jpeg_or_png(api, people, store):  # noqa: F811
    for data, code in ((b"%PDF-1.7 synthetic", "image_unsupported"), (b"\x89PNG\r\n\x1a\nbroken", "image_undecodable")):
        r = send(api, people, data)
        assert (r.status_code, r.json()["code"]) == (422, code)
    assert api.conn.execute("SELECT doc_key FROM credentials").fetchone()[0] is None
    assert not list(store.rglob("*.*"))


def test_only_the_owner_uploads_and_only_while_pending(api, people, store):  # noqa: F811
    from swasthyoid.tests import images
    other = login(api, "+8801700000077", account="staff", staff={"role": "doctor", "name": "Synthetic Doctor 2"})
    assert send(api, people, images.JPEG, headers=other).status_code == 404  # never says whose it is
    assert send(api, people, images.JPEG, headers=people.patient).status_code == 403
    assert api.http.post(f"{V1}/credentials/{people.credential}/approve", headers=people.admin).status_code == 200
    assert send(api, people, images.JPEG).status_code == 404  # verified: the reviewed document stays as it was
    assert not list(store.rglob("*.*"))  # nothing left behind by the refused uploads


def test_a_client_can_no_longer_name_a_storage_key(api, people):  # noqa: F811
    r = api.http.post(f"{V1}/credentials", headers=people.doctor,
                      json={"type": "BMDC", "number": "SYNTH-BMDC-0002", "doc_key": "patients/someone/1.jpg"})
    assert r.status_code in (201, 409)
    assert api.conn.execute("SELECT count(*) FROM credentials WHERE doc_key IS NOT NULL").fetchone()[0] == 0
