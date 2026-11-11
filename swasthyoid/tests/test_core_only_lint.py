"""CI lint (FRD section 13): only core/ may implement consent, audit or notification logic.

shortcut: name-based heuristic (file names and def/class names), so it cannot see
logic hidden behind an innocent name; upgrade to an import/storage-access check
once P1 gives core/ a real API.
"""
import ast
import re
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
ALLOWED = {"core", "tests"}
FORBIDDEN = re.compile(r"consent|audit|notif|authori[sz]", re.IGNORECASE)


def violations(source, filename):
    found = []
    if FORBIDDEN.search(Path(filename).stem):
        found.append(f"{filename}: file name")
    for node in ast.walk(ast.parse(source, filename)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and FORBIDDEN.search(node.name):
            found.append(f"{filename}:{node.lineno}: defines {node.name}")
    return found


def test_lint_detects_violations():
    assert violations("def check_consent(): pass", "x.py")
    assert violations("class AuditLog: pass", "x.py")
    assert violations("", "notifier.py")
    assert not violations("from swasthyoid.core import authorize\nauthorize()", "x.py")


def test_only_core_implements_consent_audit_notification():
    found = []
    for path in PACKAGE.rglob("*.py"):
        rel = path.relative_to(PACKAGE)
        if rel.parts[0] not in ALLOWED:
            found += violations(path.read_text(encoding="utf-8"), str(rel))
    assert not found, "consent/audit/notification logic outside core/:\n" + "\n".join(found)
