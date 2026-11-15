"""Extraction runner, slices 8.1 and 8.2 (docs/M2_COMPLETION_PLAN.md, Step 8).

Launched as `python -m swasthyoid.workers.extract [--once]` (decision D9). After the startup
checks pass, `--once` makes exactly one run_due() call with its normal limit and exits; loop
mode calls run_due(limit=1) repeatedly and waits EXTRACTION_POLL_SECONDS when nothing is due.
The first stop signal ends the loop before the next claim and lets the running attempt
finish; the second signal exits at once with code 3. The runner never applies or alters the
database schema, never reconnects, and has no switch around run_due()'s adapter allowlist and
availability probe: outside test mode it claims nothing.

Startup order (docs/DECISIONS.md, "Startup error and ordering contract"):
  1. the main-module guard at the bottom of this file; importing this module does nothing;
  2. side-effect-free argument parsing (a usage error exits 2);
  3. runtime_mode.check_test_mode_config(), the first runtime safety check;
  4. required configuration: EXTRACTION_POLL_SECONDS in loop mode, then DATABASE_URL, then EXTRACTION_KEY
     (a Fernet key: extracted text is stored sealed, D2), then the optional drug catalog (DRUG_CATALOG_PATH; when it is
     set, DRUG_CATALOG_SOURCE is required and the file must load, or the runner exits 2; when unset, no matching happens);
  5. connect with db.connect_worker() and check, read-only, that the tables and columns the
     worker uses exist;
  6. only then run_due() (availability probe, then claiming) is called.

Exit codes: 0 cycle completed or graceful shutdown; 1 infrastructure failure (database
connection, schema unavailable, connection lost, anything else that prevents a safe run);
2 invalid usage or configuration; 3 aborted by the second stop signal. A failed document never
changes the exit code.

Diagnostics go to stderr, one line each, and name settings, tables, columns and counts only:
never an environment value, a connection string, an exception message or document text.
"""
import argparse
import functools
import math
import os
import signal
import sys
import time

import psycopg
from psycopg.conninfo import conninfo_to_dict

from swasthyoid import db, runtime_mode
from swasthyoid.capture import drugcatalog, extraction, extraction_crypto
from swasthyoid.workers import monitoring

EXIT_OK = 0
EXIT_INFRASTRUCTURE = 1
EXIT_CONFIG = 2
EXIT_ABORTED = 3

# shortcut: idle waits are cut into slices because a long sleep delays signal handling on
# Windows; 0.5 s is the runner's choice, not an owner decision.
WAIT_SLICE = 0.5

POLL_VARIABLE = "EXTRACTION_POLL_SECONDS"

# The tables and columns that the worker's run_due() path reads or writes, derived from its SQL
# (capture/extraction.py: claim, _renew, _fail, _attempt, _store, _next_version;
# capture/documents.py: get, _images, read_image). patients and audit_logs are not listed: they
# are touched only when a cloud AI provider is passed to run_due(), which the runner never does.
REQUIRED_SCHEMA = {
    "documents": ("id", "patient_id", "doc_type", "status", "created_at", "updated_at",
                  "extraction_attempts", "next_extraction_at", "extraction_error", "extraction_claim",
                  "extraction_lifetime_attempts"),
    "document_images": ("document_id", "n", "storage_key", "content_type", "size_bytes", "sha256", "quality_warnings"),
    "extractions": ("id", "document_id", "version", "engine", "fields", "raw_text", "raw_text_sha256", "engine_id",
                    "model_version", "model_checksum", "adapter_interface_version", "adapter_version", "preprocessing",
                    "schema_version"),
    "extraction_raw_texts": ("extraction_id", "document_id", "ciphertext"),
}


def _say(code, **fields):
    """One diagnostic line on stderr. Callers pass names and fixed words only."""
    extra = "".join(f" {key}={value}" for key, value in fields.items())
    sys.stderr.write(f"runner: code={code}{extra}\n")
    sys.stderr.flush()


def _parser():
    parser = argparse.ArgumentParser(
        prog="python -m swasthyoid.workers.extract",
        description="Extraction runner: startup checks, then one run_due() call (--once) or a polling loop.")
    parser.add_argument("--once", action="store_true",
                        help="make exactly one run_due() call with its normal limit, then exit; "
                             f"{POLL_VARIABLE} is not needed")
    return parser


def parse_poll_seconds(raw):
    """EXTRACTION_POLL_SECONDS as a positive, finite number of seconds, or ValueError whose
    message is a fixed reason word. Empty, NaN, infinity, zero, negative and non-numeric values
    (including true/false) are refused. There is no default."""
    if raw is None:
        raise ValueError("missing")
    if not raw.strip():
        raise ValueError("empty")
    try:
        value = float(raw)
    except ValueError:
        raise ValueError("invalid") from None
    if "_" in raw or not math.isfinite(value) or value <= 0:
        raise ValueError("invalid")
    return value


def load_catalog(environ=None):
    """The drug reference catalog the worker matches medication rows against (Phase 7B, docs/DRUG_CATALOG.md), or None when
    DRUG_CATALOG_PATH is unset (matching is then off). Raises ValueError((setting, reason)) with fixed words, never a value or
    file content: a path that is set but empty, relative, unreadable or not a usable medicine.csv, a missing or empty
    DRUG_CATALOG_SOURCE (the owner's statement of where the data came from and on what terms; there is no default), or an
    empty DRUG_CATALOG_VERSION. The version defaults to the file's SHA-256."""
    environ = os.environ if environ is None else environ
    path = environ.get("DRUG_CATALOG_PATH")
    if path is None:
        return None
    if not path.strip():
        raise ValueError(("DRUG_CATALOG_PATH", "empty"))
    if not os.path.isabs(path):
        raise ValueError(("DRUG_CATALOG_PATH", "not_absolute"))
    source = environ.get("DRUG_CATALOG_SOURCE")
    if source is None or not source.strip():
        raise ValueError(("DRUG_CATALOG_SOURCE", "missing"))
    version = environ.get("DRUG_CATALOG_VERSION")
    if version is not None and not version.strip():
        raise ValueError(("DRUG_CATALOG_VERSION", "empty"))
    try:
        return drugcatalog.load_medicine_csv(path, source=source, version=version).catalog
    except drugcatalog.CatalogError as reason:
        raise ValueError(("DRUG_CATALOG_PATH", reason.args[0])) from None
    except OSError:
        raise ValueError(("DRUG_CATALOG_PATH", "unreadable")) from None


def check_database_url():
    """DATABASE_URL, validated without connecting, or ValueError whose message is a fixed reason
    word. Missing, empty and whitespace-only values are refused so that the connection library can
    never fall back to its default parameters. Anything else must be accepted by psycopg's own
    connection-string parser, which covers both libpq forms (a postgresql:// URI and a keyword/value
    string) and does not connect."""
    raw = os.environ.get("DATABASE_URL")
    if raw is None:
        raise ValueError("missing")
    if not raw.strip():
        raise ValueError("empty")
    try:
        conninfo_to_dict(raw)
    except (psycopg.Error, UnicodeError):
        raise ValueError("malformed") from None
    return raw


def missing_schema(conn):
    """The required tables and columns that are not visible, as sorted names ("documents" for a
    missing table, "documents.extraction_claim" for a missing column). Read-only: one SELECT on the
    catalog. information_schema.columns lists only what the current role may use, so a role
    without privileges also reports names as missing; that fails closed."""
    rows = conn.execute(
        "SELECT table_name, column_name FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name::text = ANY(%s::text[])",
        [list(REQUIRED_SCHEMA)]).fetchall()
    present = {(table, column) for table, column in rows}
    tables = {table for table, _ in rows}
    missing = []
    for table, columns in REQUIRED_SCHEMA.items():
        if table not in tables:
            missing.append(table)
        else:
            missing.extend(f"{table}.{column}" for column in columns if (table, column) not in present)
    return sorted(missing)


class Stop:
    """First signal: ask the loop to stop before its next claim. Second: exit now with code 3."""

    def __init__(self):
        self.requested = False

    def handler(self, signum, frame):
        if self.requested:
            _say("second_signal_abort")
            os._exit(EXIT_ABORTED)  # no cleanup: the lease expiry recovers the attempt
        self.requested = True
        _say("stop_requested")


def install_handlers(stop):
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):  # SIGBREAK exists on Windows only
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), stop.handler)


queue_stats = monitoring.snapshot  # the per-cycle counts (monitoring.METRICS); a module name so tests can replace it


class AdapterWatch:
    """Consecutive run_due() calls whose availability probe found the configured adapter unavailable (D13). Always 0 when
    OCR_ADAPTER is unset: then no adapter is configured, and an idle worker is not an alert."""

    def __init__(self):
        self.cycles = 0

    def run(self, run, conn, **options):
        before = extraction.probe_failures
        done = run(conn, **options)
        unavailable = bool(os.environ.get("OCR_ADAPTER")) and extraction.probe_failures > before
        self.cycles = self.cycles + 1 if unavailable else 0
        return done


def _stats(conn, watch):
    return {**queue_stats(conn), "adapter_unavailable_cycles": watch.cycles}


def _report(conn, attempts, alerter, watch):
    stats = _stats(conn, watch)
    _say("cycle_done", attempts=attempts, **stats)
    alerter.check(stats)


def _wait(seconds, stop, sleep=time.sleep):
    end = time.monotonic() + seconds
    while not stop.requested and (left := end - time.monotonic()) > 0:
        sleep(min(WAIT_SLICE, left))


def serve(conn, *, once, poll, stop, run=extraction.run_due, wait=_wait, alerter=None):
    """The processing cycle. Returns the exit code. Connection failures propagate. Alerts are checked after every run_due()
    call; the cycle_done line is printed as before (after a busy stretch, and at the end)."""
    alerter = monitoring.Alerter() if alerter is None else alerter
    watch = AdapterWatch()
    if once:
        _report(conn, watch.run(run, conn), alerter, watch)
        return EXIT_OK
    _say("loop_started", poll_seconds=poll)
    pending = 0
    while not stop.requested:
        # shortcut: one claim per run_due() call so a stop signal is seen before the next claim; each
        # call runs the availability probe (a child process), so this costs one probe per document and
        # per idle poll. Known performance limitation; the owner kept limit=1 over a stop hook.
        done = watch.run(run, conn, limit=1)
        pending += done
        stats = _stats(conn, watch)
        alerter.check(stats)
        if done:
            continue
        if pending:
            _say("cycle_done", attempts=pending, **stats)
            pending = 0
        wait(poll, stop)
    _report(conn, pending, alerter, watch)
    _say("graceful_shutdown")
    return EXIT_OK


def main(argv=None):
    args = _parser().parse_args(argv)  # no side effects; a usage error exits 2

    try:
        runtime_mode.check_test_mode_config()  # the first runtime safety check
    except RuntimeError as refusal:  # its one condition: APP_ENV=test without the confirmation
        _say("test_mode_config_refused", message=f'"{refusal}"')  # fixed text: variable names only
        return EXIT_CONFIG

    if not args.once:  # loop mode needs the interval; --once ignores the variable entirely
        try:
            parse_poll_seconds(os.environ.get(POLL_VARIABLE))
        except ValueError as reason:
            _say("invalid_configuration", setting=POLL_VARIABLE, reason=reason)
            return EXIT_CONFIG
    try:
        check_database_url()
    except ValueError as reason:
        _say("invalid_configuration", setting="DATABASE_URL", reason=reason)
        return EXIT_CONFIG
    try:
        extraction_crypto.check_key()  # no document is claimed that could not be stored sealed
    except extraction_crypto.KeyError_ as reason:
        _say("invalid_configuration", setting="EXTRACTION_KEY", reason=reason.args[0])
        return EXIT_CONFIG
    try:
        catalog = load_catalog()  # None unless the owner enabled drug-name candidates; a bad setting never degrades silently
    except ValueError as problem:
        setting, reason = problem.args[0]
        _say("invalid_configuration", setting=setting, reason=reason)
        return EXIT_CONFIG
    try:
        alerter = monitoring.Alerter(monitoring.owner_rules(), monitoring.owner_sinks())  # D13; never prints the URL
    except ValueError as problem:
        setting, reason = problem.args[0]
        _say("invalid_configuration", setting=setting, reason=reason)
        return EXIT_CONFIG

    try:
        conn = db.connect_worker()
    except psycopg.Error:
        _say("database_connection_failed")
        return EXIT_INFRASTRUCTURE
    except Exception as failure:
        _say("startup_failed", stage="connect", type=type(failure).__name__)
        return EXIT_INFRASTRUCTURE
    try:
        try:
            missing = missing_schema(conn)
        except Exception as failure:
            _say("startup_failed", stage="schema_check", type=type(failure).__name__)
            return EXIT_INFRASTRUCTURE
        if missing:
            _say("schema_unavailable", missing=",".join(missing))
            return EXIT_INFRASTRUCTURE
        _say("runner_started", mode="once" if args.once else "loop")
        stop = Stop()
        install_handlers(stop)
        poll = None if args.once else parse_poll_seconds(os.environ.get(POLL_VARIABLE))
        try:
            options = {} if catalog is None else {"run": functools.partial(extraction.run_due, catalog=catalog)}
            return serve(conn, once=args.once, poll=poll, stop=stop, alerter=alerter, **options)
        except (extraction.WorkerConnectionLost, psycopg.Error):
            _say("connection_lost")  # no reconnect: the lease expiry recovers the attempt
            return EXIT_INFRASTRUCTURE
        except Exception as failure:
            _say("runtime_failed", stage="cycle", type=type(failure).__name__)
            return EXIT_INFRASTRUCTURE
    finally:
        conn.close()


if __name__ == "__main__":
    sys.exit(main())
