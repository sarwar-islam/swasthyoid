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

Phase 7B (docs/DECISIONS.md "Phase 7B"): the Catalog keeps a read-only name index, so an exact lookup does not scan the
catalog. A generic name that many records share is returned as GROUPS (one candidate per generic, strength and form, with
every source id kept), not as hundreds of brand rows. `match_row()` finds catalog names inside the free text of one written
row (exact normalised phrase windows; no similarity, no abbreviation expansion, no alias) and flags whether each candidate's
strength and form also appear in that text. These row rules are PROVISIONAL and belong to the clinical reviewer (D8).

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

    __slots__ = ("version", "source", "entries", "_by_name", "_limits")

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
        entries = tuple(sorted(out, key=lambda e: e["id"]))
        by_name, longest = {}, {"name": 1, "strength": 1, "form": 1}  # normalised name -> ((position, kind), ...)
        for position, entry in enumerate(entries):
            first = {}
            for kind, known in _names(entry):
                key = normalize(known)
                longest["name"] = max(longest["name"], len(key.split()))
                first.setdefault(key, kind)  # the generic is listed first, so it wins when a brand repeats it
            for key, kind in first.items():
                by_name.setdefault(key, []).append((position, kind))
            for field in ("strength", "form"):
                if entry[field] is not None:
                    longest[field] = max(longest[field], len(normalize(entry[field]).split()))
        object.__setattr__(self, "version", version)
        object.__setattr__(self, "source", source)
        object.__setattr__(self, "entries", entries)
        object.__setattr__(self, "_by_name", MappingProxyType({k: tuple(v) for k, v in by_name.items()}))
        object.__setattr__(self, "_limits", MappingProxyType(longest))

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


def _exact_candidates(catalog, key):
    """Every record whose brand or generic name equals the normalised `key`, from the index (no scan). When several
    records share a GENERIC name they come back as groups; brand-name records are always listed one by one."""
    hits = [(catalog.entries[position], kind) for position, kind in catalog._by_name.get(key, ())]
    generic = [entry for entry, kind in hits if kind == "generic"]
    if len(generic) <= 1:
        return [_candidate(entry, kind, 1.0) for entry, kind in hits]
    groups = {}
    for entry in generic:
        groups.setdefault((entry["generic"], entry["strength"], entry["form"]), []).append(entry)
    out = [{"id": rows[0]["id"], "ids": [r["id"] for r in rows], "kind": "generic_group", "generic": g,
            "strength": strength, "form": form, "matched_on": "generic", "score": 1.0, "unconfirmed": [],
            "brand_count": sum(1 for r in rows if r["brands"]),
            "manufacturer_count": len({r["manufacturer"] for r in rows if r["manufacturer"] is not None})}
           for (g, strength, form), rows in groups.items()]
    out += [_candidate(entry, kind, 1.0) for entry, kind in hits if kind != "generic"]
    return sorted(out, key=lambda c: c["id"])


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

    exact = _exact_candidates(catalog, key)
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
        elif len(narrowed[0].get("ids", (None,))) > 1:  # one generic, strength and form, but several catalog records
            result.update(status="ambiguous", candidates=narrowed, reason="generic_name")
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


# ---- matching names inside the free text of one written row (PROVISIONAL, D8: the clinical reviewer owns these rules)

MAX_ROW_CANDIDATES = 50  # engineering limit per row, not a clinical value; `truncated` says how many were left out
_EDGE = ",.;:"  # stripped from the ends of a word for a second try: "Napa," is read as "Napa"; nothing else is stripped


def _windows(tokens, longest):
    return [(i, j) for i in range(len(tokens)) for j in range(min(len(tokens), i + longest), i, -1)]


def _row_candidate(c, strengths, forms):
    """The compact form kept with an extraction. Strength and form are CHECKS against the row's own text, never filters."""
    def check(value, seen, fold):
        return "catalog_missing" if value is None else "confirmed" if fold(value) in seen else "unconfirmed"

    out = {"id": c["id"], "kind": c.get("kind", "record"), "generic": c["generic"], "strength": c["strength"],
           "form": c["form"], "matched_on": c["matched_on"],
           "strength_check": check(c["strength"], strengths, _compact), "form_check": check(c["form"], forms, normalize)}
    if "ids" in c:
        out.update(ids=list(c["ids"]), brand_count=c["brand_count"], manufacturer_count=c["manufacturer_count"])
    else:
        out.update(brands=list(c["brands"]), manufacturer=c["manufacturer"])
    return out


def match_row(text, catalog, *, max_candidates=MAX_ROW_CANDIDATES):
    """Catalog names found inside one row's written text. Returns {status, review_required (always True), matches,
    truncated}. status is "candidates" or "unrecognised". Each match: {phrase, start, end, status, reason, candidates}
    from match(), so nothing is ever selected; every candidate also carries strength_check and form_check
    ("confirmed" when the catalog's value appears in the row text as an exact word window, "unconfirmed" when it does not,
    "catalog_missing" when the catalog has none). Only exact normalised equality is used: no similarity, no
    abbreviation expansion ("Tab." is not "tablet"), no alias. A window inside a longer matched window is dropped.
    Raises ValueError if `catalog` is not a Catalog; text that is not a string finds nothing."""
    if not isinstance(catalog, Catalog):
        raise ValueError("a Catalog is required")
    raw = normalize(text).split()
    stripped = [t.strip(_EDGE) or t for t in raw]
    views = (raw, stripped) if stripped != raw else (raw,)
    found = []
    for i, j in _windows(raw, catalog._limits["name"]):
        for view in views:
            key = " ".join(view[i:j])
            if key in catalog._by_name:
                found.append((i, j, key))
                break
    kept = []
    for i, j, key in sorted(found, key=lambda f: (-(f[1] - f[0]), f[0])):  # longest first
        if not any(ki <= i and j <= kj for ki, kj, _ in kept):
            kept.append((i, j, key))
    kept.sort()
    strengths, forms = set(), set()
    if kept:
        for view in views:
            strengths |= {_compact(" ".join(view[a:b])) for a, b in _windows(view, catalog._limits["strength"])}
            forms |= {normalize(" ".join(view[a:b])) for a, b in _windows(view, catalog._limits["form"])}
    matches, room, truncated = [], max_candidates, 0
    for i, j, key in kept:
        result = match(key, catalog)
        take = result["candidates"][:room]
        truncated += len(result["candidates"]) - len(take)
        room -= len(take)
        if take:
            matches.append({"phrase": key, "start": i, "end": j, "status": result["status"], "reason": result["reason"],
                            "candidates": [_row_candidate(c, strengths, forms) for c in take]})
    return {"status": "candidates" if matches else "unrecognised", "review_required": True, "matches": matches,
            "truncated": truncated}
