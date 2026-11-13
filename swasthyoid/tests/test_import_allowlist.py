"""CI lint (FRD section 13): only adapter modules may import a model runtime or ML framework.

Every other module may import only the standard library, swasthyoid, and the dependencies
declared in pyproject.toml (plus the dev/test ones for tests). No framework is named here.
pydantic and starlette are listed because existing code imports them directly although they
arrive only through fastapi; they are not declared in pyproject.toml.
"""
import ast
import sys
import tomllib
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1]
REPO = PACKAGE.parent
ADAPTERS = ("capture", "adapters")  # swasthyoid/capture/adapters/: owner-approved adapters only
# distribution name in pyproject.toml -> import name, where they differ
IMPORT_NAMES = {"psycopg[binary]": "psycopg", "pyjwt": "jwt", "python-multipart": "multipart", "pillow": "PIL"}
VIA_FASTAPI = {"pydantic", "starlette"}


def declared(groups):
    project = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    names = list(project["dependencies"])
    if "dev" in groups:
        names += project.get("optional-dependencies", {}).get("dev", [])
    out = set()
    for name in names:
        name = name.lower().split(";")[0].strip()
        base = name.split("[")[0].split("=")[0].split(">")[0].split("<")[0].strip()
        out.add(IMPORT_NAMES.get(name, IMPORT_NAMES.get(base, base.replace("-", "_"))))
    return out


def imports(source, filename):
    for node in ast.walk(ast.parse(source, filename)):
        if isinstance(node, ast.Import):
            yield from (a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            yield node.module.split(".")[0]


def violations(source, filename, allowed):
    return [f"{filename}: imports {m}" for m in sorted(set(imports(source, filename)))
            if m not in sys.stdlib_module_names and m != "swasthyoid" and m not in allowed]


def test_lint_detects_an_undeclared_import():
    allowed = declared({"main"}) | VIA_FASTAPI
    assert violations("import some_ml_framework", "x.py", allowed)
    assert violations("from some_runtime.sub import Model", "x.py", allowed)
    assert not violations("import os, json\nfrom swasthyoid.capture import ocr\nimport psycopg", "x.py", allowed)
    assert not violations("from . import sibling", "x.py", allowed)


def test_only_adapter_modules_import_anything_undeclared():
    app_allowed = declared({"main"}) | VIA_FASTAPI
    test_allowed = declared({"main", "dev"}) | VIA_FASTAPI
    found = []
    for path in PACKAGE.rglob("*.py"):
        rel = path.relative_to(PACKAGE)
        if rel.parts[:2] == ADAPTERS:
            continue
        allowed = test_allowed if rel.parts[0] == "tests" else app_allowed
        found += violations(path.read_text(encoding="utf-8"), str(rel), allowed)
    assert not found, "undeclared imports outside capture/adapters/:\n" + "\n".join(found)


def test_ocr_infrastructure_imports_only_the_standard_library():
    source = (PACKAGE / "capture" / "ocr.py").read_text(encoding="utf-8")
    assert not violations(source, "capture/ocr.py", set())
    source = (PACKAGE / "runtime_mode.py").read_text(encoding="utf-8")
    assert not violations(source, "runtime_mode.py", set())
