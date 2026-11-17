"""M5 summary: LLM text when an adapter is configured and its output passes the validator, else the template (FRD 8.4).

Raw store reads: the route has passed RBAC -> C1 -> C2. `fallback_reason` says, by code only, why an LLM summary was not
returned: adapter_refused codes, `provider_error`, `invalid_output`, `validation_failed`; None when no adapter is set.
"""
import logging
from datetime import datetime, timezone

from swasthyoid.summary import adapters, build, validate

log = logging.getLogger(__name__)


def _request(events):
    return {"interface_version": adapters.INTERFACE_VERSION, "rules": list(adapters.PROMPT_RULES),
            "sections": [s for s in build.SECTION_IDS if s != "diagnoses"],
            "events": [{"event_id": str(e["id"]), "event_type": e["event_type"], "date": e["event_date"].isoformat(),
                        "payload": e["payload"]} for e in events]}


def _llm_summary(response):
    """The response in the summary's own shape, sections in the fixed order. Raises ValueError when malformed."""
    if not (isinstance(response, dict) and isinstance(response.get("model_id"), str) and response["model_id"].strip()
            and isinstance(response.get("sections"), list)):
        raise ValueError("malformed")
    given = {s.get("id"): s for s in response["sections"] if isinstance(s, dict)}
    if len(given) != len(response["sections"]) or not set(given) <= set(build.SECTION_IDS):
        raise ValueError("unknown or repeated section")
    return {"sections": [{"id": sid, "note": "not_recorded" if sid == "diagnoses" else None,
                          "sentences": (given.get(sid) or {}).get("sentences", []), "truncated": 0}
                         for sid in build.SECTION_IDS]}


def summarize(conn, patient_id, *, today, catalog=None):
    events = build.permitted_events(conn, patient_id)
    out = build.template(events, today)
    out.update(generated_at=datetime.now(timezone.utc).isoformat(), model_id=None, fallback_reason=None)
    try:
        adapter = adapters.resolve("llm")
    except adapters.AdapterRefused as e:
        out["fallback_reason"] = e.args[0]
        return out
    if adapter is None:
        return out
    verified = [e for e in events if e["verification_status"] == "document_verified"]  # readings stay template lines
    try:
        response = adapter.summarize(_request(verified))
    except Exception as e:  # any provider failure: the template, by code only (no text in logs, FRD 8.1 rule 7)
        log.warning("summary llm adapter failed: %s", type(e).__name__)
        out["fallback_reason"] = "provider_error"
        return out
    try:
        llm = _llm_summary(response)
    except ValueError:
        out["fallback_reason"] = "invalid_output"
        return out
    by_id = {str(e["id"]): e for e in verified}
    if validate.validate(llm, by_id, validate.known_names(events, catalog)):
        out["fallback_reason"] = "validation_failed"
        return out
    out.update(mode="llm", sections=llm["sections"], model_id=response["model_id"])
    return out
