"""Health check endpoint."""
import shutil
import sqlite3
from pathlib import Path
from fastapi import APIRouter
from config import DB_PATH

router = APIRouter(tags=["health"])


@router.get("/health")
async def health():
    result = {"status": "ok", "claude_cli": "unknown", "db": "unknown", "ocr": "unknown"}

    # Check DB
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("SELECT 1")
        conn.close()
        result["db"] = "ok"
    except Exception as e:
        result["db"] = f"error: {e}"
        result["status"] = "degraded"

    # Check Claude Code CLI
    claude_path = shutil.which("claude") or shutil.which("claude.cmd")
    if claude_path:
        result["claude_cli"] = f"found: {claude_path}"
    else:
        result["claude_cli"] = "not_found"
        result["status"] = "degraded"

    # Check OCR script existence
    OCR_SCRIPT = (
        Path(__file__).resolve().parent.parent.parent
        / ".claude" / "skills" / "ollama-vision" / "ocr.py"
    )
    result["ocr"] = "available" if OCR_SCRIPT.exists() else "script_missing"

    return result
