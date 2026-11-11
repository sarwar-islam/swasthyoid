"""M1 identity: PII helpers, accounts, one-time codes, sessions. Synthetic people only."""
from datetime import date, timedelta
from uuid import uuid4

import jwt
import psycopg
import pytest

from swasthyoid import pii
from swasthyoid.core import audit
from swasthyoid.core import consent_authz as c1
from swasthyoid.identity import accounts, health_id, otp, sessions

PHONE = "+8801700000001"


def audit_rows(conn):
    return conn.execute("SELECT action, result, reason FROM audit_logs ORDER BY seq").fetchall()


# ---- PII helpers

def test_phone_normalisation_and_hash():
    for same in ("01700000001", "8801700000001", "+880 1700-000001", PHONE):
        assert pii.normalize_phone(same) == PHONE
        assert pii.phone_hash(same) == pii.phone_hash(PHONE)
    assert pii.phone_hash(PHONE) != pii.phone_hash("+8801700000002")
    for bad in ("", "12345", "+8801200000001", "+88017000000011", "+441700000001", None):
        with pytest.raises(ValueError):
            pii.normalize_phone(bad)


def test_encryption_round_trip_and_missing_key(monkeypatch):
    token = pii.encrypt("Synthetic Patient 1")
    assert "Synthetic" not in token and pii.decrypt(token) == "Synthetic Patient 1"
    monkeypatch.delenv("PII_KEY")
    with pytest.raises(KeyError):
        pii.encrypt("x")
    monkeypatch.delenv("HMAC_KEY")
    with pytest.raises(KeyError):
        pii.phone_hash(PHONE)


# ---- accounts

def patient(conn, phone=PHONE):
    return accounts.register_patient(conn, phone=phone, name="Synthetic Patient 1", dob=date(1990, 1, 1), sex="F")


def test_register_patient(conn):
    p = patient(conn, "01700000001")
    assert health_id.is_valid(p["health_id"])
    assert (p["language"], p["cloud_ai_opt_in"]) == ("bn", False)
    stored = " ".join(map(str, conn.execute("SELECT * FROM patients").fetchone()))
    assert PHONE not in stored and "1700000001" not in stored and "Synthetic" not in stored
    assert pii.decrypt(p["phone_enc"]) == PHONE and pii.decrypt(p["name_enc"]) == "Synthetic Patient 1"

    with pytest.raises(psycopg.errors.UniqueViolation):  # same phone, any spelling
        patient(conn, PHONE)
    conn.rollback()
    with pytest.raises(ValueError):
        patient(conn, "not a phone")


def test_health_id_collision_is_retried(conn, monkeypatch):
    ids = iter(["SID-0000000000", "SID-0000000000", "SID-0000000018"])
    monkeypatch.setattr(health_id, "generate", lambda: next(ids))
    assert patient(conn, "+8801700000001")["health_id"] == "SID-0000000000"
    assert patient(conn, "+8801700000002")["health_id"] == "SID-0000000018"


@pytest.fixture
def staff(conn):
    admin = accounts.seed_admin(conn, phone="+8801900000001", name="Synthetic Admin")
    doctor = accounts.register_user(conn, phone="+8801900000002", role="doctor", name="Synthetic Doctor")
    cred = accounts.submit_credential(conn, user_id=doctor["id"], type="BMDC", number="SYNTH-BMDC-0001")
    return admin, doctor, cred


def user_status(conn, user_id):
    return conn.execute("SELECT status FROM users WHERE id = %s", [user_id]).fetchone()[0]


def test_staff_start_pending_and_admins_cannot_self_register(conn):
    doctor = accounts.register_user(conn, phone="+8801900000002", role="doctor", name="Synthetic Doctor")
    assert doctor["status"] == "pending"
    with pytest.raises(PermissionError):
        accounts.register_user(conn, phone="+8801900000003", role="admin", name="Sneaky")
    with pytest.raises(psycopg.Error):
        accounts.register_user(conn, phone="+8801900000004", role="wizard", name="X")


def test_credential_approval(conn, staff):
    admin, doctor, cred = staff
    assert cred["status"] == "pending"
    for not_admin in (doctor["id"], uuid4()):
        with pytest.raises(PermissionError):
            accounts.approve_credential(conn, cred["id"], admin_id=not_admin)
    assert user_status(conn, doctor["id"]) == "pending"

    assert accounts.approve_credential(conn, cred["id"], admin_id=admin["id"]) == doctor["id"]
    assert user_status(conn, doctor["id"]) == "verified"
    assert conn.execute("SELECT status, reviewed_by FROM credentials").fetchone() == ("verified", admin["id"])
    assert audit_rows(conn) == [("credential.approve", "allow", None)]

    with pytest.raises(ValueError):  # already approved
        accounts.approve_credential(conn, cred["id"], admin_id=admin["id"])
    with pytest.raises(psycopg.errors.UniqueViolation):  # a credential number belongs to one user
        accounts.submit_credential(conn, user_id=admin["id"], type="BMDC", number="SYNTH-BMDC-0001")


def test_suspend_stops_grants_and_sessions_and_restore_brings_grants_back(conn, staff):
    admin, doctor, cred = staff
    with pytest.raises(ValueError):  # pending users cannot be suspended
        accounts.suspend_user(conn, doctor["id"], admin_id=admin["id"])
    accounts.approve_credential(conn, cred["id"], admin_id=admin["id"])
    p = patient(conn)
    consent = c1.create(conn, patient_id=p["id"], grantee_id=doctor["id"], grantee_role="doctor", purpose="TIMELINE",
                        allowed_categories={"timeline"}, consent_version=1, policy_version="PLACEHOLDER",
                        actor_id=doctor["id"])
    now = conn.execute("SELECT clock_timestamp()").fetchone()[0]
    c1.activate(conn, consent["id"], method="OTP", expires_at=now + timedelta(hours=1), actor_id=p["id"])
    tokens = sessions.issue_tokens(conn, subject_id=doctor["id"], role="doctor", device_id="dev-1")

    def consent_status():
        return conn.execute("SELECT status FROM consents WHERE id = %s", [consent["id"]]).fetchone()[0]

    with pytest.raises(PermissionError):
        accounts.suspend_user(conn, doctor["id"], admin_id=doctor["id"])
    assert consent_status() == "active"

    accounts.suspend_user(conn, doctor["id"], admin_id=admin["id"])
    assert user_status(conn, doctor["id"]) == "suspended"
    assert conn.execute("SELECT status FROM credentials").fetchone()[0] == "suspended"
    assert consent_status() == "suspended"
    with pytest.raises(sessions.InvalidSession):
        sessions.refresh(conn, tokens["refresh_token"], "dev-1")

    accounts.restore_user(conn, doctor["id"], admin_id=admin["id"])
    assert user_status(conn, doctor["id"]) == "verified"
    assert conn.execute("SELECT status FROM credentials").fetchone()[0] == "verified"
    assert consent_status() == "active"
    assert audit.verify_stored(conn) is None


# ---- one-time codes

@pytest.fixture
def sent():
    box = []
    return box, lambda phone, code: box.append((phone, code))


def test_code_works_once(conn, sent):
    box, send = sent
    otp.request_code(conn, "01700000001", send)
    phone, code = box[0]
    assert phone == PHONE and len(code) == 6 and code.isdigit()
    assert code not in " ".join(map(str, conn.execute("SELECT * FROM otp_codes").fetchone()))  # hash only

    assert otp.verify_code(conn, PHONE, code) is True
    assert otp.verify_code(conn, PHONE, code) is False
    assert audit_rows(conn) == [("auth.otp_failed", "deny", "no_valid_code")]


def test_wrong_codes_lock_the_code(conn, sent):
    box, send = sent
    otp.request_code(conn, PHONE, send)
    code = box[0][1]
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(otp.MAX_ATTEMPTS):
        assert otp.verify_code(conn, PHONE, wrong) is False
    assert otp.verify_code(conn, PHONE, code) is False  # even the right code is dead now
    reasons = [r[2] for r in audit_rows(conn)]
    assert reasons == ["wrong_code"] * otp.MAX_ATTEMPTS + ["too_many_attempts"]


def test_code_expires_is_per_phone_and_a_new_request_replaces_the_old(conn, sent):
    box, send = sent
    otp.request_code(conn, PHONE, send)
    assert otp.verify_code(conn, "+8801700000002", box[0][1]) is False  # another phone
    assert otp.verify_code(conn, "garbage", box[0][1]) is False
    otp.request_code(conn, PHONE, send)
    assert otp.verify_code(conn, PHONE, box[0][1]) is (box[0][1] == box[1][1])  # old code replaced

    otp.request_code(conn, PHONE, send)
    conn.execute("UPDATE otp_codes SET expires_at = clock_timestamp() - interval '1 second'")
    assert otp.verify_code(conn, PHONE, box[2][1]) is False


def test_request_rate_limit(conn, sent):
    box, send = sent
    for _ in range(otp.MAX_REQUESTS):
        otp.request_code(conn, PHONE, send)
    with pytest.raises(otp.TooManyRequests):
        otp.request_code(conn, PHONE, send)
    assert len(box) == otp.MAX_REQUESTS
    otp.request_code(conn, "+8801700000002", send)  # other phones are unaffected
    with pytest.raises(ValueError):
        otp.request_code(conn, "not a phone", send)


# ---- sessions

def test_login_issues_tokens_and_is_audited(conn):
    who = uuid4()
    tokens = sessions.issue_tokens(conn, subject_id=who, role="patient", device_id="dev-1", ip="127.0.0.1")
    claims = sessions.read_access_token(tokens["access_token"])
    assert (claims["sub"], claims["role"], claims["device_id"]) == (str(who), "patient", "dev-1")
    assert audit_rows(conn) == [("auth.login", "allow", None)]
    assert tokens["refresh_token"] not in " ".join(map(str, conn.execute("SELECT * FROM refresh_tokens").fetchone()))


def test_bad_access_tokens_are_rejected(conn, monkeypatch):
    tokens = sessions.issue_tokens(conn, subject_id=uuid4(), role="patient", device_id="dev-1")
    for bad in ("", "garbage", tokens["access_token"][:-2] + "xx", tokens["refresh_token"]):
        with pytest.raises(jwt.InvalidTokenError):
            sessions.read_access_token(bad)
    with pytest.raises(jwt.InvalidTokenError):  # unsigned token
        sessions.read_access_token(jwt.encode({"sub": "x", "role": "admin", "device_id": "d", "exp": 9999999999},
                                              None, algorithm="none"))
    monkeypatch.setattr(sessions, "ACCESS_TTL", timedelta(seconds=-1))
    expired = sessions.issue_tokens(conn, subject_id=uuid4(), role="patient", device_id="dev-1")
    with pytest.raises(jwt.ExpiredSignatureError):
        sessions.read_access_token(expired["access_token"])


def test_refresh_rotates_and_reuse_ends_the_devices_sessions(conn):
    who = uuid4()
    first = sessions.issue_tokens(conn, subject_id=who, role="patient", device_id="dev-1")
    other_device = sessions.issue_tokens(conn, subject_id=who, role="patient", device_id="dev-2")
    second = sessions.refresh(conn, first["refresh_token"], "dev-1")
    assert sessions.read_access_token(second["access_token"])["sub"] == str(who)

    with pytest.raises(sessions.InvalidSession, match="token_reused"):
        sessions.refresh(conn, first["refresh_token"], "dev-1")
    with pytest.raises(sessions.InvalidSession):  # the stolen-token alarm also killed the new token
        sessions.refresh(conn, second["refresh_token"], "dev-1")
    sessions.refresh(conn, other_device["refresh_token"], "dev-2")  # other devices keep working
    assert ("auth.refresh_failed", "deny", "token_reused") in audit_rows(conn)


def test_refresh_denials(conn):
    who = uuid4()
    tokens = sessions.issue_tokens(conn, subject_id=who, role="patient", device_id="dev-1")
    with pytest.raises(sessions.InvalidSession, match="unknown_token"):
        sessions.refresh(conn, "made-up", "dev-1")
    with pytest.raises(sessions.InvalidSession, match="device_mismatch"):
        sessions.refresh(conn, tokens["refresh_token"], "dev-2")
    conn.execute("UPDATE refresh_tokens SET expires_at = clock_timestamp() - interval '1 second'")
    with pytest.raises(sessions.InvalidSession, match="expired"):
        sessions.refresh(conn, tokens["refresh_token"], "dev-1")

    fresh = sessions.issue_tokens(conn, subject_id=who, role="patient", device_id="dev-1")
    assert sessions.revoke_all(conn, who) == 2
    with pytest.raises(sessions.InvalidSession):
        sessions.refresh(conn, fresh["refresh_token"], "dev-1")
