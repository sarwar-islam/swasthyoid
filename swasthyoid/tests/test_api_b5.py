"""B5 over HTTP: the M6 rule registry (versions, four-eyes, immutability), the admin's audit view, and the drug catalog
upload that validates and reports only. Synthetic data only; every rule here is a SYNTH placeholder, not a clinical rule.
"""
import json
import re

import psycopg
import pytest

from swasthyoid.core import audit
from swasthyoid.tests.test_api_b2 import cast  # noqa: F401
from swasthyoid.tests.test_api_m1 import V1, api, login, people  # noqa: F401

REVIEWER2 = "+8801900000015"
# P3 (D5): the strict schema-1 shape; the names are made up
DDI = {"rule_type": "ddi", "severity": "major", "definition": {"schema": 1, "ingredients": ["synthgen-alpha", "synthgen-beta"]},
       "explanation": {"en": "SYNTH explanation", "bn": "সিনথেটিক ব্যাখ্যা"}}


@pytest.fixture
def b5(api, cast):  # noqa: F811
    r = api.http.post(f"{V1}/admin/staff", headers=cast.admin,
                      json={"role": "clinical_reviewer", "name": "Synthetic Reviewer 2", "phone": REVIEWER2})
    assert r.status_code == 201, r.text
    cast.reviewer2 = login(api, REVIEWER2, account="staff")
    return cast


def draft(api, headers, body=DDI):
    return api.http.post(f"{V1}/rules", headers=headers, json=body)


# ---- rule registry

def test_the_registry_starts_empty_and_only_reviewers_use_it(api, b5):
    assert api.http.get(f"{V1}/rules", headers=b5.reviewer).json() == []  # nothing is seeded
    for headers in (b5.admin, b5.doctor, b5.patient, b5.verifier):
        for method, path, body in (("GET", "/rules", None), ("POST", "/rules", DDI)):
            r = api.http.request(method, f"{V1}{path}", headers=headers, json=body)
            assert (r.status_code, r.json()["code"]) == (403, "role_not_allowed")


@pytest.mark.parametrize("body,code", [
    ({**DDI, "rule_type": "horoscope"}, "invalid_rule"),
    ({**DDI, "severity": "catastrophic"}, "invalid_rule"),
    ({**DDI, "definition": {}}, "invalid_rule"),
    ({**DDI, "explanation": {"en": "x", "bn": " "}}, "invalid_rule"),
    ({**DDI, "rule_type": "vital_threshold", "severity": None, "definition": {"vital_type": "bp", "unit": "mg/dL"}},
     "invalid_vital_threshold"),
    ({**DDI, "rule_type": "vital_threshold", "severity": None, "definition": {"vital_type": "temperature", "unit": "C"}},
     "invalid_vital_threshold"),
])
def test_a_draft_is_checked_for_shape_only(api, b5, body, code):
    r = draft(api, b5.reviewer, body)
    assert (r.status_code, r.json()["code"]) == (422, code)


def test_versions_four_eyes_and_one_approved_version(api, b5):
    vt = {**DDI, "rule_type": "vital_threshold", "severity": None,
          "definition": {"schema": 1, "vital_type": "glucose", "unit": "mmol/L", "contexts": ["fasting"],
                         "comparison": "at_or_above", "level": "flagged"}}
    assert draft(api, b5.reviewer, vt).status_code == 201  # the P6 strict shape (V3); no number in it
    v1 = draft(api, b5.reviewer).json()
    assert (v1["version"], v1["status"], v1["created_by_name"]) == (1, "draft", "Synthetic clinical_reviewer")
    assert re.fullmatch(r"RULE-[0-9A-F]{8}", v1["rule_id"])
    again = draft(api, b5.reviewer2, {**DDI, "rule_id": v1["rule_id"]})
    assert (again.status_code, again.json()["code"]) == (409, "draft_exists")  # one open draft per rule

    own = api.http.post(f"{V1}/rules/{v1['id']}/approve", headers=b5.reviewer)
    assert (own.status_code, own.json()["code"]) == (409, "four_eyes")
    ok = api.http.post(f"{V1}/rules/{v1['id']}/approve", headers=b5.reviewer2).json()
    assert (ok["status"], ok["reviewed_by_name"]) == ("approved", "Synthetic Reviewer 2")
    assert api.http.post(f"{V1}/rules/{v1['id']}/approve", headers=b5.reviewer2).json()["code"] == "not_draft"

    v2 = draft(api, b5.reviewer2, {**DDI, "rule_id": v1["rule_id"], "severity": "moderate"}).json()
    assert v2["version"] == 2
    allergy = {"schema": 1, "allergen_terms": ["SYNTH-ALLERGEN"], "ingredients": ["synthgen-alpha"]}
    assert draft(api, b5.reviewer, {**DDI, "rule_id": v1["rule_id"], "rule_type": "allergy",
                                    "definition": allergy}).json()["code"] == "invalid_rule"  # a version keeps its type
    assert api.http.post(f"{V1}/rules/{v2['id']}/approve", headers=b5.reviewer).json()["status"] == "approved"
    versions = {r["version"]: r["status"] for r in api.http.get(f"{V1}/rules?type=ddi", headers=b5.reviewer).json()}
    assert versions == {1: "superseded", 2: "approved"}  # exactly one version runs


def test_an_author_may_withdraw_their_own_draft_with_a_reason(api, b5):
    d = draft(api, b5.reviewer).json()
    r = api.http.post(f"{V1}/rules/{d['id']}/reject", headers=b5.reviewer, json={"reason": " "})
    assert (r.status_code, r.json()["code"]) == (422, "reason_required")
    r = api.http.post(f"{V1}/rules/{d['id']}/reject", headers=b5.reviewer, json={"reason": "SYNTH withdrawn by author"})
    assert (r.json()["status"], r.json()["reason"]) == ("rejected", "SYNTH withdrawn by author")
    logged = api.conn.execute("SELECT reason FROM audit_logs WHERE action = 'rule.reject'").fetchone()[0]
    assert logged == "reason_given"


@pytest.mark.parametrize("sql", [
    "UPDATE rules SET definition = '{\"changed\": true}'",
    "UPDATE rules SET explanation_en = 'changed'",
    "UPDATE rules SET status = 'draft'",
    "DELETE FROM rules",
    "TRUNCATE rules",
])
def test_an_approved_version_cannot_be_changed_or_removed(api, b5, sql):
    d = draft(api, b5.reviewer).json()
    api.http.post(f"{V1}/rules/{d['id']}/approve", headers=b5.reviewer2)
    with pytest.raises(psycopg.Error):
        api.conn.execute(sql)


def test_the_database_itself_refuses_self_approval(api, b5):
    d = draft(api, b5.reviewer).json()
    with pytest.raises(psycopg.errors.CheckViolation):
        api.conn.execute("UPDATE rules SET status = 'approved', reviewed_by = created_by WHERE id = %s", [d["id"]])


# ---- audit view

def test_the_audit_view_is_metadata_only_with_keyed_references(api, b5):
    audit.append(api.conn, action="synthetic.note", result="allow", reason="SYNTH free text, 12 words", actor_id=None)
    page = api.http.get(f"{V1}/audit", headers=b5.admin).json()
    assert page["chain"]["status"] == "intact" and page["chain"]["first_broken_id"] is None
    assert 0 < len(page["entries"]) <= 100
    keys = set().union(*(e.keys() for e in page["entries"]))
    assert not keys & {"ip", "user_agent", "device_id", "actor_id", "patient_id", "consent_id", "resource_id"}
    refs = [e[k] for e in page["entries"] for k in ("actor_ref", "patient_ref", "consent_ref") if e[k]]
    assert refs and all(re.fullmatch(r"[0-9a-f]{10}", ref) for ref in refs)
    raw_ids = {str(r[0]) for r in api.conn.execute("SELECT actor_id FROM audit_logs WHERE actor_id IS NOT NULL")}
    assert not raw_ids & set(refs) and not any(i[:10] in refs for i in raw_ids)  # keyed, not a truncated id
    note = next(e for e in page["entries"] if e["action"] == "synthetic.note")
    assert note["reason"] == "free_text_hidden"
    assert "SYNTH free text" not in json.dumps(page)
    assert api.conn.execute("SELECT count(*) FROM audit_logs WHERE action = 'audit.read'").fetchone()[0] == 1


def test_the_audit_view_filters_on_the_server(api, b5):
    only = api.http.get(f"{V1}/audit?action=auth.&result=allow&role=patient", headers=b5.admin).json()["entries"]
    assert only and all(e["action"].startswith("auth.") and e["result"] == "allow" and e["actor_role"] == "patient"
                        for e in only)


def test_a_broken_chain_is_reported_with_its_first_broken_entry(api, b5):
    victim = api.conn.execute("SELECT id FROM audit_logs ORDER BY seq LIMIT 1 OFFSET 2").fetchone()[0]
    api.conn.execute("ALTER TABLE audit_logs DISABLE TRIGGER audit_logs_no_change")  # the attack the chain detects
    api.conn.execute("UPDATE audit_logs SET reason = 'tampered' WHERE id = %s", [victim])
    api.conn.execute("ALTER TABLE audit_logs ENABLE TRIGGER audit_logs_no_change")
    chain = api.http.get(f"{V1}/audit", headers=b5.admin).json()["chain"]
    assert (chain["status"], chain["first_broken_id"]) == ("broken", str(victim))


def test_only_an_admin_reads_the_audit_log(api, b5):
    for headers in (b5.reviewer, b5.doctor, b5.patient, b5.verifier):
        assert api.http.get(f"{V1}/audit", headers=headers).status_code == 403


# ---- catalog upload: validate and report only

CSV = ("brand id,brand name,generic,strength,dosage form,manufacturer,price\n"
       "1,SYNTH Brand A,SYNTH-GENERIC-1,500 mg,Tablet,Synthetic Pharma,9\n"
       "2,SYNTH Brand A,SYNTH-GENERIC-1,500 mg,Tablet,Synthetic Pharma,9\n"
       "3,SYNTH Brand B,,,Syrup,Synthetic Pharma,3\n").encode()


def upload(api, headers, data=CSV, name="medicine.csv", source="SYNTH test fixture, no licence needed"):
    return api.http.post(f"{V1}/catalog/import", headers=headers, data={"source": source} if source is not None else {},
                         files={"file": (name, data, "text/csv")})


def test_a_catalog_upload_is_validated_and_reported_never_stored(api, b5):
    r = upload(api, b5.admin)
    assert r.status_code == 201, r.text
    body = r.json()
    assert (body["status"], body["size_bytes"], body["file_name"]) == ("validated", len(CSV), "medicine.csv")
    assert body["report"]["rows"] == 3 and body["report"]["duplicate_groups"] == 1
    row = api.conn.execute("SELECT sha256, size_bytes, source_statement, report FROM catalog_imports").fetchone()
    assert row[0] == body["sha256"] and row[1] == len(CSV) and row[2].startswith("SYNTH test fixture")
    assert "SYNTH Brand" not in json.dumps(row[3])  # counts only, no catalog data
    stored = json.dumps([list(map(str, r)) for r in api.conn.execute("SELECT * FROM catalog_imports").fetchall()])
    assert "SYNTH-GENERIC-1" not in stored


@pytest.mark.parametrize("kwargs,code", [
    ({"source": None}, "source_required"),
    ({"source": "  "}, "source_required"),
    ({"name": "medicine.txt"}, "invalid_file"),
    ({"data": b""}, "invalid_file"),
    ({"data": b"brand name,generic\nx,y\n"}, "invalid_catalog"),
    ({"name": "generic.csv"}, "invalid_catalog"),
    ({"data": b"\xff\xfe not utf8"}, "invalid_catalog"),
])
def test_a_bad_catalog_upload_is_refused_and_nothing_recorded(api, b5, kwargs, code):
    r = upload(api, b5.admin, **kwargs)
    assert (r.status_code, r.json()["code"]) == (422, code)
    assert api.conn.execute("SELECT count(*) FROM catalog_imports").fetchone()[0] == 0


def test_only_an_admin_uploads_a_catalog(api, b5):
    for headers in (b5.reviewer, b5.doctor, b5.patient):
        assert upload(api, headers).status_code == 403
