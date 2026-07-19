"""SQLite operations layer — thin async wrapper around aiosqlite."""
import json
import uuid
import aiosqlite
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from config import DB_PATH, FILE_TTL_HOURS
from db.models import Conversation, Message, FileRecord
from logger import logger

DB: Optional[aiosqlite.Connection] = None


def init_db():
    """Synchronous init — create tables on startup."""
    import sqlite3
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS conversations (
            id TEXT PRIMARY KEY,
            title TEXT DEFAULT 'New Chat',
            claude_session_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
    """)
    # Migration: add claude_session_id if missing
    try:
        conn.execute("SELECT claude_session_id FROM conversations LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE conversations ADD COLUMN claude_session_id TEXT")
    # Migration: add pinned if missing
    try:
        conn.execute("SELECT pinned FROM conversations LIMIT 1")
    except sqlite3.OperationalError:
        conn.execute("ALTER TABLE conversations ADD COLUMN pinned INTEGER DEFAULT 0")
    # MUST create messages table BEFORE column migration
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            conversation_id TEXT NOT NULL REFERENCES conversations(id),
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            thinking TEXT,
            thinking_dur TEXT,
            thinking_wc INTEGER DEFAULT 0,
            token_usage TEXT,
            file_ids TEXT,
            tokens_in INTEGER DEFAULT 0,
            tokens_out INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_messages_conv ON messages(conversation_id);
    """)
    # Column migrations for messages (safe now — table exists)
    for col, typ in [("thinking_dur", "TEXT"), ("thinking_wc", "INTEGER DEFAULT 0"), ("token_usage", "TEXT")]:
        try:
            conn.execute("SELECT " + col + " FROM messages LIMIT 1")
        except sqlite3.OperationalError:
            conn.execute("ALTER TABLE messages ADD COLUMN " + col + " " + typ)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS files (
            id TEXT PRIMARY KEY,
            original_name TEXT NOT NULL,
            stored_path TEXT NOT NULL,
            mime_type TEXT,
            size_bytes INTEGER DEFAULT 0,
            extracted_text TEXT,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_files_expires ON files(expires_at);
    """)
    conn.commit()
    conn.close()


async def get_db() -> aiosqlite.Connection:
    global DB
    if DB is None:
        DB = await aiosqlite.connect(DB_PATH)
        DB.row_factory = aiosqlite.Row
        await DB.execute("PRAGMA journal_mode=WAL")
        await DB.execute("PRAGMA foreign_keys=ON")
    return DB


# ── Conversations ──

async def create_conversation(title: str = "New Chat") -> Conversation:
    db = await get_db()
    conv_id = str(uuid.uuid4())
    now = datetime.now().isoformat()
    await db.execute(
        "INSERT INTO conversations (id, title, created_at, updated_at) VALUES (?, ?, ?, ?)",
        (conv_id, title, now, now),
    )
    await db.commit()
    return Conversation(id=conv_id, title=title, created_at=now, updated_at=now)


async def list_conversations(limit: int = 50) -> list[Conversation]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT id, title, claude_session_id, pinned, created_at, updated_at FROM conversations ORDER BY pinned DESC, updated_at DESC LIMIT ?",
        (limit,),
    )
    rows = await cursor.fetchall()
    return [Conversation(**dict(r)) for r in rows]


async def get_conversation(conv_id: str) -> Optional[Conversation]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT id, title, claude_session_id, pinned, created_at, updated_at FROM conversations WHERE id = ?",
        (conv_id,),
    )
    row = await cursor.fetchone()
    return Conversation(**dict(row)) if row else None


async def update_conversation_title(conv_id: str, title: str):
    db = await get_db()
    now = datetime.now().isoformat()
    await db.execute(
        "UPDATE conversations SET title = ?, updated_at = ? WHERE id = ?",
        (title, now, conv_id),
    )
    await db.commit()


async def touch_conversation(conv_id: str):
    """Update updated_at timestamp."""
    db = await get_db()
    now = datetime.now().isoformat()
    await db.execute(
        "UPDATE conversations SET updated_at = ? WHERE id = ?",
        (now, conv_id),
    )
    await db.commit()


async def save_claude_session_id(conv_id: str, claude_sid: str):
    """Store the claude session ID for this conversation."""
    db = await get_db()
    now = datetime.now().isoformat()
    await db.execute(
        "UPDATE conversations SET claude_session_id = ?, updated_at = ? WHERE id = ?",
        (claude_sid, now, conv_id),
    )
    await db.commit()


async def pin_conversation(conv_id: str, pinned: bool = True):
    db = await get_db()
    now = datetime.now().isoformat()
    await db.execute(
        "UPDATE conversations SET pinned = ?, updated_at = ? WHERE id = ?",
        (1 if pinned else 0, now, conv_id),
    )
    await db.commit()


async def delete_conversation(conv_id: str):
    db = await get_db()
    await db.execute("DELETE FROM messages WHERE conversation_id = ?", (conv_id,))
    await db.execute("DELETE FROM conversations WHERE id = ?", (conv_id,))
    await db.commit()


# ── Messages ──

# ── Streaming message helpers: progressive save during generation ──
# Flow: init_streaming_msg → update_streaming_msg (×N) → finalize_streaming_msg
# This ensures DB always has the latest state, even if client disconnects mid-stream.

async def init_streaming_msg(conv_id: str) -> int:
    """Insert a placeholder assistant message (content='', thinking='').
    Returns the message ID for subsequent updates."""
    db = await get_db()
    now = datetime.now().isoformat()
    cursor = await db.execute(
        """INSERT INTO messages (conversation_id, role, content, thinking, created_at)
           VALUES (?, 'assistant', '', '', ?)""",
        (conv_id, now),
    )
    await db.commit()
    msg_id = cursor.lastrowid
    logger.info(f"[DB] init_streaming_msg conv={conv_id[:8]} msg_id={msg_id}")
    return msg_id


async def update_streaming_msg(msg_id: int, thinking: str, content: str):
    """Update the in-progress message with latest thinking and content."""
    db = await get_db()
    await db.execute(
        "UPDATE messages SET thinking = ?, content = ? WHERE id = ?",
        (thinking, content, msg_id),
    )
    await db.commit()


async def finalize_streaming_msg(
    msg_id: int,
    thinking: str,
    content: str,
    thinking_dur: str,
    thinking_wc: int,
    token_usage: str,
):
    """Mark streaming message as complete with final content and metadata."""
    db = await get_db()
    await db.execute(
        """UPDATE messages SET thinking = ?, content = ?, thinking_dur = ?,
           thinking_wc = ?, token_usage = ? WHERE id = ?""",
        (thinking, content, thinking_dur, thinking_wc, token_usage, msg_id),
    )
    await db.commit()
    logger.info(f"[DB] finalize_streaming_msg msg_id={msg_id} content_len={len(content)}")


async def cancel_streaming_msg(msg_id: int):
    """Mark a streaming message as cancelled (empty content → will be filtered)."""
    db = await get_db()
    await db.execute(
        "UPDATE messages SET content = '__CANCELLED__' WHERE id = ?",
        (msg_id,),
    )
    await db.commit()
    logger.info(f"[DB] cancel_streaming_msg msg_id={msg_id}")


async def save_message(msg: Message):
    db = await get_db()
    now = datetime.now().isoformat() if not msg.created_at else msg.created_at
    cursor = await db.execute(
        """INSERT INTO messages (conversation_id, role, content, thinking, thinking_dur,
           thinking_wc, token_usage, file_ids, tokens_in, tokens_out, created_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (msg.conversation_id, msg.role, msg.content, msg.thinking,
         msg.thinking_dur, msg.thinking_wc, msg.token_usage,
         msg.file_ids, msg.tokens_in, msg.tokens_out, now),
    )
    await db.commit()
    msg.id = cursor.lastrowid


async def get_messages(conv_id: str, limit: int = 200, before_id: int = None) -> list[Message]:
    """Fetch messages for a conversation.

    If before_id is given, returns `limit` messages older than that id (DESC then ASC).
    Otherwise returns the latest `limit` messages.
    """
    db = await get_db()
    if before_id is not None:
        cursor = await db.execute(
            """SELECT id, conversation_id, role, content, thinking, thinking_dur,
               thinking_wc, token_usage, file_ids, tokens_in, tokens_out, created_at
               FROM (
                   SELECT * FROM messages WHERE conversation_id = ? AND id < ?
                   ORDER BY id DESC LIMIT ?
               ) ORDER BY id ASC""",
            (conv_id, before_id, limit),
        )
    else:
        cursor = await db.execute(
            """SELECT id, conversation_id, role, content, thinking, thinking_dur,
               thinking_wc, token_usage, file_ids, tokens_in, tokens_out, created_at
               FROM (
                   SELECT * FROM messages WHERE conversation_id = ?
                   ORDER BY id DESC LIMIT ?
               ) ORDER BY id ASC""",
            (conv_id, limit),
        )
    rows = await cursor.fetchall()
    return [Message(**dict(r)) for r in rows]


async def has_older_messages(conv_id: str, earliest_id: int) -> bool:
    """Check if there are messages older than the given id."""
    db = await get_db()
    cursor = await db.execute(
        "SELECT COUNT(*) FROM messages WHERE conversation_id = ? AND id < ?",
        (conv_id, earliest_id),
    )
    row = await cursor.fetchone()
    return row[0] > 0


# ── Files ──

async def save_file_record(fr: FileRecord):
    db = await get_db()
    now = datetime.now().isoformat()
    expires = (datetime.now() + timedelta(hours=FILE_TTL_HOURS)).isoformat()
    await db.execute(
        """INSERT OR REPLACE INTO files (id, original_name, stored_path, mime_type, size_bytes, extracted_text, created_at, expires_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (fr.id, fr.original_name, fr.stored_path, fr.mime_type,
         fr.size_bytes, fr.extracted_text, now, expires),
    )
    await db.commit()


async def get_file_record(file_id: str) -> Optional[FileRecord]:
    db = await get_db()
    cursor = await db.execute(
        "SELECT id, original_name, stored_path, mime_type, size_bytes, extracted_text, created_at, expires_at FROM files WHERE id = ?",
        (file_id,),
    )
    row = await cursor.fetchone()
    return FileRecord(**dict(row)) if row else None


async def get_expired_files() -> list[FileRecord]:
    db = await get_db()
    now = datetime.now().isoformat()
    cursor = await db.execute(
        "SELECT id, original_name, stored_path, mime_type, size_bytes, extracted_text, created_at, expires_at FROM files WHERE expires_at < ?",
        (now,),
    )
    rows = await cursor.fetchall()
    return [FileRecord(**dict(r)) for r in rows]


async def delete_file_record(file_id: str):
    db = await get_db()
    await db.execute("DELETE FROM files WHERE id = ?", (file_id,))
    await db.commit()
