"""Tests for PipelineManager guards (module-11/TASK-3)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from workflow_app.db.models import Base
from workflow_app.domain import CommandSpec, InteractionType, ModelName
from workflow_app.pipeline.command_state_machine import CommandStateMachine
from workflow_app.pipeline.pipeline_manager import PipelineManager
from workflow_app.signal_bus import SignalBus

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def factory():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    yield Session
    engine.dispose()


@pytest.fixture()
def mock_bus():
    return MagicMock(spec=SignalBus)


@pytest.fixture()
def manager(factory, mock_bus):
    return PipelineManager(
        signal_bus=mock_bus,
        sdk_adapter=MagicMock(),
        session_factory=factory,
        workspace_dir="/tmp/test",
    )


def _spec(name: str = "/cmd") -> CommandSpec:
    return CommandSpec(name=name, model=ModelName.SONNET, interaction_type=InteractionType.AUTO)


def _make_sm(mock_bus: MagicMock, exec_id: int = 1) -> CommandStateMachine:
    """Create a bare CommandStateMachine (starts in PENDENTE)."""
    return CommandStateMachine(
        command_exec_id=exec_id,
        signal_bus=mock_bus,
        persist_callback=lambda *args: None,
    )


# ── can_edit_queue ────────────────────────────────────────────────────────────


def test_can_edit_queue_out_of_range_returns_true(manager):
    manager.set_queue([_spec()])
    assert manager.can_edit_queue(5) is True
    assert manager.can_edit_queue(-1) is True


def test_can_edit_queue_no_exec_id_returns_true(manager):
    """Position exists in queue but hasn't been launched yet."""
    manager.set_queue([_spec()])
    assert manager.can_edit_queue(0) is True


def test_can_edit_queue_executando_returns_false(manager):
    manager.set_queue([_spec()])
    with patch("workflow_app.pipeline.pipeline_manager.ProcessRunner"):
        manager.start(permission_mode="acceptEdits")
    # After start(), position 0 is EXECUTANDO
    assert manager.can_edit_queue(0) is False


def test_can_edit_queue_concluido_returns_true(manager):
    manager.set_queue([_spec()])
    with patch("workflow_app.pipeline.pipeline_manager.ProcessRunner"):
        manager.start(permission_mode="acceptEdits")
    sm = manager._state_machines[manager._current_command_exec_id]
    sm.result_ok()  # EXECUTANDO → CONCLUIDO
    assert manager.can_edit_queue(0) is True


def test_can_edit_queue_erro_returns_true(manager):
    manager.set_queue([_spec()])
    with patch("workflow_app.pipeline.pipeline_manager.ProcessRunner"):
        manager.start(permission_mode="acceptEdits")
    sm = manager._state_machines[manager._current_command_exec_id]
    sm.result_fail()  # EXECUTANDO → ERRO
    assert manager.can_edit_queue(0) is True


# ── can_reorder ───────────────────────────────────────────────────────────────


def test_can_reorder_out_of_range_returns_false(manager):
    manager.set_queue([_spec()])
    assert manager.can_reorder(5) is False
    assert manager.can_reorder(-1) is False


def test_can_reorder_no_exec_id_returns_true(manager):
    """Queue item not yet launched is implicitly PENDENTE."""
    manager.set_queue([_spec()])
    assert manager.can_reorder(0) is True


def test_can_reorder_pendente_returns_true(manager, mock_bus):
    manager.set_queue([_spec("/a"), _spec("/b")])
    # Register a bare SM (PENDENTE) for position 1
    sm = _make_sm(mock_bus, exec_id=99)
    manager._state_machines[99] = sm
    manager._position_to_exec_id[1] = 99
    assert manager.can_reorder(1) is True


def test_can_reorder_executando_returns_false(manager):
    manager.set_queue([_spec()])
    with patch("workflow_app.pipeline.pipeline_manager.ProcessRunner"):
        manager.start(permission_mode="acceptEdits")
    # Position 0 is EXECUTANDO after start()
    assert manager.can_reorder(0) is False


def test_can_reorder_concluido_returns_false(manager):
    manager.set_queue([_spec()])
    with patch("workflow_app.pipeline.pipeline_manager.ProcessRunner"):
        manager.start(permission_mode="acceptEdits")
    sm = manager._state_machines[manager._current_command_exec_id]
    sm.result_ok()  # → CONCLUIDO
    assert manager.can_reorder(0) is False


# ── can_start_next ────────────────────────────────────────────────────────────


def test_can_start_next_position_zero_always_true(manager):
    manager.set_queue([_spec()])
    assert manager.can_start_next(0) is True


def test_can_start_next_no_predecessor_exec_id_returns_false(manager):
    manager.set_queue([_spec("/a"), _spec("/b")])
    # Nothing started, position 0 has no exec_id
    assert manager.can_start_next(1) is False


def test_can_start_next_predecessor_concluido_returns_true(manager, mock_bus):
    manager.set_queue([_spec("/a"), _spec("/b")])
    sm = _make_sm(mock_bus, exec_id=10)
    sm.start()
    sm.result_ok()  # PENDENTE → EXECUTANDO → CONCLUIDO
    manager._state_machines[10] = sm
    manager._position_to_exec_id[0] = 10
    assert manager.can_start_next(1) is True


def test_can_start_next_predecessor_pulado_returns_true(manager, mock_bus):
    manager.set_queue([_spec("/a"), _spec("/b")])
    sm = _make_sm(mock_bus, exec_id=11)
    sm.skip()  # PENDENTE → PULADO
    manager._state_machines[11] = sm
    manager._position_to_exec_id[0] = 11
    assert manager.can_start_next(1) is True


def test_can_start_next_predecessor_executando_returns_false(manager, mock_bus):
    manager.set_queue([_spec("/a"), _spec("/b")])
    sm = _make_sm(mock_bus, exec_id=12)
    sm.start()  # PENDENTE → EXECUTANDO
    manager._state_machines[12] = sm
    manager._position_to_exec_id[0] = 12
    assert manager.can_start_next(1) is False


def test_can_start_next_predecessor_erro_returns_false(manager, mock_bus):
    manager.set_queue([_spec("/a"), _spec("/b")])
    sm = _make_sm(mock_bus, exec_id=13)
    sm.start()
    sm.result_fail()  # → ERRO
    manager._state_machines[13] = sm
    manager._position_to_exec_id[0] = 13
    assert manager.can_start_next(1) is False
