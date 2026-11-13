"""Validation of the extraction options (S4): _settings(), claim(), and the entry points.

No database: invalid options must fail before anything is claimed or probed, so a bare object()
stands in for the connection and any use of it would fail the test. Synthetic values only."""
import contextlib
import math
from datetime import timedelta

import pytest

from swasthyoid import runtime_mode
from swasthyoid.capture import extraction, ocr
from swasthyoid.tests import fake_engines

SECOND = timedelta(seconds=1)
LEAK = "LEAKED-VALUE-98765"  # must never appear in an error message


@pytest.fixture
def test_mode(monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv(runtime_mode.CONFIRM, "1")


# ---- defaults and valid boundaries

def test_the_shipped_defaults_are_valid():
    o = extraction._settings({})
    assert o["availability_timeout"] == ocr.AVAILABILITY_TIMEOUT and o["heartbeat"] < o["lease"]


@pytest.mark.parametrize("given", [
    {"backoff": timedelta(0)},                                        # zero backoff is allowed
    {"lease": timedelta(microseconds=2), "heartbeat": timedelta(microseconds=1)},
    {"hard_timeout": timedelta(microseconds=1)},
    {"availability_timeout": timedelta(microseconds=1)},
    {"threshold": 0}, {"threshold": 1}, {"threshold": 0.0}, {"threshold": 1.0}, {"threshold": 0.5},
    {"ai_threshold": None}, {"ai_threshold": 0}, {"ai_threshold": 1}, {"ai_threshold": 0.85},
    {"max_attempts": 1}, {"max_attempts": 100},
    {"lease": timedelta(seconds=60), "heartbeat": timedelta(seconds=59, microseconds=999999)},
])
def test_valid_boundaries_are_accepted(given):
    o = extraction._settings(given)
    for key, value in given.items():
        assert o[key] == value


def test_availability_timeout_none_resolves_to_the_default_timedelta():
    o = extraction._settings({"availability_timeout": None})
    assert o["availability_timeout"] == ocr.AVAILABILITY_TIMEOUT
    assert isinstance(o["availability_timeout"], timedelta)


def test_hard_timeout_none_is_still_test_mode_only_and_skips_the_relationship(test_mode, monkeypatch):
    o = extraction._settings({"hard_timeout": None, "lease": SECOND, "heartbeat": 5 * SECOND})
    assert o["hard_timeout"] is None
    monkeypatch.delenv("APP_ENV")
    with pytest.raises(RuntimeError, match="APP_ENV=test"):  # the existing refusal comes first, unchanged
        extraction._settings({"hard_timeout": None})


# ---- invalid values: every option, types and ranges

BAD_DURATIONS = [timedelta(0), timedelta(seconds=-1), 60, 4.0, True, "60", None, float("nan")]
BAD_FRACTIONS = [-0.01, 1.01, 2, -1, math.nan, math.inf, -math.inf, True, False, "0.5", [0.5]]
BAD_ATTEMPTS = [0, -1, True, False, 3.0, 1.5, "3", None]


def refused(given, option):
    with pytest.raises((TypeError, ValueError)) as e:
        extraction._settings(given)
    assert option in str(e.value)
    return e.value


@pytest.mark.parametrize("option", ["lease", "heartbeat", "availability_timeout"])
@pytest.mark.parametrize("bad", [b for b in BAD_DURATIONS if b is not None])
def test_invalid_durations_are_refused(option, bad):
    refused({option: bad}, option)


@pytest.mark.parametrize("option", ["lease", "heartbeat"])
def test_lease_and_heartbeat_may_not_be_none(option):
    refused({option: None}, option)


@pytest.mark.parametrize("bad", [b for b in BAD_DURATIONS if b is not None])
def test_invalid_hard_timeouts_are_refused(bad):
    refused({"hard_timeout": bad}, "hard_timeout")


@pytest.mark.parametrize("bad", [timedelta(seconds=-1), 0, 60, 1.5, True, "1", None])
def test_invalid_backoffs_are_refused(bad):
    refused({"backoff": bad}, "backoff")


@pytest.mark.parametrize("bad", BAD_ATTEMPTS)
def test_invalid_max_attempts_are_refused(bad):
    refused({"max_attempts": bad}, "max_attempts")


@pytest.mark.parametrize("bad", BAD_FRACTIONS + [None])
def test_invalid_thresholds_are_refused(bad):
    refused({"threshold": bad}, "threshold")


@pytest.mark.parametrize("bad", BAD_FRACTIONS)
def test_invalid_ai_thresholds_are_refused(bad):
    refused({"ai_threshold": bad}, "ai_threshold")


def test_error_types_are_type_error_for_types_and_value_error_for_ranges():
    with pytest.raises(TypeError):
        extraction._settings({"lease": 60})
    with pytest.raises(ValueError):
        extraction._settings({"lease": timedelta(0)})
    with pytest.raises(TypeError):
        extraction._settings({"max_attempts": True})
    with pytest.raises(ValueError):
        extraction._settings({"max_attempts": 0})
    with pytest.raises(TypeError):
        extraction._settings({"unknown": 1})  # unchanged


@pytest.mark.parametrize("given", [
    {"lease": timedelta(seconds=-98765)}, {"heartbeat": LEAK}, {"hard_timeout": LEAK},
    {"availability_timeout": LEAK}, {"backoff": LEAK}, {"max_attempts": LEAK}, {"threshold": LEAK},
    {"ai_threshold": LEAK}, {"max_attempts": -98765}, {"threshold": -98765}, {"availability_timeout": 98765},
])
def test_error_messages_do_not_expose_the_supplied_value(given):
    with pytest.raises((TypeError, ValueError)) as e:
        extraction._settings(given)
    assert "98765" not in str(e.value) and "LEAK" not in str(e.value)


# ---- the heartbeat / lease relationship (unchanged)

@pytest.mark.parametrize("heartbeat", [timedelta(seconds=60), timedelta(seconds=61)])
def test_heartbeat_must_be_shorter_than_the_lease(heartbeat):
    with pytest.raises(ValueError, match="heartbeat"):
        extraction._settings({"lease": timedelta(seconds=60), "heartbeat": heartbeat})


# ---- constants that were reconfigured

@pytest.mark.parametrize("constant, bad, option", [
    ("LEASE", timedelta(0), "lease"), ("HEARTBEAT", timedelta(seconds=-1), "heartbeat"),
    ("HARD_TIMEOUT", timedelta(0), "hard_timeout"), ("BACKOFF", timedelta(seconds=-1), "backoff"),
    ("MAX_ATTEMPTS", 0, "max_attempts"), ("CONFIDENCE_THRESHOLD", 1.5, "threshold"),
    ("CLOUD_AI_THRESHOLD", -0.1, "ai_threshold"),
])
def test_invalid_reconfigured_constants_are_refused(monkeypatch, constant, bad, option):
    monkeypatch.setattr(extraction, constant, bad)
    refused({}, option)


@pytest.mark.parametrize("bad", [None, timedelta(seconds=-1), timedelta(0), 30])
def test_an_invalid_ocr_availability_timeout_constant_is_refused(monkeypatch, bad):
    monkeypatch.setattr(ocr, "AVAILABILITY_TIMEOUT", bad)
    refused({}, "availability_timeout")


# ---- the entry points refuse before anything is claimed or probed

def fail_if_probed(monkeypatch):
    def probed(timeout=None):
        raise AssertionError("the adapter was probed")
    monkeypatch.setattr(ocr, "check_available", probed)


INVALID_OPTIONS = [{"lease": timedelta(0)}, {"max_attempts": 0}, {"threshold": 2}, {"ai_threshold": math.nan},
                   {"backoff": timedelta(seconds=-1)}, {"heartbeat": 5}, {"availability_timeout": -1},
                   {"hard_timeout": timedelta(0)}]


@pytest.mark.parametrize("options", INVALID_OPTIONS)
def test_run_due_refuses_invalid_options_before_claiming_or_probing(monkeypatch, options):
    fail_if_probed(monkeypatch)
    with pytest.raises((TypeError, ValueError)):
        extraction.run_due(object(), **options)  # any use of the connection would raise AttributeError
    with pytest.raises((TypeError, ValueError)):
        extraction.run_due(object(), fake_engines.good, **options)


@pytest.mark.parametrize("options", INVALID_OPTIONS)
def test_extract_refuses_invalid_options_before_claiming_or_probing(monkeypatch, options):
    fail_if_probed(monkeypatch)
    with pytest.raises((TypeError, ValueError)):
        extraction.extract(object(), "doc", 1, **options)


def test_the_availability_timeout_reaches_the_probe_as_a_timedelta(monkeypatch):
    seen = []

    def check_available(timeout=None):
        seen.append(timeout)
        raise ocr.AdapterError("engine_unavailable")

    monkeypatch.setattr(ocr, "check_available", check_available)
    assert extraction.run_due(object(), availability_timeout=None) == 0
    assert extraction.run_due(object(), availability_timeout=timedelta(seconds=7)) == 0
    assert extraction.run_due(object()) == 0
    assert seen == [ocr.AVAILABILITY_TIMEOUT, timedelta(seconds=7), ocr.AVAILABILITY_TIMEOUT]
    assert all(isinstance(t, timedelta) for t in seen)


# ---- claim()

class QuietConn:
    """Autocommit connection whose query finds nothing; records that a query was reached."""
    autocommit = True

    def __init__(self):
        self.queried = False

    def transaction(self):
        return contextlib.nullcontext()

    def cursor(self, **kwargs):
        return self

    def execute(self, *args, **kwargs):
        self.queried = True
        return self

    def fetchone(self):
        return None


class UntouchedConn(QuietConn):
    def execute(self, *args, **kwargs):
        raise AssertionError("a query ran")

    def transaction(self):
        raise AssertionError("a transaction was opened")


@pytest.mark.parametrize("kwargs, option", [
    ({"lease": timedelta(0)}, "lease"), ({"lease": timedelta(seconds=-1)}, "lease"), ({"lease": 60}, "lease"),
    ({"lease": 0}, "lease"), ({"max_attempts": 0}, "max_attempts"), ({"max_attempts": -1}, "max_attempts"),
    ({"max_attempts": True}, "max_attempts"), ({"max_attempts": 1.5}, "max_attempts"),
])
def test_claim_refuses_explicit_invalid_values_before_any_query(kwargs, option):
    with pytest.raises((TypeError, ValueError)) as e:
        extraction.claim(UntouchedConn(), **kwargs)
    assert option in str(e.value)


@pytest.mark.parametrize("kwargs", [
    {}, {"lease": None}, {"max_attempts": None}, {"lease": SECOND, "max_attempts": 1},
])
def test_claim_reaches_the_query_with_valid_or_omitted_values(kwargs):
    conn = QuietConn()
    assert extraction.claim(conn, **kwargs) is None and conn.queried


def test_claim_still_needs_an_autocommit_connection():
    conn = QuietConn()
    conn.autocommit = False
    with pytest.raises(ValueError, match="autocommit"):
        extraction.claim(conn, lease=timedelta(0))  # the connection check comes first, as before
