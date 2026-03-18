"""Tests for ToolUseHookMixin (module-09/TASK-4)."""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from workflow_app.db.models import Base, ExecutionLog, PipelineExecution
from workflow_app.sdk.tool_use_hooks import ToolUseHookMixin


class _FakeWorker(ToolUseHookMixin):
    """Minimal subclass to test ToolUseHookMixin without QThread."""

    def __init__(self, session_factory, pipeline_id, signal_bus):
        self._session_factory = session_factory
        self._pipeline_id = pipeline_id
        self._command_exec_id = None
        self._signal_bus = signal_bus


@pytest.fixture()
def mock_session_factory():
    """sessionmaker backed by an in-memory SQLite database."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)


def test_pre_tool_use_logs_to_db(mock_session_factory):
    """on_pre_tool_use inserts an ExecutionLog entry in the database."""
    signal_bus = MagicMock()
    worker = _FakeWorker(mock_session_factory, pipeline_id=1, signal_bus=signal_bus)

    # Create the required PipelineExecution row (FK constraint)
    with mock_session_factory() as s:
        pe = PipelineExecution(project_config_path="/tmp/p.json", commands_total=1)
        s.add(pe)
        s.commit()
        worker._pipeline_id = pe.id

    start = worker.on_pre_tool_use("Read", "path=/tmp/foo.py")
    assert start is not None

    with mock_session_factory() as s:
        logs = s.query(ExecutionLog).all()
    assert any("[PRE] tool=Read" in log.message for log in logs)


def test_post_tool_use_emits_signal(mock_session_factory):
    """on_post_tool_use emits tool_use_completed on the signal_bus."""
    signal_bus = MagicMock()
    worker = _FakeWorker(mock_session_factory, pipeline_id=99, signal_bus=signal_bus)

    start = time.monotonic()
    worker.on_post_tool_use("Bash", "exit code 0", start_time=start)

    signal_bus.tool_use_completed.emit.assert_called_once()
    tool_name, duration_ms = signal_bus.tool_use_completed.emit.call_args[0]
    assert tool_name == "Bash"
    assert duration_ms >= 0


def test_pre_tool_use_emits_started_signal(mock_session_factory):
    """on_pre_tool_use emits tool_use_started on the signal_bus."""
    signal_bus = MagicMock()
    worker = _FakeWorker(mock_session_factory, pipeline_id=99, signal_bus=signal_bus)

    worker.on_pre_tool_use("Edit", "path=/tmp/x.py")

    signal_bus.tool_use_started.emit.assert_called_once_with("Edit")


def test_hook_failure_does_not_raise(mock_session_factory):
    """Hooks with failing DB do not propagate exceptions."""

    def bad_factory():
        raise RuntimeError("DB down")

    signal_bus = MagicMock()
    worker = _FakeWorker(bad_factory, pipeline_id=1, signal_bus=signal_bus)

    # Must not raise
    result = worker.on_pre_tool_use("Edit", "path=/tmp/x.py")
    worker.on_post_tool_use("Edit", "done")

    # start_time is still returned even on DB failure
    assert result is not None


def test_hooks_safe_without_execution_context():
    """ToolUseHookMixin is safe when set_execution_context() was never called."""

    class _NoContextWorker(ToolUseHookMixin):
        pass

    w = _NoContextWorker()
    # Must not raise even without _session_factory, _pipeline_id, etc.
    result = w.on_pre_tool_use("Glob", "*.py")
    w.on_post_tool_use("Glob", "3 files", start_time=result)


def test_duration_ms_non_negative(mock_session_factory):
    """duration_ms reported by on_post_tool_use is always >= 0."""
    signal_bus = MagicMock()
    worker = _FakeWorker(mock_session_factory, pipeline_id=99, signal_bus=signal_bus)

    # Pass start_time = very recent (duration should be ~0ms)
    start = time.monotonic()
    worker.on_post_tool_use("WebFetch", "200 OK", start_time=start)

    _, duration_ms = signal_bus.tool_use_completed.emit.call_args[0]
    assert duration_ms >= 0

    # Pass no start_time (duration should be 0)
    signal_bus.reset_mock()
    worker.on_post_tool_use("WebFetch", "200 OK", start_time=None)

    _, duration_ms = signal_bus.tool_use_completed.emit.call_args[0]
    assert duration_ms == 0
