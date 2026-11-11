"""C1 — consent and authorization, pure decision logic (FRD section 4.1).

No storage here. The caller loads the consent, calls authorize_access, and MUST
write the C2 audit entry for every decision, allow or deny.
"""
from dataclasses import dataclass

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
