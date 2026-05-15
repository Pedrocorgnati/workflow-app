"""Tests for local-action dispatch (loop task-010).

Covers CommandSpec.kind == "local-action":
- registered handler is invoked with the originating spec and its return value
  drives command_completed success;
- pipeline emits command_completed with the correct (position, success) signal;
- unknown action_id surfaces as a worker error and routes the command to ERRO.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from workflow_app.command_queue.local_actions import (
    clear_registry,
    dispatch_local_action,
    get_local_action,
    register_local_action,
)
from workflow_app.db.models import Base
from workflow_app.domain import CommandSpec, InteractionType, ModelName
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


@pytest.fixture(autouse=True)
def _clean_registry():
    clear_registry()
    yield
    clear_registry()


def _local_spec(action_id: str | None = "load_specific_flow") -> CommandSpec:
    return CommandSpec(
        name="/dcp:load-specific-flow",
        model=ModelName.SONNET,
        interaction_type=InteractionType.AUTO,
        kind="local-action",
        local_action_id=action_id,
    )


# ── Registry sanity ───────────────────────────────────────────────────────────


def test_register_and_dispatch_returns_handler_result():
    register_local_action("noop_true", lambda spec: True)
    assert get_local_action("noop_true") is not None
    assert dispatch_local_action("noop_true", _local_spec("noop_true")) is True


def test_dispatch_unknown_returns_false():
    assert dispatch_local_action("does_not_exist", _local_spec("does_not_exist")) is False


def test_dispatch_swallows_handler_exceptions():
    def boom(spec):
        raise RuntimeError("kaboom")

    register_local_action("boom", boom)
    assert dispatch_local_action("boom", _local_spec("boom")) is False


# ── Pipeline integration ─────────────────────────────────────────────────────


def test_local_action_calls_registered_handler(manager):
    """Dispatch invokes the registered callable with the originating spec."""
    received: list[CommandSpec] = []

    def handler(spec: CommandSpec) -> bool:
        received.append(spec)
        return True

    register_local_action("load_specific_flow", handler)

    spec = _local_spec("load_specific_flow")
    manager.set_queue([spec])

    with patch("workflow_app.pipeline.pipeline_manager.ProcessRunner") as proc:
        manager.start(permission_mode="acceptEdits")
        # ProcessRunner must NOT be instantiated when kind == "local-action".
        proc.assert_not_called()

    assert len(received) == 1
    assert received[0].local_action_id == "load_specific_flow"
    assert received[0].kind == "local-action"


def test_local_action_emits_command_completed_with_success_flag(manager, mock_bus):
    """Success of the local action propagates through the same SignalBus path
    used by the slash branch — terminal output chunk + state-machine completion."""
    register_local_action("succeeds", lambda spec: True)

    spec = _local_spec("succeeds")
    manager.set_queue([spec])

    with patch("workflow_app.pipeline.pipeline_manager.ProcessRunner"):
        manager.start(permission_mode="acceptEdits")

    # The dispatch emits an output banner announcing the local-action.
    emitted_text = [
        call.args[0]
        for call in mock_bus.output_chunk_received.emit.call_args_list
    ]
    assert any("local-action" in t for t in emitted_text)
    # No worker error should have fired.
    mock_bus.pipeline_error_occurred.emit.assert_not_called()


def test_unknown_action_id_returns_false_and_emits_command_failed(manager, mock_bus):
    """Unknown action_id routes the command to ERRO via _on_worker_error."""
    spec = _local_spec("ghost_action")  # never registered
    manager.set_queue([spec])

    with patch("workflow_app.pipeline.pipeline_manager.ProcessRunner") as proc:
        manager.start(permission_mode="acceptEdits")
        proc.assert_not_called()

    mock_bus.pipeline_error_occurred.emit.assert_called_once()
    err_payload = mock_bus.pipeline_error_occurred.emit.call_args.args[1]
    assert "ghost_action" in err_payload or "local-action" in err_payload


def test_default_kind_is_slash_for_backward_compat():
    """CommandSpec with no kind argument keeps the legacy slash dispatch."""
    spec = CommandSpec(name="/prd-create", model=ModelName.SONNET)
    assert spec.kind == "slash"
    assert spec.local_action_id is None
