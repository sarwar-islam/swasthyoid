"""M6 check runner (P3): `python -m swasthyoid.workers.safety [--once] [--requeue]`.

Runs the queued prescription checks (safety/checks.py). Configuration: DATABASE_URL; SAFETY_POLL_SECONDS in loop mode; the
drug catalog as for the extraction runner (DRUG_CATALOG_PATH with DRUG_CATALOG_SOURCE; FRD Q1 is open, so it is usually
unset). Without a catalog every check is stored as `blocked: catalog_unavailable` (fail closed, visible to the doctor);
`--requeue` sends blocked and failed checks back to the queue once a rule or the catalog is fixed.
Exit codes: 0 done, 1 infrastructure failure, 2 invalid usage or configuration. Diagnostics name settings and counts
only, never a value or patient data. The runner never applies the schema.
"""
import argparse
import os
import sys
import time

from swasthyoid import db, runtime_mode
from swasthyoid.safety import checks
from swasthyoid.workers.extract import check_database_url, load_catalog, parse_poll_seconds


def _say(code, **fields):
    sys.stderr.write(f"safety-runner: code={code}{''.join(f' {k}={v}' for k, v in fields.items())}\n")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m swasthyoid.workers.safety")
    parser.add_argument("--once", action="store_true", help="run every due check once, then exit")
    parser.add_argument("--requeue", action="store_true", help="requeue blocked and failed checks, then exit")
    args = parser.parse_args(argv)
    try:
        runtime_mode.check_test_mode_config()
        poll = None if (args.once or args.requeue) else parse_poll_seconds(os.environ.get("SAFETY_POLL_SECONDS"))
        check_database_url()
        catalog = load_catalog()
    except RuntimeError:
        _say("config_error", setting="APP_ENV")
        return 2
    except ValueError as e:  # fixed words only: a reason, or (setting, reason) from load_catalog
        detail = e.args[0] if e.args else "invalid"
        _say("config_error", **(dict(zip(("setting", "reason"), detail)) if isinstance(detail, tuple) else {"reason": detail}))
        return 2
    try:
        with db.connect_worker() as conn:
            if args.requeue:
                _say("requeued", jobs=checks.requeue(conn))
                return 0
            if catalog is None:
                _say("catalog_unavailable")
            while True:
                _say("cycle", tried=checks.run_due(conn, catalog))
                if args.once:
                    return 0
                time.sleep(poll)
    except KeyboardInterrupt:
        return 0
    except Exception as e:
        _say("infrastructure_error", kind=type(e).__name__)
        return 1


if __name__ == "__main__":
    sys.exit(main())
