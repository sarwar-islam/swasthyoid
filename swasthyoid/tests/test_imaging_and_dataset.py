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

_METRICS = {}


def metrics(dataset):
    """Measurements of the first document's degraded copies, computed once per dataset seed."""
    if dataset["seed"] not in _METRICS:
        _METRICS[dataset["seed"]] = {(c["degradation"], c["amount"]): imaging.measure(c["png"])
                                     for c in dataset["copies"] if c["document_id"] == dataset["documents"][0]["id"]}
    return _METRICS[dataset["seed"]]


def test_blur_lowers_sharpness_and_glare_raises_the_blown_out_share(dataset):
    base, degraded = imaging.measure(clean(dataset)), metrics(dataset)
    assert base["glare"] == 0.0
    for amount in generate.AMOUNTS["blur"]:
        assert degraded[("blur", amount)]["sharpness"] < base["sharpness"]
    assert degraded[("blur", 5)]["sharpness"] < degraded[("blur", 2)]["sharpness"]
    for amount in generate.AMOUNTS["glare"]:
        assert degraded[("glare", amount)]["glare"] > base["glare"]


EXPECTED_REASON = {"rotate": "image_skewed", "blur": "image_blurry", "glare": "image_glare",
                   "low_contrast": "image_low_contrast", "noise": None}


def test_the_provisional_limits_on_the_synthetic_degraded_set(dataset):
    """Pins the measured behavior on synthetic pages as a regression check. These are not pass
    marks (D11) and say nothing about real photographs."""
    for doc in dataset["documents"]:
        assert imaging.check(doc["png"]) == []  # no clean page is refused
    for copy in dataset["copies"]:
        reasons = imaging.check(copy["png"])
        expected = EXPECTED_REASON[copy["degradation"]]
        assert (expected in reasons) if expected else reasons == [], (copy["degradation"], copy["amount"], reasons)


def test_noise_is_not_read_as_blur_or_glare_and_skew_is_measured_in_degrees(dataset):
    for amount in generate.AMOUNTS["noise"]:
        m = metrics(dataset)[("noise", amount)]
        assert m["sharpness"] >= imaging.LIMITS["min_sharpness"] and m["glare"] <= imaging.LIMITS["max_glare"]
    for amount in generate.AMOUNTS["rotate"]:
        assert abs(metrics(dataset)[("rotate", amount)]["skew"] - amount) <= 1.0
    assert abs(imaging.measure(clean(dataset))["skew"]) <= 0.5


def test_a_page_without_text_reports_no_skew():
    buffer = io.BytesIO()
    Image.new("L", (700, 700), 225).save(buffer, format="PNG")
    assert imaging.measure(buffer.getvalue())["skew"] == 0.0


# ---- processing copies (step 5B mechanism): the original is only read

def stats(data):
    return imaging.measure(data)


def test_a_processing_copy_leaves_the_original_bytes_untouched(dataset):
    data = dataset["copies"][0]["png"]
    before = (bytes(data), generate.sha256(data))
    imaging.process(data, exif=True, deskew=True, denoise=True, contrast=True)
    assert (data, generate.sha256(data)) == before


def test_with_every_switch_off_the_copy_is_the_grey_image_and_nothing_is_applied(dataset):
    data = clean(dataset)
    copy, applied = imaging.process(data)
    assert applied == [] and (imaging.decode(copy) == imaging.decode(data)).all()


def test_deskew_brings_a_rotated_page_back_within_the_limit(dataset):
    rotated = next(c["png"] for c in dataset["copies"] if c["degradation"] == "rotate" and c["amount"] == 8)
    copy, applied = imaging.process(rotated, deskew=True)
    assert applied == ["deskew"] and abs(stats(copy)["skew"]) <= imaging.LIMITS["max_skew"]


def test_denoise_lowers_the_noise_and_contrast_stretch_raises_the_contrast(dataset):
    noisy = next(c["png"] for c in dataset["copies"] if c["degradation"] == "noise" and c["amount"] == 30)
    smooth, _ = imaging.process(noisy, denoise=True)
    assert imaging.decode(smooth).astype(float).std() < imaging.decode(noisy).astype(float).std()
    faded = next(c["png"] for c in dataset["copies"] if c["degradation"] == "low_contrast" and c["amount"] == 0.3)
    stretched, applied = imaging.process(faded, contrast=True)
    assert applied == ["contrast"] and stats(stretched)["contrast"] > 2 * stats(faded)["contrast"]


def test_exif_orientation_is_applied_only_when_asked():
    image = Image.new("L", (700, 900), 225)  # portrait pixels; orientation 6 says "rotate to landscape"
    exif = Image.Exif()
    exif[0x0112] = 6
    buffer = io.BytesIO()
    image.save(buffer, format="JPEG", exif=exif)
    plain, _ = imaging.process(buffer.getvalue())
    turned, applied = imaging.process(buffer.getvalue(), exif=True)
    assert applied == ["exif"]
    assert Image.open(io.BytesIO(plain)).size == (700, 900) and Image.open(io.BytesIO(turned)).size == (900, 700)


def test_processing_applies_the_same_refusals_as_decoding():
    with pytest.raises(imaging.ImageRejected):
        imaging.process(b"not an image", deskew=True)


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
