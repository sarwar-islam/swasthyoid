"""The PaddleOCR (English) adapter (capture/adapters/paddleocr_adapter.py) without PaddleOCR or weights: the real adapter
class runs against a fake runner that speaks the same JSON protocol (fake_paddleocr_runner.py).

These tests show the adapter's contract behavior: provider-independent output that the existing validators accept, explicit
reading order, preserved confidence and positions, fail-closed handling of unreadable pages, crashes, hangs and garbage, no
secrets or text in errors, an allowlisted environment, and isolation of the heavy dependencies. They say NOTHING about
recognition quality: that needs the weights and permitted evaluation data (docs/OCR_PADDLEOCR.md). Synthetic data only.
"""
import ast
import os
import subprocess
import sys
from pathlib import Path

import pytest

from swasthyoid.capture import ocr
from swasthyoid.capture.adapters import paddleocr_adapter as adapter_module
from swasthyoid.capture.adapters.paddleocr_adapter import PaddleOcr, clean_text, reading_order
from swasthyoid.tests.adapters import fake_paddleocr

DOC = [{"page_number": 1, "image": b"synthetic-image-1", "media_type": "image/png"},
       {"page_number": 2, "image": b"synthetic-image-2", "media_type": "image/png"}]
EXPECTED_ORDER = ["Tab. Synthetic 500 mg twice daily", "first row right", "second row left", "second row right", "third row"]
ADAPTERS = Path(adapter_module.__file__).parent


@pytest.fixture
def mode(monkeypatch):
    def set_mode(value):
        monkeypatch.setenv("FAKE_PADDLEOCR_MODE", value)
    set_mode("ok")
    return set_mode


def read(document=DOC, adapter=None):
    return (adapter or fake_paddleocr.paddleocr_en()).read(document)


def fake(mode_name="ok", **kw):
    return PaddleOcr([sys.executable, str(fake_paddleocr.RUNNER)], "r", "d", extra_env={"FAKE_PADDLEOCR_MODE": mode_name}, **kw)


# ---- the contract the worker enforces

def test_the_identity_is_valid_and_carries_provenance():
    identity = ocr.validate_identity(fake_paddleocr.paddleocr_en().identity())
    assert identity["engine_id"] == "paddleocr-en" and identity["interface_versions"] == [0]
    assert identity["test_only"] is True and identity["adapter_version"] == "paddleocr-1"
    assert identity["model_version"] == "en_PP-OCRv5_mobile_rec@fake-rev-1; PP-OCRv5_mobile_det@fake-det-1"


def test_the_result_passes_the_existing_v0_validator_for_every_page(mode):
    adapter = fake_paddleocr.paddleocr_en()
    result = ocr.validate_result(adapter.read(DOC), len(DOC), ocr.validate_identity(adapter.identity()))
    assert [p["page_number"] for p in result["pages"]] == [1, 2]


def test_lines_are_in_explicit_reading_order_and_empty_boxes_are_dropped(mode):
    for page in read()["pages"]:
        assert [item["text"] for item in page["items"]] == EXPECTED_ORDER


def test_confidence_and_position_are_preserved_per_item(mode):
    item = read()["pages"][0]["items"][0]
    assert item["confidence"] == 0.97 and item["position"] == [[20, 50], [220, 50], [220, 90], [20, 90]]


def test_the_raw_text_the_worker_stores_is_the_ordered_lines(mode, monkeypatch):
    monkeypatch.setenv("APP_ENV", "test")
    monkeypatch.setenv("SWASTHYOID_TEST_MODE_CONFIRM", "1")
    assert ocr.raw_text_v0(read(DOC[:1])) == "\n".join(EXPECTED_ORDER)


def test_a_score_that_is_not_finite_is_left_out(mode):
    mode("nan_score")
    assert "confidence" not in read(DOC[:1])["pages"][0]["items"][0]


def test_a_decodable_page_without_text_is_a_valid_empty_page(mode):
    mode("empty")
    result = read()
    assert [p["items"] for p in result["pages"]] == [[], []]
    ocr.validate_result(result, 2, ocr.validate_identity(fake_paddleocr.paddleocr_en().identity()))


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
    assert code(fake("hang", page_seconds=1), DOC[:1]) == "engine_error"


def test_a_missing_interpreter_is_unavailable_not_a_crash():
    assert code(PaddleOcr(["/no/such/python"], "r", "d"), DOC[:1]) == "engine_unavailable"


def test_error_text_never_carries_runner_output(mode):
    mode("leak")
    with pytest.raises(ocr.AdapterError) as failure:
        read()
    assert "patient" not in repr(failure.value) and str(failure.value) == "engine_error"


def test_a_page_without_image_bytes_is_refused_before_the_runner_starts():
    with pytest.raises(ocr.AdapterError) as failure:
        fake_paddleocr.paddleocr_en().read([{"page_number": 1, "image": "not bytes"}])
    assert failure.value.code == "engine_error"


@pytest.mark.parametrize("revision", ["", "has space", "x" * 41, "bad;rev", None, 5])
def test_an_unusable_revision_makes_the_adapter_unavailable(revision):
    with pytest.raises(ocr.AdapterError) as failure:
        PaddleOcr(["python"], revision, "d")
    assert failure.value.code == "engine_unavailable"


@pytest.mark.parametrize("name", ["", "has space", "x" * 61, "bad;name", None, 5, "../x"])
def test_an_unusable_model_name_makes_the_adapter_unavailable(name):
    for keyword in ("recognizer_name", "detector_name"):
        with pytest.raises(ocr.AdapterError) as failure:
            PaddleOcr(["python"], "r", "d", **{keyword: name})
        assert failure.value.code == "engine_unavailable"


def test_an_identity_too_long_for_the_contract_makes_the_adapter_unavailable():
    with pytest.raises(ocr.AdapterError):
        PaddleOcr(["python"], "r" * 40, "d" * 40, recognizer_name="n" * 60, detector_name="m" * 60)  # over 128 characters


# ---- the child's environment

def test_the_child_gets_an_allowlisted_environment_with_no_secrets_no_home_and_offline_mode(mode, monkeypatch):
    mode("environment")
    for name in ("DATABASE_URL", "JWT_SECRET", "DOCUMENT_KEY", "PII_KEY", "HMAC_KEY", "HF_TOKEN",
                 "HUGGING_FACE_HUB_TOKEN", "SYNTHETIC_SECRET", "EXTRACTION_KEY"):
        monkeypatch.setenv(name, "SYNTHETIC-VALUE-THAT-MUST-NOT-ARRIVE")
    monkeypatch.setenv("HOME", "/synthetic/home")
    monkeypatch.setenv("USERPROFILE", "C:\\synthetic\\profile")
    monkeypatch.setenv("PADDLEOCR_MARKER", "1")  # a PADDLEOCR_ setting is allowed through
    text = read(DOC[:1])["pages"][0]["items"][0]["text"]
    assert text == "offline=1 leaked=[] home=[] marker=True"  # no secret, no HOME or USERPROFILE, offline set


def test_explicit_extra_environment_reaches_the_child_and_must_be_strings():
    assert read(DOC[:1], fake("empty"))["pages"][0]["items"] == []
    with pytest.raises(ocr.AdapterError):
        PaddleOcr(["python"], "r", "d", extra_env={"A": 1})


# ---- the factory validates its settings without loading anything

VALUES = {"PADDLEOCR_MODEL_REVISION": "abc123", "PADDLEOCR_DETECTOR_REVISION": "def456"}


def configure(monkeypatch, tmp_path):
    for name, value in {"PADDLEOCR_PYTHON": sys.executable, "PADDLEOCR_MODEL_DIR": str(tmp_path),
                        "PADDLEOCR_DETECTOR_DIR": str(tmp_path), **VALUES}.items():
        monkeypatch.setenv(name, value)


@pytest.mark.parametrize("missing", ["PADDLEOCR_PYTHON", "PADDLEOCR_MODEL_DIR", "PADDLEOCR_DETECTOR_DIR",
                                     "PADDLEOCR_MODEL_REVISION", "PADDLEOCR_DETECTOR_REVISION"])
def test_the_factory_refuses_incomplete_configuration(monkeypatch, tmp_path, missing):
    configure(monkeypatch, tmp_path)
    assert adapter_module.paddleocr_en().identity()["engine_id"] == "paddleocr-en"
    monkeypatch.delenv(missing)
    with pytest.raises(ocr.AdapterError) as failure:
        adapter_module.paddleocr_en()
    assert failure.value.code == "engine_unavailable"


def test_relative_or_nonexistent_paths_are_refused(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path)
    monkeypatch.setenv("PADDLEOCR_PYTHON", "python")  # relative
    with pytest.raises(ocr.AdapterError):
        adapter_module.paddleocr_en()
    configure(monkeypatch, tmp_path)
    monkeypatch.setenv("PADDLEOCR_MODEL_DIR", str(tmp_path / "missing"))
    with pytest.raises(ocr.AdapterError):
        adapter_module.paddleocr_en()


def test_the_command_is_isolated_names_the_models_and_defaults_are_the_english_ones(monkeypatch, tmp_path):
    configure(monkeypatch, tmp_path)
    command = adapter_module.paddleocr_en().command
    assert command[1] == "-I"  # isolated mode: the adapters directory is not on the runner's import path
    assert command[command.index("--recognizer-name") + 1] == "en_PP-OCRv5_mobile_rec"
    assert command[command.index("--detector-name") + 1] == "PP-OCRv5_mobile_det"
    monkeypatch.setenv("PADDLEOCR_RECOGNIZER_NAME", "en_PP-OCRv4_mobile_rec")
    adapter = adapter_module.paddleocr_en()
    assert adapter.command[adapter.command.index("--recognizer-name") + 1] == "en_PP-OCRv4_mobile_rec"
    assert adapter.identity()["model_version"].startswith("en_PP-OCRv4_mobile_rec@abc123")


def test_a_runner_that_receives_the_model_names_reports_them_by_name_only(mode):
    mode("arguments")
    assert read(DOC[:1], fake("arguments"))["pages"][0]["items"] == []  # the plain fake has no names: nothing reported
    command = [sys.executable, str(fake_paddleocr.RUNNER), "--recognizer-name", "R-name", "--detector-name", "D-name"]
    adapter = PaddleOcr(command, "r", "d", extra_env={"FAKE_PADDLEOCR_MODE": "arguments"})
    assert read(DOC[:1], adapter)["pages"][0]["items"][0]["text"] == "R-name D-name"


def test_the_real_runner_without_its_environment_exits_non_zero_with_no_output(tmp_path):
    done = subprocess.run([sys.executable, "-I", str(adapter_module.RUNNER), "--recognizer", str(tmp_path),
                           "--detector", str(tmp_path), "--recognizer-name", "a", "--detector-name", "b"],
                          input='{"pages": []}', capture_output=True, text=True, timeout=60)
    assert done.returncode != 0 and done.stdout == "" and done.stderr == ""  # no traceback, no message


def test_the_real_runner_never_downloads_it_refuses_a_missing_model_directory(tmp_path):
    done = subprocess.run([sys.executable, "-I", str(adapter_module.RUNNER), "--recognizer", str(tmp_path / "none"),
                           "--detector", str(tmp_path), "--recognizer-name", "a", "--detector-name", "b"],
                          input='{"pages": []}', capture_output=True, text=True, timeout=60)
    assert done.returncode != 0 and done.stdout == "" and done.stderr == ""


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
    assert clean_text("e\u0301") == "\u00e9"  # a combining accent composes to the single NFC form
    assert clean_text("   ") == ""
    with pytest.raises(ocr.AdapterError):
        clean_text(5)


# ---- independence and isolation

def test_the_adapter_shares_no_code_with_jonaki_and_leaves_it_alone():
    tree = ast.parse((ADAPTERS / "paddleocr_adapter.py").read_text(encoding="utf-8"))
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    imported |= {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
    assert not any("jonaki" in name for name in imported)
    assert (ADAPTERS / "jonaki.py").exists()


def test_no_module_in_the_adapters_directory_can_shadow_the_real_paddleocr_package():
    assert not (ADAPTERS / "paddleocr.py").exists() and not (ADAPTERS / "paddle.py").exists()
    assert not (ADAPTERS / "paddleocr").exists()


def test_the_adapter_and_the_core_import_no_paddle_or_other_heavy_dependency():
    probe = ("import sys, swasthyoid.capture.adapters.paddleocr_adapter, swasthyoid.capture.extraction;"
             "bad=[m for m in ('paddle','paddleocr','cv2','torch','tensorflow','onnxruntime') if m in sys.modules];"
             "print(bad)")
    done = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True, timeout=60,
                          cwd=ADAPTERS.parents[2])
    assert done.stdout.strip() == "[]", done.stderr


def test_the_runner_switches_orientation_textline_and_unwarping_off_and_passes_explicit_model_directories():
    source = (ADAPTERS / "paddleocr_runner.py").read_text(encoding="utf-8")
    for flag in ("use_doc_orientation_classify=False", "use_doc_unwarping=False", "use_textline_orientation=False"):
        assert flag in source
    assert "text_detection_model_dir=args.detector" in source and "text_recognition_model_dir=args.recognizer" in source


def test_the_runner_keeps_onednn_off_unless_the_owner_opts_in():
    """Found with the real weights (2026-11-14): with oneDNN on, predict() failed on Windows CPU after the models loaded."""
    source = (ADAPTERS / "paddleocr_runner.py").read_text(encoding="utf-8")
    assert 'enable_mkldnn=os.environ.get("PADDLEOCR_ENABLE_MKLDNN") == "1"' in source  # off by default, opt-in only
    assert "enable_mkldnn=True" not in source


def test_the_opt_in_setting_reaches_the_runner_but_a_secret_does_not(monkeypatch):
    monkeypatch.setenv("PADDLEOCR_ENABLE_MKLDNN", "1")
    monkeypatch.setenv("DATABASE_URL", "postgresql://synthetic-secret")
    env = fake_paddleocr.paddleocr_en()._environment()
    assert env["PADDLEOCR_ENABLE_MKLDNN"] == "1" and "DATABASE_URL" not in env


def test_the_optional_requirements_are_not_part_of_the_projects_dependencies():
    import tomllib
    root = ADAPTERS.parents[2]
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    declared = " ".join(project["dependencies"] + [d for g in project.get("optional-dependencies", {}).values() for d in g])
    assert not any(name in declared.lower() for name in ("paddle", "opencv", "jonaki"))
    assert "paddleocr==" in (ADAPTERS / "paddleocr_requirements.txt").read_text(encoding="utf-8")


def test_interface_version_zero_stays_test_only(monkeypatch):
    assert fake_paddleocr.paddleocr_en().identity()["test_only"] is True
    assert ocr.INTERFACE_VERSION == 0
