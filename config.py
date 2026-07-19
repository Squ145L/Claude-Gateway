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

# Auth
AUTH_SECRET = _env("AUTH_SECRET", "change-me")

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
SESSION_TIMEOUT_MINUTES = int(_env("SESSION_TIMEOUT_MINUTES", "0"))

# Session idle timeout (minutes, 0 = never reap)
SESSION_IDLE_TIMEOUT_MINUTES = int(_env("SESSION_IDLE_TIMEOUT_MINUTES", "0"))

# OCR
OCR_ENABLED = _env("OCR_ENABLED", "true").lower() == "true"

# DeepSeek balance query (CC Switch integration)
# BUGFIX #11: no longer hardcoded — configurable via .env
DEEPSEEK_CC_SWITCH_DB = _env("DEEPSEEK_CC_SWITCH_DB",
    str(Path.home() / ".cc-switch" / "cc-switch.db"))
DEEPSEEK_PROVIDER_UUID = _env("DEEPSEEK_PROVIDER_UUID",
    "your-provider-uuid-here")

# Ensure data directories exist
Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
Path(FILE_ROOT_DIR).mkdir(parents=True, exist_ok=True)
