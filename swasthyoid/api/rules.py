"""The M6 rule registry for the clinical reviewer (B5; FRD M6, section 7; owner decisions 2026-11-16).

GET /rules?type= (GAP, approved), POST /rules (FRD), POST /rules/{id}/approve (FRD, four-eyes), POST /rules/{id}/reject
{ reason } (GAP, approved). A verified clinical reviewer only; every other role is refused and the refusal audited.
"""
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool

from swasthyoid.api.deps import Actor, ApiError, get_conn, require
from swasthyoid.safety import registry

router = APIRouter()
reviewer = require("clinical_reviewer")
RuleType = Literal["ddi", "allergy", "duplicate", "drug_disease", "class_lookback", "vital_threshold", "red_flag",
                   "emergency_message"]
_CONFLICTS = {"draft_exists": "This rule already has a draft waiting for review.", "not_draft": "Only a draft can be reviewed.",
              "four_eyes": "A draft must be approved by a reviewer other than its author."}


async def _json(request):
    try:
        body = await request.json()
    except ValueError:
        return None
    return body if isinstance(body, dict) else None


def _call(fn):
    try:
        return fn()
    except registry.Invalid as e:
        raise ApiError(422, e.args[0], "Check the type, severity, definition and both explanations.")
    except registry.Conflict as e:
        raise ApiError(409, e.args[0], _CONFLICTS[e.args[0]])
    except LookupError:
        raise ApiError(404, "not_found", "No rule with this id.")


def _one(conn, version_id):
    return next(registry.view(r) for r in registry.listing(conn) if r["id"] == version_id)


@router.get("/rules")
def list_rules(type: RuleType | None = None, conn=Depends(get_conn), a: Actor = Depends(reviewer)):
    return [registry.view(r) for r in registry.listing(conn, type)]


@router.post("/rules", status_code=201)
async def draft_rule(request: Request, conn=Depends(get_conn), a: Actor = Depends(reviewer)):
    body = await _json(request)
    return await run_in_threadpool(lambda: _one(conn, _call(lambda: registry.draft(conn, body, author=a))["id"]))


@router.post("/rules/{version_id}/approve")
def approve_rule(version_id: UUID, conn=Depends(get_conn), a: Actor = Depends(reviewer)):
    _call(lambda: registry.approve(conn, version_id, reviewer=a))
    return _one(conn, version_id)


@router.post("/rules/{version_id}/reject")
async def reject_rule(version_id: UUID, request: Request, conn=Depends(get_conn), a: Actor = Depends(reviewer)):
    reason = (await _json(request) or {}).get("reason")

    def work():  # database calls off the event loop
        _call(lambda: registry.reject(conn, version_id, reviewer=a, reason=reason))
        return _one(conn, version_id)

    return await run_in_threadpool(work)
