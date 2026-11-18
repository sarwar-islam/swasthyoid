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
W3: workers/deliver.py runs deliver_due in a loop. Each attempt is claim -> send -> record: the claim commits the
attempt number and pushes the row out of reach for CLAIM_LEASE, the gateway is called with no lock held, and the result is
recorded only if this worker's claim still stands. The attempt key (notification id : attempt) goes to the gateway so it
can drop a repeat; a worker that dies after sending leaves the row due again once the lease ends (at-least-once).
"""
import logging
from datetime import timedelta
from uuid import uuid4

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from swasthyoid import pii
from swasthyoid.core import audit

CLAIM_LEASE = timedelta(minutes=5)  # longer than any gateway call; a claim older than this is taken again
log = logging.getLogger(__name__)


def send_code_dev(phone, code, context=None):
    """DEV ONLY one-time-code sender: writes the code to the log instead of sending an SMS.
    Reachable only with DEV_LOG_CODES=1 and APP_ENV=development (see api/deps.py).

    PLACEHOLDER: the real SMS gateway is not chosen. Codes do not go through the queue
    below, because a queued row would store the code and a new phone has no recipient id yet.
    """
    logging.getLogger(__name__).warning("DEV one-time code for ...%s: %s", phone[-3:], code)


def enqueue(conn, *, recipient_id, template_id, payload):
    """Persist one notification as queued and return the row. Sends nothing."""
    return conn.cursor(row_factory=dict_row).execute(
        "INSERT INTO notifications (id, recipient_id, template_id, payload) VALUES (%s, %s, %s, %s) RETURNING *",
        [uuid4(), recipient_id, template_id, Jsonb(payload)],
    ).fetchone()


def _record(conn, notification_id, channel, attempt, error):
    conn.execute(
        "INSERT INTO notification_deliveries (id, notification_id, channel, attempt, status, error) "
        "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT (notification_id, channel, attempt) DO NOTHING",
        [uuid4(), notification_id, channel, attempt, "failed" if error else "sent", error],
    )


def attempt_key(n):
    """The idempotency key a gateway gets for this attempt: the same notification and attempt never send twice."""
    return f"{n['id']}:{n['attempts']}"


def _claim(conn, lease):
    """Take the next due notification for one attempt: commit the attempt number and hide the row for `lease`."""
    with conn.transaction():
        return conn.cursor(row_factory=dict_row).execute(
            """UPDATE notifications SET attempts = attempts + 1, next_attempt_at = clock_timestamp() + %s
               WHERE id = (SELECT id FROM notifications WHERE status = 'queued' AND next_attempt_at <= clock_timestamp()
                           ORDER BY created_at, id LIMIT 1 FOR UPDATE SKIP LOCKED)
               RETURNING *""", [lease]).fetchone()


def _deliver_one(conn, channels, max_attempts, backoff, lease=CLAIM_LEASE):
    n = _claim(conn, lease)
    if n is None:
        return False
    attempt = n["attempts"]
    results, error = [], "no channels configured"
    for name, send in channels:  # no transaction or lock held while a gateway is called
        try:
            send(n)
            error = None
        except Exception as e:  # any gateway failure moves on to the next channel
            error = f"{type(e).__name__}: {e}"[:500]
        results.append((name, error))
        if error is None:
            break
    with conn.transaction():
        # Record only if the claim still stands: a worker whose lease ran out lost the row to another one.
        if conn.execute("SELECT 1 FROM notifications WHERE id = %s AND attempts = %s AND status = 'queued' FOR UPDATE",
                        [n["id"], attempt]).fetchone() is None:
            return True
        for name, err in results:
            _record(conn, n["id"], name, attempt, err)
        status = "queued"
        if error is None:
            status = "delivered"
        elif attempt >= max_attempts:
            status = "fallback_in_app"
            _record(conn, n["id"], "in_app", attempt, None)
            audit.append(conn, action="notification.failure", result="failed", reason=error,
                         resource_type="notification", resource_id=n["id"])
        conn.execute("UPDATE notifications SET status = %s, next_attempt_at = clock_timestamp() + %s WHERE id = %s",
                     [status, backoff * 2 ** (attempt - 1), n["id"]])
    return True


def in_app_channel(n):
    """The inbox already shows every notification (B3), so this channel has nothing to send."""


def _phone(conn, recipient_id):
    row = conn.execute("SELECT phone_enc FROM patients WHERE id = %s UNION ALL SELECT phone_enc FROM users WHERE id = %s",
                       [recipient_id, recipient_id]).fetchone()
    if row is None:
        raise LookupError("recipient has no phone")
    return pii.decrypt(row[0])


def sms_console_channel(conn):
    """DEV/DEMO SMS channel: logs the template id and the phone's last three digits only, never the number, the
    payload or any text. PLACEHOLDER (S2): the real SMS gateway is not chosen; it gets attempt_key(n) to drop repeats."""
    def send(n):
        log.info("sms_console template=%s to=...%s key=%s", n["template_id"], _phone(conn, n["recipient_id"])[-3:],
                 attempt_key(n))
    return send


def deliver_due(conn, channels, *, max_attempts=3, backoff=timedelta(minutes=1), limit=100):
    """Try every due notification once and return how many were tried. Safe to run from
    several workers. Delivery is at-least-once: a crash after sending resends later."""
    done = 0
    while done < limit and _deliver_one(conn, channels, max_attempts, backoff):
        done += 1
    return done


# The in-app kind of each template the patient's inbox shows (B3; owner decisions 2026-11-16). Consent, caregiver and
# emergency-access notices are security notices: there is no setting to switch them off (FRD 4.3). Others stay out.
INBOX_KINDS = {
    "CONSENT_REQUEST_PLACEHOLDER": "consent_request",
    "CONSENT_GRANTED_PLACEHOLDER": "consent_granted",
    "CAREGIVER_REQUEST_PLACEHOLDER": "caregiver_request",
    "CAREGIVER_GRANTED_PLACEHOLDER": "caregiver_granted",
    "EMERGENCY_ACCESS_PLACEHOLDER": "emergency_access",  # written by M10 (B7)
    # M13 (P6): a home reading an approved threshold rule called critical or flagged. The text is that rule version's own
    # approved explanation, read when shown. No quiet-hours bypass: there is no approved policy (safeguard 2).
    "VITAL_CRITICAL_PLACEHOLDER": "vital_critical",
    "VITAL_FLAGGED_PLACEHOLDER": "vital_flagged",
}
INBOX_LIMIT = 100


def inbox(conn, recipient_id, limit=INBOX_LIMIT):
    """In-app inbox: the recipient's newest notifications, whatever happened to push or SMS delivery (B3). The in-app
    copy is always there; a delivery failure only adds the audit entry."""
    return conn.cursor(row_factory=dict_row).execute(
        "SELECT * FROM notifications WHERE recipient_id = %s ORDER BY created_at DESC, id LIMIT %s",
        [recipient_id, limit],
    ).fetchall()


def mark_read(conn, notification_id, recipient_id):
    """Mark one of the recipient's notifications read (once; a repeat keeps the first time). None if not theirs."""
    return conn.cursor(row_factory=dict_row).execute(
        "UPDATE notifications SET read_at = COALESCE(read_at, clock_timestamp()) "
        "WHERE id = %s AND recipient_id = %s RETURNING *",
        [notification_id, recipient_id],
    ).fetchone()
