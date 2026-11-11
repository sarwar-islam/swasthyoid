from datetime import timedelta
from types import SimpleNamespace
from uuid import uuid4

import psycopg
import pytest

from swasthyoid.core import audit
from swasthyoid.core import consent_authz as c1

CATS = frozenset({"timeline"})


def now(conn):
    return conn.execute("SELECT clock_timestamp()").fetchone()[0]


def new(conn, **over):
    fields = dict(
        patient_id=uuid4(), grantee_id=uuid4(), grantee_role="doctor", purpose="TIMELINE",
        allowed_categories={"timeline", "documents"}, consent_version=1, policy_version="PLACEHOLDER",
    )
    fields.update(over)
    fields.setdefault("actor_id", fields["grantee_id"])
    return c1.create(conn, **fields)


def active(conn, **over):
    row = new(conn, **over)
    return c1.activate(conn, row["id"], method="OTP", expires_at=now(conn) + timedelta(hours=1),
                       actor_id=row["patient_id"])


def decide(conn, row, resource=None):
    """What the next request by the grantee gets: load the consent, then decide."""
    consent = c1.find(conn, grantee_id=row["grantee_id"], patient_id=row["patient_id"],
                      purpose=row["purpose"], resource=resource)
    user = SimpleNamespace(id=row["grantee_id"], is_verified=True, is_active=True)
    patient = SimpleNamespace(id=row["patient_id"])
    return c1.authorize_access(c1.AccessRequest(row["purpose"], CATS, resource), user, patient, consent, now(conn))


def status(conn, consent_id):
    return conn.execute("SELECT status FROM consents WHERE id = %s", [consent_id]).fetchone()[0]


def actions(conn, table, consent_id):
    return [r[0] for r in conn.execute(
        f"SELECT action FROM {table} WHERE consent_id = %s ORDER BY {'seq' if table == 'audit_logs' else 'at'}",
        [consent_id])]


def test_pending_consent_grants_nothing(conn):
    row = new(conn)
    assert row["status"] == "pending"
    assert decide(conn, row).reason == "not_active"


def test_activate_then_revoke_blocks_the_next_request(conn):
    row = active(conn)
    assert (row["status"], row["method"]) == ("active", "OTP")
    assert decide(conn, row).allowed and decide(conn, row).consent_id == row["id"]

    revoked = c1.revoke(conn, row["id"], actor_id=row["patient_id"])
    assert revoked["revoked_by"] == row["patient_id"] and revoked["revoked_at"] is not None
    assert decide(conn, row).reason == "not_active"

    assert actions(conn, "consent_events", row["id"]) == ["create", "activate", "revoke"]
    assert actions(conn, "audit_logs", row["id"]) == ["consent.create", "consent.activate", "consent.revoke"]
    assert audit.verify_stored(conn) is None


def test_no_consent_means_consent_required(conn):
    stranger = {"grantee_id": uuid4(), "patient_id": uuid4(), "purpose": "TIMELINE"}
    assert decide(conn, stranger).reason == "consent_required"


def test_only_the_patient_can_revoke(conn):
    row = active(conn)
    for actor in (row["grantee_id"], uuid4(), None):
        with pytest.raises(PermissionError):
            c1.revoke(conn, row["id"], actor_id=actor)
    assert status(conn, row["id"]) == "active"
    assert actions(conn, "consent_events", row["id"]) == ["create", "activate"]


def test_illegal_changes_are_rejected(conn):
    row = new(conn)
    patient = row["patient_id"]
    with pytest.raises(ValueError):  # pending cannot be revoked
        c1.revoke(conn, row["id"], actor_id=patient)
    for bad_expiry in (None, now(conn) - timedelta(seconds=1)):
        with pytest.raises(ValueError, match="future"):
            c1.activate(conn, row["id"], method="OTP", expires_at=bad_expiry, actor_id=patient)
    assert status(conn, row["id"]) == "pending"

    c1.activate(conn, row["id"], method="OTP", expires_at=now(conn) + timedelta(hours=1), actor_id=patient)
    with pytest.raises(ValueError):  # already active
        c1.activate(conn, row["id"], method="OTP", expires_at=now(conn) + timedelta(hours=1), actor_id=patient)
    c1.revoke(conn, row["id"], actor_id=patient)
    with pytest.raises(ValueError):  # revoked is final
        c1.revoke(conn, row["id"], actor_id=patient)
    with pytest.raises(LookupError):
        c1.revoke(conn, uuid4(), actor_id=patient)


@pytest.mark.parametrize("bad", [
    {"purpose": "MARKETING"},
    {"allowed_categories": set()},
    {"grantee_role": ""},
    {"resource_type": "appointment"},  # binding needs both type and id
    {"consent_version": None},
])
def test_invalid_consent_is_rejected(conn, bad):
    with pytest.raises(psycopg.Error):
        new(conn, **bad)
    conn.rollback()
    assert conn.execute("SELECT count(*) FROM consents").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM audit_logs").fetchone()[0] == 0


def test_credential_suspension_and_restore(conn):
    doctor, admin = uuid4(), uuid4()
    a = active(conn, grantee_id=doctor)
    b = active(conn, grantee_id=doctor)
    waiting = new(conn, grantee_id=doctor)
    other = active(conn)

    assert c1.suspend_grantee(conn, doctor, actor_id=admin) == 2
    assert [status(conn, r["id"]) for r in (a, b, waiting, other)] == ["suspended", "suspended", "pending", "active"]
    assert decide(conn, a).reason == "not_active"
    assert decide(conn, other).allowed

    c1.revoke(conn, b["id"], actor_id=b["patient_id"])  # patient can still revoke while suspended
    assert c1.restore_grantee(conn, doctor, actor_id=admin) == 1
    assert [status(conn, r["id"]) for r in (a, b)] == ["active", "revoked"]
    assert decide(conn, a).allowed
    assert actions(conn, "audit_logs", a["id"])[-2:] == ["consent.suspend", "consent.restore"]


def test_expire_due(conn):
    due, fresh = active(conn), active(conn)
    window = active(conn)
    conn.execute("UPDATE consents SET expires_at = clock_timestamp() - interval '1 minute' WHERE id = %s", [due["id"]])
    conn.execute("UPDATE consents SET max_window_ends_at = clock_timestamp() - interval '1 minute' WHERE id = %s",
                 [window["id"]])
    assert decide(conn, due).reason == "expired"  # denied by time even before the sweep runs

    assert c1.expire_due(conn) == 2
    assert [status(conn, r["id"]) for r in (due, window, fresh)] == ["expired", "expired", "active"]
    assert actions(conn, "audit_logs", due["id"])[-1] == "consent.expire"
    assert c1.expire_due(conn) == 0


def test_change_fails_if_audit_write_fails(conn, monkeypatch):
    row = active(conn)
    conn.commit()

    def broken(*args, **kwargs):
        raise RuntimeError("audit store down")

    monkeypatch.setattr(audit, "append", broken)
    with pytest.raises(RuntimeError):
        c1.revoke(conn, row["id"], actor_id=row["patient_id"])
    with pytest.raises(RuntimeError):
        new(conn)
    assert status(conn, row["id"]) == "active"
    assert actions(conn, "consent_events", row["id"]) == ["create", "activate"]
    assert conn.execute("SELECT count(*) FROM consents").fetchone()[0] == 1


def test_find_matches_the_resource_binding_and_prefers_active(conn):
    doctor, patient, appt = uuid4(), uuid4(), uuid4()
    old = active(conn, grantee_id=doctor, patient_id=patient)
    c1.revoke(conn, old["id"], actor_id=patient)
    assert c1.find(conn, grantee_id=doctor, patient_id=patient, purpose="TIMELINE").status == "revoked"
    current = active(conn, grantee_id=doctor, patient_id=patient)
    new(conn, grantee_id=doctor, patient_id=patient)  # a newer pending request must not hide the active one
    assert c1.find(conn, grantee_id=doctor, patient_id=patient, purpose="TIMELINE").id == current["id"]

    bound = active(conn, grantee_id=doctor, patient_id=patient, purpose="APPOINTMENT",
                   resource_type="appointment", resource_id=appt)
    live = c1.Resource("appointment", appt, live=True)
    assert decide(conn, bound, live).consent_id == bound["id"]
    assert decide(conn, bound, c1.Resource("appointment", appt)).reason == "binding_invalid"  # not checked in
    assert decide(conn, bound, c1.Resource("appointment", uuid4(), live=True)).reason == "consent_required"
    assert decide(conn, bound).reason == "consent_required"  # no resource named


@pytest.mark.parametrize("sql", ["UPDATE consent_events SET action = 'x'", "DELETE FROM consent_events",
                                 "TRUNCATE consent_events"])
def test_consent_events_are_append_only(conn, sql):
    new(conn)
    conn.commit()
    with pytest.raises(psycopg.Error, match="append-only"):
        conn.execute(sql)
