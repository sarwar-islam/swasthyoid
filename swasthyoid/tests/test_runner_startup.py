"""Step 8 slice 8.1: the runner's startup skeleton (swasthyoid/workers/extract.py).

Covers only what 8.1 owns: the main-module guard, import purity, the first runtime safety
check and its ordering, configuration validation, read-only schema validation, and that nothing
is claimed or processed. Spawn proof, the processing cycle, signals and recovery belong to later
runner slices and are not claimed here.

A local TCP "tripwire" stands in for the database: any connection attempt, including one made
inside the C library (which raises no Python audit event), is counted. Synthetic data only.
"""
import ast
import os
import re
import socket
import subprocess
import sys
import threading
import uuid
from pathlib import Path

import psycopg
import pytest
from psycopg.conninfo import make_conninfo

from swasthyoid import db
from swasthyoid.tests.conftest import require_database
from swasthyoid.tests.test_extraction_integration import job, patient, prod, upload  # noqa: F401
from swasthyoid.workers import extract

REPO = Path(__file__).resolve().parents[2]
MODULE = REPO / "swasthyoid" / "workers" / "extract.py"
CAPTURE_SCHEMA = REPO / "swasthyoid" / "capture" / "schema.sql"
COMMAND = [sys.executable, "-m", "swasthyoid.workers.extract"]
SECRET = "SECRETPW"
SENTINEL = "x9z-sentinel-value"


class Tripwire:
    """Accepts and closes every connection, and counts them."""

    def __init__(self):
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(16)
        self.sock.settimeout(0.1)
        self.port = self.sock.getsockname()[1]
        self.count = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()

    def _serve(self):
        while not self._stop.is_set():
            try:
                connection, _ = self.sock.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            self.count += 1
            connection.close()

    def stop(self):
        self._stop.set()
        self._thread.join(2)
        self.sock.close()

    @property
    def uri(self):
        return f"postgresql://runner:{SECRET}@127.0.0.1:{self.port}/db?connect_timeout=5"

    @property
    def keywords(self):
        return f"host=127.0.0.1 port={self.port} user=runner password={SECRET} dbname=db connect_timeout=5"

    @property
    def defaults(self):
        """Library defaults pointed at the tripwire: if the runner ever fell back to them, it shows."""
        return {"PGHOST": "127.0.0.1", "PGPORT": str(self.port), "PGCONNECT_TIMEOUT": "5"}


@pytest.fixture
def tripwire():
    wire = Tripwire()
    yield wire
    wire.stop()


def clean_env(**overrides):
    """The test environment without anything the runner reads; None removes a name."""
    env = {k: v for k, v in os.environ.items()
           if k not in ("APP_ENV", "SWASTHYOID_TEST_MODE_CONFIRM", "EXTRACTION_POLL_SECONDS", "DATABASE_URL")
           and not k.startswith("PG")}
    for key, value in overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    return env


def run_runner(*args, env):
    return subprocess.run([*COMMAND, *args], cwd=REPO, env=env, capture_output=True, text=True, timeout=120)


# ---- AC1 structure: real module execution only through the guarded entry point

def test_top_level_holds_only_definitions_and_the_guarded_call():
    body = ast.parse(MODULE.read_text(encoding="utf-8")).body
    for node in body[:-1]:
        is_docstring = (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant)
                        and isinstance(node.value.value, str))
        assert is_docstring or isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef,
                                                 ast.ClassDef, ast.Assign)), ast.dump(node)[:100]
        if isinstance(node, ast.Assign):  # constants: no call at import time
            assert not any(isinstance(n, ast.Call) for n in ast.walk(node.value)), ast.dump(node)[:100]
    guard = body[-1]
    assert isinstance(guard, ast.If) and ast.unparse(guard.test) == "__name__ == '__main__'"
    assert [ast.unparse(statement) for statement in guard.body] == ["sys.exit(main())"] and not guard.orelse
    assert any(isinstance(n, ast.FunctionDef) and n.name == "main" for n in body)


def test_runner_has_no_reference_to_the_processing_cycle_or_schema_application():
    names = set()
    for node in ast.walk(ast.parse(MODULE.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update(alias.name.split(".")[-1] for alias in node.names)
            if isinstance(node, ast.ImportFrom) and node.module:
                names.update(node.module.split("."))
    assert not names & {"run_due", "extract", "claim", "apply_schema", "extraction", "ocr"}


# ---- AC2: importing the runner does nothing

IMPORT_PROBE = r'''
import logging, sys, threading
events = []
WATCH = ("_thread.start_new_thread", "subprocess.Popen", "os.system", "os.exec", "os.fork", "os.posix_spawn",
         "_posixsubprocess.fork_exec", "_winapi.CreateProcess", "socket.connect", "socket.getaddrinfo")
def hook(event, args):
    if event in WATCH:
        events.append(event)
sys.addaudithook(hook)
records = []
class Collect(logging.Handler):
    def emit(self, record):
        records.append(record)
logging.getLogger().addHandler(Collect())
import swasthyoid.workers.extract
problems = []
if events:
    problems.append("audit events: " + ",".join(sorted(set(events))))
if records:
    problems.append("log records: %d" % len(records))
if threading.active_count() != 1:
    problems.append("threads: %d" % threading.active_count())
if problems:
    sys.stderr.write("; ".join(problems))
    sys.exit(3)
'''


def test_importing_the_runner_has_no_side_effects(tripwire):
    env = clean_env(DATABASE_URL=tripwire.uri, EXTRACTION_POLL_SECONDS="5", **tripwire.defaults)
    done = subprocess.run([sys.executable, "-c", IMPORT_PROBE], cwd=REPO, env=env, capture_output=True,
                          text=True, timeout=120)
    assert (done.returncode, done.stdout, done.stderr) == (0, "", "")  # no output, no event, no log record, no thread
    assert tripwire.count == 0  # no database connection attempt, not even from the C library


# ---- the first runtime safety check, and what must not happen before it

def test_usage_error_exits_2_before_anything_else(tripwire):
    done = run_runner("--bogus", env=clean_env(DATABASE_URL=tripwire.uri, **tripwire.defaults))
    assert done.returncode == 2 and done.stdout == "" and "usage" in done.stderr.lower()
    assert tripwire.count == 0


@pytest.mark.parametrize("confirm", [None, "", "0", "true", "yes", "01"])
def test_test_mode_without_the_exact_confirmation_is_refused_with_exit_2(tripwire, confirm):
    env = clean_env(APP_ENV="test", SWASTHYOID_TEST_MODE_CONFIRM=confirm, DATABASE_URL=tripwire.uri,
                    EXTRACTION_POLL_SECONDS="5", **tripwire.defaults)
    done = run_runner(env=env)
    assert done.returncode == 2 and done.stdout == ""
    assert "code=test_mode_config_refused" in done.stderr and "SWASTHYOID_TEST_MODE_CONFIRM" in done.stderr
    assert SECRET not in done.stderr and str(tripwire.port) not in done.stderr  # no environment value
    assert tripwire.count == 0  # no database connection, schema inspection or probe came first


def test_the_safety_check_comes_before_every_other_configuration_check():
    env = clean_env(APP_ENV="test")  # also no DATABASE_URL and no poll interval
    done = run_runner(env=env)
    assert done.returncode == 2 and "code=test_mode_config_refused" in done.stderr
    assert "invalid_configuration" not in done.stderr


def test_a_correctly_configured_test_mode_and_a_non_test_environment_both_pass_the_check(tripwire):
    for env in (clean_env(APP_ENV="test", SWASTHYOID_TEST_MODE_CONFIRM="1", DATABASE_URL=tripwire.uri),
                clean_env(APP_ENV="production", DATABASE_URL=tripwire.uri), clean_env(DATABASE_URL=tripwire.uri)):
        done = run_runner("--once", env=env)
        assert "test_mode_config_refused" not in done.stderr  # not refused: it went on to the connection
        assert done.returncode == 1 and "code=database_connection_failed" in done.stderr
    assert tripwire.count == 3


# ---- configuration validation

VALID_POLL = [("5", 5.0), ("0.5", 0.5), ("1e-3", 0.001), (" 2 ", 2.0), ("1", 1.0)]
INVALID_POLL = [None, "", "   ", "abc", "true", "false", "yes", "nan", "NaN", "inf", "-inf", "Infinity", "-1", "-0.5",
                "0", "0.0", "-0", "1e999", "1_0", "5s", "--5"]


@pytest.mark.parametrize("raw, expected", VALID_POLL)
def test_valid_poll_intervals_are_accepted(raw, expected):
    assert extract.parse_poll_seconds(raw) == expected


@pytest.mark.parametrize("raw", INVALID_POLL)
def test_invalid_poll_intervals_are_refused(raw):
    with pytest.raises(ValueError):
        extract.parse_poll_seconds(raw)


@pytest.mark.parametrize("raw", [None, "0", "abc", SENTINEL])
def test_loop_mode_needs_a_valid_poll_interval_and_exits_2_without_connecting(tripwire, raw):
    env = clean_env(DATABASE_URL=tripwire.uri, EXTRACTION_POLL_SECONDS=raw, **tripwire.defaults)
    done = run_runner(env=env)
    assert done.returncode == 2 and done.stdout == ""
    assert "code=invalid_configuration" in done.stderr and "setting=EXTRACTION_POLL_SECONDS" in done.stderr
    assert SENTINEL not in done.stderr and SECRET not in done.stderr  # the value is never echoed
    assert tripwire.count == 0


@pytest.mark.parametrize("poll", [None, SENTINEL, "0"])
def test_once_does_not_need_or_look_at_the_poll_interval(tripwire, poll):
    done = run_runner("--once", env=clean_env(DATABASE_URL=tripwire.uri, EXTRACTION_POLL_SECONDS=poll))
    assert "EXTRACTION_POLL_SECONDS" not in done.stderr
    assert done.returncode == 1 and "code=database_connection_failed" in done.stderr  # it reached the connection
    assert tripwire.count >= 1


@pytest.mark.parametrize("value", [None, "", "   ", "\t", "this is not a connection string", f"{SENTINEL} ==="])
def test_a_missing_empty_or_malformed_database_url_exits_2_without_connecting(tripwire, value):
    done = run_runner("--once", env=clean_env(DATABASE_URL=value, **tripwire.defaults))
    assert done.returncode == 2 and done.stdout == ""
    assert "code=invalid_configuration" in done.stderr and "setting=DATABASE_URL" in done.stderr
    assert SENTINEL not in done.stderr
    assert tripwire.count == 0  # not even through the library's default parameters


def test_both_connection_string_forms_pass_validation_and_a_failed_connection_exits_1(tripwire):
    for value in (tripwire.uri, tripwire.keywords):
        done = run_runner("--once", env=clean_env(DATABASE_URL=value))
        assert done.returncode == 1 and done.stdout == ""
        assert "code=database_connection_failed" in done.stderr
        assert SECRET not in done.stderr and str(tripwire.port) not in done.stderr
    assert tripwire.count >= 2


def test_an_unreachable_database_exits_1():
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]  # closed again on leaving the block: nothing listens
    done = run_runner("--once", env=clean_env(
        DATABASE_URL=f"postgresql://runner:{SECRET}@127.0.0.1:{port}/db?connect_timeout=5"))
    assert done.returncode == 1 and "code=database_connection_failed" in done.stderr and SECRET not in done.stderr


# ---- the schema inventory stays tied to the real schema files

def test_required_schema_names_exist_in_the_schema_files():
    text = CAPTURE_SCHEMA.read_text(encoding="utf-8")
    for table, columns in extract.REQUIRED_SCHEMA.items():
        assert re.search(rf"CREATE TABLE IF NOT EXISTS {table}\b", text), table
        for column in columns:
            assert re.search(rf"\b{column}\b", text), f"{table}.{column}"


# ---- read-only schema validation against a real PostgreSQL (CI; skipped without DATABASE_URL)

@pytest.fixture
def blank_database():
    require_database()
    admin_url = os.environ["DATABASE_URL"]
    name = f"it_{uuid.uuid4().hex}"
    with psycopg.connect(admin_url, autocommit=True) as admin:
        admin.execute(f"CREATE DATABASE {name}")
    try:
        yield make_conninfo(admin_url, dbname=name)  # a keyword/value string, as the other fixtures use
    finally:
        with psycopg.connect(admin_url, autocommit=True) as admin:
            admin.execute(f"DROP DATABASE {name} WITH (FORCE)")


def catalog(conninfo):
    with psycopg.connect(conninfo) as conn:
        return conn.execute("SELECT table_schema, table_name, column_name FROM information_schema.columns "
                            "WHERE table_schema NOT IN ('pg_catalog', 'information_schema') ORDER BY 1, 2, 3").fetchall()


def apply_real_schema(conninfo):
    with psycopg.connect(conninfo) as conn:
        db.apply_schema(conn)


def test_an_empty_database_exits_1_names_the_missing_tables_and_runs_no_ddl(blank_database):
    assert catalog(blank_database) == []
    done = run_runner("--once", env=clean_env(DATABASE_URL=blank_database))
    assert done.returncode == 1 and done.stdout == ""
    assert "code=schema_unavailable missing=document_images,documents,extractions" in done.stderr
    assert catalog(blank_database) == []  # still empty: the runner created nothing


def test_the_complete_schema_passes_with_exit_0_and_changes_nothing(blank_database):
    apply_real_schema(blank_database)
    before = catalog(blank_database)
    with psycopg.connect(blank_database) as conn:
        assert extract.missing_schema(conn) == []  # every listed table and column exists in the real schema
    for env in (clean_env(DATABASE_URL=blank_database),
                clean_env(APP_ENV="test", SWASTHYOID_TEST_MODE_CONFIRM="1", DATABASE_URL=blank_database)):
        done = run_runner("--once", env=env)
        assert done.returncode == 0 and done.stdout == "" and "code=startup_checks_passed" in done.stderr
    assert catalog(blank_database) == before


def test_a_missing_column_is_named_and_the_schema_is_left_as_it_is(blank_database):
    apply_real_schema(blank_database)
    with psycopg.connect(blank_database, autocommit=True) as conn:  # the test itself breaks the schema
        conn.execute("ALTER TABLE documents DROP COLUMN extraction_claim")
    before = catalog(blank_database)
    done = run_runner("--once", env=clean_env(DATABASE_URL=blank_database))
    assert done.returncode == 1 and "code=schema_unavailable missing=documents.extraction_claim" in done.stderr
    assert catalog(blank_database) == before  # the runner did not repair it


def test_the_runner_claims_and_processes_nothing_even_with_a_due_document_and_a_test_adapter(prod):
    doc_id = upload(prod, patient(prod))  # an uploaded document that is due
    env = clean_env(DATABASE_URL=os.environ["DATABASE_URL"], APP_ENV="test", SWASTHYOID_TEST_MODE_CONFIRM="1",
                    OCR_ADAPTER="swasthyoid.tests.adapters.fake_adapters:good")
    done = run_runner("--once", env=env)
    assert done.returncode == 0 and "code=startup_checks_passed" in done.stderr
    with prod.connect() as conn:
        assert job(conn, doc_id) == ("uploaded", 0, None, None)  # not claimed, no attempt counted
        assert conn.execute("SELECT count(*) FROM extractions").fetchone()[0] == 0
