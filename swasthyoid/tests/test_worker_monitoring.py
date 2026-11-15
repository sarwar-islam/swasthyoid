"""D13 (owner decision 2026-11-15): worker metrics, the owner's alert rules, the JSON stderr and webhook sinks, alerts sent when a
condition starts, the adapter-unavailable count, and the admin metrics endpoint. Synthetic data only."""
import http.server
import json
import threading
from datetime import datetime, timezone

import pytest

from swasthyoid.capture import extraction
from swasthyoid.tests.test_api_m1 import V1, api, people  # noqa: F401
from swasthyoid.tests.test_extraction_integration import patient, prod, upload  # noqa: F401
from swasthyoid.workers import extract, monitoring
from swasthyoid.workers.monitoring import Alert, Alerter, AlertRule

NOW = datetime(2026, 11, 15, 12, 0, tzinfo=timezone.utc)
AT = NOW.isoformat()


# ---- the owner's rules

def test_the_owner_rules_and_the_permanent_failure_setting():
    assert monitoring.owner_rules({}) == (AlertRule("lease_expired", 1), AlertRule("failed_no_retry_last_hour", 3),
                                          AlertRule("due_over_15_minutes", 51), AlertRule("adapter_unavailable_cycles", 1))
    assert monitoring.owner_rules({"ALERT_PERMANENT_FAILURES_PER_HOUR": "1"})[1] == AlertRule("failed_no_retry_last_hour", 1)
    for bad in ("0", "-1", "abc", "1.5", " ", ""):
        with pytest.raises(ValueError) as problem:
            monitoring.owner_rules({"ALERT_PERMANENT_FAILURES_PER_HOUR": bad})
        assert problem.value.args[0][0] == "ALERT_PERMANENT_FAILURES_PER_HOUR"


def test_a_rule_must_name_a_known_metric_and_a_whole_number_of_one_or_more():
    AlertRule("adapter_unavailable_cycles", 1)
    for metric, at_least in (("lease_expird", 1), ("due", 0), ("due", -1), ("due", 1.5), ("due", True), ("due", "1")):
        with pytest.raises(ValueError):
            AlertRule(metric, at_least)


@pytest.mark.parametrize("metric, below, at", [("lease_expired", 0, 1), ("failed_no_retry_last_hour", 2, 3),
                                               ("due_over_15_minutes", 50, 51), ("adapter_unavailable_cycles", 0, 1)])
def test_each_owner_rule_fires_exactly_at_its_value(metric, below, at):
    rules = monitoring.owner_rules({})
    assert monitoring.evaluate({metric: below}, rules, NOW) == []
    assert monitoring.evaluate({metric: at}, rules, NOW) == [Alert(metric, at, at, AT)]


def test_evaluate_keeps_rule_order_and_skips_missing_or_non_integer_metrics():
    rules = (AlertRule("lease_expired", 1), AlertRule("due", 4), AlertRule("in_flight", 1), AlertRule("waiting_backoff", 1))
    assert monitoring.evaluate({"due": 4, "lease_expired": 2, "in_flight": True}, rules, NOW) == [
        Alert("lease_expired", 2, 1, AT), Alert("due", 4, 4, AT)]


def test_the_payload_holds_only_the_metric_count_threshold_and_time():
    assert Alert("lease_expired", 2, 1, AT).payload() == {"type": "swasthyoid.worker_alert", "metric": "lease_expired",
                                                          "value": 2, "at_least": 1, "at": AT}


# ---- sending

def test_an_alert_is_sent_when_it_starts_and_again_only_after_it_cleared():
    sent = []
    alerter = Alerter((AlertRule("lease_expired", 1), AlertRule("due", 1)), (sent.append,))
    assert alerter.check({"lease_expired": 1, "due": 0}, NOW) == [Alert("lease_expired", 1, 1, AT)]
    assert alerter.check({"lease_expired": 3, "due": 0}, NOW) == []  # still holding: not sent again
    assert alerter.check({"lease_expired": 2, "due": 5}, NOW) == [Alert("due", 5, 1, AT)]
    assert alerter.check({"lease_expired": 0, "due": 5}, NOW) == []  # lease cleared
    assert alerter.check({"lease_expired": 1, "due": 5}, NOW) == [Alert("lease_expired", 1, 1, AT)]  # and back
    assert [a.metric for a in sent] == ["lease_expired", "due", "lease_expired"]


def test_a_failing_sink_never_raises_and_is_logged_by_type_only(caplog):
    got = []

    def broken(alert):
        raise ConnectionError("SYNTH-SECRET-DESTINATION")

    alerts = [Alert("due", 9, 1, AT), Alert("failed", 2, 1, AT)]
    assert monitoring.dispatch(alerts, (got.append, broken)) == 2
    assert got == alerts
    assert "code=ConnectionError metric=due" in caplog.text and "SYNTH-SECRET" not in caplog.text


def test_the_json_stderr_sink_writes_one_line_of_the_payload(capsys):
    monitoring.json_stderr_sink(Alert("lease_expired", 1, 1, AT))
    line = capsys.readouterr().err
    assert line.endswith("\n") and line.count("\n") == 1
    assert json.loads(line) == Alert("lease_expired", 1, 1, AT).payload()


class Receiver(http.server.BaseHTTPRequestHandler):
    bodies = []

    def do_POST(self):
        Receiver.bodies.append((self.headers["Content-Type"], self.rfile.read(int(self.headers["Content-Length"]))))
        self.send_response(204)
        self.end_headers()

    def log_message(self, *args):
        pass


def test_the_webhook_posts_the_json_payload():
    server = http.server.HTTPServer(("127.0.0.1", 0), Receiver)
    thread = threading.Thread(target=server.handle_request)
    thread.start()
    try:
        Receiver.bodies.clear()
        monitoring.WebhookSink(f"http://127.0.0.1:{server.server_port}/hook?token=SYNTH")(Alert("due", 60, 51, AT))
    finally:
        thread.join(10)
        server.server_close()
    [(kind, body)] = Receiver.bodies
    assert kind == "application/json" and json.loads(body) == Alert("due", 60, 51, AT).payload()


def test_an_unreachable_webhook_fails_quietly_and_never_shows_its_url(caplog, capsys):
    server = http.server.HTTPServer(("127.0.0.1", 0), Receiver)
    port = server.server_port
    server.server_close()  # nothing listens there now
    sink = monitoring.WebhookSink(f"http://127.0.0.1:{port}/hook?token=SYNTH-TOKEN", timeout=2)
    alerter = Alerter((AlertRule("lease_expired", 1),), (monitoring.json_stderr_sink, sink))
    assert alerter.check({"lease_expired": 1}, NOW) == [Alert("lease_expired", 1, 1, AT)]  # the loop goes on
    assert "SYNTH-TOKEN" not in caplog.text + capsys.readouterr().err + repr(sink)
    assert "alert sink failed" in caplog.text


def test_the_sinks_are_stderr_always_and_the_webhook_only_when_configured():
    assert monitoring.owner_sinks({}) == (monitoring.json_stderr_sink,)
    sinks = monitoring.owner_sinks({"ALERT_WEBHOOK_URL": "https://alerts.example.test/hook"})
    assert sinks[0] is monitoring.json_stderr_sink and isinstance(sinks[1], monitoring.WebhookSink)
    for bad in ("ftp://alerts.example.test/x", "alerts.example.test", "https://", "file:///etc/passwd"):
        with pytest.raises(ValueError) as problem:
            monitoring.owner_sinks({"ALERT_WEBHOOK_URL": bad})
        assert problem.value.args[0] == ("ALERT_WEBHOOK_URL", "not_an_http_or_https_url")


# ---- the runner

def test_adapter_unavailable_cycles_count_consecutive_failed_probes_only_when_an_adapter_is_configured(monkeypatch):
    def probe_fails(conn, **options):
        extraction.probe_failures += 1
        return 0

    watch = extract.AdapterWatch()
    monkeypatch.setenv("OCR_ADAPTER", "swasthyoid.tests.fake:adapter")
    for expected in (1, 2):
        watch.run(probe_fails, None)
        assert watch.cycles == expected
    watch.run(lambda conn, **o: 1, None)
    assert watch.cycles == 0  # available again
    monkeypatch.delenv("OCR_ADAPTER")
    watch.run(probe_fails, None)
    assert watch.cycles == 0  # nothing configured: an idle worker is not an alert


def test_the_loop_checks_alerts_after_every_call_and_sends_each_once(monkeypatch, capsys):
    monkeypatch.setattr(extract, "queue_stats", lambda conn: dict.fromkeys(monitoring.METRICS, 0) | {"lease_expired": 1})
    stop, results = extract.Stop(), [1, 0, 0, 0]

    def run(conn, **options):
        if len(results) == 1:
            stop.requested = True
        return results.pop(0)

    sent = []
    alerter = Alerter(monitoring.owner_rules({}), (sent.append,))
    assert extract.serve(object(), once=False, poll=1.0, stop=stop, run=run, wait=lambda s, st: None,
                         alerter=alerter) == extract.EXIT_OK
    assert [a.metric for a in sent] == ["lease_expired"]  # four checks, one alert
    err = capsys.readouterr().err
    assert "code=cycle_done attempts=1 " in err and "adapter_unavailable_cycles=0" in err


def test_the_cycle_line_reports_every_metric(monkeypatch, capsys):
    stats = {k: n for n, k in enumerate(monitoring.METRICS)}
    monkeypatch.setattr(extract, "queue_stats", lambda conn: stats)
    extract._report(object(), 3, Alerter(), extract.AdapterWatch())
    assert capsys.readouterr().err == ("runner: code=cycle_done attempts=3 " + " ".join(f"{k}={v}" for k, v in stats.items())
                                       + " adapter_unavailable_cycles=0\n")


@pytest.mark.parametrize("name, value", [("ALERT_PERMANENT_FAILURES_PER_HOUR", "0"),
                                         ("ALERT_WEBHOOK_URL", "ftp://SYNTH-HOST/hook")])
def test_a_bad_alert_setting_stops_the_runner_before_it_connects(monkeypatch, capsys, name, value):
    for unset in ("APP_ENV", "SWASTHYOID_TEST_MODE_CONFIRM", "DRUG_CATALOG_PATH", "ALERT_PERMANENT_FAILURES_PER_HOUR",
                  "ALERT_WEBHOOK_URL"):
        monkeypatch.delenv(unset, raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic@127.0.0.1:1/none")
    monkeypatch.setenv(name, value)
    monkeypatch.setattr(extract.db, "connect_worker", lambda: pytest.fail("connected"))
    assert extract.main(["--once"]) == extract.EXIT_CONFIG
    err = capsys.readouterr().err
    assert f"code=invalid_configuration setting={name}" in err and "SYNTH-HOST" not in err


# ---- against PostgreSQL (CI)

def test_snapshot_partitions_failures_and_counts_leases_backoff_recent_failures_and_old_backlog(prod):  # noqa: F811
    headers = patient(prod)
    ids = [upload(prod, headers) for _ in range(8)]
    set_ = "UPDATE documents SET {} WHERE id = %s"
    budget = extraction.MAX_LIFETIME_ATTEMPTS
    with prod.connect() as conn:
        conn.execute(set_.format("status = 'extracting', extraction_claim = gen_random_uuid(), extraction_attempts = 1, "
                                 "extraction_lifetime_attempts = 1, next_extraction_at = clock_timestamp() + interval '1 hour'"),
                     [ids[0]])  # in flight
        conn.execute(set_.format("status = 'extracting', extraction_claim = gen_random_uuid(), extraction_attempts = 2, "
                                 "extraction_lifetime_attempts = 2, next_extraction_at = clock_timestamp() - interval '20 minutes'"),
                     [ids[1]])  # lease expired 20 minutes ago: due, and waiting over 15 minutes
        conn.execute(set_.format("status = 'extracting', extraction_claim = NULL, extraction_attempts = 1, "
                                 "extraction_lifetime_attempts = 1, next_extraction_at = clock_timestamp() + interval '1 hour'"),
                     [ids[2]])  # waiting out a backoff
        conn.execute(set_.format("status = 'extraction_failed', extraction_error = 'malformed_output', "
                                 "extraction_lifetime_attempts = 1, updated_at = clock_timestamp()"), [ids[3]])  # permanent, now
        conn.execute(set_.format("status = 'extraction_failed', extraction_error = 'HardTimeout', "
                                 f"extraction_lifetime_attempts = {budget}, updated_at = clock_timestamp()"), [ids[4]])  # budget
        conn.execute(set_.format("status = 'extraction_failed', extraction_error = 'HardTimeout', "
                                 "extraction_lifetime_attempts = 3"), [ids[5]])  # retryable
        conn.execute(set_.format("status = 'extraction_failed', extraction_error = 'Corrupted', extraction_lifetime_attempts = 1, "
                                 "updated_at = clock_timestamp() - interval '2 hours'"), [ids[6]])  # permanent, too long ago
        # uploaded 20 minutes ago: created_at is immutable (documents_guard), so the guard is off for this one statement in
        # this throwaway database only
        conn.execute("ALTER TABLE documents DISABLE TRIGGER documents_guard")
        conn.execute(set_.format("created_at = clock_timestamp() - interval '20 minutes'"), [ids[7]])
        conn.execute("ALTER TABLE documents ENABLE TRIGGER documents_guard")
        stats = extract.queue_stats(conn)
    assert stats == {"due": 2, "in_flight": 1, "lease_expired": 1, "failed": 4, "failed_permanent": 2,
                     "failed_budget_exhausted": 1, "failed_retryable": 1, "waiting_backoff": 1, "attempts_open_runs": 4,
                     "ocr_executions_total": 1 + 2 + 1 + 1 + budget + 3 + 1, "failed_no_retry_last_hour": 2,
                     "due_over_15_minutes": 2}
    assert list(stats) == list(monitoring.METRICS)
    assert [a.metric for a in monitoring.evaluate(stats, monitoring.owner_rules({}))] == ["lease_expired"]


def test_a_failure_with_no_error_code_counts_as_retryable_not_permanent(prod):  # noqa: F811
    doc_id = upload(prod, patient(prod))
    with prod.connect() as conn:
        conn.execute("UPDATE documents SET status = 'extraction_failed', extraction_error = NULL WHERE id = %s", [doc_id])
        stats = extract.queue_stats(conn)
    assert (stats["failed"], stats["failed_permanent"], stats["failed_retryable"], stats["failed_no_retry_last_hour"]) == \
        (1, 0, 1, 0)


def test_the_metrics_endpoint_is_admin_only_and_holds_counts_only(api, people):  # noqa: F811
    r = api.http.get(f"{V1}/internal/metrics", headers=people.admin)
    assert r.status_code == 200, r.text
    body = r.json()
    assert set(body) == {"at", "documents", "worker"} and r.headers["Cache-Control"] == "no-store"
    assert set(body["documents"]) == set(monitoring.STATUSES) and list(body["worker"]) == list(monitoring.METRICS)
    assert all(isinstance(v, int) for v in [*body["documents"].values(), *body["worker"].values()])
    for headers, code in ((people.patient, 403), (people.doctor, 403), ({}, 401)):
        assert api.http.get(f"{V1}/internal/metrics", headers=headers).status_code == code
