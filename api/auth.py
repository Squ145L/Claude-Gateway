"""Authentication — Bearer token verification."""
from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from config import AUTH_SECRET

router = APIRouter(tags=["auth"])

# Paths that skip auth
PUBLIC_PATHS = {"/api/health", "/api/auth/verify", "/docs", "/openapi.json", "/", "/static"}

security = HTTPBearer(auto_error=False)


def verify_token(request: Request, credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Middleware dependency — check bearer token."""
    path = request.url.path
    if path in PUBLIC_PATHS or path.startswith("/static"):
        return True
    if credentials is None:
        raise HTTPException(status_code=401, detail={"error": "Missing token", "code": "UNAUTHORIZED"})
    if credentials.credentials != AUTH_SECRET:
        raise HTTPException(status_code=401, detail={"error": "Invalid token", "code": "UNAUTHORIZED"})
    return True


@router.post("/auth/verify")
async def verify_secret(body: dict):
    """Verify secret and return validity."""
    secret = body.get("secret", "")
    if secret == AUTH_SECRET:
        return {"valid": True}
    return {"valid": False}
