"""The Jonaki adapter (capture/adapters/jonaki.py) without PaddleOCR or weights: the real adapter
class runs against a fake runner that speaks the same JSON protocol (fake_jonaki_runner.py).

These tests show the adapter's contract behavior: provider-independent output that the existing
validators accept, explicit reading order, preserved confidence and positions, fail-closed handling
of unreadable pages, crashes, hangs and garbage, no secrets or text in errors, and isolation of the
heavy dependencies. They say NOTHING about Jonaki's recognition quality: that needs the gated
weights and permitted Bengali sample images (docs/OCR_JONAKI.md). Synthetic data only.
"""
import os
import subprocess
import sys

import pytest

from swasthyoid.capture import ocr
from swasthyoid.capture.adapters import jonaki as adapter_module
from swasthyoid.capture.adapters.jonaki import Jonaki, clean_text, reading_order
from swasthyoid.tests.adapters import fake_jonaki

DOC = [{"page_number": 1, "image": b"synthetic-image-1", "media_type": "image/png"},
       {"page_number": 2, "image": b"synthetic-image-2", "media_type": "image/png"}]
EXPECTED_ORDER = ["বাংলা পরীক্ষা 123 mixed", "first row right", "second row left", "second row right", "third row"]


@pytest.fixture
def mode(monkeypatch):
    def set_mode(value):
        monkeypatch.setenv("FAKE_JONAKI_MODE", value)
    set_mode("ok")
    return set_mode


def read(document=DOC, adapter=None):
    return (adapter or fake_jonaki.jonaki()).read(document)


# ---- the contract the worker enforces

def test_the_identity_is_valid_and_carries_provenance():
    identity = ocr.validate_identity(fake_jonaki.jonaki().identity())
    assert identity["engine_id"] == "jonaki-bangla-ocr" and identity["interface_versions"] == [0]
    assert identity["test_only"] is True and identity["adapter_version"] == "jonaki-1"
    assert "fake-rev-1" in identity["model_version"] and "PP-OCRv6_medium_det@fake-det-1" in identity["model_version"]


def test_the_result_passes_the_existing_v0_validator_for_every_page(mode):
    adapter = fake_jonaki.jonaki()
    result = ocr.validate_result(adapter.read(DOC), len(DOC), ocr.validate_identity(adapter.identity()))
    assert [p["page_number"] for p in result["pages"]] == [1, 2]


def test_lines_are_in_explicit_reading_order_and_empty_boxes_are_dropped(mode):
    for page in read()["pages"]:
        assert [item["text"] for item in page["items"]] == EXPECTED_ORDER
    assert "first row right" in EXPECTED_ORDER  # slightly lower than its row mate, still the same row


def test_confidence_and_position_are_preserved_per_item(mode):
    item = read()["pages"][0]["items"][0]
    assert item["confidence"] == 0.97 and item["position"] == [[20, 50], [220, 50], [220, 90], [20, 90]]


def test_the_raw_text_the_worker_stores_is_the_ordered_lines(mode, monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("SWASTHYOID_TEST_MODE_CONFIRM", "1")
    page = read(DOC[:1])
    assert ocr.raw_text_v0(page) == "\n".join(EXPECTED_ORDER)


def test_a_score_that_is_not_finite_is_left_out(mode):
    mode("nan_score")
    assert "confidence" not in read(DOC[:1])["pages"][0]["items"][0]


def test_a_decodable_page_without_text_is_a_valid_empty_page(mode):
    mode("empty")
    result = read()
    assert [p["items"] for p in result["pages"]] == [[], []]
    ocr.validate_result(result, 2, ocr.validate_identity(fake_jonaki.jonaki().identity()))


# ---- fail closed

def code(adapter=None, document=DOC):
    with pytest.raises(ocr.AdapterError) as failure:
        read(document, adapter)
    return failure.value.code


def test_an_undecodable_page_fails_the_attempt_instead_of_reading_as_empty(mode):
    mode("undecodable")
    assert code() == "engine_error"
    assert code(document=[{"page_number": 1, "image": b"UNDECODABLE"}]) == "engine_error"


@pytest.mark.parametrize("name, expected", [("crash", "engine_error"), ("leak", "engine_error"),
                                            ("garbage", "malformed_output"), ("bad_poly", "malformed_output"),
                                            ("wrong_page", "malformed_output")])
def test_runner_failures_become_codes_without_messages(mode, name, expected):
    mode(name)
    assert code() == expected


def test_a_hung_runner_is_killed_at_the_limit(mode):
    mode("hang")
    adapter = Jonaki([sys.executable, str(fake_jonaki.RUNNER)], "r", "d", page_seconds=1,
                     extra_env={"FAKE_JONAKI_MODE": "hang"})
    assert code(adapter, DOC[:1]) == "engine_error"


def test_a_missing_interpreter_is_unavailable_not_a_crash():
    assert code(Jonaki(["/no/such/python"], "r", "d"), DOC[:1]) == "engine_unavailable"


def test_error_text_never_carries_runner_output(mode):
    mode("leak")
    with pytest.raises(ocr.AdapterError) as failure:
        read()
    assert "patient" not in repr(failure.value) and str(failure.value) == "engine_error"


@pytest.mark.parametrize("revision", ["", "has space", "x" * 41, "bad;rev", None, 5])
def test_an_unusable_revision_makes_the_adapter_unavailable(revision):
    with pytest.raises(ocr.AdapterError) as failure:
        Jonaki(["python"], revision, "d")
    assert failure.value.code == "engine_unavailable"


def test_the_child_gets_an_allowlisted_environment_with_no_secrets_and_offline_mode(mode, monkeypatch):
    mode("environment")
    for name in ("DATABASE_URL", "JWT_SECRET", "DOCUMENT_KEY", "PII_KEY", "HMAC_KEY", "HF_TOKEN",
                 "HUGGING_FACE_HUB_TOKEN", "SYNTHETIC_SECRET"):
        monkeypatch.setenv(name, "SYNTHETIC-VALUE-THAT-MUST-NOT-ARRIVE")
    monkeypatch.setenv("JONAKI_MARKER", "1")  # a JONAKI_ setting is allowed through
    text = read(DOC[:1])["pages"][0]["items"][0]["text"]
    assert text == "offline=1 leaked=[] jonaki=True"


def test_explicit_extra_environment_reaches_the_child_and_must_be_strings():
    adapter = Jonaki([sys.executable, str(fake_jonaki.RUNNER)], "r", "d", extra_env={"FAKE_JONAKI_MODE": "empty"})
    assert read(DOC[:1], adapter)["pages"][0]["items"] == []
    with pytest.raises(ocr.AdapterError):
        Jonaki(["python"], "r", "d", extra_env={"A": 1})


# ---- the factory validates its settings without loading anything

@pytest.mark.parametrize("missing", ["JONAKI_PYTHON", "JONAKI_MODEL_DIR", "JONAKI_DETECTOR_DIR",
                                     "JONAKI_MODEL_REVISION", "JONAKI_DETECTOR_REVISION"])
def test_the_factory_refuses_incomplete_configuration(monkeypatch, tmp_path, missing):
    values = {"JONAKI_PYTHON": sys.executable, "JONAKI_MODEL_DIR": str(tmp_path), "JONAKI_DETECTOR_DIR": str(tmp_path),
              "JONAKI_MODEL_REVISION": "abc123", "JONAKI_DETECTOR_REVISION": "def456"}
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    assert adapter_module.jonaki().identity()["engine_id"] == "jonaki-bangla-ocr"
    monkeypatch.delenv(missing)
    with pytest.raises(ocr.AdapterError) as failure:
        adapter_module.jonaki()
    assert failure.value.code == "engine_unavailable"


def test_relative_or_nonexistent_paths_are_refused(monkeypatch, tmp_path):
    monkeypatch.setenv("JONAKI_PYTHON", "python")  # relative
    monkeypatch.setenv("JONAKI_MODEL_DIR", str(tmp_path / "missing"))
    monkeypatch.setenv("JONAKI_DETECTOR_DIR", str(tmp_path))
    monkeypatch.setenv("JONAKI_MODEL_REVISION", "a")
    monkeypatch.setenv("JONAKI_DETECTOR_REVISION", "b")
    with pytest.raises(ocr.AdapterError):
        adapter_module.jonaki()


def test_the_real_runner_without_its_environment_exits_non_zero_with_no_output(tmp_path):
    done = subprocess.run([sys.executable, str(adapter_module.RUNNER), "--recognizer", str(tmp_path),
                           "--detector", str(tmp_path)], input='{"pages": []}', capture_output=True, text=True, timeout=60)
    assert done.returncode != 0 and done.stdout == "" and done.stderr == ""  # no traceback, no message


# ---- reading order and text, as pure functions

def line(text, x, y, h=40):
    return {"text": text, "position": [[x, y], [x + 100, y], [x + 100, y + h], [x, y + h]]}


def test_reading_order_groups_rows_by_vertical_centre_then_sorts_left_to_right():
    lines = [line("c", 300, 10), line("a", 10, 12), line("e", 20, 100), line("b", 150, 8), line("d", 10, 98)]
    assert [x["text"] for x in reading_order(lines)] == ["a", "b", "c", "d", "e"]


def test_reading_order_is_deterministic_and_keeps_ties_in_input_order():
    lines = [line("first", 10, 10), line("second", 10, 10)]
    assert [x["text"] for x in reading_order(lines)] == ["first", "second"]
    assert reading_order([]) == [] and reading_order(lines[:1]) == lines[:1]


def test_a_two_column_page_comes_out_in_row_order_across_the_columns():
    """The documented limitation: one column is assumed (no gutter detection)."""
    lines = [line("L1", 10, 10), line("L2", 10, 60), line("R1", 500, 10), line("R2", 500, 60)]
    assert [x["text"] for x in reading_order(lines)] == ["L1", "R1", "L2", "R2"]


def test_clean_text_normalises_to_nfc_and_removes_control_characters():
    assert clean_text("a\x00b\tc\n") == "a b c"
    assert clean_text("ো") == "ো"  # Bengali vowel signs compose to the single NFC form
    assert clean_text("   ") == ""
    with pytest.raises(ocr.AdapterError):
        clean_text(5)


# ---- isolation of the heavy dependencies

def test_the_adapter_and_the_core_import_no_paddle_or_other_heavy_dependency():
    probe = ("import sys, swasthyoid.capture.adapters.jonaki, swasthyoid.capture.extraction;"
             "bad=[m for m in ('paddle','paddleocr','cv2','torch','tensorflow','onnxruntime') if m in sys.modules];"
             "print(bad)")
    done = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=60,
                          cwd=os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__)))))
    assert done.stdout.strip() == "[]", done.stderr


def test_the_optional_requirements_are_not_part_of_the_projects_dependencies():
    import tomllib
    from pathlib import Path
    root = Path(__file__).resolve().parents[3]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    declared = " ".join(project["dependencies"] + [d for g in project.get("optional-dependencies", {}).values() for d in g])
    assert not any(name in declared.lower() for name in ("paddle", "opencv", "jonaki"))
