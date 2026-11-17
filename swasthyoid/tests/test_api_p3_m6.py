"""P3 M6: strict rule shapes, the check outbox and its runner, retry and failure, requeue, and the doctor's checks route.

Synthetic data only. Every rule and catalog entry is made up; these tests show technical behaviour, not clinical
validity (clinical golden cases are REVIEWER-PENDING, FRD Q7). Patients never see raw M6 output (invariant 6).
"""
from datetime import timedelta
from uuid import uuid4

import pytest

from swasthyoid.capture import drugmatch
from swasthyoid.safety import checks, engine
from swasthyoid.workers import safety as safety_worker
from swasthyoid.tests.test_api_b2 import cast  # noqa: F401
from swasthyoid.tests.test_api_b4a import RX, b, events, in_review, prod, put  # noqa: F401
from swasthyoid.tests.test_api_b5 import DDI, b5, draft  # noqa: F401
from swasthyoid.tests.test_api_b6 import approved, consent
from swasthyoid.tests.test_api_m1 import V1, api, people  # noqa: F401
from swasthyoid.tests.test_api_p3_m5 import ev

CATALOG = drugmatch.Catalog("synthetic-1", "SYNTHETIC test catalog", [
    {"id": "S1", "generic": "synthgen-alpha", "brands": ["SYNTHBRAND-A"]},
    {"id": "S2", "generic": "synthgen-beta", "brands": ["SYNTHBRAND-B"]}])
ALLERGY = {**DDI, "rule_type": "allergy", "severity": "contraindicated",
           "definition": {"schema": 1, "allergen_terms": ["SYNTH-ALLERGEN"], "ingredients": ["synthgen-alpha"]}}
DUP = {**DDI, "rule_type": "duplicate", "severity": "moderate", "definition": {"schema": 1, "ingredients": ["synthgen-alpha"]}}


def rx(api, b, *names, patient_id=None):
    """A verified prescription with its medication events, queued for its check as M3 confirm does."""
    pid = patient_id or b.patient_id
    d = uuid4()
    api.conn.execute("INSERT INTO documents (id, patient_id, doc_type, status, uploaded_by) VALUES (%s, %s, 'prescription', "
                     "'verified', %s)", [d, pid, pid])
    ids = [ev(api, pid, "medication", {"name_as_written": n}, source=d) for n in names]
    checks.enqueue(api.conn, document_id=d, patient_id=pid)
    return d, ids


def listed(api, b):
    r = api.http.get(f"{V1}/patients/{b.patient_id}/safety-checks", headers=b.doctor)
    assert r.status_code == 200, r.text
    return r.json()


def outcomes(api, d):
    return [tuple(r) for r in api.conn.execute("SELECT attempt, outcome, reason FROM safety_checks WHERE document_id = %s "
                                               "ORDER BY created_at", [d]).fetchall()]


# ---- strict rule shapes (D5)

@pytest.mark.parametrize("body", [
    {**DDI, "definition": {"placeholder": "SYNTH", "drugs": ["SYNTH-DRUG-001"]}},           # the old free-form shape
    {**DDI, "definition": {"schema": 1, "ingredients": ["synthgen-alpha"]}},                # a pair needs two
    {**DDI, "definition": {"schema": 1, "ingredients": ["a", "b", "c"]}},
    {**DDI, "definition": {"schema": 1, "ingredients": ["SynthGen-Alpha", "synthgen-alpha "]}},  # the same name twice
    {**DDI, "definition": {"schema": 2, "ingredients": ["a", "b"]}},
    {**DDI, "definition": {"schema": True, "ingredients": ["a", "b"]}},
    {**DDI, "definition": {"schema": 1, "ingredients": ["a", "b"], "note": "x"}},          # no extra keys
    {**DDI, "definition": {"schema": 1, "ingredients": ["a", ""]}},
    {**DDI, "severity": None},                                                              # an alert needs a severity
    {**ALLERGY, "definition": {"schema": 1, "ingredients": ["synthgen-alpha"]}},
    {**DUP, "definition": {"schema": 1, "ingredients": []}},
])
def test_engine_rules_must_fit_their_strict_shape(api, b5, body):
    r = draft(api, b5.reviewer, body)
    assert (r.status_code, r.json()["code"]) == (422, "invalid_rule_definition"), r.text


def test_the_strict_shapes_are_accepted(api, b5):
    for body in (DDI, ALLERGY, DUP, {**DDI, "rule_type": "drug_disease", "definition": {"placeholder": "SYNTH"}}):
        assert draft(api, b5.reviewer, body).status_code == 201  # drug_disease keeps the B5 shape check: it cannot run


# ---- the runner (D6, D7, correction 1)

def test_a_check_runs_once_and_writes_alerts_and_its_result(api, b5):
    for body in (DDI, ALLERGY, DUP):
        approved(api, b5, body)
    old_doc, (old_b,) = rx(api, b5, "SYNTHBRAND-B")
    allergy = ev(api, b5.patient_id, "allergy", {"allergy_text": "SYNTH-ALLERGEN, dust"})
    ev(api, b5.patient_id, "allergy", {"allergy_text": "SYNTH-ALLERGEN"}, status="patient_reported")  # never an M6 input
    doc, (new_a, unknown) = rx(api, b5, "SYNTHBRAND-A 500 mg", "SYNTH-NOT-IN-CATALOG")
    assert checks.run_due(api.conn, CATALOG) == 2
    assert checks.run_due(api.conn, CATALOG) == 0  # done: never run twice
    checks.enqueue(api.conn, document_id=doc, patient_id=b5.patient_id)  # a repeated enqueue does nothing
    assert checks.run_due(api.conn, CATALOG) == 0

    consent(api, b5, ("timeline", "safety"))
    got = {c["document_id"]: c for c in listed(api, b5)}
    mine = got[str(doc)]
    assert (mine["status"], mine["reason"], mine["attempts"], mine["alert_count"]) == ("completed", None, 1, 2)
    assert mine["unrecognised"] == [{"event_id": unknown, "reason": "not_in_catalog", "scope": "prescription",
                                     "name_as_written": "SYNTH-NOT-IN-CATALOG"}]
    assert {n["check"] for n in mine["not_run"]} == {"drug_disease", "allergy_class", "duplicate_class", "class_lookback"}
    assert got[str(old_doc)]["status"] == "completed"
    alerts = api.http.get(f"{V1}/patients/{b5.patient_id}/safety-alerts", headers=b5.doctor).json()
    mine = sorted((a["severity"], sorted(a["evidence_event_ids"])) for a in alerts if a["source_document_id"] == str(doc))
    assert mine == [("contraindicated", sorted([new_a, allergy])), ("major", sorted([new_a, old_b]))]
    assert outcomes(api, doc) == [(1, "completed", None)]
    logged = api.conn.execute("SELECT action, result, reason FROM audit_logs WHERE action LIKE 'safety.check.%%' "
                              "ORDER BY seq").fetchall()
    assert logged == [("safety.check.completed", "allow", "alerts_found")] * 2  # the older document pairs with the new one too


def test_names_need_a_timeline_consent_and_patients_never_see_checks(api, b5):
    _, (unknown,) = rx(api, b5, "SYNTH-NOT-IN-CATALOG")
    checks.run_due(api.conn, CATALOG)
    url = f"{V1}/patients/{b5.patient_id}/safety-checks"
    for headers in (b5.patient, b5.verifier, b5.reviewer, b5.admin):
        assert api.http.get(url, headers=headers).json()["code"] == "role_not_allowed"
    assert api.http.get(url, headers=b5.doctor).json()["code"] == "consent_required"
    consent(api, b5, ("timeline",))
    assert api.http.get(url, headers=b5.doctor).json()["code"] == "category_not_allowed"
    consent(api, b5, ("safety",))
    assert listed(api, b5)[0]["unrecognised"][0] == {"event_id": unknown, "reason": "not_in_catalog",
                                                     "scope": "prescription", "name_as_written": None}


def test_no_catalog_blocks_visibly_and_a_requeue_runs_it_again(api, b5):
    approved(api, b5)
    doc, _ = rx(api, b5, "SYNTHBRAND-A", "SYNTHBRAND-B")
    consent(api, b5, ("timeline", "safety"))
    assert [c["status"] for c in listed(api, b5)] == ["queued"]
    checks.run_due(api.conn, None)
    c = listed(api, b5)[0]
    assert (c["status"], c["reason"], c["alert_count"]) == ("blocked", "catalog_unavailable", 0)
    assert checks.run_due(api.conn, CATALOG) == 0  # a block is a result, not silently retried
    assert checks.requeue(api.conn) == 1
    assert listed(api, b5)[0]["status"] == "queued"
    checks.run_due(api.conn, CATALOG)
    assert (listed(api, b5)[0]["status"], listed(api, b5)[0]["alert_count"]) == ("completed", 1)
    assert outcomes(api, doc) == [(1, "blocked", "catalog_unavailable"), (1, "completed", None)]
    assert checks.requeue(api.conn) == 0  # a completed check is never run again


def test_an_approved_rule_that_does_not_fit_blocks_the_check(api, b5):
    r = draft(api, b5.reviewer, {**DDI, "rule_type": "drug_disease", "definition": {"placeholder": "SYNTH"}}).json()
    # written before the strict shapes existed: an approved ddi version with the old free-form definition
    api.conn.execute("INSERT INTO rules (id, rule_id, version, rule_type, severity, definition, explanation_en, "
                     "explanation_bn, created_by) SELECT %s, 'RULE-OLDSHAPE', 1, 'ddi', 'major', "
                     "'{\"drugs\": [\"SYNTH\"]}', 'SYNTH', 'সিনথেটিক', created_by FROM rules WHERE id = %s", [uuid4(), r["id"]])
    old = api.conn.execute("SELECT id FROM rules WHERE rule_id = 'RULE-OLDSHAPE'").fetchone()[0]
    assert api.http.post(f"{V1}/rules/{old}/approve", headers=b5.reviewer2).status_code == 200
    approved(api, b5)
    doc, _ = rx(api, b5, "SYNTHBRAND-A", "SYNTHBRAND-B")
    checks.run_due(api.conn, CATALOG)
    assert outcomes(api, doc) == [(1, "blocked", "rule_load_error")]
    assert api.conn.execute("SELECT count(*) FROM safety_alerts").fetchone()[0] == 0  # nothing partial


def test_infrastructure_failures_retry_then_fail_and_never_undo_the_verification(api, b5, monkeypatch):
    approved(api, b5)
    doc, _ = rx(api, b5, "SYNTHBRAND-A", "SYNTHBRAND-B")
    real = engine.evaluate
    monkeypatch.setattr(engine, "evaluate", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("synthetic outage")))
    no_wait = dict(max_attempts=2, backoff=timedelta(0), limit=1)  # one attempt per call
    consent(api, b5, ("timeline", "safety"))
    checks.run_due(api.conn, CATALOG, **no_wait)
    assert (listed(api, b5)[0]["status"], listed(api, b5)[0]["reason"]) == ("retrying", "infrastructure_error")
    checks.run_due(api.conn, CATALOG, **no_wait)
    c = listed(api, b5)[0]
    assert (c["status"], c["attempts"], c["alert_count"]) == ("failed", 2, 0)
    assert outcomes(api, doc) == [(1, "error", "infrastructure_error"), (2, "error", "infrastructure_error")]
    assert api.conn.execute("SELECT status FROM documents WHERE id = %s", [doc]).fetchone()[0] == "verified"
    assert api.conn.execute("SELECT count(*) FROM audit_logs WHERE action = 'safety.check.failed' AND result = 'failed'"
                            ).fetchone()[0] == 1
    monkeypatch.setattr(engine, "evaluate", real)
    assert checks.requeue(api.conn) == 1
    checks.run_due(api.conn, CATALOG, **no_wait)
    assert (listed(api, b5)[0]["status"], listed(api, b5)[0]["alert_count"]) == ("completed", 1)


def test_a_failure_after_alerts_were_written_keeps_none_of_them(api, b5, monkeypatch):
    approved(api, b5)
    rx(api, b5, "SYNTHBRAND-A", "SYNTHBRAND-B")
    calls = []
    real = checks.Jsonb

    def flaky(value):  # the first result row fails after its alerts were inserted
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("synthetic failure mid-write")
        return real(value)

    monkeypatch.setattr(checks, "Jsonb", flaky)
    checks.run_due(api.conn, CATALOG, backoff=timedelta(0), limit=1)
    assert api.conn.execute("SELECT count(*) FROM safety_alerts").fetchone()[0] == 0
    checks.run_due(api.conn, CATALOG)
    assert api.conn.execute("SELECT count(*) FROM safety_alerts").fetchone()[0] == 1
    assert [r[0] for r in api.conn.execute("SELECT outcome FROM safety_checks ORDER BY created_at")] == ["error", "completed"]


# ---- transaction 1: M3 confirm and the outbox row commit together (real schema, real routes)

def test_confirming_a_prescription_queues_its_check_atomically(b, monkeypatch):  # noqa: F811
    doc_id = in_review(b)
    assert put(b, doc_id, RX).status_code == 200
    with monkeypatch.context() as m:
        m.setattr(checks, "enqueue", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("synthetic outbox failure")))
        with pytest.raises(RuntimeError):
            b.http.post(f"{V1}/documents/{doc_id}/confirm", headers=b.patient)
    assert events(b, doc_id) == []  # no verification without its pending check
    with b.connect() as conn:
        assert conn.execute("SELECT status FROM documents WHERE id = %s", [doc_id]).fetchone()[0] == "needs_review"
    assert b.http.post(f"{V1}/documents/{doc_id}/confirm", headers=b.patient).status_code == 200
    with b.connect() as conn:
        job = conn.execute("SELECT status, attempts FROM safety_check_jobs WHERE document_id = %s", [doc_id]).fetchone()
        assert job == ("queued", 0)
        checks.run_due(conn, None)
        assert conn.execute("SELECT outcome, reason FROM safety_checks").fetchall() == [("blocked", "catalog_unavailable")]
    assert b.http.get(f"{V1}/documents/{doc_id}", headers=b.patient).json()["status"] == "verified"  # never undone


def test_the_runner_command(b, monkeypatch, capsys):  # noqa: F811
    doc_id = in_review(b)
    put(b, doc_id, RX)
    b.http.post(f"{V1}/documents/{doc_id}/confirm", headers=b.patient)
    monkeypatch.delenv("SAFETY_POLL_SECONDS", raising=False)
    monkeypatch.delenv("DRUG_CATALOG_PATH", raising=False)
    assert safety_worker.main([]) == 2  # loop mode needs SAFETY_POLL_SECONDS
    monkeypatch.setenv("DRUG_CATALOG_PATH", "relative.csv")
    assert safety_worker.main(["--once"]) == 2
    monkeypatch.delenv("DRUG_CATALOG_PATH")
    assert safety_worker.main(["--once"]) == 0
    assert safety_worker.main(["--requeue"]) == 0
    err = capsys.readouterr().err
    assert "code=catalog_unavailable" in err and "setting=DRUG_CATALOG_PATH reason=not_absolute" in err
    assert "code=requeued jobs=1" in err and "SYNTH" not in err


@pytest.mark.parametrize("sql", [
    "UPDATE safety_checks SET outcome = 'completed', reason = NULL",
    "DELETE FROM safety_checks",
    "TRUNCATE safety_checks",
    "DELETE FROM safety_check_jobs",
])
def test_results_are_append_only_and_jobs_are_never_deleted(api, b5, sql):
    rx(api, b5, "SYNTHBRAND-A")
    checks.run_due(api.conn, None)
    with pytest.raises(Exception):
        api.conn.execute(sql)


def test_one_completed_result_per_document(api, b5):
    doc, _ = rx(api, b5, "SYNTHBRAND-A")
    checks.run_due(api.conn, CATALOG)
    with pytest.raises(Exception):
        api.conn.execute("INSERT INTO safety_checks (id, document_id, patient_id, attempt, outcome) "
                         "VALUES (%s, %s, %s, 2, 'completed')", [uuid4(), doc, b5.patient_id])
