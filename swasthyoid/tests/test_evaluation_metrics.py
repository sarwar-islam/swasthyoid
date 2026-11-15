"""Phase 9A metric gaps: whole-row precision and recall, the manual-entry rate, the quality gate's false refusals, latency
percentiles, resource readings, the handwritten and Bangla gates, and the OCR baseline command (with the FAKE PaddleOCR
runner only: no real model runs in pytest). Raw numbers only; nothing here is a pass mark (D11). Synthetic data only."""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from swasthyoid.tests.evaluation import generate, harness, ocr_baseline

REPO = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="module")
def dataset():
    return generate.build(seed=3, patients=8)


def oracle(dataset):
    truth = {d["id"]: d["truth"]["items"] for d in dataset["documents"]}
    return lambda document: {"items": [dict(item) for item in truth[document["id"]]]}


def counts(dataset, split):
    docs = [d for d in dataset["documents"] if d["split"] == split]
    return len(docs), sum(len(d["truth"]["items"]) for d in docs)


# ---- whole rows

def test_a_perfect_predictor_gets_every_whole_row(dataset):
    for score in harness.run(dataset, oracle(dataset), include_copies=False)["printed"].values():
        assert score["rows"]["precision"] == score["rows"]["recall"] == 1.0


def test_one_wrong_field_makes_every_row_wrong_while_two_fields_of_three_still_count(dataset):
    truth = oracle(dataset)
    _, items = counts(dataset, "held_out")
    score = harness.run(dataset, lambda d: {"items": [{**i, "dose": "WRONG"} for i in truth(d)["items"]]},
                        include_copies=False)["printed"]["held_out"]
    assert score["rows"] == {"true_positive": 0, "predicted": items, "expected": items,
                             "precision": 0.0, "recall": 0.0, "f1": 0.0}
    assert score["overall"]["precision"] == pytest.approx(2 / 3)


def test_rows_are_matched_regardless_of_position_but_fields_are_not(dataset):
    truth = oracle(dataset)
    score = harness.run(dataset, lambda d: {"items": truth(d)["items"][::-1]}, include_copies=False)["printed"]["held_out"]
    assert score["rows"]["precision"] == score["rows"]["recall"] == 1.0
    multi = any(len(d["truth"]["items"]) > 1 for d in dataset["documents"] if d["split"] == "held_out")
    assert (score["overall"]["precision"] < 1.0) == multi  # positional field tuples break when the order changes


def test_a_dropped_row_costs_recall_and_a_partial_row_is_not_a_row(dataset):
    truth = oracle(dataset)
    docs, items = counts(dataset, "development")
    dropped = harness.run(dataset, lambda d: {"items": truth(d)["items"][:-1]}, include_copies=False)["printed"]["development"]
    assert dropped["rows"]["precision"] == 1.0 and dropped["rows"]["recall"] == pytest.approx((items - docs) / items)
    partial = harness.run(dataset, lambda d: {"items": [{"drug": i["drug"], "dose": i["dose"]} for i in truth(d)["items"]]},
                          include_copies=False)["printed"]["development"]
    assert partial["rows"]["true_positive"] == 0 and partial["rows"]["predicted"] == items


# ---- the manual-entry rate

def test_without_confidence_every_expected_field_is_left_for_manual_entry(dataset):
    held = harness.run(dataset, oracle(dataset), include_copies=False, threshold=0.5)["confidence"]["held_out"]
    _, items = counts(dataset, "held_out")
    assert (held["expected_fields"], held["left_for_manual_entry"], held["manual_entry_rate"]) == (3 * items, 3 * items, 1.0)


def test_an_accepted_wrong_value_is_prefilled_not_left_for_manual_entry(dataset):
    truth = oracle(dataset)

    def confident_but_wrong(document):
        return {"items": [{**i, "drug": "WRONG", "confidence": {"drug": 0.9, "dose": 0.9, "frequency": 0.1}}
                          for i in truth(document)["items"]]}

    held = harness.run(dataset, confident_but_wrong, include_copies=False, threshold=0.5)["confidence"]["held_out"]
    _, items = counts(dataset, "held_out")
    assert held["left_for_manual_entry"] == items and held["accepted_wrong"] == items  # frequency typed; drug pre-filled wrong


def test_the_predictor_is_called_once_per_image(dataset):
    calls = []
    truth = oracle(dataset)
    harness.run(dataset, lambda d: calls.append(d["id"]) or truth(d), include_copies=False, threshold=0.5)
    assert sorted(calls) == sorted(d["id"] for d in dataset["documents"])


# ---- distributions

def test_nearest_rank_percentiles_by_hand():
    values = [5, 1, 4, 2, 3, 10, 9, 8, 7, 6]
    assert (harness.percentile(values, 50), harness.percentile(values, 95), harness.percentile(values, 100)) == (5, 10, 10)
    assert harness.percentile([7], 50) == 7 and harness.percentile([], 50) is None
    for bad in (0, -1, 101):
        with pytest.raises(ValueError):
            harness.percentile(values, bad)


def test_latency_report_ignores_non_numbers_and_is_none_when_empty():
    assert harness.latency_report([2.0, 1.0, True, None, 4.0]) == {
        "samples": 3, "p50_seconds": 2.0, "p95_seconds": 4.0, "max_seconds": 4.0, "mean_seconds": 7 / 3}
    assert harness.latency_report([])["p50_seconds"] is None


# ---- the quality gate on synthetic pages

def test_the_clean_false_refusal_rate_is_the_share_of_clean_pages_refused(dataset):
    gate = harness.quality_gate_report(dataset)
    clean = gate["clean"]
    assert clean["pages"] == len(dataset["documents"]) and clean["false_refusal_rate"] == clean["refused"] / clean["pages"]
    assert set(gate["degraded"]) == set(generate.DEGRADATIONS)
    for kind, amounts in gate["degraded"].items():
        assert set(amounts) == {str(a) for a in generate.AMOUNTS[kind]}
        assert all(entry["pages"] == len(dataset["documents"]) for entry in amounts.values())


def test_the_gate_report_uses_the_limits_given_and_names_the_reasons(dataset):
    refuse_all = {"min_side": 10 ** 6}
    gate = harness.quality_gate_report(dataset, refuse_all)
    assert gate["clean"]["false_refusal_rate"] == 1.0 and gate["clean"]["reasons"]["image_too_small"] == len(dataset["documents"])
    assert gate["limits"]["min_side"] == 10 ** 6


# ---- what is not evaluated

@pytest.mark.parametrize("language, handwritten, word", [("en", True, "D3"), ("bn", False, "font"), ("hi", False, "hi")])
def test_handwritten_and_other_languages_are_refused_never_generated(language, handwritten, word):
    with pytest.raises(generate.NotAvailable) as pending:
        generate.build(seed=0, patients=1, language=language, handwritten=handwritten)
    assert word in pending.value.args[0]


# ---- the baseline command

def test_the_layout_reader_builds_items_with_line_confidences():
    lines = [("SYNTHETIC PRESCRIPTION X", 0.9), ("Drug: A", 0.9), ("Dose: 1", 0.8), ("Frequency: f", None),
             ("Drug: B", 0.7), ("Drug:", 0.9), ("Noise without label", 1.0), ("Dose: 2", 0.6), ("Dose: 3", 0.5)]
    assert ocr_baseline.read_layout(lines) == [
        {"drug": "A", "dose": "1", "frequency": "f", "confidence": {"drug": 0.9, "dose": 0.8}},
        {"drug": "B", "dose": "2", "confidence": {"drug": 0.7, "dose": 0.6}},
        {"dose": "3", "confidence": {"dose": 0.5}}]


def test_the_reference_text_is_what_render_prints(dataset):
    doc = dataset["documents"][0]
    text = ocr_baseline.reference_text(doc["truth"]).splitlines()
    assert text[0] == f"SYNTHETIC PRESCRIPTION {doc['id']}" and len(text) == 1 + 3 * len(doc["truth"]["items"])


@pytest.mark.parametrize("argv, code", [(["--language", "bn"], "not_available"), (["--handwritten"], "not_available")])
def test_the_command_refuses_pending_sets(tmp_path, capsys, argv, code):
    assert ocr_baseline.main(["--out", str(tmp_path / "r.json"), *argv]) == ocr_baseline.EXIT_USAGE
    assert f"code={code}" in capsys.readouterr().err and not (tmp_path / "r.json").exists()


def test_the_command_refuses_to_write_inside_the_repository_or_over_a_file(tmp_path, capsys):
    assert ocr_baseline.main(["--out", str(REPO / "docs" / "baseline.json")]) == ocr_baseline.EXIT_USAGE
    existing = tmp_path / "r.json"
    existing.write_text("keep")
    assert ocr_baseline.main(["--out", str(existing)]) == ocr_baseline.EXIT_USAGE
    err = capsys.readouterr().err
    assert "code=out_inside_repository" in err and "code=out_exists" in err and existing.read_text() == "keep"


def test_the_command_needs_an_available_adapter(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv("OCR_ADAPTER", raising=False)
    assert ocr_baseline.main(["--out", str(tmp_path / "r.json")]) == ocr_baseline.EXIT_UNAVAILABLE
    assert "code=engine_unavailable" in capsys.readouterr().err and not (tmp_path / "r.json").exists()


def test_the_command_end_to_end_with_the_fake_runner_writes_metrics_and_no_ocr_text(tmp_path):
    out = tmp_path / "baseline.json"
    env = {**os.environ, "APP_ENV": "test", "SWASTHYOID_TEST_MODE_CONFIRM": "1",
           "OCR_ADAPTER": "swasthyoid.tests.adapters.fake_paddleocr:paddleocr_en"}
    env.pop("OCR_ADAPTERS_APPROVED", None)
    done = subprocess.run([sys.executable, "-m", "swasthyoid.tests.evaluation.ocr_baseline", "--out", str(out),
                           "--patients", "2", "--seed", "1"], cwd=REPO, env=env, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr
    text = out.read_text(encoding="utf-8")
    report = json.loads(text)
    assert report["engine"]["engine_id"] == "paddleocr-en" and report["engine"]["approved_entry"] is False
    assert report["dataset"]["documents"] == 2 and report["dataset"]["copies_read"] == 0
    assert report["latency"]["printed"]["samples"] == 2 and report["failures"] == {"pages": 2, "failed": 0, "codes": {}}
    assert report["text"]["samples"] == 2 and report["text"]["cer"] > 0  # the fake reads unrelated synthetic lines
    assert report["fields"]["printed"]["held_out"]["rows"]["recall"] == 0.0
    assert report["resources"]["kind"] in (None, "windows_job_peak_process_commit", "posix_rusage_max_rss")
    assert set(report["not_evaluated"]) == {"handwritten", "bn"} and "pass" in report["not_a_pass_mark"]
    assert report["settings"]["paddleocr_enable_mkldnn"] is (os.environ.get("PADDLEOCR_ENABLE_MKLDNN") == "1")
    for line in ("Tab. Synthetic", "second row", "third row"):  # the fake runner's text never reaches the report
        assert line not in text


def test_the_resource_meter_sees_a_child_process_memory():
    done = subprocess.run([sys.executable, "-m", "swasthyoid.tests.evaluation.resources", str(200_000_000)],
                          cwd=REPO, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stderr
    readings = json.loads(done.stdout)
    if readings["after"]["kind"] is None:
        pytest.skip("this platform gives no resource reading")
    assert readings["after"]["peak_memory_bytes"] >= 200_000_000
    assert readings["after"]["cpu_seconds"] >= readings["before"]["cpu_seconds"]
