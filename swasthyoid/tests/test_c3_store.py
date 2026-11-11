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
    assert c3.inbox(conn, recipient) == []

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


def test_inbox_is_per_recipient_and_only_fallbacks(conn):
    me, other = uuid4(), uuid4()
    queue(conn, me), queue(conn, other)
    c3.deliver_due(conn, [("push", Fake(fail=True))], max_attempts=1)
    delivered = queue(conn, me)
    c3.deliver_due(conn, [("push", Fake())])
    assert len(c3.inbox(conn, me)) == 1 and c3.inbox(conn, me)[0]["id"] != delivered["id"]
    assert len(c3.inbox(conn, other)) == 1


def test_if_the_audit_write_fails_the_notification_stays_queued(conn, monkeypatch):
    n = queue(conn)
    conn.commit()

    def broken(*args, **kwargs):
        raise RuntimeError("audit store down")

    monkeypatch.setattr(audit, "append", broken)
    with pytest.raises(RuntimeError):
        c3.deliver_due(conn, [("push", Fake(fail=True))], max_attempts=1)
    assert row(conn, n) == ("queued", 0)  # nothing lost, it will be tried again
    assert deliveries(conn, n) == []
