"""Step 5A (capture/imaging.py) and step 3A-data (tests/evaluation/generate.py).

Synthetic images only. The limits in imaging.LIMITS are provisional; the measured relations here
are sanity checks and a report, not pass marks (those are D11).
"""
import io
import json

import pytest
from PIL import Image

from swasthyoid.capture import imaging
from swasthyoid.tests.evaluation import generate


@pytest.fixture(scope="module")
def dataset():
    return generate.build(seed=1)


def clean(dataset, n=0):
    return dataset["documents"][n]["png"]


# ---- decoding and refusal

def test_a_clean_page_decodes_and_is_not_refused(dataset):
    assert imaging.check(clean(dataset)) == []


@pytest.mark.parametrize("data", [b"", b"\xff\xd8\xff\xe0 not really a jpeg", b"plain text", b"\x89PNG\r\n\x1a\n" + b"x" * 40])
def test_files_that_do_not_decode_are_rejected_with_a_fixed_code(data):
    with pytest.raises(imaging.ImageRejected) as refused:
        imaging.check(data)
    assert refused.value.args == ("image_undecodable",)


def test_a_truncated_image_is_rejected(dataset):
    with pytest.raises(imaging.ImageRejected):
        imaging.decode(clean(dataset)[:200])


def test_an_unsupported_format_is_rejected():
    buffer = io.BytesIO()
    Image.new("L", (700, 700), 200).save(buffer, format="BMP")
    with pytest.raises(imaging.ImageRejected) as refused:
        imaging.decode(buffer.getvalue())
    assert refused.value.args == ("image_unsupported",)


def test_the_pixel_cap_is_checked_from_the_header_before_decoding(monkeypatch):
    buffer = io.BytesIO()
    Image.new("L", (3000, 3000), 200).save(buffer, format="PNG")  # a few KB that expand to 9 million pixels
    monkeypatch.setattr(imaging, "MAX_PIXELS", 1_000_000)
    with pytest.raises(imaging.ImageRejected) as refused:
        imaging.decode(buffer.getvalue())
    assert refused.value.args == ("image_too_large",)


def test_a_small_image_is_flagged_not_rejected():
    buffer = io.BytesIO()
    Image.new("L", (200, 200), 200).save(buffer, format="JPEG")
    assert "image_too_small" in imaging.check(buffer.getvalue())


def test_checking_does_not_change_the_bytes(dataset):
    data = clean(dataset)
    before = bytes(data)
    imaging.check(data)
    assert data == before


# ---- measurements on the labelled degraded set (a report, not pass marks)

def metrics(dataset):
    return {(c["degradation"], c["amount"]): imaging.measure(c["png"]) for c in dataset["copies"]
            if c["document_id"] == dataset["documents"][0]["id"]}


def test_blur_lowers_sharpness_and_glare_raises_the_blown_out_share(dataset):
    base, degraded = imaging.measure(clean(dataset)), metrics(dataset)
    assert base["glare"] == 0.0
    for amount in generate.AMOUNTS["blur"]:
        assert degraded[("blur", amount)]["sharpness"] < base["sharpness"]
    assert degraded[("blur", 5)]["sharpness"] < degraded[("blur", 2)]["sharpness"]
    for amount in generate.AMOUNTS["glare"]:
        assert degraded[("glare", amount)]["glare"] > base["glare"]


def test_detection_report_on_the_degraded_set(dataset):
    """Prints nothing and asserts only the shape: the rates are for the owner (D11 sets pass marks)."""
    report = {"clean_refused": 0, "clean": 0}
    for doc in dataset["documents"]:
        report["clean"] += 1
        report["clean_refused"] += bool(imaging.check(doc["png"]))
    for kind in ("blur", "glare"):
        flagged = [bool(imaging.check(c["png"])) for c in dataset["copies"] if c["degradation"] == kind]
        report[kind] = sum(flagged) / len(flagged)
    assert set(report) == {"clean_refused", "clean", "blur", "glare"}
    assert report["clean_refused"] == 0  # the provisional limits do not refuse the clean synthetic pages
    assert report["blur"] > 0 and report["glare"] > 0  # and they catch something


# ---- the generator

def test_same_seed_gives_identical_ground_truth_and_image_hashes():
    a, b = generate.build(seed=3), generate.build(seed=3)
    assert [d["sha256"] for d in a["documents"]] == [d["sha256"] for d in b["documents"]]
    assert [c["sha256"] for c in a["copies"]] == [c["sha256"] for c in b["copies"]]
    assert json.dumps([d["truth"] for d in a["documents"]]) == json.dumps([d["truth"] for d in b["documents"]])
    assert generate.build(seed=4)["documents"][0]["sha256"] != a["documents"][0]["sha256"]


def test_development_and_held_out_splits_are_disjoint_and_complete(dataset):
    development = {d["id"] for d in dataset["documents"] if d["split"] == "development"}
    held_out = {d["id"] for d in dataset["documents"] if d["split"] == "held_out"}
    assert development and held_out and not development & held_out
    assert development | held_out == {d["id"] for d in dataset["documents"]}


def test_every_degraded_copy_records_its_type_amount_and_source(dataset):
    ids = {d["id"] for d in dataset["documents"]}
    assert len(dataset["copies"]) == len(ids) * sum(len(a) for a in generate.AMOUNTS.values())
    for copy in dataset["copies"]:
        assert copy["document_id"] in ids and copy["degradation"] in generate.DEGRADATIONS
        assert copy["amount"] in generate.AMOUNTS[copy["degradation"]]


def test_the_ground_truth_holds_only_synthetic_placeholders(dataset):
    for doc in dataset["documents"]:
        assert doc["truth"]["synthetic"] is True
        for item in doc["truth"]["items"]:
            assert item["drug"].startswith("SYNTH-DRUG-")
            assert item["dose"] == "PLACEHOLDER-DOSE" and item["frequency"] == "PLACEHOLDER-FREQUENCY"
