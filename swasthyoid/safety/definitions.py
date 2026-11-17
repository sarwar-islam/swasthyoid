"""Strict, versioned technical shapes of the M6 rule definitions the engine runs (P3; owner decision D5, 2026-11-17).

A shape says only where the clinical reviewer's content goes. It holds no clinical content: no drug, pair, allergen or
severity is named here, and none is seeded. Every name a definition holds is the reviewer's, compared by normalised
equality (case, spacing and Bangla digits aside). REVIEWER-PENDING: the clinical reviewer confirms these shapes (FRD Q7).

  schema 1, ddi:       {"schema": 1, "ingredients": [a, b]}              two different ingredient names
  schema 1, allergy:   {"schema": 1, "allergen_terms": [...], "ingredients": [...]}
  schema 1, duplicate: {"schema": 1, "ingredients": [...]}
Each of these needs a severity (an alert always carries one). Other rule types keep the B5 shape checks; drug_disease and
class_lookback have no shape yet and cannot run (D2, D4).

M13 home vitals (P6; owner decisions V1-V3, 2026-11-17). The shapes name what a rule applies to; every number in them is
the clinical reviewer's (or, for a threshold, the treating doctor's per-patient value, B6), never a default here:
  schema 1, vital_threshold:   {"schema": 1, "vital_type", "unit", "component" (bp only), "contexts": [...],
                                "comparison": "at_or_above" | "at_or_below", "level": "flagged" | "critical"}
  schema 1, vital_plausibility: {"schema": 1, "vital_type", "unit", "component" (bp only), "at_least": n, "at_most": n}
"""
import math

from swasthyoid.capture.drugmatch import normalize

SCHEMA = 1
MAX_TERMS, MAX_TERM = 200, 200  # engineering limits, not clinical values
KEYS = {"ddi": ("ingredients",), "allergy": ("allergen_terms", "ingredients"), "duplicate": ("ingredients",)}
ENGINE_TYPES = tuple(KEYS)


class Invalid(Exception):
    """The definition does not fit its type's shape."""


def _names(value, exactly=None):
    if not (isinstance(value, list) and 0 < len(value) <= MAX_TERMS):
        raise Invalid()
    if not all(isinstance(v, str) and 0 < len(normalize(v)) <= MAX_TERM for v in value):
        raise Invalid()
    names = frozenset(normalize(v) for v in value)
    if len(names) != len(value) or (exactly is not None and len(names) != exactly):
        raise Invalid()
    return names


def parse(rule_type, severity, definition):
    """The normalised content of an engine rule: {key: frozenset}. Raises Invalid when it does not fit."""
    if rule_type not in KEYS or severity is None or not isinstance(definition, dict):
        raise Invalid()
    if definition.get("schema") != SCHEMA or isinstance(definition.get("schema"), bool):
        raise Invalid()
    if set(definition) != {"schema", *KEYS[rule_type]}:
        raise Invalid()
    return {k: _names(definition[k], 2 if rule_type == "ddi" else None) for k in KEYS[rule_type]}


# The web app's existing vocabulary (owner decision V2): units and measurement contexts per vital, the parts of a BP reading.
VITALS = {"bp": {"units": ("mmHg",), "contexts": ("home", "resting"), "components": ("systolic", "diastolic")},
          "glucose": {"units": ("mmol/L", "mg/dL"), "contexts": ("fasting", "post_meal", "random"), "components": ()}}
VITAL_RULE_TYPES = ("vital_threshold", "vital_plausibility")
_VITAL_KEYS = {"vital_threshold": ("contexts", "comparison", "level"), "vital_plausibility": ("at_least", "at_most")}


def _number(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) and v > 0


def parse_vital(rule_type, definition):
    """The content of a vital rule as a dict, or Invalid. A unit that does not fit the vital raises Invalid("unit")."""
    if rule_type not in _VITAL_KEYS or not isinstance(definition, dict):
        raise Invalid()
    vital = VITALS.get(definition.get("vital_type"))
    if vital is None or definition.get("unit") not in vital["units"]:
        raise Invalid("unit")  # what it applies to does not fit: the B5 code invalid_vital_threshold
    keys = {"schema", "vital_type", "unit", *_VITAL_KEYS[rule_type]} | ({"component"} if vital["components"] else set())
    if definition.get("schema") != SCHEMA or isinstance(definition.get("schema"), bool) or set(definition) != keys:
        raise Invalid()
    if vital["components"] and definition["component"] not in vital["components"]:
        raise Invalid()
    if rule_type == "vital_threshold":
        contexts = definition["contexts"]
        if not (isinstance(contexts, list) and contexts and len(set(contexts)) == len(contexts)
                and all(c in vital["contexts"] for c in contexts)):
            raise Invalid()
        if definition["comparison"] not in ("at_or_above", "at_or_below") or definition["level"] not in ("flagged", "critical"):
            raise Invalid()
    elif not (_number(definition["at_least"]) and _number(definition["at_most"]) and definition["at_least"] < definition["at_most"]):
        raise Invalid()
    return {**definition, "component": definition.get("component")}
