"""Worker reliability for the extraction queue: claims, leases, fencing tokens, the hard
timeout, and recovery from crashes and hangs. Real database, real schema, real processes
(see test_extraction_integration for the setup). Design: docs/DECISIONS.md.
"""
import multiprocessing
import os
import subprocess
import sys
import threading
import time
from datetime import timedelta
from pathlib import Path

import psycopg
import pytest

from swasthyoid import db
from swasthyoid.capture import documents, extraction
from swasthyoid.tests import fake_engines
from swasthyoid.tests.test_extraction_integration import job, ocr, patient, prod, upload  # noqa: F401

REPO = Path(__file__).resolve().parents[2]
SHORT = timedelta(seconds=1)
TERMINAL = {"needs_review", "extraction_failed"}

# A separate worker process. argv: document id, lease seconds, what to do.
WORKER = """
import os, sys
from datetime import timedelta
from swasthyoid import db
from swasthyoid.capture import extraction
from swasthyoid.tests import fake_engines

doc_id, lease, mode = sys.argv[1], timedelta(seconds=float(sys.argv[2])), sys.argv[3]
conn = db.connect(autocommit=True)
if mode == "crash_after_claim":
    assert extraction.claim(conn, doc_id, lease=lease) is not None
    print("claimed", flush=True)
    os._exit(1)

def announce_then(engine):
    def run(pages, doc_type):
        print("started", flush=True)
        return engine(pages, doc_type)
    return run

if mode == "hang_in_process":
    extraction.extract(conn, doc_id, 1, announce_then(fake_engines.hang), lease=lease, hard_timeout=None)
if mode == "hang_in_child":
    print("started", flush=True)
    extraction.extract(conn, doc_id, 1, fake_engines.beating, lease=lease, hard_timeout=timedelta(minutes=5))
"""


def start_worker(doc_id, lease, mode):
    proc = subprocess.Popen([sys.executable, "-c", WORKER, doc_id, str(lease), mode], cwd=REPO,
                            stdout=subprocess.PIPE, text=True)
    watchdog = threading.Timer(60, proc.kill)  # never wait for ever on a child that says nothing
    watchdog.start()
    return proc, watchdog


def stop_worker(proc, watchdog):
    watchdog.cancel()
    proc.kill()
    proc.wait(timeout=30)
    proc.stdout.close()


def extractions(conn):
    return conn.execute("SELECT document_id::text, version, engine FROM extractions ORDER BY created_at").fetchall()


def claim_row(conn, doc_id):
    return conn.execute(
        "SELECT status, extraction_attempts, extraction_claim, next_extraction_at > clock_timestamp() "
        "FROM documents WHERE id = %s", [doc_id]).fetchone()


def expire_lease(conn, doc_id):
    conn.execute("UPDATE documents SET next_extraction_at = clock_timestamp() - interval '1 second' WHERE id = %s",
                 [doc_id])


def in_threads(*fns):
    out = [None] * len(fns)

    def run(i, fn):
        try:
            out[i] = ("ok", fn())
        except Exception as e:
            out[i] = ("err", e)

    threads = [threading.Thread(target=run, args=(i, fn)) for i, fn in enumerate(fns)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert not any(t.is_alive() for t in threads)
    return out


# ---- claiming

def test_workers_claim_different_documents_concurrently(prod):
    headers = patient(prod)
    ids = [upload(prod, headers) for _ in range(3)]
    start = threading.Barrier(5)

    def one_claim():
        with prod.connect() as conn:
            start.wait(10)
            return extraction.claim(conn)

    claims = [r[1] for r in in_threads(*[one_claim] * 5)]
    taken = [c for c in claims if c is not None]
    assert sorted(str(c["id"]) for c in taken) == sorted(ids)  # three documents, three different workers
    assert len({c["token"] for c in taken}) == 3 and claims.count(None) == 2
    assert {c["attempt"] for c in taken} == {1}


def test_workers_run_ocr_at_the_same_time(prod):
    headers = patient(prod)
    ids = [upload(prod, headers) for _ in range(3)]
    all_inside = threading.Barrier(3)

    def together(pages, doc_type):
        all_inside.wait(20)  # only passes if three workers are inside OCR at once
        return ocr(pages, doc_type)

    def worker():
        with prod.connect() as conn:
            return extraction.run_due(conn, together, limit=1)

    assert in_threads(*[worker] * 3) == [("ok", 1)] * 3
    with prod.connect() as conn:
        assert [job(conn, i)[0] for i in ids] == ["needs_review"] * 3
        assert sorted(e[0] for e in extractions(conn)) == sorted(ids)


def test_a_document_cannot_be_claimed_by_two_active_attempts(prod):
    doc_id = upload(prod, patient(prod))
    start = threading.Barrier(6)

    def one_claim():
        with prod.connect() as conn:
            start.wait(10)
            return extraction.claim(conn, doc_id)

    claims = [r[1] for r in in_threads(*[one_claim] * 6)]
    assert len([c for c in claims if c]) == 1
    with prod.connect() as conn:
        assert extraction.claim(conn, doc_id) is None and extraction.claim(conn) is None  # held: not due
        assert extraction.extract(conn, doc_id, 1, ocr) is False
        status, attempts, token, lease_running = claim_row(conn, doc_id)
        assert (status, attempts, lease_running) == ("extracting", 1, True)
        expire_lease(conn, doc_id)
        again = extraction.claim(conn, doc_id)
        assert again["attempt"] == 2 and again["token"] != token  # a new token for every attempt


def test_claim_needs_an_autocommit_connection(prod):
    with db.connect() as conn:
        with pytest.raises(ValueError, match="autocommit"):
            extraction.claim(conn)


# ---- crashes

def test_worker_crash_immediately_after_claim(prod):
    doc_id = upload(prod, patient(prod))
    proc, watchdog = start_worker(doc_id, 1.5, "crash_after_claim")
    try:
        assert proc.stdout.readline().strip() == "claimed"
        proc.wait(timeout=30)
    finally:
        stop_worker(proc, watchdog)
    with prod.connect() as conn:
        # the claim survived the crash: counted, and held until its lease ends
        assert claim_row(conn, doc_id)[:2] == ("extracting", 1)
        assert extraction.run_due(conn, ocr) == 0
        time.sleep(1.6)
        assert extraction.run_due(conn, ocr) == 1  # lease over: another worker recovers it
        assert job(conn, doc_id) == ("needs_review", 2, None, None)
        assert extractions(conn) == [(doc_id, 1, "fake-ocr")]


def test_worker_process_killed_during_ocr(prod):
    doc_id = upload(prod, patient(prod))
    proc, watchdog = start_worker(doc_id, 1.5, "hang_in_process")
    try:
        assert proc.stdout.readline().strip() == "started"
        with prod.connect() as conn:
            assert claim_row(conn, doc_id)[:2] == ("extracting", 1)
            assert extraction.run_due(conn, ocr) == 0  # it is not blocked: the document is simply not due
    finally:
        stop_worker(proc, watchdog)
    with prod.connect() as conn:
        time.sleep(1.6)
        assert extraction.run_due(conn, ocr) == 1
        assert job(conn, doc_id) == ("needs_review", 2, None, None)
        assert extractions(conn) == [(doc_id, 1, "fake-ocr")]  # once, version 1: no duplicate, no gap


def test_ocr_child_process_dies_and_the_attempt_is_counted(prod):
    doc_id = upload(prod, patient(prod))
    with prod.connect() as conn:
        options = dict(hard_timeout=timedelta(seconds=30), backoff=timedelta(0))
        assert extraction.run_due(conn, fake_engines.die, limit=1, **options) == 1
        assert job(conn, doc_id)[:3] == ("extracting", 1, "WorkerDied")
        assert extraction.run_due(conn, fake_engines.die, **options) == 2
        assert job(conn, doc_id) == ("extraction_failed", 3, "WorkerDied", None)
        assert extractions(conn) == []


def test_engine_error_in_the_child_is_reported_by_type_only(prod):
    doc_id = upload(prod, patient(prod))
    with prod.connect() as conn:
        extraction.run_due(conn, fake_engines.boom, hard_timeout=timedelta(seconds=30), max_attempts=1)
        assert job(conn, doc_id) == ("extraction_failed", 1, "RuntimeError", None)
        assert "synthetic patient text" not in str(conn.execute("SELECT * FROM documents").fetchall())


# ---- hangs and the hard timeout

def test_worker_hanging_beyond_the_hard_timeout_is_killed(prod):
    headers = patient(prod)
    hung, fine = upload(prod, headers), upload(prod, headers)
    with prod.connect() as conn:
        started = time.monotonic()
        ran = extraction.run_due(conn, fake_engines.hang, limit=1, max_attempts=1,
                                 hard_timeout=timedelta(seconds=2), heartbeat=timedelta(seconds=0.5))
        assert ran == 1 and time.monotonic() - started < 30
        assert job(conn, hung) == ("extraction_failed", 1, "HardTimeout", None)
        assert multiprocessing.active_children() == []  # the hung OCR process is gone
        # the worker itself survived and carries on with the next document
        assert extraction.run_due(conn, fake_engines.good, hard_timeout=timedelta(seconds=30)) == 1
        assert job(conn, fine)[0] == "needs_review"


def test_heartbeat_keeps_a_long_job_and_nobody_else_can_take_it(prod, monkeypatch):
    monkeypatch.setenv("FAKE_ENGINE_SECONDS", "4")
    doc_id = upload(prod, patient(prod))
    stolen = []

    def rival():  # tries to take the document while the first worker is still on it
        with prod.connect() as conn:
            for _ in range(12):
                time.sleep(0.4)
                stolen.append(extraction.claim(conn, doc_id, lease=timedelta(seconds=1.5)))

    watcher = threading.Thread(target=rival)
    watcher.start()
    try:
        with prod.connect() as conn:
            # the job outlasts its 1.5 s lease several times over; only the heartbeat keeps it
            extraction.run_due(conn, fake_engines.slow, lease=timedelta(seconds=1.5),
                               heartbeat=timedelta(seconds=0.3), hard_timeout=timedelta(seconds=60))
            assert job(conn, doc_id) == ("needs_review", 1, None, None)
    finally:
        watcher.join(30)
    assert stolen == [None] * 12


def test_orphaned_ocr_child_stops_when_its_worker_is_killed(prod, monkeypatch, tmp_path):
    beat = tmp_path / "beat"
    monkeypatch.setenv("FAKE_ENGINE_BEAT_FILE", str(beat))
    doc_id = upload(prod, patient(prod))
    proc, watchdog = start_worker(doc_id, 300, "hang_in_child")
    try:
        assert proc.stdout.readline().strip() == "started"
        for _ in range(100):  # wait for the OCR child to be running
            if beat.exists() and beat.stat().st_size > 2:
                break
            time.sleep(0.2)
        else:
            pytest.fail("the OCR child never started")
    finally:
        stop_worker(proc, watchdog)
    for _ in range(50):  # the child notices its worker is gone and exits
        size = beat.stat().st_size
        time.sleep(1)
        if beat.stat().st_size == size:
            break
    else:
        pytest.fail("the OCR child outlived its worker")


# ---- lease expiry and stale results

def test_expired_lease_is_recovered_and_the_old_worker_cannot_commit(prod):
    doc_id = upload(prod, patient(prod))

    def winner(pages, doc_type):
        return {"engine": "winner", "raw_text": "", "fields": {}}

    def late(pages, doc_type):
        # while this worker is still busy its lease runs out, and another worker finishes the job
        with prod.connect() as other:
            expire_lease(other, doc_id)
            assert extraction.run_due(other, winner) == 1
        return {"engine": "late", "raw_text": "", "fields": {}}

    with prod.connect() as conn:
        assert extraction.extract(conn, doc_id, 1, late) is True
        assert job(conn, doc_id) == ("needs_review", 2, None, None)
        assert extractions(conn) == [(doc_id, 1, "winner")]  # the late result was thrown away
        assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 0


def test_stale_worker_cannot_commit_even_if_nobody_else_took_the_document(prod):
    doc_id = upload(prod, patient(prod))

    def outlives_its_lease(pages, doc_type):
        with prod.connect() as other:
            expire_lease(other, doc_id)
        return ocr(pages, doc_type)

    with prod.connect() as conn:
        extraction.extract(conn, doc_id, 1, outlives_its_lease)
        assert extractions(conn) == []  # an expired lease is enough to refuse the result
        assert claim_row(conn, doc_id)[:2] == ("extracting", 1)
        assert extraction.run_due(conn, ocr) == 1  # and the document is due again
        assert job(conn, doc_id) == ("needs_review", 2, None, None)
        assert extractions(conn) == [(doc_id, 1, "fake-ocr")]


def test_stale_worker_cannot_record_a_failure_over_a_finished_document(prod):
    doc_id = upload(prod, patient(prod))

    def loses_then_fails(pages, doc_type):
        with prod.connect() as other:
            expire_lease(other, doc_id)
            extraction.run_due(other, ocr)
        raise RuntimeError("too late to matter")

    with prod.connect() as conn:
        extraction.extract(conn, doc_id, 1, loses_then_fails)
        assert job(conn, doc_id) == ("needs_review", 2, None, None)  # untouched by the stale failure


def test_heartbeat_cannot_revive_an_expired_lease(prod):
    doc_id = upload(prod, patient(prod))
    with prod.connect() as conn:
        mine = extraction.claim(conn, doc_id)
        assert extraction._renew(conn, mine, extraction.LEASE) is True
        expire_lease(conn, doc_id)
        assert extraction._renew(conn, mine, extraction.LEASE) is False
        assert claim_row(conn, doc_id)[3] is False


def test_stale_worker_cannot_record_a_failure_after_its_lease_ran_out(prod):
    """Even with no other worker involved: the failure write is fenced by the lease too."""
    for max_attempts in (1, 3):  # the last attempt, and an earlier one
        doc_id = upload(prod, patient(prod, f"+880170000010{max_attempts}"))

        def expires_then_fails(pages, doc_type):
            with prod.connect() as other:
                expire_lease(other, doc_id)
            raise RuntimeError("late failure")

        with prod.connect() as conn:
            extraction.extract(conn, doc_id, 1, expires_then_fails, max_attempts=max_attempts)
            status, attempts, token, lease_running = claim_row(conn, doc_id)
            # nothing was written: still claimed, still extracting, no error recorded, due again
            assert (status, attempts, lease_running) == ("extracting", 1, False) and token is not None
            assert job(conn, doc_id)[2] is None
            if max_attempts == 3:
                assert extraction.run_due(conn, ocr) == 1
                assert job(conn, doc_id) == ("needs_review", 2, None, None)
            else:
                assert extraction.claim(conn, max_attempts=1) is None  # the next look closes it
                assert job(conn, doc_id) == ("extraction_failed", 1, "LeaseExpired", None)


# ---- settings that must be refused

def test_in_process_ocr_is_refused_outside_tests(prod, monkeypatch):
    doc_id = upload(prod, patient(prod))
    with prod.connect() as conn:
        for env in ("production", "development", None):
            monkeypatch.delenv("APP_ENV", raising=False) if env is None else monkeypatch.setenv("APP_ENV", env)
            with pytest.raises(RuntimeError, match="APP_ENV=test"):
                extraction.run_due(conn, ocr, hard_timeout=None)
            with pytest.raises(RuntimeError, match="APP_ENV=test"):
                extraction.extract(conn, doc_id, 1, ocr, hard_timeout=None)
            with pytest.raises(RuntimeError, match="APP_ENV=test"):
                extraction.run_due(conn, ocr)  # the fixture left HARD_TIMEOUT at None
        assert job(conn, doc_id) == ("uploaded", 0, None, None)  # refused before anything was claimed
        # the child-process mode needs no special environment
        assert extraction.run_due(conn, fake_engines.good, hard_timeout=timedelta(minutes=10)) == 1
        assert job(conn, doc_id)[0] == "needs_review"


def test_heartbeat_must_be_shorter_than_the_lease(prod):
    doc_id = upload(prod, patient(prod))
    with prod.connect() as conn:
        for heartbeat in (timedelta(seconds=60), timedelta(seconds=61)):
            with pytest.raises(ValueError, match="heartbeat"):
                extraction.run_due(conn, fake_engines.good, lease=timedelta(seconds=60), heartbeat=heartbeat,
                                   hard_timeout=timedelta(minutes=10))
        assert job(conn, doc_id) == ("uploaded", 0, None, None)
        assert extraction.HEARTBEAT < extraction.LEASE  # the shipped settings obey the rule


def test_an_extracting_document_always_has_a_due_time(prod):
    doc_id = upload(prod, patient(prod))
    with prod.connect() as conn:
        with pytest.raises(psycopg.errors.CheckViolation):  # the database refuses a stranded row
            conn.execute("UPDATE documents SET status = 'extracting' WHERE id = %s", [doc_id])
        documents.set_status(conn, doc_id, "extracting")  # the state-machine call makes it due at once
        assert job(conn, doc_id) == ("extracting", 0, None, False)
        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute("UPDATE documents SET next_extraction_at = NULL WHERE id = %s", [doc_id])
        assert extraction.run_due(conn, ocr) == 1
        assert job(conn, doc_id)[0] == "needs_review"


# ---- maximum attempts and bounded time

def test_three_attempts_that_never_report_back_end_in_extraction_failed(prod):
    doc_id = upload(prod, patient(prod))
    with prod.connect() as conn:
        for attempt in (1, 2, 3):
            assert extraction.claim(conn, lease=timedelta(seconds=0.2))["attempt"] == attempt  # then "crashes"
            time.sleep(0.3)
        assert extraction.claim(conn) is None  # the fourth look closes it instead of trying again
        assert job(conn, doc_id) == ("extraction_failed", 3, "LeaseExpired", None)
        assert claim_row(conn, doc_id)[2] is None and extractions(conn) == []


def test_no_document_stays_in_extracting_whatever_goes_wrong(prod):
    headers = patient(prod)
    ids = [upload(prod, headers) for _ in range(6)]
    lease, backoff = timedelta(seconds=0.4), timedelta(seconds=0.1)
    options = dict(lease=lease, backoff=backoff)
    doomed = set(ids[:2])  # these fail every time

    def flaky(pages, doc_type):
        if doomed & {str(r[0]) for r in db_ids()}:
            raise RuntimeError("down")
        return ocr(pages, doc_type)

    current = []

    def db_ids():
        return current

    # worst case per document: every attempt uses its whole lease, then waits out its backoff
    bound = extraction.MAX_ATTEMPTS * (lease + backoff * 4).total_seconds() + 5
    started = time.monotonic()
    with prod.connect() as conn:
        for i in ids[2:4]:  # two documents lose a worker straight after the claim
            extraction.claim(conn, i, lease=lease)
        mine = extraction.claim(conn, ids[4], lease=lease)  # one loses a worker twice
        time.sleep(0.5)
        extraction.claim(conn, ids[4], lease=lease)
        assert mine["attempt"] == 1

        while time.monotonic() - started < bound:
            job_ = extraction.claim(conn, **{"lease": lease})
            if job_ is None:
                if all(job(conn, i)[0] in TERMINAL for i in ids):
                    break
                time.sleep(0.1)
                continue
            current[:] = [(job_["id"],)]
            extraction._attempt(conn, job_, flaky, None, extraction._settings(options))
        elapsed = time.monotonic() - started
        states = {i: job(conn, i)[0] for i in ids}
        assert set(states.values()) <= TERMINAL, states  # nothing is left in uploaded or extracting
        assert elapsed < bound
        assert [states[i] for i in ids[:2]] == ["extraction_failed"] * 2
        assert [states[i] for i in ids[2:]] == ["needs_review"] * 4
        assert conn.execute("SELECT count(*) FROM documents WHERE extraction_claim IS NOT NULL").fetchone()[0] == 0
        assert sorted(e[:2] for e in extractions(conn)) == sorted((i, 1) for i in ids[2:])
        assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 0


# ---- database backstop

def test_worker_connection_has_database_timeouts(prod):
    with db.connect_worker() as conn:
        assert conn.autocommit is True
        shown = {name: conn.execute(f"SHOW {name}").fetchone()[0]
                 for name in ("statement_timeout", "lock_timeout", "idle_in_transaction_session_timeout")}
        assert shown == {"statement_timeout": "1min", "lock_timeout": "10s",
                         "idle_in_transaction_session_timeout": "1min"}
        assert extraction.claim(conn) is None
