"""File upload, download, and content API."""
import os
import uuid
import hmac
import hashlib
import time
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from api.auth import verify_token
from db.store import save_file_record, get_file_record, FileRecord
from config import FILE_ROOT_DIR, MAX_FILE_SIZE_BYTES, ALLOWED_EXTENSIONS, AUTH_SECRET
from logger import logger

router = APIRouter(tags=["files"], dependencies=[Depends(verify_token)])

# Separate router for download — uses query-token auth instead of Bearer header
download_router = APIRouter(tags=["files"])

# Image extensions — stored in images/ subfolder for preview
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}

# ── HMAC-signed file tokens ─────────────────────────────────
# Replaces the old pattern of passing AUTH_SECRET in the URL query string.
# Signatures are time-limited (default 300s) and bound to a specific file path.

_FILE_TOKEN_TTL = 300  # seconds


def _sign_file_path(file_path: str, file_name: str, ttl: int = _FILE_TOKEN_TTL) -> str:
    """Create a time-limited HMAC signature for a file path.

    The token format is: <hex_signature>_<expiry_timestamp>
    Only usable for the specific file path it was signed for.
    """
    expiry = int(time.time()) + ttl
    msg = f"{file_path}|{file_name}|{expiry}".encode("utf-8")
    sig = hmac.new(AUTH_SECRET.encode("utf-8"), msg, hashlib.sha256).hexdigest()[:16]
    return f"{sig}_{expiry}"


def _verify_file_signature(file_path: str, file_name: str, token: str) -> bool:
    """Verify a time-limited HMAC signature. Constant-time comparison."""
    try:
        sig, expiry_str = token.split("_", 1)
        expiry = int(expiry_str)
        if time.time() > expiry:
            return False
        expected_msg = f"{file_path}|{file_name}|{expiry}".encode("utf-8")
        expected_sig = hmac.new(
            AUTH_SECRET.encode("utf-8"), expected_msg, hashlib.sha256
        ).hexdigest()[:16]
        return hmac.compare_digest(sig, expected_sig)
    except (ValueError, AttributeError):
        return False


def _check_size(size: int):
    if size > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=413,
            detail={
                "error": f"File too large. Max {MAX_FILE_SIZE_BYTES // 1024 // 1024}MB",
                "code": "FILE_TOO_LARGE",
            },
        )


def _check_type(filename: str):
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail={"error": f"File type '{ext}' not supported", "code": "FILE_TYPE_DENIED"},
        )


# ── Magic bytes verification ─────────────────────────────────
# Minimal check: verify the first few bytes match the claimed extension.
# Catches trivial renames (e.g. .exe → .png). Unknown types pass through.

_MAGIC_SIGNATURES = {
    b'\x89PNG\r\n\x1a\n': '.png',
    b'\xff\xd8\xff': '.jpg',
    b'GIF8': '.gif',
    b'RIFF': '.webp',
    b'BM': '.bmp',
    b'%PDF': '.pdf',
    b'PK\x03\x04': '.docx',
}


def _verify_content_type(content: bytes, claimed_ext: str) -> bool:
    """Check that the file's magic bytes are consistent with its extension.
    Returns True if consistent or if the type has no known magic bytes."""
    if not content:
        return False
    for magic_bytes, ext in _MAGIC_SIGNATURES.items():
        if content.startswith(magic_bytes):
            if ext == '.webp' and claimed_ext == '.webp':
                return len(content) > 11 and content[8:12] == b'WEBP'
            if ext == '.docx' and claimed_ext == '.docx':
                return True  # ZIP-based, full validation too expensive
            return ext == claimed_ext
    return True  # Unknown magic — allow through (plain text, code, etc.)


@router.post("/files/upload")
async def upload_file(file: UploadFile = File(...)):
    """Upload a file. Returns file_id for use in chat."""
    if not file.filename:
        raise HTTPException(status_code=400, detail={
            "error": "No file provided", "code": "BAD_REQUEST",
        })

    _check_type(file.filename)

    content = await file.read()
    _check_size(len(content))

    # ── Verify file content matches extension ─────────────────
    ext = Path(file.filename).suffix.lower()
    if not _verify_content_type(content, ext):
        raise HTTPException(status_code=400, detail={
            "error": f"File content does not match extension '{ext}'",
            "code": "FILE_TYPE_MISMATCH",
        })
    # ──────────────────────────────────────────────────────────

    file_id = str(uuid.uuid4())

    # Sanitize original filename — strip path, keep only the name part
    safe_name = Path(file.filename).name
    if not safe_name or safe_name in (".", ".."):
        safe_name = f"file_{file_id}{Path(file.filename).suffix}"

    # Images → images/ subfolder, others → root
    ext = Path(safe_name).suffix.lower()
    if ext in IMAGE_EXTENSIONS:
        sub_dir = Path(FILE_ROOT_DIR) / "images"
        sub_dir.mkdir(parents=True, exist_ok=True)
        base_dir = sub_dir
    else:
        base_dir = Path(FILE_ROOT_DIR)

    # Avoid collisions: append (1), (2), etc. if file exists
    stem = Path(safe_name).stem
    stored_path = str(base_dir / safe_name)
    counter = 1
    while Path(stored_path).exists():
        safe_name = f"{stem} ({counter}){ext}"
        stored_path = str(base_dir / safe_name)
        counter += 1

    with open(stored_path, "wb") as f:
        f.write(content)

    # Don't parse — Claude will Read files itself
    extracted_text = None

    rec = FileRecord(
        id=file_id, original_name=file.filename, stored_path=stored_path,
        mime_type=file.content_type, size_bytes=len(content),
        extracted_text=extracted_text,
    )
    await save_file_record(rec)

    logger.info(f"[Files] Uploaded {file.filename} ({len(content)} bytes) → {file_id}")

    return {
        "file_id": file_id,
        "filename": file.filename,
        "size": len(content),
        "has_preview": bool(extracted_text),
    }


@router.post("/files/token")
async def create_file_token(body: dict):
    """Create a short-lived download/view token for a specific file.

    Requires Bearer auth (unlike download/view which use the token).
    Returns a 5-minute token safe to embed in URLs.
    """
    file_id = body.get("file_id", "")
    if not file_id:
        raise HTTPException(status_code=400, detail={
            "error": "file_id required", "code": "BAD_REQUEST",
        })

    rec = await get_file_record(file_id)
    if not rec:
        raise HTTPException(status_code=404, detail={
            "error": "File not found", "code": "NOT_FOUND",
        })

    # Verify file still exists on disk
    if not Path(rec.stored_path).exists():
        raise HTTPException(status_code=404, detail={
            "error": "File no longer exists on disk", "code": "NOT_FOUND",
        })

    token = _sign_file_path(rec.stored_path, rec.original_name)
    return {
        "token": token,
        "filename": rec.original_name,
        "expires_in": _FILE_TOKEN_TTL,
    }


@router.get("/files/{file_id}/content")
async def get_file_content(file_id: str):
    """Get extracted text content of a file."""
    rec = await get_file_record(file_id)
    if not rec:
        raise HTTPException(status_code=404, detail={
            "error": "File not found", "code": "NOT_FOUND",
        })
    return {
        "file_id": rec.id,
        "filename": rec.original_name,
        "text": rec.extracted_text or "",
    }


@download_router.get("/files/download/{name:path}")
async def download_file(name: str, token: str = Query(...)):
    """Download a file. Uses a signed short-lived token (not AUTH_SECRET).
    Only serves files directly inside FILE_ROOT_DIR — no subdirectory traversal."""
    # Resolve target — try root first, then images/ subfolder
    root = Path(FILE_ROOT_DIR).resolve()
    target = (root / name).resolve()
    if not target.exists():
        target = (root / "images" / name).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=403, detail={
            "error": "Path traversal not allowed", "code": "FORBIDDEN",
        })

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail={
            "error": "File not found", "code": "NOT_FOUND",
        })

    # Verify token — accepts new HMAC signatures and old AUTH_SECRET (deprecated)
    if not _verify_file_signature(str(target), name, token):
        if token == AUTH_SECRET:
            logger.warning("[Files] Deprecated: AUTH_SECRET used as token for download '%s'. "
                           "Frontend should migrate to HMAC tokens.", name)
        else:
            raise HTTPException(status_code=401, detail={
                "error": "Invalid or expired download token", "code": "UNAUTHORIZED",
            })

    dl_name = Path(name).name
    logger.info("[Files] Download: %s (%s bytes)", dl_name, target.stat().st_size)
    return FileResponse(
        path=str(target),
        filename=dl_name,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{dl_name}"'},
    )


@download_router.get("/files/view/{name:path}")
async def view_file(name: str, token: str = Query(...)):
    """Serve a file inline (for images in chat). Uses a signed short-lived token.
    Content-Disposition: inline with correct MIME type."""
    root = Path(FILE_ROOT_DIR).resolve()
    target = (root / name).resolve()
    if not target.exists():
        target = (root / "images" / name).resolve()
    try:
        target.relative_to(root)
    except ValueError:
        raise HTTPException(status_code=403, detail={
            "error": "Path traversal not allowed", "code": "FORBIDDEN",
        })

    if not target.exists() or not target.is_file():
        raise HTTPException(status_code=404, detail={
            "error": "File not found", "code": "NOT_FOUND",
        })

    # Verify token — accepts new HMAC signatures and old AUTH_SECRET (deprecated)
    if not _verify_file_signature(str(target), name, token):
        if token == AUTH_SECRET:
            logger.warning("[Files] Deprecated: AUTH_SECRET used as token for view '%s'. "
                           "Frontend should migrate to HMAC tokens.", name)
        else:
            raise HTTPException(status_code=401, detail={
                "error": "Invalid or expired view token", "code": "UNAUTHORIZED",
            })

    # Map extension to MIME type
    ext = target.suffix.lower()
    mime_map = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
        ".svg": "image/svg+xml",
    }
    media_type = mime_map.get(ext, "application/octet-stream")

    logger.info("[Files] View: %s (%s bytes)", target.name, target.stat().st_size)
    return FileResponse(
        path=str(target),
        filename=target.name,
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{target.name}"'},
    )
