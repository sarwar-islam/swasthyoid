"""Drug-name matching infrastructure (M2 step 7; docs/DECISIONS.md D8). CATALOG-INDEPENDENT.

No catalog is supplied here and none is invented: a Catalog is built by the caller from approved
data (FRD Q1), with the version and source it came from, and every result carries them. Tests use
synthetic names only.

What this decides, and what it refuses to decide:
- It NEVER selects a drug. Every result has review_required=True and there is no "selected" field:
  a person picks in M3. "exact" means the written name equals a catalog name after safe
  normalisation, and nothing more.
- It never infers a strength or a form that was not written, and never treats similar names as
  equivalent. Strength and form are used only to NARROW exact name matches, by equality after
  normalisation; a record whose value CONFLICTS with the written one is dropped, a record that has NO
  value for it is kept (a missing value cannot confirm or exclude anything) and marked `unconfirmed`.
  A candidate with an unconfirmed attribute is never "exact": the result is ambiguous. When an exact
  match has a strength or form the written text did not state, `unconfirmed` lists it too.
- Similar-name suggestions exist only when the caller passes BOTH `suggestion_floor` and
  `max_suggestions`. They are the D8 parameters (how close is "similar", how many to show), they
  need the clinical reviewer's sign-off, and so they have NO defaults.
- Deterministic: same input and catalog, same output, whatever the order of the catalog entries.

Statuses: "exact" (one catalog entry has this name and nothing it was asked about is unconfirmed),
"ambiguous" (more than one entry, the written strength or form conflicts, or the one entry lacks a
written strength or form), "suggested" (no exact name; similar names listed for a
person), "unrecognised" (nothing; the written name is kept verbatim and visible).
"""
import re
import unicodedata
from types import MappingProxyType

_BANGLA_DIGITS = str.maketrans("০১২৩৪৫৬৭৮৯", "0123456789")


def normalize(text):
    """The comparison key of a name, strength or form: NFC, Bangla digits to ASCII, case-folded,
    whitespace collapsed. Nothing else is changed (no spelling fixes, no unit conversion)."""
    if not isinstance(text, str):
        return ""
    return " ".join(unicodedata.normalize("NFC", text).translate(_BANGLA_DIGITS).casefold().split())


def _compact(text):
    """A strength key: normalize(), then spaces between a digit and what follows are removed, so
    '500 mg' equals '500mg'. Spaces INSIDE a number are kept: '1 0 mg' (an OCR gap) does not equal
    '10 mg'. Units are case-folded like all text, which is a known simplification."""
    return re.sub(r"(?<=\d) (?=\D)", "", normalize(text))


class Catalog:
    """A READ-ONLY catalog: entries {id, generic, brands, strength, form, manufacturer} plus its provenance.
    `id` is the source record's own id and is kept as given. A generic name or a brand name may be absent
    (never both); strength, form and manufacturer may be absent, and an absent value stays absent. The
    manufacturer is shown with a candidate and is never used to choose one. Neither the catalog nor its
    entries can be changed after construction."""

    __slots__ = ("version", "source", "entries")

    def __init__(self, version, source, entries):
        if hasattr(self, "entries"):  # an initialised catalog cannot be re-initialised to change it
            raise AttributeError("a Catalog is read-only")
        if not (isinstance(version, str) and version.strip() and isinstance(source, str) and source.strip()):
            raise ValueError("a catalog needs a version and a source")
        seen, out = set(), []
        for entry in entries:
            if not (isinstance(entry, dict) and isinstance(entry.get("id"), str) and entry["id"]):
                raise ValueError("every catalog entry needs an id")
            generic = entry.get("generic")
            if generic is not None and not (isinstance(generic, str) and normalize(generic)):
                raise ValueError("a generic name must be text or absent")
            if entry["id"] in seen:
                raise ValueError("duplicate catalog entry id")
            seen.add(entry["id"])
            brands = entry.get("brands") or []
            if not (isinstance(brands, (list, tuple)) and all(isinstance(b, str) and normalize(b) for b in brands)):
                raise ValueError("brands must be a list of non-empty names")
            if generic is None and not brands:
                raise ValueError("every catalog entry needs a generic name or a brand name")
            for key in ("strength", "form", "manufacturer"):
                if entry.get(key) is not None and not isinstance(entry[key], str):
                    raise ValueError(f"{key} must be text or absent")
            out.append(MappingProxyType({"id": entry["id"], "generic": generic, "brands": tuple(brands),
                                         "strength": entry.get("strength"), "form": entry.get("form"),
                                         "manufacturer": entry.get("manufacturer")}))
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "entries", tuple(sorted(out, key=lambda e: e["id"])))

    def __setattr__(self, name, value):
        raise AttributeError("a Catalog is read-only")

    def __delattr__(self, name):
        raise AttributeError("a Catalog is read-only")

    def provenance(self):
        return {"version": self.version, "source": self.source}


def _trigrams(text):
    padded = f"  {normalize(text)} "
    return {padded[i:i + 3] for i in range(len(padded) - 2)}


def similarity(a, b):
    """Jaccard similarity of the trigram sets of two normalised names, 0.0 to 1.0."""
    ta, tb = _trigrams(a), _trigrams(b)
    union = ta | tb
    return len(ta & tb) / len(union) if union else 0.0


def _names(entry):
    named = [("generic", entry["generic"])] if entry["generic"] is not None else []
    return named + [("brand", b) for b in entry["brands"]]


def _candidate(entry, matched_on, score):
    """A fresh copy of what the catalog holds, as it holds it: a candidate, never a verified record.
    `unconfirmed` lists the attributes the written text stated and this record does not hold."""
    return {"id": entry["id"], "generic": entry["generic"], "brands": list(entry["brands"]), "matched_on": matched_on,
            "strength": entry["strength"], "form": entry["form"], "manufacturer": entry["manufacturer"], "score": score,
            "unconfirmed": []}


def match(name, catalog, *, strength=None, form=None, suggestion_floor=None, max_suggestions=None):
    """Match one written drug name. Returns a dict: status, review_required (always True), written
    (the name exactly as given), written_strength and written_form (as given, never filled in),
    candidates, reason, catalog (version and source). `strength` and `form` narrow exact name
    matches by equality; they are never inferred. Raises ValueError for unusable parameters."""
    if not isinstance(catalog, Catalog):
        raise ValueError("a Catalog is required")
    if (suggestion_floor is None) != (max_suggestions is None):
        raise ValueError("suggestion_floor and max_suggestions must be given together or not at all")
    if suggestion_floor is not None:
        if isinstance(suggestion_floor, bool) or not isinstance(suggestion_floor, (int, float)) \
                or not 0 < suggestion_floor <= 1:
            raise ValueError("suggestion_floor must be a number above 0 and at most 1")
        if isinstance(max_suggestions, bool) or not isinstance(max_suggestions, int) or max_suggestions < 1:
            raise ValueError("max_suggestions must be a positive integer")
    result = {"status": "unrecognised", "review_required": True, "written": name,
              "written_strength": strength, "written_form": form, "candidates": [], "reason": None,
              "unconfirmed": [], "catalog": catalog.provenance()}
    key = normalize(name)
    if not key:
        result["reason"] = "empty"
        return result

    exact = []
    for entry in catalog.entries:
        for kind, known in _names(entry):
            if normalize(known) == key:
                exact.append(_candidate(entry, kind, 1.0))
                break
    if exact:
        wanted = [(strength, _compact, "strength"), (form, normalize, "form")]
        narrowed = exact
        for value, fold, field in wanted:
            if value is not None:
                for c in exact:  # a record with no value for this attribute cannot confirm it: kept, marked
                    if c[field] is None:
                        c["unconfirmed"].append(field)
                narrowed = [c for c in narrowed if c[field] is None or fold(c[field]) == fold(value)]
        if not narrowed:
            result.update(status="ambiguous", candidates=exact, reason="attribute_mismatch")
        elif len(narrowed) > 1:
            result.update(status="ambiguous", candidates=narrowed, reason="multiple_entries")
        elif narrowed[0]["unconfirmed"]:
            result.update(status="ambiguous", candidates=narrowed, reason="attribute_unconfirmed")
        else:
            # the catalog entry has attributes the written text did not state: shown, never filled in
            unconfirmed = [f for f, value in (("strength", strength), ("form", form))
                           if value is None and narrowed[0][f] is not None]
            result.update(status="exact", candidates=narrowed, unconfirmed=unconfirmed)
        if result["status"] == "ambiguous":
            result["unconfirmed"] = [f for f in ("strength", "form") if any(f in c["unconfirmed"] for c in result["candidates"])]
        return result

    if suggestion_floor is not None:
        scored = []
        for entry in catalog.entries:
            best = max(((similarity(key, known), kind) for kind, known in _names(entry)), key=lambda s: (s[0], s[1]))
            if best[0] >= suggestion_floor:
                scored.append(_candidate(entry, best[1], best[0]))
        scored.sort(key=lambda c: (-c["score"], c["id"]))
        if scored:
            result.update(status="suggested", candidates=scored[:max_suggestions], reason="similar_names")
    return result
