"""Configuration loaded from .env file."""
import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent

# Load .env — override with system env vars if present
load_dotenv(BASE_DIR / ".env", override=False)


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default)


# Service
HOST = _env("HOST", "0.0.0.0")
PORT = int(_env("PORT", "8080"))

# Claude Code CLI — spawns as subprocess, inherits env vars
CLAUDE_CWD = _env("CLAUDE_CWD", str(Path.home()))

# Permission bypass — Gateway intercepts tool_use events and auto-approves.
# When ON: Claude tool calls are auto-approved (equivalent to old bypassPermissions).
# When OFF: each tool_use is rejected by Gateway with a guidance message.
# Managed by settings panel toggle — changes take effect immediately.
BYPASS_PERMISSIONS = _env("BYPASS_PERMISSIONS", "true").lower() == "true"

# Backward compat — migrate old key if present
if not _env("BYPASS_PERMISSIONS") and _env("CLAUDE_PERMISSION_MODE"):
    old = _env("CLAUDE_PERMISSION_MODE")
    BYPASS_PERMISSIONS = old in ("bypassPermissions", "acceptEdits")

# Auth
AUTH_SECRET = _env("AUTH_SECRET", "change-me")

# ── Startup safety checks ─────────────────────────────────
import sys as _sys
if AUTH_SECRET == "change-me":
    _sys.stderr.write("\n" + "!" * 60 + "\n")
    _sys.stderr.write("⚠️  SECURITY: AUTH_SECRET is still the default 'change-me'!\n")
    _sys.stderr.write("   Generate a strong key:\n")
    _sys.stderr.write('   python -c "import secrets; print(secrets.token_urlsafe(32))"\n')
    _sys.stderr.write("   Then set AUTH_SECRET=<output> in your .env file.\n")
    _sys.stderr.write("!" * 60 + "\n\n")
# Files
FILE_ROOT_DIR = _env("FILE_ROOT_DIR", r"D:\ClaudeFiles")
MAX_FILE_SIZE_MB = int(_env("MAX_FILE_SIZE_MB", "20"))
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024
FILE_TTL_HOURS = int(_env("FILE_TTL_HOURS", "24"))

# Allowed file types for text extraction
ALLOWED_EXTENSIONS = {
    ".pdf", ".docx", ".txt", ".md", ".py", ".c", ".cpp", ".h", ".hpp",
    ".js", ".ts", ".html", ".css", ".json", ".xml", ".yaml", ".yml",
    ".csv", ".log", ".sh", ".bat", ".ps1", ".ini", ".cfg", ".toml",
    ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp",
}

# Logging
LOG_LEVEL = _env("LOG_LEVEL", "DEBUG")
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)
CONSOLE_MIRROR = _env("CONSOLE_MIRROR", "true").lower() == "true"

# Database
DB_PATH = _env("DB_PATH", "./data/conversations.db")
if not Path(DB_PATH).is_absolute():
    DB_PATH = str(BASE_DIR / DB_PATH)

# Session timeout (minutes, 0 = never)
SESSION_TIMEOUT_MINUTES = int(_env("SESSION_TIMEOUT_MINUTES", "30"))

# Session idle timeout (minutes, 0 = never reap)
SESSION_IDLE_TIMEOUT_MINUTES = int(_env("SESSION_IDLE_TIMEOUT_MINUTES", "5"))

# Chat limits
MAX_MESSAGE_LENGTH_ENABLED = _env("MAX_MESSAGE_LENGTH_ENABLED", "true").lower() == "true"
MAX_MESSAGE_LENGTH = int(_env("MAX_MESSAGE_LENGTH", "50000"))
# Clamp to valid range
if MAX_MESSAGE_LENGTH < 1000:
    MAX_MESSAGE_LENGTH = 1000
elif MAX_MESSAGE_LENGTH > 500000:
    MAX_MESSAGE_LENGTH = 500000

# Auto update
AUTO_CHECK_UPDATE = _env("AUTO_CHECK_UPDATE", "true").lower() == "true"

# OCR
OCR_ENABLED = _env("OCR_ENABLED", "true").lower() == "true"

# DeepSeek balance query (CC Switch integration)
# BUGFIX #11: no longer hardcoded — configurable via .env
DEEPSEEK_CC_SWITCH_DB = _env("DEEPSEEK_CC_SWITCH_DB",
    str(Path.home() / ".cc-switch" / "cc-switch.db"))
DEEPSEEK_PROVIDER_UUID = _env("DEEPSEEK_PROVIDER_UUID",
    "47bb5ec7-8465-4098-a5a0-8c2df7f15643")

# Ensure data directories exist
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
Path(FILE_ROOT_DIR).mkdir(parents=True, exist_ok=True)
