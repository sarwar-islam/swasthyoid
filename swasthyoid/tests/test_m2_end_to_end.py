"""The model-independent M2 workflow, end to end, against PostgreSQL:

upload (API) -> original stored -> processing copy -> OCR adapter (a fake) -> candidate extraction
-> schema validation -> persistence -> worker -> needs_review

Written without a local PostgreSQL: these tests skip here and run in CI. They use a fake adapter
and a synthetic, test-only schema, so they show the plumbing and the safety boundaries and say
nothing about OCR quality or any clinical field. M2 output stays unverified: no verified event is
ever created. Synthetic data only.
"""
import hashlib
import json
import logging
from datetime import timedelta

import pytest

from swasthyoid.capture import documents, extraction
from swasthyoid.tests.evaluation import generate
from swasthyoid.tests.test_extraction_integration import V1, job, patient, prod  # noqa: F401

FAKE = "swasthyoid.tests.adapters.fake_adapters:"
CHILD = dict(hard_timeout=timedelta(seconds=60), heartbeat=timedelta(seconds=1), max_attempts=2)
PAGE = generate.build(seed=6, patients=2)["copies"][0]["png"]  # a real, rotated synthetic page (PNG)


@pytest.fixture
def c(prod, monkeypatch, tmp_path, caplog):  # noqa: F811
    monkeypatch.setenv("OCR_ADAPTER", FAKE + "good")
    monkeypatch.setenv("FAKE_ADAPTER_LOG", str(tmp_path / "adapter.log"))
    caplog.set_level(logging.WARNING)
    prod.headers = patient(prod)
    prod.caplog = caplog
    return prod


def upload_png(c, data=PAGE):
    r = c.http.post(f"{V1}/documents", headers=c.headers, data={"doc_type": "prescription"},
                    files=[("images", ("page.png", data, "image/png"))])
    assert r.status_code == 201, r.text
    return r.json()["id"]


def count(conn, table):
    return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]


def test_a_real_page_goes_from_upload_to_needs_review_with_the_original_preserved(c):
    doc_id = upload_png(c)
    with c.connect() as conn:
        original = documents.read_image(conn, doc_id, 1)[1]
        rows_before = conn.execute("SELECT sha256, size_bytes FROM document_images WHERE document_id = %s", [doc_id]).fetchall()
        assert extraction.run_due(conn, preprocess=("deskew", "contrast"), **CHILD) == 1
        assert job(conn, doc_id) == ("needs_review", 1, None, None)
        # the original: same bytes, same row, no extra image row for the processing copy
        assert documents.read_image(conn, doc_id, 1)[1] == original == PAGE
        assert conn.execute("SELECT sha256, size_bytes FROM document_images WHERE document_id = %s", [doc_id]).fetchall() == rows_before
        assert rows_before == [(hashlib.sha256(PAGE).hexdigest(), len(PAGE))]
        # provenance: the adapter's identity is on the row; one extraction, version 1
        assert conn.execute("SELECT version, engine_id, model_version, adapter_interface_version FROM extractions "
                            "WHERE document_id = %s", [doc_id]).fetchall() == [(1, "fake-v0", "0.0-test", 0)]


def test_the_result_is_an_unverified_candidate_and_creates_no_verified_event(c):
    doc_id = upload_png(c)
    with c.connect() as conn:
        events_before = count(conn, "events")
        extraction.run_due(conn, **CHILD)
        assert count(conn, "events") == events_before == 0  # M2 never writes the verified timeline
    body = c.http.get(f"{V1}/documents/{doc_id}/extraction", headers=c.headers).json()
    assert body["status"] == "needs_review" and body["extraction"]["version"] == 1  # awaiting M3's human check


def test_schema_rules_are_applied_to_what_is_stored_and_missing_required_is_reportable(c, monkeypatch):
    spec = {"title": {"kind": "text", "required": True}, "issued": {"kind": "date", "rules": ["not_future"]}}
    monkeypatch.setattr(extraction, "SCHEMAS", {"prescription": spec})  # test-only; the real SCHEMAS stays empty
    doc_id = upload_png(c)
    with c.connect() as conn:
        extraction.run_due(conn, **CHILD)
        stored = conn.execute("SELECT fields FROM extractions WHERE document_id = %s", [doc_id]).fetchone()[0]
    fields = json.loads(stored) if isinstance(stored, str) else stored
    assert set(fields) == {"title", "issued"}  # every schema field present, nothing else kept
    assert all(f["manual_entry"] is True and f["value"] is None for f in fields.values())  # the adapter gives no fields
    assert extraction.missing_required(spec, fields) == ["title"]


def test_a_page_that_cannot_be_decoded_fails_the_attempt_and_the_original_survives(c, tmp_path):
    bad = b"\x89PNG\r\n\x1a\n" + b"not really a png"  # passes the upload's first-bytes check, does not decode
    doc_id = upload_png(c, bad)
    with c.connect() as conn:
        assert extraction.run_due(conn, preprocess=("deskew",), backoff=timedelta(0), **CHILD) == 2  # tried, retried
        assert job(conn, doc_id) == ("extraction_failed", 2, "ImageRejected", None)
        assert count(conn, "extractions") == 0
        assert documents.read_image(conn, doc_id, 1)[1] == bad  # the original is still there, unchanged
    assert "not really a png" not in c.caplog.text


def test_two_documents_are_each_extracted_once_by_repeated_calls(c):
    ids = [upload_png(c), upload_png(c)]
    with c.connect() as conn:
        assert extraction.run_due(conn, **CHILD) == 2
        assert extraction.run_due(conn, **CHILD) == 0  # nothing is due again: no duplicate attempt
        assert [job(conn, i)[:2] for i in ids] == [("needs_review", 1)] * 2
        assert conn.execute("SELECT count(*), count(DISTINCT document_id) FROM extractions").fetchone() == (2, 2)
