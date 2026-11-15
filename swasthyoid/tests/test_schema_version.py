"""SCHEMA_VERSION is stored with every extraction and checked when it is read (extractions.schema_version).

A missing version (a row written before the column) or one the code does not support fails closed: latest() raises
SchemaVersionError before decrypting anything, and the API answers 500 extraction_unreadable with no content.
The first tests need no database; the rest run against PostgreSQL (CI). Synthetic data only."""
from types import SimpleNamespace

import pytest

from swasthyoid.capture import extraction, extraction_crypto as crypto
from swasthyoid.tests.test_extraction_integration import V1, ocr, patient, prod, upload  # noqa: F401


# ---- without a database

def test_only_the_supported_version_passes_the_check():
    assert extraction.check_schema_version(extraction.SCHEMA_VERSION) == extraction.SCHEMA_VERSION
    assert extraction.SUPPORTED_SCHEMA_VERSIONS == {extraction.SCHEMA_VERSION}
    with pytest.raises(extraction.SchemaVersionError) as missing:
        extraction.check_schema_version(None)
    assert missing.value.args == ("missing",)
    for bad in ("", "0", "2", "01", " 1", "1.0", 1, b"1", ["1"]):
        with pytest.raises(extraction.SchemaVersionError) as unsupported:
            extraction.check_schema_version(bad)
        assert unsupported.value.args == ("unsupported",)


class FakeConn:
    """Records execute() calls; cursor().execute().fetchone() returns `row`; every other fetchone() returns None."""

    def __init__(self, row=None):
        self.row, self.calls = row, []

    def execute(self, sql, params=()):
        self.calls.append((sql, params))
        return SimpleNamespace(fetchone=lambda: None)

    def cursor(self, row_factory=None):
        return SimpleNamespace(execute=lambda sql, params=(): SimpleNamespace(fetchone=lambda: self.row))


def stored_row(schema_version):
    return {"id": "x", "version": 1, "engine": "fake", "fields": crypto.seal_fields({"advice_text": {"value": "synthetic"}}),
            "raw_text": "", "raw_text_sha256": crypto.sha256(""), "schema_version": schema_version,
            "created_at": None, "patient_id": "p"}


def test_store_writes_the_current_schema_version_into_its_own_column():
    conn = FakeConn()
    extraction._store(conn, "doc", 1, "manual", {}, "")
    sql, params = conn.calls[0]
    assert "schema_version" in sql and params[-1] == extraction.SCHEMA_VERSION


def test_store_refuses_to_write_a_version_the_reader_would_refuse(monkeypatch):
    monkeypatch.setattr(extraction, "SCHEMA_VERSION", "2")  # bumped without updating SUPPORTED_SCHEMA_VERSIONS
    conn = FakeConn()
    with pytest.raises(extraction.SchemaVersionError):
        extraction._store(conn, "doc", 1, "manual", {}, "")
    assert conn.calls == []  # nothing written


def test_latest_reads_a_row_of_the_supported_version():
    got = extraction.latest(FakeConn(stored_row(extraction.SCHEMA_VERSION)), "doc")
    assert got["fields"] == {"advice_text": {"value": "synthetic"}} and got["printed_name_check"] == "not_checked"


@pytest.mark.parametrize("version, reason", [(None, "missing"), ("2", "unsupported"), ("999", "unsupported")])
def test_latest_fails_closed_before_decrypting_on_a_missing_or_unsupported_version(monkeypatch, version, reason):
    monkeypatch.setattr(crypto, "open_fields", lambda stored: pytest.fail("decrypted a refused row"))
    with pytest.raises(extraction.SchemaVersionError) as failure:
        extraction.latest(FakeConn(stored_row(version)), "doc")
    assert failure.value.args == (reason,)


# ---- against PostgreSQL (CI)

def version_of(conn, doc_id):
    return conn.execute("SELECT schema_version FROM extractions WHERE document_id = %s ORDER BY version DESC LIMIT 1",
                        [doc_id]).fetchone()[0]


def test_an_ocr_result_and_a_manual_entry_both_store_the_schema_version(prod):  # noqa: F811
    headers = patient(prod)
    read, typed = upload(prod, headers), upload(prod, headers)
    assert prod.http.post(f"{V1}/documents/{typed}/manual-entry", headers=headers).status_code == 200
    with prod.connect() as conn:
        assert extraction.run_due(conn, ocr) == 1
        assert version_of(conn, read) == version_of(conn, typed) == extraction.SCHEMA_VERSION
        assert extraction.latest(conn, read)["fields"]["prescriber_name"]["manual_entry"] is True  # read back fine


def test_an_unsupported_version_fails_closed_in_the_reader_and_the_api(prod):  # noqa: F811
    headers = patient(prod)
    doc_id = upload(prod, headers)
    with prod.connect() as conn:
        assert extraction.run_due(conn, ocr) == 1
        conn.execute("INSERT INTO extractions (id, document_id, version, engine, fields, raw_text_sha256, schema_version) "
                     "VALUES (gen_random_uuid(), %s, 2, 'later', '{}', %s, '999')", [doc_id, crypto.sha256("")])
        with pytest.raises(extraction.SchemaVersionError):
            extraction.latest(conn, doc_id)  # the newest row is version 999: refused, the older row is not used instead
    r = prod.http.get(f"{V1}/documents/{doc_id}/extraction", headers=headers)
    assert (r.status_code, r.json()["code"]) == (500, "extraction_unreadable")
    assert "prescriber" not in r.text


def test_the_database_refuses_a_malformed_schema_version(prod):  # noqa: F811
    import psycopg
    doc_id = upload(prod, patient(prod))
    with prod.connect() as conn:
        for n, bad in enumerate(("", "abc", "0", "01", "1.0", "1234567890"), 1):
            with pytest.raises(psycopg.errors.CheckViolation):
                conn.execute("INSERT INTO extractions (id, document_id, version, engine, fields, schema_version) "
                             "VALUES (gen_random_uuid(), %s, %s, 'x', '{}', %s)", [doc_id, n, bad])
