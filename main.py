"""
Claude Gateway — FastAPI entry point.

Start: uvicorn main:app --host 0.0.0.0 --port 8080
"""
import uuid
import time
import asyncio
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from config import PORT, HOST
from logger import logger
from db.store import init_db


async def cleanup_stale_streams():
    """Background task — force-pop StreamingSessions stuck in draining/cancelled
    for longer than the configured timeout.  This is the safety net for the
    safety net: if the finally block in chat.py also fails, this cleans up."""
    from services.streaming import StreamingStore, StreamStatus
    from config import SESSION_IDLE_TIMEOUT_MINUTES
    timeout = SESSION_IDLE_TIMEOUT_MINUTES * 60 if SESSION_IDLE_TIMEOUT_MINUTES > 0 else 300
    logger.info("[StreamStore] Cleanup task started (timeout=%ss, interval=30s)", timeout)
    while True:
        await asyncio.sleep(30)
        try:
            now = __import__('time').time()
            stale = []
            for cid, s in list(StreamingStore._sessions.items()):
                if s.status in (StreamStatus.DRAINING, StreamStatus.CANCELLED):
                    if now - s.created_at > timeout:
                        stale.append((cid, s.msg_id, s.status.value))
            if stale:
                logger.warning("[StreamStore] Cleanup found %s stale sessions (total=%s)",
                               len(stale), len(StreamingStore._sessions))
            for cid, mid, st in stale:
                logger.warning("[StreamStore] Cleanup force-popping stale session %s msg=%s status=%s age=%ss",
                               cid[:8], mid, st, round(now - StreamingStore._sessions[cid].created_at, 1) if cid in StreamingStore._sessions else '?')
                StreamingStore._sessions.pop(cid, None)
        except Exception as e:
            logger.error("[StreamStore] Cleanup error: %s", e)


async def cleanup_expired_files():
    """Background task — delete expired files every hour."""
    while True:
        await asyncio.sleep(3600)
        try:
            from db.store import get_expired_files, delete_file_record
            from config import FILE_ROOT_DIR
            expired = await get_expired_files()
            for rec in expired:
                try:
                    Path(rec.stored_path).unlink(missing_ok=True)
                except Exception:
                    pass
                await delete_file_record(rec.id)
            if expired:
                logger.info(f"[Cleanup] Removed {len(expired)} expired files")
        except Exception as e:
            logger.error(f"[Cleanup] Error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown lifecycle."""
    # Global asyncio exception handler — prevents silent crashes
    loop = asyncio.get_event_loop()
    loop.set_exception_handler(lambda l, ctx: logger.error(
        f"[AsyncIO] Unhandled exception: {ctx.get('message','?')} {ctx.get('exception','')}"
    ))
    logger.info("=" * 50)
    logger.info("Claude Gateway starting...")
    init_db()
    logger.info("Database initialized")
    logger.info(f"File storage: {__import__('config').FILE_ROOT_DIR}")
    logger.info(f"Listening on http://{HOST}:{PORT}")
    logger.info("=" * 50)
    asyncio.create_task(cleanup_expired_files())
    asyncio.create_task(cleanup_stale_streams())
    # Start persistent claude session pool
    from services.claude_client import get_session_manager
    session_mgr = get_session_manager()
    await session_mgr.start_cleanup()
    logger.info("Session pool started")
    yield
    logger.info("Claude Gateway shutting down...")
    await session_mgr.close_all()


app = FastAPI(
    title="Claude Gateway",
    version="1.0.0",
    lifespan=lifespan,
    request_max_size=10 * 1024 * 1024,  # 10MB — reject oversized request bodies
)

# CORS — allow all origins (auth handles security)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,   # Bearer token auth doesn't rely on cookies; compatible with allow_origins=["*"]
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═══════════════════════════════════════════════════════════
# Security headers middleware
# ═══════════════════════════════════════════════════════════

@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=()"
    )
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data: blob:; "
        "connect-src 'self'; "
        "font-src 'self'; "
        "manifest-src 'self'; "
        "worker-src 'self'"
    )
    return response


# Rate limit middleware
from api.ratelimit import rate_limit  # noqa: E402

app.middleware("http")(rate_limit)


# Request ID middleware
@app.middleware("http")
async def add_request_id(request: Request, call_next):
    req_id = str(uuid.uuid4())[:8]
    request.state.req_id = req_id
    start = time.monotonic()
    response = await call_next(request)
    elapsed = time.monotonic() - start
    logger.info(
        "[%s] %s %s → %d (%.2fs)",
        req_id, request.method, request.url.path,
        response.status_code, elapsed,
    )
    response.headers["X-Request-ID"] = req_id
    return response


# Mount static files (PWA)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    """Redirect to PWA."""
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/static/index.html")


@app.get("/sw.js")
async def service_worker():
    """Serve Service Worker from root so scope '/' is valid."""
    from fastapi.responses import FileResponse
    return FileResponse("static/sw.js", media_type="application/javascript")


# Register API routers (imports after app creation to avoid circular imports)
from api.auth import router as auth_router              # noqa: E402
from api.chat import router as chat_router              # noqa: E402
from api.conversations import router as conv_router     # noqa: E402
from api.files import router as files_router            # noqa: E402
from api.files import download_router                   # noqa: E402
from api.health import router as health_router          # noqa: E402
# from api.esp32 import router as esp32_router          # noqa: E402 — reserved for future ESP32/MCU
from api.system import router as system_router          # noqa: E402
from api.update import router as update_router          # noqa: E402

app.include_router(auth_router, prefix="/api")
app.include_router(chat_router, prefix="/api")
app.include_router(conv_router, prefix="/api")
app.include_router(files_router, prefix="/api")
app.include_router(download_router, prefix="/api")
app.include_router(health_router, prefix="/api")
# app.include_router(esp32_router, prefix="/api")  # reserved for future ESP32/MCU
app.include_router(system_router, prefix="/api")
app.include_router(update_router, prefix="/api")
