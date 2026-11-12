"""Caregiver-assisted access (docs/DECISIONS.md, "Caregiver access"). Synthetic people only.

No documents or timeline exist yet, so the three scopes are exercised through probe routes
that exist only in this test module and use the real gateway chain.
"""
import itertools
import threading
from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest
from fastapi import Depends

from swasthyoid import pii
from swasthyoid.api import caregivers, deps
from swasthyoid.api.main import app
from swasthyoid.core import audit, notification
from swasthyoid.core import consent_authz as c1
from swasthyoid.identity import otp
from swasthyoid.tests.test_api_m1 import PROFILE, V1, api, login  # noqa: F401

PATIENT, CAREGIVER, OTHER = "+8801700000001", "+8801700000002", "+8801700000003"
SCOPES = ["upload_documents", "view_documents", "view_timeline"]
URL = f"{V1}/caregiver-authorizations"
handled = []


@app.get("/api/v1/_cg/patients/{patient_id}/timeline")
def _timeline(patient_id: str, a=Depends(deps.patient_read("TIMELINE", "timeline", caregiver="view_timeline"))):
    handled.append(("view_timeline", str(a.id)))
    return {}


@app.get("/api/v1/_cg/patients/{patient_id}/documents")
def _documents(patient_id: str, a=Depends(deps.patient_read("TIMELINE", "documents", caregiver="view_documents"))):
    handled.append(("view_documents", str(a.id)))
    return {}


@app.post("/api/v1/_cg/patients/{patient_id}/documents")
def _upload(patient_id: str, a=Depends(deps.patient_read("TIMELINE", "documents", roles=(),
                                                         caregiver="upload_documents"))):
    handled.append(("upload_documents", str(a.id)))
    return {}


PROBES = {"upload_documents": "post", "view_documents": "get", "view_timeline": "get"}


@pytest.fixture
def w(api, monkeypatch):  # noqa: F811
    handled.clear()
    monkeypatch.setattr(caregivers, "RESPONSE_FLOOR", 0)
    api.messages = {}

    def send(phone, code, context=None):  # mocked code delivery
        api.codes[phone] = code
        api.messages[phone] = context

    app.dependency_overrides[deps.get_code_sender] = lambda: send

    def person(phone, name):
        headers = login(api, phone, profile={**PROFILE, "name": name})
        pid, hid = api.conn.execute(
            "SELECT id, health_id FROM patients WHERE phone_hash = %s", [pii.phone_hash(phone)]).fetchone()
        return SimpleNamespace(h=headers, id=pid, health_id=hid, phone=phone)

    return SimpleNamespace(api=api, http=api.http, conn=api.conn, person=person,
                           patient=person(PATIENT, "Synthetic Elder"),
                           caregiver=person(CAREGIVER, "Synthetic Daughter"))


def ask(w, scopes=("view_timeline",), who=None, health_id=None, **extra):
    who = who or w.caregiver
    body = {"patient_health_id": health_id or w.patient.health_id, "scopes": list(scopes), **extra}
    return w.http.post(URL, headers={**who.h, **extra.pop("headers", {})}, json=body)


def pending_id(w, who=None):
    row = w.conn.execute(
        "SELECT id FROM consents WHERE purpose = 'CAREGIVER' AND status = 'pending' AND grantee_id = %s",
        [(who or w.caregiver).id]).fetchone()
    return row and row[0]


def grant(w, scopes=("view_timeline",), who=None, **extra):
    assert ask(w, scopes, who, **extra).status_code == 202
    consent_id = pending_id(w, who)
    r = w.http.post(f"{URL}/{consent_id}/approve", headers=w.patient.h)
    assert r.status_code == 200, r.text
    return consent_id


def probe(w, scope, who=None, patient=None):
    url = f"{V1}/_cg/patients/{(patient or w.patient).id}/{'timeline' if scope == 'view_timeline' else 'documents'}"
    return getattr(w.http, PROBES[scope])(url, headers=(who or w.caregiver).h)


def can(w, who=None):
    return {s for s in SCOPES if probe(w, s, who).status_code == 200}


def statuses(w):
    return sorted(r[0] for r in w.conn.execute("SELECT status FROM consents WHERE purpose = 'CAREGIVER'"))


def race(*fns):
    barrier, out = threading.Barrier(len(fns)), [None] * len(fns)

    def run(i, fn):
        barrier.wait()
        try:
            out[i] = ("ok", fn())
        except Exception as e:
            out[i] = ("err", e)

    threads = [threading.Thread(target=run, args=(i, fn)) for i, fn in enumerate(fns)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return out


# ---- request and the two ways a patient authorises

def test_request_grants_nothing_and_patient_sees_who_and_what(w):
    r = ask(w, ["view_timeline", "upload_documents"], duration_days=14)
    assert (r.status_code, r.json()) == (202, {"status": "pending"})
    assert can(w) == set()
    assert probe(w, "view_timeline").json()["code"] == "not_active"

    shown = w.http.get(f"{V1}/consents", headers=w.patient.h).json()
    assert len(shown) == 1
    assert (shown[0]["status"], shown[0]["purpose"], shown[0]["grantee_role"]) == ("pending", "CAREGIVER", "caregiver")
    assert (shown[0]["grantee_name"], shown[0]["grantee_phone_tail"]) == ("Synthetic Daughter", "002")
    assert sorted(shown[0]["allowed_categories"]) == ["upload_documents", "view_timeline"]
    assert shown[0]["requested_days"] == 14
    # the message carrying the code states the same identity, scopes and duration
    assert w.api.messages[PATIENT] == {"caregiver_name": "Synthetic Daughter", "caregiver_phone_tail": "002",
                                       "scopes": ["upload_documents", "view_timeline"], "days": 14}
    assert w.http.get(URL, headers=w.caregiver.h).json() == []  # pending is never listed to the caregiver


def test_patient_approves_in_the_app(w):
    ask(w, ["view_timeline"])  # default duration
    r = w.http.post(f"{URL}/{pending_id(w)}/approve", headers=w.patient.h)
    assert r.status_code == 200 and r.json()["status"] == "active"
    method, lifetime = w.conn.execute(
        "SELECT method, expires_at - activated_at FROM consents WHERE purpose = 'CAREGIVER'").fetchone()
    assert (method, lifetime) == ("in-app", timedelta(days=c1.CAREGIVER_DEFAULT_DAYS))
    assert can(w) == {"view_timeline"}
    mine = w.http.get(URL, headers=w.caregiver.h).json()
    assert [(m["patient_id"], m["patient_name"], m["scopes"]) for m in mine] == [
        (str(w.patient.id), "Synthetic Elder", ["view_timeline"])]
    assert ("CAREGIVER_GRANTED_PLACEHOLDER",) in w.conn.execute("SELECT template_id FROM notifications").fetchall()


def test_patient_authorises_by_code_once(w):
    ask(w, ["view_documents"])
    code = w.api.codes[PATIENT]
    body = {"patient_health_id": w.patient.health_id, "code": code}
    wrong = {**body, "code": "000000" if code != "000000" else "111111"}
    bad = w.http.post(f"{URL}/confirm", headers=w.caregiver.h, json=wrong)
    assert (bad.status_code, bad.json()["code"]) == (403, "invalid_code")
    assert can(w) == set()

    ok = w.http.post(f"{URL}/confirm", headers=w.caregiver.h, json=body)
    assert ok.status_code == 200 and ok.json()["status"] == "active"
    assert w.conn.execute("SELECT method FROM consents WHERE purpose = 'CAREGIVER'").fetchone()[0] == "OTP"
    assert can(w) == {"view_documents"}
    again = w.http.post(f"{URL}/confirm", headers=w.caregiver.h, json=body)  # single use
    assert (again.status_code, again.json()["code"]) == (403, "invalid_code")
    assert statuses(w) == ["active"]


def test_code_expiry_and_brute_force_lockout(w):
    ask(w)
    body = {"patient_health_id": w.patient.health_id, "code": w.api.codes[PATIENT]}
    w.conn.execute("UPDATE otp_codes SET expires_at = clock_timestamp() - interval '1 second' WHERE kind = 'caregiver'")
    assert w.http.post(f"{URL}/confirm", headers=w.caregiver.h, json=body).status_code == 403

    ask(w)  # asking again sends a fresh code for the same request
    code = w.api.codes[PATIENT]
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(otp.MAX_ATTEMPTS):
        w.http.post(f"{URL}/confirm", headers=w.caregiver.h, json={**body, "code": wrong})
    dead = w.http.post(f"{URL}/confirm", headers=w.caregiver.h, json={**body, "code": code})
    assert dead.status_code == 403
    assert statuses(w) == ["pending"] and can(w) == set()
    reasons = [r[0] for r in w.conn.execute(
        "SELECT reason FROM audit_logs WHERE action = 'auth.otp_failed' AND actor_id = %s AND patient_id = %s",
        [w.caregiver.id, w.patient.id])]
    assert reasons.count("wrong_code") == otp.MAX_ATTEMPTS and "too_many_attempts" in reasons


def test_code_limits_per_request(w):
    for _ in range(caregivers.MAX_CODES_PER_REQUEST):
        w.api.codes.pop(PATIENT, None)
        assert ask(w).json() == {"status": "pending"}
        assert PATIENT in w.api.codes
    w.api.codes.pop(PATIENT)
    assert (ask(w).status_code, ask(w).json()) == (202, {"status": "pending"})  # same answer, no new code
    assert PATIENT not in w.api.codes
    assert statuses(w) == ["pending"]


def test_a_code_is_bound_to_its_own_request(w):
    other = w.person(OTHER, "Synthetic Son")
    ask(w, ["view_timeline"])
    first_code = w.api.codes[PATIENT]
    ask(w, ["view_timeline"], who=other)
    second_code = w.api.codes[PATIENT]
    body = {"patient_health_id": w.patient.health_id}
    if first_code != second_code:  # the son cannot use the daughter's code
        assert w.http.post(f"{URL}/confirm", headers=other.h, json={**body, "code": first_code}).status_code == 403
    stolen = w.http.post(f"{V1}/auth/otp/verify", json={"phone": PATIENT, "code": second_code, "device_id": "x"})
    assert stolen.status_code == 401  # nor can it log anyone in as the patient
    assert w.http.post(f"{URL}/confirm", headers=other.h, json={**body, "code": second_code}).status_code == 200
    assert can(w, other) == {"view_timeline"} and can(w) == set()


# ---- scopes

@pytest.mark.parametrize("granted", [c for n in (1, 2, 3) for c in itertools.combinations(SCOPES, n)])
def test_each_scope_allows_only_its_own_action(w, granted):
    grant(w, granted)
    assert can(w) == set(granted)
    assert sorted(h[0] for h in handled) == sorted(granted)  # handlers ran only for granted scopes


def test_unauthorised_callers(w):
    grant(w, SCOPES)
    stranger = w.person(OTHER, "Synthetic Stranger")
    assert can(w, stranger) == set()
    assert probe(w, "view_timeline", stranger).json()["code"] == "consent_required"
    assert probe(w, "view_timeline", patient=stranger).json()["code"] == "consent_required"  # wrong patient
    assert can(w, w.patient) == set(SCOPES)  # the patient needs no authorisation for their own data

    doctor = login(w.api, "+8801900000002", account="staff", staff={"role": "doctor", "name": "Synthetic Doctor"})
    w.conn.execute("UPDATE users SET status = 'verified'")
    as_doctor = SimpleNamespace(h=doctor)
    assert probe(w, "view_timeline", as_doctor).json()["code"] == "consent_required"  # needs a TIMELINE consent
    assert probe(w, "upload_documents", as_doctor).json()["code"] == "role_not_allowed"
    unauthenticated = SimpleNamespace(h={})
    assert probe(w, "view_timeline", unauthenticated).status_code == 401


def test_caregiver_cannot_act_as_the_patient_elsewhere(w):
    consent_id = grant(w, SCOPES)
    assert w.http.post(f"{V1}/consents/{consent_id}/revoke", headers=w.caregiver.h).status_code == 404
    assert w.http.get(f"{V1}/consents", headers=w.caregiver.h).json() == []
    assert w.http.get(f"{V1}/me/access-history", headers=w.caregiver.h).json() == []
    ask(w, ["view_timeline"])  # a renewal request
    renewal = pending_id(w)
    for action in ("approve", "decline"):  # the caregiver cannot answer their own request
        assert w.http.post(f"{URL}/{renewal}/{action}", headers=w.caregiver.h).status_code == 404
    assert statuses(w) == ["active", "pending"]


# ---- scope escalation and atomic replacement

def test_verify_scope_is_refused_at_every_level(w):
    assert ask(w, ["view_timeline", "verify_documents"]).status_code == 422
    with pytest.raises(ValueError):
        c1.request_caregiver(w.conn, patient_id=w.patient.id, caregiver_id=w.caregiver.id,
                             scopes={"verify_documents"}, days=30, consent_version=0, policy_version="P")
    with pytest.raises(psycopg.errors.CheckViolation):
        c1.create(w.conn, patient_id=w.patient.id, grantee_id=w.caregiver.id, grantee_role="caregiver",
                  purpose="CAREGIVER", allowed_categories={"verify_documents"}, consent_version=0,
                  policy_version="P", actor_id=w.caregiver.id, requested_ttl=timedelta(days=30))
    assert statuses(w) == []


def test_more_scopes_need_a_new_approval_and_replace_atomically(w):
    first = grant(w, ["view_timeline"])
    assert ask(w, ["view_timeline", "view_documents"]).status_code == 202
    assert can(w) == {"view_timeline"}  # asking changes nothing
    assert ask(w, SCOPES).status_code == 202  # asking again cannot widen the open request
    assert sorted(w.conn.execute("SELECT allowed_categories FROM consents WHERE status = 'pending'").fetchone()[0]) == [
        "view_documents", "view_timeline"]

    w.http.post(f"{URL}/{pending_id(w)}/approve", headers=w.patient.h)
    assert can(w) == {"view_timeline", "view_documents"}
    assert statuses(w) == ["active", "revoked"]
    assert w.conn.execute("SELECT status, revoked_by FROM consents WHERE id = %s", [first]).fetchone() == (
        "revoked", w.patient.id)

    grant(w, ["upload_documents"])  # a narrower grant replaces, it does not merge
    assert can(w) == {"upload_documents"}
    assert statuses(w) == ["active", "revoked", "revoked"]


def test_failed_replacement_keeps_the_old_grant(w, monkeypatch):
    grant(w, ["view_timeline"])
    ask(w, SCOPES)
    real, calls = audit.append, []

    def fail_on_activate(conn, **fields):
        calls.append(fields["action"])
        if fields["action"] == "consent.activate":
            raise RuntimeError("audit store down")
        return real(conn, **fields)

    monkeypatch.setattr(audit, "append", fail_on_activate)
    with pytest.raises(RuntimeError):
        w.http.post(f"{URL}/{pending_id(w)}/approve", headers=w.patient.h)
    monkeypatch.undo()
    assert "consent.replace" in calls  # the old grant had been ended inside the same transaction ...
    assert statuses(w) == ["active", "pending"]  # ... and came back when the activation failed
    assert can(w) == {"view_timeline"}


def test_database_enforces_pair_uniqueness_duration_and_shape(w):
    def insert(status="pending", ttl=timedelta(days=30), **over):
        fields = dict(patient_id=w.patient.id, grantee_id=w.caregiver.id, grantee_role="caregiver",
                      scopes=["view_timeline"])
        fields.update(over)
        with w.conn.transaction():
            w.conn.execute(
                "INSERT INTO consents (id, patient_id, grantee_id, grantee_role, purpose, allowed_categories, status, "
                "activated_at, expires_at, consent_version, policy_version, requested_ttl) "
                "VALUES (%s, %s, %s, %s, 'CAREGIVER', %s, %s, clock_timestamp(), clock_timestamp() + %s, 0, 'P', %s)",
                [uuid4(), fields["patient_id"], fields["grantee_id"], fields["grantee_role"], fields["scopes"],
                 status, over.get("lifetime", ttl), ttl])

    insert("pending")
    insert("active")
    for status in ("pending", "active"):
        with pytest.raises(psycopg.errors.UniqueViolation):
            insert(status)
    for bad in ({"ttl": timedelta(days=91)}, {"ttl": timedelta(0)}, {"ttl": None},
                {"lifetime": timedelta(days=91), "grantee_id": uuid4()},  # expiry beyond the maximum
                {"grantee_id": w.patient.id}, {"grantee_role": "doctor", "grantee_id": uuid4()},
                {"scopes": ["timeline"], "grantee_id": uuid4()}):
        with pytest.raises(psycopg.errors.CheckViolation):
            insert("pending", **bad)
    for days in (0, 91, 30.5, None):
        with pytest.raises(ValueError):
            c1.request_caregiver(w.conn, patient_id=w.patient.id, caregiver_id=uuid4(), scopes={"view_timeline"},
                                 days=days, consent_version=0, policy_version="P")
    assert ask(w, duration_days=91).status_code == 422 and ask(w, duration_days=0).status_code == 422
    assert ask(w, scopes=[]).status_code == 422


# ---- decline, expiry, revocation

def test_decline_is_not_expiry(w):
    ask(w)
    declined = pending_id(w)
    assert w.http.post(f"{URL}/{declined}/decline", headers=w.patient.h).json()["status"] == "declined"
    assert w.http.post(f"{URL}/{declined}/approve", headers=w.patient.h).status_code == 409
    assert w.http.post(f"{URL}/confirm", headers=w.caregiver.h,
                       json={"patient_health_id": w.patient.health_id, "code": w.api.codes[PATIENT]}).status_code == 403

    ask(w)  # a new request is allowed after a decline
    stale = pending_id(w)
    code = w.api.codes[PATIENT]
    w.conn.execute("UPDATE consents SET created_at = clock_timestamp() - interval '25 hours' WHERE id = %s", [stale])
    r = w.http.post(f"{URL}/{stale}/approve", headers=w.patient.h)  # enforced at request time, no sweep ran
    assert (r.status_code, r.json()["code"]) == (409, "not_pending")
    assert w.http.post(f"{URL}/confirm", headers=w.caregiver.h,
                       json={"patient_health_id": w.patient.health_id, "code": code}).status_code == 403
    assert statuses(w) == ["declined", "expired"] and can(w) == set()
    actions = [r[0] for r in w.conn.execute(
        "SELECT action FROM consent_events e JOIN consents c ON c.id = e.consent_id "
        "WHERE c.purpose = 'CAREGIVER' AND action IN ('decline', 'expire') ORDER BY e.at")]
    assert actions == ["decline", "expire"]
    ask(w)
    assert statuses(w) == ["declined", "expired", "pending"]


def test_stale_request_shows_as_expired_to_the_patient(w):
    ask(w)
    w.conn.execute("UPDATE consents SET created_at = clock_timestamp() - interval '25 hours'")
    assert [c["status"] for c in w.http.get(f"{V1}/consents", headers=w.patient.h).json()] == ["expired"]


def test_revocation_blocks_the_next_request(w):
    consent_id = grant(w, SCOPES)
    assert can(w) == set(SCOPES)
    assert w.http.post(f"{V1}/consents/{consent_id}/revoke", headers=w.patient.h).status_code == 200
    r = probe(w, "view_timeline")
    assert (r.status_code, r.json()["code"]) == (403, "not_active")
    assert can(w) == set() and w.http.get(URL, headers=w.caregiver.h).json() == []
    grant(w, ["view_timeline"])  # a fresh approval is needed and possible
    assert can(w) == {"view_timeline"}


def test_expiry_is_enforced_without_a_sweep(w):
    grant(w, SCOPES, duration_days=1)
    w.conn.execute("UPDATE consents SET activated_at = activated_at - interval '2 days', "
                   "expires_at = clock_timestamp() - interval '1 second' WHERE purpose = 'CAREGIVER'")
    r = probe(w, "view_documents")
    assert (r.status_code, r.json()["code"]) == (403, "expired")
    assert statuses(w) == ["active"]  # no job ran; the time check alone denied it
    assert w.http.get(URL, headers=w.caregiver.h).json() == []
    with pytest.raises(psycopg.errors.CheckViolation):  # there is no permanent authorisation
        w.conn.execute("UPDATE consents SET expires_at = activated_at + interval '10 years' WHERE purpose = 'CAREGIVER'")


# ---- concurrency

def test_simultaneous_requests_make_one_pending_row(w, connect):
    def one():
        conn = connect()
        conn.autocommit = True
        return c1.request_caregiver(conn, patient_id=w.patient.id, caregiver_id=w.caregiver.id,
                                    scopes={"view_timeline"}, days=30, consent_version=0, policy_version="P")

    results = race(*[one] * 6)
    assert [r[0] for r in results] == ["ok"] * 6
    assert len({r[1][0]["id"] for r in results}) == 1 and sum(r[1][1] for r in results) == 1
    assert statuses(w) == ["pending"]


def test_simultaneous_app_approval_and_code_confirmation_activate_once(w, connect):
    grant(w, ["view_timeline"])
    ask(w, ["view_documents"])
    consent_id = pending_id(w)

    def approve(method):
        def run():
            conn = connect()
            conn.autocommit = True
            return c1.approve_caregiver(conn, consent_id, patient_id=w.patient.id, method=method)
        return run

    results = race(approve("in-app"), approve("OTP"), approve("in-app"))
    assert sorted(r[0] for r in results) == ["err", "err", "ok"]
    assert all(isinstance(r[1], ValueError) for r in results if r[0] == "err")
    assert statuses(w) == ["active", "revoked"] and can(w) == {"view_documents"}
    assert audit.verify_stored(w.conn) is None


def test_simultaneous_confirmations_use_the_code_once(w, connect):
    ask(w)
    consent_id, code = pending_id(w), w.api.codes[PATIENT]

    def confirm():
        conn = connect()
        conn.autocommit = True
        return otp.verify_code(conn, PATIENT, code, kind="caregiver", ref=str(consent_id))

    assert sorted(r[1] for r in race(*[confirm] * 5)) == [False, False, False, False, True]


@pytest.mark.parametrize("round_", range(5))
def test_simultaneous_approval_and_revocation_stay_consistent(w, connect, round_):
    old = grant(w, ["view_timeline"])
    ask(w, ["view_documents"])
    new = pending_id(w)

    def run(fn):
        def go():
            conn = connect()
            conn.autocommit = True
            return fn(conn)
        return go

    results = race(
        run(lambda conn: c1.approve_caregiver(conn, new, patient_id=w.patient.id, method="in-app")),
        run(lambda conn: c1.revoke(conn, old, actor_id=w.patient.id)),
    )
    assert results[0][0] == "ok"  # the approval always wins through
    if results[1][0] == "err":    # the revoke lost the race: the grant was already replaced
        assert isinstance(results[1][1], ValueError)
    assert statuses(w) == ["active", "revoked"]
    assert can(w) == {"view_documents"}  # never the old scope, never both
    assert audit.verify_stored(w.conn) is None

    assert w.http.post(f"{V1}/consents/{new}/revoke", headers=w.patient.h).status_code == 200
    assert can(w) == set()


# ---- idempotency and keyed hashing

def test_idempotent_request_sends_one_code(w):
    key = {"Idempotency-Key": "k-1"}
    body = {"patient_health_id": w.patient.health_id, "scopes": ["view_timeline"]}
    first = w.http.post(URL, headers={**w.caregiver.h, **key}, json=body)
    w.api.codes.pop(PATIENT)
    second = w.http.post(URL, headers={**w.caregiver.h, **key}, json=body)
    assert (first.status_code, second.status_code) == (202, 202) and first.json() == second.json()
    assert PATIENT not in w.api.codes
    assert w.conn.execute("SELECT count(*) FROM otp_codes WHERE kind = 'caregiver'").fetchone()[0] == 1
    reused = w.http.post(URL, headers={**w.caregiver.h, **key}, json={**body, "scopes": SCOPES})
    assert (reused.status_code, reused.json()["code"]) == (422, "idempotency_key_reused")


def test_codes_never_reach_storage_logs_or_audit(w, monkeypatch, caplog):
    marker = "CODE-MARKER-7391"
    monkeypatch.setattr(otp, "_new_code", lambda: marker)
    caplog.set_level("DEBUG")
    ask(w, headers={"Idempotency-Key": "ask"})
    assert w.api.codes[PATIENT] == marker
    body = {"patient_health_id": w.patient.health_id, "code": marker}
    wrong = w.http.post(f"{URL}/confirm", headers={**w.caregiver.h, "Idempotency-Key": "c1"},
                        json={**body, "code": marker + "x"})
    assert wrong.status_code == 403
    ok = w.http.post(f"{URL}/confirm", headers={**w.caregiver.h, "Idempotency-Key": "c2"}, json=body)
    assert ok.status_code == 200 and marker not in ok.text
    replay = w.http.post(f"{URL}/confirm", headers={**w.caregiver.h, "Idempotency-Key": "c2"}, json=body)
    assert replay.json() == ok.json()

    tables = ("audit_logs", "consents", "consent_events", "notifications", "notification_deliveries",
              "idempotency_keys", "otp_codes", "refresh_tokens")
    for table in tables:
        dump = str(w.conn.execute(f"SELECT * FROM {table}").fetchall())
        assert "MARKER" not in dump, table
    assert "MARKER" not in caplog.text

    import hashlib
    stored = {r[0] for r in w.conn.execute("SELECT request_hash FROM idempotency_keys")}
    plain = hashlib.sha256(caregivers.ConfirmBody(**body).model_dump_json().encode()).hexdigest()
    keyed = pii.secret_hash("idempotency:" + caregivers.ConfirmBody(**body).model_dump_json())
    assert keyed in stored and plain not in stored


# ---- Health ID enumeration

def test_unknown_health_id_is_indistinguishable(w):
    known = ask(w)
    unknown = ask(w, health_id="SID-0000000000")
    own = ask(w, health_id=w.caregiver.health_id)  # asking about yourself is treated the same
    assert {(r.status_code, r.text) for r in (known, unknown, own)} == {(202, '{"status":"pending"}')}
    assert {r.headers.keys() == known.headers.keys() for r in (unknown, own)} == {True}
    assert statuses(w) == ["pending"]
    assert w.http.get(URL, headers=w.caregiver.h).json() == []

    confirm = [w.http.post(f"{URL}/confirm", headers=w.caregiver.h, json={"patient_health_id": hid, "code": "000001"})
               for hid in (w.patient.health_id, "SID-0000000000", w.caregiver.health_id)]
    assert len({(r.status_code, r.text) for r in confirm}) == 1 and confirm[0].status_code == 403
    probes = w.conn.execute(
        "SELECT result, reason, patient_id FROM audit_logs WHERE action = 'caregiver.request' ORDER BY seq").fetchall()
    assert probes == [("allow", None, w.patient.id), ("deny", "no_such_patient", None), ("deny", "no_such_patient", None)]


def test_attempt_limit_counts_misses_and_hits_alike(w):
    for _ in range(caregivers.MAX_REQUESTS):
        assert ask(w, health_id="SID-0000000000").status_code == 202
    limited = [ask(w, health_id=hid) for hid in ("SID-0000000000", w.patient.health_id)]
    assert {(r.status_code, r.json()["code"]) for r in limited} == {(429, "too_many_requests")}
    assert statuses(w) == []


def test_response_time_floor_applies_to_hits_and_misses(w, monkeypatch):
    slept = []
    monkeypatch.setattr(caregivers, "RESPONSE_FLOOR", 30)
    monkeypatch.setattr(caregivers.time, "sleep", slept.append)
    ask(w)
    ask(w, health_id="SID-0000000000")
    w.http.post(f"{URL}/confirm", headers=w.caregiver.h, json={"patient_health_id": "SID-0000000000", "code": "1"})
    assert len(slept) == 3 and all(25 < s <= 30 for s in slept)


def test_code_is_sent_after_the_response(w):
    order = []
    app.dependency_overrides[deps.get_code_sender] = lambda: lambda *a: order.append("sent")
    real = caregivers._floor
    caregivers._floor = lambda started: order.append("answered")
    try:
        ask(w)
    finally:
        caregivers._floor = real
    assert order == ["answered", "sent"]


# ---- DEV_LOG_CODES

def test_dev_code_logging_is_off_by_default_and_refused_outside_development(monkeypatch, caplog):
    monkeypatch.delenv("DEV_LOG_CODES", raising=False)
    monkeypatch.delenv("APP_ENV", raising=False)
    deps.check_config()
    assert deps.get_code_sender() is deps.no_code_delivery
    with pytest.raises(deps.ApiError) as e:
        deps.get_code_sender()("+8801700000001", "123456")
    assert (e.value.status, e.value.code) == (503, "code_delivery_unavailable")

    monkeypatch.setenv("DEV_LOG_CODES", "1")
    for env in (None, "production", "staging"):
        monkeypatch.delenv("APP_ENV", raising=False) if env is None else monkeypatch.setenv("APP_ENV", env)
        with pytest.raises(RuntimeError):
            deps.check_config()
        assert deps.get_code_sender() is deps.no_code_delivery
    monkeypatch.setenv("APP_ENV", "production")
    from fastapi.testclient import TestClient
    with pytest.raises(RuntimeError):
        with TestClient(app):  # the application itself refuses to start
            pass

    monkeypatch.setenv("APP_ENV", "development")
    deps.check_config()
    assert deps.get_code_sender() is notification.send_code_dev
    deps.get_code_sender()("+8801700000001", "123456", {"caregiver_name": "Synthetic Daughter"})
    assert "123456" in caplog.text and "+8801700000001" not in caplog.text and "Synthetic" not in caplog.text


def test_without_a_gateway_login_codes_are_unavailable_not_logged(w, caplog):
    app.dependency_overrides.pop(deps.get_code_sender)
    r = w.http.post(f"{V1}/auth/otp/request", json={"phone": OTHER})
    assert (r.status_code, r.json()["code"]) == (503, "code_delivery_unavailable")
    assert ask(w).status_code == 202  # the caregiver answer stays uniform; delivery failure is logged without the code
    assert "code delivery failed: ApiError" in caplog.text


# ---- audit attribution

def test_every_caregiver_action_names_caregiver_and_patient(w):
    probe(w, "view_timeline")  # denied before any grant
    consent_id = grant(w, ["view_timeline"])
    probe(w, "view_timeline")
    probe(w, "view_documents")
    rows = w.conn.execute(
        "SELECT actor_id, actor_role, patient_id, purpose, result, reason, consent_id FROM audit_logs "
        "WHERE action LIKE '%%/_cg/%%' ORDER BY seq").fetchall()
    who = (w.caregiver.id, "caregiver", w.patient.id, "CAREGIVER")
    assert rows == [(*who, "deny", "consent_required", None), (*who, "allow", None, consent_id),
                    (*who, "deny", "category_not_allowed", consent_id)]
    lifecycle = w.conn.execute(
        "SELECT action, actor_id, patient_id FROM audit_logs WHERE consent_id = %s AND action LIKE 'consent.%%' "
        "ORDER BY seq", [consent_id]).fetchall()
    assert lifecycle == [("consent.create", w.caregiver.id, w.patient.id),
                         ("consent.activate", w.patient.id, w.patient.id)]

    history = w.http.get(f"{V1}/me/access-history", headers=w.patient.h).json()
    reads = [(h["actor_name"], h["purpose"], h["result"]) for h in history if "/_cg/" in h["action"]]
    assert reads == [("Synthetic Daughter", "CAREGIVER", "deny"), ("Synthetic Daughter", "CAREGIVER", "allow"),
                     ("Synthetic Daughter", "CAREGIVER", "deny")]
    assert audit.verify_stored(w.conn) is None


def test_strangers_who_probe_are_audited_but_not_named(w):
    stranger = w.person(OTHER, "Synthetic Stranger")
    probe(w, "view_timeline", stranger)
    history = w.http.get(f"{V1}/me/access-history", headers=w.patient.h).json()
    assert [(h["actor_id"], h["actor_name"]) for h in history if "/_cg/" in h["action"]] == [(str(stranger.id), None)]
