"""Phase 7B (docs/DECISIONS.md "Phase 7B"): the catalog's name index, generic-level groups, and matching names inside the free
text of one written row. Synthetic names only. The row rules are PROVISIONAL (D8, the clinical reviewer owns them): exact
normalised phrase windows, no similarity, no abbreviation expansion, never a selection."""
from types import MappingProxyType

import pytest

from swasthyoid.capture import drugmatch
from swasthyoid.capture.drugmatch import MAX_ROW_CANDIDATES, Catalog, match, match_row

ENTRIES = [
    {"id": "B1", "generic": "SYNTH-PARA", "brands": ["Synthnapa"], "strength": "500 mg", "form": "Synth Tablet", "manufacturer": "Maker A"},
    {"id": "B2", "generic": "SYNTH-PARA", "brands": ["Synthnapa Extra"], "strength": "665 mg", "form": "Synth Tablet", "manufacturer": "Maker A"},
    {"id": "B3", "generic": "SYNTH-PARA", "brands": ["Otherbrand"], "strength": "500 mg", "form": "Synth Tablet", "manufacturer": "Maker B"},
    {"id": "B4", "generic": "SYNTH-IBU", "brands": ["Ibubrand"], "strength": None, "form": None},
    {"id": "B5", "generic": "SYNTH-IBU (Nasal Preparation)", "brands": [], "strength": "0.05 %", "form": "Synth Spray"},
]


@pytest.fixture
def book():
    return Catalog("t1", "synthetic test fixture", ENTRIES)


def ids(result):
    return [c["id"] for c in result["candidates"]]


def reference_ids(book, name):
    """What a full scan finds: the ids of every entry that has this name as its generic or one of its brands."""
    key = drugmatch.normalize(name)
    return sorted(e["id"] for e in book.entries
                  if drugmatch.normalize(e["generic"] or "") == key or any(drugmatch.normalize(b) == key for b in e["brands"]))


# ---- the index

def test_the_index_finds_exactly_what_a_full_scan_finds_for_every_name_in_the_catalog(book):
    for entry in ENTRIES:
        for name in [entry["generic"], *entry["brands"]]:
            found = match(name, book)
            every_id = sorted({i for c in found["candidates"] for i in c.get("ids", [c["id"]])})
            assert every_id == reference_ids(book, name), name


def test_the_index_is_read_only_and_keyed_by_the_normalised_name(book):
    assert isinstance(book._by_name, MappingProxyType) and isinstance(book._limits, MappingProxyType)
    assert "synthnapa" in book._by_name and "SYNTHNAPA" not in book._by_name
    with pytest.raises(TypeError):
        book._by_name["x"] = ()
    with pytest.raises(AttributeError):
        book._by_name = {}
    assert book._limits["name"] == 3  # "synth-ibu (nasal preparation)" is the longest name, in words


def test_lookups_do_not_depend_on_how_the_name_is_cased_or_spaced(book):
    assert ids(match("  sYnThNaPa  ", book)) == ["B1"] and ids(match("synthnapa   extra", book)) == ["B2"]


# ---- generic-level groups

def test_a_generic_shared_by_many_records_comes_back_as_groups_with_every_id_kept(book):
    result = match("SYNTH-PARA", book)
    assert (result["status"], result["reason"]) == ("ambiguous", "multiple_entries") and ids(result) == ["B1", "B2"]
    first, second = result["candidates"]
    assert first["kind"] == "generic_group" and first["ids"] == ["B1", "B3"] and (first["strength"], first["form"]) == ("500 mg", "Synth Tablet")
    assert (first["brand_count"], first["manufacturer_count"]) == (2, 2) and second["ids"] == ["B2"]
    assert result["review_required"] is True and "selected" not in result


def test_one_generic_strength_and_form_with_several_records_is_still_not_exact():
    book = Catalog("t", "s", [{"id": str(n), "generic": "SYNTH-G", "brands": [f"Brand{n}"], "strength": "5 mg", "form": "Synth Tablet"}
                              for n in range(3)])
    result = match("SYNTH-G", book)
    assert (result["status"], result["reason"]) == ("ambiguous", "generic_name") and result["candidates"][0]["ids"] == ["0", "1", "2"]


def test_a_written_strength_narrows_the_groups_by_equality_only(book):
    assert ids(match("SYNTH-PARA", book, strength="665mg")) == ["B2"]
    result = match("SYNTH-PARA", book, strength="500 mg")
    assert ids(result) == ["B1"] and result["candidates"][0]["ids"] == ["B1", "B3"] and result["reason"] == "generic_name"


def test_a_generic_of_one_record_is_exact_as_before(book):
    result = match("SYNTH-IBU", book)
    assert result["status"] == "exact" and ids(result) == ["B4"] and "ids" not in result["candidates"][0]


def test_a_route_qualifier_keeps_the_names_apart(book):
    assert ids(match("SYNTH-IBU (Nasal Preparation)", book)) == ["B5"] and ids(match("SYNTH-IBU", book)) == ["B4"]


def test_a_name_that_is_one_records_generic_and_anothers_brand_returns_both_kinds():
    book = Catalog("t", "s", [{"id": "1", "generic": "SYNTH-DUAL"}, {"id": "2", "generic": "SYNTH-OTHER", "brands": ["Synth-Dual"]}])
    result = match("synth-dual", book)
    assert sorted((c["id"], c["matched_on"]) for c in result["candidates"]) == [("1", "generic"), ("2", "brand")]


# ---- matching inside the text of one row

def found(text, book, **kw):
    return match_row(text, book, **kw)


def only(result):
    (m,) = result["matches"]
    return m


def test_a_brand_in_a_written_row_is_found_and_its_strength_is_confirmed_by_the_text(book):
    result = found("Tab. Synthnapa 500 mg twice daily", book)
    assert result["status"] == "candidates" and result["review_required"] is True and result["truncated"] == 0
    m = only(result)
    assert (m["phrase"], m["status"]) == ("synthnapa", "exact") and ids(m) == ["B1"]
    c = m["candidates"][0]
    assert (c["strength_check"], c["form_check"]) == ("confirmed", "unconfirmed")  # "Synth Tablet" is not written
    assert (c["kind"], c["matched_on"], c["manufacturer"], c["brands"]) == ("record", "brand", "Maker A", ["Synthnapa"])


def test_the_longest_name_wins_and_a_name_inside_it_is_not_reported_separately(book):
    m = only(found("Synthnapa Extra 665 mg", book))
    assert (m["phrase"], ids(m)) == ("synthnapa extra", ["B2"])


def test_two_names_in_one_row_are_both_reported_in_text_order(book):
    result = found("Ibubrand then Otherbrand 500 mg", book)
    assert [m["phrase"] for m in result["matches"]] == ["ibubrand", "otherbrand"]


def test_a_comma_or_full_stop_after_a_word_is_ignored_but_other_punctuation_is_not(book):
    assert ids(only(found("Synthnapa, 500 mg.", book))) == ["B1"]
    assert found("(Synthnapa) 500 mg", book)["status"] == "unrecognised"  # a bracket is part of the word: no guessing


def test_a_strength_the_catalog_lacks_is_marked_missing_and_a_different_written_strength_is_unconfirmed_not_dropped(book):
    assert only(found("Ibubrand 200 mg", book))["candidates"][0]["strength_check"] == "catalog_missing"
    c = only(found("Synthnapa 250 mg", book))["candidates"][0]
    assert ids(only(found("Synthnapa 250 mg", book))) == ["B1"] and c["strength_check"] == "unconfirmed"


def test_bangla_digits_and_a_missing_space_do_not_stop_a_strength_from_being_confirmed(book):
    assert only(found("Synthnapa ৫০০ mg", book))["candidates"][0]["strength_check"] == "confirmed"
    assert only(found("Synthnapa 500mg", book))["candidates"][0]["strength_check"] == "confirmed"


def test_a_form_is_confirmed_only_when_written_in_full_and_an_abbreviation_is_not_expanded(book):
    assert only(found("Synthnapa 500 mg Synth Tablet", book))["candidates"][0]["form_check"] == "confirmed"
    assert only(found("Synthnapa 500 mg tab", book))["candidates"][0]["form_check"] == "unconfirmed"


def test_a_generic_in_a_row_gives_groups_each_checked_against_the_text(book):
    m = only(found("SYNTH-PARA 500 mg", book))
    checks = {tuple(c["ids"]): c["strength_check"] for c in m["candidates"]}
    assert checks == {("B1", "B3"): "confirmed", ("B2",): "unconfirmed"} and m["status"] == "ambiguous"


def test_nothing_in_the_catalog_is_unrecognised_and_nothing_is_filled_in(book):
    result = found("Totally unknown 5 mg", book)
    assert result == {"status": "unrecognised", "review_required": True, "matches": [], "truncated": 0}
    assert found(None, book)["status"] == "unrecognised" and found("   ", book)["matches"] == []


def test_no_result_ever_selects_verifies_or_recommends(book):
    for text in ("Synthnapa 500 mg", "SYNTH-PARA", "Ibubrand", "unknown"):
        result = found(text, book)
        assert result["review_required"] is True and not {"selected", "chosen", "verified", "recommended", "best"} & set(result)
        for m in result["matches"]:
            assert not {"selected", "verified", "recommended", "score"} & set(m)
            assert all(not {"selected", "verified", "recommended", "score"} & set(c) for c in m["candidates"])


def test_the_same_row_gives_the_same_result_and_the_candidates_are_copies(book):
    first = found("Synthnapa 500 mg", book)
    assert first == found("Synthnapa 500 mg", book)
    first["matches"][0]["candidates"][0]["brands"].append("Injected")
    assert found("Synthnapa 500 mg", book)["matches"][0]["candidates"][0]["brands"] == ["Synthnapa"]


def test_the_candidates_per_row_are_capped_and_the_rest_are_counted():
    book = Catalog("t", "s", [{"id": f"{n:03d}", "generic": f"SYNTH-G{n}", "brands": ["Samebrand"], "strength": f"{n} mg"}
                              for n in range(MAX_ROW_CANDIDATES + 10)])
    result = match_row("Samebrand", book)
    assert sum(len(m["candidates"]) for m in result["matches"]) == MAX_ROW_CANDIDATES and result["truncated"] == 10
    small = match_row("Samebrand", book, max_candidates=3)
    assert sum(len(m["candidates"]) for m in small["matches"]) == 3 and small["truncated"] == MAX_ROW_CANDIDATES + 7


def test_a_catalog_is_required(book):
    with pytest.raises(ValueError):
        match_row("Synthnapa", {"entries": []})


def test_match_row_uses_no_similarity_and_no_alias_machinery():
    import ast
    import inspect
    import textwrap
    names = set()
    for function in (match_row, drugmatch._row_candidate):
        for node in ast.walk(ast.parse(textwrap.dedent(inspect.getsource(function)))):
            if isinstance(node, ast.Name):
                names.add(node.id)
            elif isinstance(node, ast.Attribute):
                names.add(node.attr)
    assert not {"similarity", "_trigrams", "suggestion_floor", "max_suggestions"} & names
    assert not any("alias" in n.lower() or "abbrev" in n.lower() for n in names)
