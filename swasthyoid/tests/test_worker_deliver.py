"""W3 notification runner: configuration, one pass over the queue, and no phone number or payload in its output."""
import contextlib
from uuid import uuid4

from swasthyoid.core import notification as c3
from swasthyoid.workers import deliver as notify


def test_unknown_or_unbuilt_channels_are_configuration_errors(monkeypatch, capsys):
    for name, reason in (("sms_gateway", "not_built"), ("carrier_pigeon", "unknown")):
        monkeypatch.setenv("NOTIFY_CHANNEL", name)
        assert notify.main(["--once"]) == 2
        assert f"setting=NOTIFY_CHANNEL reason={reason}" in capsys.readouterr().err
    monkeypatch.setenv("NOTIFY_CHANNEL", "in_app")
    monkeypatch.delenv("NOTIFY_POLL_SECONDS", raising=False)
    assert notify.main([]) == 2  # loop mode needs the interval


def test_one_pass_delivers_the_queue(connect, monkeypatch, capsys):
    conn = connect()
    conn.autocommit = True
    n = c3.enqueue(conn, recipient_id=uuid4(), template_id="PLACEHOLDER_TEMPLATE", payload={"synthetic": "SECRET-PAYLOAD"})
    monkeypatch.setattr(notify.db, "connect_worker", lambda: contextlib.nullcontext(conn))
    monkeypatch.setenv("NOTIFY_CHANNEL", "in_app")
    assert notify.main(["--once"]) == 0
    assert conn.execute("SELECT status FROM notifications WHERE id = %s", [n["id"]]).fetchone()[0] == "delivered"
    err = capsys.readouterr().err
    assert "code=cycle channel=in_app tried=1" in err and "SECRET" not in err


def test_a_database_failure_is_an_infrastructure_error(monkeypatch, capsys):
    def down():
        raise ConnectionError("db down")
    monkeypatch.setattr(notify.db, "connect_worker", down)
    assert notify.main(["--once"]) == 1
    assert "code=infrastructure_error kind=ConnectionError" in capsys.readouterr().err
