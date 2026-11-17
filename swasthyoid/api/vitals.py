"""M13 home vitals routes (P6; FRD section 7; owner decision V5): the patient's own readings only.

POST /vitals, GET /vitals, POST /vitals/{reading_id}/correct. Patients only (caregivers act as their own patient account
here and reach nobody else's readings); doctors see readings through the timeline and summary under their consent (P3).
The reading id in the path and body is the id the patient's app made; another patient's id is simply not found.
"""
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse
from fastapi.encoders import jsonable_encoder

from swasthyoid.api.deps import Actor, ApiError, get_conn, require
from swasthyoid.vitals import readings

router = APIRouter()
patient_only = require("patient")
_TEXT = {"invalid_reading": "Check the value, unit, context and time.",
         "reason_required": "A correction needs a reason.",
         "reading_id_conflict": "This reading id was already used for a different reading.",
         "already_corrected": "This reading was already corrected. Correct the newest version."}


def _save(conn, a, body, of=None):
    try:
        view, created = readings.save(conn, a.id, body, actor=a, of=of)
    except readings.Invalid as e:
        raise ApiError(422, e.args[0], _TEXT[e.args[0]])
    except readings.NeedsConfirmation:
        raise ApiError(422, "confirmation_required", "This value looks unusual. Confirm it.")
    except readings.Conflict as e:
        raise ApiError(409, e.args[0], _TEXT[e.args[0]])
    except LookupError:
        raise ApiError(404, "not_found", "No reading with this id.")
    return JSONResponse(jsonable_encoder(view), status_code=201 if created else 200)


@router.post("/vitals", status_code=201)
def create(body: Any = Body(None), conn=Depends(get_conn), a: Actor = Depends(patient_only)):
    return _save(conn, a, body)


@router.post("/vitals/{reading_id}/correct", status_code=201)
def correct(reading_id: UUID, body: Any = Body(None), conn=Depends(get_conn), a: Actor = Depends(patient_only)):
    return _save(conn, a, body, of=reading_id)


@router.get("/vitals")
def list_vitals(conn=Depends(get_conn), a: Actor = Depends(patient_only)):
    return readings.listing(conn, a.id)
