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


SELF_REGISTER_ROLES = ("doctor", "verifier")  # console roles are created by an admin (owner decision 2026-11-16)


def register_user(conn, *, phone, role, name):
    """Create a staff user as `pending`. They can do nothing until an admin approves them."""
    if role not in SELF_REGISTER_ROLES:
        raise PermissionError(f"{role} accounts cannot self-register")
    return _insert_user(conn, phone, role, name, "pending")


def seed_admin(conn, *, phone, name):
    """Create a verified admin. For deployment seeding only; never expose this over HTTP."""
    return _insert_user(conn, phone, "admin", name, "verified")


def _require_admin(conn, admin_id):
    ok = conn.execute(
        "SELECT 1 FROM users WHERE id = %s AND role = 'admin' AND status = 'verified'", [admin_id]).fetchone()
    if not ok:
        raise PermissionError("a verified admin is required")


def _log(conn, action, admin_id, user_id, reason=None):
    audit.append(conn, action=action, result="allow", actor_id=admin_id, actor_role="admin",
                 resource_type="user", resource_id=user_id, reason=reason)


ADMIN_CREATED_ROLES = ("verifier", "clinical_reviewer")  # doctors register and are approved through their credential


def create_staff(conn, *, admin_id, role, name, phone):
    """An admin creates a verifier or clinical reviewer account, already verified (owner decision 2026-11-16: console
    roles never self-register). Raises PermissionError for other roles, UniqueViolation if the phone has an account."""
    if role not in ADMIN_CREATED_ROLES:
        raise PermissionError(f"admins cannot create {role} accounts")
    with conn.transaction():
        _require_admin(conn, admin_id)
        row = _insert_user(conn, phone, role, name, "verified")
        _log(conn, "staff.create", admin_id, row["id"])
        return row


def approve_staff(conn, user_id, *, admin_id):
    """An admin approves a verifier who registered themselves (pending -> verified)."""
    with conn.transaction():
        _require_admin(conn, admin_id)
        row = conn.cursor(row_factory=dict_row).execute(
            "UPDATE users SET status = 'verified', updated_at = clock_timestamp() "
            "WHERE id = %s AND role = 'verifier' AND status = 'pending' RETURNING *", [user_id]).fetchone()
        if row is None:
            raise ValueError("no pending verifier with this id")
        _log(conn, "staff.approve", admin_id, user_id)
        return row


def list_staff(conn, status=None):
    """Verifier and clinical reviewer accounts, oldest first, optionally of one status."""
    return conn.cursor(row_factory=dict_row).execute(
        "SELECT * FROM users WHERE role IN ('verifier', 'clinical_reviewer') AND (%s::text IS NULL OR status = %s) "
        "ORDER BY created_at, id", [status, status]).fetchall()


def list_credentials(conn, status=None):
    """Credentials with their owner's name and account status, oldest first, optionally of one status."""
    return conn.cursor(row_factory=dict_row).execute(
        "SELECT c.*, u.name, u.role, u.status AS user_status FROM credentials c JOIN users u ON u.id = c.user_id "
        "WHERE (%s::text IS NULL OR c.status = %s) ORDER BY c.created_at, c.id", [status, status]).fetchall()


def current_credential(conn, user_id):
    """The user's newest credential that was not rejected, or None."""
    return conn.cursor(row_factory=dict_row).execute(
        "SELECT * FROM credentials WHERE user_id = %s AND status <> 'rejected' ORDER BY created_at DESC LIMIT 1",
        [user_id]).fetchone()


def reject_credential(conn, credential_id, *, admin_id, reason):
    """An admin rejects a pending credential. The row is kept with the reason; the number may be submitted again.
    The audit entry says only that a reason was given (free text may hold personal detail)."""
    if not reason or not reason.strip():
        raise ValueError("a reason is required")
    with conn.transaction():
        _require_admin(conn, admin_id)
        row = conn.execute(
            "UPDATE credentials SET status = 'rejected', reviewed_by = %s, review_reason = %s, updated_at = clock_timestamp() "
            "WHERE id = %s AND status = 'pending' RETURNING user_id",
            [admin_id, reason.strip(), credential_id]).fetchone()
        if row is None:
            raise LookupError("no pending credential with this id")
        _log(conn, "credential.reject", admin_id, row[0], reason="reason_given")
        return row[0]


def submit_credential(conn, *, user_id, type, number, doc_key=None):
    """Record a credential (e.g. BMDC number) as `pending` for admin review."""
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


def _set_status(conn, user_id, admin_id, old, new, action, reason=None):
    _require_admin(conn, admin_id)
    changed = conn.execute(
        "UPDATE users SET status = %s, status_reason = %s, updated_at = clock_timestamp() "
        "WHERE id = %s AND status = %s AND role <> 'admin'",  # an admin never changes another admin's status
        [new, reason, user_id, old],
    ).rowcount
    if not changed:
        raise ValueError(f"user is not a {old} staff member")
    conn.execute(
        "UPDATE credentials SET status = %s, updated_at = clock_timestamp() WHERE user_id = %s AND status = %s",
        [new, user_id, old],
    )
    _log(conn, action, admin_id, user_id, reason="reason_given" if reason else None)


def suspend_user(conn, user_id, *, admin_id, reason=None):
    """verified -> suspended, for any staff role but admin. Their active grants stop working and every session ends.
    The reason is kept on the account; the audit entry says only that one was given."""
    with conn.transaction():
        _set_status(conn, user_id, admin_id, "verified", "suspended", "credential.suspend", reason)
        consent_authz.end_sessions_of(conn, user_id, actor_id=admin_id)  # a verifier's assisted sessions end for good
        consent_authz.suspend_grantee(conn, user_id, actor_id=admin_id)
        sessions.revoke_all(conn, user_id)


def restore_user(conn, user_id, *, admin_id):
    """suspended -> verified. Suspended grants work again; the user must log in again."""
    with conn.transaction():
        _set_status(conn, user_id, admin_id, "suspended", "verified", "credential.restore")
        consent_authz.restore_grantee(conn, user_id, actor_id=admin_id)
