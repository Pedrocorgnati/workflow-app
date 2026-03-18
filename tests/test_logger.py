"""Tests for workflow_app.logger (module-02/TASK-6)."""

from __future__ import annotations

import logging

import pytest

import workflow_app.logger as logger_mod
from workflow_app.logger import get_logger, setup_logging


@pytest.fixture(autouse=True)
def reset_logging_config():
    """Reset the module-level _configured flag and root handlers between tests."""
    # Save state
    original_configured = logger_mod._configured
    root = logging.getLogger()
    original_handlers = list(root.handlers)

    yield

    # Restore state
    logger_mod._configured = original_configured
    # Remove handlers added by tests
    for h in list(root.handlers):
        if h not in original_handlers:
            root.removeHandler(h)
            h.close()


class TestSetupLogging:
    def test_idempotent(self, tmp_path, monkeypatch):
        monkeypatch.setattr(logger_mod, "_LOG_DIR", tmp_path / "logs")
        monkeypatch.setattr(
            logger_mod, "_LOG_FILE", tmp_path / "logs" / "workflow-app.log"
        )
        logger_mod._configured = False

        root = logging.getLogger()
        before = len(root.handlers)

        setup_logging()
        after_first = len(root.handlers)

        # Second call must not add more handlers
        setup_logging()
        after_second = len(root.handlers)

        assert after_second == after_first
        assert after_first > before

    def test_creates_log_dir(self, tmp_path, monkeypatch):
        log_dir = tmp_path / "new" / "logs"
        monkeypatch.setattr(logger_mod, "_LOG_DIR", log_dir)
        monkeypatch.setattr(logger_mod, "_LOG_FILE", log_dir / "workflow-app.log")
        logger_mod._configured = False

        assert not log_dir.exists()
        setup_logging()
        assert log_dir.exists()

    def test_file_handler_added(self, tmp_path, monkeypatch):
        log_dir = tmp_path / "logs"
        monkeypatch.setattr(logger_mod, "_LOG_DIR", log_dir)
        monkeypatch.setattr(logger_mod, "_LOG_FILE", log_dir / "workflow-app.log")
        logger_mod._configured = False

        setup_logging()
        from logging.handlers import RotatingFileHandler

        root = logging.getLogger()
        file_handlers = [h for h in root.handlers if isinstance(h, RotatingFileHandler)]
        assert len(file_handlers) >= 1

    def test_stream_handler_added_in_debug(self, tmp_path, monkeypatch):
        log_dir = tmp_path / "logs"
        monkeypatch.setattr(logger_mod, "_LOG_DIR", log_dir)
        monkeypatch.setattr(logger_mod, "_LOG_FILE", log_dir / "workflow-app.log")
        logger_mod._configured = False

        setup_logging(level=logging.DEBUG)
        root = logging.getLogger()
        # Exact type match excludes pytest's LogCaptureHandler subclass
        stream_handlers = [
            h for h in root.handlers if type(h) is logging.StreamHandler
        ]
        assert len(stream_handlers) >= 1

    def test_no_stream_handler_above_debug(self, tmp_path, monkeypatch):
        log_dir = tmp_path / "logs"
        monkeypatch.setattr(logger_mod, "_LOG_DIR", log_dir)
        monkeypatch.setattr(logger_mod, "_LOG_FILE", log_dir / "workflow-app.log")
        logger_mod._configured = False

        setup_logging(level=logging.INFO)
        root = logging.getLogger()
        # Use exact type match to exclude pytest's LogCaptureHandler subclass
        stream_handlers = [
            h for h in root.handlers if type(h) is logging.StreamHandler
        ]
        assert len(stream_handlers) == 0


class TestGetLogger:
    def test_returns_logger(self):
        lg = get_logger("workflow_app.test")
        assert isinstance(lg, logging.Logger)

    def test_name_preserved(self):
        lg = get_logger("workflow_app.my_module")
        assert lg.name == "workflow_app.my_module"

    def test_same_instance_for_same_name(self):
        lg1 = get_logger("workflow_app.shared")
        lg2 = get_logger("workflow_app.shared")
        assert lg1 is lg2
