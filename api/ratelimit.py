"""Simple in-memory rate limiter — only limits POST/PUT/DELETE."""
import time
from collections import defaultdict
from fastapi import Request
from fastapi.responses import JSONResponse

_store: dict[str, list[float]] = defaultdict(list)
RATE_LIMIT = 60
RATE_WINDOW = 60


async def rate_limit(request: Request, call_next):
    """Check rate limit on mutating requests. GET requests always pass."""
    if request.method == "GET":
        return await call_next(request)

    ip = request.client.host if request.client else "unknown"
    now = time.monotonic()
    _store[ip] = [t for t in _store[ip] if now - t < RATE_WINDOW]

    if len(_store[ip]) >= RATE_LIMIT:
        return JSONResponse(
            status_code=429,
            content={"error": "Too many requests. Try again later.", "code": "RATE_LIMITED"},
        )

    _store[ip].append(now)
    return await call_next(request)
