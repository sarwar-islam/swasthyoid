"""Evaluation harness (tests/evaluation/harness.py): scoring checked against hand-computed values,
determinism, and ground-truth and split integrity. Synthetic data only; no model."""
import copy

import pytest

from swasthyoid.tests.evaluation import generate, harness


@pytest.fixture(scope="module")
def dataset():
    return generate.build(seed=2, patients=8)


def oracle(dataset):
    truth = {d["id"]: d["truth"]["items"] for d in dataset["documents"]}
    return lambda document: {"items": [dict(item) for item in truth[document["id"]]]}


def counts(dataset, split):
    docs = [d for d in dataset["documents"] if d["split"] == split]
    return len(docs), sum(len(d["truth"]["items"]) for d in docs)


def test_a_perfect_predictor_scores_100_percent_everywhere(dataset):
    report = harness.run(dataset, oracle(dataset))
    sections = [report["printed"]] + list(report["degraded"].values())
    for section in sections:
        for score in section.values():
            assert score["overall"]["precision"] == score["overall"]["recall"] == score["overall"]["f1"] == 1.0
            assert all(rate["f1"] == 1.0 for rate in score["fields"].values())
            assert score["errors"] == {"missed": 0, "wrong_or_extra": 0}


def test_a_predictor_with_one_wrong_field_scores_the_hand_computed_values(dataset):
    truth = oracle(dataset)

    def wrong_drug(document):
        return {"items": [{**item, "drug": "WRONG"} for item in truth(document)["items"]]}

    docs, items = counts(dataset, "held_out")
    score = harness.run(dataset, wrong_drug, include_copies=False)["printed"]["held_out"]
    assert score["fields"]["drug"] == {"true_positive": 0, "predicted": items, "expected": items,
                                       "precision": 0.0, "recall": 0.0, "f1": 0.0}
    assert score["fields"]["dose"]["f1"] == score["fields"]["frequency"]["f1"] == 1.0
    assert score["overall"]["true_positive"] == 2 * items and score["overall"]["predicted"] == 3 * items
    assert score["overall"]["precision"] == pytest.approx(2 / 3) and score["overall"]["f1"] == pytest.approx(2 / 3)
    assert score["errors"] == {"missed": items, "wrong_or_extra": items}


def test_a_predictor_that_drops_the_last_item_of_each_document_loses_recall_only(dataset):
    truth = oracle(dataset)
    docs, items = counts(dataset, "development")
    score = harness.run(dataset, lambda d: {"items": truth(d)["items"][:-1]}, include_copies=False)["printed"]["development"]
    assert score["overall"]["precision"] == 1.0
    assert score["overall"]["recall"] == pytest.approx((items - docs) / items)
    assert score["errors"] == {"missed": 3 * docs, "wrong_or_extra": 0}


def test_a_predictor_that_returns_nothing_has_no_precision_and_zero_recall(dataset):
    score = harness.run(dataset, lambda d: {"items": []}, include_copies=False)["printed"]["held_out"]
    assert score["overall"]["precision"] is None and score["overall"]["f1"] is None
    assert score["overall"]["recall"] == 0.0


def test_the_predictor_is_given_the_image_and_id_and_never_the_ground_truth(dataset):
    seen = []
    harness.run(dataset, lambda d: seen.append(set(d)) or {"items": []})
    assert seen and all(keys == {"id", "image"} for keys in seen)


def test_results_are_reported_per_split_per_field_and_per_degradation(dataset):
    report = harness.run(dataset, oracle(dataset))
    assert set(report["printed"]) == {"development", "held_out"}
    assert set(report["degraded"]) == set(generate.DEGRADATIONS)
    assert all(set(v) == {"development", "held_out"} for v in report["degraded"].values())
    assert set(report["printed"]["held_out"]["fields"]) == set(harness.FIELDS)


def test_the_report_is_reproducible_byte_for_byte(dataset):
    first = harness.to_json(harness.run(dataset, oracle(dataset)))
    again = harness.to_json(harness.run(generate.build(seed=2, patients=8), oracle(dataset)))
    assert first == again


# ---- ground-truth and split integrity

def test_an_unchanged_dataset_matches_its_manifest_and_a_rebuild_does_too(dataset):
    stored = harness.manifest(dataset)
    assert harness.verify(dataset, stored) == []
    assert harness.verify(generate.build(seed=2, patients=8), stored) == []


def test_a_changed_ground_truth_value_is_detected(dataset):
    stored = harness.manifest(dataset)
    tampered = copy.deepcopy(dataset)
    tampered["documents"][0]["truth"]["items"][0]["dose"] = "CHANGED"
    problems = harness.verify(tampered, stored)
    assert problems == [f"document {tampered['documents'][0]['id']} changed, added or removed"]


def test_a_changed_image_or_a_moved_split_is_detected(dataset):
    stored = harness.manifest(dataset)
    changed = copy.deepcopy(dataset)
    changed["documents"][0]["sha256"] = "0" * 64
    changed["documents"][1]["split"] = "held_out" if changed["documents"][1]["split"] == "development" else "development"
    assert len(harness.verify(changed, stored)) == 2


def test_a_copy_of_an_unknown_document_is_reported(dataset):
    stored = harness.manifest(dataset)
    leaked = copy.deepcopy(dataset)
    leaked["copies"][0]["document_id"] = "SYNTH-RX-UNKNOWN"
    assert any("unknown document" in problem for problem in harness.verify(leaked, stored))


def test_every_degraded_copy_stays_in_its_source_documents_split(dataset):
    split = {d["id"]: d["split"] for d in dataset["documents"]}
    report = harness.run(dataset, oracle(dataset))
    development = sum(1 for c in dataset["copies"] if split[c["document_id"]] == "development")
    held_out = len(dataset["copies"]) - development
    scored = {name: sum(v[name]["overall"]["expected"] > 0 for v in report["degraded"].values())
              for name in ("development", "held_out")}
    assert development and held_out and scored == {"development": 5, "held_out": 5}


# ---- confidence analysis (9A mechanism): the threshold is an argument, results are hand-computed

def with_confidence(dataset, levels, wrong_field=None):
    truth = oracle(dataset)

    def predictor(document):
        out = []
        for item in truth(document)["items"]:
            item = dict(item)
            if wrong_field:
                item[wrong_field] = "WRONG"
            item["confidence"] = dict(levels)
            out.append(item)
        return {"items": out}

    return predictor


def test_values_below_the_threshold_go_to_manual_entry_and_are_not_counted_as_accepted(dataset):
    docs, items = counts(dataset, "held_out")
    levels = {"drug": 0.95, "dose": 0.40, "frequency": 0.90}
    report = harness.run(dataset, with_confidence(dataset, levels), include_copies=False, threshold=0.85)
    held = report["confidence"]["held_out"]
    assert held == {"accepted": 2 * items, "accepted_wrong": 0, "manual_entry": items,
                    "accepted_but_wrong_rate": 0.0}


def test_a_confident_wrong_value_is_counted_as_accepted_but_wrong(dataset):
    docs, items = counts(dataset, "held_out")
    levels = {"drug": 0.99, "dose": 0.99, "frequency": 0.99}
    report = harness.run(dataset, with_confidence(dataset, levels, wrong_field="drug"), include_copies=False, threshold=0.85)
    held = report["confidence"]["held_out"]
    assert held["accepted"] == 3 * items and held["accepted_wrong"] == items
    assert held["accepted_but_wrong_rate"] == pytest.approx(1 / 3) and held["manual_entry"] == 0


def test_a_value_with_no_usable_confidence_is_never_accepted(dataset):
    report = harness.run(dataset, oracle(dataset), include_copies=False, threshold=0.5)  # the oracle gives none
    held = report["confidence"]["held_out"]
    assert held["accepted"] == 0 and held["accepted_but_wrong_rate"] is None and held["manual_entry"] > 0


def test_the_confidence_section_exists_only_when_a_threshold_is_given(dataset):
    assert "confidence" not in harness.run(dataset, oracle(dataset), include_copies=False)


# ---- text-level metrics (CER, WER, rates), hand-computed

def test_edit_distance_on_strings_and_word_lists():
    assert harness.edit_distance("kitten", "sitting") == 3
    assert harness.edit_distance(["a", "b"], ["a", "c", "d"]) == 2 and harness.edit_distance("", "abc") == 3


def test_cer_and_wer_of_one_pair():
    assert harness.cer("abcd", "abxd") == 0.25 and harness.cer("abcd", "abcd") == 0.0
    assert harness.cer("ab", "") == 1.0 and harness.cer("", "abc") is None
    assert harness.wer("a b c", "a x c") == pytest.approx(1 / 3) and harness.wer("a b", "a b c") == 0.5
    assert harness.wer("", "x") is None


def test_normalisation_is_nfc_and_whitespace_only():
    assert harness.cer("\u09cb", "\u09c7\u09be") == 0.0  # the composed and decomposed Bengali vowel sign are the same text
    assert harness.cer("a  b\n c", "a b c") == 0.0
    assert harness.cer("\u0964", ".") == 1.0  # nothing else is folded: danda is not a full stop


def test_the_corpus_report_micro_averages_and_counts_failures_and_empty_outputs_separately():
    samples = [{"reference": "abcd", "hypothesis": "abxd", "seconds": 1.0, "peak_memory_bytes": 100},
               {"reference": "hello world", "hypothesis": "hello world", "seconds": 3.0},
               {"reference": "gone", "hypothesis": ""},
               {"reference": "lost", "hypothesis": None}]
    report = harness.text_report(samples)
    assert (report["samples"], report["failed"], report["failure_rate"]) == (4, 1, 0.25)
    assert report["empty_output_rate"] == pytest.approx(1 / 3) and report["exact_match_rate"] == pytest.approx(1 / 3)
    assert report["cer"] == pytest.approx((1 + 0 + 4) / (4 + 11 + 4))  # edits over total reference characters, failures excluded
    assert report["wer"] == pytest.approx((1 + 0 + 1) / (1 + 2 + 1))
    assert (report["mean_seconds"], report["max_seconds"], report["max_peak_memory_bytes"]) == (2.0, 3.0, 100)


def test_an_empty_corpus_has_no_rates_and_unmeasured_fields_stay_none():
    report = harness.text_report([])
    assert report["samples"] == 0 and report["cer"] is None and report["failure_rate"] is None
    only = harness.text_report([{"reference": "a", "hypothesis": "a"}])
    assert only["mean_seconds"] is None and only["max_peak_memory_bytes"] is None and only["cer"] == 0.0


def test_a_corpus_of_only_failures_reports_the_failure_rate_and_no_cer():
    report = harness.text_report([{"reference": "a", "hypothesis": None}])
    assert report["failure_rate"] == 1.0 and report["cer"] is None and report["empty_output_rate"] is None


def test_scoring_refuses_anything_that_is_not_text():
    for call in (lambda: harness.normalize_text(5), lambda: harness.cer(None, "x"), lambda: harness.wer("a", 3),
                 lambda: harness.text_report([{"reference": None, "hypothesis": "x"}]),
                 lambda: harness.text_report([{"reference": "a", "hypothesis": 7}]),
                 lambda: harness.text_report(["not a sample"])):
        with pytest.raises(ValueError):
            call()


def test_an_insertion_against_an_empty_reference_is_an_edit_and_an_all_empty_corpus_has_no_cer():
    mixed = harness.text_report([{"reference": "abcd", "hypothesis": "abcd"}, {"reference": "", "hypothesis": "xy"}])
    assert mixed["cer"] == pytest.approx(2 / 4)  # two insertions over four reference characters
    assert harness.text_report([{"reference": "", "hypothesis": "xy"}])["cer"] is None  # nothing to divide by
