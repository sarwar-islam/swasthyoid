"""M6 check jobs: the transactional outbox and its runner (P3; owner decisions D6, D7 and correction 1, 2026-11-17).

Transaction 1 (M3 confirm, verification/review.py): the verified events and enqueue() commit together.
Transaction 2 (run_due, a worker): claim one due job with a row lock, run the engine and store its result (alerts and a
`completed` or `blocked` row) inside a savepoint, then mark the job done; all of it commits together, so a crash
part-way stores nothing and the job is still queued. An exception is an infrastructure failure: the savepoint is rolled
back, an `error` row is stored and the job retried with backoff; past MAX_ATTEMPTS the job is `failed` and audited. A
clinical result (completed, with or without alerts) and a block (rule_load_error, catalog_unavailable) are kept apart
from infrastructure errors, and nothing ever undoes the verification.
Idempotent: one job per document (primary key), at most one `completed` row per document (unique index), and the alerts
are written in the same transaction as that row.
shortcut: a crash while a job is locked is not counted as an attempt (the transaction rolls back); add a lease column
like extraction's if crash loops ever show up.
"""
import logging
from datetime import timedelta
from uuid import uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from swasthyoid.core import audit
from swasthyoid.safety import definitions, engine

log = logging.getLogger(__name__)
MAX_ATTEMPTS = 5                      # engineering defaults, not FRD values
BACKOFF = timedelta(minutes=1)


def enqueue(conn, *, document_id, patient_id):
    """Queue the check of one verified prescription. Call inside the M3 confirm transaction. A repeat does nothing."""
    conn.execute("INSERT INTO safety_check_jobs (document_id, patient_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                 [document_id, patient_id])


def _current(conn, patient_id, event_type):
    return conn.cursor(row_factory=dict_row).execute(
        """SELECT id, source_document_id, payload FROM events e
           WHERE patient_id = %s AND event_type = %s AND verification_status = 'document_verified'
             AND NOT EXISTS (SELECT 1 FROM events n WHERE n.supersedes = e.id)
           ORDER BY id""", [patient_id, event_type]).fetchall()


def _store(conn, job, attempt, outcome, reason=None, result=None, rules=(), catalog=None):
    result = result or {}
    alert_ids = []
    for a in result.get("alerts", []):
        alert_ids.append(uuid4())
        conn.execute("INSERT INTO safety_alerts (id, patient_id, rule_version_id, severity, source_document_id, "
                     "evidence_event_ids) VALUES (%s, %s, %s, %s, %s, %s)",
                     [alert_ids[-1], job["patient_id"], a["rule_version_id"], a["severity"], job["document_id"],
                      a["evidence"]])
    conn.execute(
        "INSERT INTO safety_checks (id, document_id, patient_id, attempt, outcome, reason, alert_ids, rule_version_ids, "
        "unrecognised, not_run, catalog) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        [uuid4(), job["document_id"], job["patient_id"], attempt, outcome, reason, alert_ids, [r[0] for r in rules],
         Jsonb(result.get("unrecognised", [])), Jsonb(result.get("not_run", [])),
         Jsonb(catalog.provenance()) if catalog is not None else None])
    return len(alert_ids)


def _check(conn, job, attempt, catalog):
    """Run the engine for one job and store its completed or blocked result. Raises on infrastructure failure."""
    rows = conn.cursor(row_factory=dict_row).execute(
        "SELECT id, rule_type, severity, definition FROM rules WHERE status = 'approved' AND rule_type = ANY(%s)",
        [list(definitions.ENGINE_TYPES)]).fetchall()
    try:
        rules = engine.load_rules(rows)
        meds = _current(conn, job["patient_id"], "medication")
        new = [(m["id"], m["payload"].get("name_as_written") or "") for m in meds
               if m["source_document_id"] == job["document_id"]]
        other = [(m["id"], m["payload"].get("name_as_written") or "") for m in meds
                 if m["source_document_id"] != job["document_id"]]
        allergies = [(a["id"], a["payload"].get("allergy_text") or "") for a in _current(conn, job["patient_id"], "allergy")]
        result = engine.evaluate(rules, new, other, allergies, catalog)
    except engine.Blocked as b:
        _store(conn, job, attempt, "blocked", b.args[0], {"not_run": [dict(x) for x in engine.NOT_RUN]}, catalog=catalog)
        return "blocked", b.args[0], 0
    return "completed", None, _store(conn, job, attempt, "completed", None, result, rules, catalog)


def _record(conn, job, action, result, reason=None):
    audit.append(conn, action=action, result=result, reason=reason, patient_id=job["patient_id"],
                 resource_type="document", resource_id=job["document_id"])


def _run_one(conn, catalog, max_attempts, backoff):
    with conn.transaction():
        job = conn.cursor(row_factory=dict_row).execute(
            """SELECT * FROM safety_check_jobs WHERE status = 'queued' AND next_attempt_at <= clock_timestamp()
               ORDER BY next_attempt_at, created_at, document_id LIMIT 1 FOR UPDATE SKIP LOCKED""").fetchone()
        if job is None:
            return False
        attempt = job["attempts"] + 1
        try:
            with conn.transaction():  # savepoint: an infrastructure failure keeps nothing of this attempt
                outcome, reason, count = _check(conn, job, attempt, catalog)
        except Exception as e:
            log.warning("safety check attempt failed: %s", type(e).__name__)  # code only, never data
            _store(conn, job, attempt, "error", "infrastructure_error")
            failed = attempt >= max_attempts
            conn.execute("UPDATE safety_check_jobs SET status = %s, attempts = %s, updated_at = clock_timestamp(), "
                         "next_attempt_at = clock_timestamp() + %s WHERE document_id = %s",
                         ["failed" if failed else "queued", attempt, backoff * 2 ** (attempt - 1), job["document_id"]])
            if failed:
                _record(conn, job, "safety.check.failed", "failed", "infrastructure_error")
            return True
        conn.execute("UPDATE safety_check_jobs SET status = 'done', attempts = %s, updated_at = clock_timestamp() "
                     "WHERE document_id = %s", [attempt, job["document_id"]])
        _record(conn, job, f"safety.check.{outcome}", "allow" if outcome == "completed" else "deny",
                reason or ("alerts_found" if count else "no_alerts"))
        return True


def run_due(conn, catalog, *, max_attempts=MAX_ATTEMPTS, backoff=BACKOFF, limit=100):
    """Run every due check once; returns how many jobs were tried. Safe to run from several workers."""
    done = 0
    while done < limit and _run_one(conn, catalog, max_attempts, backoff):
        done += 1
    return done


def requeue(conn):
    """Operator step after fixing a rule or the catalog: every blocked or failed job runs again. Returns the count."""
    with conn.transaction():
        n = conn.execute(
            """UPDATE safety_check_jobs j SET status = 'queued', attempts = 0, next_attempt_at = clock_timestamp(),
                      updated_at = clock_timestamp()
               WHERE j.status = 'failed' OR (j.status = 'done' AND NOT EXISTS (
                   SELECT 1 FROM safety_checks c WHERE c.document_id = j.document_id AND c.outcome = 'completed'))""").rowcount
        if n:
            audit.append(conn, action="safety.check.requeue", result="allow")
        return n


def for_patient(conn, patient_id):
    """Each verified prescription's check, newest first: the job and its latest result. Raw read: the route has passed
    RBAC -> C1 -> C2 (a doctor under a consent covering `safety`)."""
    return conn.cursor(row_factory=dict_row).execute(
        """SELECT j.document_id, j.status AS job_status, j.attempts, j.created_at, c.outcome, c.reason, c.alert_ids,
                  c.unrecognised, c.not_run, c.created_at AS checked_at
           FROM safety_check_jobs j
           LEFT JOIN LATERAL (SELECT * FROM safety_checks c WHERE c.document_id = j.document_id
                              ORDER BY c.created_at DESC, c.attempt DESC LIMIT 1) c ON true
           WHERE j.patient_id = %s ORDER BY j.created_at DESC, j.document_id""", [patient_id]).fetchall()


def status(row):
    """queued | retrying | completed | blocked | failed: infrastructure states never look like a clinical result."""
    if row["job_status"] == "failed":
        return "failed"
    if row["job_status"] == "queued":
        return "retrying" if row["outcome"] == "error" else "queued"
    return row["outcome"]
