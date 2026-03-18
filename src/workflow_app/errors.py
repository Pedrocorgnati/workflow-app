"""
Custom exception hierarchy for Workflow App (module-02/TASK-6).

All application errors inherit from AppError. The handle_exception
decorator captures unhandled exceptions, logs them as ERROR and re-raises.
"""

from __future__ import annotations

import functools
import logging
from collections.abc import Callable
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


class AppError(Exception):
    """Base application error. All custom errors inherit from here."""

    code: str = "APP_ERROR"

    def __init__(self, message: str, *, cause: BaseException | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.cause = cause

    def __str__(self) -> str:
        return f"[{self.code}] {self.message}"


class SDKError(AppError):
    """Failure communicating with claude-agent-sdk (subprocess, invalid JSON, timeout)."""
    code = "SDK_ERROR"


class SDKNotAvailableError(AppError):
    """claude-agent-sdk not installed or not importable."""
    code = "SDK_NOT_AVAILABLE"


class SDKNotAuthenticatedError(AppError):
    """Claude CLI not authenticated."""
    code = "SDK_NOT_AUTHENTICATED"


class SDKExecutionError(AppError):
    """Error during command execution via SDK."""
    code = "SDK_EXECUTION_ERROR"


class DatabaseError(AppError):
    """Failure in a database operation."""
    code = "DB_ERROR"


class ConfigError(AppError):
    """Failure loading or validating project.json."""
    code = "CONFIG_ERROR"


class FilesystemError(AppError):
    """Failure in a filesystem operation (permission, disk full, etc.)."""
    code = "FS_ERROR"


class TemplateError(AppError):
    """Failure validating or parsing a template."""
    code = "TEMPLATE_ERROR"


def handle_exception(logger: logging.Logger) -> Callable[[F], F]:
    """Decorator that captures exceptions, logs them as ERROR and re-raises.

    Usage:
        @handle_exception(logger)
        def my_method(self) -> None:
            ...
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            try:
                return func(*args, **kwargs)
            except Exception as exc:
                logger.error(
                    "Unhandled exception in %s: %s",
                    func.__qualname__,
                    exc,
                    exc_info=True,
                )
                raise
        return wrapper  # type: ignore[return-value]
    return decorator
