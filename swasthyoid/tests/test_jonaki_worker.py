"""The Jonaki adapter through the real worker and PostgreSQL, with the fake runner (no PaddleOCR, no
weights): provenance on the extraction row, raw text in reading order, failure and retry handling,
original immutability, and no verified events. Needs DATABASE_URL (skips without it).

Shows plumbing and safety boundaries only; nothing here measures Jonaki's accuracy. Synthetic data."""
import json
import logging
from datetime import timedelta

import pytest

from swasthyoid.capture import documents, extraction
from swasthyoid.tests.evaluation import generate
from swasthyoid.tests.test_extraction_integration import V1, job, patient, prod  # noqa: F401

FAKE = "swasthyoid.tests.adapters.fake_jonaki:jonaki"
CHILD = dict(hard_timeout=timedelta(seconds=120), heartbeat=timedelta(seconds=2), max_attempts=2, backoff=timedelta(0))
PAGE = generate.build(seed=7, patients=2)["documents"][0]["png"]
ORDERED = "\n".join(["বাংলা পরীক্ষা 123 mixed", "first row right", "second row left", "second row right", "third row"])


@pytest.fixture
def c(prod, monkeypatch, caplog):  # noqa: F811
    monkeypatch.setenv("OCR_ADAPTER", FAKE)
    monkeypatch.setenv("FAKE_JONAKI_MODE", "ok")
    caplog.set_level(logging.WARNING)
    prod.headers = patient(prod)
    prod.caplog = caplog
    return prod


def upload_png(c, data=PAGE):
    r = c.http.post(f"{V1}/documents", headers=c.headers, data={"doc_type": "prescription"},
                    files=[("images", ("page.png", data, "image/png"))])
    assert r.status_code == 201, r.text
    return r.json()["id"]


def rows(conn, doc_id):
    """Provenance columns plus raw_text and fields read through the decrypting reader (D2 stores them sealed)."""
    got = extraction.latest(conn, doc_id)
    if got is None:
        return []
    base = conn.execute("SELECT version, engine, engine_id, model_version, adapter_version, adapter_interface_version "
                        "FROM extractions WHERE document_id = %s", [doc_id]).fetchall()
    return [(*row, got["raw_text"], json.dumps(got["fields"])) for row in base]


def test_a_page_is_extracted_with_jonaki_provenance_and_ordered_text(c):
    doc_id = upload_png(c)
    with c.connect() as conn:
        original = documents.read_image(conn, doc_id, 1)[1]
        assert extraction.run_due(conn, preprocess=("contrast",), **CHILD) == 1
        assert job(conn, doc_id) == ("needs_review", 1, None, None)
        ((version, engine, engine_id, model_version, adapter_version, interface, raw_text, fields),) = rows(conn, doc_id)
        assert (version, engine, engine_id, adapter_version, interface) == (1, "jonaki-bangla-ocr", "jonaki-bangla-ocr", "jonaki-1", 0)
        assert "jonaki-small-rec@fake-rev-1" in model_version and "PP-OCRv6_medium_det@fake-det-1" in model_version
        assert raw_text == ORDERED  # the lines in reading order
        assert "0.97" not in fields and "0.97" not in raw_text  # version 0 stores no confidence or position
        assert documents.read_image(conn, doc_id, 1)[1] == original == PAGE  # the original is untouched
        assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 0  # nothing verified, nothing on the timeline


def test_the_result_is_unverified_and_waits_for_review(c):
    doc_id = upload_png(c)
    with c.connect() as conn:
        extraction.run_due(conn, **CHILD)
    body = c.http.get(f"{V1}/documents/{doc_id}/extraction", headers=c.headers).json()
    assert body["status"] == "needs_review" and body["extraction"]["engine"] == "jonaki-bangla-ocr"


@pytest.mark.parametrize("mode, code", [("undecodable", "engine_error"), ("crash", "engine_error"),
                                        ("garbage", "malformed_output"), ("bad_poly", "malformed_output")])
def test_failures_are_retried_then_recorded_by_code_and_the_original_survives(c, monkeypatch, mode, code):
    monkeypatch.setenv("FAKE_JONAKI_MODE", mode)
    doc_id = upload_png(c)
    with c.connect() as conn:
        assert extraction.run_due(conn, **CHILD) == 2  # attempted, retried
        assert job(conn, doc_id) == ("extraction_failed", 2, code, None)
        assert rows(conn, doc_id) == []  # nothing stored for a failed read
        assert documents.read_image(conn, doc_id, 1)[1] == PAGE
    assert "synthetic" not in c.caplog.text  # no page text in the logs


def test_a_hung_runner_fails_the_attempt_without_blocking_the_worker(c, monkeypatch):
    monkeypatch.setenv("FAKE_JONAKI_MODE", "hang")
    doc_id = upload_png(c)
    with c.connect() as conn:
        assert extraction.run_due(conn, hard_timeout=timedelta(seconds=120), heartbeat=timedelta(seconds=2),
                                  max_attempts=1) == 1  # the adapter's 20 s limit ends the attempt
        assert job(conn, doc_id)[:3] == ("extraction_failed", 1, "engine_error")


def test_a_decodable_page_with_no_text_is_stored_as_an_empty_candidate(c, monkeypatch):
    monkeypatch.setenv("FAKE_JONAKI_MODE", "empty")
    doc_id = upload_png(c)
    with c.connect() as conn:
        assert extraction.run_due(conn, **CHILD) == 1
        assert job(conn, doc_id)[:2] == ("needs_review", 1)
        assert [r[6] for r in rows(conn, doc_id)] == [""]  # nothing found; manual entry follows in M3


def test_two_documents_are_each_extracted_once(c):
    ids = [upload_png(c), upload_png(c)]
    with c.connect() as conn:
        assert extraction.run_due(conn, **CHILD) == 2 and extraction.run_due(conn, **CHILD) == 0
        assert conn.execute("SELECT count(*), count(DISTINCT document_id) FROM extractions").fetchone() == (2, 2)
        assert [job(conn, i)[:2] for i in ids] == [("needs_review", 1)] * 2
