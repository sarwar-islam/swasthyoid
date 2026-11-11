"""Patients, staff users and their credentials (FRD M1, section 2).

Callers must have verified the phone by one-time code before registering anyone.
Status of a staff user: pending -> verified -> suspended.
"""
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row

from swasthyoid import pii
from swasthyoid.core import audit, consent_authz
from swasthyoid.identity import health_id, sessions


def register_patient(conn, *, phone, name, dob, sex, language="bn"):
    """Create a patient with a new Health ID. Raises UniqueViolation if the phone is already registered."""
    phone = pii.normalize_phone(phone)
    for _ in range(5):  # a Health ID collision is retried with a fresh random ID
        try:
            with conn.transaction():
                return conn.cursor(row_factory=dict_row).execute(
                    """INSERT INTO patients (id, health_id, phone_hash, phone_enc, name_enc, dob, sex, language)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING *""",
                    [uuid4(), health_id.generate(), pii.phone_hash(phone), pii.encrypt(phone),
                     pii.encrypt(name), dob, sex, language],
                ).fetchone()
        except psycopg.errors.UniqueViolation as e:
            if e.diag.constraint_name != "patients_health_id_key":
                raise
    raise RuntimeError("could not allocate a unique Health ID")


def _insert_user(conn, phone, role, name, status):
    phone = pii.normalize_phone(phone)
    return conn.cursor(row_factory=dict_row).execute(
        "INSERT INTO users (id, role, name, status, phone_hash, phone_enc) VALUES (%s, %s, %s, %s, %s, %s) RETURNING *",
        [uuid4(), role, name, status, pii.phone_hash(phone), pii.encrypt(phone)],
    ).fetchone()


def register_user(conn, *, phone, role, name):
    """Create a staff user as `pending`. They can do nothing until an admin approves a credential."""
    if role == "admin":
        raise PermissionError("admins are created by seed_admin only")
    return _insert_user(conn, phone, role, name, "pending")


def seed_admin(conn, *, phone, name):
    """Create a verified admin. For deployment seeding only; never expose this over HTTP."""
    return _insert_user(conn, phone, "admin", name, "verified")


def _require_admin(conn, admin_id):
    ok = conn.execute(
        "SELECT 1 FROM users WHERE id = %s AND role = 'admin' AND status = 'verified'", [admin_id]).fetchone()
    if not ok:
        raise PermissionError("a verified admin is required")


def _log(conn, action, admin_id, user_id):
    audit.append(conn, action=action, result="allow", actor_id=admin_id, actor_role="admin",
                 resource_type="user", resource_id=user_id)


def submit_credential(conn, *, user_id, type, number, doc_key=None):
    """Record a credential (e.g. BMDC number, pharmacy licence) as `pending` for admin review."""
    return conn.cursor(row_factory=dict_row).execute(
        "INSERT INTO credentials (id, user_id, type, number, doc_key) VALUES (%s, %s, %s, %s, %s) RETURNING *",
        [uuid4(), user_id, type, number, doc_key],
    ).fetchone()


def approve_credential(conn, credential_id, *, admin_id):
    """Admin approves a pending credential; its owner becomes `verified`."""
    with conn.transaction():
        _require_admin(conn, admin_id)
        row = conn.execute(
            "UPDATE credentials SET status = 'verified', reviewed_by = %s, updated_at = clock_timestamp() "
            "WHERE id = %s AND status = 'pending' RETURNING user_id",
            [admin_id, credential_id],
        ).fetchone()
        if row is None:
            raise ValueError("no pending credential with this id")
        conn.execute(
            "UPDATE users SET status = 'verified', updated_at = clock_timestamp() WHERE id = %s AND status = 'pending'",
            [row[0]],
        )
        _log(conn, "credential.approve", admin_id, row[0])
        return row[0]


def _set_status(conn, user_id, admin_id, old, new, action):
    _require_admin(conn, admin_id)
    changed = conn.execute(
        "UPDATE users SET status = %s, updated_at = clock_timestamp() WHERE id = %s AND status = %s",
        [new, user_id, old],
    ).rowcount
    if not changed:
        raise ValueError(f"user is not {old}")
    conn.execute(
        "UPDATE credentials SET status = %s, updated_at = clock_timestamp() WHERE user_id = %s AND status = %s",
        [new, user_id, old],
    )
    _log(conn, action, admin_id, user_id)


def suspend_user(conn, user_id, *, admin_id):
    """verified -> suspended. Their active grants stop working and every session ends."""
    with conn.transaction():
        _set_status(conn, user_id, admin_id, "verified", "suspended", "credential.suspend")
        consent_authz.suspend_grantee(conn, user_id, actor_id=admin_id)
        sessions.revoke_all(conn, user_id)


def restore_user(conn, user_id, *, admin_id):
    """suspended -> verified. Suspended grants work again; the user must log in again."""
    with conn.transaction():
        _set_status(conn, user_id, admin_id, "suspended", "verified", "credential.restore")
        consent_authz.restore_grantee(conn, user_id, actor_id=admin_id)
