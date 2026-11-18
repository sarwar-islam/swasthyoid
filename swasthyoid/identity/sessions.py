"""Short-lived JWT access tokens and device-bound, rotating refresh tokens (FRD M1).

JWT_SECRET comes from the environment; there is no default.
The lifetimes are security defaults, not FRD values; change them here.
"""
import os
import secrets
from datetime import datetime, timedelta, timezone
from uuid import uuid4

import jwt
from psycopg.rows import dict_row

from swasthyoid import pii
from swasthyoid.core import audit

ACCESS_TTL = timedelta(minutes=15)
REFRESH_TTL = timedelta(days=30)
# W2 owner decision (a), 2026-11-17: a session with no request for this long ends (audited "session_idle").
IDLE_TIMEOUT = {"patient": timedelta(minutes=30)}
STAFF_IDLE_TIMEOUT = timedelta(minutes=15)


def idle_timeout(role):
    return IDLE_TIMEOUT.get(role, STAFF_IDLE_TIMEOUT)


class InvalidSession(Exception):
    pass


def _token_hash(token):
    return pii.secret_hash("refresh:" + token)


# UX-3c: (marker in the user-agent, name), first match wins; order matters (Edge and Opera also say "Chrome").
_BROWSERS = (("Edg/", "Edge"), ("OPR/", "Opera"), ("SamsungBrowser/", "Samsung Internet"), ("Firefox/", "Firefox"),
             ("Chrome/", "Chrome"), ("Safari/", "Safari"))
_SYSTEMS = (("Android", "Android"), ("iPhone", "iOS"), ("iPad", "iOS"), ("Windows", "Windows"), ("Mac OS X", "macOS"),
            ("CrOS", "ChromeOS"), ("Linux", "Linux"))


def device_label(user_agent):
    """A device family such as "Chrome · Android", or None. Only this label is stored or shown, never the user-agent."""
    ua = user_agent or ""
    browser = next((name for mark, name in _BROWSERS if mark in ua), None)
    system = next((name for mark, name in _SYSTEMS if mark in ua), None)
    return " · ".join(p for p in (browser, system) if p) or None


def _new_tokens(conn, subject_id, role, device_id, last_seen_at=None, session_id=None, label=None):
    refresh_token = secrets.token_urlsafe(32)
    conn.execute(  # a rotated token keeps its session's last activity: a silent refresh is not activity
        "INSERT INTO refresh_tokens (id, subject_id, role, device_id, token_hash, expires_at, last_seen_at, session_id, "
        "device_label) VALUES (%s, %s, %s, %s, %s, clock_timestamp() + %s, coalesce(%s, clock_timestamp()), %s, %s)",
        [uuid4(), subject_id, role, device_id, _token_hash(refresh_token), REFRESH_TTL, last_seen_at,
         session_id or uuid4(), label],
    )
    now = datetime.now(timezone.utc)
    access_token = jwt.encode(
        {"sub": str(subject_id), "role": role, "device_id": device_id, "iat": now, "exp": now + ACCESS_TTL},
        os.environ["JWT_SECRET"], algorithm="HS256",
    )
    return {"access_token": access_token, "refresh_token": refresh_token}


def issue_tokens(conn, *, subject_id, role, device_id, ip=None, user_agent=None):
    """Log a subject in on a device. Call only after their one-time code was verified."""
    with conn.transaction():
        tokens = _new_tokens(conn, subject_id, role, device_id, label=device_label(user_agent))
        audit.append(conn, action="auth.login", result="allow", actor_id=subject_id, actor_role=role,
                     device_id=device_id, ip=ip, user_agent=user_agent)
    return tokens


def read_access_token(token):
    """Claims of a valid access token; raises jwt.InvalidTokenError otherwise."""
    return jwt.decode(token, os.environ["JWT_SECRET"], algorithms=["HS256"],
                      options={"require": ["sub", "role", "device_id", "exp"]})


def refresh(conn, refresh_token, device_id):
    """Swap a refresh token for a new pair. Each token works once and only on its device."""
    with conn.transaction():
        row = conn.cursor(row_factory=dict_row).execute(
            "SELECT *, expires_at <= clock_timestamp() AS expired, "
            "last_seen_at <= clock_timestamp() - CASE WHEN role = 'patient' THEN %s ELSE %s END AS idle "
            "FROM refresh_tokens WHERE token_hash = %s FOR UPDATE",
            [IDLE_TIMEOUT["patient"], STAFF_IDLE_TIMEOUT, _token_hash(str(refresh_token))],
        ).fetchone()
        tokens = reason = None
        if row is None:
            reason = "unknown_token"
        elif row["device_id"] != device_id:
            reason = "device_mismatch"
        elif row["revoked_at"] is not None:
            reason = "token_reused"  # a used token came back: assume theft, end this device's sessions
            conn.execute(
                "UPDATE refresh_tokens SET revoked_at = clock_timestamp() "
                "WHERE subject_id = %s AND device_id = %s AND revoked_at IS NULL",
                [row["subject_id"], row["device_id"]],
            )
        elif row["expired"]:
            reason = "expired"
        elif row["idle"]:
            reason = "session_idle"
            revoke_device(conn, row["subject_id"], row["device_id"])
        else:
            conn.execute("UPDATE refresh_tokens SET revoked_at = clock_timestamp() WHERE id = %s", [row["id"]])
            tokens = _new_tokens(conn, row["subject_id"], row["role"], device_id, row["last_seen_at"], row["session_id"],
                                 row["device_label"])
        if reason:
            audit.append(conn, action="auth.refresh_failed", result="deny", reason=reason,
                         actor_id=row and row["subject_id"], device_id=device_id)
    if reason:  # raised after the block so the audit entry and revocations are kept
        raise InvalidSession(reason)
    return tokens


def touch(conn, subject_id, role, device_id):
    """"live" (and the request counts as activity), "idle" (no request within idle_timeout: the session is ended now) or
    "ended". A device's session is live while it holds an unrevoked, unexpired refresh token that was active recently.
    Logging out, a reused refresh token and suspension revoke them, so the access token stops at once, not at ACCESS_TTL."""
    live = "subject_id = %s AND device_id = %s AND revoked_at IS NULL AND expires_at > clock_timestamp()"
    # shortcut: one write per request; throttle it (only when last_seen_at is a minute old) if it shows up under load
    if conn.execute(f"UPDATE refresh_tokens SET last_seen_at = clock_timestamp() WHERE {live} "
                    "AND last_seen_at > clock_timestamp() - %s RETURNING 1",
                    [subject_id, device_id, idle_timeout(role)]).fetchone():
        return "live"
    idle = conn.execute(f"UPDATE refresh_tokens SET revoked_at = clock_timestamp() WHERE {live} RETURNING 1",
                        [subject_id, device_id]).fetchone()
    return "idle" if idle else "ended"


def revoke_device(conn, subject_id, device_id):
    """End this device's session (logout)."""
    return conn.execute(
        "UPDATE refresh_tokens SET revoked_at = clock_timestamp() "
        "WHERE subject_id = %s AND device_id = %s AND revoked_at IS NULL", [subject_id, device_id]).rowcount


class NotYourSession(Exception):
    """No such session for this account (someone else's looks the same: 404)."""


class CurrentSession(Exception):
    """The session of the device asking; Sign out ends it."""


_LIVE = "revoked_at IS NULL AND expires_at > clock_timestamp()"


def list_sessions(conn, subject_id, device_id):
    """This account's live sessions, most recently active first. `current` marks the asking device."""
    rows = conn.cursor(row_factory=dict_row).execute(
        f"SELECT session_id AS id, max(device_label) AS device, min(created_at) AS started_at, "
        f"max(last_seen_at) AS last_seen_at, bool_or(device_id = %s) AS current FROM refresh_tokens "
        f"WHERE subject_id = %s GROUP BY session_id HAVING bool_or({_LIVE}) ORDER BY current DESC, last_seen_at DESC",
        [device_id, subject_id]).fetchall()
    return rows


def revoke_session(conn, subject_id, session_id, device_id):
    """End one of this account's other sessions. Idempotent: an ended session stays ended. Returns tokens revoked."""
    row = conn.execute("SELECT bool_or(device_id = %s) FROM refresh_tokens WHERE subject_id = %s AND session_id = %s",
                       [device_id, subject_id, session_id]).fetchone()
    if row[0] is None:
        raise NotYourSession()
    if row[0]:
        raise CurrentSession()
    return conn.execute("UPDATE refresh_tokens SET revoked_at = clock_timestamp() "
                        "WHERE subject_id = %s AND session_id = %s AND revoked_at IS NULL", [subject_id, session_id]).rowcount


def revoke_all(conn, subject_id):
    """End every session of a subject (suspension, phone change). Access tokens run out within ACCESS_TTL."""
    return conn.execute(
        "UPDATE refresh_tokens SET revoked_at = clock_timestamp() WHERE subject_id = %s AND revoked_at IS NULL",
        [subject_id],
    ).rowcount
