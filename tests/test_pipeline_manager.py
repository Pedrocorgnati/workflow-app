"""Tests for PipelineManager (module-11/TASK-2)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from workflow_app.db.models import Base, CommandExecution, PipelineExecution
from workflow_app.domain import CommandSpec, InteractionType, ModelName
from workflow_app.pipeline.pipeline_manager import PipelineManager
from workflow_app.signal_bus import SignalBus

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def factory():
    """Fresh in-memory SQLite sessionmaker per test."""
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
def mock_adapter():
    return MagicMock()


@pytest.fixture()
def manager(factory, mock_bus, mock_adapter):
    return PipelineManager(
        signal_bus=mock_bus,
        sdk_adapter=mock_adapter,
        session_factory=factory,
        workspace_dir="/tmp/test",
    )


def _spec(name: str = "/cmd", interaction_type: InteractionType = InteractionType.AUTO) -> CommandSpec:
    return CommandSpec(name=name, model=ModelName.SONNET, interaction_type=interaction_type)


# ── set_queue ─────────────────────────────────────────────────────────────────


def test_set_queue_stores_commands(manager):
    specs = [_spec("/cmd-a"), _spec("/cmd-b")]
    manager.set_queue(specs)
    assert manager._queue == specs


def test_set_queue_resets_index(manager):
    manager.set_queue([_spec("/cmd-a"), _spec("/cmd-b")])
    manager._current_index = 1
    manager.set_queue([_spec("/cmd-c")])
    assert manager._current_index == 0


# ── start ─────────────────────────────────────────────────────────────────────


def test_start_with_empty_queue_does_nothing(manager, mock_bus):
    manager.start()
    mock_bus.pipeline_started.emit.assert_not_called()


def test_start_creates_pipeline_execution_in_db(manager, factory):
    manager.set_queue([_spec()])
    with patch("workflow_app.pipeline.pipeline_manager.ProcessRunner"):
        manager.start(permission_mode="acceptEdits")
    with factory() as session:
        assert session.query(PipelineExecution).count() == 1


def test_start_emits_pipeline_started(manager, mock_bus):
    manager.set_queue([_spec()])
    with patch("workflow_app.pipeline.pipeline_manager.ProcessRunner"):
        manager.start(permission_mode="acceptEdits")
    mock_bus.pipeline_started.emit.assert_called_once()


def test_start_creates_command_execution_in_db(manager, factory):
    manager.set_queue([_spec("/my-cmd")])
    with patch("workflow_app.pipeline.pipeline_manager.ProcessRunner"):
        manager.start(permission_mode="acceptEdits")
    with factory() as session:
        ce = session.query(CommandExecution).first()
        assert ce is not None
        assert ce.command_name == "/my-cmd"


def test_start_stores_permission_mode(manager):
    manager.set_queue([_spec()])
    with patch("workflow_app.pipeline.pipeline_manager.ProcessRunner"):
        manager.start(permission_mode="manual")
    assert manager._permission_mode == "manual"


# ── pause / resume ────────────────────────────────────────────────────────────


def test_pause_sets_paused_flag(manager):
    manager.set_queue([_spec()])
    with patch("workflow_app.pipeline.pipeline_manager.ProcessRunner"):
        manager.start(permission_mode="acceptEdits")
    manager.pause()
    assert manager._paused is True


def test_pause_emits_pipeline_paused(manager, mock_bus):
    manager.set_queue([_spec()])
    with patch("workflow_app.pipeline.pipeline_manager.ProcessRunner"):
        manager.start(permission_mode="acceptEdits")
    manager.pause()
    mock_bus.pipeline_paused.emit.assert_called_once()


def test_resume_clears_paused_flag(manager):
    manager.set_queue([_spec()])
    with patch("workflow_app.pipeline.pipeline_manager.ProcessRunner"):
        manager.start(permission_mode="acceptEdits")
        manager.pause()
        manager.resume()
    assert manager._paused is False


def test_resume_emits_pipeline_resumed(manager, mock_bus):
    manager.set_queue([_spec()])
    with patch("workflow_app.pipeline.pipeline_manager.ProcessRunner"):
        manager.start(permission_mode="acceptEdits")
        manager.pause()
        manager.resume()
    mock_bus.pipeline_resumed.emit.assert_called_once()


# ── cancel ────────────────────────────────────────────────────────────────────


def test_cancel_terminates_current_runner(manager):
    manager.set_queue([_spec()])
    with patch("workflow_app.pipeline.pipeline_manager.ProcessRunner") as MockRunner:
        mock_runner_instance = MockRunner.return_value
        manager.start(permission_mode="acceptEdits")
        manager.cancel()
    mock_runner_instance.terminate.assert_called_once()


def test_cancel_emits_pipeline_cancelled(manager, mock_bus):
    manager.set_queue([_spec()])
    with patch("workflow_app.pipeline.pipeline_manager.ProcessRunner"):
        manager.start(permission_mode="acceptEdits")
    manager.cancel()
    mock_bus.pipeline_cancelled.emit.assert_called_once()


# ── advance / pipeline completion ─────────────────────────────────────────────


def test_advance_past_last_command_completes_pipeline(manager, mock_bus):
    manager.set_queue([_spec()])
    with patch("workflow_app.pipeline.pipeline_manager.ProcessRunner"):
        manager.start(permission_mode="acceptEdits")
    # Simulate the running command finishing OK
    sm = manager._state_machines[manager._current_command_exec_id]
    sm.result_ok()
    manager.advance()
    mock_bus.pipeline_completed.emit.assert_called_once()


def test_on_command_completed_auto_advances_to_next(manager):
    """AUTO interaction type: successful completion advances to index 1."""
    specs = [_spec("/cmd-1"), _spec("/cmd-2")]
    manager.set_queue(specs)
    with patch("workflow_app.pipeline.pipeline_manager.ProcessRunner"):
        manager.start(permission_mode="acceptEdits")
        exec_id = manager._current_command_exec_id
        manager._on_command_completed(exec_id, True)
    assert manager._current_index == 1


def test_on_command_completed_interactive_does_not_autocast(manager):
    """INTERACTIVE type: successful completion must NOT auto-advance."""
    spec = _spec(interaction_type=InteractionType.INTERACTIVE)
    manager.set_queue([spec])
    with patch("workflow_app.pipeline.pipeline_manager.ProcessRunner"):
        manager.start(permission_mode="acceptEdits")
        exec_id = manager._current_command_exec_id
        manager._on_command_completed(exec_id, True)
    assert manager._current_index == 0


def test_interactive_command_emits_advance_ready(manager, mock_bus):
    """INTERACTIVE completion emits interactive_advance_ready with command_exec_id."""
    spec = _spec(interaction_type=InteractionType.INTERACTIVE)
    manager.set_queue([spec, _spec("/next")])
    with patch("workflow_app.pipeline.pipeline_manager.ProcessRunner"):
        manager.start(permission_mode="acceptEdits")
        exec_id = manager._current_command_exec_id
        manager._on_command_completed(exec_id, True)
    mock_bus.interactive_advance_ready.emit.assert_called_once_with(exec_id)


def test_interactive_advance_wrong_state_is_noop(manager, mock_bus):
    """interactive_advance() is a no-op when current command is still EXECUTANDO."""
    spec = _spec(interaction_type=InteractionType.INTERACTIVE)
    manager.set_queue([spec, _spec("/next")])
    with patch("workflow_app.pipeline.pipeline_manager.ProcessRunner"):
        manager.start(permission_mode="acceptEdits")
        # command is EXECUTANDO — do NOT call _on_command_completed
        manager.interactive_advance()
    # Index must NOT have advanced
    assert manager._current_index == 0


# ── check_resume ──────────────────────────────────────────────────────────────


def test_check_resume_returns_none_when_no_interrupted_pipelines(manager):
    assert manager.check_resume() is None
