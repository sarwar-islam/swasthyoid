"""M6 prescription safety engine (P3; FRD M6; owner decisions D2, D4, D5, 2026-11-17). Deterministic code, no model.

evaluate() is pure: the same rules, medications, allergies and catalog always give the same result, whatever their order.
Only approved rule versions are passed in (checks.py reads them); an engine rule that does not fit its shape blocks the
whole check (`rule_load_error`), and so does a missing catalog (`catalog_unavailable`): fail closed, never a silent pass.

Technical steps, all REVIEWER-PENDING (FRD Q7) and none of them clinical content:
- Ingredients of a medication: catalog names found in its name as written (drugmatch.match_row: exact normalised phrases,
  no similarity), then the catalog's generic name split on "+". A row with no catalog name, a name whose candidates have
  different generics or no generic, or a truncated match is `unrecognised` and takes part in no check; it is never passed.
- Compared against: every medication recorded on the patient's other verified documents. What counts as "active" is not
  decided (D3), so nothing recorded is left out (more alerts, never fewer).
- Allergy terms: a reviewer's term matches an allergy written as text when its words appear there in order.
- Not run, said explicitly: drug-disease (diagnoses are not recorded, D2) and every class-based check (no class data until
  FRD Q1, D4).
"""
from swasthyoid.capture import drugmatch
from swasthyoid.capture.drugmatch import normalize
from swasthyoid.safety import definitions

NOT_RUN = (
    {"check": "drug_disease", "reason": "diagnoses_not_recorded"},
    {"check": "allergy_class", "reason": "class_data_unavailable"},
    {"check": "duplicate_class", "reason": "class_data_unavailable"},
    {"check": "class_lookback", "reason": "class_data_unavailable"},
)
_EDGE = ",.;:()[]"


class Blocked(Exception):
    """The check cannot run safely. args[0]: rule_load_error or catalog_unavailable."""


def load_rules(rows):
    """Approved engine rule rows -> [(version id, rule type, severity, parsed definition)], sorted by version id."""
    out = []
    for r in rows:
        try:
            out.append((str(r["id"]), r["rule_type"], r["severity"], definitions.parse(r["rule_type"], r["severity"],
                                                                                        r["definition"])))
        except definitions.Invalid:
            raise Blocked("rule_load_error") from None
    return sorted(out, key=lambda r: r[0])


def ingredients(text, catalog):
    """(frozenset of normalised ingredient names, None) or (None, reason) for one medication name as written."""
    found = drugmatch.match_row(text, catalog)
    if not found["matches"]:
        return None, "not_in_catalog"
    if found["truncated"]:
        return None, "ambiguous"
    generics = set()
    for m in found["matches"]:
        names = {normalize(c["generic"]) if c["generic"] else "" for c in m["candidates"]}
        if len(names) != 1 or "" in names:
            return None, "ambiguous"
        generics |= names
    parts = frozenset(p.strip() for g in generics for p in g.split("+") if p.strip())
    return (parts, None) if parts else (None, "ambiguous")


def _words(text):
    return [w.strip(_EDGE) or w for w in normalize(text).split()]


def _mentions(text, term):
    words, want = _words(text), _words(term)
    return bool(want) and any(words[i:i + len(want)] == want for i in range(len(words) - len(want) + 1))


def evaluate(rules, new_meds, other_meds, allergies, catalog):
    """rules: from load_rules. new_meds: [(event id, name as written)] of the prescription just verified; other_meds: the
    same for the patient's other verified documents; allergies: [(event id, allergy as written)]. Returns
    {alerts: [{rule_version_id, rule_type, severity, evidence}], unrecognised: [{event_id, reason, scope}], not_run}."""
    if catalog is None:
        raise Blocked("catalog_unavailable")
    known, unrecognised = {}, []
    for scope, meds in (("prescription", new_meds), ("recorded", other_meds)):
        for eid, text in meds:
            parts, reason = ingredients(text, catalog)
            if parts is None:
                unrecognised.append({"event_id": str(eid), "reason": reason, "scope": scope})
            else:
                known[str(eid)] = parts
    new = [str(e) for e, _ in new_meds if str(e) in known]
    everyone = sorted(known)
    alerts = {}

    def fire(rule, evidence):
        key = (rule[0], frozenset(evidence))
        alerts.setdefault(key, {"rule_version_id": rule[0], "rule_type": rule[1], "severity": rule[2],
                                "evidence": sorted(evidence)})

    for rule in rules:
        version, rule_type, _, d = rule
        for n in new:
            if rule_type == "ddi":
                a, b = sorted(d["ingredients"])
                for m in everyone:
                    if (a in known[n] and b in known[m]) or (b in known[n] and a in known[m]):
                        fire(rule, {n, m})
            elif rule_type == "duplicate":
                for m in everyone:
                    if m != n and known[n] & known[m] & d["ingredients"]:
                        fire(rule, {n, m})
            elif rule_type == "allergy" and known[n] & d["ingredients"]:
                for eid, text in allergies:
                    if any(_mentions(text, t) for t in d["allergen_terms"]):
                        fire(rule, {n, str(eid)})
    ordered = sorted(alerts.values(), key=lambda a: (a["rule_version_id"], a["evidence"]))
    return {"alerts": ordered, "unrecognised": sorted(unrecognised, key=lambda u: (u["scope"], u["event_id"])),
            "not_run": [dict(x) for x in NOT_RUN]}
