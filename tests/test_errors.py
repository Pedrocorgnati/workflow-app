"""Tests for workflow_app.errors (module-02/TASK-6)."""

from __future__ import annotations

import logging

import pytest

from workflow_app.errors import (
    AppError,
    ConfigError,
    DatabaseError,
    FilesystemError,
    SDKError,
    TemplateError,
    handle_exception,
)

# ── AppError base ────────────────────────────────────────────────────────────


class TestAppError:
    def test_message_stored(self):
        err = AppError("oops")
        assert err.message == "oops"

    def test_str_format(self):
        err = AppError("oops")
        assert str(err) == "[APP_ERROR] oops"

    def test_cause_none_by_default(self):
        err = AppError("oops")
        assert err.cause is None

    def test_cause_stored(self):
        original = ValueError("original")
        err = AppError("wrapped", cause=original)
        assert err.cause is original

    def test_is_exception(self):
        err = AppError("oops")
        assert isinstance(err, Exception)

    def test_args_tuple(self):
        err = AppError("oops")
        assert err.args == ("oops",)


# ── Subclasses ────────────────────────────────────────────────────────────────


class TestSubclasses:
    @pytest.mark.parametrize(
        "cls, expected_code",
        [
            (SDKError, "SDK_ERROR"),
            (DatabaseError, "DB_ERROR"),
            (ConfigError, "CONFIG_ERROR"),
            (FilesystemError, "FS_ERROR"),
            (TemplateError, "TEMPLATE_ERROR"),
        ],
    )
    def test_code(self, cls, expected_code):
        err = cls("msg")
        assert err.code == expected_code

    @pytest.mark.parametrize(
        "cls",
        [SDKError, DatabaseError, ConfigError, FilesystemError, TemplateError],
    )
    def test_inherits_app_error(self, cls):
        err = cls("msg")
        assert isinstance(err, AppError)

    @pytest.mark.parametrize(
        "cls",
        [SDKError, DatabaseError, ConfigError, FilesystemError, TemplateError],
    )
    def test_str_uses_subclass_code(self, cls):
        err = cls("msg")
        assert err.code in str(err)
        assert "msg" in str(err)


# ── handle_exception decorator ────────────────────────────────────────────────


class TestHandleException:
    def _make_logger(self):
        logger = logging.getLogger("test_handle_exception")
        logger.handlers.clear()
        return logger

    def test_returns_value_on_success(self):
        logger = self._make_logger()

        @handle_exception(logger)
        def add(a, b):
            return a + b

        assert add(2, 3) == 5

    def test_re_raises_exception(self):
        logger = self._make_logger()

        @handle_exception(logger)
        def boom():
            raise ValueError("kaboom")

        with pytest.raises(ValueError, match="kaboom"):
            boom()

    def test_logs_error_on_exception(self, caplog):
        logger = logging.getLogger("test_log_error")
        logger.handlers.clear()

        @handle_exception(logger)
        def boom():
            raise RuntimeError("bad thing")

        with caplog.at_level(logging.ERROR, logger="test_log_error"):
            with pytest.raises(RuntimeError):
                boom()

        assert any("bad thing" in r.message for r in caplog.records)

    def test_preserves_function_name(self):
        logger = self._make_logger()

        @handle_exception(logger)
        def my_function():
            pass

        assert my_function.__name__ == "my_function"

    def test_passes_args_and_kwargs(self):
        logger = self._make_logger()

        @handle_exception(logger)
        def greet(name, *, greeting="Hello"):
            return f"{greeting}, {name}!"

        assert greet("Alice", greeting="Hi") == "Hi, Alice!"
