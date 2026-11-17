"""B6 over HTTP: M6 safety alerts (list, acknowledge, override) and M13 per-patient threshold overrides.

Synthetic data only. No M6 engine exists, so the alerts here are inserted directly from SYNTH rules approved through the
B5 registry; none of them is a clinical rule. Patients never see raw alerts (invariant 6).
"""
from uuid import uuid4

import psycopg
import pytest

from swasthyoid.tests.test_api_b2 import cast  # noqa: F401
from swasthyoid.tests.test_api_b5 import DDI, b5, draft  # noqa: F401
from swasthyoid.tests.test_api_m1 import PATIENT, V1, api, people, request_consent  # noqa: F401

VT_GLUCOSE = {"schema": 1, "vital_type": "glucose", "unit": "mmol/L", "contexts": ["fasting"],  # P6 strict shape (V3)
              "comparison": "at_or_above", "level": "flagged"}
VT_BP = {"schema": 1, "vital_type": "bp", "unit": "mmHg", "component": "systolic", "contexts": ["home"],
         "comparison": "at_or_above", "level": "critical"}
VT = {**DDI, "rule_type": "vital_threshold", "severity": None, "definition": VT_GLUCOSE,
      "explanation": {"en": "SYNTH threshold label", "bn": "সিনথেটিক সীমা"}}
ALERTS, THRESHOLDS = "/safety-alerts", "/vital-thresholds"


def approved(api, b, body=DDI):
    d = draft(api, b.reviewer, body).json()
    r = api.http.post(f"{V1}/rules/{d['id']}/approve", headers=b.reviewer2)
    assert r.status_code == 200, r.text
    return r.json()


def consent(api, b, categories=("timeline", "safety")):
    r = request_consent(api, b, categories=list(categories))
    assert r.status_code == 201, r.text
    ok = api.http.post(f"{V1}/consents/requests/{r.json()['id']}/confirm", headers=b.doctor, json={"code": api.codes[PATIENT]})
    assert ok.status_code == 200, ok.text


def synth_alert(api, b, version_id, severity="major"):
    doc = uuid4()
    api.conn.execute("INSERT INTO documents (id, patient_id, doc_type, status, uploaded_by) VALUES (%s, %s, 'prescription', "
                     "'verified', %s)", [doc, b.patient_id, b.patient_id])
    alert = uuid4()
    api.conn.execute("INSERT INTO safety_alerts (id, patient_id, rule_version_id, severity, source_document_id, "
                     "evidence_event_ids) VALUES (%s, %s, %s, %s, %s, %s)", [alert, b.patient_id, version_id, severity, doc,
                                                                            [uuid4(), uuid4()]])
    return str(alert)


def path(b, tail):
    return f"{V1}/patients/{b.patient_id}{tail}"


# ---- who may read

@pytest.mark.parametrize("tail", [ALERTS, THRESHOLDS])
def test_only_a_doctor_with_a_safety_consent_reads(api, b5, tail):
    for headers in (b5.patient, b5.verifier, b5.reviewer, b5.admin):  # the patient too: invariant 6
        r = api.http.get(path(b5, tail), headers=headers)
        assert (r.status_code, r.json()["code"]) == (403, "role_not_allowed"), r.text
    assert api.http.get(path(b5, tail), headers=b5.doctor).status_code == 403  # no consent yet
    consent(api, b5, ("timeline",))
    assert api.http.get(path(b5, tail), headers=b5.doctor).status_code == 403  # a consent without `safety`


@pytest.mark.parametrize("tail", [ALERTS, THRESHOLDS])
def test_a_safety_consent_opens_the_read_and_it_is_audited(api, b5, tail):
    consent(api, b5)
    assert api.http.get(path(b5, tail), headers=b5.doctor).status_code == 200
    seen = api.conn.execute("SELECT result FROM audit_logs WHERE action = %s",
                            [f"GET /patients/{{patient_id}}{tail}"]).fetchall()
    assert ("allow",) in seen


# ---- alerts

def test_alerts_list_ack_and_override(api, b5):
    consent(api, b5)
    assert api.http.get(path(b5, ALERTS), headers=b5.doctor).json() == []  # nothing creates alerts yet
    v1 = approved(api, b5)
    first, second = synth_alert(api, b5, v1["id"]), synth_alert(api, b5, v1["id"], "moderate")
    approved(api, b5, {**DDI, "rule_id": v1["rule_id"], "explanation": {"en": "SYNTH v2 text", "bn": "সিনথেটিক ২"}})

    listed = {a["id"]: a for a in api.http.get(path(b5, ALERTS), headers=b5.doctor).json()}
    assert set(listed) == {first, second}
    a = listed[first]
    assert (a["rule_id"], a["severity"], a["status"], a["reason"]) == (v1["rule_id"], "major", "open", None)
    assert a["explanation"] == {"en": "SYNTH explanation", "bn": "সিনথেটিক ব্যাখ্যা", "status": "approved"}  # the version that fired
    assert len(a["evidence_event_ids"]) == 2 and a["source_document_id"]

    ack = f"{V1}/safety/alerts/{first}/ack"
    for body, code in (({"action": "override"}, "reason_required"), ({"action": "override", "reason": "  "}, "reason_required"),
                       ({"action": "dismiss"}, "invalid_action"), (None, "invalid_action")):
        r = api.http.post(ack, headers=b5.doctor, json=body)
        assert (r.status_code, r.json()["code"]) == (422, code)
    r = api.http.post(ack, headers=b5.doctor, json={"action": "acknowledge"})
    assert (r.status_code, r.json()["status"], r.json()["reason"]) == (200, "acknowledged", None)
    r = api.http.post(ack, headers=b5.doctor, json={"action": "override", "reason": "SYNTH"})
    assert (r.status_code, r.json()["code"]) == (409, "not_open")

    r = api.http.post(f"{V1}/safety/alerts/{second}/ack", headers=b5.doctor,
                      json={"action": "override", "reason": " SYNTH reason, free text "})
    assert (r.json()["status"], r.json()["reason"]) == ("overridden", "SYNTH reason, free text")
    logged = api.conn.execute("SELECT action, reason FROM audit_logs WHERE action LIKE 'safety.alert.%' ORDER BY seq").fetchall()
    assert logged == [("safety.alert.acknowledge", None), ("safety.alert.override", "reason_given")]

    assert api.http.post(f"{V1}/safety/alerts/{uuid4()}/ack", headers=b5.doctor,
                         json={"action": "acknowledge"}).status_code == 404


def test_handling_an_alert_needs_the_doctor_role_and_the_consent(api, b5):
    alert = synth_alert(api, b5, approved(api, b5)["id"])
    ack = f"{V1}/safety/alerts/{alert}/ack"
    for headers in (b5.patient, b5.verifier, b5.reviewer, b5.admin):
        r = api.http.post(ack, headers=headers, json={"action": "acknowledge"})
        assert (r.status_code, r.json()["code"]) == (403, "role_not_allowed")
    assert api.http.post(ack, headers=b5.doctor, json={"action": "acknowledge"}).status_code == 403  # no consent
    assert api.conn.execute("SELECT status FROM safety_alerts").fetchone()[0] == "open"


@pytest.mark.parametrize("sql", [
    "UPDATE safety_alerts SET severity = 'minor'",
    "UPDATE safety_alerts SET evidence_event_ids = ARRAY[gen_random_uuid()]",
    "UPDATE safety_alerts SET status = 'overridden', handled_by = (SELECT id FROM users WHERE role = 'doctor'), "
    "handled_at = now()",  # an override without a reason
    "DELETE FROM safety_alerts",
    "TRUNCATE safety_alerts",
])
def test_the_database_guards_alerts(api, b5, sql):
    synth_alert(api, b5, approved(api, b5)["id"])
    with pytest.raises(psycopg.Error):
        api.conn.execute(sql)


def test_a_handled_alert_never_reopens_and_only_approved_rules_fire(api, b5):
    synth_alert(api, b5, approved(api, b5)["id"])
    doctor = api.conn.execute("SELECT id FROM users WHERE role = 'doctor'").fetchone()[0]
    api.conn.execute("UPDATE safety_alerts SET status = 'acknowledged', handled_by = %s, handled_at = now()", [doctor])
    with pytest.raises(psycopg.Error):
        api.conn.execute("UPDATE safety_alerts SET status = 'open', handled_by = NULL, handled_at = NULL")
    pending = draft(api, b5.reviewer).json()
    with pytest.raises(psycopg.Error):
        synth_alert(api, b5, pending["id"])


# ---- thresholds

def test_threshold_fields_come_from_approved_rules_with_null_defaults(api, b5):
    consent(api, b5)
    empty = api.http.get(path(b5, THRESHOLDS), headers=b5.doctor).json()
    assert (empty["version"], empty["fields"], empty["updated_at"], empty["updated_by_name"]) == (0, [], None, None)
    rule = approved(api, b5, VT)
    draft(api, b5.reviewer, {**VT, "definition": VT_BP})  # a draft gives no field
    fields = api.http.get(path(b5, THRESHOLDS), headers=b5.doctor).json()["fields"]
    assert fields == [{"key": rule["rule_id"], "vital_type": "glucose", "unit": "mmol/L", "default_value": None,
                       "override_value": None,
                       "label": {"en": "SYNTH threshold label", "bn": "সিনথেটিক সীমা", "status": "approved"}}]


def test_threshold_overrides_are_versioned_checked_and_audited(api, b5):
    consent(api, b5)
    key = approved(api, b5, VT)["rule_id"]
    put = lambda body: api.http.put(path(b5, THRESHOLDS), headers=b5.doctor, json=body)  # noqa: E731
    r = put({"version": 0, "overrides": {key: 7.5}})
    assert r.status_code == 200, r.text
    assert (r.json()["version"], r.json()["fields"][0]["override_value"], r.json()["updated_by_name"]) == (1, 7.5, "Synthetic Doctor")
    assert (put({"version": 0, "overrides": {key: 8}}).json()["code"]) == "version_conflict"
    for bad in ({"version": 1, "overrides": {"RULE-UNKNOWN0": 1}}, {"version": 1, "overrides": {key: 0}},
                {"version": 1, "overrides": {key: -2}}, {"version": 1, "overrides": {key: "7"}},
                {"version": 1, "overrides": {key: True}}, {"version": "1", "overrides": {}}, {"version": 1}):
        r = put(bad)
        assert (r.status_code, r.json()["code"]) == (422, "invalid_threshold"), bad
    cleared = put({"version": 1, "overrides": {key: None}}).json()
    assert (cleared["version"], cleared["fields"][0]["override_value"]) == (2, None)
    assert api.conn.execute("SELECT count(*) FROM audit_logs WHERE action = 'vital_thresholds.update'").fetchone()[0] == 2
    assert [r[0] for r in api.conn.execute("SELECT version FROM patient_thresholds ORDER BY version")] == [1, 2]
    for sql in ("UPDATE patient_thresholds SET overrides = '{}'", "DELETE FROM patient_thresholds", "TRUNCATE patient_thresholds"):
        with pytest.raises(psycopg.Error):
            api.conn.execute(sql)


def test_only_a_doctor_with_a_safety_consent_changes_thresholds(api, b5):
    key = approved(api, b5, VT)["rule_id"]
    body = {"version": 0, "overrides": {key: 7}}
    for headers in (b5.patient, b5.verifier, b5.reviewer, b5.admin):
        r = api.http.put(path(b5, THRESHOLDS), headers=headers, json=body)
        assert (r.status_code, r.json()["code"]) == (403, "role_not_allowed")
    assert api.http.put(path(b5, THRESHOLDS), headers=b5.doctor, json=body).status_code == 403
    assert api.conn.execute("SELECT count(*) FROM patient_thresholds").fetchone()[0] == 0
