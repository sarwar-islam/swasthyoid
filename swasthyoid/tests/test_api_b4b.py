"""B4b over HTTP: verifier assisted sessions (purpose ASSISTED_CAPTURE) and verifier access to the checking routes.

Synthetic data only, on a fresh database with the real schema (the `prod` fixture).
"""
import json

import pytest

from swasthyoid.identity import accounts
from swasthyoid.tests import images
from swasthyoid.tests.test_api_b4a import RX, events, in_review, put, staff  # noqa: F401
from swasthyoid.tests.test_extraction_integration import V1, patient, prod  # noqa: F401

PATIENT_PHONE = "+8801700000001"


@pytest.fixture
def v(prod, monkeypatch):  # noqa: F811
    monkeypatch.setenv("TIMELINE_CONSENT_HOURS", "24")
    monkeypatch.setenv("ASSIST_SESSION_MINUTES", "30")  # test value only; the real one is REVIEWER-PENDING
    prod.patient = patient(prod)
    me = prod.http.get(f"{V1}/me", headers=prod.patient).json()
    prod.pid, prod.health_id = me["id"], me["health_id"]
    prod.verifier = staff(prod, "+8801900000004", "verifier", "Synthetic Verifier")
    return prod


def start(v, health_id=None):
    r = v.http.post(f"{V1}/verifier/sessions", headers=v.verifier, json={"health_id": health_id or v.health_id})
    return r


def open_session(v):
    s = start(v).json()
    r = v.http.post(f"{V1}/verifier/sessions/{s['id']}/confirm", headers=v.verifier, json={"code": v.codes[PATIENT_PHONE]})
    assert r.status_code == 200, r.text
    return r.json()


def test_no_session_without_the_reviewer_pending_length(v, monkeypatch):
    monkeypatch.delenv("ASSIST_SESSION_MINUTES")
    r = start(v)
    assert (r.status_code, r.json()["code"]) == (503, "not_configured")


def test_the_patients_code_read_out_opens_a_short_session(v):
    assert start(v, "SID-0000000000").json()["code"] == "patient_not_found"
    s = start(v).json()
    assert (s["status"], s["patient_id"], s["purpose"]) == ("pending", None, "ASSISTED_CAPTURE")
    code = v.codes[PATIENT_PHONE]
    # nothing is reachable while the session waits for the code
    r = v.http.get(f"{V1}/patients/{v.pid}/documents", headers=v.verifier)
    assert (r.status_code, r.json()["code"]) == (403, "not_active")
    wrong = "000000" if code != "000000" else "111111"
    r = v.http.post(f"{V1}/verifier/sessions/{s['id']}/confirm", headers=v.verifier, json={"code": wrong})
    assert (r.status_code, r.json()["code"]) == (403, "invalid_code")
    r = v.http.post(f"{V1}/verifier/sessions/{s['id']}/confirm", headers=v.verifier, json={"code": code})
    active = r.json()
    assert (active["status"], active["patient_id"]) == ("active", v.pid)
    assert v.http.post(f"{V1}/verifier/sessions/{s['id']}/confirm", headers=v.verifier,
                       json={"code": code}).json()["code"] == "invalid_code"  # single use
    with v.connect() as conn:
        logged = json.dumps([list(r) for r in conn.execute("SELECT action, result, reason FROM audit_logs").fetchall()])
    assert code not in logged


def test_in_session_a_verifier_uploads_lists_and_checks_but_never_sees_the_record(v):
    open_session(v)
    up = v.http.post(f"{V1}/patients/{v.pid}/documents", headers=v.verifier, data={"doc_type": "prescription"},
                     files=[("images", ("page.jpg", images.JPEG, "image/jpeg"))])  # the verifier uploads for the patient
    assert up.status_code == 201, up.text
    doc_id = up.json()["id"]
    assert [d["id"] for d in v.http.get(f"{V1}/patients/{v.pid}/documents", headers=v.verifier).json()] == [doc_id]
    assert v.http.post(f"{V1}/documents/{doc_id}/manual-entry", headers=v.verifier).status_code == 200
    assert v.http.get(f"{V1}/documents/{doc_id}/extraction", headers=v.verifier).status_code == 200
    assert put(v, doc_id, RX, v.verifier).status_code == 200
    r = v.http.post(f"{V1}/documents/{doc_id}/confirm", headers=v.verifier)
    assert r.status_code == 200, r.text
    with v.connect() as conn:
        roles = conn.execute("SELECT DISTINCT actor_role FROM events WHERE source_document_id = %s", [doc_id]).fetchall()
        verifier_id = conn.execute("SELECT id FROM users WHERE role = 'verifier'").fetchone()[0]
        by = conn.execute("SELECT DISTINCT verified_by FROM events WHERE source_document_id = %s", [doc_id]).fetchall()
    assert roles == [("verifier",)] and by == [(verifier_id,)]
    # the verified document is now the record: its status line only, never its content, never the timeline
    assert v.http.get(f"{V1}/documents/{doc_id}", headers=v.verifier).json()["status"] == "verified"
    for path in (f"/documents/{doc_id}/images/1", f"/documents/{doc_id}/extraction"):
        assert v.http.get(f"{V1}{path}", headers=v.verifier).status_code == 404
    assert v.http.get(f"{V1}/patients/{v.pid}/documents", headers=v.verifier).json() == []
    r = v.http.get(f"{V1}/patients/{v.pid}/timeline", headers=v.verifier)
    assert (r.status_code, r.json()["code"]) == (403, "role_not_allowed")
    # every step reached the patient's access history
    history = v.http.get(f"{V1}/me/access-history", headers=v.patient).json()
    assert {"verifier"} <= {h["actor_role"] for h in history}
    assert any(h["purpose"] == "ASSISTED_CAPTURE" and h["result"] == "allow" for h in history)


def test_a_session_covers_one_patient_and_ends(v):
    session = open_session(v)
    other = patient(v, "+8801700000009")
    other_id = v.http.get(f"{V1}/me", headers=other).json()["id"]
    r = v.http.get(f"{V1}/patients/{other_id}/documents", headers=v.verifier)
    assert (r.status_code, r.json()["code"]) == (403, "consent_required")
    ended = v.http.post(f"{V1}/verifier/sessions/{session['id']}/end", headers=v.verifier).json()
    assert ended["status"] == "revoked"
    r = v.http.get(f"{V1}/patients/{v.pid}/documents", headers=v.verifier)
    assert (r.status_code, r.json()["code"]) == (403, "not_active")


def test_an_expired_session_grants_nothing(v):
    session = open_session(v)
    with v.connect() as conn:
        conn.execute("UPDATE consents SET expires_at = clock_timestamp() - interval '1 second' WHERE id = %s", [session["id"]])
    r = v.http.get(f"{V1}/patients/{v.pid}/documents", headers=v.verifier)
    assert (r.status_code, r.json()["code"]) == (403, "expired")


def test_suspension_revokes_open_sessions_for_good(v):
    session = open_session(v)
    with v.connect() as conn:
        admin_id = conn.execute("SELECT id FROM users WHERE role = 'admin'").fetchone()[0]
        verifier_id = conn.execute("SELECT id FROM users WHERE role = 'verifier'").fetchone()[0]
        accounts.suspend_user(conn, verifier_id, admin_id=admin_id, reason="SYNTH")
        accounts.restore_user(conn, verifier_id, admin_id=admin_id)
        status = conn.execute("SELECT status FROM consents WHERE id = %s", [session["id"]]).fetchone()[0]
    assert status == "revoked"  # a restored account does not get the old session back


def test_only_a_verified_verifier_starts_sessions_and_only_their_own(v):
    doctor = staff(v, "+8801900000002", "doctor", "Synthetic Doctor")
    for headers in (v.patient, doctor):
        r = v.http.post(f"{V1}/verifier/sessions", headers=headers, json={"health_id": v.health_id})
        assert (r.status_code, r.json()["code"]) == (403, "role_not_allowed")
    session = start(v).json()
    other = staff(v, "+8801900000014", "verifier", "Synthetic Verifier 2")
    assert v.http.post(f"{V1}/verifier/sessions/{session['id']}/confirm", headers=other,
                       json={"code": v.codes[PATIENT_PHONE]}).status_code == 404
    assert v.http.post(f"{V1}/verifier/sessions/{session['id']}/end", headers=other).status_code == 404


def test_a_doctor_or_caregiver_still_cannot_check(v):
    doc_id = in_review(v)
    doctor = staff(v, "+8801900000002", "doctor", "Synthetic Doctor")
    for path in ("confirm", "reject", "manual-entry"):
        r = v.http.post(f"{V1}/documents/{doc_id}/{path}", headers=doctor)
        assert (r.status_code, r.json()["code"]) == (403, "role_not_allowed")
    stranger = patient(v, "+8801700000009")
    assert put(v, doc_id, RX, stranger).status_code == 404
    assert events(v, doc_id) == []
