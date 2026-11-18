"""W4 deployment files: the CSP pins the one inline script by hash, so the script and both configs must agree."""
import base64
import hashlib
import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]


def test_csp_hash_matches_the_prerender_script():
    src = (ROOT / "web/scripts/prerender.mjs").read_text(encoding="utf-8")
    script = re.search(r"<script>(.*?)</script>", src).group(1)
    pin = "sha256-" + base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    assert pin in (ROOT / "deploy/nginx.conf").read_text(encoding="utf-8")
    vercel = json.loads((ROOT / "deploy/vercel.json").read_text(encoding="utf-8"))
    assert any(pin in h["value"] for rule in vercel["headers"] for h in rule["headers"])


def test_no_secret_values_in_the_example_env():
    for line in (ROOT / "deploy/.env.example").read_text(encoding="utf-8").splitlines():
        if line and not line.startswith("#") and line.split("=")[0].endswith(("KEY", "SECRET", "PASSWORD")):
            assert line.endswith("="), line
