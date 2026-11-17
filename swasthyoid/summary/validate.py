"""M5 provenance validator (P3; FRD M5 and 8.4; owner correction 2, 2026-11-17). Deterministic, no model.

A summary passes only if every clinical fact it states is traceable to the events it cites:
1. sections are the fixed ones; the diagnoses section states nothing (D2: diagnoses are not recorded);
2. every sentence cites at least one event, every cited event is one the caller may see, and each cited event backs a fact;
3. every fact (drug, dose, unit, date, duration, result, name) names a cited event and equals, as written, that event's
   field (`date` is the event's date);
4. once the stated facts are taken out of the text, no digit is left (no unbacked number, dose, date or duration), and
   no drug, allergen, test, facility or prescriber name known from the permitted events or the catalog is left (no
   unbacked or misattributed entity).
What it cannot see: a wording that infers a status without naming an entity or a number (for example calling a recorded
medication "active"). The prompt rules forbid it and the pre-pilot clinician reading of a sample (FRD 8.5) checks it.
"""
import re

from swasthyoid.capture.drugmatch import normalize
from swasthyoid.summary.build import SECTION_IDS

NAME_FIELDS = ("name_as_written", "allergy_text", "test_name", "facility_name", "prescriber_name")
_DIGIT = re.compile(r"[0-9০-৯]")


def known_names(events, catalog=None):
    """Entity names a sentence may only state as a cited fact: from the permitted events, and the catalog if given."""
    names = {normalize(e["payload"].get(f)) for e in events for f in NAME_FIELDS if isinstance(e["payload"].get(f), str)}
    if catalog is not None:
        for entry in catalog.entries:
            names.update(normalize(n) for n in (entry["generic"], *entry["brands"]) if n)
    return {n for n in names if n}


def _fact_ok(fact, cited, events):
    if not isinstance(fact, dict) or fact.get("event_id") not in cited or not isinstance(fact.get("value"), str):
        return False
    event = events[fact["event_id"]]
    if fact.get("field") == "date":
        return fact["value"] == event["event_date"].isoformat()
    held = event["payload"].get(fact.get("field"))
    return isinstance(held, (str, int, float)) and not isinstance(held, bool) and normalize(str(held)) == normalize(fact["value"])


def _residue(text, facts):
    rest = normalize(text)
    for value in sorted({normalize(f["value"]) for f in facts}, key=len, reverse=True):
        rest = rest.replace(value, " ")
    return f" {' '.join(rest.split())} "


def check_sentence(s, events, names):
    """Problem codes for one sentence; [] when it passes. `events`: id (str) -> permitted event row."""
    if not (isinstance(s, dict) and isinstance(s.get("text"), str) and isinstance(s.get("citations"), list)
            and isinstance(s.get("facts"), list)):
        return ["malformed"]
    cited = {str(c) for c in s["citations"]}
    if not cited:
        return ["no_citation"]
    if not cited <= set(events):
        return ["citation_not_permitted"]
    if not s["facts"] or not all(_fact_ok(f, cited, events) for f in s["facts"]):
        return ["unsupported_fact"]
    problems = []
    if cited - {f["event_id"] for f in s["facts"]}:
        problems.append("citation_without_fact")
    rest = _residue(s["text"], s["facts"])
    if _DIGIT.search(rest):
        problems.append("unbacked_number")
    if any(f" {n} " in rest for n in names):
        problems.append("unbacked_entity")
    return problems


def validate(summary, events, names):
    """All problems in a summary's sections, as (section id, sentence index, code); [] means it passes."""
    problems = []
    sections = summary.get("sections") if isinstance(summary, dict) else None
    if not isinstance(sections, list):
        return [(None, None, "malformed")]
    seen = [s.get("id") if isinstance(s, dict) else None for s in sections]
    if sorted(map(str, seen)) != sorted(SECTION_IDS):
        problems.append((None, None, "sections_not_fixed"))
    for section in sections:
        if not isinstance(section, dict) or not isinstance(section.get("sentences"), list):
            problems.append((None, None, "malformed"))
            continue
        if section.get("id") == "diagnoses" and section["sentences"]:
            problems.append(("diagnoses", None, "diagnosis_stated"))
        for i, s in enumerate(section["sentences"]):
            problems += [(section.get("id"), i, code) for code in check_sentence(s, events, names)]
    for i, s in enumerate(summary.get("patient_reported") or []):
        problems += [("patient_reported", i, code) for code in check_sentence(s, events, names)]
    return problems
