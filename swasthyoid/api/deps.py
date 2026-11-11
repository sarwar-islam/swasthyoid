"""Shared API pieces: database connection, error format, who is calling, role check (RBAC).

Order for every protected request: token -> account still valid -> role. The C1
consent check and C2 audit for patient-data reads are added with the gateway chain.
"""
from dataclasses import dataclass
from uuid import UUID

from fastapi import Depends, Request

from swasthyoid import db
from swasthyoid.core import audit, notification
from swasthyoid.identity import sessions


class ApiError(Exception):
    """Rendered as { "code", "message", "details" } (FRD section 7)."""

    def __init__(self, status, code, message="", **details):
        self.status, self.code, self.message, self.details = status, code, message, details


def get_conn():
    # autocommit: each core/identity call commits its own transaction, so a deny that
    # is audited stays audited even though the request then ends in an error.
    with db.connect(autocommit=True) as conn:
        yield conn


def get_code_sender():
    return notification.send_code_dev  # PLACEHOLDER until an SMS gateway is chosen


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
        reason = None
        if a.role not in roles:
            reason = "role_not_allowed"
        elif verified and not a.is_verified:
            reason = "user_not_verified"
        if reason:
            route = request.scope.get("route")
            audit.append(conn, action="rbac.deny", result="deny",
                         reason=f"{reason}: {request.method} {route.path if route else request.url.path}",
                         actor_id=a.id, actor_role=a.role, device_id=a.device_id, **client_info(request))
            raise ApiError(403, reason, "You are not allowed to do this.")
        return a

    return check
