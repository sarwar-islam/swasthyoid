"""W4 API-level rate limit: at most RATE_LIMIT_PER_MINUTE requests per client address per minute, then 429.

Unset or 0: off (development and tests). nginx limits first (deploy/nginx.conf); this is the backstop when the API is
reached some other way. Behind a proxy, run uvicorn with --proxy-headers so the client address is the visitor's.
shortcut: counts live in this process only (a fixed one-minute window); with several API instances, move them to the
database or Redis.
"""
import os
import time

from fastapi.responses import JSONResponse

_window = [0, {}]  # [minute number, {client address: requests in that minute}]


def limit():
    raw = os.environ.get("RATE_LIMIT_PER_MINUTE", "0")
    try:
        return max(0, int(raw))
    except ValueError:
        raise RuntimeError("RATE_LIMIT_PER_MINUTE must be a whole number") from None


async def middleware(request, call_next):
    most = limit()
    if most and request.url.path != "/health":
        minute = int(time.time() // 60)
        if _window[0] != minute:
            _window[0], _window[1] = minute, {}  # a new minute forgets the last one, so memory stays bounded
        who = request.client.host if request.client else "unknown"
        _window[1][who] = _window[1].get(who, 0) + 1
        if _window[1][who] > most:
            return JSONResponse({"code": "too_many_requests", "message": "Too many requests. Try again in a minute.",
                                 "details": {}}, status_code=429, headers={"Retry-After": str(60 - int(time.time()) % 60)})
    return await call_next(request)
