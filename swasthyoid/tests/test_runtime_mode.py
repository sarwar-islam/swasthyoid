"""Test mode needs APP_ENV=test AND SWASTHYOID_TEST_MODE_CONFIRM=1 (4A plan R10, owner Option C).
Checked at API startup, at the worker entry points (run_due, extract) and in the OCR children."""
import logging
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from swasthyoid import runtime_mode
from swasthyoid.api.main import app
from swasthyoid.capture import extraction

CONFIRM = runtime_mode.CONFIRM
APP_ENVS = [None, "production", "development", "test", "TEST", " test"]
MARKERS = [None, "1", "0", "true", " 1"]


def set_env(monkeypatch, app_env, marker):
    for name, value in (("APP_ENV", app_env), (CONFIRM, marker)):
        monkeypatch.delenv(name, raising=False) if value is None else monkeypatch.setenv(name, value)


@pytest.mark.parametrize("app_env", APP_ENVS)
@pytest.mark.parametrize("marker", MARKERS)
def test_only_both_exact_values_enable_test_mode(monkeypatch, app_env, marker):
    set_env(monkeypatch, app_env, marker)
    assert runtime_mode.is_test_mode() is (app_env == "test" and marker == "1")
    if app_env == "test" and marker != "1":
        with pytest.raises(RuntimeError, match=CONFIRM):  # fail closed
            runtime_mode.check_test_mode_config()
    else:
        runtime_mode.check_test_mode_config()


def no_database(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)  # startup then skips the schema
    monkeypatch.delenv("DEV_LOG_CODES", raising=False)


@pytest.mark.parametrize("marker", [None, "0", "true"])
def test_api_refuses_to_start_with_app_env_test_but_no_confirmation(monkeypatch, marker):
    no_database(monkeypatch)
    set_env(monkeypatch, "test", marker)
    with pytest.raises(RuntimeError, match=CONFIRM):
        with TestClient(app):
            pass


def test_api_starts_in_test_mode_with_both(monkeypatch):
    no_database(monkeypatch)
    set_env(monkeypatch, "test", "1")
    with TestClient(app) as http:
        assert http.get("/health").status_code == 200


def test_api_with_the_confirmation_alone_starts_with_test_mode_off_and_warns(monkeypatch, caplog):
    no_database(monkeypatch)
    set_env(monkeypatch, "production", "1")
    with caplog.at_level(logging.WARNING), TestClient(app) as http:
        assert http.get("/health").status_code == 200
    assert not runtime_mode.is_test_mode()
    assert any(CONFIRM in r.getMessage() and "test mode is off" in r.getMessage() for r in caplog.records)


def legacy_engine(pages, doc_type):  # never reached: refused before anything is claimed
    raise AssertionError("called")


@pytest.mark.parametrize("call", ["run_due", "extract"])
def test_worker_entry_refuses_app_env_test_without_confirmation(monkeypatch, call):
    set_env(monkeypatch, "test", None)
    conn = object()  # refused before the database is touched
    with pytest.raises(RuntimeError, match=CONFIRM):
        if call == "run_due":
            extraction.run_due(conn, legacy_engine, hard_timeout=timedelta(minutes=1))
        else:
            extraction.extract(conn, "doc", 1, legacy_engine, hard_timeout=timedelta(minutes=1))


@pytest.mark.parametrize("app_env", [None, "production", "development"])
def test_confirmation_alone_does_not_allow_the_legacy_engine(monkeypatch, app_env):
    set_env(monkeypatch, app_env, "1")
    with pytest.raises(RuntimeError, match="deprecated"):
        extraction.run_due(object(), legacy_engine, hard_timeout=timedelta(minutes=1))
    with pytest.raises(RuntimeError, match="in-process"):
        extraction.run_due(object(), legacy_engine, hard_timeout=None)
