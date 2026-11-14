"""D7: the approved field list in SCHEMAS and the deterministic parsers (capture/parsers.py).

Synthetic text only. Every field is a transcription: these tests check that nothing is guessed, split or
interpreted, that conflicts and invalid values stay out, and that low or missing confidence goes to manual
entry. They say nothing about OCR quality, and the clinical reviewer's sign-off is still pending."""
import pytest

from swasthyoid.capture import extraction, parsers
from swasthyoid.tests.approved_fields import APPROVED

THRESHOLD = 0.85


def lines(*pairs):
    """A v0-shaped result from (text, confidence) pairs; a bare string gets confidence 0.95."""
    items = [{"text": p, "confidence": 0.95} if isinstance(p, str) else {"text": p[0], "confidence": p[1]} for p in pairs]
    return {"pages": [{"page_number": 1, "items": items}]}


def structured(doc_type, got):
    return extraction.structure(extraction.SCHEMAS[doc_type], parsers.parse(doc_type, got), THRESHOLD)


# ---- the approved list is exactly what the code has

def test_schemas_equal_the_approved_list_and_fail_on_any_difference():
    assert extraction.SCHEMAS == APPROVED


def test_every_field_is_optional_and_nothing_is_required_at_extraction():
    for doc_type, spec in extraction.SCHEMAS.items():
        extraction.check_spec(spec)
        for entry in spec.values():
            for sub in (entry[0].values() if isinstance(entry, list) else [entry]):
                assert isinstance(sub, str)  # a plain kind: no required mark, no rule
        fields = extraction.structure(spec, {}, THRESHOLD)
        assert extraction.missing_required(spec, fields) == []


def test_the_other_document_type_has_no_fields_and_the_parser_returns_nothing_for_it():
    assert extraction.SCHEMAS["other"] == {} and parsers.parse("other", lines("Date: 2024-03-12")) == {}
    assert parsers.parse("unknown_type", lines("Date: 2024-03-12")) == {}


# ---- labelled transcription

def test_a_labelled_value_is_transcribed_verbatim_with_the_confidence_of_its_line():
    got = lines(("Date: 12/03/2024", 0.97), ("Dr: Synth Doctor", 0.9), ("BMDC No: A-12345", 0.88),
                ("Hospital: Synth Facility", 0.93), ("Diagnosis: synthetic text, as written", 0.91))
    out = parsers.parse("prescription", got)
    assert out["prescription_date"] == {"value": "12/03/2024", "confidence": 0.97}
    assert out["prescriber_name"] == {"value": "Synth Doctor", "confidence": 0.9}
    assert out["prescriber_registration"] == {"value": "A-12345", "confidence": 0.88}
    assert out["facility_name"]["value"] == "Synth Facility"
    assert out["diagnosis_text"] == {"value": "synthetic text, as written", "confidence": 0.91}


def test_a_label_alone_takes_the_next_line_and_the_lowest_confidence_of_the_two():
    out = parsers.parse("prescription", lines(("Advice:", 0.99), ("rest and fluids", 0.86)))
    assert out["advice_text"] == {"value": "rest and fluids", "confidence": 0.86}


def test_a_label_alone_followed_by_another_label_has_no_value():
    out = parsers.parse("prescription", lines("Advice:", "Dr: Synth Doctor"))
    assert "advice_text" not in out and out["prescriber_name"]["value"] == "Synth Doctor"


def test_a_word_without_a_separator_is_not_a_label():
    out = parsers.parse("prescription", lines("Date of review is pending", "Dr Synth Doctor", "Hospital - Synth"))
    assert out == {}


def test_labels_are_case_insensitive_and_spaces_are_collapsed():
    out = parsers.parse("prescription", lines("  DATE :   2024-03-12 ", "dr.:  Synth   Doctor"))
    assert out["prescription_date"]["value"] == "2024-03-12" and out["prescriber_name"]["value"] == "Synth Doctor"


def test_text_is_nfc_normalised_and_nothing_else_is_changed():
    out = parsers.parse("prescription", lines("Advice: ো  synthetic"))
    assert out["advice_text"]["value"] == "ো synthetic"


def test_the_same_reading_twice_is_kept_and_conflicting_readings_stay_empty():
    same = parsers.parse("prescription", lines(("Date: 2024-03-12", 0.9), ("Date: 2024-03-12", 0.8)))
    assert same["prescription_date"] == {"value": "2024-03-12", "confidence": 0.8}
    conflict = parsers.parse("prescription", lines("Date: 2024-03-12", "Date: 2024-03-13"))
    assert "prescription_date" not in conflict  # ambiguous: never "first wins"


def test_the_parser_is_deterministic():
    got = lines("Date: 2024-03-12", "Dr: Synth", "Rx:", "SYNTH A", "SYNTH B")
    assert parsers.parse("prescription", got) == parsers.parse("prescription", got)


def test_missing_or_unusable_confidence_counts_as_zero_so_it_goes_to_manual_entry():
    got = {"pages": [{"items": [{"text": "Date: 2024-03-12"}, {"text": "Dr: X", "confidence": float("nan")},
                                {"text": "Advice: y", "confidence": True}]}]}
    out = parsers.parse("prescription", got)
    assert [out[f]["confidence"] for f in ("prescription_date", "prescriber_name", "advice_text")] == [0.0] * 3
    fields = extraction.structure(extraction.SCHEMAS["prescription"], out, THRESHOLD)
    assert fields["prescription_date"]["manual_entry"] is True and fields["prescription_date"]["value"] is None


def test_malformed_input_gives_no_fields_instead_of_an_error():
    for got in (None, {}, {"pages": None}, {"pages": [None, {"items": None}, {"items": [None, {"text": 5}]}]}):
        assert parsers.parse("prescription", got) == {}


# ---- dates go through the existing parser: invalid is never accepted

def test_an_accepted_date_format_is_stored_in_iso_form_and_bangla_digits_work():
    fields = structured("prescription", lines("Date: 12/03/2024", "Follow up: ১২-০৪-২০২৪"))
    assert fields["prescription_date"]["value"] == "2024-03-12" and fields["prescription_date"]["manual_entry"] is False
    assert fields["follow_up_date"]["value"] == "2024-04-12"


@pytest.mark.parametrize("written", ["31/02/2024", "12 March 2024", "2024/03/12", "12/03/2024 (Tue)", "soon"])
def test_an_invalid_date_is_kept_as_the_raw_reading_and_never_accepted(written):
    field = structured("prescription", lines((f"Date: {written}", 1.0)))["prescription_date"]
    assert field["value"] is None and field["manual_entry"] is True and field["error"] == "invalid_date"
    assert field["raw"] == written


def test_a_field_below_the_threshold_is_left_for_manual_entry_with_the_reading_kept():
    field = structured("prescription", lines(("Dr: Synth Doctor", 0.5)))["prescriber_name"]
    assert field["value"] is None and field["manual_entry"] is True and field["raw"] == "Synth Doctor"


# ---- repeated groups: rows kept whole, nothing split

def test_medication_rows_are_whole_lines_under_the_anchor_up_to_the_next_label():
    got = lines("Rx:", ("SYNTH-DRUG-001 500 mg 1+0+1 5 days", 0.93), "SYNTH-DRUG-002 tablet", "Advice: rest")
    rows = parsers.parse("prescription", got)["medications"]
    assert [r["name_as_written"]["value"] for r in rows] == ["SYNTH-DRUG-001 500 mg 1+0+1 5 days", "SYNTH-DRUG-002 tablet"]
    assert rows[0]["name_as_written"]["confidence"] == 0.93 and set(rows[0]) == {"name_as_written"}  # nothing is split off


def test_the_first_row_may_sit_on_the_anchor_line():
    rows = parsers.parse("prescription", lines("Medications: SYNTH-A", "SYNTH-B"))["medications"]
    assert [r["name_as_written"]["value"] for r in rows] == ["SYNTH-A", "SYNTH-B"]


def test_strength_form_dose_and_duration_stay_empty_for_manual_entry():
    fields = structured("prescription", lines("Rx:", "SYNTH-DRUG-001 500 mg 1+0+1 5 days"))
    row = fields["medications"][0]
    assert row["name_as_written"]["manual_entry"] is False
    for sub in ("strength", "form", "dose_instruction", "duration"):
        assert row[sub]["value"] is None and row[sub]["manual_entry"] is True


def test_no_anchor_means_no_rows():
    assert "medications" not in parsers.parse("prescription", lines("SYNTH-DRUG-001", "SYNTH-DRUG-002"))


# ---- the other document types

def test_a_lab_report_keeps_test_rows_whole_and_result_unit_and_range_empty():
    got = lines("Report date: 2024-03-12", "Laboratory: Synth Lab", "Tests:", "SYNTH-TEST-A 5.4 mg/dL (3 - 6)")
    fields = structured("lab_report", got)
    assert fields["report_date"]["value"] == "2024-03-12" and fields["lab_name"]["value"] == "Synth Lab"
    row = fields["tests"][0]
    assert row["test_name"]["value"] == "SYNTH-TEST-A 5.4 mg/dL (3 - 6)"
    assert all(row[s]["value"] is None for s in ("result", "unit", "reference_range"))


def test_a_discharge_summary_has_its_three_dates_allergy_and_medications():
    got = lines("Date of admission: 2024-03-01", "Discharge date: 2024-03-05", "Follow up: 2024-04-01",
                "Allergies: synthetic note", "Diagnosis: synthetic", "Rx:", "SYNTH-DRUG-001")
    fields = structured("discharge_summary", got)
    assert [fields[f]["value"] for f in ("admission_date", "discharge_date", "follow_up_date")] == \
        ["2024-03-01", "2024-03-05", "2024-04-01"]
    assert fields["allergy_text"]["value"] == "synthetic note" and len(fields["medications"]) == 1


def test_allergy_text_is_its_own_field_on_a_prescription():
    assert parsers.parse("prescription", lines("Allergy: synthetic note"))["allergy_text"]["value"] == "synthetic note"


def test_a_reviewer_supplied_label_list_replaces_the_defaults_for_one_call():
    custom = {"prescription": {"prescription_date": ("tarikh",)}}
    assert parsers.parse("prescription", lines("tarikh: 2024-03-12"), labels=custom)["prescription_date"]["value"] == "2024-03-12"
    assert parsers.parse("prescription", lines("Date: 2024-03-12"), labels=custom) == {}


def test_the_printed_patient_name_is_not_extracted_unless_explicitly_enabled():
    got = lines("Patient: Synth Person")
    assert parsers.parse("prescription", got) == {}
    assert parsers.parse("prescription", got, patient_name=True)["printed_patient_name"]["value"] == "Synth Person"


def test_the_parser_never_returns_a_value_that_was_not_on_the_page():
    got = lines("Date: 2024-03-12", "Dr: Synth Doctor", "Rx:", "SYNTH-A")
    page_text = " ".join(i["text"] for i in got["pages"][0]["items"])
    out = parsers.parse("prescription", got)
    values = [out[f]["value"] for f in out if isinstance(out[f], dict)] + \
             [r["name_as_written"]["value"] for r in out["medications"]]
    assert all(v in page_text for v in values)


def test_diagnosis_text_is_never_referenced_by_any_code_that_could_create_an_event():
    """The owner's rule (D7 Q4): diagnosis_text is shown with the document only and is never promoted to a verified
    diagnosis event without M3 confirmation. M3 and M4 do not exist yet, so no module outside the extraction code
    may even name the field."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    allowed = {"capture/extraction.py", "capture/parsers.py"}
    for path in root.rglob("*.py"):
        rel = path.relative_to(root).as_posix()
        if rel.startswith("tests/") or rel in allowed:
            continue
        assert "diagnosis_text" not in path.read_text(encoding="utf-8"), rel
