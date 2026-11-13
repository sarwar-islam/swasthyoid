"""Extraction runner, slice 8.1: the startup skeleton (docs/M2_COMPLETION_PLAN.md, Step 8).

Launched as `python -m swasthyoid.workers.extract [--once]` (decision D9). This slice only
validates that the process can start safely. It does NOT call run_due(), run a --once polling
cycle, start the polling loop, handle stop signals, or claim or process any document, and it
never applies or alters the database schema. Those belong to later runner slices.

Startup order (docs/DECISIONS.md, "Startup error and ordering contract"):
  1. the main-module guard at the bottom of this file; importing this module does nothing;
  2. side-effect-free argument parsing (a usage error exits 2);
  3. runtime_mode.check_test_mode_config(), the first runtime safety check;
  4. required configuration: EXTRACTION_POLL_SECONDS in loop mode, then DATABASE_URL;
  5. connect with db.connect_worker() and check, read-only, that the tables and columns the
     worker uses exist;
  6. only then would a later slice go on to the availability probe and to claiming.

Exit codes: 0 startup checks passed; 1 infrastructure failure (database connection, schema
unavailable, anything else that prevents a safe start); 2 invalid usage or configuration.
Exit code 3 (second stop signal) belongs to the signal slice.

Diagnostics go to stderr, one line each, and name settings, tables and columns only: never an
environment value, a connection string or an exception message.
"""
import argparse
import math
import os
import sys

import psycopg
from psycopg.conninfo import conninfo_to_dict

from swasthyoid import db, runtime_mode

EXIT_OK = 0
EXIT_INFRASTRUCTURE = 1
EXIT_CONFIG = 2

POLL_VARIABLE = "EXTRACTION_POLL_SECONDS"

# The tables and columns that the worker's run_due() path reads or writes, derived from its SQL
# (capture/extraction.py: claim, _renew, _fail, _attempt, _store, _next_version;
# capture/documents.py: get, _images, read_image). patients and audit_logs are not listed: they
# are touched only when a cloud AI provider is passed to run_due(), which the runner never does.
REQUIRED_SCHEMA = {
    "documents": ("id", "patient_id", "doc_type", "status", "created_at", "updated_at",
                  "extraction_attempts", "next_extraction_at", "extraction_error", "extraction_claim"),
    "document_images": ("document_id", "n", "storage_key", "content_type", "size_bytes", "sha256"),
    "extractions": ("id", "document_id", "version", "engine", "fields", "raw_text", "engine_id",
                    "model_version", "model_checksum", "adapter_interface_version", "adapter_version"),
}


def _say(code, **fields):
    """One diagnostic line on stderr. Callers pass names and fixed words only."""
    extra = "".join(f" {key}={value}" for key, value in fields.items())
    sys.stderr.write(f"runner: code={code}{extra}\n")
    sys.stderr.flush()


def _parser():
    parser = argparse.ArgumentParser(
        prog="python -m swasthyoid.workers.extract",
        description="Extraction runner (slice 8.1: startup checks only).")
    parser.add_argument("--once", action="store_true",
                        help=f"one polling cycle instead of the loop; {POLL_VARIABLE} is not needed")
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
        conn = db.connect_worker()
    except psycopg.Error:
        _say("database_connection_failed")
        return EXIT_INFRASTRUCTURE
    except Exception as failure:
        _say("startup_failed", stage="connect", type=type(failure).__name__)
        return EXIT_INFRASTRUCTURE
    try:
        missing = missing_schema(conn)
    except Exception as failure:
        _say("startup_failed", stage="schema_check", type=type(failure).__name__)
        return EXIT_INFRASTRUCTURE
    finally:
        conn.close()
    if missing:
        _say("schema_unavailable", missing=",".join(missing))
        return EXIT_INFRASTRUCTURE

    _say("startup_checks_passed", note="no_polling_cycle_is_run_by_this_slice")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
