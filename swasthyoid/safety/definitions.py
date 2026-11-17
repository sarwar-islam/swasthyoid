"""Strict, versioned technical shapes of the M6 rule definitions the engine runs (P3; owner decision D5, 2026-11-17).

A shape says only where the clinical reviewer's content goes. It holds no clinical content: no drug, pair, allergen or
severity is named here, and none is seeded. Every name a definition holds is the reviewer's, compared by normalised
equality (case, spacing and Bangla digits aside). REVIEWER-PENDING: the clinical reviewer confirms these shapes (FRD Q7).

  schema 1, ddi:       {"schema": 1, "ingredients": [a, b]}              two different ingredient names
  schema 1, allergy:   {"schema": 1, "allergen_terms": [...], "ingredients": [...]}
  schema 1, duplicate: {"schema": 1, "ingredients": [...]}
Each of these needs a severity (an alert always carries one). Other rule types keep the B5 shape checks; drug_disease and
class_lookback have no shape yet and cannot run (D2, D4).
"""
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
