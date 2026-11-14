"""D2 verification with synthetic canary strings, without a database: the wrong or rotated key fails closed in both the
field and the raw-text path, nothing is lost or changed by the failed attempt, and neither a canary nor a key reaches an
error, a traceback or a log line, including on the failure path of the worker. The PostgreSQL side (a full data dump of
every table, the retention rule, the API and its logs) is in test_extraction_privacy_pg.py. Synthetic data only; the canaries
are fixed test strings and the keys are generated for the test."""
import copy
import json
import logging
import traceback

import pytest
from cryptography.fernet import Fernet

from swasthyoid.capture import extraction, extraction_crypto as crypto
from swasthyoid.tests.test_extraction_lease import Conn, world  # noqa: F401

CANARY_NAME = "CANARY-PRESCRIBER-7f3a"
CANARY_PRINTED = "CANARY-PRINTED-NAME-91bc"
CANARY_ALLERGY = "CANARY-ALLERGY-c40d"
CANARY_RAW = "CANARY-RAW-TEXT-55e2"
CANARIES = (CANARY_NAME, CANARY_PRINTED, CANARY_ALLERGY, CANARY_RAW)
FIELDS = {"prescriber_name": {"value": CANARY_NAME, "confidence": 0.9},
          "printed_patient_name": {"value": CANARY_PRINTED, "confidence": 0.9},
          "allergy_text": {"value": CANARY_ALLERGY, "confidence": 0.9}}


def everything(error):
    """All the text an error can show: message, repr, the full traceback with its chain, and its arguments."""
    chain = "".join(traceback.format_exception(type(error), error, error.__traceback__))
    return f"{error!s}|{error!r}|{chain}|{error.args!r}"


@pytest.fixture
def keys(monkeypatch):
    """(the key the data was sealed with, another valid key). The first is the active key on return."""
    first, second = Fernet.generate_key().decode(), Fernet.generate_key().decode()
    monkeypatch.setenv("EXTRACTION_KEY", first)
    return first, second


def test_the_sealed_fields_and_text_hold_no_canary_and_no_field_name(keys):
    sealed, token = crypto.seal_fields(FIELDS), crypto.seal_text(CANARY_RAW)
    stored = json.dumps(sealed) + token
    assert not any(c in stored for c in CANARIES) and "allergy_text" not in stored and "printed_patient_name" not in stored
    assert crypto.open_fields(sealed) == FIELDS and crypto.open_text(token) == CANARY_RAW  # the right key reads them


def test_a_rotated_key_fails_closed_in_the_field_path_and_the_raw_text_path(keys):
    first, second = keys
    sealed, token = crypto.seal_fields(FIELDS), crypto.seal_text(CANARY_RAW)
    before = (copy.deepcopy(sealed), token)
    import os
    os.environ["EXTRACTION_KEY"] = second  # rotation without re-sealing (the monkeypatch fixture restores the original)
    for attempt in (lambda: crypto.open_fields(sealed), lambda: crypto.open_text(token)):
        with pytest.raises(crypto.Undecryptable) as failure:
            attempt()
        shown = everything(failure.value)
        assert not any(c in shown for c in CANARIES) and first not in shown and second not in shown
        assert failure.value.__cause__ is None and failure.value.__suppress_context__  # nothing chained to the error
        assert failure.value.args == () and str(failure.value) == ""  # a controlled error: no detail at all
    assert (sealed, token) == before  # the stored ciphertext was not touched by the failed reads
    os.environ["EXTRACTION_KEY"] = first
    assert crypto.open_fields(sealed) == FIELDS and crypto.open_text(token) == CANARY_RAW  # the data is intact


def test_a_wrong_key_never_returns_a_partial_or_plain_value(keys):
    _, second = keys
    sealed = crypto.seal_fields(FIELDS)
    import os
    os.environ["EXTRACTION_KEY"] = second
    results = []
    for attempt in (lambda: crypto.open_fields(sealed), lambda: crypto.open_text(sealed["enc"])):
        try:
            results.append(attempt())
        except crypto.Undecryptable:
            pass
    assert results == []  # an error each time: no dict, no string, no fallback to the stored form


def test_the_right_key_with_a_damaged_plaintext_fails_closed_without_showing_it(keys):
    """A token that decrypts but is not the expected JSON (damaged data, or sealed by other software)."""
    first, _ = keys
    for damaged in (CANARY_NAME.encode() + b" is not json", b"\xff" + CANARY_NAME.encode()):
        bad = {"v": 1, "enc": Fernet(first).encrypt(damaged).decode()}
        with pytest.raises(crypto.Undecryptable) as failure:
            crypto.open_fields(bad)
        assert CANARY_NAME not in everything(failure.value) and first not in everything(failure.value)


def test_a_missing_or_invalid_key_never_shows_the_key(monkeypatch, keys):
    first, _ = keys
    for value in ("not-a-key-CANARY-KEY-0a1b", "", None):
        if value is None:
            monkeypatch.delenv("EXTRACTION_KEY")
        else:
            monkeypatch.setenv("EXTRACTION_KEY", value)
        with pytest.raises(crypto.KeyError_) as problem:
            crypto.seal_fields(FIELDS)
        assert "CANARY-KEY" not in everything(problem.value) and first not in everything(problem.value)
        with pytest.raises(RuntimeError) as refused:
            extraction._settings({})  # the worker and the API refuse before anything is claimed or stored
        assert "CANARY-KEY" not in everything(refused.value) and first not in everything(refused.value)


# ---- the failure path of the worker: logs and what is written

class Recording(Conn):
    def __init__(self, events, **kw):
        super().__init__(events, **kw)
        self.params = []

    def execute(self, sql, params=None):
        self.params.append(params)
        return super().execute(sql, params)


def test_an_engine_failure_carrying_the_canaries_reaches_neither_the_log_nor_the_database(world, monkeypatch, caplog, keys):
    secret = " ".join(CANARIES) + " " + keys[0]

    def engine_that_fails_with_text(*args):
        raise RuntimeError(secret)

    monkeypatch.setattr(extraction, "_run_engine", engine_that_fails_with_text)
    conn = Recording(world.events)
    with caplog.at_level(logging.DEBUG):  # every logger, every level
        world.run(conn)
    written = repr(conn.params)
    assert "fail" in world.events and "RuntimeError" in written  # the failure was recorded by its type only
    assert not any(c in written for c in CANARIES) and keys[0] not in written
    assert not any(c in caplog.text for c in CANARIES) and keys[0] not in caplog.text
    assert all(r.exc_info is None for r in caplog.records)  # no traceback is attached to any record


def test_a_lost_lease_or_a_stale_write_logs_no_canary(world, monkeypatch, caplog, keys):
    def engine_that_loses_the_lease(*args):
        raise extraction.LeaseLost()

    monkeypatch.setattr(extraction, "_run_engine", engine_that_loses_the_lease)
    with caplog.at_level(logging.DEBUG):
        world.run(Conn(world.events))
    assert not any(c in caplog.text for c in CANARIES) and keys[0] not in caplog.text
