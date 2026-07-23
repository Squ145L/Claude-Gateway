"""Authentication — Bearer token verification with brute-force protection."""
import secrets
import asyncio
import time
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from config import AUTH_SECRET
from logger import logger

router = APIRouter(tags=["auth"])

# Paths that skip auth
PUBLIC_PATHS = {"/api/health", "/api/auth/verify", "/docs", "/openapi.json", "/", "/static"}

security = HTTPBearer(auto_error=False)

# ── Login rate limiting (per IP) ───────────────────────────
_LOGIN_ATTEMPTS: dict[str, list[float]] = {}
_LOGIN_MAX_ATTEMPTS = 5       # max failures before lock
_LOGIN_WINDOW = 60            # sliding window (seconds)
_LOGIN_BLOCK_SEC = 5          # forced delay when locked


def verify_token(request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Middleware dependency — check bearer token with constant-time comparison."""
    path = request.url.path
    if path in PUBLIC_PATHS or path.startswith("/static"):
        return True
    if credentials is None:
        raise HTTPException(status_code=401, detail={"error": "Missing token", "code": "UNAUTHORIZED"})
    # Constant-time comparison (prevents timing side-channel on token check)
    if not secrets.compare_digest(credentials.credentials, AUTH_SECRET):
        raise HTTPException(status_code=401, detail={"error": "Invalid token", "code": "UNAUTHORIZED"})
    return True


@router.post("/auth/verify")
async def verify_secret(body: dict, request: Request):
    """Verify secret and return validity. Rate-limited per IP with constant-time comparison."""
    ip = request.client.host if request.client else "unknown"
    now = time.time()

    # Clean old entries outside the sliding window
    if ip in _LOGIN_ATTEMPTS:
        _LOGIN_ATTEMPTS[ip] = [t for t in _LOGIN_ATTEMPTS[ip] if now - t < _LOGIN_WINDOW]

    # Check if this IP is temporarily locked
    recent_failures = len(_LOGIN_ATTEMPTS.get(ip, []))
    if recent_failures >= _LOGIN_MAX_ATTEMPTS:
        logger.warning("[Auth] IP %s locked — %s failures in %ss",
                       ip, recent_failures, _LOGIN_WINDOW)
        await asyncio.sleep(_LOGIN_BLOCK_SEC)  # fixed delay to slow down brute-force
        return {"valid": False, "locked": True}

    secret = body.get("secret", "")

    # Constant-time comparison (prevents timing side-channel)
    is_valid = secrets.compare_digest(secret, AUTH_SECRET)

    if is_valid:
        # Clear failure history on success
        _LOGIN_ATTEMPTS.pop(ip, None)
    else:
        # Record this failure
        _LOGIN_ATTEMPTS.setdefault(ip, []).append(now)

    return {"valid": is_valid}
