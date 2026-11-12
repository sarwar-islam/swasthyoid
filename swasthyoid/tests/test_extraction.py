"""M2 extraction pipeline with fake engines. The schema here is test-only and synthetic:
the product field list is still awaiting approval (docs/DECISIONS.md)."""
import threading
from pathlib import Path

import psycopg
import pytest

from swasthyoid.capture import documents, extraction
from swasthyoid.tests.authz_matrix.test_caregiver import SCOPES, grant, w  # noqa: F401
from swasthyoid.tests.test_api_m1 import V1, api, login  # noqa: F401
from swasthyoid.tests.test_documents import JPEG, PNG, d, upload  # noqa: F401

SPEC = {"prescription": {"visit_date": "date", "prescriber": "text",
                         "items": [{"name": "text", "amount": "number"}]}}


def high(value):
    return {"value": value, "confidence": 0.99}


def low(value):
    return {"value": value, "confidence": 0.40}


GOOD = {"visit_date": high("০৫/১২/২০২৬"), "prescriber": high("  Synthetic Prescriber  "),
        "items": [{"name": high("SYNTH-DRUG-001"), "amount": high("৫০০")},
                  {"name": high("SYNTH-DRUG-002"), "amount": high("2.5")}],
        "not_in_schema": high("dropped")}


def engine_returning(fields, calls=None):
    def engine(pages, doc_type):
        if calls is not None:
            calls.append(pages)
        return {"engine": "fake-ocr", "raw_text": "synthetic raw text", "fields": fields}
    return engine


def failing(pages, doc_type):
    raise RuntimeError("synthetic patient text that must not be stored")


@pytest.fixture
def x(d, monkeypatch):  # noqa: F811
    monkeypatch.setattr(extraction, "SCHEMAS", SPEC)
    return d


def new_doc(x, **kw):
    return upload(x, **kw).json()["id"]


def doc_row(x, doc_id):
    return x.conn.execute(
        "SELECT status, extraction_attempts, extraction_error FROM documents WHERE id = %s", [doc_id]).fetchone()


def make_due(x):
    x.conn.execute("UPDATE documents SET next_extraction_at = clock_timestamp() WHERE status = 'extracting'")


def stored(x, doc_id):
    return extraction.latest(x.conn, doc_id)


# ---- parsing

def test_numerals_dates_and_numbers():
    assert extraction.normalise_numerals("৫০০ mg, ২ বার") == "500 mg, 2 বার"
    for text in ("2026-12-05", "05/12/2026", "05-12-2026", "05.12.2026", "০৫/১২/২০২৬", " 5/12/2026 "):
        assert extraction.parse("date", text) == "2026-12-05"
    for bad in ("31/02/2026", "12/2026", "05/12/26", "yesterday", "", "2026-13-01"):
        with pytest.raises(ValueError):
            extraction.parse("date", bad)
    assert extraction.parse("number", "৫০০") == "500" and extraction.parse("number", " 2.50 ") == "2.50"
    for bad in ("five", "1/2", "NaN", "Infinity", "", "12 mg"):
        with pytest.raises(ValueError):
            extraction.parse("number", bad)
    assert extraction.parse("text", "  Synthetic  ") == "Synthetic"
    with pytest.raises(ValueError):
        extraction.parse("text", "   ")


# ---- the pipeline

def test_extraction_ends_in_needs_review_with_typed_fields(x):
    doc_id, calls = new_doc(x, images=[JPEG, PNG]), []
    assert extraction.run_due(x.conn, engine_returning(GOOD, calls)) == 1
    assert calls == [[JPEG, PNG]]  # the engine got the decrypted originals, in order
    assert doc_row(x, doc_id) == ("needs_review", 0, None)

    row = stored(x, doc_id)
    assert (row["version"], row["engine"], row["raw_text"]) == (1, "fake-ocr", "synthetic raw text")
    f = row["fields"]
    assert set(f) == {"visit_date", "prescriber", "items"}  # only schema fields are kept
    assert f["visit_date"] == {"value": "2026-12-05", "raw": "০৫/১২/২০২৬", "confidence": 0.99,
                               "source": "ocr", "manual_entry": False}
    assert f["prescriber"]["value"] == "Synthetic Prescriber"
    assert [(i["name"]["value"], i["amount"]["value"]) for i in f["items"]] == [
        ("SYNTH-DRUG-001", "500"), ("SYNTH-DRUG-002", "2.5")]
    assert extraction.run_due(x.conn, engine_returning(GOOD, calls)) == 0 and len(calls) == 1
    # extraction never writes to the timeline and never verifies
    assert x.conn.execute("SELECT count(*) FROM events").fetchone()[0] == 0
    assert x.conn.execute("SELECT verified_by FROM documents").fetchone()[0] is None


def test_low_confidence_missing_and_invalid_fields_are_left_for_manual_entry(x):
    doc_id = new_doc(x)
    extraction.run_due(x.conn, engine_returning({
        "visit_date": high("not a date"), "prescriber": low("Synthetic Guess"),
        "items": [{"name": high("SYNTH-DRUG-001"), "amount": high("lots")}, "junk", {"amount": {"value": None}}],
    }))
    f = stored(x, doc_id)["fields"]
    assert f["visit_date"] == {"value": None, "raw": "not a date", "confidence": 0.99, "source": "ocr",
                               "manual_entry": True, "error": "invalid_date"}
    assert f["prescriber"] == {"value": None, "raw": "Synthetic Guess", "confidence": 0.4, "source": "ocr",
                               "manual_entry": True}
    assert f["items"][0]["amount"]["error"] == "invalid_number" and f["items"][0]["name"]["manual_entry"] is False
    assert len(f["items"]) == 2  # the junk row is dropped, the empty row is kept for entry
    assert f["items"][1]["name"] == {"value": None, "raw": None, "confidence": 0.0, "source": None,
                                     "manual_entry": True}
    assert doc_row(x, doc_id)[0] == "needs_review"


@pytest.mark.parametrize("threshold, kept", [(0.85, False), (0.30, True)])
def test_threshold_is_configurable(x, threshold, kept):
    doc_id = new_doc(x)
    extraction.run_due(x.conn, engine_returning({"prescriber": low("Synthetic Prescriber")}), threshold=threshold)
    assert (stored(x, doc_id)["fields"]["prescriber"]["value"] is not None) == kept


def test_malformed_engine_output_still_ends_in_review(x):
    for fields in (None, "text", [], {"items": "not a list", "prescriber": {"value": "x", "confidence": "high"}}):
        doc_id = new_doc(x)
        extraction.run_due(x.conn, engine_returning(fields))
        assert doc_row(x, doc_id)[0] == "needs_review"
        assert stored(x, doc_id)["fields"]["prescriber"]["manual_entry"] is True


def test_doc_type_without_a_schema_goes_to_review_with_raw_text_only(x):
    doc_id = new_doc(x, doc_type="other")
    extraction.run_due(x.conn, engine_returning(GOOD))
    assert doc_row(x, doc_id)[0] == "needs_review"
    assert (stored(x, doc_id)["fields"], stored(x, doc_id)["raw_text"]) == ({}, "synthetic raw text")


# ---- cloud AI gate

def ai_spy(calls, answers=None, fail=False):
    def ai(pages, doc_type, paths):
        calls.append((pages, doc_type, sorted(paths)))
        if fail:
            raise ConnectionError("provider down")
        return answers or {}
    return ai


MIXED = {"visit_date": high("05/12/2026"), "prescriber": low("Synthetic Guess"),
         "items": [{"name": low("SYNTH-GUESS"), "amount": high("500")}]}


def test_without_opt_in_the_cloud_ai_is_never_called(x):
    doc_id, calls = new_doc(x), []
    extraction.run_due(x.conn, engine_returning(MIXED), ai_spy(calls, {"prescriber": high("From AI")}),
                       ai_threshold=0.85)
    assert calls == []
    assert stored(x, doc_id)["fields"]["prescriber"]["manual_entry"] is True
    assert x.conn.execute("SELECT count(*) FROM audit_logs WHERE action = 'cloud_ai.send'").fetchone()[0] == 0


def test_with_opt_in_only_low_confidence_fields_go_to_the_cloud_ai_and_it_is_audited(x):
    x.conn.execute("UPDATE patients SET cloud_ai_opt_in = true WHERE id = %s", [x.patient.id])
    doc_id, calls = new_doc(x), []
    answers = {"prescriber": high("Synthetic Prescriber"), "items[0].name": low("still unsure"),
               "visit_date": high("01/01/2000")}  # an answer nobody asked for is ignored
    extraction.run_due(x.conn, engine_returning(MIXED), ai_spy(calls, answers), ai_threshold=0.85)
    assert calls == [([JPEG], "prescription", ["items[0].name", "prescriber"])]
    f = stored(x, doc_id)["fields"]
    assert (f["prescriber"]["value"], f["prescriber"]["source"]) == ("Synthetic Prescriber", "cloud_ai")
    assert f["items"][0]["name"]["manual_entry"] is True and f["items"][0]["name"]["source"] == "cloud_ai"
    assert f["visit_date"]["value"] == "2026-12-05" and f["visit_date"]["source"] == "ocr"
    sent = x.conn.execute(
        "SELECT patient_id, purpose, resource_id FROM audit_logs WHERE action = 'cloud_ai.send'").fetchall()
    assert [(r[0], r[1], str(r[2])) for r in sent] == [(x.patient.id, "CLOUD_AI", doc_id)]


def test_cloud_ai_is_skipped_when_nothing_is_low_and_its_failure_is_not_fatal(x):
    x.conn.execute("UPDATE patients SET cloud_ai_opt_in = true")
    calls = []
    new_doc(x)
    extraction.run_due(x.conn, engine_returning(GOOD), ai_spy(calls), ai_threshold=0.85)
    assert calls == []  # nothing was low-confidence, so nothing left the system
    doc_id = new_doc(x)
    extraction.run_due(x.conn, engine_returning(MIXED), ai_spy(calls, fail=True), ai_threshold=0.85)
    assert len(calls) == 1 and doc_row(x, doc_id)[0] == "needs_review"
    assert stored(x, doc_id)["fields"]["prescriber"]["manual_entry"] is True


def test_cloud_ai_threshold_is_unset_by_default_so_nothing_is_sent(x):
    assert extraction.CLOUD_AI_THRESHOLD is None  # no number is approved yet
    x.conn.execute("UPDATE patients SET cloud_ai_opt_in = true")
    doc_id, calls = new_doc(x), []
    extraction.run_due(x.conn, engine_returning(MIXED), ai_spy(calls, {"prescriber": high("From AI")}))
    assert calls == [] and stored(x, doc_id)["fields"]["prescriber"]["manual_entry"] is True
    assert x.conn.execute("SELECT count(*) FROM audit_logs WHERE action = 'cloud_ai.send'").fetchone()[0] == 0


def test_cloud_ai_threshold_is_independent_of_the_review_threshold(x):
    x.conn.execute("UPDATE patients SET cloud_ai_opt_in = true")
    readings = {"visit_date": {"value": "05/12/2026", "confidence": 0.90},
                "prescriber": {"value": "Synthetic Guess", "confidence": 0.70},
                "items": [{"name": {"value": "SYNTH-GUESS", "confidence": 0.40}, "amount": high("500")}]}
    answers = {"items[0].name": high("SYNTH-DRUG-001"), "prescriber": high("From AI"),
               "visit_date": low("01/01/2000")}

    # lower than review: 0.70 is not sent, and stays for manual entry (it is below 0.85)
    doc_id, calls = new_doc(x), []
    extraction.run_due(x.conn, engine_returning(readings), ai_spy(calls, answers), ai_threshold=0.5)
    assert calls[0][2] == ["items[0].name"]
    f = stored(x, doc_id)["fields"]
    assert f["items"][0]["name"]["value"] == "SYNTH-DRUG-001"
    assert f["prescriber"]["manual_entry"] is True and f["prescriber"]["source"] == "ocr"

    # higher than review: 0.90 is sent too, but a worse answer never replaces an accepted reading
    doc_id, calls = new_doc(x), []
    extraction.run_due(x.conn, engine_returning(readings), ai_spy(calls, answers), ai_threshold=0.95)
    assert calls[0][2] == ["items[0].name", "prescriber", "visit_date"]
    f = stored(x, doc_id)["fields"]
    assert (f["visit_date"]["value"], f["visit_date"]["source"]) == ("2026-12-05", "ocr")
    assert (f["prescriber"]["value"], f["prescriber"]["source"]) == ("From AI", "cloud_ai")
    assert extraction.CONFIDENCE_THRESHOLD == 0.85


# ---- failure, retry, idempotency

def test_retries_with_backoff_then_extraction_failed(x):
    doc_id = new_doc(x)
    assert extraction.run_due(x.conn, failing) == 1
    assert doc_row(x, doc_id) == ("extracting", 1, "RuntimeError")  # the error type, never its text
    assert extraction.run_due(x.conn, failing) == 0  # backing off
    make_due(x)
    extraction.run_due(x.conn, failing)
    make_due(x)
    extraction.run_due(x.conn, failing)
    assert doc_row(x, doc_id) == ("extraction_failed", 3, "RuntimeError")
    make_due(x)
    assert extraction.run_due(x.conn, failing) == 0  # finished; not retried on its own
    assert stored(x, doc_id) is None
    assert "synthetic patient text" not in str(x.conn.execute("SELECT * FROM documents").fetchall())

    extraction.requeue(x.conn, doc_id)
    assert doc_row(x, doc_id)[:2] == ("extracting", 0)
    extraction.run_due(x.conn, engine_returning(GOOD))
    assert doc_row(x, doc_id)[0] == "needs_review" and stored(x, doc_id)["version"] == 1


def test_manual_entry_after_failure(x):
    doc_id = new_doc(x)
    with pytest.raises(ValueError):  # only from extraction_failed
        extraction.manual_entry(x.conn, doc_id)
    extraction.run_due(x.conn, failing, max_attempts=1)
    extraction.manual_entry(x.conn, doc_id)
    row = stored(x, doc_id)
    assert doc_row(x, doc_id)[0] == "needs_review" and (row["engine"], row["raw_text"]) == ("manual", "")
    assert row["fields"]["prescriber"]["manual_entry"] is True and row["fields"]["items"] == []


def test_a_corrupted_original_counts_as_a_failed_attempt(x):
    doc_id = new_doc(x)
    next(p for p in Path(x.store).rglob("*") if p.is_file()).unlink()
    extraction.run_due(x.conn, engine_returning(GOOD), max_attempts=1)
    assert doc_row(x, doc_id) == ("extraction_failed", 1, "Corrupted")


def test_job_is_idempotent_by_document_and_version(x):
    doc_id, calls = new_doc(x), []
    engine = engine_returning(GOOD, calls)
    assert extraction.extract(x.conn, doc_id, 2, engine) is False  # not the version being waited for
    assert extraction.extract(x.conn, doc_id, 1, engine) is True
    assert extraction.extract(x.conn, doc_id, 1, engine) is False  # a repeat does nothing
    assert extraction.extract(x.conn, doc_id, 2, engine) is False  # the document is in review, not waiting
    assert extraction.extract(x.conn, "00000000-0000-0000-0000-000000000000", 1, engine) is False
    assert len(calls) == 1
    assert x.conn.execute("SELECT count(*) FROM extractions").fetchone()[0] == 1


def test_two_workers_extract_a_document_once(x, connect):
    doc_id, calls, barrier, results = new_doc(x), [], threading.Barrier(2), []

    def worker():
        conn = connect()
        conn.autocommit = True
        barrier.wait()
        results.append(extraction.extract(conn, doc_id, 1, engine_returning(GOOD, calls)))

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(results) == [False, True] and len(calls) == 1
    assert x.conn.execute("SELECT count(*) FROM extractions").fetchone()[0] == 1


def test_every_document_ends_in_needs_review_or_extraction_failed(x):
    ids = [new_doc(x) for _ in range(6)]

    def flaky(pages, doc_type):  # works for the first three documents, then is down for good
        if x.conn.execute("SELECT count(*) FROM documents WHERE status = 'needs_review'").fetchone()[0] >= 3:
            raise RuntimeError("down")
        return {"engine": "fake-ocr", "fields": GOOD}

    for _ in range(extraction.MAX_ATTEMPTS + 1):
        extraction.run_due(x.conn, flaky)
        make_due(x)
    statuses = [doc_row(x, i)[0] for i in ids]
    assert sorted(set(statuses)) == ["extraction_failed", "needs_review"]
    assert statuses.count("needs_review") == 3
    assert x.conn.execute("SELECT count(*) FROM events").fetchone()[0] == 0


def test_capture_code_cannot_write_events():
    capture = Path(extraction.__file__).parent
    for source in capture.glob("*.py"):
        assert "events_provenance" not in source.read_text(encoding="utf-8"), source.name


def test_extractions_are_append_only(x):
    new_doc(x)
    extraction.run_due(x.conn, engine_returning(GOOD))
    for sql in ("UPDATE extractions SET fields = '{}'", "DELETE FROM extractions", "TRUNCATE extractions"):
        with pytest.raises(psycopg.Error, match="append-only"):
            x.conn.execute(sql)


# ---- API

def test_only_the_patient_sees_unverified_extraction(x):
    doc_id = new_doc(x)
    url = f"{V1}/documents/{doc_id}/extraction"
    before = x.http.get(url, headers=x.patient.h).json()
    assert (before["status"], before["extraction"], before["threshold"]) == ("uploaded", None, 0.85)
    extraction.run_due(x.conn, engine_returning(GOOD))
    after = x.http.get(url, headers=x.patient.h).json()
    assert after["status"] == "needs_review" and after["extraction"]["version"] == 1
    assert after["extraction"]["fields"]["prescriber"]["value"] == "Synthetic Prescriber"

    grant(x, SCOPES)  # even a caregiver with every scope: they do not verify
    assert x.http.get(url, headers=x.caregiver.h).status_code == 404
    doctor = login(x.api, "+8801900000002", account="staff", staff={"role": "doctor", "name": "Synthetic Doctor"})
    x.conn.execute("UPDATE users SET status = 'verified'")
    assert x.http.get(url, headers=doctor).status_code == 403
    assert x.http.get(f"{V1}/documents/00000000-0000-0000-0000-000000000000/extraction",
                      headers=x.patient.h).status_code == 404
    # the caregiver still sees the document and its new status, just not the unverified fields
    seen = x.http.get(f"{V1}/documents/{doc_id}", headers=x.caregiver.h).json()
    assert seen["status"] == "needs_review" and "fields" not in str(seen)
