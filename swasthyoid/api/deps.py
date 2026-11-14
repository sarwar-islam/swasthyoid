"""Shared API pieces: database connection, error format, who is calling, role check (RBAC).

Order for every protected request: token -> account still valid -> role (RBAC).
Reads of patient data by anyone but the patient then go through C1 (consent) and
C2 (audit): use patient_read() on those routes.
"""
import logging
import os
from dataclasses import dataclass, replace
from datetime import timedelta
from uuid import UUID

from fastapi import Depends, Request
from fastapi.encoders import jsonable_encoder
from psycopg.types.json import Jsonb

from swasthyoid import db, pii, runtime_mode
from swasthyoid.capture import extraction_crypto
from swasthyoid.core import audit, consent_authz, notification
from swasthyoid.identity import sessions

IDEMPOTENCY_TTL = timedelta(hours=24)  # engineering default, not an FRD value


class ApiError(Exception):
    """Rendered as { "code", "message", "details" } (FRD section 7)."""

    def __init__(self, status, code, message="", **details):
        self.status, self.code, self.message, self.details = status, code, message, details


def get_conn():
    # autocommit: each core/identity call commits its own transaction, so a deny that
    # is audited stays audited even though the request then ends in an error.
    with db.connect(autocommit=True) as conn:
        yield conn


def dev_codes_enabled():
    return os.environ.get("DEV_LOG_CODES", "0") == "1"


def check_config():
    """Refuse to start if codes would be logged anywhere but an explicit development setup, or
    if APP_ENV=test lacks its confirmation (runtime_mode)."""
    if dev_codes_enabled() and os.environ.get("APP_ENV") != "development":
        raise RuntimeError("DEV_LOG_CODES=1 is only allowed with APP_ENV=development")
    runtime_mode.check_test_mode_config()
    try:  # extracted text is stored sealed (D2): refuse to start without the key
        extraction_crypto.check_key()
    except extraction_crypto.KeyError_ as problem:
        raise RuntimeError(f"EXTRACTION_KEY is {problem.args[0]}") from None
    if runtime_mode.confirm_without_test_env():
        # owner decision 4A §2.4 pending; option (ii), a warning, implemented as recommended
        logging.getLogger(__name__).warning("%s is set but APP_ENV is not test: test mode is off",
                                            runtime_mode.CONFIRM)


def no_code_delivery(*args, **kwargs):
    raise ApiError(503, "code_delivery_unavailable", "No SMS gateway is configured.")


def get_code_sender():
    """send(phone, code, context=None). PLACEHOLDER: no SMS gateway is chosen, so by default
    codes cannot be delivered. Logging them is an explicit local-development opt-in."""
    if dev_codes_enabled() and os.environ.get("APP_ENV") == "development":
        return notification.send_code_dev
    return no_code_delivery


def person_labels(conn, ids):
    """Name and phone ending of person accounts, for showing a patient who is asking."""
    rows = conn.execute("SELECT id, name_enc, phone_enc FROM patients WHERE id = ANY(%s)", [list(ids)]).fetchall()
    return {r[0]: {"name": pii.decrypt(r[1]), "phone_tail": pii.decrypt(r[2])[-3:]} for r in rows}


def client_info(request: Request):
    return {"ip": request.client.host if request.client else None, "user_agent": request.headers.get("user-agent")}


@dataclass(frozen=True)
class Actor:
    id: UUID
    role: str
    device_id: str
    is_verified: bool
    is_active: bool = True


def actor(request: Request, conn=Depends(get_conn)) -> Actor:
    """The caller, from a valid access token and an account that still exists and is not suspended."""
    info = client_info(request)
    try:
        scheme, token = request.headers.get("authorization", "").split(" ", 1)
        if scheme.lower() != "bearer":
            raise ValueError("not a bearer token")
        claims = sessions.read_access_token(token)
        who, role = UUID(claims["sub"]), claims["role"]
    except Exception:
        audit.append(conn, action="auth.token_rejected", result="deny", reason="invalid_token", **info)
        raise ApiError(401, "unauthenticated", "A valid access token is required.")

    if role == "patient":
        status = "verified" if conn.execute("SELECT 1 FROM patients WHERE id = %s", [who]).fetchone() else None
    else:
        row = conn.execute("SELECT status FROM users WHERE id = %s AND role = %s", [who, role]).fetchone()
        status = row and row[0]
    if status not in ("pending", "verified"):
        audit.append(conn, action="auth.token_rejected", result="deny", reason="account_not_active",
                     actor_id=who, actor_role=role, device_id=claims["device_id"], **info)
        raise ApiError(401, "unauthenticated", "This account is not active.")
    return Actor(who, role, claims["device_id"], is_verified=status == "verified")


def require(*roles, verified=True):
    """RBAC: the caller must hold one of these roles and, unless verified=False, be verified."""

    def check(request: Request, a: Actor = Depends(actor), conn=Depends(get_conn)) -> Actor:
        _rbac(request, conn, a, roles, verified)
        return a

    return check


def _endpoint(request):
    route = request.scope.get("route")
    return f"{request.method} {route.path if route else request.url.path}"


def _rbac(request, conn, a, roles, verified=True, patient_id=None):
    reason = None
    if a.role not in roles:
        reason = "role_not_allowed"
    elif verified and not a.is_verified:
        reason = "user_not_verified"
    if reason:
        audit.append(conn, action="rbac.deny", result="deny", reason=f"{reason}: {_endpoint(request)}",
                     actor_id=a.id, actor_role=a.role, device_id=a.device_id, patient_id=patient_id,
                     **client_info(request))
        raise ApiError(403, reason, "You are not allowed to do this.")


def patient_read(purpose, *categories, roles=("doctor",), caregiver=None):
    """Gateway chain for routes that act on one patient's data, with a {patient_id} path parameter.

    A patient acting on their own data passes. Staff: RBAC -> C1 consent -> C2 audit.
    Another person passes only on a route that names a `caregiver` scope, and only with an
    active CAREGIVER consent holding that scope: C1 -> C2, no role involved.
    The audit entry is written before the handler runs; if C1 or C2 fails the request fails
    and the handler never runs (fail closed).
    """

    def check(patient_id: UUID, request: Request, a: Actor = Depends(actor), conn=Depends(get_conn)) -> Actor:
        return authorize_patient_access(request, conn, a, patient_id, purpose, categories, roles, caregiver)

    return check


def authorize_patient_access(request, conn, a, patient_id, purpose, categories, roles=("doctor",), caregiver=None):
    """The chain behind patient_read, for routes that learn the patient from a record
    (for example a document id) instead of the path."""
    if a.role == "patient" and a.id == patient_id:
        return a
    if a.role == "patient" and caregiver:
        user, want, scopes = replace(a, role="caregiver"), "CAREGIVER", (caregiver,)
    else:
        _rbac(request, conn, a, roles, patient_id=patient_id)
        user, want, scopes = a, purpose, categories
    decision = consent_authz.check_access(
        conn, user=user, patient_id=patient_id, purpose=want, categories=scopes,
        action=_endpoint(request), device_id=a.device_id, **client_info(request),
    )
    if not decision.allowed:
        raise ApiError(403, decision.reason, "The patient has not allowed this access.")
    return a


def idempotent(conn, request: Request, a: Actor, body, work):
    """Run work() once per Idempotency-Key and replay its result for a repeat (FRD 7).

    Scoped to the caller, method and path. A failed request stores nothing, so it can be
    retried. Without the header the work simply runs. Login endpoints do not use this:
    they have no caller yet and their responses carry tokens that must not be stored.
    """
    key = request.headers.get("idempotency-key")
    if key is None:
        return work()
    if not 0 < len(key) <= 255:
        raise ApiError(422, "invalid_idempotency_key", "Idempotency-Key must be 1 to 255 characters.")
    scope = [a.id, f"{request.method} {request.url.path}", key]
    where = "actor_id = %s AND endpoint = %s AND key = %s"
    # keyed: a plain hash of a body that holds a 6-digit code could be guessed offline
    # body: a pydantic model, None, or a string fingerprint (uploads)
    text = body if isinstance(body, str) else body.model_dump_json() if body is not None else ""
    digest = pii.secret_hash("idempotency:" + text)

    conn.execute(f"DELETE FROM idempotency_keys WHERE {where} AND expires_at <= clock_timestamp()", scope)
    claimed = conn.execute(
        "INSERT INTO idempotency_keys (actor_id, endpoint, key, request_hash, expires_at) "
        "VALUES (%s, %s, %s, %s, clock_timestamp() + %s) ON CONFLICT DO NOTHING RETURNING 1",
        [*scope, digest, IDEMPOTENCY_TTL],
    ).fetchone()
    if not claimed:
        seen = conn.execute(f"SELECT request_hash, response FROM idempotency_keys WHERE {where}", scope).fetchone()
        if seen is None or seen[1] is None:
            raise ApiError(409, "request_in_progress", "The first request with this key is still running.")
        if seen[0] != digest:
            raise ApiError(422, "idempotency_key_reused", "This key was used with a different request.")
        return seen[1]
    try:
        result = jsonable_encoder(work())
    except BaseException:
        conn.execute(f"DELETE FROM idempotency_keys WHERE {where}", scope)
        raise
    conn.execute(f"UPDATE idempotency_keys SET response = %s WHERE {where}", [Jsonb(result), *scope])
    return result
