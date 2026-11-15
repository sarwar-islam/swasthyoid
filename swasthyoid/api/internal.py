"""Operator endpoints (D13, owner decision 2026-11-15). Admin only: the caller must be a verified admin (RBAC; a refusal is
audited by the gateway chain like any other). Aggregate counts only, no document, patient or text, so there is no patient
consent to check.

shortcut: an allowed read is not audited (a metrics scraper would flood audit_logs); add it if the owner wants scrapes recorded.
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Response

from swasthyoid.api.deps import Actor, get_conn, require
from swasthyoid.workers import monitoring

router = APIRouter()


@router.get("/internal/metrics")
def metrics(response: Response, conn=Depends(get_conn), a: Actor = Depends(require("admin"))):
    """Documents per status and the worker counts (monitoring.METRICS), read now. `adapter_unavailable_cycles` is known only
    inside a running worker and is not here."""
    response.headers["Cache-Control"] = "no-store"
    return {"at": datetime.now(timezone.utc).isoformat(), "documents": monitoring.by_status(conn),
            "worker": monitoring.snapshot(conn)}
