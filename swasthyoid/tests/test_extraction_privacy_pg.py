"""D2 against PostgreSQL (owner decision 2026-11-14, option b): extracted text is stored sealed, the raw text lives
in a deletable table with only its hash in the append-only row, and it is deleted at verification or rejection.
Synthetic data only.

These tests show what is technically enforced in the database. They do not show anything about a database
backup, a replica, or a stolen EXTRACTION_KEY: that key is the root of the protection."""
import logging
from datetime import timedelta

import pytest
from cryptography.fernet import Fernet

from swasthyoid.capture import documents, extraction, extraction_crypto as crypto
from swasthyoid.tests.evaluation import generate
from swasthyoid.tests.test_extraction_integration import V1, job, patient, prod, upload  # noqa: F401

CHILD = dict(hard_timeout=timedelta(seconds=60), heartbeat=timedelta(seconds=1), max_attempts=2)
RAW = "SYNTH-PRIVATE-RAW text that must never sit in a table"
NAME = "SYNTH-PRIVATE-NAME"
PAGE = generate.build(seed=9, patients=2)["documents"][0]["png"]


def engine(pages, doc_type):
    return {"engine": "fake-ocr", "raw_text": RAW,
            "fields": {"prescriber_name": {"value": NAME, "confidence": 0.99}}}


@pytest.fixture
def c(prod, caplog):  # noqa: F811
    caplog.set_level(logging.DEBUG)
    prod.headers = patient(prod)
    return prod


def extract(c):
    doc_id = upload(c, c.headers)
    with c.connect() as conn:
        assert extraction.run_due(conn, engine) == 1
    return doc_id


def everything(conn):
    """The text of every row of every table, as a dump would hold it."""
    out = []
    for (table,) in conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
                                 "AND table_type = 'BASE TABLE'").fetchall():
        out += [r[0] for r in conn.execute(f'SELECT row_to_json(t)::text FROM "{table}" t').fetchall()]
    return "\n".join(out)


def test_no_table_holds_the_raw_text_or_a_field_value_in_plain_form(c, caplog):
    doc_id = extract(c)
    with c.connect() as conn:
        dump = everything(conn)
        assert RAW not in dump and NAME not in dump and "SYNTH-PRIVATE" not in dump
        got = extraction.latest(conn, doc_id)  # ... yet the reader returns both
        assert got["raw_text"] == RAW and got["fields"]["prescriber_name"]["value"] == NAME
    assert "SYNTH-PRIVATE" not in caplog.text


def test_the_append_only_row_keeps_the_hash_the_sealed_fields_and_an_empty_raw_text_column(c):
    doc_id = extract(c)
    with c.connect() as conn:
        raw_text, sha, fields = conn.execute(
            "SELECT raw_text, raw_text_sha256, fields FROM extractions WHERE document_id = %s", [doc_id]).fetchone()
        token = conn.execute("SELECT ciphertext FROM extraction_raw_texts WHERE document_id = %s", [doc_id]).fetchone()[0]
    assert raw_text == "" and sha == crypto.sha256(RAW)
    assert crypto.is_sealed(fields) and crypto.open_fields(fields)["prescriber_name"]["value"] == NAME
    assert RAW not in token and crypto.open_text(token) == RAW


def test_the_patient_gets_the_decrypted_extraction_through_the_api_and_nobody_else_does(c):
    doc_id = extract(c)
    url = f"{V1}/documents/{doc_id}/extraction"
    body = c.http.get(url, headers=c.headers).json()["extraction"]
    assert body["raw_text"] == RAW and body["raw_text_available"] is True
    assert body["fields"]["prescriber_name"]["value"] == NAME and body["printed_name_check"] == "not_checked"
    assert c.http.get(url, headers=patient(c, "+8801700000002")).status_code == 404
    assert c.http.get(url).status_code == 401


@pytest.mark.parametrize("closing", ["verified", "rejected"])
def test_the_raw_text_is_deleted_when_review_ends_and_only_its_hash_remains(c, closing):
    doc_id = extract(c)
    other = extract(c)
    with c.connect() as conn:
        assert conn.execute("SELECT count(*) FROM extraction_raw_texts WHERE document_id = %s", [doc_id]).fetchone()[0] == 1
        documents.set_status(conn, doc_id, closing)
        assert conn.execute("SELECT count(*) FROM extraction_raw_texts WHERE document_id = %s", [doc_id]).fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM extraction_raw_texts WHERE document_id = %s", [other]).fetchone()[0] == 1
        sha = conn.execute("SELECT raw_text_sha256 FROM extractions WHERE document_id = %s", [doc_id]).fetchone()[0]
        assert sha == crypto.sha256(RAW)  # the append-only row still proves what was read
        got = extraction.latest(conn, doc_id)
        assert got["raw_text"] == "" and got["raw_text_available"] is False  # deleted, and said so
        assert got["fields"]["prescriber_name"]["value"] == NAME  # the sealed fields are not part of the retention rule
        assert RAW not in everything(conn)


def test_the_raw_text_is_kept_while_the_document_is_in_review(c):
    doc_id = extract(c)
    with c.connect() as conn:
        assert job(conn, doc_id)[0] == "needs_review"
        assert extraction.latest(conn, doc_id)["raw_text"] == RAW


def test_a_manual_entry_has_no_raw_text_to_store_and_is_not_reported_as_deleted(c):
    doc_id = upload(c, c.headers)
    assert c.http.post(f"{V1}/documents/{doc_id}/manual-entry", headers=c.headers).status_code == 200
    with c.connect() as conn:
        assert conn.execute("SELECT count(*) FROM extraction_raw_texts WHERE document_id = %s", [doc_id]).fetchone()[0] == 0
        got = extraction.latest(conn, doc_id)
    assert got["raw_text"] == "" and got["raw_text_available"] is True


def test_a_wrong_key_makes_the_reader_fail_closed(c, monkeypatch):
    doc_id = extract(c)
    monkeypatch.setenv("EXTRACTION_KEY", Fernet.generate_key().decode())
    with c.connect() as conn:
        with pytest.raises(crypto.Undecryptable):
            extraction.latest(conn, doc_id)


def test_a_row_written_before_d2_is_still_readable_as_it_is(c):
    doc_id = upload(c, c.headers)
    with c.connect() as conn:
        conn.execute("INSERT INTO extractions (id, document_id, version, engine, fields, raw_text) "
                     "VALUES (gen_random_uuid(), %s, 1, 'old', '{\"x\": 1}', 'plain old text')", [doc_id])
        got = extraction.latest(conn, doc_id)
    assert got["fields"] == {"x": 1} and got["raw_text"] == "plain old text" and got["raw_text_available"] is True


def test_the_extractions_table_is_still_append_only_but_the_raw_text_table_is_deletable(c):
    import psycopg
    doc_id = extract(c)
    with c.connect() as conn:
        for sql in ("UPDATE extractions SET raw_text = 'x'", "DELETE FROM extractions"):
            with pytest.raises(psycopg.Error, match="append-only"):
                conn.execute(sql)
        conn.execute("DELETE FROM extraction_raw_texts WHERE document_id = %s", [doc_id])  # allowed: the retention rule


# ---- the printed patient name: stored sealed, advisory flag only

@pytest.mark.parametrize("adapter, expected", [("labelled_same_patient", "same_after_normalisation"),
                                               ("labelled_other_patient", "not_the_same"), ("labelled", "not_checked")])
def test_the_printed_patient_name_is_sealed_and_gives_an_advisory_flag(c, monkeypatch, adapter, expected):
    monkeypatch.setenv("OCR_ADAPTER", f"swasthyoid.tests.adapters.fake_adapters:{adapter}")
    doc_id = upload(c, c.headers)
    with c.connect() as conn:
        assert extraction.run_due(conn, **CHILD) == 1
        got = extraction.latest(conn, doc_id)
        dump = everything(conn)
        assert job(conn, doc_id)[0] == "needs_review"  # the flag never blocks anything
        assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 0
    assert got["printed_name_check"] == expected
    assert "Somebody Else" not in dump and "SYNTHETIC   patient" not in dump  # the name is not in any table in plain form


# ---- the retention rule lives in the database, so it holds for every writer

@pytest.mark.parametrize("closing", ["verified", "rejected"])
def test_the_database_deletes_the_raw_text_when_any_writer_closes_the_document(c, closing):
    doc_id, other = extract(c), extract(c)
    with c.connect() as conn:
        conn.execute("UPDATE documents SET updated_at = clock_timestamp() WHERE id = %s", [doc_id])  # not a status change
        assert conn.execute("SELECT count(*) FROM extraction_raw_texts WHERE document_id = %s", [doc_id]).fetchone()[0] == 1
        conn.execute("UPDATE documents SET status = %s WHERE id = %s", [closing, doc_id])  # plain SQL, not set_status
        assert conn.execute("SELECT count(*) FROM extraction_raw_texts WHERE document_id = %s", [doc_id]).fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM extraction_raw_texts WHERE document_id = %s", [other]).fetchone()[0] == 1
        assert RAW not in everything(conn)


def test_a_wrong_key_gives_a_controlled_error_through_the_api_and_leaks_nothing(c, monkeypatch):
    doc_id = extract(c)
    monkeypatch.setenv("EXTRACTION_KEY", Fernet.generate_key().decode())
    r = c.http.get(f"{V1}/documents/{doc_id}/extraction", headers=c.headers)
    assert (r.status_code, r.json()["code"]) == (500, "extraction_unreadable")
    assert RAW not in r.text and NAME not in r.text
