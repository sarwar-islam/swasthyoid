from datetime import timedelta
from uuid import uuid4

import psycopg
import pytest

from swasthyoid.core import audit
from swasthyoid.core import notification as c3


class Fake:
    """Fake gateway: records what it was asked to send, fails when told to."""

    def __init__(self, fail=False):
        self.fail, self.sent = fail, []

    def __call__(self, n):
        if self.fail:
            raise ConnectionError("gateway down")
        self.sent.append(n["id"])


def queue(conn, recipient=None):
    return c3.enqueue(conn, recipient_id=recipient or uuid4(), template_id="PLACEHOLDER_TEMPLATE",
                      payload={"synthetic": True})


def row(conn, n):
    return conn.execute("SELECT status, attempts FROM notifications WHERE id = %s", [n["id"]]).fetchone()


def deliveries(conn, n):
    return conn.execute(
        "SELECT channel, attempt, status FROM notification_deliveries WHERE notification_id = %s ORDER BY at",
        [n["id"]]).fetchall()


def make_due(conn):
    conn.execute("UPDATE notifications SET next_attempt_at = clock_timestamp() WHERE status = 'queued'")


def test_enqueue_persists_without_sending_and_follows_the_callers_transaction(conn):
    n = queue(conn)
    assert (n["status"], n["attempts"]) == ("queued", 0)
    conn.rollback()
    assert conn.execute("SELECT count(*) FROM notifications").fetchone()[0] == 0


@pytest.mark.parametrize("bad", [{"template_id": ""}, {"payload": None}, {"recipient_id": None}])
def test_invalid_notification_is_rejected(conn, bad):
    fields = {"recipient_id": uuid4(), "template_id": "PLACEHOLDER_TEMPLATE", "payload": {}, **bad}
    with pytest.raises(psycopg.Error):
        c3.enqueue(conn, **fields)


def test_push_succeeds(conn):
    push, sms = Fake(), Fake()
    n = queue(conn)
    assert c3.deliver_due(conn, [("push", push), ("sms", sms)]) == 1
    assert row(conn, n) == ("delivered", 1)
    assert push.sent == [n["id"]] and sms.sent == []
    assert deliveries(conn, n) == [("push", 1, "sent")]
    assert c3.deliver_due(conn, [("push", push), ("sms", sms)]) == 0  # not sent twice


def test_sms_is_used_when_push_fails(conn):
    sms = Fake()
    n = queue(conn)
    c3.deliver_due(conn, [("push", Fake(fail=True)), ("sms", sms)])
    assert row(conn, n) == ("delivered", 1)
    assert sms.sent == [n["id"]]
    assert deliveries(conn, n) == [("push", 1, "failed"), ("sms", 1, "sent")]


def test_retry_with_backoff_then_in_app_fallback_and_audit(conn):
    recipient = uuid4()
    channels = [("push", Fake(fail=True)), ("sms", Fake(fail=True))]
    n = queue(conn, recipient)

    assert c3.deliver_due(conn, channels, max_attempts=3) == 1
    assert row(conn, n) == ("queued", 1)
    assert c3.deliver_due(conn, channels, max_attempts=3) == 0  # backing off, not due yet
    assert [i["id"] for i in c3.inbox(conn, recipient)] == [n["id"]]  # in-app from the start (B3)

    make_due(conn)
    c3.deliver_due(conn, channels, max_attempts=3)
    assert row(conn, n) == ("queued", 2)
    make_due(conn)
    c3.deliver_due(conn, channels, max_attempts=3)
    assert row(conn, n) == ("fallback_in_app", 3)

    assert deliveries(conn, n)[-3:] == [("push", 3, "failed"), ("sms", 3, "failed"), ("in_app", 3, "sent")]
    assert [i["id"] for i in c3.inbox(conn, recipient)] == [n["id"]]
    logged = conn.execute("SELECT action, result, reason, resource_id FROM audit_logs").fetchall()
    assert logged == [("notification.failure", "failed", "ConnectionError: gateway down", n["id"])]
    assert audit.verify_stored(conn) is None
    make_due(conn)
    assert c3.deliver_due(conn, channels) == 0  # finished, never retried again


def test_backoff_grows(conn):
    n = queue(conn)
    channels = [("push", Fake(fail=True))]
    gaps = []
    for _ in range(2):
        c3.deliver_due(conn, channels, max_attempts=5, backoff=timedelta(minutes=10))
        gaps.append(conn.execute(
            "SELECT next_attempt_at - clock_timestamp() FROM notifications WHERE id = %s", [n["id"]]).fetchone()[0])
        make_due(conn)
    assert timedelta(minutes=9) < gaps[0] <= timedelta(minutes=10)
    assert timedelta(minutes=19) < gaps[1] <= timedelta(minutes=20)


def test_no_channels_is_a_failure_not_a_silent_delivery(conn):
    n = queue(conn)
    c3.deliver_due(conn, [], max_attempts=1)
    assert row(conn, n) == ("fallback_in_app", 1)


def test_one_failing_notification_does_not_block_the_rest(conn):
    bad, good = queue(conn), queue(conn)

    def picky(n):
        if n["id"] == bad["id"]:
            raise ConnectionError("gateway down")

    assert c3.deliver_due(conn, [("push", picky)]) == 2
    assert row(conn, bad) == ("queued", 1)
    assert row(conn, good) == ("delivered", 1)


def test_inbox_is_per_recipient_and_shows_every_notice_whatever_the_delivery(conn):
    me, other = uuid4(), uuid4()
    failed, _ = queue(conn, me), queue(conn, other)
    c3.deliver_due(conn, [("push", Fake(fail=True))], max_attempts=1)
    delivered = queue(conn, me)
    c3.deliver_due(conn, [("push", Fake())])
    assert {i["id"] for i in c3.inbox(conn, me)} == {failed["id"], delivered["id"]}  # B3: not only fallbacks
    assert len(c3.inbox(conn, other)) == 1


def test_mark_read_only_for_the_recipient_and_only_once(conn):
    me = uuid4()
    n = queue(conn, me)
    assert c3.mark_read(conn, n["id"], uuid4()) is None
    first = c3.mark_read(conn, n["id"], me)["read_at"]
    assert first is not None and c3.mark_read(conn, n["id"], me)["read_at"] == first


def test_if_the_audit_write_fails_the_notification_stays_queued(conn, monkeypatch):
    n = queue(conn)
    conn.commit()

    def broken(*args, **kwargs):
        raise RuntimeError("audit store down")

    monkeypatch.setattr(audit, "append", broken)
    with pytest.raises(RuntimeError):
        c3.deliver_due(conn, [("push", Fake(fail=True))], max_attempts=1)
    assert row(conn, n) == ("queued", 1)  # nothing lost: the claimed attempt is taken again when its lease ends
    assert deliveries(conn, n) == []


# ---- W3: claim -> send -> record, attempt keys, two workers

def test_delivered_exactly_once_and_the_gateway_gets_the_attempt_key(conn):
    keys = []
    n = queue(conn)
    assert c3.deliver_due(conn, [("sms", lambda m: keys.append(c3.attempt_key(m)))]) == 1
    make_due(conn)
    assert c3.deliver_due(conn, [("sms", lambda m: keys.append(c3.attempt_key(m)))]) == 0
    assert keys == [f"{n['id']}:1"]
    assert deliveries(conn, n) == [("sms", 1, "sent")]


def test_the_gateway_is_called_with_no_lock_held(connect):
    first, second = connect(), connect()
    first.autocommit = second.autocommit = True
    n = queue(first)
    seen = []

    def gateway(m):  # while sending, another connection can still update the row: nothing holds it
        seen.append(second.execute("UPDATE notifications SET payload = payload WHERE id = %s RETURNING 1",
                                   [m["id"]]).fetchone())

    second.execute("SET lock_timeout = '2s'")
    assert c3.deliver_due(first, [("sms", gateway)]) == 1
    assert seen == [(1,)] and row(first, n) == ("delivered", 1)


def test_a_worker_that_dies_after_claiming_loses_nothing(conn):
    n = queue(conn)
    assert c3._claim(conn, c3.CLAIM_LEASE)["id"] == n["id"]  # claimed, then the worker is gone
    assert c3.deliver_due(conn, [("sms", Fake())]) == 0  # hidden while the lease runs
    make_due(conn)  # the lease ran out
    sms = Fake()
    assert c3.deliver_due(conn, [("sms", sms)]) == 1
    assert sms.sent == [n["id"]] and row(conn, n) == ("delivered", 2)


def test_a_late_worker_does_not_overwrite_the_one_that_took_over(conn):
    n = queue(conn)
    late = c3._claim(conn, c3.CLAIM_LEASE)
    make_due(conn)
    c3.deliver_due(conn, [("sms", Fake())])  # the second worker delivers attempt 2
    conn.execute("UPDATE notifications SET status = 'queued' WHERE id = %s", [n["id"]])  # worst case: still open
    with conn.transaction():
        c3._record(conn, late["id"], "sms", 2, None)  # a repeat of an attempt key changes nothing
    assert deliveries(conn, n) == [("sms", 2, "sent")]


def test_two_workers_never_deliver_the_same_notification(connect):
    import threading
    setup = connect()
    setup.autocommit = True
    ids = [queue(setup)["id"] for _ in range(30)]
    sent, lock = [], threading.Lock()

    def gateway(m):
        with lock:
            sent.append(m["id"])

    def worker():
        c = connect()
        c.autocommit = True
        c3.deliver_due(c, [("sms", gateway)])

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(sent) == sorted(ids)  # every one, once
    assert setup.execute("SELECT count(*) FROM notifications WHERE status = 'delivered'").fetchone()[0] == 30


def test_gateway_down_keeps_retrying_then_falls_back_in_app_with_audit(conn):
    n = queue(conn)
    down = [("sms", Fake(fail=True))]
    for attempt in (1, 2, 3):
        assert c3.deliver_due(conn, down, max_attempts=3) == 1
        make_due(conn)
    assert row(conn, n) == ("fallback_in_app", 3)
    assert [d[0] for d in deliveries(conn, n)] == ["sms", "sms", "sms", "in_app"]
    assert conn.execute("SELECT count(*) FROM audit_logs WHERE action = 'notification.failure'").fetchone()[0] == 1
    assert [i["id"] for i in c3.inbox(conn, n["recipient_id"])] == [n["id"]]  # never lost


def test_sms_console_logs_only_the_template_and_last_three_digits(conn, caplog):
    from swasthyoid.identity import accounts
    from swasthyoid.tests.test_api_m1 import PROFILE
    me = accounts.register_patient(conn, phone="01700000123", **PROFILE)["id"]
    n = queue(conn, me)
    with caplog.at_level("INFO"):
        c3.deliver_due(conn, [("sms_console", c3.sms_console_channel(conn))])
    assert row(conn, n) == ("delivered", 1)
    text = caplog.text
    assert "PLACEHOLDER_TEMPLATE" in text and "...123" in text
    assert "01700000" not in text and "synthetic" not in text
