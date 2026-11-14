"""Static privacy guards for the M2 pipeline (capture/ and workers/): the properties that are
technically enforced by the code's shape, checked on its syntax tree. They cannot prove the absence
of every leak; they stop the easy regressions: a temporary file, a traceback or exception message
in a log, a log message built from content, a file write outside the encrypted store.

What they do NOT cover (see docs/M2_OWNER_DECISIONS.md): extracted text is still stored in plain
form in PostgreSQL (D2), and offline library settings do not block the network."""
import ast
from pathlib import Path

import pytest

PACKAGE = Path(__file__).resolve().parents[1]
FILES = sorted(p for d in ("capture", "workers") for p in (PACKAGE / d).rglob("*.py"))
LOG_METHODS = {"debug", "info", "warning", "error", "critical", "exception", "log"}
EXCEPTION_NAMES = {"e", "ex", "exc", "err", "error", "failure", "exception"}
WRITE_MODES = set("wax+")


def tree(path):
    return ast.parse(path.read_text(encoding="utf-8"), str(path))


def rel(path):
    return path.relative_to(PACKAGE).as_posix()


def log_calls(module):
    for node in ast.walk(module):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in LOG_METHODS
                and isinstance(node.func.value, ast.Name) and node.func.value.id in {"log", "logging", "logger"}):
            yield node


def is_exception_value(node):
    """A bare exception variable, its text (str/repr/format of it), or its args/message."""
    if isinstance(node, ast.Name):
        return node.id in EXCEPTION_NAMES
    if isinstance(node, ast.Attribute):
        return node.attr in {"args", "message", "__cause__", "__context__"} or is_exception_value(node.value) and \
            node.attr not in {"code", "__name__"}
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"str", "repr", "format"}:
        return any(is_exception_value(a) for a in node.args)
    if isinstance(node, ast.JoinedStr):
        return True
    return False


def test_the_files_under_guard_are_found():
    names = {rel(p) for p in FILES}
    assert {"capture/extraction.py", "capture/ocr.py", "capture/storage.py", "workers/extract.py",
            "capture/adapters/jonaki.py"} <= names
    assert sum(len(list(log_calls(tree(p)))) for p in FILES) >= 5  # the scan below is not vacuous


@pytest.mark.parametrize("path", FILES, ids=rel)
def test_no_temporary_files_and_no_traceback_handling(path):
    for node in ast.walk(tree(path)):
        names = []
        if isinstance(node, ast.Import):
            names = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            names = [node.module.split(".")[0]]
        assert not {"tempfile", "traceback"} & set(names), f"{rel(path)} imports {names}"


@pytest.mark.parametrize("path", FILES, ids=rel)
def test_logging_carries_constant_messages_and_never_an_exception_or_traceback(path):
    for call in log_calls(tree(path)):
        where = f"{rel(path)}:{call.lineno}"
        assert call.func.attr != "exception", f"{where} logs a traceback"
        assert not any(k.arg == "exc_info" for k in call.keywords), f"{where} asks for exc_info"
        assert call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str), \
            f"{where}: the message must be a constant string, not built from content"
        assert not any(is_exception_value(a) for a in call.args[1:]), f"{where} logs an exception value"


@pytest.mark.parametrize("path", [p for p in FILES if rel(p) != "capture/storage.py"], ids=rel)
def test_nothing_but_the_encrypted_store_writes_files(path):
    for node in ast.walk(tree(path)):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == "open":
            mode = node.args[1] if len(node.args) > 1 else next((k.value for k in node.keywords if k.arg == "mode"), None)
            assert not (isinstance(mode, ast.Constant) and set(str(mode.value)) & WRITE_MODES), \
                f"{rel(path)}:{node.lineno} opens a file for writing"
        if isinstance(node.func, ast.Attribute):
            assert node.func.attr not in {"write_text", "write_bytes"}, f"{rel(path)}:{node.lineno} writes a file"


def test_the_guard_itself_catches_the_patterns_it_exists_for():
    bad = ast.parse("import tempfile\nlog.warning(f'x {text}')\nlog.warning('x %s', str(e))\nlog.exception('y')\n"
                    "log.warning('z', exc_info=True)\nopen('f', 'w')\n")
    calls = list(log_calls(bad))
    assert len(calls) == 4
    assert isinstance(calls[0].args[0], ast.JoinedStr)
    assert is_exception_value(calls[1].args[1]) and calls[2].func.attr == "exception"
    assert any(k.arg == "exc_info" for k in calls[3].keywords)
    good = ast.parse("log.warning('ocr attempt failed: code=%s', type(failure).__name__)\nlog.warning('c %s', e.code)")
    assert not any(is_exception_value(a) for c in log_calls(good) for a in c.args[1:])
