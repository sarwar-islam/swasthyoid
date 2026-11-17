"""Synthetic development seed (B8a; owner decision 3, 2026-11-17). SYNTHETIC DATA ONLY: no real person, clinic or drug.

    python -m swasthyoid.devtools.seed        (scripts/dev_api.ps1 -Seed sets the environment)

Runs only with APP_ENV=development, against the database in DATABASE_URL, and only into an empty one (a second run
changes nothing). Everything after the admin goes through the real HTTP routes in process, so the seed takes the same
path as a person would: RBAC, consent, audit, and for documents the actual M3 workflow (upload, manual entry, check,
confirm). The admin is created with identity.accounts.seed_admin, as in a deployment (never over HTTP).

Seeded: an admin, two clinical reviewers, a verifier, a verified doctor (emergency capability OFF), a patient and a second
person account for trying caregiver mode; two confirmed documents (a prescription and a lab report) and a third left in
review. No clinical rule is seeded (FRD Q7): alert and threshold screens show their empty states. One-time codes are
captured in memory here and never printed or stored.
"""
import os
import sys
from types import SimpleNamespace

from fastapi.testclient import TestClient

from swasthyoid import db
from swasthyoid.api import deps
from swasthyoid.api.main import app
from swasthyoid.identity import accounts

V1 = "/api/v1"
PHONES = SimpleNamespace(admin="+8801900000101", reviewer="+8801900000102", reviewer2="+8801900000103",
                         verifier="+8801900000104", doctor="+8801900000105", patient="+8801700000101",
                         caregiver="+8801700000102")
RX = {"prescription_date": "2026-11-02", "prescriber_name": "Dr. SYNTH Prescriber", "facility_name": "SYNTH Clinic",
      "allergy_text": "SYNTH-ALLERGEN-01", "follow_up_date": "2026-12-02", "advice_text": "SYNTH advice as written",
      "medications": [{"name_as_written": "SYNTH-DRUG-001 500 mg", "dose_instruction": "1+0+1"},
                      {"name_as_written": "SYNTH-DRUG-002 10 mg", "dose_instruction": "0+0+1"}]}
LAB = {"report_date": "2026-11-05", "lab_name": "SYNTH Laboratory",
       "tests": [{"test_name": "SYNTH-TEST-A", "result": "5.8", "unit": "SYNTH-UNIT", "reference_range": "SYNTH-RANGE"}]}


class Refused(Exception):
    pass


def _page():
    # shortcut: borrows the test suite's synthetic page renderer (it passes the upload quality checks); move it out of
    # tests/ if a non-test caller ever needs more than this seed.
    from swasthyoid.tests import images
    return images.JPEG


def run(out=print):
    """Seed an empty development database and return a summary, or None when it was already seeded."""
    if os.environ.get("APP_ENV") != "development":
        raise Refused("APP_ENV must be development")
    with db.connect(autocommit=True) as conn:
        db.apply_schema(conn)
        if conn.execute("SELECT (SELECT count(*) FROM users) + (SELECT count(*) FROM patients)").fetchone()[0]:
            out("seed: the database already has accounts; nothing changed")
            return None
        accounts.seed_admin(conn, phone=PHONES.admin, name="SYNTH Admin")

    codes = {}
    app.dependency_overrides[deps.get_code_sender] = lambda: (lambda phone, code, context=None: codes.__setitem__(phone, code))
    try:
        http = TestClient(app)

        def call(method, path, headers=None, ok=(200, 201, 202, 204), **kw):
            r = http.request(method, V1 + path, headers=headers, **kw)
            if r.status_code not in ok:
                raise RuntimeError(f"seed: {method} {path} answered {r.status_code}")
            return r.json() if r.content else None

        def login(phone, **extra):
            call("POST", "/auth/otp/request", json={"phone": phone})
            tokens = call("POST", "/auth/otp/verify", json={"phone": phone, "code": codes.pop(phone), "device_id": "seed",
                                                            **extra})
            return {"Authorization": f"Bearer {tokens['access_token']}"}

        admin = login(PHONES.admin, account="staff")
        for phone, role, name in ((PHONES.reviewer, "clinical_reviewer", "SYNTH Reviewer One"),
                                  (PHONES.reviewer2, "clinical_reviewer", "SYNTH Reviewer Two"),
                                  (PHONES.verifier, "verifier", "SYNTH Health Worker")):
            call("POST", "/admin/staff", admin, json={"role": role, "name": name, "phone": phone})
        doctor = login(PHONES.doctor, account="staff", staff={"role": "doctor", "name": "Dr. SYNTH Doctor"})
        credential = call("POST", "/credentials", doctor, json={"type": "BMDC", "number": "SYNTH-BMDC-0105"})
        call("POST", f"/credentials/{credential['id']}/approve", admin)
        patient = login(PHONES.patient, profile={"name": "SYNTH Patient One", "dob": "1958-03-14", "sex": "F"})
        login(PHONES.caregiver, profile={"name": "SYNTH Caregiver", "dob": "1985-07-01", "sex": "M"})

        def document(doc_type, fields=None):
            doc = call("POST", "/documents", patient, data={"doc_type": doc_type},
                       files=[("images", ("page.jpg", _page(), "image/jpeg"))])
            call("POST", f"/documents/{doc['id']}/manual-entry", patient)
            if fields is not None:
                call("PUT", f"/documents/{doc['id']}/review", patient, json={"fields": fields})
                call("POST", f"/documents/{doc['id']}/confirm", patient)
            return doc["id"]

        confirmed = [document("prescription", RX), document("lab_report", LAB)]
        waiting = document("prescription")  # left in review, for the patient or a verifier to check by hand
        me = call("GET", "/me", patient)
    finally:
        app.dependency_overrides.pop(deps.get_code_sender, None)

    summary = {"health_id": me["health_id"], "phones": vars(PHONES), "confirmed_documents": confirmed,
               "document_in_review": waiting}
    out("seed: synthetic accounts created (log in with these phones; codes appear in the API log with DEV_LOG_CODES=1)")
    for role, phone in vars(PHONES).items():
        out(f"  {role:10} {phone}")
    out(f"  patient Health ID {me['health_id']}; 2 documents confirmed, 1 waiting in review; no rules seeded")
    return summary


if __name__ == "__main__":
    try:
        run()
    except Refused as e:
        print(f"seed: refused: {e}", file=sys.stderr)
        sys.exit(2)
