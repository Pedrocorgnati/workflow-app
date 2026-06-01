"""
Logging configuration for Workflow App (module-02/TASK-6).

setup_logging() is idempotent — safe to call multiple times.
get_logger()   is a thin wrapper around logging.getLogger.
"""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

_LOG_DIR = Path.home() / ".workflow-app" / "logs"
# Per-process log file: Python's RotatingFileHandler is not safe for concurrent
# use by multiple OS processes (flock semantics differ per platform and rotation
# causes data loss when two processes race on the rename). Each instance writes
# to its own file; a log reader can `cat workflow-app-*.log | sort` to merge.
_LOG_FILE = _LOG_DIR / f"workflow-app-{os.getpid()}.log"

_FMT = "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s"
_DATE_FMT = "%Y-%m-%d %H:%M:%S"

_configured: bool = False


def setup_logging(level: int = logging.DEBUG) -> None:
    """Configure root logger with RotatingFileHandler (and optional StreamHandler).

    Idempotent: subsequent calls are no-ops.
    If the user log directory is not writable, keep startup alive with stderr
    logging instead of aborting the desktop app.

    Args:
        level: Minimum log level (default DEBUG).
               StreamHandler is added only when level <= DEBUG.
    """
    global _configured
    if _configured:
        return

    root = logging.getLogger()
    root.setLevel(level)

    formatter = logging.Formatter(_FMT, datefmt=_DATE_FMT)

    # Rotating file handler — 5 MB × 5 backups
    file_logging_enabled = False
    try:
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        file_handler = RotatingFileHandler(
            _LOG_FILE,
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        file_handler.setLevel(level)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
        file_logging_enabled = True
    except OSError as exc:
        # Startup must not depend on ~/.workflow-app being writable.
        sys.stderr.write(
            f"[workflow-app] WARN: file logging disabled for {_LOG_FILE}: {exc}\n"
        )

    # Stream handler in DEBUG mode, or as the fallback when file logging fails.
    if level <= logging.DEBUG or not file_logging_enabled:
        stream_handler = logging.StreamHandler(sys.stderr)
        stream_handler.setLevel(logging.DEBUG if level <= logging.DEBUG else level)
        stream_handler.setFormatter(formatter)
        root.addHandler(stream_handler)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a named logger.

    Args:
        name: Typically ``__name__`` of the calling module.

    Returns:
        A :class:`logging.Logger` instance.
    """
    return logging.getLogger(name)
