"""W3 notification sender: `python -m swasthyoid.workers.notify [--once]`.

Delivers queued notifications (core/notification.py deliver_due: claim -> send -> record, retry with backoff, in-app
fallback plus an audit entry after the last attempt). Configuration: DATABASE_URL; NOTIFY_POLL_SECONDS in loop mode;
NOTIFY_CHANNEL = in_app (default: the inbox only) or sms_console (dev/demo: logs the template id and the phone's last three
digits). sms_gateway is a PLACEHOLDER until the gateway is chosen (S2) and is refused as a configuration error.
Exit codes: 0 done, 1 infrastructure failure, 2 invalid usage or configuration. Diagnostics name settings and counts only,
never a phone number, payload or patient data. The runner never applies the schema.
"""
import argparse
import logging
import os
import sys
import time

from swasthyoid import db, runtime_mode
from swasthyoid.core import notification
from swasthyoid.workers.extract import check_database_url, parse_poll_seconds

CHANNELS = ("in_app", "sms_console")


def _say(code, **fields):
    sys.stderr.write(f"notify-runner: code={code}{''.join(f' {k}={v}' for k, v in fields.items())}\n")


def channels(name, conn):
    if name == "in_app":
        return [("in_app", notification.in_app_channel)]
    return [("sms_console", notification.sms_console_channel(conn))]


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m swasthyoid.workers.notify")
    parser.add_argument("--once", action="store_true", help="try every due notification once, then exit")
    args = parser.parse_args(argv)
    name = os.environ.get("NOTIFY_CHANNEL", "in_app")
    try:
        runtime_mode.check_test_mode_config()
        poll = None if args.once else parse_poll_seconds(os.environ.get("NOTIFY_POLL_SECONDS"))
        check_database_url()
    except RuntimeError:
        _say("config_error", setting="APP_ENV")
        return 2
    except ValueError as e:
        _say("config_error", reason=e.args[0] if e.args else "invalid")
        return 2
    if name not in CHANNELS:  # sms_gateway included: PLACEHOLDER until S2 picks a gateway
        _say("config_error", setting="NOTIFY_CHANNEL", reason="not_built" if name == "sms_gateway" else "unknown")
        return 2
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    try:
        with db.connect_worker() as conn:
            chosen = channels(name, conn)
            while True:
                _say("cycle", channel=name, tried=notification.deliver_due(conn, chosen))
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
