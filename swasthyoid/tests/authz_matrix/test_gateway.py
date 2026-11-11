"""Gateway chain over HTTP (RBAC -> C1 -> C2), the role side of the authorization matrix,
Idempotency-Key handling, and the three P1 exit-gate checks (FRD section 11).

No P1 module serves patient data yet (the timeline is M4, phase P2), so the chain is
exercised through a probe route that exists only in this test module.
"""
from types import SimpleNamespace

import pytest
from fastapi import Depends
from fastapi.testclient import TestClient

from swasthyoid.api import deps
from swasthyoid.api.main import app
from swasthyoid.core import audit
from swasthyoid.core import consent_authz as c1
from swasthyoid.identity import accounts
from swasthyoid.tests.test_api_m1 import PROFILE, V1, api, approve, login, people, request_consent  # noqa: F401

served = []  # patient ids whose data the probe handler actually returned


@app.get("/api/v1/_probe/patients/{patient_id}/timeline")
def probe(patient_id: str, a: deps.Actor = Depends(deps.patient_read("TIMELINE", "timeline"))):
    served.append(patient_id)
    return {"patient_id": patient_id}


@pytest.fixture
def world(api, people):  # noqa: F811
    """The M1 cast plus ids, and a doctor whose credential is approved."""
    served.clear()
    approve(api, people)
    people.patient_id = api.conn.execute("SELECT id FROM patients").fetchone()[0]
    people.doctor_id = api.conn.execute("SELECT id FROM users WHERE role = 'doctor'").fetchone()[0]
    people.admin_id = api.conn.execute("SELECT id FROM users WHERE role = 'admin'").fetchone()[0]
    return SimpleNamespace(api=api, p=people)


def read(world, headers, patient_id=None):
    return world.api.http.get(f"{V1}/_probe/patients/{patient_id or world.p.patient_id}/timeline", headers=headers)


def grant(world, categories=("timeline",)):
    consent_id = request_consent(world.api, world.p, categories=list(categories)).json()["id"]
    r = world.api.http.post(f"{V1}/consents/requests/{consent_id}/confirm", headers=world.p.doctor,
                            json={"code": world.api.codes["+8801700000001"]})
    assert r.status_code == 200, r.text
    return consent_id


def read_audit(world):
    return world.api.conn.execute(
        "SELECT actor_id, patient_id, result, reason, consent_id FROM audit_logs "
        "WHERE action LIKE 'GET %%' ORDER BY seq").fetchall()


# ---- P1 exit gate

def test_exit_gate_doctor_without_consent_gets_403_and_an_audit_entry(world):
    r = read(world, world.p.doctor)
    assert r.status_code == 403
    assert r.json() == {"code": "consent_required", "message": "The patient has not allowed this access.",
                        "details": {}}
    assert served == []
    assert read_audit(world) == [(world.p.doctor_id, world.p.patient_id, "deny", "consent_required", None)]


def test_exit_gate_revoke_blocks_the_next_request(world):
    consent_id = grant(world)
    assert read(world, world.p.doctor).status_code == 200
    assert world.api.http.post(f"{V1}/consents/{consent_id}/revoke", headers=world.p.patient).status_code == 200
    r = read(world, world.p.doctor)
    assert (r.status_code, r.json()["code"]) == (403, "not_active")
    assert len(served) == 1
    assert [(row[2], row[3]) for row in read_audit(world)] == [("allow", None), ("deny", "not_active")]


def test_exit_gate_audit_chain_verifies_after_a_full_scenario(world):
    read(world, world.p.doctor)                      # denied
    consent_id = grant(world)
    read(world, world.p.doctor)                      # allowed
    read(world, {"Authorization": "Bearer garbage"})  # rejected token
    world.api.http.post(f"{V1}/consents/{consent_id}/revoke", headers=world.p.patient)
    read(world, world.p.doctor)                      # denied again
    assert world.api.conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0] >= 10
    assert audit.verify_stored(world.api.conn) is None

    history = world.api.http.get(f"{V1}/me/access-history", headers=world.p.patient).json()
    reads = [(h["result"], h["actor_name"]) for h in history if h["action"].startswith("GET ")]
    assert reads == [("deny", "Synthetic Doctor"), ("allow", "Synthetic Doctor"), ("deny", "Synthetic Doctor")]


# ---- authorization matrix: role and consent state, over HTTP

def test_patient_reads_own_data_without_consent_and_nobody_elses(world):
    assert read(world, world.p.patient).status_code == 200
    stranger = login(world.api, "+8801700000002", profile=PROFILE)
    r = read(world, stranger)
    assert (r.status_code, r.json()["code"]) == (403, "role_not_allowed")
    assert len(served) == 1


@pytest.mark.parametrize("role", ["pharmacist", "verifier", "clinical_reviewer", "admin"])
def test_other_roles_are_denied_even_with_a_consent_in_place(world, role):
    grant(world)
    if role == "admin":
        headers = world.p.admin
    else:
        headers = login(world.api, "+8801900000009", account="staff", staff={"role": role, "name": "Synthetic Staff"})
        world.api.conn.execute("UPDATE users SET status = 'verified' WHERE role = %s", [role])
    r = read(world, headers)
    assert (r.status_code, r.json()["code"]) == (403, "role_not_allowed")
    assert served == []
    denied = world.api.conn.execute(
        "SELECT actor_role, patient_id FROM audit_logs WHERE action = 'rbac.deny'").fetchall()
    assert denied == [(role, world.p.patient_id)]


def test_unverified_doctor_is_denied(world):
    other = login(world.api, "+8801900000003", account="staff", staff={"role": "doctor", "name": "Synthetic Doctor 2"})
    r = read(world, other)
    assert (r.status_code, r.json()["code"]) == (403, "user_not_verified")


@pytest.mark.parametrize("state, code", [
    ("pending", "not_active"), ("suspended", "not_active"), ("expired", "not_active"), ("revoked", "not_active"),
    ("active_but_past_expiry", "expired"), ("active_other_category", "category_not_allowed"),
])
def test_consent_states(world, state, code):
    if state == "pending":
        request_consent(world.api, world.p)
    else:
        consent_id = grant(world, ["documents"] if state == "active_other_category" else ["timeline"])
        if state == "active_but_past_expiry":
            world.api.conn.execute("UPDATE consents SET expires_at = clock_timestamp() - interval '1 second'")
        elif state in ("suspended", "expired", "revoked"):
            # set the stored state directly; the transitions themselves are tested in test_consent_store
            world.api.conn.execute("UPDATE consents SET status = %s WHERE id = %s", [state, consent_id])
    r = read(world, world.p.doctor)
    assert (r.status_code, r.json()["code"]) == (403, code)
    assert served == []


def test_consent_is_for_one_doctor_and_one_patient(world):
    grant(world)
    other = login(world.api, "+8801900000003", account="staff", staff={"role": "doctor", "name": "Synthetic Doctor 2"})
    world.api.conn.execute("UPDATE users SET status = 'verified' WHERE name = 'Synthetic Doctor 2'")
    assert read(world, other).json()["code"] == "consent_required"

    login(world.api, "+8801700000002", profile=PROFILE)
    second_patient = world.api.conn.execute(
        "SELECT id FROM patients WHERE id <> %s", [world.p.patient_id]).fetchone()[0]
    assert read(world, world.p.doctor, second_patient).json()["code"] == "consent_required"
    assert read(world, world.p.doctor).status_code == 200


def test_suspending_the_doctor_cuts_access_at_once(world):
    grant(world)
    assert read(world, world.p.doctor).status_code == 200
    accounts.suspend_user(world.api.conn, world.p.doctor_id, admin_id=world.p.admin_id)
    assert read(world, world.p.doctor).status_code == 401
    assert len(served) == 1


# ---- fail closed

def test_no_data_if_the_audit_write_fails(world, monkeypatch):
    grant(world)

    def broken(*args, **kwargs):
        raise RuntimeError("audit store down")

    monkeypatch.setattr(audit, "append", broken)
    r = TestClient(app, raise_server_exceptions=False).get(
        f"{V1}/_probe/patients/{world.p.patient_id}/timeline", headers=world.p.doctor)
    assert r.status_code == 500
    assert served == []


def test_no_data_if_the_consent_lookup_fails(world, monkeypatch):
    grant(world)

    def broken(*args, **kwargs):
        raise RuntimeError("consent store down")

    monkeypatch.setattr(c1, "find", broken)
    r = TestClient(app, raise_server_exceptions=False).get(
        f"{V1}/_probe/patients/{world.p.patient_id}/timeline", headers=world.p.doctor)
    assert r.status_code == 500
    assert served == []


# ---- Idempotency-Key

def consents(world):
    return world.api.conn.execute("SELECT count(*) FROM consents").fetchone()[0]


def test_same_key_runs_once_and_replays_the_response(world):
    key = {**world.p.doctor, "Idempotency-Key": "k-1"}
    body = {"health_id": world.p.health_id, "categories": ["timeline"]}
    first = world.api.http.post(f"{V1}/consents/requests", headers=key, json=body)
    code = world.api.codes["+8801700000001"]
    second = world.api.http.post(f"{V1}/consents/requests", headers=key, json=body)
    assert (first.status_code, second.status_code) == (201, 201)
    assert first.json() == second.json()
    assert consents(world) == 1
    assert world.api.codes["+8801700000001"] == code  # no second code was sent

    different = world.api.http.post(f"{V1}/consents/requests", headers=key,
                                    json={**body, "categories": ["documents"]})
    assert (different.status_code, different.json()["code"]) == (422, "idempotency_key_reused")
    world.api.http.post(f"{V1}/consents/requests", headers={**world.p.doctor, "Idempotency-Key": "k-2"}, json=body)
    world.api.http.post(f"{V1}/consents/requests", headers=world.p.doctor, json=body)  # no key: runs every time
    assert consents(world) == 3


def test_a_failed_request_is_not_stored_and_keys_are_per_caller_and_path(world):
    key = {"Idempotency-Key": "k-1"}
    bad = world.api.http.post(f"{V1}/consents/requests", headers={**world.p.doctor, **key},
                              json={"health_id": "SID-0000000000", "categories": ["timeline"]})
    assert bad.status_code == 404
    ok = world.api.http.post(f"{V1}/consents/requests", headers={**world.p.doctor, **key},
                             json={"health_id": world.p.health_id, "categories": ["timeline"]})
    assert ok.status_code == 201  # the failure left nothing behind, so the retry ran

    consent_id = ok.json()["id"]
    confirm = world.api.http.post(f"{V1}/consents/requests/{consent_id}/confirm", headers={**world.p.doctor, **key},
                                  json={"code": world.api.codes["+8801700000001"]})
    assert confirm.status_code == 200  # same key, different path: independent
    revoke = f"{V1}/consents/{consent_id}/revoke"
    first = world.api.http.post(revoke, headers={**world.p.patient, **key})  # same key, different caller
    again = world.api.http.post(revoke, headers={**world.p.patient, **key})
    assert (first.status_code, again.status_code) == (200, 200) and first.json() == again.json()
    assert world.api.http.post(revoke, headers=world.p.patient).status_code == 409  # without the key it really runs

    too_long = world.api.http.post(revoke, headers={**world.p.patient, "Idempotency-Key": "x" * 256})
    assert (too_long.status_code, too_long.json()["code"]) == (422, "invalid_idempotency_key")


def test_a_wrong_code_still_counts_when_sent_with_an_idempotency_key(world):
    consent_id = request_consent(world.api, world.p).json()["id"]
    code = world.api.codes["+8801700000001"]
    wrong = "000000" if code != "000000" else "111111"
    for i in range(5):
        r = world.api.http.post(f"{V1}/consents/requests/{consent_id}/confirm",
                                headers={**world.p.doctor, "Idempotency-Key": f"guess-{i}"}, json={"code": wrong})
        assert r.status_code == 403
    locked = world.api.http.post(f"{V1}/consents/requests/{consent_id}/confirm", headers=world.p.doctor,
                                 json={"code": code})
    assert locked.status_code == 403  # the guesses were counted, the code is dead
