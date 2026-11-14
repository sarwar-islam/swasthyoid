"""The lifetime attempt budget (owner decision 2026-11-14: at most 5 ACTUAL OCR executions per document, one counter
for the first run, automatic retries, patient retries and crash recovery). No database: a recording connection shows
the decisions and the statements; the PostgreSQL behavior is tested in test_manual_entry_retry.py (CI). Synthetic only."""
import inspect
import re
from datetime import timedelta
from pathlib import Path

import pytest

from swasthyoid.capture import extraction

ROOT = Path(__file__).resolve().parents[1]
JOB = {"id": "doc-1", "token": "token-1", "attempt": 1, "executions": 0}


class Result:
    def __init__(self, row):
        self.row, self.rowcount = row, 0 if row is None else 1

    def fetchone(self):
        return self.row


class Conn:
    """Answers each execute() with the next prepared row and records (sql, params)."""

    def __init__(self, *rows):
        self.rows, self.calls = list(rows), []

    def execute(self, sql, params=None):
        self.calls.append((" ".join(sql.split()), params))
        return Result(self.rows.pop(0) if self.rows else None)


def test_the_lifetime_limit_is_exactly_five_and_the_old_caps_are_gone():
    assert extraction.MAX_LIFETIME_ATTEMPTS == 5
    assert extraction.MAX_ATTEMPTS <= extraction.MAX_LIFETIME_ATTEMPTS  # a run can never be larger than the budget
    assert not hasattr(extraction, "MAX_RETRIES") and not hasattr(extraction, "MAX_TOTAL_ATTEMPTS")


def test_beginning_an_execution_is_one_guarded_update_that_checks_the_fence_the_lease_and_the_limit():
    conn = Conn((3,))
    assert extraction._begin_execution(conn, JOB, timedelta(minutes=5)) == 3
    (sql, params), = conn.calls
    assert sql.startswith("UPDATE documents SET extraction_lifetime_attempts = extraction_lifetime_attempts + 1")
    assert "extraction_claim = %s" in sql and "next_extraction_at > clock_timestamp()" in sql  # fence and lease
    assert "extraction_lifetime_attempts < %s" in sql and sql.endswith("RETURNING extraction_lifetime_attempts")
    assert params == [timedelta(minutes=5), "doc-1", "token-1", 5]  # the limit is the constant, bound as a parameter


def test_a_claim_that_was_lost_is_lease_lost_not_an_exhausted_budget():
    conn = Conn(None, None)  # the update matched nothing, and the claim is not ours any more
    with pytest.raises(extraction.LeaseLost):
        extraction._begin_execution(conn, JOB, timedelta(minutes=5))


def test_a_claim_we_still_hold_with_no_attempt_left_is_an_exhausted_budget():
    conn = Conn(None, (1,))  # the update matched nothing, but the claim is ours and live
    with pytest.raises(extraction.AttemptFailed) as refused:
        extraction._begin_execution(conn, JOB, timedelta(minutes=5))
    assert refused.value.args == ("AttemptBudgetExhausted",)
    assert len(conn.calls) == 2  # nothing was changed


def failed(job, reason, *, max_attempts=3, backoff=timedelta(minutes=1)):
    conn = Conn()
    extraction._fail(conn, job, reason, max_attempts, backoff)
    (_, params), = conn.calls
    status, error, final, wait = params[:4]
    return status, error, final, wait


def test_a_transient_failure_retries_with_doubling_backoff_and_the_run_ends_at_its_third_claim():
    assert failed({**JOB, "attempt": 1}, "HardTimeout") == ("extracting", "HardTimeout", False, timedelta(minutes=1))
    assert failed({**JOB, "attempt": 2}, "WorkerDied") == ("extracting", "WorkerDied", False, timedelta(minutes=2))
    status, _, final, _ = failed({**JOB, "attempt": 3}, "RuntimeError")
    assert (status, final) == ("extraction_failed", True)


@pytest.mark.parametrize("code", sorted(extraction.PERMANENT_CODES))
def test_a_permanent_failure_closes_the_document_at_once(code):
    status, error, final, _ = failed({**JOB, "attempt": 1}, code)
    assert (status, error, final) == ("extraction_failed", code, True)


@pytest.mark.parametrize("code", ["HardTimeout", "WorkerDied", "LeaseExpired", "engine_error", "engine_unavailable",
                                  "RuntimeError", "OperationalError"])
def test_infrastructure_and_unknown_failures_are_retryable(code):
    assert code not in extraction.PERMANENT_CODES and failed({**JOB, "attempt": 1}, code)[2] is False


def test_the_fifth_execution_closes_the_document_whatever_the_failure_was():
    status, _, final, _ = failed({**JOB, "attempt": 1, "executions": 5}, "HardTimeout")
    assert (status, final) == ("extraction_failed", True)  # nothing is left to retry with
    assert failed({**JOB, "attempt": 1, "executions": 4}, "HardTimeout")[2] is False  # one is left


def test_the_permanent_codes_are_exactly_the_documented_ones():
    assert extraction.PERMANENT_CODES == {"model_integrity_failed", "malformed_output", "ImageRejected", "Corrupted",
                                          "AttemptBudgetExhausted"}


def test_nothing_in_the_code_ever_lowers_or_sets_the_lifetime_counter():
    """Only `... = extraction_lifetime_attempts + 1` may change it; a retry, a restart or a recovery cannot reset it."""
    assignment = re.compile(r"extraction_lifetime_attempts\s*=(?!=)\s*+(?!extraction_lifetime_attempts \+ 1)")
    for path in ROOT.rglob("*.py"):
        if "tests" not in path.relative_to(ROOT).parts:
            assert not assignment.search(path.read_text(encoding="utf-8")), path.name
    assert assignment.search("SET extraction_lifetime_attempts = 0")  # the check itself works
    assert not assignment.search("SET extraction_lifetime_attempts = extraction_lifetime_attempts + 1")
    for function in (extraction.requeue, extraction.retry_extraction, extraction.claim, extraction.manual_entry,
                     extraction.start_manual_entry):
        assert "extraction_lifetime_attempts =" not in inspect.getsource(function), function.__name__


def test_the_schema_adds_the_column_without_a_default_that_a_rerun_could_reset():
    schema = (ROOT / "capture" / "schema.sql").read_text(encoding="utf-8")
    assert "extraction_lifetime_attempts int NOT NULL DEFAULT 0" in schema and "extraction_lifetime_attempts >= 0" in schema
    # the backfill sits inside the IF NOT EXISTS block, so applying the schema again never changes a counter
    block = schema[schema.index("DO $$", schema.index("Lifetime attempt budget")):]
    assert block.index("IF NOT EXISTS") < block.index("ADD COLUMN") < block.index("UPDATE documents SET extraction_lifetime_attempts")
    assert block.index("UPDATE documents SET extraction_lifetime_attempts") < block.index("END IF")


def test_the_worker_checks_for_the_column_but_never_creates_it():
    from swasthyoid.workers import extract as runner
    assert "extraction_lifetime_attempts" in runner.REQUIRED_SCHEMA["documents"]
    source = inspect.getsource(runner)
    assert "apply_schema" not in source and "ALTER TABLE" not in source  # no migration from the worker
