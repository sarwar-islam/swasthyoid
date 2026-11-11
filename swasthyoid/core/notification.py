"""C3 — notification queue and delivery (FRD section 4.3).

enqueue() only writes a row, inside the caller's transaction, so the health event
or audit record it belongs to never depends on delivery (invariant 7). A worker
calls deliver_due() to send: each channel in order, retry with backoff, and after
the last attempt an in-app fallback plus an audit entry.

A channel is (name, send) where send(notification_row) raises on failure. Real push
and SMS gateways are not chosen yet; tests pass fakes.

PLACEHOLDER: message text. Rows carry template_id and payload only. Bangla wording
needs the lawyer (consent notices) and the clinical reviewer (vitals, emergency).
PLACEHOLDER: quiet hours (Asia/Dhaka) are not implemented; the FRD gives no hours.
shortcut: no Celery yet, deliver_due is a plain function; wrap it in a task when
Redis and hosting exist.
"""
from datetime import timedelta
from uuid import uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from swasthyoid.core import audit


def enqueue(conn, *, recipient_id, template_id, payload):
    """Persist one notification as queued and return the row. Sends nothing."""
    return conn.cursor(row_factory=dict_row).execute(
        "INSERT INTO notifications (id, recipient_id, template_id, payload) VALUES (%s, %s, %s, %s) RETURNING *",
        [uuid4(), recipient_id, template_id, Jsonb(payload)],
    ).fetchone()


def _record(conn, notification_id, channel, attempt, error):
    conn.execute(
        "INSERT INTO notification_deliveries (id, notification_id, channel, attempt, status, error) "
        "VALUES (%s, %s, %s, %s, %s, %s)",
        [uuid4(), notification_id, channel, attempt, "failed" if error else "sent", error],
    )


def _deliver_one(conn, channels, max_attempts, backoff):
    with conn.transaction():
        # shortcut: the row stays locked while the gateway is called; fine for a prototype
        # worker, split claim and send if gateway calls get slow.
        n = conn.cursor(row_factory=dict_row).execute(
            """SELECT * FROM notifications
               WHERE status = 'queued' AND next_attempt_at <= clock_timestamp()
               ORDER BY created_at, id LIMIT 1 FOR UPDATE SKIP LOCKED"""
        ).fetchone()
        if n is None:
            return False
        attempt = n["attempts"] + 1
        error = "no channels configured"
        for name, send in channels:
            try:
                send(n)
                error = None
            except Exception as e:  # any gateway failure moves on to the next channel
                error = f"{type(e).__name__}: {e}"[:500]
            _record(conn, n["id"], name, attempt, error)
            if error is None:
                break
        status = "queued"
        if error is None:
            status = "delivered"
        elif attempt >= max_attempts:
            status = "fallback_in_app"
            _record(conn, n["id"], "in_app", attempt, None)
            audit.append(conn, action="notification.failure", result="failed", reason=error,
                         resource_type="notification", resource_id=n["id"])
        conn.execute(
            "UPDATE notifications SET status = %s, attempts = %s, next_attempt_at = clock_timestamp() + %s "
            "WHERE id = %s",
            [status, attempt, backoff * 2 ** (attempt - 1), n["id"]],
        )
        return True


def deliver_due(conn, channels, *, max_attempts=3, backoff=timedelta(minutes=1), limit=100):
    """Try every due notification once and return how many were tried. Safe to run from
    several workers. Delivery is at-least-once: a crash after sending resends later."""
    done = 0
    while done < limit and _deliver_one(conn, channels, max_attempts, backoff):
        done += 1
    return done


def inbox(conn, recipient_id):
    """In-app inbox: the recipient's notifications that fell back to in-app, newest first."""
    return conn.cursor(row_factory=dict_row).execute(
        "SELECT * FROM notifications WHERE recipient_id = %s AND status = 'fallback_in_app' "
        "ORDER BY created_at DESC, id",
        [recipient_id],
    ).fetchall()
