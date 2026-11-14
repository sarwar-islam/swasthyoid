"""Step 6A: the schema mechanism (required marks and validation rules) on a synthetic, test-only
spec. No clinical field, rule or value is defined here; SCHEMAS stays empty (pinned elsewhere)."""
from datetime import date, timedelta

import pytest

from swasthyoid.capture import extraction

SPEC = {
    "title": {"kind": "text", "required": True},
    "note": "text",
    "issued": {"kind": "date", "required": True, "rules": ["not_future"]},
    "count": {"kind": "number", "rules": ["positive"]},
    "lines": [{"label": "text", "qty": {"kind": "number", "required": True, "rules": ["positive"]}}],
}


def reading(value, confidence=0.99):
    return {"value": value, "confidence": confidence}


def structured(got, threshold=0.85):
    return extraction.structure(SPEC, got, threshold)


def test_a_future_date_is_never_accepted_whatever_its_confidence():
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
    field = structured({"issued": reading(tomorrow, 1.0)})["issued"]
    assert field["value"] is None and field["manual_entry"] is True and field["error"] == "invalid_not_future"
    assert field["raw"] == tomorrow  # what was read stays visible to the reviewer


def test_a_date_that_passes_its_rule_is_accepted():
    field = structured({"issued": reading("2020-01-02")})["issued"]
    assert field["value"] == "2020-01-02" and field["manual_entry"] is False and "error" not in field


@pytest.mark.parametrize("value", ["0", "-3", "-0.5"])
def test_a_number_that_breaks_the_positive_rule_is_refused(value):
    field = structured({"count": reading(value, 1.0)})["count"]
    assert field["value"] is None and field["error"] == "invalid_positive"


def test_a_number_that_passes_the_positive_rule_is_accepted():
    assert structured({"count": reading("2.5")})["count"]["value"] == "2.5"


def test_rules_apply_inside_repeated_groups():
    rows = structured({"lines": [{"label": reading("a"), "qty": reading("0")}, {"qty": reading("4")}]})["lines"]
    assert rows[0]["qty"]["error"] == "invalid_positive" and rows[1]["qty"]["value"] == "4"


def test_missing_required_reports_unfilled_required_fields_only():
    fields = structured({"issued": reading("2020-01-02"), "lines": [{"qty": reading("4")}, {"qty": reading("0")}]})
    assert extraction.missing_required(SPEC, fields) == ["title", "lines[1].qty"]  # note and count are optional


def test_a_required_field_below_the_threshold_is_reported_missing():
    fields = structured({"title": reading("t", 0.5), "issued": reading("2020-01-02")})
    assert "title" in extraction.missing_required(SPEC, fields) and fields["title"]["raw"] == "t"


def test_nothing_is_missing_when_every_required_field_has_an_accepted_value():
    fields = structured({"title": reading("t"), "issued": reading("2020-01-02"), "lines": [{"qty": reading("1")}]})
    assert extraction.missing_required(SPEC, fields) == []


def test_a_spec_with_only_kinds_behaves_as_before():
    plain = {"name": "text", "when": "date"}
    out = extraction.structure(plain, {"name": reading("x"), "when": reading("2020-01-02")}, 0.85)
    assert out["name"]["value"] == "x" and out["when"]["value"] == "2020-01-02"
    assert extraction.missing_required(plain, out) == []


def test_check_spec_accepts_a_valid_spec_and_refuses_unknown_kinds_and_rules():
    extraction.check_spec(SPEC)
    with pytest.raises(ValueError, match="unknown kind"):
        extraction.check_spec({"x": {"kind": "blob"}})
    with pytest.raises(ValueError, match="unknown rule"):
        extraction.check_spec({"x": {"kind": "text", "rules": ["made_up"]}})
    with pytest.raises(ValueError, match="unknown rule"):
        extraction.check_spec({"g": [{"y": {"kind": "number", "rules": ["made_up"]}}]})


def test_the_clinical_field_list_is_the_approved_one():
    from swasthyoid.tests.approved_fields import APPROVED
    assert extraction.SCHEMAS == APPROVED  # D7 approved by the owner 2026-11-14; reviewer sign-off pending
