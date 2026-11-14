"""Drug-name matching infrastructure (capture/drugmatch.py). Synthetic names only: the catalog below
is a controlled test fixture, not a drug catalog. No clinical content, no real names, no approved
thresholds (suggestion parameters are passed explicitly in each test)."""
import pytest

from swasthyoid.capture import drugmatch
from swasthyoid.capture.drugmatch import Catalog, match

ENTRIES = [
    {"id": "S1", "generic": "SYNTH-ALPHA", "brands": ["Brandone", "Bran-One"], "strength": "10 mg", "form": "tablet"},
    {"id": "S2", "generic": "SYNTH-ALPHA", "brands": ["Brandone"], "strength": "20 mg", "form": "tablet"},
    {"id": "S3", "generic": "SYNTH-ALPHB", "brands": [], "strength": "5 mg", "form": "syrup"},
    {"id": "S4", "generic": "SYNTH-GAMMA", "brands": ["Gamm"], "strength": None, "form": None},
]


@pytest.fixture
def catalog():
    return Catalog("test-1", "synthetic test fixture", ENTRIES)


def ids(result):
    return [c["id"] for c in result["candidates"]]


# ---- no choice is ever made

def test_every_result_requires_review_and_has_no_selected_drug(catalog):
    for name in ("SYNTH-GAMMA", "Brandone", "SYNTH-ALPHX", "nothing", ""):
        result = match(name, catalog, suggestion_floor=0.3, max_suggestions=5)
        assert result["review_required"] is True
        assert "selected" not in result and "chosen" not in result


def test_the_written_name_strength_and_form_are_kept_verbatim_and_never_filled_in(catalog):
    result = match("  SYNTH-gamma ", catalog)
    assert result["written"] == "  SYNTH-gamma " and result["written_strength"] is None and result["written_form"] is None
    assert result["status"] == "exact" and result["candidates"][0]["strength"] is None  # the catalog's value, shown, not applied


# ---- exact matching and safe normalisation

def test_a_generic_name_matches_exactly_after_safe_normalisation(catalog):
    assert match("synth-gamma", catalog)["status"] == "exact"
    assert match("SYNTH-GAMMA ", catalog)["status"] == "exact"  # no-break space collapses with the rest
    assert match("  Synth-Gamma  ", catalog)["candidates"][0]["matched_on"] == "generic"


def test_a_brand_name_matches_exactly(catalog):
    result = match("gamm", catalog)
    assert result["status"] == "exact" and ids(result) == ["S4"] and result["candidates"][0]["matched_on"] == "brand"


def test_normalisation_does_not_fix_spelling_or_merge_similar_names(catalog):
    assert match("SYNTH-GAMA", catalog)["status"] == "unrecognised"  # one letter off is not a match
    assert drugmatch.normalize("SYNTH-ALPHA") != drugmatch.normalize("SYNTH-ALPHB")


def test_bangla_digits_are_normalised_in_strengths():
    book = Catalog("t", "s", [{"id": "A", "generic": "X", "strength": "500 mg", "form": None}])
    assert match("x", book, strength="৫০০mg")["status"] == "exact"


# ---- ambiguity: never resolved silently

def test_a_name_shared_by_several_entries_is_ambiguous_and_lists_all_of_them(catalog):
    result = match("Brandone", catalog)
    assert result["status"] == "ambiguous" and result["reason"] == "multiple_entries" and ids(result) == ["S1", "S2"]


def test_the_generic_shared_by_two_strengths_is_ambiguous(catalog):
    assert ids(match("SYNTH-ALPHA", catalog)) == ["S1", "S2"]


def test_a_written_strength_narrows_but_only_by_equality(catalog):
    assert ids(match("Brandone", catalog, strength="10mg")) == ["S1"]
    assert match("Brandone", catalog, strength="20 MG")["status"] == "exact"
    assert match("Brandone", catalog, strength="20 mg", form="tablet")["status"] == "exact"


def test_a_strength_that_matches_no_entry_is_ambiguous_with_every_name_match_never_resolved(catalog):
    result = match("Brandone", catalog, strength="15 mg")
    assert result["status"] == "ambiguous" and result["reason"] == "attribute_mismatch" and ids(result) == ["S1", "S2"]


def test_a_written_form_that_conflicts_is_never_overridden(catalog):
    result = match("SYNTH-ALPHB", catalog, form="tablet")
    assert result["status"] == "ambiguous" and ids(result) == ["S3"]


def test_a_missing_strength_is_not_inferred_from_the_only_remaining_candidate(catalog):
    result = match("SYNTH-ALPHB", catalog)  # a single entry: exact on the name, strength still unwritten
    assert result["status"] == "exact" and result["written_strength"] is None


# ---- unrecognised and suggestions

def test_an_unknown_name_is_unrecognised_and_kept_visible(catalog):
    result = match("Totally Unknown", catalog)
    assert result["status"] == "unrecognised" and result["candidates"] == [] and result["written"] == "Totally Unknown"


def test_empty_or_non_text_names_are_unrecognised_with_a_reason(catalog):
    assert match("   ", catalog)["reason"] == "empty" and match(None, catalog)["status"] == "unrecognised"


def test_no_similar_name_suggestions_without_explicit_parameters(catalog):
    assert match("SYNTH-ALPHX", catalog)["candidates"] == []


def test_look_alike_names_are_suggested_together_never_a_single_silent_pick(catalog):
    result = match("SYNTH-ALPHX", catalog, suggestion_floor=0.4, max_suggestions=5)
    assert result["status"] == "suggested" and result["reason"] == "similar_names"
    assert {"S1", "S2", "S3"} <= set(ids(result))
    scores = [c["score"] for c in result["candidates"]]
    assert scores == sorted(scores, reverse=True) and all(0.4 <= s <= 1 for s in scores)


def test_the_suggestion_limit_and_floor_are_applied(catalog):
    assert len(match("SYNTH-ALPHX", catalog, suggestion_floor=0.4, max_suggestions=2)["candidates"]) == 2
    assert match("SYNTH-ALPHX", catalog, suggestion_floor=1.0, max_suggestions=5)["status"] == "unrecognised"


@pytest.mark.parametrize("kwargs", [{"suggestion_floor": 0.5}, {"max_suggestions": 3},
                                    {"suggestion_floor": 0, "max_suggestions": 3},
                                    {"suggestion_floor": 1.5, "max_suggestions": 3},
                                    {"suggestion_floor": True, "max_suggestions": 3},
                                    {"suggestion_floor": 0.5, "max_suggestions": 0},
                                    {"suggestion_floor": 0.5, "max_suggestions": 2.5}])
def test_suggestion_parameters_have_no_defaults_and_are_validated(catalog, kwargs):
    with pytest.raises(ValueError):
        match("x", catalog, **kwargs)


# ---- determinism and provenance

def test_results_do_not_depend_on_the_order_of_the_catalog_entries(catalog):
    shuffled = Catalog("test-1", "synthetic test fixture", list(reversed(ENTRIES)))
    for name in ("Brandone", "SYNTH-ALPHX", "gamm"):
        a = match(name, catalog, suggestion_floor=0.3, max_suggestions=4)
        b = match(name, shuffled, suggestion_floor=0.3, max_suggestions=4)
        assert a == b


def test_every_result_carries_the_catalog_version_and_source(catalog):
    assert match("gamm", catalog)["catalog"] == {"version": "test-1", "source": "synthetic test fixture"}
    assert match("nothing", catalog)["catalog"]["version"] == "test-1"


@pytest.mark.parametrize("version, source, entries", [
    ("", "s", ENTRIES), ("v", " ", ENTRIES), ("v", "s", [{"id": "A"}]),
    ("v", "s", [{"id": "A", "generic": "x"}, {"id": "A", "generic": "y"}]),
    ("v", "s", [{"id": "A", "generic": "x", "brands": [""]}]),
    ("v", "s", [{"id": "A", "generic": "x", "strength": 5}])])
def test_an_invalid_catalog_is_refused(version, source, entries):
    with pytest.raises(ValueError):
        Catalog(version, source, entries)


def test_match_requires_a_catalog_object():
    with pytest.raises(ValueError):
        match("x", ENTRIES)


def test_similarity_is_symmetric_bounded_and_one_for_equal_names():
    assert drugmatch.similarity("abc", "ABC") == 1.0
    assert drugmatch.similarity("abcd", "abxd") == drugmatch.similarity("abxd", "abcd")
    assert 0 <= drugmatch.similarity("abc", "xyz") < 1


# ---- review fixes: a gap inside a number is not removed; unstated attributes are reported, never filled in

def test_a_space_inside_a_number_is_not_removed_when_comparing_strengths(catalog):
    for written in ("1 0 mg", "1 00 mg"):
        result = match("Brandone", catalog, strength=written)  # an OCR gap must not become a match for 10 mg
        assert result["status"] == "ambiguous" and result["reason"] == "attribute_mismatch"
    assert match("Brandone", catalog, strength="10  mg")["status"] == "exact"  # a space before the unit still equals none


def test_an_exact_match_lists_the_attributes_the_written_text_did_not_state(catalog):
    assert match("SYNTH-ALPHB", catalog)["unconfirmed"] == ["strength", "form"]
    assert match("SYNTH-ALPHB", catalog, strength="5 mg")["unconfirmed"] == ["form"]
    assert match("SYNTH-ALPHB", catalog, strength="5 mg", form="syrup")["unconfirmed"] == []
    assert match("gamm", catalog)["unconfirmed"] == []  # the entry has no strength or form to confirm
    assert match("nothing", catalog)["unconfirmed"] == [] and match("Brandone", catalog)["unconfirmed"] == []
