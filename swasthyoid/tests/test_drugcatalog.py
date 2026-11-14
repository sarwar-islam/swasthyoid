"""D8 Phase A: the in-memory drug reference catalog loader (capture/drugcatalog.py) on SYNTHETIC data only.

Every fixture below is invented text in the shape of the supplied medicine.csv. No test reads data/ or needs the
local CSV files, so none of them depends on those files being present in CI. They show how the loader keeps
original values, keeps ambiguity, and never selects a candidate; they say nothing about any real medicine."""
import ast
import dataclasses
import hashlib
import io
import subprocess
from pathlib import Path

import pytest

from swasthyoid.capture import drugcatalog, drugmatch
from swasthyoid.capture.drugcatalog import CatalogError, load_csv, load_medicine_csv
from swasthyoid.capture.drugmatch import match

HEADER = "brand id,brand name,generic,strength,dosage form,manufacturer,package container,Package Size"


def csv_text(*rows, header=HEADER, eol="\n"):
    return eol.join([header, *rows]) + eol


def load(*rows, **kw):
    return load_csv(io.StringIO(csv_text(*rows, **kw), newline=""), source="synthetic test data", version="t1")


def ids(result):
    return [c["id"] for c in result["candidates"]]


# ---- valid loading and original values

def test_a_valid_file_loads_into_records_and_a_read_only_catalog():
    loaded = load("101,Alpha,SYNTH-GENERIC-A,500 mg,Tablet,Maker One,x,y", "102,Beta,SYNTH-GENERIC-B,10 mg/5 ml,Syrup,Maker Two,x,y")
    assert [r.source_id for r in loaded.records] == ["101", "102"]
    assert (loaded.report.rows, loaded.report.matchable) == (2, 2) and loaded.report.unmatchable == ()
    assert loaded.catalog.provenance() == {"version": "t1", "source": "synthetic test data"}
    assert [e["id"] for e in loaded.catalog.entries] == ["101", "102"]
    assert match("Alpha", loaded.catalog)["candidates"][0]["manufacturer"] == "Maker One"


def test_original_values_are_kept_exactly_as_written():
    loaded = load("7,  Alpha  ,Synth-Generic (Nasal Preparation),(10 mg+30 mg+1.25 mg)/5 ml,Capsule (Sustained Release),MAKER one Ltd.,x,y")
    (record,) = loaded.records
    assert (record.brand, record.generic, record.strength, record.form, record.manufacturer) == (
        "  Alpha  ", "Synth-Generic (Nasal Preparation)", "(10 mg+30 mg+1.25 mg)/5 ml", "Capsule (Sustained Release)", "MAKER one Ltd.")
    (entry,) = loaded.catalog.entries
    assert entry["brands"] == ("  Alpha  ",) and entry["generic"] == record.generic and entry["strength"] == record.strength


def test_a_quoted_cell_with_a_line_break_is_kept_as_written():
    loaded = load('9,"Brand\r\nTwo",SYNTH-G,5 mg,Tablet,Maker,x,y')
    assert loaded.records[0].brand == "Brand\r\nTwo"


def test_crlf_files_and_a_byte_order_mark_load_and_the_file_is_not_modified(tmp_path):
    path = tmp_path / "medicine.csv"
    data = ("﻿" + csv_text("1,Alpha,SYNTH-G,5 mg,Tablet,Maker,x,y", eol="\r\n")).encode("utf-8")
    path.write_bytes(data)
    loaded = load_medicine_csv(path, source="synthetic")
    assert loaded.records[0].brand == "Alpha"
    assert path.read_bytes() == data  # the loader only reads
    assert loaded.file_sha256 == hashlib.sha256(data).hexdigest()
    assert loaded.catalog.version == f"sha256:{loaded.file_sha256}"  # a changed file is a different version


def test_an_explicit_version_is_used_and_the_hash_is_still_recorded(tmp_path):
    path = tmp_path / "medicine.csv"
    path.write_bytes(csv_text("1,Alpha,SYNTH-G,5 mg,Tablet,Maker,x,y").encode("utf-8"))
    loaded = load_medicine_csv(path, source="owner-stated source", version="2026-11-14 snapshot")
    assert loaded.catalog.version == "2026-11-14 snapshot" and len(loaded.file_sha256) == 64


# ---- only the six approved columns are kept

def test_every_other_column_is_discarded_including_prices_links_and_clinical_text():
    header = HEADER + ",monograph link,dosage description,indication description"
    loaded = load("1,Alpha,SYNTH-G,5 mg,Tablet,Maker,100 ml bottle: ৳ 40.12,(5's pack: ৳ 142.15),http://x.invalid/a,TAKE 2 DAILY,FOR DISEASE X",
                  header=header)
    assert {f.name for f in dataclasses.fields(loaded.records[0])} == {"source_id", "brand", "generic", "strength", "form", "manufacturer"}
    everything = repr(loaded.records) + repr(loaded.catalog.entries) + repr(match("Alpha", loaded.catalog))
    for foreign in ("৳", "x.invalid", "TAKE 2 DAILY", "DISEASE X", "100 ml bottle"):
        assert foreign not in everything


def test_a_file_in_the_shape_of_the_clinical_generic_list_is_refused():
    header = "generic id,generic name,slug,dosage description,indication description"
    with pytest.raises(CatalogError) as refused:
        load("1,SYNTH-G,synth-g,TAKE 2,FOR X", header=header)
    assert refused.value.args == ("missing_column",)


# ---- missing values stay missing

@pytest.mark.parametrize("row, field", [("1,,SYNTH-G,5 mg,Tablet,Maker", "brand"), ("1,Alpha,,5 mg,Tablet,Maker", "generic"),
                                        ("1,Alpha,SYNTH-G,,Tablet,Maker", "strength"), ("1,Alpha,SYNTH-G,5 mg,,Maker", "form"),
                                        ("1,Alpha,SYNTH-G,5 mg,Tablet,", "manufacturer")])
def test_a_missing_value_stays_missing_and_is_counted(row, field):
    loaded = load(row + ",x,y")
    assert getattr(loaded.records[0], field) is None
    assert loaded.report.missing_count(field) == 1 and sum(n for _, n in loaded.report.missing) == 1
    assert loaded.report.matchable == 1


def test_whitespace_only_cells_count_as_missing_and_are_reported_apart():
    loaded = load("1,Alpha,SYNTH-G,   ,Tablet,Maker,x,y")
    assert loaded.records[0].strength is None
    assert dict(loaded.report.whitespace_only)["strength"] == 1 and loaded.report.missing_count("strength") == 1


def test_a_record_without_a_brand_matches_by_its_generic_only_and_never_gets_a_brand_filled_in():
    loaded = load("1,,SYNTH-G,5 mg,Tablet,Maker,x,y")
    result = match("SYNTH-G", loaded.catalog)
    assert result["status"] == "exact" and result["candidates"][0]["brands"] == []
    assert match("Alpha", loaded.catalog)["status"] == "unrecognised"


def test_a_record_without_a_generic_matches_by_its_brand_only_and_never_gets_a_generic_filled_in():
    loaded = load("1,Alpha,,5 mg,Tablet,Maker,x,y")
    result = match("Alpha", loaded.catalog)
    assert result["status"] == "exact" and result["candidates"][0]["generic"] is None
    assert match("SYNTH-G", loaded.catalog)["status"] == "unrecognised"


def test_a_missing_strength_is_reported_as_unconfirmed_and_never_inferred():
    loaded = load("1,Alpha,SYNTH-G,,Tablet,Maker,x,y")
    result = match("Alpha", loaded.catalog)
    assert result["candidates"][0]["strength"] is None  # nothing is filled in for the strength the catalog lacks
    assert result["unconfirmed"] == ["form"]  # only what the catalog HAS and the text did not state is listed
    unconfirmed = match("Alpha", loaded.catalog, strength="5 mg")  # a written strength cannot be confirmed by a missing one
    assert (unconfirmed["status"], unconfirmed["reason"], unconfirmed["unconfirmed"]) == ("ambiguous", "attribute_unconfirmed", ["strength"])
    assert ids(unconfirmed) == ["1"] and unconfirmed["candidates"][0]["unconfirmed"] == ["strength"]  # kept, never dropped


def test_a_record_with_neither_a_brand_nor_a_generic_is_kept_but_cannot_match():
    loaded = load("1,,,5 mg,Tablet,Maker,x,y", "2,Alpha,SYNTH-G,5 mg,Tablet,Maker,x,y")
    assert [r.source_id for r in loaded.records] == ["1", "2"]
    assert loaded.report.unmatchable == ("1",) and [e["id"] for e in loaded.catalog.entries] == ["2"]


# ---- duplicates and ambiguity are kept, never resolved

def test_duplicate_records_are_kept_reported_and_returned_as_separate_candidates():
    loaded = load("1,Alpha,SYNTH-G,5 mg,Tablet,Maker,x,y", "2,Alpha,SYNTH-G,5 mg,Tablet,Maker,x,y", "3,Other,SYNTH-H,1 mg,Tablet,Maker,x,y")
    assert loaded.report.duplicate_groups == (("1", "2"),) and len(loaded.records) == 3
    result = match("Alpha", loaded.catalog)
    assert result["status"] == "ambiguous" and result["reason"] == "multiple_entries" and ids(result) == ["1", "2"]


def test_records_equal_only_after_case_and_spacing_are_reported_as_near_duplicates_and_kept_as_written():
    loaded = load("1,Alpha,SYNTH-G,5 mg,Tablet,Maker,x,y", "2,ALPHA ,synth-g,5 mg,Tablet,Maker,x,y")
    assert loaded.report.duplicate_groups == () and loaded.report.near_duplicate_groups == (("1", "2"),)
    assert [r.brand for r in loaded.records] == ["Alpha", "ALPHA "]


def test_one_brand_with_different_generics_is_ambiguous_and_never_resolved():
    loaded = load("1,Alpha,SYNTH-G-ONE,5 mg,Tablet,Maker,x,y", "2,alpha,SYNTH-G-TWO,5 mg,Tablet,Maker,x,y")
    assert loaded.report.brands_with_several_generics == (("1", "2"),)
    result = match("ALPHA", loaded.catalog)
    assert result["status"] == "ambiguous" and ids(result) == ["1", "2"]
    assert {c["generic"] for c in result["candidates"]} == {"SYNTH-G-ONE", "SYNTH-G-TWO"}


def test_the_same_product_from_several_manufacturers_stays_several_candidates_with_their_manufacturers():
    loaded = load("1,Alpha,SYNTH-G,5 mg,Tablet,Maker One,x,y", "2,Alpha,SYNTH-G,5 mg,Tablet,Maker Two,x,y")
    assert loaded.report.products_with_several_manufacturers == (("1", "2"),) and loaded.report.duplicate_groups == ()
    result = match("Alpha", loaded.catalog, strength="5 mg", form="Tablet")  # even with strength and form written
    assert result["status"] == "ambiguous" and [c["manufacturer"] for c in result["candidates"]] == ["Maker One", "Maker Two"]


def test_one_brand_in_several_strengths_is_ambiguous_until_a_matching_strength_is_written():
    loaded = load("1,Alpha,SYNTH-G,5 mg,Tablet,Maker,x,y", "2,Alpha,SYNTH-G,10 mg,Tablet,Maker,x,y")
    assert match("Alpha", loaded.catalog)["status"] == "ambiguous"
    assert ids(match("Alpha", loaded.catalog, strength="10 mg")) == ["2"]


# ---- combination strengths and route qualifiers are not normalised away

def test_combination_strengths_are_kept_whole_and_compared_only_by_equality():
    text = "(10 mg+30 mg+1.25 mg)/5 ml"
    loaded = load(f'1,Alpha,SYNTH-A + SYNTH-B + SYNTH-C,"{text}",Syrup,Maker,x,y')
    assert loaded.records[0].strength == text and loaded.records[0].generic == "SYNTH-A + SYNTH-B + SYNTH-C"
    assert match("Alpha", loaded.catalog, strength=text)["status"] == "exact"
    reordered = match("Alpha", loaded.catalog, strength="(30 mg+10 mg+1.25 mg)/5 ml")  # no reordering, no splitting
    assert reordered["status"] == "ambiguous" and reordered["reason"] == "attribute_mismatch"
    assert match("Alpha", loaded.catalog, strength="10 mg")["reason"] == "attribute_mismatch"  # a component is not the product


def test_route_qualifiers_are_kept_and_the_bare_name_is_not_treated_as_the_same_medicine():
    loaded = load("1,Alpha,SYNTH-G (Nasal Preparation),0.05 %,Spray,Maker,x,y", "2,Beta,SYNTH-G (Cream),0.05 %,Cream,Maker,x,y")
    assert [r.generic for r in loaded.records] == ["SYNTH-G (Nasal Preparation)", "SYNTH-G (Cream)"]
    assert match("SYNTH-G", loaded.catalog)["status"] == "unrecognised"  # the qualifier is not stripped to make a match
    assert ids(match("SYNTH-G (Nasal Preparation)", loaded.catalog)) == ["1"]
    assert ids(match("synth-g  (cream)", loaded.catalog)) == ["2"]


# ---- unknown names and no automatic selection

def test_unknown_and_unmatched_names_are_unrecognised_and_kept_verbatim():
    loaded = load("1,Alpha,SYNTH-G,5 mg,Tablet,Maker,x,y")
    for name in ("Totally Unknown", "Alph", "", "   "):
        result = match(name, loaded.catalog)
        assert result["status"] == "unrecognised" and result["candidates"] == [] and result["written"] == name


def test_no_result_ever_selects_a_candidate_or_claims_verification():
    loaded = load("1,Alpha,SYNTH-G,5 mg,Tablet,Maker One,x,y", "2,Alpha,SYNTH-G,5 mg,Tablet,Maker Two,x,y",
                  "3,Gamma,SYNTH-H,1 mg,Tablet,Maker One,x,y", "4,Gamme,SYNTH-I,2 mg,Tablet,Maker One,x,y")
    for name in ("Alpha", "Gamma", "Gamma ", "Nothing", "Gam"):
        result = match(name, loaded.catalog, suggestion_floor=0.3, max_suggestions=5)
        assert result["review_required"] is True
        assert not {"selected", "chosen", "verified", "recommended", "best"} & set(result)
        assert not any({"selected", "verified", "recommended"} & set(c) for c in result["candidates"])
    exact = match("Gamma", loaded.catalog)
    assert exact["status"] == "exact" and exact["review_required"] is True  # a name match is still only a candidate


def test_loading_sets_no_threshold_or_similarity_setting_and_suggestions_still_need_explicit_parameters():
    loaded = load("1,Gamma,SYNTH-H,1 mg,Tablet,Maker,x,y")
    assert match("Gamme", loaded.catalog)["candidates"] == []  # no suggestion without the reviewer's parameters
    with pytest.raises(ValueError):
        match("Gamme", loaded.catalog, suggestion_floor=0.5)


def test_results_do_not_depend_on_the_order_of_the_rows():
    rows = ["1,Alpha,SYNTH-G,5 mg,Tablet,Maker One,x,y", "2,Alpha,SYNTH-G,5 mg,Tablet,Maker Two,x,y", "3,Beta,SYNTH-H,1 mg,Syrup,Maker,x,y"]
    a, b = load(*rows), load(*reversed(rows))
    assert match("Alpha", a.catalog) == match("Alpha", b.catalog) and a.report.duplicate_groups == b.report.duplicate_groups


# ---- the loaded data cannot be changed

def test_records_the_catalog_and_its_entries_are_read_only_and_candidates_are_copies():
    loaded = load("1,Alpha,SYNTH-G,5 mg,Tablet,Maker,x,y")
    with pytest.raises(dataclasses.FrozenInstanceError):
        loaded.records[0].brand = "Changed"
    with pytest.raises(dataclasses.FrozenInstanceError):
        loaded.report.rows = 99
    with pytest.raises(AttributeError):
        loaded.catalog.version = "other"
    with pytest.raises(AttributeError):
        loaded.catalog.entries = ()
    with pytest.raises(TypeError):
        loaded.catalog.entries[0]["generic"] = "Changed"
    candidate = match("Alpha", loaded.catalog)["candidates"][0]
    candidate["generic"] = "Changed"
    candidate["brands"].append("Injected")
    assert loaded.catalog.entries[0]["generic"] == "SYNTH-G" and loaded.catalog.entries[0]["brands"] == ("Alpha",)
    assert match("Alpha", loaded.catalog)["candidates"][0]["brands"] == ["Alpha"]


# ---- the file must be usable, or it is refused with a fixed word

@pytest.mark.parametrize("header, reason", [
    ("brand name,generic,strength,dosage form,manufacturer", "missing_column"),                       # no id column
    ("brand id,brand name,generic,strength,dosage form", "missing_column"),                           # no manufacturer
    ("brand id,brand name,generic,strength,dosage form,manufacturer,brand name", "duplicate_column"),
])
def test_a_file_without_the_required_columns_is_refused(header, reason):
    with pytest.raises(CatalogError) as refused:
        load_csv(io.StringIO(header + "\n", newline=""), source="s", version="v")
    assert refused.value.args == (reason,)


@pytest.mark.parametrize("rows, reason", [(["  ,Alpha,SYNTH-G,5 mg,Tablet,Maker,x,y"], "missing_source_id"),
                                          ([",Alpha,SYNTH-G,5 mg,Tablet,Maker,x,y"], "missing_source_id"),
                                          (["1,Alpha,SYNTH-G,5 mg,Tablet,Maker,x,y", "1,Beta,SYNTH-H,1 mg,Tablet,Maker,x,y"], "duplicate_source_id")])
def test_a_blank_or_repeated_source_record_id_is_refused(rows, reason):
    with pytest.raises(CatalogError) as refused:
        load(*rows)
    assert refused.value.args == (reason,)


def test_a_file_that_is_not_utf8_is_refused_without_quoting_it(tmp_path):
    path = tmp_path / "medicine.csv"
    path.write_bytes(b"brand id,brand name\n1,\xff\xfe SECRET-LOOKING TEXT\n")
    with pytest.raises(CatalogError) as refused:
        load_medicine_csv(path, source="s")
    assert refused.value.args == ("not_utf8",) and "SECRET" not in repr(refused.value)


def test_source_and_version_are_required_by_the_catalog():
    with pytest.raises(ValueError):
        load_csv(io.StringIO(csv_text("1,Alpha,SYNTH-G,5 mg,Tablet,Maker,x,y"), newline=""), source=" ", version="v")


# ---- audit corrections: malformed rows, csv errors, reports, file guards

@pytest.mark.parametrize("row", ["1,Alpha,SYNTH-G", "1,Alpha,SYNTH-G,5 mg,Tablet,Maker,x", "1,Alpha,SYNTH-G,5 mg,Tablet,Maker,x,y,EXTRA"])
def test_a_row_with_fewer_or_more_cells_than_the_header_is_refused_not_read_as_missing_values(row):
    with pytest.raises(CatalogError) as refused:
        load(row)
    assert refused.value.args == ("bad_row",) and "Alpha" not in repr(refused.value)


def test_a_completely_empty_line_is_not_a_record_and_is_not_an_error():
    loaded = load("1,Alpha,SYNTH-G,5 mg,Tablet,Maker,x,y", "", "2,Beta,SYNTH-H,1 mg,Tablet,Maker,x,y")
    assert [r.source_id for r in loaded.records] == ["1", "2"]


def test_a_nul_byte_is_refused_without_quoting_the_file():
    with pytest.raises(CatalogError) as refused:
        load("1,Alpha" + chr(0) + "SECRET,SYNTH-G,5 mg,Tablet,Maker,x,y")
    assert refused.value.args == ("nul_byte",) and "SECRET" not in repr(refused.value)


def test_a_cell_too_large_for_the_csv_reader_is_a_safe_catalog_error():
    with pytest.raises(CatalogError) as refused:
        load("1,Alpha," + "A" * 200_000 + ",5 mg,Tablet,Maker,x,y")
    assert refused.value.args == ("bad_csv",) and "AAAA" not in repr(refused.value) and refused.value.__cause__ is None


def test_an_empty_file_is_refused():
    with pytest.raises(CatalogError) as refused:
        load_csv(io.StringIO("", newline=""), source="s", version="v")
    assert refused.value.args == ("missing_column",)


def test_near_duplicates_are_reported_even_when_each_side_is_itself_an_exact_duplicate_group():
    loaded = load("1,Alpha,SYNTH-G,5 mg,Tablet,Maker,x,y", "2,Alpha,SYNTH-G,5 mg,Tablet,Maker,x,y",
                  "3,ALPHA,synth-g,5 mg,Tablet,Maker,x,y", "4,ALPHA,synth-g,5 mg,Tablet,Maker,x,y")
    assert loaded.report.duplicate_groups == (("1", "2"), ("3", "4"))
    assert loaded.report.near_duplicate_groups == (("1", "2", "3", "4"),)
    assert len(loaded.records) == 4  # nothing was merged


def test_a_missing_generic_or_manufacturer_is_not_counted_as_a_conflicting_value():
    loaded = load("1,Alpha,SYNTH-G,5 mg,Tablet,Maker,x,y", "2,Alpha,,5 mg,Tablet,Maker,x,y",
                  "3,Beta,SYNTH-G,5 mg,Tablet,Maker One,x,y", "4,Beta,SYNTH-G,5 mg,Tablet,,x,y")
    assert loaded.report.brands_with_several_generics == () and loaded.report.products_with_several_manufacturers == ()
    assert loaded.report.missing_count("generic") == 1 and loaded.report.missing_count("manufacturer") == 1
    real = load("1,Alpha,SYNTH-G,5 mg,Tablet,Maker,x,y", "2,Alpha,SYNTH-H,5 mg,Tablet,Maker,x,y",
                "3,Beta,SYNTH-G,5 mg,Tablet,Maker One,x,y", "4,Beta,SYNTH-G,5 mg,Tablet,Maker Two,x,y")
    assert real.report.brands_with_several_generics == (("1", "2"),)  # real conflicts are still reported
    assert real.report.products_with_several_manufacturers == (("3", "4"),)


@pytest.mark.parametrize("version", ["", "   "])
def test_an_explicitly_empty_version_is_refused_not_replaced_by_the_hash(tmp_path, version):
    path = tmp_path / "medicine.csv"
    path.write_bytes(csv_text("1,Alpha,SYNTH-G,5 mg,Tablet,Maker,x,y").encode("utf-8"))
    with pytest.raises(CatalogError) as refused:
        load_medicine_csv(path, source="s", version=version)
    assert refused.value.args == ("empty_version",)


@pytest.mark.parametrize("name", ["generic.csv", "Manufacturer.CSV", "dosage form.csv", "drug class.csv", "indication.csv"])
def test_a_file_named_like_one_of_the_other_supplied_files_is_refused_before_it_is_opened(tmp_path, name):
    missing_file = tmp_path / name  # does not exist: a FileNotFoundError would mean the loader tried to open it
    with pytest.raises(CatalogError) as refused:
        load_medicine_csv(missing_file, source="s")
    assert refused.value.args == ("wrong_file",)


def test_a_file_over_the_size_limit_is_refused_before_it_is_read(tmp_path):
    path = tmp_path / "medicine.csv"
    path.write_bytes(csv_text("1,Alpha,SYNTH-G,5 mg,Tablet,Maker,x,y").encode("utf-8"))
    size = path.stat().st_size
    assert load_medicine_csv(path, source="s", max_bytes=size).records  # exactly at the limit is accepted
    with pytest.raises(CatalogError) as refused:
        load_medicine_csv(path, source="s", max_bytes=size - 1)
    assert refused.value.args == ("file_too_large",)
    for bad in (0, -1, True, 1.5, None):
        with pytest.raises(ValueError):
            load_medicine_csv(path, source="s", max_bytes=bad)
    assert isinstance(drugcatalog.MAX_FILE_BYTES, int) and drugcatalog.MAX_FILE_BYTES >= 4 * 1024 * 1024


def test_a_wrongly_shaped_file_with_an_ordinary_name_is_still_refused_by_its_header(tmp_path):
    path = tmp_path / "list.csv"
    path.write_bytes(b"generic id,generic name,dosage description\n1,SYNTH-G,TAKE 2\n")
    with pytest.raises(CatalogError) as refused:
        load_medicine_csv(path, source="s")
    assert refused.value.args == ("missing_column",) and "TAKE" not in repr(refused.value)


# ---- audit corrections: a record that lacks strength or form is never dropped and never "exact"

def test_a_record_with_a_missing_strength_is_not_hidden_by_a_written_strength():
    loaded = load("1,Alpha,SYNTH-G,5 mg,Tablet,Maker,x,y", "2,Alpha,SYNTH-G,,Tablet,Maker,x,y", "3,Alpha,SYNTH-G,10 mg,Tablet,Maker,x,y")
    result = match("Alpha", loaded.catalog, strength="5 mg")
    assert (result["status"], result["reason"]) == ("ambiguous", "multiple_entries")
    assert ids(result) == ["1", "2"]  # the 10 mg record conflicts and is dropped; the one with no strength stays
    by_id = {c["id"]: c for c in result["candidates"]}
    assert by_id["1"]["unconfirmed"] == [] and by_id["2"]["unconfirmed"] == ["strength"] and by_id["2"]["strength"] is None
    assert result["unconfirmed"] == ["strength"] and result["review_required"] is True


def test_a_record_with_a_missing_form_is_kept_and_marked_unconfirmed():
    loaded = load("1,Alpha,SYNTH-G,5 mg,Tablet,Maker,x,y", "2,Alpha,SYNTH-G,5 mg,,Maker,x,y")
    result = match("Alpha", loaded.catalog, strength="5 mg", form="Tablet")
    assert result["status"] == "ambiguous" and ids(result) == ["1", "2"] and result["unconfirmed"] == ["form"]
    assert match("Alpha", loaded.catalog)["status"] == "ambiguous"  # nothing written: both stay, as before


def test_a_single_record_that_cannot_confirm_a_written_attribute_is_never_exact():
    loaded = load("1,Alpha,SYNTH-G,,,Maker,x,y")
    result = match("Alpha", loaded.catalog, strength="5 mg", form="Tablet")
    assert (result["status"], result["reason"], result["unconfirmed"]) == ("ambiguous", "attribute_unconfirmed", ["strength", "form"])
    assert ids(result) == ["1"]
    assert match("Alpha", loaded.catalog)["status"] == "exact"  # nothing was written, so nothing is unconfirmed


def test_a_conflicting_value_still_excludes_a_record_and_all_candidates_return_when_none_fit():
    loaded = load("1,Alpha,SYNTH-G,5 mg,Tablet,Maker,x,y", "2,Alpha,SYNTH-G,,Tablet,Maker,x,y")
    assert ids(match("Alpha", loaded.catalog, strength="10 mg")) == ["2"]  # 1 conflicts; 2 cannot say
    only_conflicts = load("1,Alpha,SYNTH-G,5 mg,Tablet,Maker,x,y")
    result = match("Alpha", only_conflicts.catalog, strength="10 mg")
    assert (result["status"], result["reason"]) == ("ambiguous", "attribute_mismatch") and ids(result) == ["1"]


# ---- boundaries: local, read-only, and kept out of git

def test_the_loader_imports_nothing_that_could_reach_a_network_or_a_database_and_never_writes():
    tree = ast.parse(Path(drugcatalog.__file__).read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name for a in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported |= {f"{node.module}.{a.name}" if node.module == "swasthyoid.capture" else node.module for a in node.names}
    assert imported <= {"csv", "hashlib", "io", "dataclasses", "pathlib", "swasthyoid.capture.drugmatch"}, imported
    calls = [n.func for n in ast.walk(tree) if isinstance(n, ast.Call)]
    assert not {f.id for f in calls if isinstance(f, ast.Name)} & {"open", "exec", "eval", "compile", "__import__", "print"}
    assert not {f.attr for f in calls if isinstance(f, ast.Attribute)} & {
        "open", "write", "write_text", "write_bytes", "unlink", "mkdir", "touch", "rename", "replace", "rmdir"}


def test_git_really_ignores_the_data_directory_and_tracks_nothing_in_it():
    root = Path(__file__).resolve().parents[2]

    def git(*args):
        try:
            return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired):
            pytest.skip("git is not available")

    probe = git("check-ignore", "-q", "data/drug_catalog/medicine.csv")
    if probe.returncode not in (0, 1):
        pytest.skip("not a git work tree")
    assert probe.returncode == 0, "data/ is not ignored by git"
    tracked = git("ls-files", "data")
    assert tracked.returncode == 0 and tracked.stdout.strip() == ""


def test_the_catalog_in_these_tests_is_the_matchers_own_read_only_type():
    assert isinstance(load("1,Alpha,SYNTH-G,5 mg,Tablet,Maker,x,y").catalog, drugmatch.Catalog)
