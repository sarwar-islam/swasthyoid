"""P6 over HTTP: M13 home vitals (FRD M13; owner decisions V1-V6 and safeguards 1-7, 2026-11-17).

SYNTHETIC rules and values only: every rule below is made up to exercise the machinery and is not a clinical threshold,
plausibility limit or message (Q7, Q13 REVIEWER-PENDING). No result here is clinical validation.
"""
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import psycopg
import pytest

from swasthyoid.core import notification
from swasthyoid.tests.test_api_b2 import cast  # noqa: F401
from swasthyoid.tests.test_api_b5 import DDI, b5, draft  # noqa: F401
from swasthyoid.tests.test_api_b6 import THRESHOLDS, VT, VT_BP, VT_GLUCOSE, approved, consent, path
from swasthyoid.tests.test_api_m1 import V1, api, login, people  # noqa: F401
from swasthyoid.vitals import readings

NOW = datetime.now(timezone.utc).replace(microsecond=0)
OTHER = "+8801700000077"


def bp(value="128/82", context="home", **extra):
    return {"id": str(uuid4()), "vital_type": "bp", "value": value, "unit": "mmHg", "context": context,
            "measured_at": (NOW - timedelta(hours=1)).isoformat(), **extra}


def glucose(value="6.1", unit="mmol/L", context="fasting", **extra):
    return {**bp(), "vital_type": "glucose", "value": value, "unit": unit, "context": context, **extra}


def post(api, headers, body, of=None):
    return api.http.post(f"{V1}/vitals/{of}/correct" if of else f"{V1}/vitals", headers=headers, json=body)


def count(api, sql, *args):
    return api.conn.execute(sql, args).fetchone()[0]


def rule(api, b, definition, en="SYNTH approved message", bn="সিনথেটিক অনুমোদিত বার্তা", rule_type="vital_threshold"):
    return approved(api, b, {**VT, "rule_type": rule_type, "definition": definition, "explanation": {"en": en, "bn": bn}})


def thresholds(api, b, values):
    """The treating doctor's per-patient values (B6), under a consent covering safety. SYNTHETIC numbers."""
    consent(api, b)
    version = api.http.get(path(b, THRESHOLDS), headers=b.doctor).json()["version"]
    r = api.http.put(path(b, THRESHOLDS), headers=b.doctor, json={"version": version, "overrides": values})
    assert r.status_code == 200, r.text


@pytest.fixture
def other(api, people):  # noqa: F811
    return login(api, OTHER, profile={"name": "Synthetic Patient 2", "dob": "1991-02-02", "sex": "M"})


# ---- who

def test_only_the_patient_uses_vitals(api, b5):
    for headers in (b5.doctor, b5.verifier, b5.reviewer, b5.admin):
        for method, url, body in (("POST", "/vitals", bp()), ("GET", "/vitals", None),
                                  ("POST", f"/vitals/{uuid4()}/correct", {**bp(), "reason": "x"})):
            r = api.http.request(method, f"{V1}{url}", headers=headers, json=body)
            assert (r.status_code, r.json()["code"]) == (403, "role_not_allowed")
    assert api.http.get(f"{V1}/vitals").status_code == 401
    assert api.http.post(f"{V1}/vitals", json=bp()).status_code == 401
    assert count(api, "SELECT count(*) FROM events WHERE event_type = 'vital_reading'") == 0


# ---- saving and format checks

def test_a_reading_is_saved_as_written_and_patient_reported(api, b5):
    body = bp()
    r = post(api, b5.patient, body)
    assert r.status_code == 201, r.text
    saved = r.json()
    reading = saved["reading"]
    assert (reading["id"], reading["vital_type"], reading["value"], reading["unit"], reading["context"]) == \
        (body["id"], "bp", "128/82", "mmHg", "home")
    assert (reading["verification_status"], reading["version"], reading["supersedes"], reading["supersedes_reading_id"]) == \
        ("patient_reported", 1, None, None)
    # no approved threshold: not evaluated, never "within range" (safeguard 6), and no notice (safeguard 2)
    assert saved["evaluation"] == {"level": "not_evaluated", "rule_id": None, "message": None,
                                   "reason": "no_applicable_threshold"}
    assert count(api, "SELECT count(*) FROM notifications WHERE template_id LIKE 'VITAL_%%'") == 0
    event = api.conn.execute("SELECT verification_status, payload, source_type FROM events WHERE id = %s",
                             [reading["event_id"]]).fetchone()
    assert event[0] == "patient_reported" and event[1]["value"] == "128/82" and event[2] == "patient_entry"
    assert count(api, "SELECT count(*) FROM audit_logs WHERE action = 'vitals.create' AND result = 'allow'") == 1
    assert [x["id"] for x in api.http.get(f"{V1}/vitals", headers=b5.patient).json()] == [body["id"]]


def test_glucose_keeps_its_unit_with_no_conversion(api, b5):
    r = post(api, b5.patient, glucose("110", unit="mg/dL", context="post_meal")).json()["reading"]
    assert (r["value"], r["unit"], r["context"]) == ("110", "mg/dL", "post_meal")


@pytest.mark.parametrize("body", [
    bp(unit="mg/dL"), bp(context="fasting"), glucose(unit="mmHg"), glucose(context="home"),
    bp(value="১২৮/৮২"), bp(value="0/80"), bp(value="128"), bp(value="128/82/1"), bp(value="12345/80"),
    glucose(value="6.123"), glucose(value="-6"), glucose(value="0"), glucose(value="six"), glucose(value=6.1),
    bp(measured_at=(NOW + timedelta(hours=1)).isoformat()), bp(measured_at="2026-11-17T10:00:00"),
    bp(measured_at="yesterday"), bp(id="not-a-uuid"), bp(extra="x"), bp(confirmed="yes"), {"vital_type": "bp"}, [],
    {**bp(), "vital_type": "temperature"},
])
def test_format_checks_only(api, b5, body):
    r = api.http.post(f"{V1}/vitals", headers=b5.patient, json=body)
    assert (r.status_code, r.json()["code"]) == (422, "invalid_reading")
    assert count(api, "SELECT count(*) FROM events WHERE event_type = 'vital_reading'") == 0


def test_no_plausibility_confirmation_without_an_approved_rule(api, b5):
    assert post(api, b5.patient, bp("9999/1")).status_code == 201  # V1: format only until the reviewer approves limits


# ---- idempotency (safeguard 4)

def test_a_retry_returns_the_saved_result_and_other_data_conflicts(api, b5, other):
    body = bp()
    first = post(api, b5.patient, body)
    again = post(api, b5.patient, {**body, "confirmed": True})  # `confirmed` is not part of the reading
    assert (first.status_code, again.status_code) == (201, 200) and again.json() == first.json()
    changed = post(api, b5.patient, {**body, "value": "129/82"})
    assert (changed.status_code, changed.json()["code"]) == (409, "reading_id_conflict")
    assert count(api, "SELECT count(*) FROM events WHERE event_type = 'vital_reading'") == 1
    assert count(api, "SELECT count(*) FROM audit_logs WHERE action = 'vitals.create'") == 1
    # ids are per patient: another patient's identical id is their own reading, and reveals nothing
    assert post(api, other, {**body, "value": "130/85"}).status_code == 201
    assert [r["value"] for r in api.http.get(f"{V1}/vitals", headers=other).json()] == ["130/85"]
    assert [r["value"] for r in api.http.get(f"{V1}/vitals", headers=b5.patient).json()] == ["128/82"]


# ---- evaluation (SYNTHETIC rules and values)

def test_synthetic_thresholds_flag_and_escalate_only_where_they_apply(api, b5):
    critical = rule(api, b5, VT_BP, en="SYNTH critical message", bn="সিনথেটিক জরুরি বার্তা")
    flagged = rule(api, b5, VT_GLUCOSE, en="SYNTH flagged message", bn="সিনথেটিক সতর্ক বার্তা")
    thresholds(api, b5, {critical["rule_id"]: 150, flagged["rule_id"]: 7.5})
    ev = lambda body: post(api, b5.patient, body).json()["evaluation"]  # noqa: E731

    hit = ev(bp("150/90"))  # at_or_above on the systolic part
    assert (hit["level"], hit["rule_id"], hit["reason"]) == ("critical", critical["rule_id"], None)
    assert hit["message"] == {"en": "SYNTH critical message", "bn": "সিনথেটিক জরুরি বার্তা", "status": "approved"}
    assert ev(bp("149/160"))["level"] == "within_range"  # the rule names the systolic part only
    assert ev(bp("200/90", context="resting"))["reason"] == "no_applicable_threshold"  # context not in the rule
    assert ev(glucose("7.5"))["level"] == "flagged"
    assert ev(glucose("7.4"))["level"] == "within_range"
    assert ev(glucose("200", unit="mg/dL"))["reason"] == "no_applicable_threshold"  # V2: never converted
    assert ev(glucose("9", context="random"))["level"] == "not_evaluated"

    notices = api.conn.execute("SELECT template_id, recipient_id, payload FROM notifications "
                               "WHERE template_id LIKE 'VITAL_%%' ORDER BY created_at").fetchall()
    assert [n[0] for n in notices] == ["VITAL_CRITICAL_PLACEHOLDER", "VITAL_FLAGGED_PLACEHOLDER"]
    assert all(n[1] == b5.patient_id for n in notices) and set(notices[0][2]) == {"reading_id", "rule_version_id"}
    inbox = api.http.get(f"{V1}/notifications", headers=b5.patient).json()
    vital = [n for n in inbox if n["kind"] in ("vital_critical", "vital_flagged")]
    assert [n["kind"] for n in vital] == ["vital_flagged", "vital_critical"]  # newest first
    assert vital[1]["message"]["en"] == "SYNTH critical message" and vital[1]["reading_id"]


def test_no_per_patient_value_means_not_evaluated(api, b5):
    rule(api, b5, VT_BP)  # approved, but the treating doctor set no value: no reviewer default exists (V3)
    assert post(api, b5.patient, bp("250/90")).json()["evaluation"]["reason"] == "no_applicable_threshold"


def test_a_threshold_below_fires_on_low_values(api, b5):
    low = rule(api, b5, {**VT_GLUCOSE, "comparison": "at_or_below", "level": "critical"})
    thresholds(api, b5, {low["rule_id"]: 3})
    assert post(api, b5.patient, glucose("3")).json()["evaluation"]["level"] == "critical"
    assert post(api, b5.patient, glucose("3.1")).json()["evaluation"]["level"] == "within_range"


def test_the_most_serious_level_wins(api, b5):
    a = rule(api, b5, {**VT_BP, "level": "flagged"})
    c = rule(api, b5, VT_BP)
    thresholds(api, b5, {a["rule_id"]: 140, c["rule_id"]: 160})
    assert post(api, b5.patient, bp("145/80")).json()["evaluation"]["rule_id"] == a["rule_id"]
    assert post(api, b5.patient, bp("165/80")).json()["evaluation"]["rule_id"] == c["rule_id"]


def _approve_raw(api, b, rule_type, definition):
    """An approved rule that bypassed the registry's shape check (an old or damaged definition)."""
    rid = uuid4()
    api.conn.execute("INSERT INTO rules (id, rule_id, version, rule_type, definition, explanation_en, explanation_bn, "
                     "created_by) VALUES (%s, %s, 1, %s, %s, 'SYNTH', 'সিনথেটিক', %s)",
                     [rid, f"SYNTH-RAW-{rid.hex[:6].upper()}", rule_type, psycopg.types.json.Jsonb(definition),
                      b.reviewer_id])
    api.conn.execute("UPDATE rules SET status = 'approved', reviewed_by = %s, reviewed_at = now() WHERE id = %s",
                     [b.reviewer2_id, rid])
    api.conn.commit()


@pytest.fixture
def ids(api, b5):
    staff = dict(api.conn.execute("SELECT name, id FROM users WHERE role = 'clinical_reviewer'").fetchall())
    b5.reviewer_id, b5.reviewer2_id = staff["Synthetic clinical_reviewer"], staff["Synthetic Reviewer 2"]
    return b5


def test_a_rule_that_does_not_fit_fails_closed(api, ids):
    _approve_raw(api, ids, "vital_threshold", {"vital_type": "bp", "unit": "mmHg"})  # the old B5 shape
    saved = post(api, ids.patient, bp("250/90")).json()
    assert saved["evaluation"]["level"] == "not_evaluated" and saved["evaluation"]["reason"] == "rule_load_error"
    assert count(api, "SELECT count(*) FROM notifications WHERE template_id LIKE 'VITAL_%%'") == 0


def test_a_failed_check_saves_the_reading_as_not_evaluated(api, b5, monkeypatch):
    def broken(*a, **k):
        raise RuntimeError("synthetic failure")
    monkeypatch.setattr(readings, "evaluate", broken)
    r = post(api, b5.patient, bp())
    assert r.status_code == 201
    assert r.json()["evaluation"] == {"level": "not_evaluated", "rule_id": None, "message": None,
                                      "reason": "evaluation_unavailable"}
    assert count(api, "SELECT count(*) FROM events WHERE event_type = 'vital_reading'") == 1


def test_an_approved_plausibility_rule_asks_for_confirmation(api, ids):
    rule(api, ids, {"schema": 1, "vital_type": "bp", "unit": "mmHg", "component": "systolic", "at_least": 50,
                    "at_most": 250}, rule_type="vital_plausibility")  # SYNTHETIC limits
    body = bp("300/80")
    r = post(api, ids.patient, body)
    assert (r.status_code, r.json()["code"]) == (422, "confirmation_required")
    assert count(api, "SELECT count(*) FROM events WHERE event_type = 'vital_reading'") == 0
    assert post(api, ids.patient, {**body, "confirmed": True}).status_code == 201
    assert post(api, ids.patient, bp("120/80")).status_code == 201
    assert post(api, ids.patient, glucose("99")).status_code == 201  # the rule is about BP only
    _approve_raw(api, ids, "vital_plausibility", {"vital_type": "bp"})  # does not fit: ask, fail closed
    assert post(api, ids.patient, glucose("5")).json()["code"] == "confirmation_required"


def test_vital_rule_drafts_must_fit_their_shapes(api, b5):
    bad = [({**VT_BP, "component": None}, "invalid_rule_definition"),
           ({**VT_GLUCOSE, "component": "systolic"}, "invalid_rule_definition"),
           ({**VT_BP, "contexts": ["fasting"]}, "invalid_rule_definition"),
           ({**VT_BP, "contexts": []}, "invalid_rule_definition"),
           ({**VT_BP, "comparison": "above"}, "invalid_rule_definition"),
           ({**VT_BP, "level": "urgent"}, "invalid_rule_definition"),
           ({**VT_BP, "value": 150}, "invalid_rule_definition"),  # no number lives in a threshold rule
           ({**VT_BP, "schema": 2}, "invalid_rule_definition"),
           ({**VT_BP, "unit": "mg/dL"}, "invalid_vital_threshold")]
    for definition, code in bad:
        r = draft(api, b5.reviewer, {**VT, "definition": definition})
        assert (r.status_code, r.json()["code"]) == (422, code), definition
    plaus = {"schema": 1, "vital_type": "glucose", "unit": "mmol/L", "at_least": 2, "at_most": 1}
    r = draft(api, b5.reviewer, {**VT, "rule_type": "vital_plausibility", "definition": plaus})
    assert (r.status_code, r.json()["code"]) == (422, "invalid_rule_definition")
    ok = draft(api, b5.reviewer, {**VT, "rule_type": "vital_plausibility", "definition": {**plaus, "at_least": 0.5}})
    assert ok.status_code == 201


# ---- corrections (V6, safeguard 5)

def test_a_correction_keeps_the_original_with_its_reason(api, b5, other):
    original = post(api, b5.patient, glucose("6.1")).json()["reading"]
    fix = {**glucose("6.4"), "reason": "SYNTH typed the wrong number"}
    r = post(api, b5.patient, fix, of=original["id"])
    assert r.status_code == 201, r.text
    new = r.json()["reading"]
    assert (new["version"], new["supersedes"], new["supersedes_reading_id"], new["correction_reason"]) == \
        (2, original["event_id"], original["id"], "SYNTH typed the wrong number")
    listed = {x["id"]: x for x in api.http.get(f"{V1}/vitals", headers=b5.patient).json()}
    assert listed[original["id"]]["value"] == "6.1" and listed[fix["id"]]["value"] == "6.4"  # both kept
    assert post(api, b5.patient, fix, of=original["id"]).status_code == 200  # a retry of the correction
    entry = api.conn.execute("SELECT actor_id, reason, resource_id FROM audit_logs WHERE action = 'vitals.correct'").fetchall()
    assert len(entry) == 1 and entry[0][1] == "reason_given" and str(entry[0][2]) == new["event_id"]
    row = api.conn.execute("SELECT actor_id, created_at FROM vital_readings WHERE id = %s", [fix["id"]]).fetchone()
    assert row[0] == b5.patient_id and row[1] is not None

    again = post(api, b5.patient, {**glucose("6.5"), "reason": "SYNTH"}, of=original["id"])
    assert (again.status_code, again.json()["code"]) == (409, "already_corrected")
    third = post(api, b5.patient, {**glucose("6.5"), "reason": "SYNTH again"}, of=new["id"]).json()["reading"]
    assert third["version"] == 3

    no_reason = post(api, b5.patient, glucose("6.6"), of=third["id"])
    assert (no_reason.status_code, no_reason.json()["code"]) == (422, "reason_required")
    other_type = post(api, b5.patient, {**bp(), "reason": "SYNTH"}, of=third["id"])
    assert (other_type.status_code, other_type.json()["code"]) == (422, "invalid_reading")
    assert post(api, b5.patient, {**glucose(), "reason": "SYNTH"}, of=uuid4()).status_code == 404
    assert post(api, other, {**glucose(), "reason": "SYNTH"}, of=third["id"]).status_code == 404  # not theirs


# ---- the patient notice (safeguards 1, 2)

def test_a_failing_notice_is_retried_then_kept_in_app_and_never_duplicated(api, b5):
    c = rule(api, b5, VT_BP)
    thresholds(api, b5, {c["rule_id"]: 150})
    body = bp("170/90")
    post(api, b5.patient, body)
    post(api, b5.patient, body)  # the app retried: still one notice
    assert count(api, "SELECT count(*) FROM notifications WHERE template_id = 'VITAL_CRITICAL_PLACEHOLDER'") == 1

    def down(n):
        raise ConnectionError("synthetic gateway down")
    notification.deliver_due(api.conn, [("push", down)], max_attempts=2, backoff=timedelta(0))  # consent notices too
    assert notification.deliver_due(api.conn, [("push", down)], max_attempts=2, backoff=timedelta(0)) == 0
    status = api.conn.execute("SELECT status, attempts FROM notifications WHERE template_id = 'VITAL_CRITICAL_PLACEHOLDER'"
                              ).fetchone()
    assert status == ("fallback_in_app", 2)
    assert count(api, "SELECT count(*) FROM audit_logs a JOIN notifications n ON n.id = a.resource_id "
                      "WHERE a.action = 'notification.failure' AND n.template_id = 'VITAL_CRITICAL_PLACEHOLDER'") == 1
    assert count(api, "SELECT count(*) FROM vital_readings") == 1  # the reading never depends on delivery
    assert [n["kind"] for n in api.http.get(f"{V1}/notifications", headers=b5.patient).json()].count("vital_critical") == 1


def test_a_notice_is_only_ever_linked_to_a_fired_reading(api, b5):
    post(api, b5.patient, bp())
    n = notification.enqueue(api.conn, recipient_id=b5.patient_id, template_id="VITAL_CRITICAL_PLACEHOLDER", payload={})
    with pytest.raises(psycopg.errors.CheckViolation):
        api.conn.execute("INSERT INTO vital_readings (patient_id, id, event_id, request_hash, actor_id, evaluation, "
                         "notification_id) SELECT patient_id, %s, event_id, 'x', actor_id, %s, %s FROM vital_readings",
                         [uuid4(), psycopg.types.json.Jsonb({"level": "not_evaluated"}), n["id"]])
    api.conn.rollback()


def test_readings_are_append_only(api, b5):
    post(api, b5.patient, bp())
    for sql in ("UPDATE vital_readings SET confirmed = true", "DELETE FROM vital_readings", "TRUNCATE vital_readings CASCADE"):
        with pytest.raises(psycopg.errors.RaiseException):
            api.conn.execute(sql)
        api.conn.rollback()


# ---- doctors see readings only through the timeline and summary under consent (V5, safeguard 3)

def test_doctors_see_readings_only_under_a_timeline_consent(api, b5, other):
    post(api, b5.patient, bp("131/83"))
    post(api, other, bp("140/90"))
    timeline = f"{V1}/patients/{b5.patient_id}/timeline"
    r = api.http.get(timeline, headers=b5.doctor)
    assert (r.status_code, r.json()["code"]) == (403, "consent_required")
    consent(api, b5, categories=("timeline",))
    events = api.http.get(timeline, headers=b5.doctor).json()
    assert [e["payload"]["value"] for e in events if e["event_type"] == "vital_reading"] == ["131/83"]
    summary = api.http.get(f"{V1}/patients/{b5.patient_id}/summary", headers=b5.doctor).json()
    assert [s["text"].split(" · ")[:3] for s in summary["patient_reported"]] == [["131/83", "mmHg", "home"]]
    other_id = api.conn.execute("SELECT id FROM patients WHERE id <> %s", [b5.patient_id]).fetchone()[0]
    r = api.http.get(f"{V1}/patients/{other_id}/timeline", headers=b5.doctor)
    assert (r.status_code, r.json()["code"]) == (403, "consent_required")
