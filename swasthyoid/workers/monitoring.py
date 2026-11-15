"""Extraction worker metrics and operator alerts (D13). Counts, metric names and timestamps only: never a document id, patient
id, document text or error message.

snapshot(conn) is one read-only statement over `documents` (the names in METRICS). The runner (workers/extract.py) takes one per
run_due() call, adds `adapter_unavailable_cycles`, prints it on its `cycle_done` line and gives it to an Alerter; the admin endpoint
GET /api/v1/internal/metrics (api/internal.py) returns it with the documents per status.

OWNER DECISION D13 (2026-11-15): the rules in owner_rules(); the JSON stderr sink always on; a webhook sink when ALERT_WEBHOOK_URL is
set; an alert is sent when its condition starts and again only after the condition has cleared and returned. These are operator
alerts, not patient notification (C3, core/notification.py).
"""
import json
import logging
import os
import sys
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone

from swasthyoid.capture import extraction

log = logging.getLogger(__name__)

# ---- owner decision D13, 2026-11-15
LEASE_EXPIRED_AT_LEAST = 1             # "expired leases > 0 in any cycle"
NO_RETRY_WINDOW = timedelta(hours=1)   # "permanent failures ... within a rolling 1-hour window"
NO_RETRY_DEFAULT_AT_LEAST = 3          # ">= 3"; ALERT_PERMANENT_FAILURES_PER_HOUR overrides (1 = "> 0", for prototype testing)
BACKLOG_WAIT = timedelta(minutes=15)   # "queued/unclaimed for more than 15 minutes"
BACKLOG_AT_LEAST = 51                  # "> 50 documents"
ADAPTER_UNAVAILABLE_AT_LEAST = 1       # "> 0 consecutive cycles when an OCR adapter is configured"
PERMANENT_VARIABLE = "ALERT_PERMANENT_FAILURES_PER_HOUR"
WEBHOOK_VARIABLE = "ALERT_WEBHOOK_URL"
WEBHOOK_TIMEOUT_SECONDS = 5            # engineering default, not an owner value: a slow webhook delays the loop at most this long

# snapshot(), in this order. failed_permanent, failed_budget_exhausted and failed_retryable partition `failed`.
METRICS = (
    "due",                      # uploaded, or extracting and due (backoff over or lease expired)
    "in_flight",                # extracting under a live claim and lease
    "lease_expired",            # extracting with a claim whose lease ran out (also counted in due)
    "failed",                   # extraction_failed
    "failed_permanent",         # ... with an error in extraction.PERMANENT_CODES (retry refused)
    "failed_budget_exhausted",  # ... other error, but all lifetime OCR executions used (retry refused)
    "failed_retryable",         # ... the patient may still retry
    "waiting_backoff",          # extracting, no claim, next try not yet due
    "attempts_open_runs",       # claims counted in runs still open (status extracting)
    "ocr_executions_total",     # actual OCR executions over all documents (lifetime counters)
    "failed_no_retry_last_hour",  # failed_permanent or failed_budget_exhausted, last changed within NO_RETRY_WINDOW
    "due_over_15_minutes",      # due and unclaimed for longer than BACKLOG_WAIT
)
RUNNER_METRICS = ("adapter_unavailable_cycles",)  # added by the runner: consecutive run_due() calls whose probe failed
ALERT_METRICS = METRICS + RUNNER_METRICS
STATUSES = ("uploaded", "extracting", "needs_review", "extraction_failed", "verified", "rejected")


def snapshot(conn):
    """Counts only, read-only, one statement: METRICS, in that order."""
    no_retry = "(extraction_error = ANY(%(permanent)s) OR extraction_lifetime_attempts >= %(budget)s)"
    permanent = "coalesce(extraction_error = ANY(%(permanent)s), false)"
    row = conn.execute(
        "SELECT count(*) FILTER (WHERE status = 'uploaded' OR (status = 'extracting' AND next_extraction_at <= clock_timestamp())), "
        "count(*) FILTER (WHERE status = 'extracting' AND extraction_claim IS NOT NULL AND next_extraction_at > clock_timestamp()), "
        "count(*) FILTER (WHERE status = 'extracting' AND extraction_claim IS NOT NULL AND next_extraction_at <= clock_timestamp()), "
        "count(*) FILTER (WHERE status = 'extraction_failed'), "
        f"count(*) FILTER (WHERE status = 'extraction_failed' AND {permanent}), "
        f"count(*) FILTER (WHERE status = 'extraction_failed' AND NOT {permanent} AND extraction_lifetime_attempts >= %(budget)s), "
        f"count(*) FILTER (WHERE status = 'extraction_failed' AND NOT {permanent} AND extraction_lifetime_attempts < %(budget)s), "
        "count(*) FILTER (WHERE status = 'extracting' AND extraction_claim IS NULL AND next_extraction_at > clock_timestamp()), "
        "coalesce(sum(extraction_attempts) FILTER (WHERE status = 'extracting'), 0), "
        "coalesce(sum(extraction_lifetime_attempts), 0), "
        f"count(*) FILTER (WHERE status = 'extraction_failed' AND {no_retry} "
        "AND updated_at > clock_timestamp() - %(window)s), "
        "count(*) FILTER (WHERE (status = 'uploaded' AND created_at <= clock_timestamp() - %(wait)s) "
        "OR (status = 'extracting' AND next_extraction_at <= clock_timestamp() - %(wait)s)) FROM documents",
        {"permanent": sorted(extraction.PERMANENT_CODES), "budget": extraction.MAX_LIFETIME_ATTEMPTS,
         "window": NO_RETRY_WINDOW, "wait": BACKLOG_WAIT}).fetchone()
    return dict(zip(METRICS, (int(value) for value in row)))


def by_status(conn):
    """Documents per status (every status in STATUSES, 0 when none)."""
    counts = dict(conn.execute("SELECT status, count(*) FROM documents GROUP BY status").fetchall())
    return {status: int(counts.get(status, 0)) for status in STATUSES}


@dataclass(frozen=True)
class AlertRule:
    """Fires when the snapshot's `metric` is at least `at_least` (an integer, 1 or more)."""
    metric: str
    at_least: int

    def __post_init__(self):
        if self.metric not in ALERT_METRICS:
            raise ValueError("alert rule names an unknown metric")
        if isinstance(self.at_least, bool) or not isinstance(self.at_least, int) or self.at_least < 1:
            raise ValueError("alert rule at_least must be an integer of 1 or more")


@dataclass(frozen=True)
class Alert:
    metric: str
    value: int
    at_least: int
    at: str  # ISO 8601, UTC

    def payload(self):
        """What a sink sends: metric name, count, threshold and time. Nothing else."""
        return {"type": "swasthyoid.worker_alert", **asdict(self)}


def owner_rules(environ=None):
    """The D13 rules. Raises ValueError((variable, reason)) for an unusable ALERT_PERMANENT_FAILURES_PER_HOUR."""
    environ = os.environ if environ is None else environ
    raw = environ.get(PERMANENT_VARIABLE)
    per_hour = NO_RETRY_DEFAULT_AT_LEAST
    if raw is not None:
        if not raw.strip().isdigit() or int(raw) < 1:
            raise ValueError((PERMANENT_VARIABLE, "not_a_whole_number_of_1_or_more"))
        per_hour = int(raw)
    return (AlertRule("lease_expired", LEASE_EXPIRED_AT_LEAST), AlertRule("failed_no_retry_last_hour", per_hour),
            AlertRule("due_over_15_minutes", BACKLOG_AT_LEAST),
            AlertRule("adapter_unavailable_cycles", ADAPTER_UNAVAILABLE_AT_LEAST))


def json_stderr_sink(alert):
    """One JSON line on stderr (on by default)."""
    sys.stderr.write(json.dumps(alert.payload(), sort_keys=True) + "\n")
    sys.stderr.flush()


class WebhookSink:
    """POSTs the alert payload as JSON. Raises on any failure (dispatch logs the type name only, never the URL)."""

    def __init__(self, url, timeout=WEBHOOK_TIMEOUT_SECONDS):
        parts = urllib.parse.urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            raise ValueError((WEBHOOK_VARIABLE, "not_an_http_or_https_url"))
        self._url, self._timeout = url, timeout

    def __call__(self, alert):
        request = urllib.request.Request(self._url, data=json.dumps(alert.payload()).encode("utf-8"), method="POST",
                                         headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=self._timeout) as response:
            response.read(1024)

    def __repr__(self):
        return "WebhookSink(<url hidden>)"  # the URL may carry a token


def owner_sinks(environ=None):
    """JSON stderr always; the webhook when ALERT_WEBHOOK_URL is set. Raises ValueError((variable, reason)) for a bad URL."""
    environ = os.environ if environ is None else environ
    url = environ.get(WEBHOOK_VARIABLE)
    return (json_stderr_sink,) + ((WebhookSink(url),) if url else ())


def evaluate(stats, rules, now=None):
    """The alerts for one snapshot, in rule order. A metric missing from the snapshot (or not an int) fires nothing."""
    at = (now or datetime.now(timezone.utc)).isoformat()
    alerts = []
    for rule in rules:
        value = stats.get(rule.metric)
        if isinstance(value, int) and not isinstance(value, bool) and value >= rule.at_least:
            alerts.append(Alert(rule.metric, value, rule.at_least, at))
    return alerts


def dispatch(alerts, sinks):
    """Give every alert to every sink. A failing sink never stops the worker: it is logged by type name and counted.
    Returns the number of failed deliveries."""
    failures = 0
    for alert in alerts:
        for sink in sinks:
            try:
                sink(alert)
            except Exception as failure:
                failures += 1
                log.warning("alert sink failed: code=%s metric=%s", type(failure).__name__, alert.metric)
    return failures


class Alerter:
    """Sends an alert when its rule starts firing, and again only after the rule has stopped firing and fires anew."""

    def __init__(self, rules=(), sinks=()):
        self.rules, self.sinks, self._active = tuple(rules), tuple(sinks), set()

    def check(self, stats, now=None):
        firing = evaluate(stats, self.rules, now)
        keys = {(alert.metric, alert.at_least) for alert in firing}
        new = [alert for alert in firing if (alert.metric, alert.at_least) not in self._active]
        self._active = keys
        dispatch(new, self.sinks)
        return new
