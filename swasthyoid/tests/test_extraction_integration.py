"""Slice 2 against the real thing, not the per-test sandbox used elsewhere.

Each test gets a brand-new, empty PostgreSQL database. The application's own startup applies
the real schema files to it (core, identity, capture), requests go through the real
connection path with no database override, and the field list is the product one, which is
empty until approved. Only one-time-code delivery and the OCR engine are faked.
"""
import os
import threading
import uuid
from types import SimpleNamespace

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.conninfo import make_conninfo

from swasthyoid import db
from swasthyoid.api import deps
from swasthyoid.api.main import app
from swasthyoid.capture import extraction
from swasthyoid.tests.conftest import require_database

V1 = "/api/v1"
JPEG = b"\xff\xd8\xff\xe0 synthetic prescription page"
READING = {"prescriber": {"value": "Synthetic Prescriber", "confidence": 0.99}}


def ocr(pages, doc_type):
    return {"engine": "fake-ocr", "raw_text": "synthetic raw text", "fields": READING}


def broken(pages, doc_type):
    raise RuntimeError("synthetic failure")


@pytest.fixture
def prod(monkeypatch, tmp_path):
    require_database()
    admin_url = os.environ["DATABASE_URL"]
    name = f"it_{uuid.uuid4().hex}"
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(f"CREATE DATABASE {name}")
    monkeypatch.setenv("DATABASE_URL", make_conninfo(admin_url, dbname=name))
    monkeypatch.setenv("DOCUMENT_STORE", str(tmp_path))
    monkeypatch.delenv("DEV_LOG_CODES", raising=False)
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("SWASTHYOID_TEST_MODE_CONFIRM", "1")  # test mode needs both (runtime_mode)
    monkeypatch.setattr(extraction, "HARD_TIMEOUT", None)  # in-process engines unless a test sets a hard timeout
    codes = {}
    app.dependency_overrides[deps.get_code_sender] = lambda: lambda phone, code, context=None: codes.update({phone: code})
    try:
        with TestClient(app) as http:  # startup runs check_config and applies the real schema
            yield SimpleNamespace(http=http, codes=codes, connect=lambda: db.connect(autocommit=True))
    finally:
        app.dependency_overrides.clear()
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(f"DROP DATABASE {name} WITH (FORCE)")


def patient(prod, phone="+8801700000001"):
    assert prod.http.post(f"{V1}/auth/otp/request", json={"phone": phone}).status_code == 204
    r = prod.http.post(f"{V1}/auth/otp/verify", json={
        "phone": phone, "code": prod.codes[phone], "device_id": "dev-1",
        "profile": {"name": "Synthetic Patient", "dob": "1950-01-01", "sex": "F"}})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def upload(prod, headers):
    r = prod.http.post(f"{V1}/documents", headers=headers, data={"doc_type": "prescription"},
                       files=[("images", ("page.jpg", JPEG, "image/jpeg"))])
    assert r.status_code == 201, r.text
    return r.json()["id"]


def job(conn, doc_id):
    return conn.execute(
        "SELECT status, extraction_attempts, extraction_error, next_extraction_at > clock_timestamp() "
        "FROM documents WHERE id = %s", [doc_id]).fetchone()


def blank(doc_type="prescription"):
    """Every approved field of a document type, empty and marked for manual entry."""
    return extraction.structure(extraction.SCHEMAS[doc_type], {}, extraction.CONFIDENCE_THRESHOLD)


def make_due(conn):
    conn.execute("UPDATE documents SET next_extraction_at = clock_timestamp() WHERE status = 'extracting'")


def test_real_schema_has_the_extraction_objects(prod):
    from swasthyoid.tests.approved_fields import APPROVED
    assert extraction.SCHEMAS == APPROVED  # the owner-approved list (D7, 2026-11-14), nothing more
    with prod.connect() as conn:
        def columns(table):
            return {r[0]: r[1:] for r in conn.execute(
                "SELECT column_name, data_type, is_nullable, column_default FROM information_schema.columns "
                "WHERE table_schema = 'public' AND table_name = %s", [table])}

        ext = columns("extractions")
        assert {k: v[:2] for k, v in ext.items()} == {
            "id": ("uuid", "NO"), "document_id": ("uuid", "NO"), "version": ("integer", "NO"),
            "engine": ("text", "NO"), "fields": ("jsonb", "NO"), "raw_text": ("text", "NO"),
            "created_at": ("timestamp with time zone", "NO"),
            # 4A identity columns: nullable, no backfill
            "engine_id": ("text", "YES"), "model_version": ("text", "YES"), "model_checksum": ("text", "YES"),
            "adapter_interface_version": ("integer", "YES"), "adapter_version": ("text", "YES"),
            # D2: the hash of the raw text; the text itself lives in extraction_raw_texts
            "raw_text_sha256": ("text", "YES")}
        raw = columns("extraction_raw_texts")  # deletable, unlike extractions: no append-only triggers
        assert {k: v[:2] for k, v in raw.items()} == {
            "extraction_id": ("uuid", "NO"), "document_id": ("uuid", "NO"), "ciphertext": ("text", "NO"),
            "created_at": ("timestamp with time zone", "NO")}
        docs = columns("documents")
        assert docs["extraction_attempts"] == ("integer", "NO", "0")
        assert docs["next_extraction_at"][:2] == ("timestamp with time zone", "YES")
        assert docs["extraction_error"][:2] == ("text", "YES")
        assert docs["extraction_claim"][:2] == ("uuid", "YES")
        assert docs["extraction_lifetime_attempts"] == ("integer", "NO", "0")  # the lifetime OCR execution counter

        constraints = {r[0]: r[1] for r in conn.execute(
            "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint WHERE conrelid = 'extractions'::regclass")}
        assert constraints["extractions_document_id_version_key"] == "UNIQUE (document_id, version)"
        assert constraints["extractions_document_id_fkey"].startswith("FOREIGN KEY (document_id) REFERENCES documents")
        assert "version >= 1" in constraints["extractions_version_check"]
        assert "model_checksum ~ '^[0-9a-f]{64}$'" in constraints["extraction_identity"]
        assert "raw_text_sha256 ~ '^[0-9a-f]{64}$'" in constraints["extraction_raw_hash"]
        triggers = {r[0] for r in conn.execute(
            "SELECT tgname FROM pg_trigger WHERE tgrelid = 'extractions'::regclass AND NOT tgisinternal")}
        assert triggers == {"extractions_no_change", "extractions_no_truncate"}


def test_schema_applies_twice_and_upgrades_a_slice_1_database(prod):
    with prod.connect() as conn:
        db.apply_schema(conn)  # a second start changes nothing and does not fail
        # put the database back to how slice 1 left it, then start again
        conn.execute("DROP TABLE extraction_raw_texts")  # slice 1 had neither this nor extractions
        conn.execute("DROP TABLE extractions")
        conn.execute("ALTER TABLE documents DROP COLUMN extraction_attempts, DROP COLUMN next_extraction_at, "
                     "DROP COLUMN extraction_error, DROP COLUMN extraction_claim, "
                     "DROP COLUMN extraction_lifetime_attempts")
    doc_id = upload(prod, patient(prod))  # a document that existed before the upgrade
    with TestClient(app):  # a restart applies the slice 2 additions
        pass
    with prod.connect() as conn:
        assert job(conn, doc_id) == ("uploaded", 0, None, None)
        assert conn.execute("SELECT extraction_lifetime_attempts FROM documents WHERE id = %s", [doc_id]).fetchone()[0] == 0
        conn.execute("UPDATE documents SET extraction_lifetime_attempts = 3 WHERE id = %s", [doc_id])
        db.apply_schema(conn)  # applying the schema again never resets or backfills an existing counter
        assert conn.execute("SELECT extraction_lifetime_attempts FROM documents WHERE id = %s", [doc_id]).fetchone()[0] == 3
        conn.execute("UPDATE documents SET extraction_lifetime_attempts = 0 WHERE id = %s", [doc_id])
        assert extraction.run_due(conn, ocr) == 1
        assert job(conn, doc_id)[0] == "needs_review"


def test_pipeline_and_endpoint_on_the_real_schema(prod):
    headers = patient(prod)
    doc_id = upload(prod, headers)
    url = f"{V1}/documents/{doc_id}/extraction"
    assert prod.http.get(url, headers=headers).json() == {
        "document_id": doc_id, "status": "uploaded", "threshold": 0.85, "extraction": None}

    with prod.connect() as conn:
        assert extraction.run_due(conn, ocr) == 1
        assert job(conn, doc_id) == ("needs_review", 1, None, None)
        assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 0  # nothing reaches the timeline
        with pytest.raises(psycopg.errors.UniqueViolation):  # one row per document and version
            conn.execute("INSERT INTO extractions (id, document_id, version, engine, fields) "
                         "VALUES (%s, %s, 1, 'dup', '{}')", [uuid.uuid4(), doc_id])
        with pytest.raises(psycopg.Error, match="append-only"):
            conn.execute("UPDATE extractions SET raw_text = ''")

    body = prod.http.get(url, headers=headers).json()
    assert (body["status"], body["threshold"]) == ("needs_review", 0.85)
    ex = body["extraction"]
    # the engine's readings do not use the approved field names, so every approved field stays for manual entry
    assert (ex["version"], ex["engine"], ex["fields"], ex["raw_text"]) == (1, "fake-ocr", blank(), "synthetic raw text")

    stranger = patient(prod, "+8801700000002")
    assert prod.http.get(url, headers=stranger).status_code == 404
    assert prod.http.get(url).status_code == 401


def test_retry_state_transitions_on_the_real_schema(prod):
    headers = patient(prod)
    doc_id = upload(prod, headers)
    with prod.connect() as conn:
        assert extraction.run_due(conn, broken) == 1
        assert job(conn, doc_id) == ("extracting", 1, "RuntimeError", True)  # waiting for its retry time
        assert extraction.run_due(conn, broken) == 0
        make_due(conn)
        extraction.run_due(conn, broken)
        assert job(conn, doc_id)[:2] == ("extracting", 2)
        make_due(conn)
        extraction.run_due(conn, broken)
        assert job(conn, doc_id)[:3] == ("extraction_failed", 3, "RuntimeError")
        make_due(conn)
        assert extraction.run_due(conn, ocr) == 0  # a failed document is not retried on its own
        assert conn.execute("SELECT count(*) FROM extractions").fetchone()[0] == 0
        assert prod.http.get(f"{V1}/documents/{doc_id}/extraction", headers=headers).json()["status"] == "extraction_failed"

        with pytest.raises(ValueError):  # the state machine refuses to skip review
            extraction.documents.set_status(conn, doc_id, "verified")
        extraction.requeue(conn, doc_id)
        assert job(conn, doc_id)[:2] == ("extracting", 0)
        assert extraction.run_due(conn, ocr) == 1
        assert job(conn, doc_id)[0] == "needs_review"

        second = upload(prod, headers)
        extraction.run_due(conn, broken, max_attempts=1)
        extraction.manual_entry(conn, second)
        assert job(conn, second)[0] == "needs_review"
    manual = prod.http.get(f"{V1}/documents/{second}/extraction", headers=headers).json()["extraction"]
    assert (manual["engine"], manual["fields"], manual["version"]) == ("manual", blank(), 1)


def test_concurrent_workers_on_the_real_schema(prod):
    headers = patient(prod)
    ids = [upload(prod, headers) for _ in range(4)]
    calls, barrier = [], threading.Barrier(4)

    def counting(pages, doc_type):
        calls.append(1)
        return ocr(pages, doc_type)

    def worker():
        with prod.connect() as conn:
            barrier.wait()
            extraction.run_due(conn, counting)

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    with prod.connect() as conn:
        assert [job(conn, i)[0] for i in ids] == ["needs_review"] * 4
        rows = conn.execute("SELECT document_id, version FROM extractions").fetchall()
    assert sorted(str(r[0]) for r in rows) == sorted(ids) and {r[1] for r in rows} == {1}
    assert len(calls) == 4  # each document was read exactly once, whichever worker took it
