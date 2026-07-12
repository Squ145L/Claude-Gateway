"""Database model definitions (schemas via dataclasses, not ORM)."""
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Conversation:
    id: str
    title: str = "New Chat"
    claude_session_id: Optional[str] = None
    pinned: int = 0
    created_at: str = ""
    updated_at: str = ""


@dataclass
class Message:
    conversation_id: str
    role: str  # "user" | "assistant"
    content: str
    id: Optional[int] = None
    thinking: Optional[str] = None
    thinking_dur: Optional[str] = None
    thinking_wc: int = 0
    token_usage: Optional[str] = None  # JSON: {"i":"47.0k","o":"128"}
    file_ids: Optional[str] = None
    tokens_in: int = 0
    tokens_out: int = 0
    created_at: str = ""


@dataclass
class FileRecord:
    id: str
    original_name: str
    stored_path: str
    mime_type: Optional[str] = None
    size_bytes: int = 0
    extracted_text: Optional[str] = None
    created_at: str = ""
    expires_at: str = ""
