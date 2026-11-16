"""B4a over HTTP: M3 check, confirm and reject, and the M4 timeline. Synthetic data only.

Runs against a fresh database with the real schema (the `prod` fixture), so the document store, the sealed extraction
and the append-only tables are the real ones.
"""
import json

import pytest

from swasthyoid import pii
from swasthyoid.capture import extraction_crypto
from swasthyoid.identity import accounts
from swasthyoid.tests.test_extraction_integration import V1, patient, prod, upload  # noqa: F401
from swasthyoid.verification import review

RX = {"prescription_date": "১২/১১/২০২৬", "prescriber_name": "Dr. Synthetic Prescriber", "facility_name": "Synthetic Clinic",
      "diagnosis_text": "SYNTH diagnosis as written", "allergy_text": "SYNTH-ALLERGEN-01", "follow_up_date": "2026-12-01",
      "medications": [{"name_as_written": "SYNTH-DRUG-001 500 mg", "dose_instruction": "1+0+1"}, {"name_as_written": ""}]}


@pytest.fixture
def b(prod, monkeypatch):  # noqa: F811
    monkeypatch.setenv("TIMELINE_CONSENT_HOURS", "24")
    prod.patient = patient(prod)
    return prod


def in_review(b, headers=None):
    doc_id = upload(b, headers or b.patient)
    r = b.http.post(f"{V1}/documents/{doc_id}/manual-entry", headers=headers or b.patient)
    assert r.status_code == 200, r.text
    return doc_id


def put(b, doc_id, fields, headers=None):
    return b.http.put(f"{V1}/documents/{doc_id}/review", headers=headers or b.patient, json={"fields": fields})


def events(b, doc_id):
    with b.connect() as conn:
        return conn.execute("SELECT event_type, event_date::text, payload, verification_status, verified_by IS NOT NULL "
                            "FROM events WHERE source_document_id = %s ORDER BY event_type", [doc_id]).fetchall()


def staff(b, phone, role, name):
    """A verified doctor (approved credential) or an admin-created verifier, logged in."""
    with b.connect() as conn:
        admin = conn.execute("SELECT id FROM users WHERE role = 'admin'").fetchone()
        admin_id = admin[0] if admin else accounts.seed_admin(conn, phone="+8801900000001", name="Synthetic Admin")["id"]
        if role == "doctor":
            user = accounts.register_user(conn, phone=phone, role="doctor", name=name)
            cred = accounts.submit_credential(conn, user_id=user["id"], type="BMDC", number=f"SYNTH-{phone[-4:]}")
            accounts.approve_credential(conn, cred["id"], admin_id=admin_id)
        else:
            accounts.create_staff(conn, admin_id=admin_id, role=role, name=name, phone=phone)
    assert b.http.post(f"{V1}/auth/otp/request", json={"phone": phone}).status_code == 204
    r = b.http.post(f"{V1}/auth/otp/verify", json={"phone": phone, "code": b.codes[pii.normalize_phone(phone)],
                                                   "device_id": "dev-1", "account": "staff"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


# ---- M3

def test_check_then_confirm_writes_the_mapped_events_once(b):
    doc_id = in_review(b)
    r = put(b, doc_id, RX)
    assert r.status_code == 200, r.text
    saved = r.json()["fields"]
    assert saved["prescription_date"] == "2026-11-12"  # parsed like an extraction, Bangla digits accepted
    assert saved["medications"] == [{"name_as_written": "SYNTH-DRUG-001 500 mg", "strength": None, "form": None,
                                     "dose_instruction": "1+0+1", "duration": None}]  # the empty row is dropped
    with b.connect() as conn:
        stored = json.dumps(conn.execute("SELECT fields FROM document_reviews").fetchone()[0])
    assert "SYNTH-DRUG-001" not in stored and "Synthetic Prescriber" not in stored  # sealed

    r = b.http.post(f"{V1}/documents/{doc_id}/confirm", headers=b.patient)
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "verified"
    got = events(b, doc_id)
    assert [(e[0], e[1]) for e in got] == [("allergy", "2026-11-12"), ("follow_up", "2026-12-01"),
                                          ("medication", "2026-11-12"), ("prescription", "2026-11-12")]
    assert all(e[3] == "document_verified" and e[4] for e in got)
    assert {"prescriber_name": "Dr. Synthetic Prescriber", "facility_name": "Synthetic Clinic"} == got[3][2]
    assert "diagnosis" not in json.dumps([e[2] for e in got]).lower()  # D7 Q4: never an event

    # a repeat cannot write events twice
    again = b.http.post(f"{V1}/documents/{doc_id}/confirm", headers=b.patient)
    assert (again.status_code, again.json()["code"]) == (409, "not_allowed_state")
    assert len(events(b, doc_id)) == 4
    with b.connect() as conn:
        v = conn.execute("SELECT fields_total, fields_corrected, corrections, cardinality(event_ids), verifier_role "
                         "FROM verifications WHERE document_id = %s", [doc_id]).fetchone()
        reason = conn.execute("SELECT reason FROM audit_logs WHERE action = 'document.confirm'").fetchone()[0]
    assert v[1] > 0 and v[1] <= v[0] and v[3] == 4 and v[4] == "patient"
    assert extraction_crypto.is_sealed(v[2]) and "SYNTH" not in json.dumps(v[2])
    assert "SYNTH" not in reason  # counts only in the audit log


def test_confirm_needs_a_saved_check_and_the_documents_date(b):
    doc_id = in_review(b)
    r = b.http.post(f"{V1}/documents/{doc_id}/confirm", headers=b.patient)
    assert (r.status_code, r.json()["code"]) == (422, "review_required")
    put(b, doc_id, {**RX, "prescription_date": None})
    r = b.http.post(f"{V1}/documents/{doc_id}/confirm", headers=b.patient)
    assert (r.status_code, r.json()["code"], r.json()["details"]["field"]) == (422, "date_required", "prescription_date")
    assert events(b, doc_id) == []


@pytest.mark.parametrize("fields,code", [
    ({"made_up": "x"}, "unknown_field"),
    ({"prescription_date": "31/02/2026"}, "invalid_date"),
    ({"medications": [{"name_as_written": "x", "colour": "red"}]}, "unknown_field"),
    ({"prescriber_name": 7}, "invalid_field"),
    ("not an object", "invalid_fields"),
])
def test_a_check_with_unknown_or_unparseable_fields_is_refused(b, fields, code):
    doc_id = in_review(b)
    r = put(b, doc_id, fields)
    assert (r.status_code, r.json()["code"]) == (422, code)


def test_reject_writes_no_event_and_closes_the_document(b):
    doc_id = in_review(b)
    put(b, doc_id, RX)
    r = b.http.post(f"{V1}/documents/{doc_id}/reject", headers=b.patient)
    assert r.json()["status"] == "rejected" and events(b, doc_id) == []
    assert put(b, doc_id, RX).json()["code"] == "not_allowed_state"
    assert b.http.post(f"{V1}/documents/{doc_id}/confirm", headers=b.patient).status_code == 409


def test_lab_and_discharge_mapping_and_other_writes_nothing():
    lab = review.events_for("lab_report", {"report_date": "2026-11-01", "tests": [
        {"test_name": "SYNTH-TEST-A", "result": "5.9", "unit": "mg/dL", "reference_range": None}]})
    assert lab == [("lab_result", "2026-11-01", {"test_name": "SYNTH-TEST-A", "result": "5.9", "unit": "mg/dL"})]
    dis = review.events_for("discharge_summary", {"admission_date": "2026-10-01", "discharge_date": "2026-10-05",
                                                  "facility_name": "Synthetic Hospital", "diagnosis_text": "x",
                                                  "medications": [], "allergy_text": None, "follow_up_date": None})
    assert dis == [("visit", "2026-10-05", {"admission_date": "2026-10-01", "discharge_date": "2026-10-05",
                                            "facility_name": "Synthetic Hospital"})]
    assert review.events_for("other", {}) == []


def test_only_the_patient_checks_their_document(b):
    doc_id = in_review(b)
    stranger = patient(b, "+8801700000009")
    doctor = staff(b, "+8801900000002", "doctor", "Synthetic Doctor")
    for headers in (stranger,):
        assert put(b, doc_id, RX, headers).status_code == 404
        assert b.http.post(f"{V1}/documents/{doc_id}/confirm", headers=headers).status_code == 404
    for path in ("confirm", "reject"):
        r = b.http.post(f"{V1}/documents/{doc_id}/{path}", headers=doctor)
        assert (r.status_code, r.json()["code"]) == (403, "role_not_allowed")
    assert put(b, doc_id, RX, doctor).status_code == 403


# ---- M4 timeline

def confirmed(b):
    doc_id = in_review(b)
    put(b, doc_id, RX)
    assert b.http.post(f"{V1}/documents/{doc_id}/confirm", headers=b.patient).status_code == 200
    return doc_id


def test_timeline_for_the_patient_with_filters_and_never_pending(b):
    doc_id = confirmed(b)
    pid = b.http.get(f"{V1}/me", headers=b.patient).json()["id"]
    with b.connect() as conn:
        conn.execute("INSERT INTO events (id, patient_id, event_type, event_date, date_precision, actor_id, actor_role, "
                     "source_type, verification_status, version, payload) VALUES (gen_random_uuid(), %s, 'visit', "
                     "'2026-11-13', 'day', %s, 'patient', 'synthetic', 'pending', 1, '{}')", [pid, pid])
    items = b.http.get(f"{V1}/patients/{pid}/timeline", headers=b.patient).json()
    assert len(items) == 4 and all(i["verification_status"] == "document_verified" for i in items)
    assert all(i["source_document_id"] == doc_id for i in items)
    assert [i["date"] for i in items] == sorted(i["date"] for i in items)  # stable order by date
    only = b.http.get(f"{V1}/patients/{pid}/timeline?type=medication", headers=b.patient).json()
    assert [i["event_type"] for i in only] == ["medication"]
    window = b.http.get(f"{V1}/patients/{pid}/timeline?from=2026-11-20&to=2026-12-31", headers=b.patient).json()
    assert [i["event_type"] for i in window] == ["follow_up"]


def test_timeline_for_a_doctor_needs_a_timeline_consent_and_a_verifier_never(b):
    confirmed(b)
    pid = b.http.get(f"{V1}/me", headers=b.patient).json()["id"]
    health_id = b.http.get(f"{V1}/me", headers=b.patient).json()["health_id"]
    doctor = staff(b, "+8801900000002", "doctor", "Synthetic Doctor")
    r = b.http.get(f"{V1}/patients/{pid}/timeline", headers=doctor)
    assert (r.status_code, r.json()["code"]) == (403, "consent_required")
    req = b.http.post(f"{V1}/consents/requests", headers=doctor, json={"health_id": health_id, "categories": ["timeline"]}).json()
    b.http.post(f"{V1}/consents/requests/{req['id']}/confirm", headers=doctor, json={"code": b.codes["+8801700000001"]})
    assert len(b.http.get(f"{V1}/patients/{pid}/timeline", headers=doctor).json()) == 4
    verifier = staff(b, "+8801900000004", "verifier", "Synthetic Verifier")
    r = b.http.get(f"{V1}/patients/{pid}/timeline", headers=verifier)
    assert (r.status_code, r.json()["code"]) == (403, "role_not_allowed")
    with b.connect() as conn:
        reads = conn.execute("SELECT actor_role, result, reason FROM audit_logs WHERE action LIKE 'GET %%timeline' "
                             "ORDER BY seq").fetchall()
    assert reads == [("doctor", "deny", "consent_required"), ("doctor", "allow", None)]
