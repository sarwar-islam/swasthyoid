"""Phase 7B: drug-name candidates in the extraction pipeline, without a database (docs/DECISIONS.md "Phase 7B"). The real
`_attempt` runs against a fake connection with the engine and storage patched. The catalog is a synthetic fixture. Opt-in:
nothing happens unless the worker was given a catalog, and nothing is selected, verified or written into a schema field."""
import io

import pytest

from swasthyoid.capture import documents, drugmatch, extraction, extraction_crypto
from swasthyoid.tests.evaluation import catalog_benchmark
from swasthyoid.tests.test_extraction_lease import Conn, world  # noqa: F401
from swasthyoid.workers import extract as worker

CANARY = "CANARY-BRAND-8f21"
BOOK = drugmatch.Catalog("v1", "synthetic test catalog", [
    {"id": "C1", "generic": "SYNTH-PARA", "brands": [CANARY], "strength": "500 mg", "form": "Synth Tablet", "manufacturer": "Maker A"},
    {"id": "C2", "generic": "SYNTH-PARA", "brands": ["Otherbrand"], "strength": "500 mg", "form": "Synth Tablet"},
])


def row(text, confidence=0.99):
    return {"name_as_written": {"value": text, "confidence": confidence}}


@pytest.fixture
def stored(world, monkeypatch):  # noqa: F811
    """Runs one attempt and returns the fields that would have been stored."""
    def run(medications, doc_type="prescription", **options):
        world.job["doc_type"] = doc_type
        monkeypatch.setattr(extraction, "_run_engine", lambda *a: {
            "engine": "fake", "raw_text": "", "fields": {"medications": medications}})
        saved = []
        monkeypatch.setattr(extraction, "_store", lambda conn, doc, version, name, fields, raw, config=None, preprocessing=None:
                            saved.append(fields))
        world.options = extraction._settings(options)
        world.run(Conn(world.events))
        (fields,) = saved
        return fields
    return run


# ---- the pipeline hook

def test_without_a_catalog_nothing_is_added(stored):
    assert "catalog_matches" not in stored([row(CANARY)])


def test_with_a_catalog_each_medication_row_gets_candidates_and_the_catalogs_provenance(stored):
    fields = stored([row(f"Tab. {CANARY} 500 mg twice daily"), row("nothing known here")], catalog=BOOK)
    matches = fields["catalog_matches"]
    assert matches["catalog"] == {"version": "v1", "source": "synthetic test catalog"}
    first, second = matches["rows"]
    assert (first["row"], first["status"], first["review_required"]) == (0, "candidates", True)
    candidate = first["matches"][0]["candidates"][0]
    assert (candidate["id"], candidate["strength_check"], candidate["form_check"]) == ("C1", "confirmed", "unconfirmed")
    assert (second["row"], second["status"], second["matches"]) == (1, "unrecognised", [])


def test_the_candidates_never_enter_a_schema_field_or_a_selection(stored):
    fields = stored([row(CANARY)], catalog=BOOK)
    medication = fields["medications"][0]
    assert set(medication) == set(extraction.SCHEMAS["prescription"]["medications"][0]) and "catalog" not in str(medication)
    assert medication["name_as_written"]["value"] == CANARY  # the reading is untouched, nothing was filled in
    assert medication["strength"]["value"] is None and medication["strength"]["manual_entry"] is True
    blob = str(fields["catalog_matches"])
    assert "selected" not in blob and "verified" not in blob and "recommended" not in blob
    assert extraction.missing_required(extraction.SCHEMAS["prescription"], fields) == []


def test_a_row_below_the_threshold_is_still_matched_on_its_reading(stored):
    fields = stored([row(CANARY, confidence=0.1)], catalog=BOOK)
    assert fields["medications"][0]["name_as_written"]["value"] is None  # not accepted: left for manual entry
    assert fields["catalog_matches"]["rows"][0]["matches"][0]["candidates"][0]["id"] == "C1"


@pytest.mark.parametrize("doc_type, expected", [("prescription", True), ("discharge_summary", True), ("lab_report", False), ("other", False)])
def test_only_documents_with_medication_rows_are_matched(stored, doc_type, expected):
    assert ("catalog_matches" in stored([row(CANARY)] if expected else [], doc_type=doc_type, catalog=BOOK)) is expected


def test_a_document_without_medication_rows_records_that_matching_ran_and_found_nothing_to_match(stored):
    assert stored([], catalog=BOOK)["catalog_matches"] == {"catalog": BOOK.provenance(), "rows": []}


def test_an_empty_reading_is_skipped(stored):
    assert stored([row("   ")], catalog=BOOK)["catalog_matches"]["rows"] == []


def test_a_matching_failure_is_recorded_by_code_only_and_the_extraction_still_succeeds(stored, monkeypatch):
    def broken(text, catalog):
        raise RuntimeError("synthetic message that must not be kept: " + text)

    monkeypatch.setattr(drugmatch, "match_row", broken)
    fields = stored([row(CANARY)], catalog=BOOK)
    assert fields["catalog_matches"]["rows"] == [{"row": 0, "status": "unavailable"}]
    assert "synthetic message" not in str(fields["catalog_matches"])


def test_the_option_must_be_a_catalog_or_none():
    assert extraction._settings({})["catalog"] is None and extraction._settings({"catalog": BOOK})["catalog"] is BOOK
    for bad in ("medicine.csv", {"entries": []}, 5):
        with pytest.raises(TypeError):
            extraction._settings({"catalog": bad})


def test_the_matches_are_stored_inside_the_sealed_fields_and_not_in_plain_form(stored):
    fields = stored([row(CANARY)], catalog=BOOK)
    sealed = extraction_crypto.seal_fields(fields)
    # (a two-letter id like "C1" is not checked: it could appear by chance inside a random token)
    assert CANARY not in str(sealed) and "catalog_matches" not in str(sealed) and "Synth Tablet" not in str(sealed)
    assert extraction_crypto.open_fields(sealed)["catalog_matches"] == fields["catalog_matches"]


def test_manual_entry_has_no_matches():
    fields = extraction.structure(extraction.SCHEMAS["prescription"], {}, extraction.CONFIDENCE_THRESHOLD)
    assert "catalog_matches" not in fields


# ---- worker configuration: off unless set; set means it must work (fail closed)

def synthetic_file(tmp_path, name="medicine.csv", rows=40):
    path = tmp_path / name
    path.write_text(catalog_benchmark.synthetic_csv(rows, seed=1), encoding="utf-8", newline="")
    return str(path)


def test_no_path_means_no_catalog():
    assert worker.load_catalog({}) is None and worker.load_catalog({"DRUG_CATALOG_SOURCE": "ignored without a path"}) is None


def test_a_valid_synthetic_file_loads_with_its_source_and_a_hash_version(tmp_path):
    catalog = worker.load_catalog({"DRUG_CATALOG_PATH": synthetic_file(tmp_path), "DRUG_CATALOG_SOURCE": "owner-stated source"})
    assert isinstance(catalog, drugmatch.Catalog) and catalog.source == "owner-stated source" and catalog.version.startswith("sha256:")
    named = worker.load_catalog({"DRUG_CATALOG_PATH": synthetic_file(tmp_path), "DRUG_CATALOG_SOURCE": "s", "DRUG_CATALOG_VERSION": "2026-11"})
    assert named.version == "2026-11"


@pytest.mark.parametrize("env, expected", [
    ({"DRUG_CATALOG_PATH": ""}, ("DRUG_CATALOG_PATH", "empty")),
    ({"DRUG_CATALOG_PATH": "relative/medicine.csv", "DRUG_CATALOG_SOURCE": "s"}, ("DRUG_CATALOG_PATH", "not_absolute")),
    ({"DRUG_CATALOG_SOURCE": None}, ("DRUG_CATALOG_SOURCE", "missing")),
    ({"DRUG_CATALOG_SOURCE": "   "}, ("DRUG_CATALOG_SOURCE", "missing")),
    ({"DRUG_CATALOG_VERSION": " "}, ("DRUG_CATALOG_VERSION", "empty")),
])
def test_a_bad_setting_is_refused_with_a_fixed_word(tmp_path, env, expected):
    full = {"DRUG_CATALOG_PATH": synthetic_file(tmp_path), "DRUG_CATALOG_SOURCE": "s", **env}
    full = {k: v for k, v in full.items() if v is not None}
    with pytest.raises(ValueError) as problem:
        worker.load_catalog(full)
    assert problem.value.args == (expected,)


def test_an_unreadable_wrongly_named_or_unusable_file_is_refused_without_naming_it(tmp_path):
    base = {"DRUG_CATALOG_SOURCE": "s"}
    cases = [(str(tmp_path / "missing" / "medicine.csv"), "unreadable"), (synthetic_file(tmp_path, "generic.csv"), "wrong_file")]
    bad = tmp_path / "bad.csv"
    bad.write_bytes(b"brand id,brand name\n1,\xff\xfe\n")
    cases.append((str(bad), "not_utf8"))
    headerless = tmp_path / "other.csv"
    headerless.write_text("id,name\n1,x\n", encoding="utf-8")
    cases.append((str(headerless), "missing_column"))
    for path, reason in cases:
        with pytest.raises(ValueError) as problem:
            worker.load_catalog({**base, "DRUG_CATALOG_PATH": path})
        assert problem.value.args == (("DRUG_CATALOG_PATH", reason),) and path not in repr(problem.value)


def run_main(monkeypatch, capsys, env, argv=("--once",)):
    for name in ("DRUG_CATALOG_PATH", "DRUG_CATALOG_SOURCE", "DRUG_CATALOG_VERSION"):
        monkeypatch.delenv(name, raising=False)
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic:synthetic@localhost/synthetic")
    code = worker.main(list(argv))
    return code, capsys.readouterr().err


def test_a_bad_catalog_setting_exits_2_before_any_connection_and_names_only_the_setting_and_a_word(monkeypatch, capsys):
    monkeypatch.setattr(worker.db, "connect_worker", lambda: pytest.fail("connected before the configuration was checked"))
    code, err = run_main(monkeypatch, capsys, {"DRUG_CATALOG_PATH": "relative/synthetic-secret-path.csv"})
    assert code == 2 and "code=invalid_configuration setting=DRUG_CATALOG_PATH reason=not_absolute" in err
    assert "synthetic-secret-path" not in err
    code, err = run_main(monkeypatch, capsys, {"DRUG_CATALOG_PATH": "/abs/medicine.csv"})
    assert code == 2 and "setting=DRUG_CATALOG_SOURCE reason=missing" in err


def test_the_worker_passes_the_catalog_to_the_cycle_only_when_one_is_configured(monkeypatch, capsys, tmp_path):
    class Connection:
        def close(self):
            pass

    seen = []
    monkeypatch.setattr(worker.db, "connect_worker", lambda: Connection())
    monkeypatch.setattr(worker, "missing_schema", lambda conn: [])
    monkeypatch.setattr(worker, "serve", lambda conn, **kw: seen.append(kw) or 0)
    assert run_main(monkeypatch, capsys, {})[0] == 0
    assert "run" not in seen[-1]  # unset: the ordinary cycle, exactly as before
    env = {"DRUG_CATALOG_PATH": synthetic_file(tmp_path), "DRUG_CATALOG_SOURCE": "s"}
    assert run_main(monkeypatch, capsys, env)[0] == 0
    assert isinstance(seen[-1]["run"].keywords["catalog"], drugmatch.Catalog) and seen[-1]["run"].func is extraction.run_due


def test_the_catalog_never_reaches_the_ocr_child():
    import inspect
    assert "catalog" not in inspect.getsource(extraction._child) and "catalog" not in inspect.getsource(extraction._run_engine)
