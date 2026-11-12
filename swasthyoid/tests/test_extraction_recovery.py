"""How the extraction queue behaves when workers race, crash or hang. Real database, real
schema, real processes (see test_extraction_integration for the setup).

Some tests here pin a CURRENT LIMITATION, described in docs/DECISIONS.md ("Extraction worker
recovery"). When the fix proposed there is built, those assertions are meant to change.
"""
import subprocess
import sys
import threading
import time
from pathlib import Path

import psycopg
import pytest

from swasthyoid.capture import extraction
from swasthyoid.tests.test_extraction_integration import job, ocr, patient, prod, upload  # noqa: F401

REPO = Path(__file__).resolve().parents[2]
HANGING_WORKER = """
import sys, time
from swasthyoid import db
from swasthyoid.capture import extraction

def engine(pages, doc_type):
    print("started", flush=True)
    time.sleep(600)

extraction.extract(db.connect(autocommit=True), sys.argv[1], 1, engine)
"""


def impatient(prod):
    """A worker connection that gives up on a locked row instead of waiting for ever."""
    conn = prod.connect()
    conn.execute("SET lock_timeout = '300ms'")
    return conn


def extractions(conn):
    return conn.execute("SELECT document_id::text, version FROM extractions ORDER BY created_at").fetchall()


def test_killed_worker_leaves_the_document_recoverable_and_extracted_once(prod):
    doc_id = upload(prod, patient(prod))
    worker = subprocess.Popen([sys.executable, "-c", HANGING_WORKER, doc_id], cwd=REPO, stdout=subprocess.PIPE, text=True)
    watchdog = threading.Timer(60, worker.kill)  # if the child never reports, do not wait for ever
    watchdog.start()
    try:
        assert worker.stdout.readline().strip() == "started"  # it holds the document now
        with impatient(prod) as other:
            # nothing the worker did is visible yet: no status change, no attempt counted
            assert job(other, doc_id) == ("uploaded", 0, None, None)
            with pytest.raises(psycopg.errors.LockNotAvailable):
                extraction.run_due(other, ocr)
    finally:
        watchdog.cancel()
        worker.kill()  # the process dies without any cleanup
        worker.wait(timeout=30)
        worker.stdout.close()

    with impatient(prod) as other:
        for _ in range(40):  # the database notices the dead client and rolls its work back
            try:
                assert extraction.run_due(other, ocr) == 1
                break
            except psycopg.errors.LockNotAvailable:
                time.sleep(0.25)
        else:
            pytest.fail("the dead worker's lock was never released")
        assert job(other, doc_id) == ("needs_review", 0, None, None)
        assert extractions(other) == [(doc_id, 1)]  # once, at version 1: no duplicate, no gap
        assert extraction.run_due(other, ocr) == 0


def test_lost_connection_mid_extraction_rolls_back_and_is_retried_once(prod):
    doc_id = upload(prod, patient(prod))
    conn = prod.connect()
    pid = conn.execute("SELECT pg_backend_pid()").fetchone()[0]

    def engine_then_connection_dies(pages, doc_type):
        with prod.connect() as admin:
            admin.execute("SELECT pg_terminate_backend(%s)", [pid])
        return ocr(pages, doc_type)

    try:
        with pytest.raises(psycopg.OperationalError):
            extraction.extract(conn, doc_id, 1, engine_then_connection_dies)
    finally:
        conn.close()
    with prod.connect() as other:
        assert job(other, doc_id) == ("uploaded", 0, None, None) and extractions(other) == []
        assert extraction.run_due(other, ocr) == 1
        assert extractions(other) == [(doc_id, 1)]


def test_limitation_a_crashing_document_is_retried_without_end(prod):
    """CURRENT LIMITATION: the attempt counter is part of the transaction that a crash rolls
    back, so a document that always kills its worker never reaches extraction_failed."""
    doc_id = upload(prod, patient(prod))
    for _ in range(extraction.MAX_ATTEMPTS + 2):
        conn = prod.connect()
        pid = conn.execute("SELECT pg_backend_pid()").fetchone()[0]

        def poison(pages, doc_type):
            with prod.connect() as admin:
                admin.execute("SELECT pg_terminate_backend(%s)", [pid])
            return ocr(pages, doc_type)

        try:
            with pytest.raises(psycopg.OperationalError):
                extraction.run_due(conn, poison)
        finally:
            conn.close()
    with prod.connect() as other:
        assert job(other, doc_id) == ("uploaded", 0, None, None)  # five crashes, none counted
        assert extractions(other) == []


def test_limitation_a_hung_worker_blocks_the_whole_queue_but_never_duplicates(prod):
    """CURRENT LIMITATION: every worker picks the oldest due document and waits for its lock,
    so one worker stuck on it stops all the others, even from documents nobody is working on."""
    headers = patient(prod)
    first, second = upload(prod, headers), upload(prod, headers)
    holding, release, calls = threading.Event(), threading.Event(), []

    def slow(pages, doc_type):
        calls.append("slow")
        holding.set()
        release.wait(30)
        return ocr(pages, doc_type)

    def counted(pages, doc_type):
        calls.append("other")
        return ocr(pages, doc_type)

    def stuck_worker():
        with prod.connect() as conn:
            extraction.extract(conn, first, 1, slow)

    stuck = threading.Thread(target=stuck_worker)
    stuck.start()
    try:
        assert holding.wait(10)
        with impatient(prod) as other:
            with pytest.raises(psycopg.errors.LockNotAvailable):
                extraction.run_due(other, counted)  # it queues behind `first` and never reaches `second`
            assert job(other, second)[0] == "uploaded" and calls == ["slow"]
    finally:
        release.set()  # whatever happened above, let the stuck worker finish and close its connection
        stuck.join(timeout=30)
    assert not stuck.is_alive()
    with impatient(prod) as other:
        # the worker that lost the race for `first` finds it done and simply moves on
        assert extraction.run_due(other, counted) == 1
        assert [job(other, d)[0] for d in (first, second)] == ["needs_review", "needs_review"]
        assert sorted(extractions(other)) == sorted([(first, 1), (second, 1)])
        assert calls == ["slow", "other"]  # each document was read exactly once


def test_a_worker_that_loses_the_race_stops_and_a_later_run_finds_nothing_left(prod):
    headers = patient(prod)
    ids = [upload(prod, headers) for _ in range(3)]
    barrier, ran = threading.Barrier(3), []

    def worker():
        with prod.connect() as conn:
            barrier.wait()
            ran.append(extraction.run_due(conn, ocr))

    threads = [threading.Thread(target=worker) for _ in range(3)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    with prod.connect() as conn:
        # jobs are not handed to a worker: the table is the queue, so whatever a losing worker
        # did not do is still due and the winner (or the next run) takes it
        assert sum(ran) == 3 and sorted(extractions(conn)) == sorted((i, 1) for i in ids)
        assert extraction.run_due(conn, ocr) == 0
