"""
StreamingSession state machine — the single source of truth for in-flight messages.

Lifecycle:
  create() → THINKING → (append_thinking × N) → GENERATING → (append_text × N) → finalize()
      ↓                       ↓                         ↓
  CANCELLED               DRAINING                DRAINING (client disconnected)
                              ↓                         ↓
                          finalize()               finalize()

Every append_*() writes to IN-MEMORY immediately.  sync_to_db() flushes to SQLite
periodically (~1/s).  The API (conversations.py) reads the in-memory state via
StreamingStore.get() and merges it over any stale DB values.

This eliminates the old pattern of closure-variable spaghetti in chat.py's
event_generator() and the fragile frontend heuristics for detecting in-progress
messages.
"""
from __future__ import annotations

import time
import json
import asyncio
from enum import Enum
from typing import Optional

from logger import logger


class StreamStatus(str, Enum):
    THINKING   = "thinking"    # Claude is thinking, no text output yet
    GENERATING = "generating"  # Claude is producing text
    DRAINING   = "draining"    # Client disconnected, still reading from Claude
    AWAITING_AGENT = "awaiting_agent"  # result received but bg agent still running
    FINALIZED  = "finalized"   # Message complete and saved to DB
    CANCELLED  = "cancelled"   # User sent a new message before this one finished


class StreamingSession:
    """One in-flight assistant message.  All state is in memory; DB sync is
    via StreamingStore.sync_to_db() and finalize()."""

    __slots__ = (
        "conv_id", "msg_id", "status", "thinking_parts", "text_parts",
        "thinking_start", "usage", "created_at", "last_sync_at",
    )

    def __init__(self, conv_id: str, msg_id: int):
        self.conv_id       = conv_id
        self.msg_id        = msg_id
        self.status        = StreamStatus.THINKING
        self.thinking_parts: list[str] = []
        self.text_parts:   list[str] = []
        self.thinking_start: Optional[float] = None
        self.usage:        dict = {}
        self.created_at    = time.time()
        self.last_sync_at  = 0.0

    # ── properties ──────────────────────────────────────────

    @property
    def thinking(self) -> str:
        return "".join(self.thinking_parts).strip()

    @property
    def content(self) -> str:
        return "".join(self.text_parts).strip()

    @property
    def thinking_dur(self) -> Optional[str]:
        if not self.thinking or self.thinking_start is None:
            return None
        dur = time.time() - self.thinking_start
        if dur >= 60:
            return f"{int(dur // 60)}m {int(dur % 60)}s"
        return f"{dur:.1f}s"

    @property
    def thinking_wc(self) -> int:
        return len(self.thinking.split()) if self.thinking else 0

    @property
    def token_usage_json(self) -> Optional[str]:
        return json.dumps(self.usage) if self.usage else None

    # ── append methods (memory only — no DB I/O) ────────────

    def append_thinking(self, chunk: str):
        if self.thinking_start is None:
            self.thinking_start = time.time()
        self.thinking_parts.append(chunk)

    def append_text(self, chunk: str):
        if self.status == StreamStatus.THINKING:
            self.status = StreamStatus.GENERATING
        self.text_parts.append(chunk)

    def set_usage(self, input_tokens: int, output_tokens: int):
        self.usage = {"i": input_tokens, "o": output_tokens}

    # ── status transitions ──────────────────────────────────

    def mark_draining(self):
        """Client disconnected — keep reading from Claude."""
        if self.status in (StreamStatus.THINKING, StreamStatus.GENERATING):
            self.status = StreamStatus.DRAINING

    def mark_cancelled(self):
        self.status = StreamStatus.CANCELLED

    def mark_finalized(self):
        self.status = StreamStatus.FINALIZED

    # ── serialisation for API ───────────────────────────────

    def to_api_dict(self) -> dict:
        """The `streaming` field returned by GET /api/conversations/{id}."""
        return {
            "msg_id":  self.msg_id,
            "status":  self.status.value,
            "thinking": self.thinking,
            "content": self.content,
        }


# ═══════════════════════════════════════════════════════════════
# StreamingStore — global in-memory registry
# ═══════════════════════════════════════════════════════════════

class StreamingStore:
    """Singleton registry of all active StreamingSessions.

    Usage:
        sess = await StreamingStore.create(conv_id, msg_id)
        sess.append_thinking("...")
        await StreamingStore.sync_to_db(conv_id)      # periodic flush
        await StreamingStore.finalize(conv_id)        # save to DB + pop
    """

    _sessions: dict[str, StreamingSession] = {}
    _lock = asyncio.Lock()

    # ── factory ─────────────────────────────────────────────

    @classmethod
    async def create(cls, conv_id: str, msg_id: int) -> StreamingSession:
        """Create a new streaming session, cancelling any previous one
        for the same conversation."""
        # Cancel previous session if still alive
        async with cls._lock:
            if conv_id in cls._sessions:
                old = cls._sessions[conv_id]
                if old.status not in (StreamStatus.FINALIZED, StreamStatus.CANCELLED):
                    old.mark_cancelled()
                    await cls._db_cancel(old)
                    logger.info(
                        "[StreamStore] Cancelled old session conv=%s msg_id=%s",
                        conv_id[:8], old.msg_id,
                    )

            session = StreamingSession(conv_id, msg_id)
            cls._sessions[conv_id] = session
            logger.info(
                "[StreamStore] Created conv=%s msg_id=%s",
                conv_id[:8], msg_id,
            )
            return session

    # ── accessors ───────────────────────────────────────────

    @classmethod
    def get(cls, conv_id: str) -> Optional[StreamingSession]:
        """Return live session or None."""
        s = cls._sessions.get(conv_id)
        if s and s.status == StreamStatus.FINALIZED:
            logger.debug("[StreamStore] get(%s) → FINALIZED, returning None", conv_id[:8])
            return None
        if s:
            logger.debug("[StreamStore] get(%s) → status=%s thinking=%schars content=%schars",
                         conv_id[:8], s.status.value, len(s.thinking), len(s.content))
        return s

    @classmethod
    def get_api_state(cls, conv_id: str) -> Optional[dict]:
        """Return the streaming field dict for the API, or None."""
        s = cls.get(conv_id)
        return s.to_api_dict() if s else None

    @classmethod
    def active_count(cls) -> int:
        return sum(
            1 for s in cls._sessions.values()
            if s.status not in (StreamStatus.FINALIZED, StreamStatus.CANCELLED)
        )

    # ── DB sync ─────────────────────────────────────────────

    @classmethod
    async def sync_to_db(cls, conv_id: str) -> bool:
        """Flush in-memory thinking + content to SQLite.
        Throttled to ~1 write/second.  Returns True if a write happened."""
        s = cls._sessions.get(conv_id)
        if not s or s.status in (StreamStatus.FINALIZED, StreamStatus.CANCELLED):
            return False

        now = time.time()
        if now - s.last_sync_at < 1.0:
            return False
        s.last_sync_at = now

        from db.store import update_streaming_msg
        try:
            await update_streaming_msg(s.msg_id, s.thinking, s.content)
            return True
        except (asyncio.CancelledError, Exception) as exc:
            if isinstance(exc, asyncio.CancelledError):
                logger.warning("[StreamStore] sync_to_db cancelled conv=%s msg=%s",
                               conv_id[:8], s.msg_id)
            else:
                logger.error("[StreamStore] sync_to_db failed conv=%s msg=%s: %s",
                             conv_id[:8], s.msg_id, exc)
            return False

    @classmethod
    async def sync_to_db_force(cls, conv_id: str):
        """Unconditional DB sync (used before finalize)."""
        s = cls._sessions.get(conv_id)
        if not s or s.status in (StreamStatus.FINALIZED, StreamStatus.CANCELLED):
            return
        s.last_sync_at = 0  # reset throttle
        await cls.sync_to_db(conv_id)

    # ── finalize ────────────────────────────────────────────

    @classmethod
    async def finalize(cls, conv_id: str, msg_id: int):
        """Save final state to DB and remove from memory.
        
        Only finalizes if the current session's msg_id matches — prevents
        a cancelled event_generator from stealing another generator's session."""
        s = cls._sessions.get(conv_id)
        if not s:
            logger.debug("[StreamStore] finalize(%s) → no session, skip", conv_id[:8])
            return
        if s.msg_id != msg_id:
            logger.info("[StreamStore] finalize(%s) msg_id mismatch (expected=%s, actual=%s) → session was replaced, skip",
                         conv_id[:8], msg_id, s.msg_id)
            return
        # Remove from registry — only now we know it is ours
        del cls._sessions[conv_id]

        logger.info("[StreamStore] finalize(%s) msg=%s status=%s thinking=%schars content=%schars",
                     conv_id[:8], s.msg_id, s.status.value, len(s.thinking), len(s.content))
        s.mark_finalized()

        # If Claude produced thinking but no text, use thinking as content.
        # Otherwise the frontend sees content="" + thinking≠"" and falsely
        # treats the message as still-streaming (eternal thinking dots).
        content = s.content
        if not content and s.thinking:
            content = s.thinking

        # If BOTH thinking and content are empty, Claude produced nothing
        # (e.g. drain was killed before any chunk arrived).  Cancel rather
        # than finalize — an empty message is just noise in the chat.
        if not content and not s.thinking:
            logger.info("[StreamStore] finalize(%s) msg=%s — empty, cancelling",
                         conv_id[:8], s.msg_id)
            await cls._db_cancel(s)
            return

        from db.store import finalize_streaming_msg
        try:
            await finalize_streaming_msg(
                s.msg_id,
                s.thinking,
                content,
                s.thinking_dur or "",
                s.thinking_wc,
                s.token_usage_json or "",
            )
            logger.info(
                "[StreamStore] Finalized conv=%s msg=%s content_len=%s",
                conv_id[:8], s.msg_id, len(content),
            )
        except (asyncio.CancelledError, Exception) as exc:
            logger.error(
                "[StreamStore] finalize failed conv=%s msg=%s: %s",
                conv_id[:8], s.msg_id, exc,
            )

    # ── cancel ──────────────────────────────────────────────

    @classmethod
    async def _db_cancel(cls, session: StreamingSession):
        """Mark a streaming message as cancelled in the DB."""
        from db.store import cancel_streaming_msg
        try:
            await cancel_streaming_msg(session.msg_id)
        except (asyncio.CancelledError, Exception) as exc:
            logger.error("[StreamStore] cancel failed msg=%s: %s",
                         session.msg_id, exc)

    @classmethod
    async def cancel(cls, conv_id: str):
        """Cancel and remove a streaming session."""
        s = cls._sessions.pop(conv_id, None)
        if s and s.status not in (StreamStatus.FINALIZED, StreamStatus.CANCELLED):
            s.mark_cancelled()
            await cls._db_cancel(s)

    # ── stats for /api/system/info ──────────────────────────

    @classmethod
    def stats(cls) -> dict:
        return {
            "active": cls.active_count(),
            "sessions": [
                {
                    "conv_id": cid[:12],
                    "msg_id": s.msg_id,
                    "status": s.status.value,
                    "age_sec": round(time.time() - s.created_at, 1),
                }
                for cid, s in cls._sessions.items()
                if s.status not in (StreamStatus.FINALIZED, StreamStatus.CANCELLED)
            ],
        }
