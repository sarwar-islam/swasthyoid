"""C1 — consent and authorization (FRD section 4.1).

First the pure decision logic, then the consent store. The caller loads the consent
with find(), calls authorize_access, and MUST write the C2 audit entry for every
decision, allow or deny.
"""
from dataclasses import dataclass
from uuid import UUID, uuid4

from psycopg.rows import dict_row

from swasthyoid.core import audit

PURPOSES = {"TIMELINE", "APPOINTMENT", "REFERRAL", "DISPENSING", "EMERGENCY", "CLOUD_AI"}

# Consent state machine, FRD section 4.1. expired and revoked are terminal.
TRANSITIONS = {
    "pending": {"active", "expired"},
    "active": {"expired", "revoked", "suspended"},
    "suspended": {"active", "revoked"},
    "expired": set(),
    "revoked": set(),
}


def transition(status, target):
    """Return target if the move is allowed by the state machine, else raise."""
    if target not in TRANSITIONS.get(status, ()):
        raise ValueError(f"illegal consent transition: {status} -> {target}")
    return target


@dataclass(frozen=True)
class Resource:
    type: str
    id: str
    # Is the bound thing usable right now (appointment checked in, referral token
    # live, prescription open)? The owning module supplies this. Defaults to closed.
    live: bool = False


@dataclass(frozen=True)
class AccessRequest:
    purpose: str
    data_categories: frozenset
    resource: Resource | None = None


@dataclass(frozen=True)
class Consent:
    id: str
    patient_id: str
    grantee_id: str
    purpose: str
    status: str
    allowed_categories: frozenset
    expires_at: object  # tz-aware datetime; a consent without an expiry is denied
    max_window_ends_at: object = None  # optional hard stop (appointments)
    resource_type: str | None = None
    resource_id: str | None = None


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str | None = None
    consent_id: str | None = None


def deny(reason):
    return Decision(False, reason)


def binding_valid(consent, resource):
    if consent.resource_type is None and consent.resource_id is None:
        return resource is None  # unbound consent (TIMELINE): request must not name a resource
    return (
        resource is not None
        and resource.type == consent.resource_type
        and resource.id == consent.resource_id
        and resource.live is True
    )


def authorize_access(req, user, patient, consent, now):
    """Decide one non-patient access. `now` is server time, never client time."""
    try:
        return _authorize(req, user, patient, consent, now)
    except Exception:
        return deny("authorization_error")  # fail closed (FRD invariant 8)


def _authorize(req, user, patient, consent, now):
    if not (user.is_verified is True and user.is_active is True):
        return deny("user_not_verified")
    if req.purpose not in PURPOSES:
        return deny("unknown_purpose")
    if req.purpose == "EMERGENCY":
        # PLACEHOLDER: emergency policy is M10 (phase P9, conditional on clinical
        # reviewer and lawyer approval). Until then every emergency request is denied.
        return deny("emergency_not_enabled")
    if consent is None:
        return deny("consent_required")
    if consent.patient_id != patient.id:
        return deny("patient_mismatch")
    if consent.grantee_id != user.id:
        return deny("grantee_mismatch")
    if consent.purpose != req.purpose:
        return deny("purpose_mismatch")
    if consent.status != "active":
        return deny("not_active")
    if consent.expires_at is None or now > consent.expires_at:
        return deny("expired")
    if consent.max_window_ends_at is not None and now > consent.max_window_ends_at:
        return deny("expired")
    if not binding_valid(consent, req.resource):
        return deny("binding_invalid")
    if not req.data_categories or not req.data_categories <= consent.allowed_categories:
        return deny("category_not_allowed")
    return Decision(True, consent_id=consent.id)


# ---- Consent store (PostgreSQL). Every change is written to consent_events and to
# the C2 audit log in the same transaction: if the audit write fails, the change fails.

def _now(conn):
    return conn.execute("SELECT clock_timestamp()").fetchone()[0]  # server time only


def _log(conn, row, action, actor_id):
    conn.execute(
        "INSERT INTO consent_events (id, consent_id, action, actor_id) VALUES (%s, %s, %s, %s)",
        [uuid4(), row["id"], action, actor_id],
    )
    audit.append(
        conn, action=f"consent.{action}", result="allow", actor_id=actor_id, patient_id=row["patient_id"],
        consent_id=row["id"], purpose=row["purpose"], resource_type=row["resource_type"],
        resource_id=row["resource_id"],
    )


def _change(conn, consent_id, target, action, actor_id, patient_only=False, **cols):
    """Move one consent to `target` if the state machine allows it; return the new row."""
    with conn.transaction():
        cur = conn.cursor(row_factory=dict_row)
        row = cur.execute("SELECT * FROM consents WHERE id = %s FOR UPDATE", [consent_id]).fetchone()
        if row is None:
            raise LookupError("consent not found")
        if patient_only and (actor_id is None or UUID(str(actor_id)) != row["patient_id"]):
            raise PermissionError("only the patient may do this")
        cols["status"] = transition(row["status"], target)
        sets = ", ".join(f"{c} = %s" for c in cols)  # column names come from this module only
        row = cur.execute(
            f"UPDATE consents SET {sets}, updated_at = clock_timestamp() WHERE id = %s RETURNING *",
            [*cols.values(), consent_id],
        ).fetchone()
        _log(conn, row, action, actor_id)
        return row


def create(conn, *, patient_id, grantee_id, grantee_role, purpose, allowed_categories, consent_version,
           policy_version, actor_id, resource_type=None, resource_id=None, max_window_ends_at=None):
    """Record a consent request as `pending`. It grants nothing until activated."""
    with conn.transaction():
        row = conn.cursor(row_factory=dict_row).execute(
            """INSERT INTO consents (id, patient_id, grantee_id, grantee_role, purpose, resource_type,
                   resource_id, allowed_categories, status, max_window_ends_at, consent_version, policy_version)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'pending', %s, %s, %s) RETURNING *""",
            [uuid4(), patient_id, grantee_id, grantee_role, purpose, resource_type, resource_id,
             sorted(allowed_categories), max_window_ends_at, consent_version, policy_version],
        ).fetchone()
        _log(conn, row, "create", actor_id)
        return row


def activate(conn, consent_id, *, method, expires_at, actor_id):
    """pending -> active. The caller must already have verified the patient's confirmation
    (OTP or QR); that check arrives with M1 in slice 6."""
    with conn.transaction():
        now = _now(conn)
        if expires_at is None or expires_at <= now:
            raise ValueError("expires_at must be in the future")
        return _change(conn, consent_id, "active", "activate", actor_id,
                       method=method, activated_at=now, expires_at=expires_at)


def revoke(conn, consent_id, *, actor_id):
    """Patient revokes. Takes effect on the next request, which reads the new status."""
    with conn.transaction():
        return _change(conn, consent_id, "revoked", "revoke", actor_id, patient_only=True,
                       revoked_at=_now(conn), revoked_by=actor_id)


def _change_all(conn, where, params, target, action, actor_id):
    with conn.transaction():
        ids = conn.execute(f"SELECT id FROM consents WHERE {where} ORDER BY id FOR UPDATE", params).fetchall()
        for (consent_id,) in ids:
            _change(conn, consent_id, target, action, actor_id)
        return len(ids)


def suspend_grantee(conn, grantee_id, *, actor_id):
    """Grantee's credential was suspended: all their active consents stop working."""
    return _change_all(conn, "grantee_id = %s AND status = 'active'", [grantee_id], "suspended", "suspend", actor_id)


def restore_grantee(conn, grantee_id, *, actor_id):
    """Credential restored: suspended consents work again (if not expired meanwhile)."""
    return _change_all(conn, "grantee_id = %s AND status = 'suspended'", [grantee_id], "active", "restore", actor_id)


def expire_due(conn):
    """Mark active consents past their expiry or max window as expired. For a periodic job;
    access is already denied by time in authorize_access before this runs."""
    return _change_all(
        conn,
        "status = 'active' AND (expires_at < clock_timestamp() OR max_window_ends_at < clock_timestamp())",
        [], "expired", "expire", None,
    )


def find(conn, *, grantee_id, patient_id, purpose, resource=None):
    """The consent to judge a request against, or None. Prefers an active one, then the newest."""
    row = conn.cursor(row_factory=dict_row).execute(
        """SELECT * FROM consents
           WHERE grantee_id = %s AND patient_id = %s AND purpose = %s
             AND resource_type IS NOT DISTINCT FROM %s AND resource_id IS NOT DISTINCT FROM %s
           ORDER BY (status = 'active') DESC, created_at DESC LIMIT 1""",
        [grantee_id, patient_id, purpose, resource and resource.type, resource and resource.id],
    ).fetchone()
    if row is None:
        return None
    return Consent(
        id=row["id"], patient_id=row["patient_id"], grantee_id=row["grantee_id"], purpose=row["purpose"],
        status=row["status"], allowed_categories=frozenset(row["allowed_categories"]),
        expires_at=row["expires_at"], max_window_ends_at=row["max_window_ends_at"],
        resource_type=row["resource_type"], resource_id=row["resource_id"],
    )


def get(conn, consent_id):
    """One consent row, or None."""
    return conn.cursor(row_factory=dict_row).execute("SELECT * FROM consents WHERE id = %s", [consent_id]).fetchone()


def list_for_patient(conn, patient_id):
    """Every consent the patient has been asked for or given, newest first (Consent Center)."""
    return conn.cursor(row_factory=dict_row).execute(
        "SELECT * FROM consents WHERE patient_id = %s ORDER BY created_at DESC, id", [patient_id]).fetchall()
