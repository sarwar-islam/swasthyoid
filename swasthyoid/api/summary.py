"""M5 summary and search for the treating doctor (P3; FRD M5, section 7; owner decision D1 and correction 3, 2026-11-17).

GET /patients/{id}/summary and GET /patients/{id}/search?q=: a verified doctor under a TIMELINE consent covering
`timeline`, RBAC -> C1 -> C2 before any event is read (FRD section 7 names only the doctor). Source document links are
returned only when the same consent also covers `documents` (a summary cites events, never documents); the audit
entry never holds the query text.
"""
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request

from swasthyoid.api.deps import Actor, ApiError, authorize_patient_access, get_conn, require
from swasthyoid.core import consent_authz
from swasthyoid.summary import search as event_search
from swasthyoid.summary import service

router = APIRouter()
doctor = require("doctor")


def _documents_covered(conn, a, patient_id):
    return consent_authz.covers(conn, user=a, patient_id=patient_id, purpose="TIMELINE", category="documents")


@router.get("/patients/{patient_id}/summary")
def summary(patient_id: UUID, request: Request, conn=Depends(get_conn), a: Actor = Depends(doctor)):
    authorize_patient_access(request, conn, a, patient_id, "TIMELINE", ("timeline",))
    return service.summarize(conn, patient_id, today=conn.execute("SELECT current_date").fetchone()[0])


@router.get("/patients/{patient_id}/search")
def search(patient_id: UUID, request: Request, q: str = Query(""), conn=Depends(get_conn), a: Actor = Depends(doctor)):
    authorize_patient_access(request, conn, a, patient_id, "TIMELINE", ("timeline",))
    try:
        return event_search.search(conn, patient_id, q, with_documents=_documents_covered(conn, a, patient_id))
    except event_search.BadQuery as e:
        raise ApiError(422, e.args[0], "Type a word to search for (at most 200 characters).")
