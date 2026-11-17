"""B7 over HTTP: M10 emergency access behind the server flag (profile, break-glass, post-hoc review, the doctor's
capability). Synthetic data only; the reasons, facilities, allergens and contacts here are SYNTH placeholders.
"""
import json
import time
from datetime import date, datetime, timezone
from uuid import uuid4

import psycopg
import pytest

from swasthyoid.core import events_provenance
from swasthyoid.tests.test_api_b2 import cast  # noqa: F401
from swasthyoid.tests.test_api_m1 import V1, api, people  # noqa: F401

REASON, FACILITY = "SYNTH-REASON unconscious on arrival", "Synthetic General Hospital"
CONTACT = {"name": "Synthetic Contact", "phone": "+8801711000009"}
PROFILE = f"{V1}/me/emergency-profile"
REVIEWS = f"{V1}/admin/emergency/reviews"


def doctor_id(api):
    return api.conn.execute("SELECT id FROM users WHERE role = 'doctor'").fetchone()[0]


@pytest.fixture
def m10(api, cast, monkeypatch):  # noqa: F811
    monkeypatch.setenv("EMERGENCY_ACCESS_ENABLED", "1")
    monkeypatch.delenv("EMERGENCY_SESSION_MINUTES", raising=False)
    cast.doctor_id = doctor_id(api)
    return cast


def capable(api, b, value=True):
    r = api.http.post(f"{V1}/admin/users/{b.doctor_id}/emergency", headers=b.admin, json={"enabled": value})
    assert r.status_code == 200, r.text


def access(api, b, **over):
    return api.http.post(f"{V1}/emergency/access", headers=b.doctor,
                         json={"health_id": b.health_id, "reason": REASON, "facility": FACILITY, **over})


def allergy(api, b, text, status="document_verified"):
    doc = uuid4()
    api.conn.execute("INSERT INTO documents (id, patient_id, doc_type, status, uploaded_by) VALUES (%s, %s, 'prescription', "
                     "'verified', %s)", [doc, b.patient_id, b.patient_id])
    verified = status == "document_verified"
    events_provenance.append(api.conn, patient_id=b.patient_id, event_type="allergy", event_date=date(2026, 11, 1),
                             date_precision="day", actor_id=b.patient_id, actor_role="patient", source_type="document",
                             verification_status=status, payload={"allergy_text": text}, source_document_id=doc,
                             verified_by=b.patient_id if verified else None,
                             verified_at=datetime.now(timezone.utc) if verified else None)


def close_soon(monkeypatch):
    monkeypatch.setenv("EMERGENCY_SESSION_MINUTES", "0.002")  # about 120 ms, so the test can see a closed session


# ---- the server flag

def test_every_m10_route_is_refused_while_the_flag_is_off(api, cast, monkeypatch):  # noqa: F811
    monkeypatch.delenv("EMERGENCY_ACCESS_ENABLED", raising=False)
    api.conn.execute("UPDATE users SET emergency_enabled = true WHERE role = 'doctor'")  # capable, yet still refused
    calls = [(cast.patient, "GET", PROFILE, None), (cast.patient, "PUT", PROFILE, {"enabled": True}),
             (cast.doctor, "POST", f"{V1}/emergency/access", {"health_id": cast.health_id, "reason": REASON,
                                                              "facility": FACILITY}),
             (cast.reviewer, "GET", REVIEWS, None), (cast.reviewer, "POST", f"{REVIEWS}/{uuid4()}/review", {}),
             (cast.admin, "POST", f"{V1}/admin/users/{doctor_id(api)}/emergency", {"enabled": False})]
    for headers, method, url, body in calls:
        r = api.http.request(method, url, headers=headers, json=body)
        assert (r.status_code, r.json()["code"]) == (403, "emergency_not_enabled"), url
    logged = api.conn.execute("SELECT count(*) FROM audit_logs WHERE result = 'deny' AND reason = 'emergency_not_enabled'")
    assert logged.fetchone()[0] == len(calls)
    assert api.conn.execute("SELECT count(*) FROM emergency_sessions").fetchone()[0] == 0
    assert api.conn.execute("SELECT count(*) FROM notifications WHERE template_id = 'EMERGENCY_ACCESS_PLACEHOLDER'"
                            ).fetchone()[0] == 0


# ---- the patient's profile

def test_the_profile_is_the_patients_own_and_off_until_turned_on(api, m10):
    allergy(api, m10, "SYNTH-ALLERGEN-01")
    allergy(api, m10, "SYNTH-ALLERGEN-SAID", status="patient_reported")  # never on the card
    p = api.http.get(PROFILE, headers=m10.patient).json()
    assert (p["enabled"], p["fields"], p["contacts"]) == (False, [], [])
    assert p["available"] == {"blood_group": None, "allergies": ["SYNTH-ALLERGEN-01"], "active_medications": [],
                              "conditions": []}  # REVIEWER-PENDING: only allergies come from events
    for headers in (m10.doctor, m10.verifier, m10.reviewer, m10.admin):
        r = api.http.get(PROFILE, headers=headers)
        assert (r.status_code, r.json()["code"]) == (403, "role_not_allowed")

    for body, code in (({"enabled": True, "contacts": [{"name": "X", "phone": "12345"}]}, "invalid_contact"),
                       ({"enabled": True, "contacts": [{"name": " ", "phone": CONTACT["phone"]}]}, "invalid_contact"),
                       ({"enabled": True, "fields": ["horoscope"]}, "invalid_profile"),
                       ({"enabled": True, "fields": ["allergies", "allergies"]}, "invalid_profile"),
                       ({"fields": ["allergies"]}, "invalid_profile")):
        r = api.http.put(PROFILE, headers=m10.patient, json=body)
        assert (r.status_code, r.json()["code"]) == (422, code), body
    saved = api.http.put(PROFILE, headers=m10.patient,
                         json={"enabled": True, "fields": ["allergies", "emergency_contacts"], "contacts": [CONTACT]}).json()
    assert (saved["enabled"], saved["fields"], saved["contacts"]) == (True, ["allergies", "emergency_contacts"], [CONTACT])
    sealed = api.conn.execute("SELECT contacts_enc FROM emergency_profiles").fetchone()[0]
    assert CONTACT["phone"] not in sealed and CONTACT["name"] not in sealed
    assert api.conn.execute("SELECT count(*) FROM audit_logs WHERE action = 'emergency.profile.update'").fetchone()[0] == 1


# ---- break-glass

def test_break_glass_needs_capability_reason_facility_and_a_known_patient(api, m10):
    r = access(api, m10)
    assert (r.status_code, r.json()["code"]) == (403, "emergency_not_enabled")  # capability off by default
    capable(api, m10)
    for over, status, code in (({"reason": " "}, 422, "reason_required"), ({"facility": ""}, 422, "reason_required"),
                               ({"reason": None}, 422, "reason_required"),
                               ({"health_id": "SID-0000000000"}, 404, "patient_not_found")):
        r = access(api, m10, **over)
        assert (r.status_code, r.json()["code"]) == (status, code), over
    for headers in (m10.patient, m10.verifier, m10.reviewer, m10.admin):
        r = api.http.post(f"{V1}/emergency/access", headers=headers,
                          json={"health_id": m10.health_id, "reason": REASON, "facility": FACILITY})
        assert (r.status_code, r.json()["code"]) == (403, "role_not_allowed")
    denied = api.conn.execute("SELECT count(*) FROM audit_logs WHERE action = 'emergency.access' AND result = 'deny'")
    assert denied.fetchone()[0] == 5  # every refusal of a doctor is audited
    assert api.conn.execute("SELECT count(*) FROM emergency_sessions").fetchone()[0] == 0


def test_a_session_shows_the_card_notifies_the_patient_and_audits_first(api, m10):
    capable(api, m10)
    r = access(api, m10)  # the profile is off: a session and a notice, but no card
    assert r.status_code == 201, r.text
    assert r.json()["card"] is None and r.json()["session_id"]
    span = datetime.fromisoformat(r.json()["expires_at"]) - api.conn.execute("SELECT started_at FROM emergency_sessions"
                                                                             ).fetchone()[0]
    assert span.total_seconds() == 120 * 60  # FRD default, 2 hours

    allergy(api, m10, "SYNTH-ALLERGEN-01")
    api.http.put(PROFILE, headers=m10.patient, json={"enabled": True, "contacts": [CONTACT],
                                                     "fields": ["allergies", "emergency_contacts", "blood_group"]})
    card = access(api, m10, facility="Synthetic Clinic").json()["card"]
    assert card == {"allergies": ["SYNTH-ALLERGEN-01"], "emergency_contacts": [CONTACT]}  # no blood group: none verified
    shown = [r[0] for r in api.conn.execute("SELECT fields_shown FROM emergency_sessions ORDER BY started_at")]
    assert shown == [[], ["allergies", "emergency_contacts"]]

    allowed = api.conn.execute("SELECT reason, patient_id FROM audit_logs WHERE action = 'emergency.access' "
                               "AND result = 'allow'").fetchall()
    assert allowed == [("reason_given", m10.patient_id)] * 2
    assert REASON not in json.dumps([list(map(str, r)) for r in api.conn.execute("SELECT * FROM audit_logs")])

    notes = api.http.get(f"{V1}/notifications", headers=m10.patient).json()
    emergency = [n for n in notes if n["kind"] == "emergency_access"]
    assert [(n["facility"], n["actor_name"]) for n in emergency] == [("Synthetic Clinic", "Synthetic Doctor"),
                                                                     (FACILITY, "Synthetic Doctor")]
    assert REASON not in json.dumps(notes)


def test_a_bad_session_length_refuses_to_open(api, m10, monkeypatch):
    capable(api, m10)
    for value in ("abc", "0", "-5", "nan"):
        monkeypatch.setenv("EMERGENCY_SESSION_MINUTES", value)
        r = access(api, m10)
        assert (r.status_code, r.json()["code"]) == (503, "not_configured")
    assert api.conn.execute("SELECT count(*) FROM emergency_sessions").fetchone()[0] == 0


# ---- post-hoc review and capability

def test_a_closed_session_is_reviewed_and_unjustified_suspends_the_capability(api, m10, monkeypatch):
    capable(api, m10)
    close_soon(monkeypatch)
    session = access(api, m10).json()["session_id"]
    assert api.http.get(REVIEWS, headers=m10.reviewer).json() == []  # still open: not in the queue yet
    review = f"{REVIEWS}/{session}/review"
    assert api.http.post(review, headers=m10.reviewer, json={"decision": "justified"}).status_code == 404
    time.sleep(0.3)

    item = api.http.get(REVIEWS, headers=m10.reviewer).json()[0]
    assert (item["id"], item["status"], item["doctor_name"], item["reason"], item["facility"]) == (
        session, "review_pending", "Synthetic Doctor", REASON, FACILITY)
    assert (item["fields_shown"], item["capability_suspended"], item["note"]) == ([], False, None)
    for headers in (m10.patient, m10.doctor, m10.verifier, m10.admin):
        for method, url in (("GET", REVIEWS), ("POST", review)):
            r = api.http.request(method, url, headers=headers, json={"decision": "justified"})
            assert (r.status_code, r.json()["code"]) == (403, "role_not_allowed")

    for body, code in (({"decision": "maybe"}, "invalid_decision"), ({"decision": "unjustified"}, "reason_required"),
                       ({"decision": "unjustified", "note": "  "}, "reason_required")):
        r = api.http.post(review, headers=m10.reviewer, json=body)
        assert (r.status_code, r.json()["code"]) == (422, code)
    done = api.http.post(review, headers=m10.reviewer, json={"decision": "unjustified", "note": "SYNTH no emergency"}).json()
    assert (done["status"], done["capability_suspended"], done["note"]) == ("unjustified", True, "SYNTH no emergency")
    assert api.http.post(review, headers=m10.reviewer, json={"decision": "justified"}).json()["code"] == "not_pending"
    logged = api.conn.execute("SELECT reason FROM audit_logs WHERE action = 'emergency.review.unjustified'").fetchall()
    assert logged == [("reason_given",)]

    assert access(api, m10).json()["code"] == "emergency_not_enabled"  # capability off after an unjustified access
    capable(api, m10)  # an admin restores it
    assert access(api, m10).status_code == 201


def test_only_an_admin_switches_a_verified_doctors_capability(api, m10):
    url = f"{V1}/admin/users/{m10.doctor_id}/emergency"
    for headers in (m10.patient, m10.doctor, m10.verifier, m10.reviewer):
        r = api.http.post(url, headers=headers, json={"enabled": True})
        assert (r.status_code, r.json()["code"]) == (403, "role_not_allowed")
    assert api.http.post(url, headers=m10.admin, json={"enabled": "yes"}).json()["code"] == "invalid_request"
    verifier = api.conn.execute("SELECT id FROM users WHERE role = 'verifier'").fetchone()[0]
    assert api.http.post(f"{V1}/admin/users/{verifier}/emergency", headers=m10.admin,
                         json={"enabled": True}).status_code == 404
    assert api.http.post(url, headers=m10.admin, json={"enabled": True}).json() == {
        "user_id": str(m10.doctor_id), "emergency_enabled": True}
    assert api.http.get(f"{V1}/me", headers=m10.doctor).json()["emergency_enabled"] is True
    assert [r[0] for r in api.conn.execute("SELECT action FROM audit_logs WHERE action LIKE 'user.emergency.%'")] == [
        "user.emergency.enable"]


@pytest.mark.parametrize("sql", [
    "UPDATE emergency_sessions SET reason = 'changed'",
    "UPDATE emergency_sessions SET fields_shown = ARRAY['allergies']",
    "UPDATE emergency_sessions SET review_status = 'justified', reviewed_by = (SELECT id FROM users WHERE role = "
    "'clinical_reviewer'), reviewed_at = now()",  # still open: no review yet
    "DELETE FROM emergency_sessions",
    "TRUNCATE emergency_sessions",
])
def test_the_database_guards_sessions(api, m10, sql):
    capable(api, m10)
    assert access(api, m10).status_code == 201
    with pytest.raises(psycopg.Error):
        api.conn.execute(sql)


def test_the_database_wants_a_note_for_unjustified(api, m10, monkeypatch):
    capable(api, m10)
    close_soon(monkeypatch)
    access(api, m10)
    time.sleep(0.3)
    with pytest.raises(psycopg.errors.CheckViolation):
        api.conn.execute("UPDATE emergency_sessions SET review_status = 'unjustified', reviewed_at = now(), "
                         "reviewed_by = (SELECT id FROM users WHERE role = 'clinical_reviewer')")
