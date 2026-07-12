"""Logging setup with rotation."""
import logging
import sys
from logging.handlers import RotatingFileHandler
from config import LOG_LEVEL, LOG_DIR


def setup_logging() -> logging.Logger:
    logger = logging.getLogger("claude-gateway")
    logger.setLevel(getattr(logging, LOG_LEVEL.upper(), logging.DEBUG))

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-5s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(console)

    # File handler with rotation (5MB x 3 backups)
    file_handler = RotatingFileHandler(
        LOG_DIR / "claude-gateway.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=3,
        encoding="utf-8",
    )
    file_handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)-5s] [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logger.addHandler(file_handler)

    return logger


logger = setup_logging()
