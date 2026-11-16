"""Authorization matrix: purpose x consent state, plus one case per deny reason.

The role dimension is RBAC and is tested with the gateway (P1 slice 7).
"""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from swasthyoid.core.consent_authz import (
    PURPOSES,
    TRANSITIONS,
    AccessRequest,
    Consent,
    authorize_access,
    transition,
)

NOW = datetime(2026, 12, 1, 12, 0, tzinfo=timezone.utc)
DOCTOR = SimpleNamespace(id="user-1", is_verified=True, is_active=True)
PATIENT = SimpleNamespace(id="patient-1")
CATS = frozenset({"timeline"})

# Purposes a consent can grant today (EMERGENCY is refused until M10 is enabled, see test_deny_reasons).
GRANTABLE = sorted(PURPOSES - {"EMERGENCY"})


def make(purpose, status="active"):
    consent = Consent(
        id="consent-1",
        patient_id=PATIENT.id,
        grantee_id=DOCTOR.id,
        purpose=purpose,
        status=status,
        allowed_categories=frozenset({"timeline", "documents"}),
        expires_at=NOW + timedelta(hours=1),
    )
    return AccessRequest(purpose, CATS), consent


def test_v4_purposes_only():
    # M9, M11 and M12 are removed (FRD v4): their purposes are unknown and refused
    assert PURPOSES == {"TIMELINE", "EMERGENCY", "CLOUD_AI", "CAREGIVER"}
    for gone in ("APPOINTMENT", "REFERRAL", "DISPENSING"):
        req, consent = make("TIMELINE")
        assert decide(req=replace(req, purpose=gone), consent=replace(consent, purpose=gone)).reason == "unknown_purpose"


@pytest.mark.parametrize("purpose", GRANTABLE)
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
        "purpose_mismatch": [decide(req=replace(req, purpose="CLOUD_AI"))],
        "expired": [
            decide(now=NOW + timedelta(hours=2)),
            decide(consent=replace(consent, expires_at=None)),
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
        ("pending", "active"), ("pending", "expired"), ("pending", "declined"),
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
