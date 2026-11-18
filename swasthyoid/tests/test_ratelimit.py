"""W4 API rate limit: off unless configured; past the limit a 429 with Retry-After; /health is never limited."""
from fastapi.testclient import TestClient

from swasthyoid.api import ratelimit
from swasthyoid.api.main import app


def test_past_the_limit_requests_get_429(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)  # no schema work: these requests never reach the database
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "3")
    monkeypatch.setattr(ratelimit, "_window", [0, {}])
    with TestClient(app) as http:
        codes = [http.get("/api/v1/nothing-here").status_code for _ in range(4)]
        assert codes[:3] == [404, 404, 404]
        assert codes[3] == 429
        r = http.get("/api/v1/nothing-here")
        assert r.json()["code"] == "too_many_requests" and 0 < int(r.headers["Retry-After"]) <= 60
        assert http.get("/health").status_code == 200


def test_off_by_default_and_bad_values_refuse_to_start(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("RATE_LIMIT_PER_MINUTE", raising=False)
    assert ratelimit.limit() == 0
    monkeypatch.setenv("RATE_LIMIT_PER_MINUTE", "lots")
    try:
        with TestClient(app):
            raise AssertionError("started")
    except RuntimeError as e:
        assert "RATE_LIMIT_PER_MINUTE" in str(e)
