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
from config import DEEPSEEK_CC_SWITCH_DB, DEEPSEEK_PROVIDER_UUID
from logger import logger

router = APIRouter(tags=["system"], dependencies=[Depends(verify_token)])

_START_TIME = time.time()

# ── DeepSeek balance cache ────────────── (for /system/status polling)
_balance_cache = None       # cached dict or None
_balance_cache_at = 0.0     # timestamp of last fetch
BALANCE_CACHE_TTL = 60      # seconds — avoid hitting DeepSeek API on every poll


def _read_version_json():
    """Read version.json. Returns "0.0.0" if missing."""
    import json as _json
    vp = BASE_DIR / "version.json"
    try:
        return _json.loads(vp.read_text(encoding="utf-8")).get("version", "0.0.0")
    except Exception:
        return "0.0.0"


async def _get_deepseek_balance() -> dict:
    """Query DeepSeek balance via API. BUGFIX #11: paths now from config, not hardcoded."""
    try:
        import os as _os
        cc_db = Path(DEEPSEEK_CC_SWITCH_DB)

        # ── Path safety check ──────────────────────────────
        # Only allow paths inside ~/.cc-switch/ (prevents reading arbitrary SQLite files)
        allowed_parents = [
            Path.home() / ".cc-switch",
        ]
        resolved = cc_db.resolve()
        is_allowed = any(
            resolved == p.resolve() or str(resolved).startswith(str(p.resolve()) + _os.sep)
            for p in allowed_parents
        ) or resolved == Path.home() / ".cc-switch" / "cc-switch.db"
        if not is_allowed:
            logger.warning(
                "[System] DeepSeek balance query blocked — "
                "DEEPSEEK_CC_SWITCH_DB outside ~/.cc-switch/: %s", resolved
            )
            return {}
        # ────────────────────────────────────────────────────

        if not cc_db.exists():
            return {}
        conn = sqlite3.connect(str(cc_db))
        row = conn.execute(
            "SELECT settings_config FROM providers WHERE id=?",
            (DEEPSEEK_PROVIDER_UUID,)
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


async def _get_balance_cached(force: bool = False) -> dict:
    """Cached balance query. force=True bypasses cache."""
    global _balance_cache, _balance_cache_at
    if not force and _balance_cache is not None and (time.time() - _balance_cache_at) < BALANCE_CACHE_TTL:
        return _balance_cache
    _balance_cache = await _get_deepseek_balance()
    _balance_cache_at = time.time()
    return _balance_cache


async def _build_status() -> dict:
    """Lightweight status snapshot — no DB I/O, no external API (balance cached)."""
    uptime_val = time.time() - _START_TIME
    hours = int(uptime_val // 3600)
    mins = int((uptime_val % 3600) // 60)
    secs = int(uptime_val % 60)

    try:
        from services.claude_client import get_session_manager
        pool = get_session_manager().stats()
    except Exception:
        pool = {"total": 0, "alive": 0, "sessions": []}

    try:
        from services.streaming import StreamingStore
        streaming_stats = StreamingStore.stats()
    except Exception:
        streaming_stats = {"active": 0, "sessions": []}

    return {
        "port": PORT,
        "uptime": f"{hours}h {mins}m {secs}s",
        "pool": pool,
        "streaming": streaming_stats,
        "deepseek_balance": await _get_balance_cached(force=False),
    }


@router.get("/system/status")
async def system_status():
    """Lightweight status — safe for 3s polling. Balance cached 60s."""
    return await _build_status()


@router.post("/system/refresh-balance")
async def refresh_balance():
    """Force-refresh DeepSeek balance cache."""
    data = await _get_balance_cached(force=True)
    logger.info("[System] Balance cache refreshed — balance=%s", data.get("balance", "?"))
    return {"status": "ok", "deepseek_balance": data}


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

    # Streaming session stats
    try:
        from services.streaming import StreamingStore
        streaming_stats = StreamingStore.stats()
    except Exception:
        streaming_stats = {"active": 0, "sessions": []}

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
        "streaming": streaming_stats,
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
    conv_id = body.get("conversation_id", "")
    if not conv_id:
        raise HTTPException(status_code=400, detail={"error": "conversation_id required", "code": "BAD_REQUEST"})
    from services.claude_client import get_session_manager
    mgr = get_session_manager()
    sp = mgr._sessions.get(conv_id)
    if sp:
        await mgr.close_session(conv_id)
        logger.info("[System] Session %s stopped by user", conv_id[:8])
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
    from config import SESSION_IDLE_TIMEOUT_MINUTES, BYPASS_PERMISSIONS
    from config import MAX_MESSAGE_LENGTH_ENABLED, MAX_MESSAGE_LENGTH, AUTO_CHECK_UPDATE
    return {
        "session_timeout_minutes": SESSION_TIMEOUT_MINUTES,
        "console_mirror": CONSOLE_MIRROR,
        "file_root_dir": FILE_ROOT_DIR,
        "max_file_size_mb": MAX_FILE_SIZE_MB,
        "session_idle_timeout_minutes": SESSION_IDLE_TIMEOUT_MINUTES,
        "bypass_permissions": BYPASS_PERMISSIONS,
        "message_length_limit_enabled": MAX_MESSAGE_LENGTH_ENABLED,
        "message_length_limit": MAX_MESSAGE_LENGTH,
        "auto_check_update": AUTO_CHECK_UPDATE,
        "version": _read_version_json(),
    }


@router.post("/system/config")
async def update_config(body: dict):
    """Update runtime config (writes to .env)."""
    timeout = body.get("session_timeout_minutes")
    idle_timeout = body.get("session_idle_timeout_minutes")
    mirror = body.get("console_mirror")
    file_root = body.get("file_root_dir")
    max_fsize = body.get("max_file_size_mb")
    bypass_perms = body.get("bypass_permissions")  # bool or None
    msg_limit_enabled = body.get("message_length_limit_enabled")  # bool or None
    msg_limit_val = body.get("message_length_limit")             # int or None
    auto_check = body.get("auto_check_update")                   # bool or None

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

    # BUGFIX #6: import config once at module level, update ALL 5 config vars consistently
    import config as cfg

    for line in lines:
        if timeout is not None and line.startswith("SESSION_TIMEOUT_MINUTES="):
            new_lines.append(f"SESSION_TIMEOUT_MINUTES={timeout}")
            cfg.SESSION_TIMEOUT_MINUTES = timeout
        elif mirror is not None and line.startswith("CONSOLE_MIRROR="):
            val = "true" if mirror else "false"
            new_lines.append(f"CONSOLE_MIRROR={val}")
            cfg.CONSOLE_MIRROR = mirror
        elif idle_timeout is not None and line.startswith("SESSION_IDLE_TIMEOUT_MINUTES="):
            new_lines.append(f"SESSION_IDLE_TIMEOUT_MINUTES={idle_timeout}")
            cfg.SESSION_IDLE_TIMEOUT_MINUTES = idle_timeout
        elif file_root is not None and line.startswith("FILE_ROOT_DIR="):
            new_lines.append(f"FILE_ROOT_DIR={file_root}")
            cfg.FILE_ROOT_DIR = file_root
        elif max_fsize is not None and line.startswith("MAX_FILE_SIZE_MB="):
            new_lines.append(f"MAX_FILE_SIZE_MB={max_fsize}")
            cfg.MAX_FILE_SIZE_MB = max_fsize
            cfg.MAX_FILE_SIZE_BYTES = max_fsize * 1024 * 1024
        elif bypass_perms is not None and line.startswith("BYPASS_PERMISSIONS="):
            val = "true" if bypass_perms else "false"
            new_lines.append(f"BYPASS_PERMISSIONS={val}")
            cfg.BYPASS_PERMISSIONS = bypass_perms
        # Backward compat — also update old key if present
        elif bypass_perms is not None and line.startswith("CLAUDE_PERMISSION_MODE="):
            val = "true" if bypass_perms else "false"
            new_lines.append(f"BYPASS_PERMISSIONS={val}")
            cfg.BYPASS_PERMISSIONS = bypass_perms
        elif msg_limit_enabled is not None and line.startswith("MAX_MESSAGE_LENGTH_ENABLED="):
            val = "true" if msg_limit_enabled else "false"
            new_lines.append(f"MAX_MESSAGE_LENGTH_ENABLED={val}")
            cfg.MAX_MESSAGE_LENGTH_ENABLED = msg_limit_enabled
        elif msg_limit_val is not None and line.startswith("MAX_MESSAGE_LENGTH="):
            v = int(msg_limit_val)
            if v < 1000 or v > 500000:
                raise HTTPException(status_code=400, detail={
                    "error": "MAX_MESSAGE_LENGTH must be 1000-500000", "code": "BAD_REQUEST",
                })
            new_lines.append(f"MAX_MESSAGE_LENGTH={v}")
            cfg.MAX_MESSAGE_LENGTH = v
        elif auto_check is not None and line.startswith("AUTO_CHECK_UPDATE="):
            val = "true" if auto_check else "false"
            new_lines.append(f"AUTO_CHECK_UPDATE={val}")
            cfg.AUTO_CHECK_UPDATE = auto_check
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
    if bypass_perms is not None:
        result["bypass_permissions"] = bypass_perms
        logger.info("[System] Bypass permissions = %s", bypass_perms)
    if msg_limit_enabled is not None:
        result["message_length_limit_enabled"] = msg_limit_enabled
        logger.info("[System] Message length limit enabled = %s", msg_limit_enabled)
    if msg_limit_val is not None:
        result["message_length_limit"] = msg_limit_val
        logger.info("[System] Message length limit = %s", msg_limit_val)
    if auto_check is not None:
        result["auto_check_update"] = auto_check
        logger.info("[System] Auto check update = %s", auto_check)
    return result


@router.get("/system/events")
async def get_events(since: int = 0):
    """Return recent system events (session kills, etc). Pass ?since=N to get events after index N."""
    from services.claude_client import get_system_events
    events = get_system_events()
    if since >= len(events):
        return {"events": [], "next_since": since}
    return {"events": events[since:], "next_since": len(events)}


@router.post("/system/migrate-images")
async def migrate_images():
    """Move all image files from FILE_ROOT_DIR into images/ subfolder.
    Updates the files table stored_path for each moved file."""
    from config import FILE_ROOT_DIR
    import sqlite3
    from config import DB_PATH

    root = Path(FILE_ROOT_DIR)
    img_dir = root / "images"
    img_dir.mkdir(parents=True, exist_ok=True)

    image_exts = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
    moved = 0

    for f in root.iterdir():
        if not f.is_file():
            continue
        if f.suffix.lower() not in image_exts:
            continue
        dest = img_dir / f.name
        # Skip if dest exists (avoid collision — keep newer)
        if dest.exists():
            logger.warning(f"[Migrate] Skip {f.name} — already in images/")
            continue
        try:
            shutil.move(str(f), str(dest))
            moved += 1
            logger.info(f"[Migrate] {f.name} → images/")
        except Exception as e:
            logger.error(f"[Migrate] Failed {f.name}: {e}")

    # Update DB — change stored_path from root → images/ for moved files
    if moved > 0:
        try:
            conn = sqlite3.connect(DB_PATH)
            # Update all image paths that are in root (not already in a subdir)
            for ext in image_exts:
                conn.execute(
                    "UPDATE files SET stored_path = REPLACE(stored_path, ?, ?) "
                    "WHERE stored_path LIKE ? AND stored_path NOT LIKE ?",
                    (str(root) + "\\", str(img_dir) + "\\",
                     str(root) + "\\%" + ext, str(img_dir) + "\\%"),
                )
            conn.commit()
            conn.close()
        except Exception as e:
            logger.error(f"[Migrate] DB update failed: {e}")

    return {"moved": moved, "message": f"已整理 {moved} 张图片 → images/"}

@router.post("/system/restart")
async def restart_server():
    """Spawn restart.bat and exit."""
    base = Path(__file__).resolve().parent.parent
    bat = base / "restart.bat"
    if not bat.exists():
        raise HTTPException(status_code=500, detail={"error": "restart.bat not found", "code": "SYSTEM_ERROR"})

    logger.info("[System] Restart triggered — spawning restart.bat")
    subprocess.Popen(
        ["cmd.exe", "/c", str(bat)],
        cwd=str(base),
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
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
        ["cmd.exe", "/c", str(bat)],
        cwd=str(base),
        creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
    )
    return {"restarting": True, "message": "Server restarting gracefully. Refresh page in 5 seconds."}
