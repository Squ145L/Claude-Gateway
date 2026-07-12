"""System management endpoints — info, logs, cleanup, restart."""
import asyncio
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import aiohttp

from fastapi import APIRouter, Depends, HTTPException
from api.auth import verify_token
from config import DB_PATH, LOG_DIR, FILE_ROOT_DIR, BASE_DIR, PORT
from logger import logger

router = APIRouter(tags=["system"], dependencies=[Depends(verify_token)])

_START_TIME = time.time()


async def _get_deepseek_balance() -> dict:
    """Query DeepSeek balance via API. Returns {'balance':..., 'currency':...} or {} on failure."""
    try:
        # Read API key from CC Switch DB
        cc_db = Path.home() / ".cc-switch" / "cc-switch.db"
        if not cc_db.exists():
            return {}
        conn = sqlite3.connect(str(cc_db))
        row = conn.execute(
            "SELECT settings_config FROM providers WHERE id='47bb5ec7-8465-4098-a5a0-8c2df7f15643'"
        ).fetchone()
        conn.close()
        if not row:
            return {}
        import json
        config = json.loads(row[0])
        api_key = config.get("env", {}).get("ANTHROPIC_AUTH_TOKEN", "")
        if not api_key:
            return {}

        async with aiohttp.ClientSession() as session:
            async with session.get(
                "https://api.deepseek.com/user/balance",
                headers={"Authorization": f"Bearer {api_key}"},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    bal = data.get("balance_infos", [{}])
                    if bal:
                        b = bal[0]
                        return {
                            "balance": b.get("total_balance", "?"),
                            "currency": b.get("currency", "CNY"),
                            "topped_up": b.get("topped_up_balance", "?"),
                        }
    except Exception:
        pass
    return {}


@router.get("/system/info")
async def system_info():
    """Detailed system information."""
    # DB stats
    try:
        conn = sqlite3.connect(DB_PATH)
        conv_count = conn.execute("SELECT COUNT(*) FROM conversations").fetchone()[0]
        msg_count = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        db_size = os.path.getsize(DB_PATH)
        conn.close()
    except Exception:
        conv_count = msg_count = db_size = -1

    # File stats
    file_dir = Path(FILE_ROOT_DIR)
    file_count = 0
    file_size = 0
    if file_dir.exists():
        for f in file_dir.iterdir():
            if f.is_file():
                file_count += 1
                try:
                    file_size += f.stat().st_size
                except Exception:
                    pass

    # Uptime
    uptime = time.time() - _START_TIME
    hours = int(uptime // 3600)
    mins = int((uptime % 3600) // 60)
    secs = int(uptime % 60)

    # Session pool stats
    try:
        from services.claude_client import get_session_manager
        pool = get_session_manager().stats()
    except Exception:
        pool = {"total": 0, "alive": 0, "sessions": []}

    # DeepSeek balance (async, non-blocking)
    deepseek_balance = await _get_deepseek_balance()

    return {
        "status": "ok",
        "port": PORT,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "uptime": f"{hours}h {mins}m {secs}s",
        "claude_cli": shutil.which("claude") or shutil.which("claude.cmd") or "not found",
        "deepseek_balance": deepseek_balance or None,
        "pool": pool,
        "db": {
            "conversations": conv_count,
            "messages": msg_count,
            "size_mb": round(db_size / 1024 / 1024, 2) if db_size > 0 else 0,
        },
        "files": {
            "count": file_count,
            "size_mb": round(file_size / 1024 / 1024, 2),
            "dir": str(FILE_ROOT_DIR),
        },
    }


@router.post("/system/clear-conversations")
async def clear_conversations():
    """Delete all conversations and messages."""
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("DELETE FROM messages")
        conn.execute("DELETE FROM conversations")
        conn.commit()
        conn.close()
        logger.info("[System] All conversations cleared")
        return {"cleared": True, "message": "All conversations deleted"}
    except Exception as e:
        logger.error(f"[System] Clear failed: {e}")
        raise HTTPException(status_code=500, detail={"error": str(e), "code": "SYSTEM_ERROR"})


@router.get("/system/logs")
async def view_logs(lines: int = 50):
    """Read recent log entries."""
    log_file = LOG_DIR / "claude-gateway.log"
    if not log_file.exists():
        return {"logs": [], "message": "No log file found"}

    try:
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            all_lines = f.readlines()
        recent = all_lines[-lines:] if len(all_lines) > lines else all_lines
        return {"logs": [l.rstrip("\n") for l in recent], "total_lines": len(all_lines)}
    except Exception as e:
        raise HTTPException(status_code=500, detail={"error": str(e), "code": "SYSTEM_ERROR"})


@router.post("/system/clean-cache")
async def clean_cache():
    """Clear Python __pycache__ directories."""
    base = Path(__file__).resolve().parent.parent
    removed = 0
    for d in base.rglob("__pycache__"):
        try:
            shutil.rmtree(d)
            removed += 1
        except Exception:
            pass
    for f in base.rglob("*.pyc"):
        try:
            f.unlink()
            removed += 1
        except Exception:
            pass
    logger.info(f"[System] Cleaned {removed} cache items")
    return {"cleaned": removed, "message": f"Removed {removed} cache entries. Restart server to apply."}


@router.post("/system/stop-session")
async def stop_session(body: dict):
    """Kill a specific claude session by conversation_id."""
    from services.claude_client import _sessions
    conv_id = body.get("conversation_id", "")
    if not conv_id:
        raise HTTPException(status_code=400, detail={"error": "conversation_id required", "code": "BAD_REQUEST"})
    if conv_id in _sessions:
        try:
            _sessions[conv_id]["process"].kill()
        except Exception:
            pass
        del _sessions[conv_id]
        logger.info(f"[System] Session {conv_id[:8]} stopped by user")
        return {"stopped": True, "conversation_id": conv_id}
    return {"stopped": False, "message": "Session not found"}


@router.post("/system/clear-logs")
async def clear_logs():
    """Truncate the log file."""
    log_file = LOG_DIR / "claude-gateway.log"
    if log_file.exists():
        log_file.write_text("", encoding="utf-8")
    logger.info("[System] Logs cleared")
    return {"cleared": True}


@router.get("/system/config")
async def get_config():
    """Return current config values."""
    from config import SESSION_TIMEOUT_MINUTES, CONSOLE_MIRROR, FILE_ROOT_DIR, MAX_FILE_SIZE_MB
    from config import SESSION_IDLE_TIMEOUT_MINUTES
    return {
        "session_timeout_minutes": SESSION_TIMEOUT_MINUTES,
        "console_mirror": CONSOLE_MIRROR,
        "file_root_dir": FILE_ROOT_DIR,
        "max_file_size_mb": MAX_FILE_SIZE_MB,
        "session_idle_timeout_minutes": SESSION_IDLE_TIMEOUT_MINUTES,
    }


@router.post("/system/config")
async def update_config(body: dict):
    """Update runtime config (writes to .env)."""
    timeout = body.get("session_timeout_minutes")
    idle_timeout = body.get("session_idle_timeout_minutes")
    mirror = body.get("console_mirror")
    file_root = body.get("file_root_dir")
    max_fsize = body.get("max_file_size_mb")

    env_path = BASE_DIR / ".env"
    lines = env_path.read_text(encoding="utf-8").splitlines()
    new_lines = []

    if timeout is not None:
        timeout = int(timeout)
        if timeout not in (0, 30, 60):
            raise HTTPException(status_code=400, detail={"error": "Timeout must be 0, 30, or 60", "code": "BAD_REQUEST"})
    if mirror is not None and not isinstance(mirror, bool):
        raise HTTPException(status_code=400, detail={"error": "console_mirror must be boolean", "code": "BAD_REQUEST"})
    if idle_timeout is not None:
        idle_timeout = int(idle_timeout)
        if idle_timeout < 0 or idle_timeout > 120:
            raise HTTPException(status_code=400, detail={"error": "session_idle_timeout_minutes must be 0-120", "code": "BAD_REQUEST"})
    if max_fsize is not None:
        max_fsize = int(max_fsize)
        if max_fsize < 1 or max_fsize > 500:
            raise HTTPException(status_code=400, detail={"error": "max_file_size_mb must be 1-500", "code": "BAD_REQUEST"})

    for line in lines:
        if timeout is not None and line.startswith("SESSION_TIMEOUT_MINUTES="):
            new_lines.append(f"SESSION_TIMEOUT_MINUTES={timeout}")
        elif mirror is not None and line.startswith("CONSOLE_MIRROR="):
            val = "true" if mirror else "false"
            new_lines.append(f"CONSOLE_MIRROR={val}")
            import config
            config.CONSOLE_MIRROR = mirror
        elif idle_timeout is not None and line.startswith("SESSION_IDLE_TIMEOUT_MINUTES="):
            new_lines.append(f"SESSION_IDLE_TIMEOUT_MINUTES={idle_timeout}")
            import config
            config.SESSION_IDLE_TIMEOUT_MINUTES = idle_timeout
        elif file_root is not None and line.startswith("FILE_ROOT_DIR="):
            new_lines.append(f"FILE_ROOT_DIR={file_root}")
            import config
            config.FILE_ROOT_DIR = file_root
        elif max_fsize is not None and line.startswith("MAX_FILE_SIZE_MB="):
            new_lines.append(f"MAX_FILE_SIZE_MB={max_fsize}")
            import config
            config.MAX_FILE_SIZE_MB = max_fsize
            config.MAX_FILE_SIZE_BYTES = max_fsize * 1024 * 1024
        else:
            new_lines.append(line)
    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")

    result = {}
    if timeout is not None:
        result["session_timeout_minutes"] = timeout
        logger.info(f"[System] Timeout updated to {timeout}m")
    if idle_timeout is not None:
        result["session_idle_timeout_minutes"] = idle_timeout
        logger.info(f"[System] Idle timeout = {idle_timeout}m")
    if mirror is not None:
        result["console_mirror"] = mirror
        logger.info(f"[System] Console mirror = {mirror}")
    if file_root is not None:
        result["file_root_dir"] = file_root
        logger.info(f"[System] File root dir = {file_root}")
    if max_fsize is not None:
        result["max_file_size_mb"] = max_fsize
        logger.info(f"[System] Max file size = {max_fsize}MB")
    return result


@router.get("/system/events")
async def get_events(since: int = 0):
    """Return recent system events (session kills, etc). Pass ?since=N to get events after index N."""
    from services.claude_client import get_system_events
    events = get_system_events()
    if since >= len(events):
        return {"events": [], "next_since": since}
    return {"events": events[since:], "next_since": len(events)}


@router.post("/system/restart")
async def restart_server():
    """Spawn restart.bat and exit."""
    base = Path(__file__).resolve().parent.parent
    bat = base / "restart.bat"
    if not bat.exists():
        raise HTTPException(status_code=500, detail={"error": "restart.bat not found", "code": "SYSTEM_ERROR"})

    logger.info("[System] Restart triggered — spawning restart.bat")
    subprocess.Popen(
        [str(bat)],
        cwd=str(base),
        creationflags=subprocess.CREATE_NEW_CONSOLE | subprocess.DETACHED_PROCESS,
        shell=True,
    )
    return {"restarting": True, "message": "Server restarting in background. Refresh page in 3 seconds."}


@router.post("/system/soft-restart")
async def soft_restart_server():
    """Graceful restart — no force-kill, lets shutdown handlers run cleanly."""
    base = Path(__file__).resolve().parent.parent
    bat = base / "soft-restart.bat"
    if not bat.exists():
        raise HTTPException(status_code=500, detail={"error": "soft-restart.bat not found", "code": "SYSTEM_ERROR"})

    logger.info("[System] Soft restart triggered — spawning soft-restart.bat")
    subprocess.Popen(
        [str(bat)],
        cwd=str(base),
        creationflags=subprocess.CREATE_NEW_CONSOLE | subprocess.DETACHED_PROCESS,
        shell=True,
    )
    return {"restarting": True, "message": "Server restarting gracefully. Refresh page in 5 seconds."}
