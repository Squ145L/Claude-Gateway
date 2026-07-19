"""File upload, download, and content API."""
import os
import uuid
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, Query
from fastapi.responses import FileResponse, PlainTextResponse
from api.auth import verify_token
from db.store import save_file_record, get_file_record, FileRecord
from config import FILE_ROOT_DIR, MAX_FILE_SIZE_BYTES, ALLOWED_EXTENSIONS
from logger import logger

router = APIRouter(tags=["files"], dependencies=[Depends(verify_token)])

# Separate router for download — uses query-token auth instead of Bearer header
download_router = APIRouter(tags=["files"])

# Image extensions — stored in images/ subfolder for preview
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}


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
    """Download a file from FILE_ROOT_DIR. Requires auth token in query string.
    Only serves files directly inside FILE_ROOT_DIR — no subdirectory traversal."""
    # Auth check via query token
    from config import AUTH_SECRET
    if token != AUTH_SECRET:
        raise HTTPException(status_code=401, detail={"error": "Invalid token", "code": "UNAUTHORIZED"})

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

    dl_name = Path(name).name
    logger.info(f"[Files] Download: {dl_name} ({target.stat().st_size} bytes)")
    return FileResponse(
        path=str(target),
        filename=dl_name,
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{dl_name}"'},
    )


@download_router.get("/files/view/{name:path}")
async def view_file(name: str, token: str = Query(...)):
    """Serve a file inline (for images in chat). Same security as download but
    uses Content-Disposition: inline with correct MIME type."""
    from config import AUTH_SECRET
    if token != AUTH_SECRET:
        raise HTTPException(status_code=401, detail={"error": "Invalid token", "code": "UNAUTHORIZED"})

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

    # Map extension to MIME type
    ext = target.suffix.lower()
    mime_map = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
        ".svg": "image/svg+xml",
    }
    media_type = mime_map.get(ext, "application/octet-stream")

    logger.info(f"[Files] View: {target.name} ({target.stat().st_size} bytes)")
    return FileResponse(
        path=str(target),
        filename=target.name,
        media_type=media_type,
        headers={"Content-Disposition": f'inline; filename="{target.name}"'},
    )
