"""Tests for CommandStateMachine (module-11/TASK-1)."""

from __future__ import annotations

from unittest.mock import MagicMock, call

import pytest

from workflow_app.domain import CommandStatus
from workflow_app.pipeline.command_state_machine import CommandStateMachine


@pytest.fixture()
def machine():
    signal_bus = MagicMock()
    persisted: list[tuple] = []

    def persist(exec_id, status, started_at, finished_at):
        persisted.append((exec_id, status, started_at, finished_at))

    m = CommandStateMachine(
        command_exec_id=42,
        signal_bus=signal_bus,
        persist_callback=persist,
    )
    m._persisted = persisted
    return m


def test_initial_state_is_pendente(machine):
    assert machine.current_command_status == CommandStatus.PENDENTE


def test_start_transitions_to_executando(machine):
    machine.start()
    assert machine.current_command_status == CommandStatus.EXECUTANDO
    machine._signal_bus.command_status_changed.emit.assert_called_with(
        42, CommandStatus.EXECUTANDO.value
    )


def test_result_ok_transitions_to_concluido(machine):
    machine.start()
    machine.result_ok()
    assert machine.current_command_status == CommandStatus.CONCLUIDO
    machine._signal_bus.command_status_changed.emit.assert_called_with(
        42, CommandStatus.CONCLUIDO.value
    )


def test_result_fail_transitions_to_erro(machine):
    machine.start()
    machine.result_fail()
    assert machine.current_command_status == CommandStatus.ERRO


def test_retry_from_erro_transitions_to_executando(machine):
    machine.start()
    machine.result_fail()
    machine.retry()
    assert machine.current_command_status == CommandStatus.EXECUTANDO


def test_skip_from_pendente_transitions_to_pulado(machine):
    machine.skip()
    assert machine.current_command_status == CommandStatus.PULADO


def test_app_closed_from_executando_transitions_to_incerto(machine):
    machine.start()
    machine.app_closed()
    assert machine.current_command_status == CommandStatus.INCERTO
    # on_enter_incerto must NOT emit a signal — last emit should be from on_enter_executando
    calls = machine._signal_bus.command_status_changed.emit.call_args_list
    assert calls[-1] == call(42, CommandStatus.EXECUTANDO.value)


def test_retry_uncertain_from_incerto_transitions_to_executando(machine):
    machine.start()
    machine.app_closed()
    machine.retry_uncertain()
    assert machine.current_command_status == CommandStatus.EXECUTANDO


def test_duration_seconds_calculated_after_concluido(machine):
    machine.start()
    machine.result_ok()
    assert machine.duration_seconds is not None
    assert machine.duration_seconds >= 0.0


def test_persist_called_on_each_transition(machine):
    machine.start()
    machine.result_ok()
    # pendente→executando and executando→concluido = 2 persist calls
    assert len(machine._persisted) == 2
    assert machine._persisted[0][1] == CommandStatus.EXECUTANDO
    assert machine._persisted[1][1] == CommandStatus.CONCLUIDO


def test_all_six_states_exist():
    """Verify all 6 states are declared as class attributes."""
    for state_name in ("pendente", "executando", "concluido", "erro", "pulado", "incerto"):
        assert hasattr(CommandStateMachine, state_name)
