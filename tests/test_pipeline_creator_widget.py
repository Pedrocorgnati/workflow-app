"""Tests for PipelineCreatorWidget QA-remediation — module-11/TASK-5.

Covers:
  P061 — _on_worker_error calls mark_error() on CommandStateMachine
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from workflow_app.domain import CommandStatus
from workflow_app.pipeline.command_state_machine import CommandStateMachine

# ── Fixtures ─────────────────────────────────────────────────────────────── #


@pytest.fixture()
def state_machine():
    signal_bus = MagicMock()
    persisted: list[tuple] = []

    def persist(exec_id, status, started_at, finished_at):
        persisted.append((exec_id, status, started_at, finished_at))

    m = CommandStateMachine(
        command_exec_id=99,
        signal_bus=signal_bus,
        persist_callback=persist,
    )
    m._persisted = persisted
    return m


# ── Tests: CommandStateMachine.mark_error ────────────────────────────────── #


def test_mark_error_transitions_to_erro(state_machine):
    """mark_error() must transition FSM from EXECUTANDO to ERRO."""
    state_machine.start()
    assert state_machine.current_command_status == CommandStatus.EXECUTANDO

    state_machine.mark_error("sdk crashed")

    assert state_machine.current_command_status == CommandStatus.ERRO


def test_mark_error_stores_message(state_machine):
    """mark_error() must store the error message in last_error_message."""
    state_machine.start()
    state_machine.mark_error("timeout after 30s")

    assert state_machine.last_error_message == "timeout after 30s"


def test_mark_error_emits_erro_signal(state_machine):
    """mark_error() must emit command_status_changed with ERRO value."""
    state_machine.start()
    state_machine.mark_error("network error")

    state_machine._signal_bus.command_status_changed.emit.assert_called_with(
        99, CommandStatus.ERRO.value
    )


def test_last_error_message_none_before_mark_error(state_machine):
    """last_error_message must be None before any error occurs."""
    assert state_machine.last_error_message is None


def test_on_worker_error_marks_state_machine():
    """PipelineManager._on_worker_error must call sm.mark_error(), not result_fail().

    Verifies P061: the FSM transitions to ERRO and the error message is stored.
    """
    from workflow_app.pipeline.pipeline_manager import PipelineManager

    signal_bus = MagicMock()
    signal_bus.pipeline_error_occurred = MagicMock()
    signal_bus.pipeline_error_occurred.emit = MagicMock()

    sdk_adapter = MagicMock()
    session_factory = MagicMock()

    manager = PipelineManager(
        signal_bus=signal_bus,
        sdk_adapter=sdk_adapter,
        session_factory=session_factory,
    )

    # Inject a fake CommandStateMachine already in EXECUTANDO
    fake_sm = MagicMock(spec=CommandStateMachine)
    fake_sm.current_command_status = CommandStatus.EXECUTANDO

    command_exec_id = 7
    manager._state_machines[command_exec_id] = fake_sm
    manager._pipeline_exec_id = 1
    manager._queue = []  # no specs needed for error path

    manager._on_worker_error(command_exec_id, "test error msg")

    # mark_error must have been called with the error message
    fake_sm.mark_error.assert_called_once_with("test error msg")
    # result_fail must NOT be called directly (mark_error wraps it)
    fake_sm.result_fail.assert_not_called()
