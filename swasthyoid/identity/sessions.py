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


class InvalidSession(Exception):
    pass


def _token_hash(token):
    return pii.secret_hash("refresh:" + token)


def _new_tokens(conn, subject_id, role, device_id):
    refresh_token = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO refresh_tokens (id, subject_id, role, device_id, token_hash, expires_at) "
        "VALUES (%s, %s, %s, %s, %s, clock_timestamp() + %s)",
        [uuid4(), subject_id, role, device_id, _token_hash(refresh_token), REFRESH_TTL],
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
        tokens = _new_tokens(conn, subject_id, role, device_id)
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
            "SELECT *, expires_at <= clock_timestamp() AS expired FROM refresh_tokens WHERE token_hash = %s FOR UPDATE",
            [_token_hash(str(refresh_token))],
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
        else:
            conn.execute("UPDATE refresh_tokens SET revoked_at = clock_timestamp() WHERE id = %s", [row["id"]])
            tokens = _new_tokens(conn, row["subject_id"], row["role"], device_id)
        if reason:
            audit.append(conn, action="auth.refresh_failed", result="deny", reason=reason,
                         actor_id=row and row["subject_id"], device_id=device_id)
    if reason:  # raised after the block so the audit entry and revocations are kept
        raise InvalidSession(reason)
    return tokens


def revoke_all(conn, subject_id):
    """End every session of a subject (suspension, phone change). Access tokens run out within ACCESS_TTL."""
    return conn.execute(
        "UPDATE refresh_tokens SET revoked_at = clock_timestamp() WHERE subject_id = %s AND revoked_at IS NULL",
        [subject_id],
    ).rowcount
