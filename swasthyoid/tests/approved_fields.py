"""The owner-approved extraction field list (docs/DECISIONS.md, "Extraction field list", approved by the
owner on 2026-11-14 with two additions). A SEPARATE copy of the list, so that a test can fail on any field
that capture/extraction.py SCHEMAS adds, drops or retypes. Change it only with a recorded approval.

Transcription only; kinds are text, number or date; a list of one dict is a repeated group.
The clinical reviewer has not been named: reviewer sign-off is PENDING (FRD Q7)."""

MEDICATIONS = [{"name_as_written": "text", "strength": "text", "form": "text", "dose_instruction": "text",
                "duration": "text"}]

APPROVED = {
    "prescription": {
        "prescription_date": "date", "prescriber_name": "text", "prescriber_registration": "text",
        "facility_name": "text", "diagnosis_text": "text", "medications": MEDICATIONS, "advice_text": "text",
        "follow_up_date": "date", "allergy_text": "text",
    },
    "lab_report": {
        "report_date": "date", "lab_name": "text",
        "tests": [{"test_name": "text", "result": "text", "unit": "text", "reference_range": "text"}],
    },
    "discharge_summary": {
        "admission_date": "date", "discharge_date": "date", "follow_up_date": "date", "facility_name": "text",
        "diagnosis_text": "text", "medications": MEDICATIONS, "allergy_text": "text",
    },
    "other": {},
}

# Approved with D7 (stored encrypted, an advisory mismatch flag); in SCHEMAS now that D2 stores fields sealed.
for _doc_type in ("prescription", "lab_report", "discharge_summary"):
    APPROVED[_doc_type]["printed_patient_name"] = "text"
