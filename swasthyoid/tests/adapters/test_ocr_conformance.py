"""Infrastructure conformance for OCR adapters (M2 step 4A; D17). Real database, real schema,
real probe and OCR child processes, test-only interface version 0 fakes. Model-output
conformance tests are out of scope until the owner's model specification (D18)."""
import hashlib
import json
import logging
import os
import subprocess
import sys
import time
import uuid
from datetime import timedelta
from pathlib import Path

import psycopg
import pytest

from swasthyoid import db
from swasthyoid.capture import extraction, ocr
from swasthyoid.tests.adapters import fake_adapters
from swasthyoid.tests.test_extraction_integration import V1, job, patient, prod, upload  # noqa: F401

FAKE = "swasthyoid.tests.adapters.fake_adapters:"
EMPTY_SHA = hashlib.sha256(b"").hexdigest()
REPO = Path(__file__).resolve().parents[3]
CHILD = dict(hard_timeout=timedelta(seconds=60), heartbeat=timedelta(seconds=1), max_attempts=1)


@pytest.fixture
def c(prod, monkeypatch, tmp_path, caplog):  # noqa: F811
    for name in ("OCR_ADAPTER", "OCR_ADAPTERS_APPROVED", "OCR_TEST_BLOCK_NETWORK"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("FAKE_ADAPTER_LOG", str(tmp_path / "adapter.log"))
    caplog.set_level(logging.WARNING)
    prod.log = tmp_path / "adapter.log"
    prod.caplog = caplog
    prod.headers = patient(prod)
    return prod


def events(c):
    return c.log.read_text(encoding="utf-8").split() if c.log.exists() else []


def documents_row(conn, doc_id):
    return conn.execute("SELECT * FROM documents WHERE id = %s", [doc_id]).fetchone()


def extraction_rows(conn):
    return conn.execute(
        "SELECT engine, engine_id, model_version, model_checksum, adapter_interface_version, adapter_version, "
        "fields::text, raw_text FROM extractions").fetchall()


def everything(conn):
    """All stored text, for asserting what must never be stored."""
    return str([conn.execute("SELECT * FROM documents").fetchall(), conn.execute("SELECT * FROM extractions").fetchall(),
                conn.execute("SELECT * FROM audit_logs").fetchall()])


def logged(c):
    return "\n".join(r.getMessage() for r in c.caplog.records)


def use(monkeypatch, factory):
    monkeypatch.setenv("OCR_ADAPTER", FAKE + factory)


# ---- availability before any claim

def test_no_adapter_configured_claims_nothing_and_writes_nothing(c):
    doc_id = upload(c, c.headers)
    with c.connect() as conn:
        before = documents_row(conn, doc_id)
        assert extraction.run_due(conn, **CHILD) == 0
        assert extraction.extract(conn, doc_id, 1, **CHILD) is False
        assert documents_row(conn, doc_id) == before  # still uploaded, 0 attempts, untouched
        assert job(conn, doc_id) == ("uploaded", 0, None, None)
        assert extraction_rows(conn) == []
    assert "code=engine_unavailable stage=probe" in logged(c)


def test_a_probe_timeout_is_logged_only_and_writes_nothing(c, monkeypatch):
    use(monkeypatch, "hangs_identity")
    doc_id = upload(c, c.headers)
    with c.connect() as conn:
        before = documents_row(conn, doc_id)
        assert extraction.run_due(conn, availability_timeout=timedelta(seconds=4), **CHILD) == 0
        assert documents_row(conn, doc_id) == before
        assert extraction_rows(conn) == []
    text = logged(c)
    assert "code=availability_timeout stage=probe" in text and fake_adapters.SECRET not in text


def test_outside_test_mode_no_adapter_is_available(c, monkeypatch):
    use(monkeypatch, "not_test_only")
    doc_id = upload(c, c.headers)
    monkeypatch.delenv("APP_ENV")  # the confirmation alone is not test mode
    with c.connect() as conn:
        assert extraction.run_due(conn, **CHILD) == 0
        assert job(conn, doc_id) == ("uploaded", 0, None, None)
    assert events(c) == []  # refused before any adapter code ran


# ---- a good adapter through the real pipeline

def test_good_adapter_end_to_end_records_identity_and_stores_no_items(c, monkeypatch):
    use(monkeypatch, "good")
    doc_id = upload(c, c.headers)
    with c.connect() as conn:
        assert extraction.run_due(conn, **CHILD) == 1
        assert job(conn, doc_id) == ("needs_review", 1, None, None)
        assert extraction_rows(conn) == [("fake-v0", "fake-v0", "0.0-test", EMPTY_SHA, 0, "fake-1", "{}",
                                          "synthetic line 1")]
        stored = everything(conn)
        assert "0.9" not in str(extraction_rows(conn)) and "[0, 0]" not in stored  # no confidence, no position
    assert events(c) == ["identity", "identity", "prepare", "read", "release"]  # probe, then the attempt
    assert "synthetic line" not in logged(c)
    body = c.http.get(f"{V1}/documents/{doc_id}/extraction", headers=c.headers).json()
    assert (body["status"], body["extraction"]["engine"], body["extraction"]["raw_text"]) == \
        ("needs_review", "fake-v0", "synthetic line 1")


# ---- failures inside a claimed attempt are codes, never messages

@pytest.mark.parametrize("factory, expected", [
    ("boom", "engine_error"), ("malformed", "malformed_output"), ("dies", "WorkerDied"),
    ("wrong_identity_in_result", "malformed_output"),
])
def test_attempt_failures_store_codes_only(c, monkeypatch, factory, expected):
    use(monkeypatch, factory)
    doc_id = upload(c, c.headers)
    with c.connect() as conn:
        assert extraction.run_due(conn, **CHILD) == 1
        assert job(conn, doc_id) == ("extraction_failed", 1, expected, None)
        assert extraction_rows(conn) == []
        assert fake_adapters.SECRET not in everything(conn)
    assert fake_adapters.SECRET not in logged(c)


def test_a_failing_adapter_has_no_fallback(c, monkeypatch):
    use(monkeypatch, "boom")
    doc_id = upload(c, c.headers)
    with c.connect() as conn:
        assert extraction.run_due(conn, limit=1, **{**CHILD, "max_attempts": 3}) == 1
        assert job(conn, doc_id)[:3] == ("extracting", 1, "engine_error")
        assert extraction_rows(conn) == []
    # probe, then the attempt: only the configured adapter ran, and no other adapter's read()
    assert events(c) == ["identity", "identity", "prepare", "release"]


def test_a_hanging_adapter_is_killed_at_the_hard_timeout(c, monkeypatch):
    use(monkeypatch, "hangs_reading")
    doc_id = upload(c, c.headers)
    with c.connect() as conn:
        started = time.monotonic()
        assert extraction.run_due(conn, **{**CHILD, "hard_timeout": timedelta(seconds=3)}) == 1
        assert time.monotonic() - started < 60
        assert job(conn, doc_id) == ("extraction_failed", 1, "HardTimeout", None)


def test_network_guard_fails_the_adapter_closed(c, monkeypatch):
    use(monkeypatch, "network")
    monkeypatch.setenv("OCR_TEST_BLOCK_NETWORK", "1")
    doc_id = upload(c, c.headers)
    with c.connect() as conn:
        extraction.run_due(conn, **CHILD)
        assert job(conn, doc_id) == ("extraction_failed", 1, "engine_error", None)
        assert extraction_rows(conn) == []
    assert "network:blocked by the test network guard" in c.log.read_text(encoding="utf-8")


def claimed(c, conn, monkeypatch, factory, options=CHILD):
    """Probe and claim under test mode, so a test can change the world before the attempt."""
    use(monkeypatch, factory)
    doc_id = upload(c, c.headers)
    o = extraction._settings(dict(options))
    engine, config = extraction._engine(None, o)
    work = extraction.claim(conn, lease=o["lease"], max_attempts=o["max_attempts"])
    return doc_id, o, engine, config, work


def test_version_0_is_refused_by_the_ocr_child_outside_test_mode(c, monkeypatch):
    with c.connect() as conn:
        doc_id, o, engine, config, work = claimed(c, conn, monkeypatch, "good")
        monkeypatch.delenv("APP_ENV")  # the child no longer sees test mode
        extraction._attempt(conn, work, engine, None, o, config)
        assert job(conn, doc_id) == ("extraction_failed", 1, "engine_unavailable", None)
        assert extraction_rows(conn) == []
    assert events(c) == ["identity"]  # the probe only: the child refused before adapter code


def test_version_0_is_never_stored_outside_test_mode(c, monkeypatch):
    with c.connect() as conn:
        doc_id, o, engine, config, work = claimed(c, conn, monkeypatch, "good",
                                                  {**CHILD, "hard_timeout": None})
        result = fake_adapters.Good().read([{"page_number": 1}])
        monkeypatch.delenv("APP_ENV")
        extraction._attempt(conn, work, lambda document, doc_type: result, None, o, config)
        assert job(conn, doc_id) == ("extraction_failed", 1, "engine_unavailable", None)
        assert extraction_rows(conn) == []


def test_artifacts_changed_after_the_claim_count_as_an_attempt(c, monkeypatch, tmp_path):
    root = tmp_path / "model"
    root.mkdir()
    (root / "w.bin").write_bytes(b"weights")
    approved = tmp_path / "approved.json"
    approved.write_text(json.dumps({"adapters": [{
        "ref": FAKE + "good", "artifact_root": str(root), "artifacts": ["w.bin"],
        "model_checksum": ocr.manifest_checksum({"artifact_root": str(root), "artifacts": ["w.bin"]})}]}))
    monkeypatch.setenv("OCR_ADAPTERS_APPROVED", str(approved))
    with c.connect() as conn:
        doc_id, o, engine, config, work = claimed(c, conn, monkeypatch, "good")
        (root / "w.bin").write_bytes(b"swapped")
        extraction._attempt(conn, work, engine, None, o, config)
        # claimed, so the existing failure path records it; still no extractions row
        assert job(conn, doc_id) == ("extraction_failed", 1, "model_integrity_failed", None)
        assert extraction_rows(conn) == []
        assert extraction.run_due(conn, **CHILD) == 0  # and the next probe refuses before any claim
    assert "code=model_integrity_failed stage=probe" in logged(c)


# ---- process groups (Linux): the adapter's own children die with it

def alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return Path(f"/proc/{pid}/status").exists() and "zombie" not in Path(f"/proc/{pid}/status").read_text()


def wait_gone(pid, seconds=20):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not alive(pid):
            return True
        time.sleep(0.2)
    return False


def grandchild_pid(c):
    for _ in range(150):
        pids = [int(e[4:]) for e in events(c) if e.startswith("pid:")]
        if pids:
            return pids[0]
        time.sleep(0.2)
    pytest.fail("the adapter never started its child")


linux_only = pytest.mark.skipif(not sys.platform.startswith("linux"),
                                reason="process groups are killed on Linux only; Windows kills the OCR child alone")


@linux_only
def test_hard_timeout_kills_the_adapters_children_in_its_group(c, monkeypatch):
    use(monkeypatch, "spawns")
    doc_id = upload(c, c.headers)
    with c.connect() as conn:
        assert extraction.run_due(conn, **{**CHILD, "hard_timeout": timedelta(seconds=4)}) == 1
        assert job(conn, doc_id)[2] == "HardTimeout"
    assert wait_gone(grandchild_pid(c))


@linux_only
def test_a_child_in_its_own_session_escapes_as_documented(c, monkeypatch):
    use(monkeypatch, "spawns_new_session")
    upload(c, c.headers)
    with c.connect() as conn:
        extraction.run_due(conn, **{**CHILD, "hard_timeout": timedelta(seconds=4)})
    pid = grandchild_pid(c)
    try:
        assert alive(pid)  # documented limit: setsid() leaves the group, so the group kill misses it
    finally:
        os.kill(pid, 9)


WORKER = """
import sys
from datetime import timedelta
from swasthyoid import db
from swasthyoid.capture import extraction
conn = db.connect(autocommit=True)
extraction.run_due(conn, hard_timeout=timedelta(minutes=5), heartbeat=timedelta(seconds=1))
"""


@linux_only
def test_killing_the_worker_kills_the_adapters_children(c, monkeypatch):
    use(monkeypatch, "spawns")
    upload(c, c.headers)
    worker = subprocess.Popen([sys.executable, "-c", WORKER], cwd=REPO)
    try:
        pid = grandchild_pid(c)
    finally:
        worker.kill()
        worker.wait(30)
    assert wait_gone(pid)  # the OCR child's watchdog ends its whole group


# ---- identity columns: the constraint

def insert(conn, doc_id, version, **identity):
    cols = ["id", "document_id", "version", *identity]
    conn.execute(f"INSERT INTO extractions ({', '.join(cols)}, engine, fields) "
                 f"VALUES ({', '.join(['%s'] * len(cols))}, 'x', '{{}}')",
                 [uuid.uuid4(), doc_id, version, *identity.values()])


FULL = {"engine_id": "fake-v0", "model_version": "1", "model_checksum": "a" * 64, "adapter_interface_version": 0}


def test_identity_constraint_allows_all_null_or_complete_rows_only(c):
    doc_id = upload(c, c.headers)
    with c.connect() as conn:
        insert(conn, doc_id, 1)  # legacy, manual: all NULL
        insert(conn, doc_id, 2, **FULL)
        insert(conn, doc_id, 3, **FULL, adapter_version="a1")
        version = 4
        for bad in ([{**FULL, k: None} for k in FULL] +
                    [{"adapter_version": "a1"}, {**FULL, "model_checksum": "A" * 64},
                     {**FULL, "model_checksum": "a" * 63}, {**FULL, "engine_id": "Bad Id"},
                     {**FULL, "adapter_version": ""}, {**FULL, "adapter_version": "x" * 65},
                     {**FULL, "adapter_interface_version": -1}, {**FULL, "model_version": ""}]):
            with pytest.raises(psycopg.errors.CheckViolation):
                insert(conn, doc_id, version, **bad)
            version += 1


def test_upgrade_keeps_existing_rows_null(c):
    doc_id = upload(c, c.headers)
    with c.connect() as conn:
        conn.execute("ALTER TABLE extractions DROP CONSTRAINT extraction_identity, DROP COLUMN engine_id, "
                     "DROP COLUMN model_version, DROP COLUMN model_checksum, DROP COLUMN adapter_interface_version, "
                     "DROP COLUMN adapter_version")
        insert(conn, doc_id, 1)  # a row from before 4A
        db.apply_schema(conn)
        db.apply_schema(conn)  # twice: idempotent
        assert conn.execute("SELECT engine_id, model_version, model_checksum, adapter_interface_version, "
                            "adapter_version FROM extractions").fetchall() == [(None,) * 5]
