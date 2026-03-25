"""
AppConfig — File-based key-value store for application preferences.

Persists settings to ~/.workflow-app/config.json so they survive app restarts.
Not to be confused with the DB model AppConfig in workflow_app.db.models,
which stores project-specific configuration.

Module: module-11/TASK-4
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class AppConfig:
    """File-based application preferences.

    Class methods operate on a shared in-memory cache backed by
    ~/.workflow-app/config.json.

    Usage:
        from workflow_app.config.app_config import AppConfig

        mode = AppConfig.get("default_permission_mode", "acceptEdits")
        AppConfig.set("default_permission_mode", "manual")
    """

    _CONFIG_PATH: Path = Path.home() / ".workflow-app" / "config.json"
    _cache: dict[str, Any] = {}
    _loaded: bool = False

    # Default values for all known preference keys
    _DEFAULTS: dict[str, Any] = {
        "default_permission_mode": "acceptEdits",
        "remote_mode_enabled": False,  # workflow-mobile: start WebSocket server on launch
    }

    @classmethod
    def get(cls, key: str, default: Any = None) -> Any:
        """Return the value for key, or default if not set."""
        cls._ensure_loaded()
        if key in cls._cache:
            return cls._cache[key]
        if default is not None:
            return default
        return cls._DEFAULTS.get(key)

    @classmethod
    def set(cls, key: str, value: Any) -> None:
        """Set key to value and persist to disk."""
        cls._ensure_loaded()
        cls._cache[key] = value
        cls._save()

    @classmethod
    def reset(cls) -> None:
        """Clear in-memory cache (forces reload on next access)."""
        cls._cache = {}
        cls._loaded = False

    @classmethod
    def _ensure_loaded(cls) -> None:
        if not cls._loaded:
            cls._load()

    @classmethod
    def _load(cls) -> None:
        if cls._CONFIG_PATH.exists():
            try:
                cls._cache = json.loads(cls._CONFIG_PATH.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                cls._cache = {}
        else:
            cls._cache = {}
        cls._loaded = True

    @classmethod
    def _save(cls) -> None:
        try:
            cls._CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            cls._CONFIG_PATH.write_text(
                json.dumps(cls._cache, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
        except OSError as exc:
            logger.warning("AppConfig: failed to persist %s: %s", cls._CONFIG_PATH, exc)
