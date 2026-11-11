"""Authorization matrix: purpose x consent state, plus one case per deny reason.

The role dimension is RBAC and is tested with the gateway (P1 slice 7).
"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from swasthyoid.core.consent_authz import (
    TRANSITIONS,
    AccessRequest,
    Consent,
    Resource,
    authorize_access,
    transition,
)

NOW = datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc)
DOCTOR = SimpleNamespace(id="user-1", is_verified=True, is_active=True)
PATIENT = SimpleNamespace(id="patient-1")
CATS = frozenset({"timeline"})

# purpose -> resource type the consent is bound to (None = bound to doctor + patient only)
BINDINGS = {"TIMELINE": None, "APPOINTMENT": "appointment", "REFERRAL": "referral", "DISPENSING": "prescription"}


def make(purpose, status="active"):
    rtype = BINDINGS[purpose]
    consent = Consent(
        id="consent-1",
        patient_id=PATIENT.id,
        grantee_id=DOCTOR.id,
        purpose=purpose,
        status=status,
        allowed_categories=frozenset({"timeline", "documents"}),
        expires_at=NOW + timedelta(hours=1),
        resource_type=rtype,
        resource_id="res-1" if rtype else None,
    )
    resource = Resource(rtype, "res-1", live=True) if rtype else None
    return AccessRequest(purpose, CATS, resource), consent


@pytest.mark.parametrize("purpose", BINDINGS)
@pytest.mark.parametrize("status", TRANSITIONS)
def test_purpose_x_state(purpose, status):
    req, consent = make(purpose, status)
    d = authorize_access(req, DOCTOR, PATIENT, consent, NOW)
    assert d.allowed == (status == "active")
    if status == "active":
        assert d.consent_id == "consent-1"
    else:
        assert d.reason == "not_active" and d.consent_id is None


def decide(req=None, user=DOCTOR, patient=PATIENT, consent="default", now=NOW, purpose="TIMELINE"):
    default_req, default_consent = make(purpose)
    return authorize_access(
        req or default_req, user, patient, default_consent if consent == "default" else consent, now
    )


def test_deny_reasons():
    req, consent = make("TIMELINE")
    areq, aconsent = make("APPOINTMENT")
    cases = {
        "user_not_verified": [
            decide(user=SimpleNamespace(id="user-1", is_verified=False, is_active=True)),
            decide(user=SimpleNamespace(id="user-1", is_verified=True, is_active=False)),
            decide(user=SimpleNamespace(id="user-1", is_verified="yes", is_active=True)),
        ],
        "unknown_purpose": [decide(req=replace(req, purpose="MARKETING"))],
        "emergency_not_enabled": [decide(req=replace(req, purpose="EMERGENCY"))],
        "consent_required": [decide(consent=None)],
        "patient_mismatch": [decide(patient=SimpleNamespace(id="patient-2"))],
        "grantee_mismatch": [decide(user=SimpleNamespace(id="user-2", is_verified=True, is_active=True))],
        "purpose_mismatch": [decide(req=replace(req, purpose="REFERRAL"))],
        "expired": [
            decide(now=NOW + timedelta(hours=2)),
            decide(consent=replace(consent, expires_at=None)),
            decide(consent=replace(consent, max_window_ends_at=NOW - timedelta(minutes=1))),
        ],
        "binding_invalid": [
            decide(req=replace(req, resource=Resource("appointment", "res-1", live=True))),
            decide(req=replace(areq, resource=None), consent=aconsent),
            decide(req=replace(areq, resource=Resource("appointment", "res-2", live=True)), consent=aconsent),
            decide(req=replace(areq, resource=Resource("referral", "res-1", live=True)), consent=aconsent),
            decide(req=replace(areq, resource=Resource("appointment", "res-1")), consent=aconsent),
        ],
        "category_not_allowed": [
            decide(req=replace(req, data_categories=frozenset({"timeline", "safety"}))),
            decide(req=replace(req, data_categories=frozenset())),
            decide(req=replace(req, data_categories=None)),
        ],
        "authorization_error": [  # malformed input fails closed
            decide(user=object()),
            decide(now="not a datetime"),
            decide(req=replace(req, data_categories=["timeline"])),
        ],
    }
    for reason, decisions in cases.items():
        for d in decisions:
            assert (d.allowed, d.reason, d.consent_id) == (False, reason, None)


def test_boundary_at_expiry_is_still_allowed():
    _, consent = make("TIMELINE")
    assert decide(now=consent.expires_at).allowed
    assert not decide(now=consent.expires_at + timedelta(microseconds=1)).allowed


def test_state_machine():
    allowed = {(s, t) for s, targets in TRANSITIONS.items() for t in targets}
    assert allowed == {
        ("pending", "active"), ("pending", "expired"),
        ("active", "expired"), ("active", "revoked"), ("active", "suspended"),
        ("suspended", "active"), ("suspended", "revoked"),
    }
    for s in TRANSITIONS:
        for t in TRANSITIONS:
            if (s, t) in allowed:
                assert transition(s, t) == t
            else:
                with pytest.raises(ValueError):
                    transition(s, t)
    with pytest.raises(ValueError):
        transition("bogus", "active")
