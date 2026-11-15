"""Worker metrics and the D13 alert hooks (workers/monitoring.py, workers/extract.py queue_stats and _report).

No threshold or transport is chosen (OWNER-DECISION-PENDING, D13): the rules below are test-only values. Synthetic data."""
import pytest

from swasthyoid.capture import extraction
from swasthyoid.tests.test_extraction_integration import patient, prod, upload  # noqa: F401
from swasthyoid.workers import extract, monitoring
from swasthyoid.workers.monitoring import Alert, AlertRule


def test_no_rule_and_no_sink_is_configured_until_the_owner_decides_d13():
    assert monitoring.ALERT_RULES == () and monitoring.ALERT_SINKS == ()


def test_a_rule_must_name_a_known_metric_and_a_whole_number_of_one_or_more():
    AlertRule("lease_expired", 1)
    for metric, at_least in (("lease_expird", 1), ("due", 0), ("due", -1), ("due", 1.5), ("due", True), ("due", "1")):
        with pytest.raises(ValueError):
            AlertRule(metric, at_least)


def test_evaluate_fires_in_rule_order_at_or_above_the_value_and_skips_missing_metrics():
    stats = {"due": 4, "lease_expired": 1, "failed": 0, "in_flight": True}
    rules = (AlertRule("lease_expired", 1), AlertRule("due", 5), AlertRule("due", 4), AlertRule("failed", 1),
             AlertRule("in_flight", 1), AlertRule("waiting_backoff", 1))
    assert monitoring.evaluate(stats, rules) == [Alert("lease_expired", 1, 1), Alert("due", 4, 4)]
    assert monitoring.evaluate(stats, ()) == []


def test_dispatch_gives_every_alert_to_every_sink_and_a_failing_sink_never_raises(caplog):
    got = []

    def broken(alert):
        raise ConnectionError("SYNTH-SECRET-DESTINATION")

    alerts = [Alert("due", 9, 1), Alert("failed", 2, 1)]
    assert monitoring.dispatch(alerts, (got.append, broken)) == 2
    assert got == alerts
    assert "code=ConnectionError metric=due" in caplog.text and "SYNTH-SECRET" not in caplog.text


def test_the_runner_reports_every_metric_and_raises_configured_alerts(monkeypatch, capsys):
    stats = dict.fromkeys(monitoring.METRICS, 0) | {"lease_expired": 2}
    sent = []
    monkeypatch.setattr(extract, "queue_stats", lambda conn: stats)
    monkeypatch.setattr(monitoring, "ALERT_RULES", (AlertRule("lease_expired", 1), AlertRule("failed", 1)))
    monkeypatch.setattr(monitoring, "ALERT_SINKS", (sent.append,))
    extract._report(object(), 3)
    err = capsys.readouterr().err.splitlines()
    assert err[0] == "runner: code=cycle_done attempts=3 " + " ".join(f"{k}={stats[k]}" for k in monitoring.METRICS)
    assert err[1:] == ["runner: code=alert metric=lease_expired value=2 at_least=1"]
    assert sent == [Alert("lease_expired", 2, 1)]


def test_without_rules_the_runner_reports_and_alerts_nothing(monkeypatch, capsys):
    monkeypatch.setattr(extract, "queue_stats", lambda conn: dict.fromkeys(monitoring.METRICS, 7))
    extract._report(object(), 0)
    assert "code=alert" not in capsys.readouterr().err


# ---- the snapshot against PostgreSQL (CI)

def test_queue_stats_partitions_failures_and_detects_expired_leases_and_backoff(prod):  # noqa: F811
    headers = patient(prod)
    ids = [upload(prod, headers) for _ in range(7)]
    set_ = "UPDATE documents SET {} WHERE id = %s"
    with prod.connect() as conn:
        conn.execute(set_.format("status = 'extracting', extraction_claim = gen_random_uuid(), extraction_attempts = 1, "
                                 "extraction_lifetime_attempts = 1, next_extraction_at = clock_timestamp() + interval '1 hour'"),
                     [ids[0]])  # in flight
        conn.execute(set_.format("status = 'extracting', extraction_claim = gen_random_uuid(), extraction_attempts = 2, "
                                 "extraction_lifetime_attempts = 2, next_extraction_at = clock_timestamp() - interval '1 minute'"),
                     [ids[1]])  # lease expired
        conn.execute(set_.format("status = 'extracting', extraction_claim = NULL, extraction_attempts = 1, "
                                 "extraction_lifetime_attempts = 1, next_extraction_at = clock_timestamp() + interval '1 hour'"),
                     [ids[2]])  # waiting out a backoff
        conn.execute(set_.format("status = 'extraction_failed', extraction_error = 'malformed_output', "
                                 "extraction_lifetime_attempts = 1"), [ids[3]])  # permanent
        conn.execute(set_.format("status = 'extraction_failed', extraction_error = 'HardTimeout', "
                                 f"extraction_lifetime_attempts = {extraction.MAX_LIFETIME_ATTEMPTS}"), [ids[4]])  # budget used
        conn.execute(set_.format("status = 'extraction_failed', extraction_error = 'HardTimeout', "
                                 "extraction_lifetime_attempts = 3"), [ids[5]])  # retryable
        # ids[6] stays uploaded
        stats = extract.queue_stats(conn)
    assert stats == {"due": 2, "in_flight": 1, "lease_expired": 1, "failed": 3, "failed_permanent": 1,
                     "failed_budget_exhausted": 1, "failed_retryable": 1, "waiting_backoff": 1,
                     "attempts_open_runs": 4, "ocr_executions_total": 1 + 2 + 1 + 1 + extraction.MAX_LIFETIME_ATTEMPTS + 3}
    assert list(stats) == list(monitoring.METRICS)
    assert monitoring.evaluate(stats, (AlertRule("lease_expired", 1),)) == [Alert("lease_expired", 1, 1)]


def test_a_failure_with_no_error_code_counts_as_retryable_not_permanent(prod):  # noqa: F811
    doc_id = upload(prod, patient(prod))
    with prod.connect() as conn:
        conn.execute("UPDATE documents SET status = 'extraction_failed', extraction_error = NULL WHERE id = %s", [doc_id])
        stats = extract.queue_stats(conn)
    assert (stats["failed"], stats["failed_permanent"], stats["failed_retryable"]) == (1, 0, 1)
