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


# ---- D2 verification with canary strings: a full data dump, a rotated key, and the failure path (CI: Linux, PostgreSQL 16)

CANARY_NAME = "CANARY-PRESCRIBER-7f3a"
CANARY_PRINTED = "CANARY-PRINTED-NAME-91bc"
CANARY_ALLERGY = "CANARY-ALLERGY-c40d"
CANARY_RAW = "CANARY-RAW-TEXT-55e2"
CANARIES = (CANARY_NAME, CANARY_PRINTED, CANARY_ALLERGY, CANARY_RAW)


def canary_engine(pages, doc_type):
    return {"engine": "fake-ocr", "raw_text": CANARY_RAW, "fields": {
        "prescriber_name": {"value": CANARY_NAME, "confidence": 0.9},
        "printed_patient_name": {"value": CANARY_PRINTED, "confidence": 0.9},
        "allergy_text": {"value": CANARY_ALLERGY, "confidence": 0.9}}}


def failing_engine(pages, doc_type):
    raise RuntimeError(f"{CANARY_RAW} {CANARY_NAME} must not be stored")


def full_dump(conn, only=None):
    """The data of every base table of the public schema in COPY text format, as bytes: what the data section of a
    pg_dump holds (the same rows, the same escaping). `only` limits it to the named tables."""
    names = [r[0] for r in conn.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'public' "
                                        "AND table_type = 'BASE TABLE' ORDER BY 1").fetchall()]
    out = b""
    for name in (n for n in names if only is None or n in only):
        with conn.cursor().copy(f'COPY "{name}" TO STDOUT') as copy:
            for chunk in copy:
                out += bytes(chunk)
    return out


def canary_free(*texts):
    return not any(canary in text for text in texts for canary in CANARIES)


def test_a_full_dump_holds_no_canary_after_success_failure_and_manual_entry_and_keeps_the_metadata(c, caplog):
    import os
    import shutil
    import subprocess
    from pathlib import Path

    import psycopg
    ok = upload(c, c.headers)
    with c.connect() as conn:
        assert extraction.run_due(conn, canary_engine) == 1  # needs_review, with all three sensitive fields and a raw text
    failed = upload(c, c.headers)
    with c.connect() as conn:
        extraction.run_due(conn, failing_engine, backoff=timedelta(0))  # fails every attempt; its error text holds canaries
        assert job(conn, failed)[0] == "extraction_failed"
    manual = upload(c, c.headers)
    assert c.http.post(f"{V1}/documents/{manual}/manual-entry", headers=c.headers).status_code == 200

    with c.connect() as conn:
        dump = full_dump(conn)
        assert canary_free(dump.decode("utf-8", "replace"))  # no sensitive field, no raw text, no error text, in any table
        # the metadata is intact: engine, the hash of the raw text, the ids, and the failure's code and nothing more
        assert b"fake-ocr" in dump and crypto.sha256(CANARY_RAW).encode() in dump and ok.encode() in dump
        assert b"RuntimeError" in dump and b"extraction_failed" in dump and b"needs_review" in dump
        assert conn.execute("SELECT count(*) FROM extraction_raw_texts WHERE document_id = %s", [ok]).fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM extraction_raw_texts WHERE document_id = %s", [manual]).fetchone()[0] == 0
        fields, raw_text, sha = conn.execute(
            "SELECT fields, raw_text, raw_text_sha256 FROM extractions WHERE document_id = %s", [ok]).fetchone()
        assert crypto.is_sealed(fields) and raw_text == "" and sha == crypto.sha256(CANARY_RAW)
        got = extraction.latest(conn, ok)  # the owner of the key still reads all three, and the raw text
        assert got["raw_text"] == CANARY_RAW and got["fields"]["allergy_text"]["value"] == CANARY_ALLERGY
        assert got["fields"]["printed_patient_name"]["value"] == CANARY_PRINTED

        # the raw text lives only in the deletable store and is gone, ciphertext included, once the document is closed
        token = conn.execute("SELECT ciphertext FROM extraction_raw_texts WHERE document_id = %s", [ok]).fetchone()[0]
        assert token.encode() in dump
        documents.set_status(conn, ok, "verified")
        after = full_dump(conn)
        assert token.encode() not in after and canary_free(after.decode("utf-8", "replace"))
        assert crypto.sha256(CANARY_RAW).encode() in after  # the append-only hash remains

        # the append-only guarantees hold for the audit log and the extraction rows
        for sql in ("UPDATE audit_logs SET result = 'x'", "DELETE FROM audit_logs", "UPDATE extractions SET engine = 'x'"):
            with pytest.raises(psycopg.Error, match="append-only"):
                conn.execute(sql)

    # a real pg_dump, when the machine has one that can dump this server (an older client refuses; that is not a failure)
    exe = shutil.which("pg_dump")
    if exe:
        done = subprocess.run([exe, "--data-only", os.environ["DATABASE_URL"]], capture_output=True, timeout=300)
        if done.returncode == 0:
            assert canary_free(done.stdout.decode("utf-8", "replace"))
    # files on disk (the document store holds only the encrypted originals): no canary in any of them
    for path in Path(os.environ["DOCUMENT_STORE"]).rglob("*"):
        if path.is_file():
            assert canary_free(path.read_bytes().decode("latin-1"))
    assert canary_free(caplog.text)  # nor in any log line of the whole run, DEBUG included


def test_a_rotated_key_changes_nothing_leaks_nothing_and_the_original_key_works_again(c, caplog, monkeypatch):
    import os
    doc_id = upload(c, c.headers)
    with c.connect() as conn:
        assert extraction.run_due(conn, canary_engine) == 1
        tables = ("extractions", "extraction_raw_texts", "documents")
        before, state = full_dump(conn, tables), job(conn, doc_id)
        token = conn.execute("SELECT ciphertext FROM extraction_raw_texts WHERE document_id = %s", [doc_id]).fetchone()[0]
    original, other = os.environ["EXTRACTION_KEY"], Fernet.generate_key().decode()
    monkeypatch.setenv("EXTRACTION_KEY", other)

    r = c.http.get(f"{V1}/documents/{doc_id}/extraction", headers=c.headers)
    assert (r.status_code, r.json()["code"]) == (500, "extraction_unreadable")  # a controlled error, never garbage
    assert canary_free(r.text) and original not in r.text and other not in r.text
    with c.connect() as conn:
        with pytest.raises(crypto.Undecryptable):
            extraction.latest(conn, doc_id)  # the fields path
        with pytest.raises(crypto.Undecryptable):
            crypto.open_text(token)  # the raw-text path on its own
        assert full_dump(conn, tables) == before  # the stored ciphertext was not corrupted or overwritten
        assert job(conn, doc_id) == state and state[0] == "needs_review"  # no silent move to verified
        assert conn.execute("SELECT count(*) FROM documents WHERE status = 'verified'").fetchone()[0] == 0
        assert conn.execute("SELECT count(*) FROM events").fetchone()[0] == 0
    assert canary_free(caplog.text) and original not in caplog.text and other not in caplog.text

    monkeypatch.setenv("EXTRACTION_KEY", original)  # the key is back: everything reads again, nothing was lost
    with c.connect() as conn:
        got = extraction.latest(conn, doc_id)
    assert got["raw_text"] == CANARY_RAW and got["fields"]["prescriber_name"]["value"] == CANARY_NAME


def test_a_failing_ocr_child_leaks_no_canary_into_the_log_the_error_column_or_the_dump(c, caplog):
    from swasthyoid.tests import fake_engines
    doc_id = upload(c, c.headers)
    with c.connect() as conn:
        extraction.run_due(conn, fake_engines.boom, hard_timeout=timedelta(seconds=60), heartbeat=timedelta(seconds=1),
                           backoff=timedelta(0))
        error = conn.execute("SELECT extraction_error FROM documents WHERE id = %s", [doc_id]).fetchone()[0]
        dump = full_dump(conn).decode("utf-8", "replace")
    assert error == "RuntimeError"  # the type, never the message of the engine's exception
    assert "synthetic patient text" not in caplog.text and "synthetic patient text" not in dump
    assert all(r.exc_info is None for r in caplog.records)  # no traceback is attached to any log record
