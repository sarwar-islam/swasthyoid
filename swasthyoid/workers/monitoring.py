"""Extraction worker metrics and operator alert hooks (D13). Counts only: no document id, patient, text or error message.

The runner (workers/extract.py) reads one snapshot per cycle (`queue_stats`, the names in METRICS), prints it on its
`cycle_done` line, checks it against ALERT_RULES and hands every alert to each ALERT_SINKS callable.

OWNER-DECISION-PENDING (D13): which metrics alert, at what values, and where an alert goes (log aggregator, pager, mail,
supervisor hook) are not decided. ALERT_RULES and ALERT_SINKS are therefore EMPTY: nothing alerts and nothing is sent.
Do not fill them with guessed values. This module only evaluates rules and calls sinks; it sends nothing itself and is
not patient notification (that is core/notification.py, C3).
"""
import logging
from dataclasses import dataclass

log = logging.getLogger(__name__)

# The snapshot, in the order the runner prints it. The three failed_* counts partition `failed`.
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
)


@dataclass(frozen=True)
class AlertRule:
    """Fires when the snapshot's `metric` is at least `at_least` (an integer, 1 or more)."""
    metric: str
    at_least: int

    def __post_init__(self):
        if self.metric not in METRICS:
            raise ValueError("alert rule names an unknown metric")
        if isinstance(self.at_least, bool) or not isinstance(self.at_least, int) or self.at_least < 1:
            raise ValueError("alert rule at_least must be an integer of 1 or more")


@dataclass(frozen=True)
class Alert:
    metric: str
    value: int
    at_least: int


# OWNER-DECISION-PENDING (D13): thresholds. Example shape only: (AlertRule("lease_expired", <owner's value>),)
ALERT_RULES: tuple = ()
# OWNER-DECISION-PENDING (D13): transport. A sink is a callable sink(alert) that raises on failure.
ALERT_SINKS: tuple = ()


def evaluate(stats, rules):
    """The alerts for one snapshot, in rule order. A metric missing from the snapshot (or not an int) fires nothing."""
    alerts = []
    for rule in rules:
        value = stats.get(rule.metric)
        if isinstance(value, int) and not isinstance(value, bool) and value >= rule.at_least:
            alerts.append(Alert(rule.metric, value, rule.at_least))
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
