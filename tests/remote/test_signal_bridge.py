"""
Tests for SignalBridge — bidirectional bridge between SignalBus and WebSocket protocol.

OutputThrottle is mocked to avoid QTimer dependency.
Signal connections are patched to avoid Qt signal/slot mechanics in unit tests.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from workflow_app.remote.signal_bridge import SignalBridge

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def mock_signal_bus():
    """Mock SignalBus with all signals used by SignalBridge."""
    bus = MagicMock()
    return bus


@pytest.fixture
def mock_pipeline_mgr():
    """Mock PipelineManager with the internal attributes read by build_snapshot()."""
    pm = MagicMock()
    pm._current_index = 0
    pm._queue = []
    pm._paused = False
    pm.send_interactive_response.return_value = True
    return pm


@pytest.fixture
def mock_server():
    """Mock RemoteServer with a send_text() method."""
    return MagicMock()


@pytest.fixture
def bridge(mock_signal_bus, mock_pipeline_mgr):
    """SignalBridge with OutputThrottle mocked (no QTimer)."""
    with patch("workflow_app.remote.signal_bridge.OutputThrottle") as MockThrottle:
        mock_throttle = MagicMock()
        MockThrottle.return_value = mock_throttle
        b = SignalBridge(
            signal_bus=mock_signal_bus,
            pipeline_manager=mock_pipeline_mgr,
        )
    return b


@pytest.fixture
def attached_bridge(bridge, mock_server):
    """Bridge attached to mock_server with signal connections bypassed."""
    with patch.object(bridge, "_connect_signals"):
        bridge.attach(mock_server)
    return bridge


# ── Lifecycle ─────────────────────────────────────────────────────────────────


def test_attach_sets_server(bridge, mock_server):
    with patch.object(bridge, "_connect_signals"):
        bridge.attach(mock_server)
    assert bridge._server is mock_server


def test_attach_starts_throttle(bridge, mock_server):
    with patch.object(bridge, "_connect_signals"):
        bridge.attach(mock_server)
    bridge._throttle.start.assert_called_once()


def test_detach_clears_server(bridge, mock_server):
    with patch.object(bridge, "_connect_signals"), \
         patch.object(bridge, "_disconnect_signals"):
        bridge.attach(mock_server)
        bridge.detach()
    assert bridge._server is None


def test_detach_stops_throttle(bridge, mock_server):
    with patch.object(bridge, "_connect_signals"), \
         patch.object(bridge, "_disconnect_signals"):
        bridge.attach(mock_server)
        bridge._throttle.reset_mock()
        bridge.detach()
    bridge._throttle.stop.assert_called_once()


def test_detach_clears_pending_interaction(bridge, mock_server):
    with patch.object(bridge, "_connect_signals"), \
         patch.object(bridge, "_disconnect_signals"):
        bridge.attach(mock_server)
        bridge._pending_interaction = MagicMock()
        bridge.detach()
    assert bridge._pending_interaction is None


# ── handle_incoming — dispatch ────────────────────────────────────────────────


def _make_envelope(msg_type: str, payload: dict, message_id: str = "test-id") -> str:
    return json.dumps({
        "message_id": message_id,
        "type": msg_type,
        "timestamp": "2026-01-01T00:00:00Z",
        "payload": payload,
    })


def test_handle_incoming_dispatches_sync_request(attached_bridge, mock_server):
    with patch.object(attached_bridge, "_handle_sync_request") as mock_sync:
        attached_bridge.handle_incoming(_make_envelope("sync_request", {}))
    mock_sync.assert_called_once()


def test_handle_incoming_dispatches_control(attached_bridge):
    with patch.object(attached_bridge, "_handle_control") as mock_ctrl:
        attached_bridge.handle_incoming(
            _make_envelope("control", {"action": "pause"})
        )
    mock_ctrl.assert_called_once()


def test_handle_incoming_dispatches_interaction_response(attached_bridge):
    with patch.object(attached_bridge, "_handle_interaction_response") as mock_ir:
        attached_bridge.handle_incoming(
            _make_envelope("interaction_response", {"request_id": "x", "value": "yes"})
        )
    mock_ir.assert_called_once()


def test_handle_incoming_unknown_type_sends_error(attached_bridge, mock_server):
    attached_bridge.handle_incoming(
        _make_envelope("unknown_type_xyz", {}, message_id="unk-1")
    )
    mock_server.send_text.assert_called_once()
    data = json.loads(mock_server.send_text.call_args[0][0])
    assert data["type"] == "error"
    assert data["payload"]["code"] == "UNKNOWN_MESSAGE_TYPE"


def test_handle_incoming_malformed_json_sends_error(attached_bridge, mock_server):
    attached_bridge.handle_incoming("{not valid json")
    mock_server.send_text.assert_called_once()
    data = json.loads(mock_server.send_text.call_args[0][0])
    assert data["type"] == "error"


def test_handle_incoming_duplicate_message_id_ignored(attached_bridge):
    raw = _make_envelope("sync_request", {}, message_id="dup-1")
    with patch.object(attached_bridge, "_handle_sync_request") as mock_sync:
        attached_bridge.handle_incoming(raw)
        attached_bridge.handle_incoming(raw)  # duplicate
    mock_sync.assert_called_once()


# ── Outbound handlers (PC → Android) ─────────────────────────────────────────


def test_on_pipeline_status_changed_sends_pipeline_state(
    attached_bridge, mock_server
):
    attached_bridge._on_pipeline_status_changed(1, "executando")
    mock_server.send_text.assert_called_once()
    data = json.loads(mock_server.send_text.call_args[0][0])
    assert data["type"] == "pipeline_state"
    assert data["payload"]["pipeline_status"] == "RUNNING"


def test_on_command_started_sends_command_status_changed(
    attached_bridge, mock_server
):
    attached_bridge._on_command_started(2)
    mock_server.send_text.assert_called_once()
    data = json.loads(mock_server.send_text.call_args[0][0])
    assert data["type"] == "command_status_changed"
    assert data["payload"]["index"] == 2
    assert data["payload"]["status"] == "RUNNING"


def test_on_command_completed_sends_completed(attached_bridge, mock_server):
    attached_bridge._on_command_completed(1)
    data = json.loads(mock_server.send_text.call_args[0][0])
    assert data["payload"]["status"] == "COMPLETED"
    assert data["payload"]["index"] == 1


def test_on_command_failed_sends_error_status(attached_bridge, mock_server):
    attached_bridge._on_command_failed(0, "some error")
    data = json.loads(mock_server.send_text.call_args[0][0])
    assert data["payload"]["status"] == "ERROR"
    assert data["payload"]["error"] == "some error"


def test_on_command_skipped_sends_skipped_status(attached_bridge, mock_server):
    attached_bridge._on_command_skipped(3)
    data = json.loads(mock_server.send_text.call_args[0][0])
    assert data["type"] == "command_status_changed"
    assert data["payload"]["index"] == 3
    assert data["payload"]["status"] == "SKIPPED"


def test_on_pipeline_error_sends_error(attached_bridge, mock_server):
    attached_bridge._on_pipeline_error(1, "Pipeline falhou")
    data = json.loads(mock_server.send_text.call_args[0][0])
    assert data["type"] == "error"
    assert data["payload"]["code"] == "PIPELINE_ERROR"
    assert data["payload"]["message"] == "Pipeline falhou"


def test_on_output_chunk_accumulates_lines(attached_bridge):
    attached_bridge._on_output_chunk("line1\nline2\nline3")
    assert "line1" in attached_bridge._output_lines
    assert "line2" in attached_bridge._output_lines
    assert "line3" in attached_bridge._output_lines


def test_on_output_chunk_pushes_to_throttle(attached_bridge):
    attached_bridge._on_output_chunk("some text")
    attached_bridge._throttle.push.assert_called_once_with("some text")


def test_on_output_chunk_does_not_send_directly(attached_bridge, mock_server):
    """output_chunk must be delegated to throttle, not sent directly."""
    mock_server.send_text.reset_mock()
    attached_bridge._on_output_chunk("should not be direct")
    mock_server.send_text.assert_not_called()


def test_on_interactive_prompt_sets_pending_interaction(
    attached_bridge, mock_server
):
    attached_bridge._on_interactive_prompt("Continue?")
    assert attached_bridge._pending_interaction is not None
    assert attached_bridge._pending_interaction.prompt == "Continue?"
    assert attached_bridge._pending_interaction.status == "pending"
    assert attached_bridge._pending_interaction.interaction_type == "text_input"


def test_on_interactive_prompt_sends_interaction_request(
    attached_bridge, mock_server
):
    attached_bridge._on_interactive_prompt("Do it?")
    data = json.loads(mock_server.send_text.call_args[0][0])
    assert data["type"] == "interaction_request"
    assert data["payload"]["prompt"] == "Do it?"
    assert data["payload"]["status"] == "pending"


def test_on_interactive_mode_ended_clears_pending(attached_bridge, mock_server):
    attached_bridge._on_interactive_prompt("Question?")
    mock_server.send_text.reset_mock()
    attached_bridge._on_interactive_mode_ended()
    assert attached_bridge._pending_interaction is None


def test_on_interactive_mode_ended_sends_resolved_elsewhere(
    attached_bridge, mock_server
):
    attached_bridge._on_interactive_prompt("Question?")
    mock_server.send_text.reset_mock()
    attached_bridge._on_interactive_mode_ended()
    data = json.loads(mock_server.send_text.call_args[0][0])
    assert data["type"] == "interaction_request"
    assert data["payload"]["status"] == "resolved_elsewhere"


def test_on_interactive_mode_ended_without_pending_is_silent(
    attached_bridge, mock_server
):
    mock_server.send_text.reset_mock()
    attached_bridge._on_interactive_mode_ended()
    mock_server.send_text.assert_not_called()


# ── Observer passivo — não modifica estado do pipeline ───────────────────────


def test_signal_handlers_do_not_modify_pipeline_state(
    attached_bridge, mock_pipeline_mgr
):
    """All outbound handlers must be passive observers."""
    # None of these should call methods that change pipeline state
    attached_bridge._on_command_started(0)
    attached_bridge._on_command_completed(0)
    attached_bridge._on_command_failed(0, "err")
    mock_pipeline_mgr.pause.assert_not_called()
    mock_pipeline_mgr.resume.assert_not_called()
    mock_pipeline_mgr.skip_current.assert_not_called()


# ── build_snapshot ────────────────────────────────────────────────────────────


def test_build_snapshot_returns_dict(attached_bridge):
    snapshot = attached_bridge.build_snapshot()
    assert isinstance(snapshot, dict)


def test_build_snapshot_has_required_fields(attached_bridge):
    snapshot = attached_bridge.build_snapshot()
    assert "pipeline_status" in snapshot
    assert "current_index" in snapshot
    assert "queue" in snapshot
    assert "output_buffer" in snapshot
    assert "pending_interaction" in snapshot


def test_build_snapshot_output_buffer_contains_accumulated_lines(attached_bridge):
    attached_bridge._on_output_chunk("hello\nworld")
    snapshot = attached_bridge.build_snapshot()
    assert "hello" in snapshot["output_buffer"]
    assert "world" in snapshot["output_buffer"]


def test_build_snapshot_pending_interaction_none_by_default(attached_bridge):
    snapshot = attached_bridge.build_snapshot()
    assert snapshot["pending_interaction"] is None


def test_build_snapshot_includes_pending_interaction(attached_bridge, mock_server):
    attached_bridge._on_interactive_prompt("Confirm?")
    snapshot = attached_bridge.build_snapshot()
    assert snapshot["pending_interaction"] is not None
    assert snapshot["pending_interaction"]["prompt"] == "Confirm?"


def test_build_snapshot_idempotent(attached_bridge):
    """Two calls with unchanged state produce identical payloads."""
    attached_bridge._on_output_chunk("line")
    snap1 = attached_bridge.build_snapshot()
    snap2 = attached_bridge.build_snapshot()
    # Same content (pipeline_status, queue, output_buffer, pending_interaction)
    assert snap1["pipeline_status"] == snap2["pipeline_status"]
    assert snap1["output_buffer"] == snap2["output_buffer"]
    assert snap1["pending_interaction"] == snap2["pending_interaction"]


# ── Inbound: control ──────────────────────────────────────────────────────────


def test_handle_control_pause(attached_bridge, mock_pipeline_mgr):
    attached_bridge._handle_control({"action": "pause"}, "msg-1")
    mock_pipeline_mgr.pause.assert_called_once()


def test_handle_control_play_when_paused(attached_bridge, mock_pipeline_mgr):
    mock_pipeline_mgr._paused = True
    attached_bridge._handle_control({"action": "play"}, "msg-2")
    mock_pipeline_mgr.resume.assert_called_once()


def test_handle_control_skip(attached_bridge, mock_pipeline_mgr):
    attached_bridge._handle_control({"action": "skip"}, "msg-3")
    mock_pipeline_mgr.skip_current.assert_called_once()


def test_handle_control_invalid_action_sends_error(attached_bridge, mock_server):
    attached_bridge._handle_control({"action": "invalid_action"}, "msg-4")
    data = json.loads(mock_server.send_text.call_args[0][0])
    assert data["type"] == "error"
    assert data["payload"]["code"] == "INVALID_COMMAND"


# ── Inbound: interaction_response ────────────────────────────────────────────


def test_handle_interaction_response_resolves_pending(
    attached_bridge, mock_server, mock_pipeline_mgr
):
    attached_bridge._on_interactive_prompt("Question?")
    request_id = attached_bridge._pending_interaction.request_id
    mock_server.send_text.reset_mock()

    attached_bridge._handle_interaction_response(
        {"request_id": request_id, "value": "yes"}, "resp-1"
    )
    mock_pipeline_mgr.send_interactive_response.assert_called_once()
    assert attached_bridge._pending_interaction is None


def test_handle_interaction_response_no_pending_sends_error(
    attached_bridge, mock_server
):
    attached_bridge._handle_interaction_response(
        {"request_id": "x", "value": "yes"}, "resp-2"
    )
    data = json.loads(mock_server.send_text.call_args[0][0])
    assert data["type"] == "error"
    assert data["payload"]["code"] == "INTERACTION_ALREADY_RESOLVED"


def test_handle_interaction_response_wrong_request_id_sends_error(
    attached_bridge, mock_server
):
    attached_bridge._on_interactive_prompt("Question?")
    mock_server.send_text.reset_mock()
    attached_bridge._handle_interaction_response(
        {"request_id": "wrong-id", "value": "yes"}, "resp-3"
    )
    data = json.loads(mock_server.send_text.call_args[0][0])
    assert data["type"] == "error"


# ── _handle_sync_request ─────────────────────────────────────────────────────


def test_handle_sync_request_sends_pipeline_state(attached_bridge, mock_server):
    attached_bridge._handle_sync_request()
    data = json.loads(mock_server.send_text.call_args[0][0])
    assert data["type"] == "pipeline_state"


# ── No server → silent ────────────────────────────────────────────────────────


def test_send_message_without_server_is_silent(bridge):
    """_send_message must not raise when _server is None."""
    assert bridge._server is None
    bridge._send_message("pipeline_state", {})  # should not raise
