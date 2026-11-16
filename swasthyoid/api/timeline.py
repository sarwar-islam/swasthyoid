"""M4 timeline (B4a; FRD M4, section 7: GET /patients/{id}/timeline?from&to&type).

The patient; a doctor whose consent covers `timeline`; a caregiver holding `view_timeline`. Never a verifier (FRD section 2).
Every non-patient read goes RBAC -> C1 -> C2 through patient_read before any event is read.
"""
from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from swasthyoid.api.deps import Actor, get_conn, patient_read
from swasthyoid.core import events_provenance

router = APIRouter()
EventType = Literal["visit", "diagnosis", "medication", "lab_result", "allergy", "follow_up", "prescription", "vital_reading"]


@router.get("/patients/{patient_id}/timeline")
def timeline(patient_id: UUID, date_from: date | None = Query(None, alias="from"), date_to: date | None = Query(None, alias="to"),
             type: EventType | None = None, conn=Depends(get_conn),
             a: Actor = Depends(patient_read("TIMELINE", "timeline", caregiver="view_timeline"))):
    rows = events_provenance.timeline(conn, patient_id, date_from=date_from, date_to=date_to, event_type=type)
    return [{"event_id": r["id"], "event_type": r["event_type"], "date": r["event_date"], "date_precision": r["date_precision"],
             "verification_status": r["verification_status"], "source_document_id": r["source_document_id"],
             "recorded_at": r["recorded_at"], "version": r["version"], "supersedes": r["supersedes"], "payload": r["payload"]}
            for r in rows]
