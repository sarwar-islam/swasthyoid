"""D7 end to end against PostgreSQL: labelled OCR text from a fake adapter goes through the real worker, the
parsers and the approved field list, and is stored as an UNVERIFIED candidate with provenance. Synthetic data.

Shows plumbing and safety boundaries only; it says nothing about OCR quality or clinical correctness."""
import logging
from datetime import timedelta

import pytest

from swasthyoid.capture import extraction
from swasthyoid.tests.evaluation import generate
from swasthyoid.tests.test_extraction_integration import V1, job, patient, prod  # noqa: F401

CHILD = dict(hard_timeout=timedelta(seconds=60), heartbeat=timedelta(seconds=1), max_attempts=2)
PAGE = generate.build(seed=8, patients=2)["documents"][0]["png"]


@pytest.fixture
def c(prod, monkeypatch, caplog):  # noqa: F811
    monkeypatch.setenv("OCR_ADAPTER", "swasthyoid.tests.adapters.fake_adapters:labelled")
    caplog.set_level(logging.WARNING)
    prod.headers = patient(prod)
    return prod


def upload(c, doc_type):
    r = c.http.post(f"{V1}/documents", headers=c.headers, data={"doc_type": doc_type},
                    files=[("images", ("page.png", PAGE, "image/png"))])
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_a_labelled_prescription_becomes_an_unverified_candidate_with_the_right_fields(c):
    doc_id = upload(c, "prescription")
    with c.connect() as conn:
        assert extraction.run_due(conn, **CHILD) == 1
        assert job(conn, doc_id)[:2] == ("needs_review", 1)
        fields = extraction.latest(conn, doc_id)["fields"]
        assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 0  # nothing verified, nothing on the timeline
        provenance = conn.execute("SELECT engine_id, adapter_interface_version FROM extractions WHERE document_id = %s",
                                  [doc_id]).fetchone()
    assert provenance == ("fake-v0", 0)
    date = fields["prescription_date"]
    assert (date["value"], date["manual_entry"], date["source"]) == ("2024-03-12", False, "ocr")
    assert fields["prescriber_name"]["value"] == "Synth Doctor" and fields["advice_text"]["value"] == "rest"
    allergy = fields["allergy_text"]  # below the review threshold: kept as read, left for manual entry
    assert (allergy["value"], allergy["raw"], allergy["manual_entry"], allergy["confidence"]) == (None, "synthetic note", True, 0.5)
    row = fields["medications"][0]
    assert row["name_as_written"]["value"] == "SYNTH-DRUG-001 500 mg" and row["strength"]["manual_entry"] is True
    assert fields["facility_name"]["manual_entry"] is True and fields["follow_up_date"]["value"] is None


def test_the_patient_sees_the_candidate_through_the_extraction_endpoint_and_it_stays_unverified(c):
    doc_id = upload(c, "prescription")
    with c.connect() as conn:
        extraction.run_due(conn, **CHILD)
    body = c.http.get(f"{V1}/documents/{doc_id}/extraction", headers=c.headers).json()
    assert body["status"] == "needs_review" and body["extraction"]["fields"]["prescription_date"]["value"] == "2024-03-12"


def test_a_document_type_without_fields_goes_to_review_with_raw_text_only(c):
    doc_id = upload(c, "other")
    with c.connect() as conn:
        extraction.run_due(conn, **CHILD)
        stored = extraction.latest(conn, doc_id)
    assert job_status(c, doc_id) == "needs_review" and stored["fields"] == {} and "Date: 12/03/2024" in stored["raw_text"]


def job_status(c, doc_id):
    with c.connect() as conn:
        return job(conn, doc_id)[0]


def test_a_lab_report_reads_only_what_a_lab_report_has(c):
    doc_id = upload(c, "lab_report")  # the same text: the date label also exists for lab reports
    with c.connect() as conn:
        extraction.run_due(conn, **CHILD)
        fields = extraction.latest(conn, doc_id)["fields"]
    assert fields["report_date"]["value"] == "2024-03-12" and set(fields) == {"report_date", "lab_name", "tests", "printed_patient_name"}
    assert "prescriber_name" not in fields and "allergy_text" not in fields
