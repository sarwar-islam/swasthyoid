"""Deterministic parsers for the approved clinical field list (M2 step 6B; docs/DECISIONS.md, "Owner
decisions of 2026-11-14", D7). No language model. Pure functions: OCR output in, candidate fields out.

What this does, and refuses to do:
- Every field is a TRANSCRIPTION of what is written. Nothing is interpreted, coded, normalised
  beyond Unicode NFC and trimmed spaces, or inferred. Anything the parser cannot place stays empty
  and goes to manual entry. An invalid value (for example a date in no accepted format) is kept as
  the raw reading and never accepted: extraction.structure() enforces that, whatever the confidence.
- A field is taken only from a LABELLED line: `label: value` on one line, or `label:` alone with the
  value on the next line. A label without a separator is not a label. If the same field is found
  twice with different values, it stays empty (ambiguous), never "first wins".
- Repeated groups (medications, tests): each line under the group's anchor (also across pages, also
  on the anchor line itself), up to the next labelled line, is one row, kept whole as `name_as_written` /
  `test_name`. A leading list marker ("1.", "2)", "১।", "•", "-", followed by a space) is layout and is
  removed; a line with no letter or digit left is not a row. A row is never joined with the next line
  (a wrapped row stays two rows: telling a continuation from a new row needs vocabulary).
- Splitting a row into strength, form, dose instruction, duration, result, unit or reference range
  needs vocabularies that the clinical reviewer has not supplied. The hook for it is ROW_SPLITTERS
  (REVIEWER-PENDING, empty): until a splitter is registered those fields stay empty for manual entry.
  A splitter's output is checked and refused whole (the row stays unsplit) if any part is not an
  allowed field or not text found in the row as written. Nothing here is a clinical rule.
- Field confidence is the LOWEST OCR confidence among the lines the field came from (a missing
  confidence counts as 0.0, so it goes to manual entry). What an OCR confidence means is open until
  D18; this is not clinical correctness.
- Labels are structural English words, a PROPOSED default. Other languages need a label list from the
  reviewer; pass it as `labels`. Bangla labels are deliberately not guessed here.

Input is the validated interface-version-0 result (`{"pages": [{"items": [{"text", "confidence"}]}]}`,
already in reading order per page); positions are ignored. Output is the shape extraction.structure()
takes: `{field: {"value", "confidence"}}`, with a list of row dicts for a group.
"""
import logging
import re
import unicodedata
from collections.abc import Callable, Mapping

log = logging.getLogger(__name__)

# PROPOSED default structural labels (English). Not clinical vocabulary; a first-party list per language
# is the reviewer's to supply.
LABELS = {
    "prescription": {
        "prescription_date": ("date", "dated", "prescription date"),
        "prescriber_name": ("doctor", "dr", "prescriber"),
        "prescriber_registration": ("registration", "registration no", "reg", "reg no", "bmdc", "bmdc no",
                                    "bmdc reg no"),
        "facility_name": ("hospital", "clinic", "facility", "centre", "center"),
        "diagnosis_text": ("diagnosis", "dx"),
        "advice_text": ("advice", "advise", "instructions"),
        "follow_up_date": ("follow up", "follow-up", "followup", "next visit", "review date"),
        "allergy_text": ("allergy", "allergies"),
    },
    "lab_report": {
        "report_date": ("date", "report date", "reported on"),
        "lab_name": ("laboratory", "lab", "lab name"),
    },
    "discharge_summary": {
        "admission_date": ("admission date", "date of admission", "admitted"),
        "discharge_date": ("discharge date", "date of discharge", "discharged"),
        "follow_up_date": ("follow up", "follow-up", "followup", "next visit", "review date"),
        "facility_name": ("hospital", "clinic", "facility", "centre", "center"),
        "diagnosis_text": ("diagnosis", "dx"),
        "allergy_text": ("allergy", "allergies"),
    },
}
_MEDICATION_PARTS = ("strength", "form", "dose_instruction", "duration")
GROUPS = {
    "prescription": {"medications": ("rx", "medication", "medications", "medicine", "medicines"),
                     "row_field": "name_as_written", "split_fields": _MEDICATION_PARTS},
    "lab_report": {"tests": ("test", "tests", "investigation", "investigations"), "row_field": "test_name",
                   "split_fields": ("result", "unit", "reference_range")},
    "discharge_summary": {"medications": ("rx", "medication", "medications", "medicine", "medicines"),
                          "row_field": "name_as_written", "split_fields": _MEDICATION_PARTS},
}
_GROUP_KEYS = ("row_field", "split_fields")

# REVIEWER-PENDING (FRD Q7, D7): row splitting needs the clinical reviewer's vocabularies (strengths and units, forms,
# dose and frequency notation, durations, result units, reference-range notation). None is supplied, so NO splitter is
# registered and the split fields stay empty for manual entry. Do not add one without the reviewer's signed vocabulary.
# A RowSplitter takes the row text (as stored in the row field) and returns {split field: that part's text exactly as
# written in the row}; it must be deterministic and must not guess. Register it per document type.
RowSplitter = Callable[[str], Mapping[str, str]]
ROW_SPLITTERS: dict[str, RowSplitter] = {}

_SEPARATOR = re.compile(r"\s*[:：]\s*")
_PRINTED_PATIENT = ("patient", "patient name", "name of patient")
# Structural default, not clinical: a list marker at the start of a row, then a space or the end of the line. "5% ..." or
# "0.9% ..." are not markers (no space after the punctuation).
_ROW_MARKER = re.compile(r"(?:[0-9০-৯]{1,2}\s*[.)।]|[•·*\-–—])(?:\s+|$)")


def _clean(text):
    return " ".join(unicodedata.normalize("NFC", text).split())


def _key(text):
    return _clean(text).casefold().rstrip(".")


def _lines(got):
    """(text, confidence) of every non-empty OCR line, page by page, in the order given."""
    out = []
    pages = got.get("pages") if isinstance(got, dict) else None
    for page in pages if isinstance(pages, list) else []:
        items = page.get("items") if isinstance(page, dict) else None
        for item in items if isinstance(items, list) else []:
            text = _clean(item.get("text", "")) if isinstance(item, dict) and isinstance(item.get("text"), str) else ""
            if text:
                confidence = item.get("confidence")
                ok = isinstance(confidence, (int, float)) and not isinstance(confidence, bool) and confidence == confidence
                out.append((text, float(confidence) if ok else 0.0))
    return out


def _split_label(text, known):
    """(label key, value) if the line is `known label : value` or `known label :`, else None."""
    parts = _SEPARATOR.split(text, maxsplit=1)
    if len(parts) != 2:
        return None
    label = _key(parts[0])
    return (label, parts[1].strip()) if label in known else None


def _field_index(labels):
    return {_key(l): field for field, names in labels.items() for l in names}


def _row_text(text):
    """The row without its leading list marker, or None if nothing with a letter or digit is left."""
    marker = _ROW_MARKER.match(text)
    text = text[marker.end():] if marker else text
    return text if any(ch.isalnum() for ch in text) else None


def _split(splitter, text, allowed):
    """{split field: text} from a reviewer splitter, or {} so the row stays whole: no splitter, the splitter raised,
    or ANY part is refused (not an allowed field, not a non-empty string, or not found in the row as written)."""
    if splitter is None:
        return {}
    try:
        parts = splitter(text)
    except Exception as e:
        log.warning("row splitter failed: code=%s", type(e).__name__)  # a type name only, never row text
        return {}
    out = {}
    for field, value in (parts.items() if isinstance(parts, Mapping) else [(None, None)]):
        value = _clean(value) if isinstance(value, str) else ""
        if field not in allowed or not value or value not in text:
            log.warning("row splitter output refused: code=invalid_part")
            return {}
        out[field] = value
    return out


def parse(doc_type, got, labels=None, patient_name=False, row_splitters=None):
    """Candidate fields for one document, or {} for a document type without parsers (other, unknown).
    `labels` overrides LABELS for this call (a reviewer-supplied list, per language). `patient_name`
    adds `printed_patient_name` (only once the field is stored encrypted: D2). `row_splitters` overrides
    ROW_SPLITTERS for this call (doc_type -> RowSplitter)."""
    table = (labels or LABELS).get(doc_type)
    if table is None:
        return {}
    group = GROUPS.get(doc_type)
    index = _field_index(table)
    group_name = next((g for g in group if g not in _GROUP_KEYS), None) if group else None
    anchors = {_key(a): group_name for a in group[group_name]} if group_name else {}
    patient_keys = {_key(p) for p in _PRINTED_PATIENT} if patient_name else set()
    known = set(index) | set(anchors) | patient_keys
    lines = _lines(got)

    found = {}  # field -> list of (value, confidence)
    rows = []
    i, in_group = 0, False
    while i < len(lines):
        text, confidence = lines[i]
        hit = _split_label(text, known)
        if hit is None:
            if in_group:
                rows.append((text, confidence))  # a line under the anchor, kept whole
            i += 1
            continue
        label, value = hit
        in_group = label in anchors
        if label in anchors:
            if value:  # `Rx: first line` carries the first row on the anchor line itself
                rows.append((value, confidence))
            i += 1
            continue
        low = confidence
        if not value and i + 1 < len(lines) and _split_label(lines[i + 1][0], known) is None:
            value, low = lines[i + 1][0], min(confidence, lines[i + 1][1])
            i += 1
        i += 1
        if value:
            field = index.get(label, "printed_patient_name" if label in patient_keys else None)
            found.setdefault(field, []).append((value, low))

    out = {}
    for field, readings in found.items():
        values = {v for v, _ in readings}
        if len(values) == 1:  # the same reading more than once is fine; conflicting readings stay empty
            out[field] = {"value": readings[0][0], "confidence": min(c for _, c in readings)}
    splitter = (ROW_SPLITTERS if row_splitters is None else row_splitters).get(doc_type)
    kept = []
    for raw, c in rows:
        text = _row_text(raw)
        if text is not None:
            parts = _split(splitter, text, group["split_fields"])
            kept.append({group["row_field"]: {"value": text, "confidence": c},
                         **{field: {"value": value, "confidence": c} for field, value in parts.items()}})
    if kept:
        out[group_name] = kept
    return out
