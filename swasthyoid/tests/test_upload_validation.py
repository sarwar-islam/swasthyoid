"""Phase 5 (decision D5/D6, docs/DECISIONS.md "Phase 5"), without a database: every upload image is really decoded once and
quality-checked before anything is stored, a file that cannot be used is refused whatever the caller asks, poor pages are
refused with Bangla guidance unless the caller accepts them, and a copy without metadata can be made for other viewers.
The database and API side (rows, audit entry, status codes, serving) is in test_documents.py. Synthetic images only."""
import io

import pytest
from PIL import Image, ImageFile

from swasthyoid.capture import documents, imaging
from swasthyoid.capture.guidance import GUIDANCE, QUALITY_CODES, guidance_for
from swasthyoid.tests import images as img

QUALITY = ("image_blurry", "image_glare", "image_low_contrast", "image_skewed", "image_too_small")


def reasons(data):
    with pytest.raises(documents.QualityWarning) as warning:
        documents.inspect_images([data])
    return warning.value.pages[0][1]


def rejected(images, **kw):
    with pytest.raises(documents.UploadRejected) as refused:
        documents.inspect_images(images, **kw)
    return refused.value.code, refused.value.page


# ---- valid files

def test_valid_jpeg_and_png_pass_with_no_warnings_and_get_their_content_type_from_the_decoded_file():
    out = documents.inspect_images([img.PNG, img.JPEG])
    assert [(k["content_type"], k["ext"], k["warnings"]) for k in out] == [("image/png", "png", []), ("image/jpeg", "jpg", [])]


def test_a_multi_picture_jpeg_from_a_phone_is_accepted_as_a_jpeg():
    data = img.mpo()
    assert Image.open(io.BytesIO(data)).format == "MPO"
    assert documents.inspect_images([data])[0]["content_type"] == "image/jpeg"


def test_a_page_stored_sideways_with_an_exif_orientation_is_measured_the_way_a_person_sees_it():
    data = img.jpeg_with_metadata(orientation=6)
    assert Image.open(io.BytesIO(data)).size == (1400, 1000)  # stored sideways
    grey, _ = imaging.load(data, exif=True)
    assert grey.shape == (1400, 1000)  # height, width after the orientation is applied
    assert documents.inspect_images([data])[0]["warnings"] == []


def test_each_image_is_decoded_once(monkeypatch):
    calls = []
    original = imaging.load
    monkeypatch.setattr(imaging, "load", lambda *a, **k: calls.append(1) or original(*a, **k))
    monkeypatch.setattr(imaging, "decode", lambda *a, **k: pytest.fail("a second decode"))
    documents.inspect_images([img.PNG, img.JPEG])
    assert len(calls) == 2


# ---- hard failures: never bypassed

@pytest.mark.parametrize("data, code", [
    (b"GIF89a not allowed", "image_unsupported"),
    (b"II*\x00 a TIFF header", "image_unsupported"),
    (b"MZ this is a program", "image_unsupported"),
    (b"\x89PNG\r\n\x1a\n" + b"not really a png", "image_undecodable"),     # right first bytes, nothing behind them
    (b"\xff\xd8\xff\xe0 not really a jpeg", "image_undecodable"),
    (img.truncated(img.PNG), "image_undecodable"),
    (img.truncated(img.JPEG), "image_undecodable"),
])
def test_spoofed_corrupt_and_truncated_files_are_refused_with_a_stable_code_even_with_upload_anyway(data, code):
    for anyway in (False, True):
        assert rejected([img.PNG, data], upload_anyway=anyway) == (code, 2)  # the page number is the second one


def test_the_pixel_cap_is_checked_at_its_boundary_and_before_any_pixel_is_decoded(monkeypatch):
    width, height = Image.open(io.BytesIO(img.PNG)).size
    monkeypatch.setattr(imaging, "MAX_PIXELS", width * height)  # exactly at the cap: allowed
    assert documents.inspect_images([img.PNG])
    monkeypatch.setattr(imaging, "MAX_PIXELS", width * height - 1)
    monkeypatch.setattr(ImageFile.ImageFile, "load", lambda self: pytest.fail("pixels were decoded"))
    assert rejected([img.PNG], upload_anyway=True) == ("image_too_large", 1)


def test_the_documented_pixel_cap_is_forty_million():
    assert imaging.MAX_PIXELS == 40_000_000


def test_the_file_size_limit_is_checked_at_its_boundary_before_decoding(monkeypatch):
    monkeypatch.setattr(documents, "MAX_IMAGE_BYTES", len(img.PNG))
    assert documents.inspect_images([img.PNG])
    monkeypatch.setattr(documents, "MAX_IMAGE_BYTES", len(img.PNG) - 1)
    monkeypatch.setattr(imaging, "load", lambda *a, **k: pytest.fail("a too-large file was decoded"))
    assert rejected([img.PNG], upload_anyway=True) == ("image_file_too_large", 1)


@pytest.mark.parametrize("images", [[], [img.PNG] * 11, [b""], [img.PNG, b""]])
def test_the_number_of_images_and_an_empty_file_are_still_value_errors(images):
    with pytest.raises(ValueError):
        documents.inspect_images(images)


def test_the_cheap_checks_of_every_page_run_before_any_page_is_decoded(monkeypatch):
    monkeypatch.setattr(imaging, "load", lambda *a, **k: pytest.fail("decoded before the cheap checks finished"))
    assert rejected([img.PNG, b"GIF89a"]) == ("image_unsupported", 2)


# ---- quality warnings

@pytest.mark.parametrize("kind, expected", [("blur", "image_blurry"), ("glare", "image_glare"),
                                            ("low_contrast", "image_low_contrast"), ("rotate", "image_skewed"),
                                            ("small", "image_too_small")])
def test_each_quality_reason_is_reported_by_page(kind, expected):
    assert expected in reasons(img.poor_page(kind))


def test_only_the_poor_pages_are_flagged_and_the_page_numbers_are_kept():
    with pytest.raises(documents.QualityWarning) as warning:
        documents.inspect_images([img.PNG, img.poor_page("rotate"), img.JPEG, img.poor_page("small")])
    assert [page for page, _ in warning.value.pages] == [2, 4]


def test_upload_anyway_accepts_the_warnings_and_returns_them_per_page():
    out = documents.inspect_images([img.PNG, img.poor_page("rotate")], upload_anyway=True)
    assert [k["warnings"] for k in out] == [[], ["image_skewed"]]


def test_a_clean_upload_with_upload_anyway_has_no_warnings_to_record():
    assert documents.inspect_images([img.PNG], upload_anyway=True)[0]["warnings"] == []


# ---- Bangla guidance

APPROVED = {
    "image_blurry": "ছবিটি ঝাপসা হয়েছে। ক্যামেরা স্থির রেখে আবার পরিষ্কার ছবি তুলুন।",
    "image_glare": "ছবিতে অতিরিক্ত আলো বা প্রতিফলন রয়েছে। আলো পরিবর্তন করে আবার ছবি তুলুন।",
    "image_low_contrast": "লেখাগুলো স্পষ্ট দেখা যাচ্ছে না। পর্যাপ্ত আলোতে আবার ছবি তুলুন।",
    "image_skewed": "কাগজটি বাঁকা অবস্থায় তোলা হয়েছে। ক্যামেরা কাগজের সমান্তরালে রেখে ছবি তুলুন।",
    "image_too_small": "ছবির রেজোলিউশন কম। কাগজের আরও কাছে গিয়ে পরিষ্কার ছবি তুলুন।",
}


def test_the_guidance_is_exactly_the_approved_bangla_text_for_exactly_the_quality_codes():
    assert {code: text["bn"] for code, text in GUIDANCE.items()} == APPROVED
    assert set(QUALITY_CODES) == set(QUALITY)


def test_every_reason_the_checker_can_return_has_guidance():
    emitted = set()
    for m in ({"width": 10, "height": 10, "sharpness": 0, "glare": 1, "contrast": 0, "skew": 9},):
        emitted |= set(imaging.check_measures(m))
    assert emitted == set(QUALITY) and emitted <= set(GUIDANCE)


def test_guidance_keeps_the_code_and_the_order_and_never_drops_an_unknown_code():
    out = guidance_for(["image_glare", "image_blurry", "something_new"])
    assert [g["code"] for g in out] == ["image_glare", "image_blurry", "something_new"]
    assert out[0]["bn"] == APPROVED["image_glare"] and out[2] == {"code": "something_new"}


def test_the_guidance_text_makes_no_clinical_claim():
    assert not any(word in text["bn"] for text in GUIDANCE.values() for word in ("ঔষধ", "রোগ", "চিকিৎসা", "ডোজ"))


# ---- a copy without metadata (D6)

def test_the_copy_has_no_exif_gps_or_comment_and_the_picture_keeps_its_orientation():
    data = img.jpeg_with_metadata(orientation=6)
    original = Image.open(io.BytesIO(data))
    assert original.getexif().get(0x0112) == 6 and b"SYNTHETIC-COMMENT" in data and b"SYNTHETIC-CAMERA-MAKER" in data
    out, content_type = imaging.strip_metadata(data)
    copy = Image.open(io.BytesIO(out))
    assert content_type == "image/jpeg" and copy.size == (1000, 1400)  # the sideways pixels were turned upright
    assert len(copy.getexif()) == 0 and not copy.info.get("comment") and "icc_profile" not in copy.info
    assert not any(marker in out for marker in (b"Exif", b"SYNTHETIC-CAMERA-MAKER", b"SYNTHETIC-COMMENT", b"2026:01:02"))


def test_a_png_text_chunk_does_not_survive_and_the_format_is_kept():
    data = img.png_with_metadata()
    assert b"SYNTHETIC-PNG-COMMENT" in data
    out, content_type = imaging.strip_metadata(data)
    assert content_type == "image/png" and b"SYNTHETIC-PNG-COMMENT" not in out and Image.open(io.BytesIO(out)).format == "PNG"


def test_a_multi_picture_jpeg_gives_a_plain_jpeg_copy():
    out, content_type = imaging.strip_metadata(img.mpo())
    assert content_type == "image/jpeg" and Image.open(io.BytesIO(out)).format == "JPEG"


@pytest.mark.parametrize("data", [b"GIF89a", b"not an image", img.truncated(img.JPEG), b""])
def test_a_file_that_cannot_be_copied_raises_so_the_caller_serves_nothing(data):
    with pytest.raises(imaging.ImageRejected):
        imaging.strip_metadata(data)


def test_making_the_copy_leaves_the_original_bytes_alone():
    data = bytearray(img.jpeg_with_metadata(orientation=6))
    before = bytes(data)
    imaging.strip_metadata(bytes(data))
    assert bytes(data) == before
