"""Slice 8.6 against PostgreSQL: manual entry and retry endpoints (owner decisions of 2026-11-14: D10 patient
only, D12 manual entry always allowed, D14 conflicts not audited, retry cap 5). Synthetic data only.

Shows the state machine, authorization, idempotency, the races with a worker, the audit entries, and that no
verified event is ever created."""
import logging
import threading
from datetime import timedelta

import pytest

from swasthyoid.api.deps import Actor
from swasthyoid.capture import extraction
from swasthyoid.identity import accounts, sessions
from swasthyoid.tests.test_extraction_integration import V1, blank, broken, job, ocr, patient, prod, upload  # noqa: F401

CHILD = dict(hard_timeout=timedelta(seconds=60), heartbeat=timedelta(seconds=1), max_attempts=2)
MANUAL, RETRY = "manual-entry", "retry-extraction"


@pytest.fixture
def c(prod, caplog):  # noqa: F811
    caplog.set_level(logging.WARNING)
    prod.headers = patient(prod)
    return prod


def post(c, doc_id, what, headers=None, key=None):
    extra = {"Idempotency-Key": key} if key else {}
    return c.http.post(f"{V1}/documents/{doc_id}/{what}", headers={**(headers or c.headers), **extra})


def audit(conn, doc_id):
    return conn.execute("SELECT action, result, actor_role, reason FROM audit_logs WHERE resource_id = %s "
                        "AND action LIKE 'document.%%' ORDER BY at", [doc_id]).fetchall()


def snapshot(conn, doc_id):
    """Everything a refused request must leave alone."""
    return (conn.execute("SELECT status, extraction_attempts, extraction_error, extraction_claim, next_extraction_at "
                         "FROM documents WHERE id = %s", [doc_id]).fetchone(),
            conn.execute("SELECT count(*) FROM extractions WHERE document_id = %s", [doc_id]).fetchone()[0],
            audit(conn, doc_id))


def fail(conn, doc_id):
    """Drive a fresh or requeued document to extraction_failed with a broken engine."""
    extraction.run_due(conn, broken, max_attempts=1)
    assert job(conn, doc_id)[0] == "extraction_failed"



# ---- manual entry

def test_manual_entry_from_uploaded_stores_an_empty_manual_row_and_one_audit_entry(c):
    doc_id = upload(c, c.headers)
    r = post(c, doc_id, MANUAL)
    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["document_id"], body["status"]) == (doc_id, "needs_review")
    assert (body["extraction"]["engine"], body["extraction"]["version"], body["extraction"]["raw_text"]) == ("manual", 1, "")
    assert body["extraction"]["fields"] == blank()  # every approved field empty and marked for manual entry
    with c.connect() as conn:
        assert job(conn, doc_id)[0] == "needs_review"
        assert audit(conn, doc_id) == [("document.manual_entry", "allow", "patient", "from:uploaded")]
        assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 0  # nothing verified
        assert extraction.claim(conn) is None and extraction.run_due(conn, ocr) == 0  # a worker finds nothing due


def test_manual_entry_is_allowed_while_an_adapter_is_configured(c, monkeypatch):
    monkeypatch.setenv("OCR_ADAPTER", "swasthyoid.tests.adapters.fake_adapters:good")  # D12: always allowed
    doc_id = upload(c, c.headers)
    assert post(c, doc_id, MANUAL).status_code == 200
    with c.connect() as conn:
        assert extraction.run_due(conn, **CHILD) == 0 and job(conn, doc_id)[0] == "needs_review"


def test_manual_entry_from_a_failed_extraction(c):
    doc_id = upload(c, c.headers)
    with c.connect() as conn:
        fail(conn, doc_id)
    assert post(c, doc_id, MANUAL).status_code == 200
    with c.connect() as conn:
        assert audit(conn, doc_id) == [("document.manual_entry", "allow", "patient", "from:extraction_failed")]


@pytest.mark.parametrize("lease", ["expired", "waiting_for_retry"])
def test_manual_entry_from_extracting_without_a_live_claim(c, lease):
    doc_id = upload(c, c.headers)
    with c.connect() as conn:
        if lease == "expired":
            extraction.claim(conn, doc_id)
            conn.execute("UPDATE documents SET next_extraction_at = clock_timestamp() - interval '1 second' WHERE id = %s", [doc_id])
        else:
            extraction.run_due(conn, broken, limit=1)  # failed once: extracting, no claim, retry time ahead
            assert job(conn, doc_id)[0] == "extracting"
    assert post(c, doc_id, MANUAL).status_code == 200
    with c.connect() as conn:
        status = conn.execute("SELECT status, extraction_claim, next_extraction_at FROM documents WHERE id = %s", [doc_id]).fetchone()
        assert status == ("needs_review", None, None)


def test_a_live_claim_refuses_manual_entry_with_409_and_changes_and_audits_nothing(c):
    doc_id = upload(c, c.headers)
    with c.connect() as conn:
        extraction.claim(conn, doc_id)
        before = snapshot(conn, doc_id)
    r = post(c, doc_id, MANUAL)
    assert (r.status_code, r.json()["code"]) == (409, "extraction_in_progress")
    with c.connect() as conn:
        assert snapshot(conn, doc_id) == before and before[2] == []  # D14: the refusal is not audited


@pytest.mark.parametrize("state", ["needs_review", "verified", "rejected"])
def test_manual_entry_from_review_or_a_closed_state_is_refused(c, state):
    doc_id = upload(c, c.headers)
    with c.connect() as conn:
        extraction.run_due(conn, ocr)
        if state != "needs_review":
            extraction.documents.set_status(conn, doc_id, state)
        before = snapshot(conn, doc_id)
    r = post(c, doc_id, MANUAL)
    assert (r.status_code, r.json()["code"]) == (409, "not_allowed_state")
    with c.connect() as conn:
        assert snapshot(conn, doc_id) == before


def test_another_patient_unauthenticated_and_staff_callers_cannot_use_either_endpoint(c):
    doc_id = upload(c, c.headers)
    stranger = patient(c, "+8801700000002")
    with c.connect() as conn:
        doctor = accounts.register_user(conn, phone="+8801900000002", role="doctor", name="Synthetic Doctor")
        token = sessions.issue_tokens(conn, subject_id=doctor["id"], role="doctor", device_id="dev-1")["access_token"]
        before = snapshot(conn, doc_id)
    for what in (MANUAL, RETRY):
        assert post(c, doc_id, what, headers=stranger).status_code == 404  # someone else's document
        assert c.http.post(f"{V1}/documents/{doc_id}/{what}").status_code == 401
        assert post(c, doc_id, what, headers={"Authorization": f"Bearer {token}"}).status_code == 403  # patient only (D10)
        assert post(c, "00000000-0000-0000-0000-000000000000", what).status_code == 404
    with c.connect() as conn:
        assert snapshot(conn, doc_id) == before
        denied = conn.execute("SELECT count(*) FROM audit_logs WHERE action = 'rbac.deny'").fetchone()[0]
        assert denied >= 2  # the gateway chain audits the role refusals, as it always did


def test_a_repeated_request_with_the_same_idempotency_key_replays_and_does_nothing_twice(c):
    doc_id = upload(c, c.headers)
    first = post(c, doc_id, MANUAL, key="k-1")
    again = post(c, doc_id, MANUAL, key="k-1")
    assert first.status_code == again.status_code == 200 and first.json() == again.json()
    with c.connect() as conn:
        assert len(audit(conn, doc_id)) == 1 and snapshot(conn, doc_id)[1] == 1
    other = post(c, doc_id, MANUAL, key="k-2")  # a new key on a document already in review
    assert (other.status_code, other.json()["code"]) == (409, "not_allowed_state")


def test_an_audit_failure_undoes_the_whole_manual_entry(c, monkeypatch):
    doc_id = upload(c, c.headers)
    with c.connect() as conn:
        me = conn.execute("SELECT patient_id FROM documents WHERE id = %s", [doc_id]).fetchone()[0]
        before = snapshot(conn, doc_id)

        def refuse(*args, **kwargs):
            raise RuntimeError("audit store unavailable")

        monkeypatch.setattr(extraction.audit, "append", refuse)
        with pytest.raises(RuntimeError):
            extraction.start_manual_entry(conn, doc_id, actor=Actor(id=me, role="patient", device_id="d", is_verified=True))
        assert snapshot(conn, doc_id) == before  # state, rows and audit untouched: fail closed


def test_a_worker_whose_lease_ran_out_stores_nothing_after_manual_entry(c):
    doc_id = upload(c, c.headers)
    with c.connect() as conn:
        job_ = extraction.claim(conn, doc_id)
        conn.execute("UPDATE documents SET next_extraction_at = clock_timestamp() - interval '1 second' WHERE id = %s", [doc_id])
    assert post(c, doc_id, MANUAL).status_code == 200
    with c.connect() as conn:
        options = extraction._settings({"hard_timeout": None})
        extraction._attempt(conn, job_, ocr, None, options)  # the late worker finishes its read and tries to store
        assert job(conn, doc_id)[0] == "needs_review"
        assert conn.execute("SELECT engine FROM extractions WHERE document_id = %s", [doc_id]).fetchall() == [("manual",)]
        assert conn.execute("SELECT extraction_error FROM documents WHERE id = %s", [doc_id]).fetchone()[0] is None


# ---- retry

def test_retry_requeues_a_failed_document_from_the_first_attempt_and_audits_it(c):
    doc_id = upload(c, c.headers)
    with c.connect() as conn:
        fail(conn, doc_id)
    r = post(c, doc_id, RETRY)
    assert r.status_code == 200
    assert r.json() == {"document_id": doc_id, "status": "extracting", "retries_used": 1, "retries_allowed": 5}
    with c.connect() as conn:
        assert job(conn, doc_id)[:2] == ("extracting", 0)
        assert audit(conn, doc_id) == [("document.retry", "allow", "patient", "retry 1 of 5")]
        assert extraction.run_due(conn, ocr) == 1 and job(conn, doc_id)[0] == "needs_review"  # the worker picks it up
        assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 0


@pytest.mark.parametrize("state", ["uploaded", "extracting", "needs_review"])
def test_retry_is_refused_unless_the_extraction_failed(c, state):
    doc_id = upload(c, c.headers)
    with c.connect() as conn:
        if state == "extracting":
            extraction.claim(conn, doc_id)
        elif state == "needs_review":
            extraction.run_due(conn, ocr)
        before = snapshot(conn, doc_id)
    r = post(c, doc_id, RETRY)
    assert (r.status_code, r.json()["code"]) == (409, "not_allowed_state")
    with c.connect() as conn:
        assert snapshot(conn, doc_id) == before


def test_the_sixth_retry_is_refused_and_manual_entry_is_still_possible(c):
    doc_id = upload(c, c.headers)
    with c.connect() as conn:
        fail(conn, doc_id)
    for n in range(1, 6):
        r = post(c, doc_id, RETRY)
        assert (r.status_code, r.json()["retries_used"]) == (200, n)
        with c.connect() as conn:
            fail(conn, doc_id)
    with c.connect() as conn:
        before = snapshot(conn, doc_id)
    r = post(c, doc_id, RETRY)
    assert (r.status_code, r.json()["code"]) == (409, "retry_limit_reached")
    with c.connect() as conn:
        assert snapshot(conn, doc_id) == before  # the refused retry is not counted or audited
        assert [a[0] for a in audit(conn, doc_id)] == ["document.retry"] * 5
    assert post(c, doc_id, MANUAL).status_code == 200  # the cap never takes the patient's escape hatch away


def test_a_retry_cap_is_per_document(c):
    first, second = upload(c, c.headers), upload(c, c.headers)
    with c.connect() as conn:
        fail(conn, first)
        fail(conn, second)
    assert post(c, first, RETRY).json()["retries_used"] == 1
    assert post(c, second, RETRY).json()["retries_used"] == 1


def test_a_repeated_retry_with_the_same_key_replays_and_uses_one_retry(c):
    doc_id = upload(c, c.headers)
    with c.connect() as conn:
        fail(conn, doc_id)
    a, b = post(c, doc_id, RETRY, key="r-1"), post(c, doc_id, RETRY, key="r-1")
    assert a.status_code == b.status_code == 200 and a.json() == b.json()
    with c.connect() as conn:
        assert [x[0] for x in audit(conn, doc_id)] == ["document.retry"]


def test_two_simultaneous_retries_use_exactly_one(c):
    doc_id = upload(c, c.headers)
    with c.connect() as conn:
        fail(conn, doc_id)
        me = conn.execute("SELECT patient_id FROM documents WHERE id = %s", [doc_id]).fetchone()[0]
    outcomes, gate = [], threading.Barrier(2)

    def attempt():
        with c.connect() as conn:
            gate.wait()
            try:
                outcomes.append(extraction.retry_extraction(
                    conn, doc_id, actor=Actor(id=me, role="patient", device_id="d", is_verified=True)))
            except extraction.Conflict as e:
                outcomes.append(e.args[0])

    threads = [threading.Thread(target=attempt) for _ in range(2)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert sorted(map(str, outcomes)) == ["1", "not_allowed_state"]
    with c.connect() as conn:
        assert [x[0] for x in audit(conn, doc_id)] == ["document.retry"]
