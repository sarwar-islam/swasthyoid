from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

import psycopg
import pytest

from swasthyoid.core import events_provenance as events

# FRD 4.4 mandatory fields, with the ERD column names.
MANDATORY = {
    "id", "event_type", "patient_id", "event_date", "date_precision", "actor_id", "actor_role",
    "source_type", "source_document_id", "recorded_at", "verified_by", "verified_at",
    "verification_status", "related_record_id", "version", "supersedes", "payload",
}


def base(**over):
    # Synthetic placeholder payload, not clinical content.
    fields = dict(
        patient_id=uuid4(), event_type="vital_reading", event_date=date(2026, 12, 1), date_precision="day",
        actor_id=uuid4(), actor_role="patient", source_type="synthetic",
        verification_status="patient_reported", payload={"synthetic": True},
    )
    return {**fields, **over}


def count(conn):
    return conn.execute("SELECT count(*) FROM events").fetchone()[0]


def test_append_stores_all_mandatory_fields(conn):
    row = events.append(conn, **base())
    assert set(row) == MANDATORY
    assert row["version"] == 1 and row["supersedes"] is None
    assert row["payload"] == {"synthetic": True}
    assert abs(row["recorded_at"] - datetime.now(timezone.utc)) < timedelta(minutes=1)


@pytest.mark.parametrize("server_set", ["id", "recorded_at", "version"])
def test_caller_cannot_set_server_fields(conn, server_set):
    with pytest.raises(TypeError):
        events.append(conn, **base(), **{server_set: 1})


@pytest.mark.parametrize("bad", [
    {"event_type": "horoscope"},
    {"verification_status": "verified"},
    {"date_precision": "week"},
    {"actor_role": ""},
    {"source_type": ""},
    {"event_date": None},
    {"actor_id": None},
    {"payload": None},
    {"payload": ["not", "an", "object"]},
    # paper data cannot be marked verified without a verifier, a time and its source document
    {"verification_status": "document_verified"},
    {"verification_status": "document_verified", "verified_by": uuid4(), "verified_at": datetime.now(timezone.utc)},
    {"verification_status": "document_verified", "verified_by": uuid4(), "source_document_id": uuid4()},
])
def test_invalid_event_is_rejected_and_nothing_written(conn, bad):
    with pytest.raises(psycopg.Error):
        events.append(conn, **base(**bad))
    conn.rollback()
    assert count(conn) == 0


def test_document_verified_with_full_provenance_is_accepted(conn):
    row = events.append(conn, **base(
        event_type="prescription", actor_role="verifier", verification_status="document_verified",
        verified_by=uuid4(), verified_at=datetime.now(timezone.utc), source_document_id=uuid4(),
    ))
    assert row["verification_status"] == "document_verified"


def test_correction_supersedes_and_old_event_is_kept(conn):
    patient = uuid4()
    v1 = events.append(conn, **base(patient_id=patient, payload={"synthetic": True, "n": 1}))
    v2 = events.append(conn, **base(patient_id=patient, payload={"synthetic": True, "n": 2}, supersedes=v1["id"]))
    v3 = events.append(conn, **base(patient_id=patient, payload={"synthetic": True, "n": 3}, supersedes=v2["id"]))

    assert (v2["version"], v2["supersedes"]) == (2, v1["id"])
    assert v3["version"] == 3
    assert count(conn) == 3  # nothing overwritten
    kept = conn.execute("SELECT payload FROM events WHERE id = %s", [v1["id"]]).fetchone()[0]
    assert kept == {"synthetic": True, "n": 1}
    assert [e["id"] for e in events.current_events(conn, patient)] == [v3["id"]]


def test_supersede_rules(conn):
    patient = uuid4()
    v1 = events.append(conn, **base(patient_id=patient))
    events.append(conn, **base(patient_id=patient, supersedes=v1["id"]))

    with pytest.raises(psycopg.errors.UniqueViolation):  # an event has at most one successor
        events.append(conn, **base(patient_id=patient, supersedes=v1["id"]))
    conn.rollback()
    with pytest.raises(ValueError, match="not found"):
        events.append(conn, **base(patient_id=patient, supersedes=uuid4()))
    with pytest.raises(ValueError, match="same patient"):
        events.append(conn, **base(supersedes=v1["id"]))  # a different patient


def test_current_events_are_per_patient_and_ordered(conn):
    a, b = uuid4(), uuid4()
    late = events.append(conn, **base(patient_id=a, event_date=date(2026, 12, 5)))
    early = events.append(conn, **base(patient_id=a, event_date=date(2026, 12, 1)))
    events.append(conn, **base(patient_id=b))

    assert [e["id"] for e in events.current_events(conn, a)] == [early["id"], late["id"]]
    assert len(events.current_events(conn, b)) == 1
    assert events.current_events(conn, uuid4()) == []


@pytest.mark.parametrize("sql", [
    "UPDATE events SET payload = '{}'",
    "DELETE FROM events",
    "TRUNCATE events",
])
def test_append_only(conn, sql):
    events.append(conn, **base())
    conn.commit()
    with pytest.raises(psycopg.Error, match="append-only"):
        conn.execute(sql)
    conn.rollback()
    assert count(conn) == 1
