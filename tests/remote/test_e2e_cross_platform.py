"""
E2E Cross-Platform Tests — module-12/TASK-1

Validates the complete PC ↔ Android communication protocol:
- Full message flow: PC sends → Android parses (Python MessageParser simulation)
- Full message flow: Android sends → PC validates and dispatches
- Protocol contract between output_throttle, signal_bridge, and remote_server
- Protocol compliance verified post-fix for DIV-001 and DIV-002

Architecture note:
  These tests exercise the Python protocol layer end-to-end using mocked
  QWebSocket transport. Android-side parsing is simulated via direct JSON
  validation against the expected wire format (matching MessageParser.kt).
"""

from __future__ import annotations

import json
import uuid
from unittest.mock import MagicMock, patch

import pytest

from workflow_app.remote.protocol import (
    ANDROID_ACCEPTED_TYPES,
    PC_ACCEPTED_TYPES,
    ControlAction,
    MessageType,
    PipelineStatus,
    ResponseType,
    WsEnvelope,
    is_valid_client_message,
)
from workflow_app.remote.remote_server import RemoteServer, RemoteServerState
from workflow_app.remote.tailscale import TailscaleResult

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def signal_bus():
    """Mock signal bus with all required remote signals."""
    bus = MagicMock()
    bus.remote_mode_toggle_requested = MagicMock()
    bus.remote_mode_toggle_requested.connect = MagicMock()
    bus.remote_server_started = MagicMock()
    bus.remote_server_stopped = MagicMock()
    bus.remote_client_connected = MagicMock()
    bus.remote_client_disconnected = MagicMock()
    bus.command_output = MagicMock()
    bus.command_started = MagicMock()
    bus.command_completed = MagicMock()
    bus.command_failed = MagicMock()
    return bus


@pytest.fixture
def mock_server(qapp, signal_bus):
    """RemoteServer with mocked Tailscale and QWebSocketServer."""
    with patch("workflow_app.remote.remote_server.TailscaleDetector") as mock_ts, \
         patch("workflow_app.remote.remote_server.QWebSocketServer") as mock_ws_cls:

        mock_ts.return_value.detect.return_value = TailscaleResult(
            success=True, ip="127.0.0.1", error=""
        )
        mock_ws = MagicMock()
        mock_ws.listen.return_value = True
        mock_ws.newConnection = MagicMock()
        mock_ws.newConnection.connect = MagicMock()
        mock_ws_cls.return_value = mock_ws

        server = RemoteServer(signal_bus)
        server.start()
        yield server


@pytest.fixture
def connected_server(mock_server, signal_bus):
    """Server with a connected client (CONNECTED_CLIENT state)."""
    mock_client = MagicMock()
    mock_client.isValid.return_value = True
    mock_client.peerAddress.return_value.toString.return_value = "127.0.0.1"
    mock_server._client = mock_client
    mock_server._state = RemoteServerState.CONNECTED_CLIENT
    signal_bus.remote_client_connected.emit.reset_mock()
    return mock_server


# ── 1. Protocol Envelope Round-Trip ──────────────────────────────────────────


class TestProtocolEnvelopeRoundTrip:
    """End-to-end serialization: Python WsEnvelope → JSON → re-parsed."""

    def test_envelope_to_dict_and_back(self):
        """WsEnvelope serializes and deserializes without data loss."""
        original = WsEnvelope(
            type=MessageType.PIPELINE_STATE.value,
            payload={"status": "running", "command_queue": []},
        )
        wire = json.dumps(original.to_dict())

        parsed = WsEnvelope.from_dict(json.loads(wire))

        assert parsed.type == original.type
        assert parsed.payload == original.payload
        assert parsed.message_id == original.message_id

    def test_envelope_has_uuid_message_id(self):
        """Every envelope gets a unique UUID message_id."""
        env1 = WsEnvelope(type=MessageType.OUTPUT_CHUNK.value, payload={"lines": []})
        env2 = WsEnvelope(type=MessageType.OUTPUT_CHUNK.value, payload={"lines": []})

        assert env1.message_id != env2.message_id
        # Validate it's a real UUID
        uuid.UUID(env1.message_id)

    def test_envelope_has_timestamp(self):
        """Every envelope includes an ISO-8601 timestamp."""
        env = WsEnvelope(type=MessageType.ERROR.value, payload={"message": "test"})
        assert "T" in env.timestamp  # ISO-8601 format

    def test_from_dict_rejects_missing_message_id(self):
        """from_dict raises ValueError when message_id is None."""
        data = {
            "message_id": None,
            "type": "error",
            "timestamp": "2026-03-15T00:00:00+00:00",
            "payload": {"message": "test"},
        }
        with pytest.raises(ValueError, match="message_id"):
            WsEnvelope.from_dict(data)

    def test_from_dict_rejects_unknown_type(self):
        """from_dict raises ValueError for unknown message type."""
        data = {
            "message_id": str(uuid.uuid4()),
            "type": "unknown_type",
            "timestamp": "2026-03-15T00:00:00+00:00",
            "payload": {},
        }
        with pytest.raises(ValueError, match="Unknown message type"):
            WsEnvelope.from_dict(data)


# ── 2. PC → Android Message Flow ──────────────────────────────────────────────


class TestPCToAndroidFlow:
    """Tests for messages sent from PC to Android (server → client)."""

    def test_pipeline_state_wire_format(self):
        """pipeline_state message has correct wire format for Android."""
        env = WsEnvelope(
            type=MessageType.PIPELINE_STATE.value,
            payload={
                "status": PipelineStatus.RUNNING.value,
                "command_queue": [
                    {"index": 0, "name": "echo hello", "status": "running"}
                ],
            },
        )
        env.validate_payload()
        wire = env.to_dict()

        assert wire["type"] == "pipeline_state"
        assert wire["payload"]["status"] == "running"
        assert len(wire["payload"]["command_queue"]) == 1

    def test_output_chunk_android_expected_format(self):
        """output_chunk must have 'lines' (List) key — Android MessageParser expects it."""
        # This test documents the CORRECT format (DIV-001 fix target)
        env = WsEnvelope(
            type=MessageType.OUTPUT_CHUNK.value,
            payload={"lines": ["line 1", "line 2", "line 3"]},
        )
        env.validate_payload()  # should NOT raise

        wire = env.to_dict()
        assert "lines" in wire["payload"]
        assert isinstance(wire["payload"]["lines"], list)

    def test_output_chunk_invalid_text_field_fails_validation(self):
        """output_chunk with 'text' field (DIV-001) fails protocol validation."""
        env = WsEnvelope(
            type=MessageType.OUTPUT_CHUNK.value,
            payload={"text": "line 1\nline 2"},  # WRONG: DIV-001 bug
        )
        with pytest.raises(KeyError, match="lines"):
            env.validate_payload()

    def test_output_truncated_wire_format(self):
        """output_truncated must have 'lines_omitted' key — Android expects it."""
        env = WsEnvelope(
            type=MessageType.OUTPUT_TRUNCATED.value,
            payload={"lines_omitted": 42},  # Correct field name
        )
        env.validate_payload()

        wire = env.to_dict()
        assert wire["payload"]["lines_omitted"] == 42

    def test_output_truncated_wrong_field_fails_validation(self):
        """output_truncated with 'lines_skipped' (DIV-002) fails protocol validation."""
        env = WsEnvelope(
            type=MessageType.OUTPUT_TRUNCATED.value,
            payload={"lines_skipped": 42},  # WRONG: DIV-002 bug
        )
        with pytest.raises(KeyError, match="lines_omitted"):
            env.validate_payload()

    def test_interaction_request_wire_format(self):
        """interaction_request has required 'prompt' field."""
        env = WsEnvelope(
            type=MessageType.INTERACTION_REQUEST.value,
            payload={"prompt": "Continue? [Y/n]", "type": "text", "options": []},
        )
        env.validate_payload()

        wire = env.to_dict()
        assert wire["payload"]["prompt"] == "Continue? [Y/n]"

    def test_control_ack_wire_format(self):
        """control_ack has required 'action' and 'accepted' fields."""
        env = WsEnvelope(
            type=MessageType.CONTROL_ACK.value,
            payload={"action": "play", "accepted": True},
        )
        env.validate_payload()

    def test_interactive_mode_ended_empty_payload_valid(self):
        """interactive_mode_ended with empty payload {} is valid."""
        env = WsEnvelope(
            type=MessageType.INTERACTIVE_MODE_ENDED.value,
            payload={},
        )
        env.validate_payload()  # must not raise

    def test_error_wire_format(self):
        """error message has required 'message' field."""
        env = WsEnvelope(
            type=MessageType.ERROR.value,
            payload={"message": "Connection refused", "code": "REMOTE_003"},
        )
        env.validate_payload()

    def test_server_sends_message_to_connected_client(self, connected_server):
        """RemoteServer.send_message() serializes and sends to mock client."""
        env = WsEnvelope(
            type=MessageType.PIPELINE_STATE.value,
            payload={"status": "idle", "command_queue": []},
        )
        connected_server.send_message(env)

        connected_server._client.sendTextMessage.assert_called_once()
        sent_raw = connected_server._client.sendTextMessage.call_args[0][0]
        wire = json.loads(sent_raw)
        assert wire["type"] == "pipeline_state"
        assert wire["payload"]["status"] == "idle"


# ── 3. Android → PC Message Flow ──────────────────────────────────────────────


class TestAndroidToPCFlow:
    """Tests for messages sent from Android to PC (client → server)."""

    def test_control_play_is_valid_inbound(self):
        """control/play is accepted by the PC server."""
        assert is_valid_client_message("control") is True

    def test_interaction_response_is_valid_inbound(self):
        """interaction_response is accepted by the PC server."""
        assert is_valid_client_message("interaction_response") is True

    def test_sync_request_is_valid_inbound(self):
        """sync_request is accepted by the PC server."""
        assert is_valid_client_message("sync_request") is True

    def test_output_chunk_is_not_valid_inbound(self):
        """output_chunk (PC→Android only) is rejected as inbound."""
        assert is_valid_client_message("output_chunk") is False

    def test_pipeline_state_is_not_valid_inbound(self):
        """pipeline_state (PC→Android only) is rejected as inbound."""
        assert is_valid_client_message("pipeline_state") is False

    def test_control_message_wire_format(self):
        """control message from Android has correct wire format."""
        env = WsEnvelope(
            type=MessageType.CONTROL.value,
            payload={"action": ControlAction.PLAY.value},
        )
        env.validate_payload()
        wire = env.to_dict()

        assert wire["type"] == "control"
        assert wire["payload"]["action"] == "play"

    def test_interaction_response_wire_format(self):
        """interaction_response from Android has required fields."""
        env = WsEnvelope(
            type=MessageType.INTERACTION_RESPONSE.value,
            payload={
                "text": "yes",
                "response_type": ResponseType.YES.value,
            },
        )
        env.validate_payload()
        wire = env.to_dict()

        assert wire["payload"]["text"] == "yes"
        assert wire["payload"]["response_type"] == "yes"

    def test_sync_request_empty_payload_valid(self):
        """sync_request from Android with empty payload {} is valid."""
        env = WsEnvelope(
            type=MessageType.SYNC_REQUEST.value,
            payload={},
        )
        env.validate_payload()  # must not raise

    def test_all_pc_accepted_types_are_valid_inbound(self):
        """Every type in PC_ACCEPTED_TYPES is accepted as inbound."""
        for msg_type in PC_ACCEPTED_TYPES:
            assert is_valid_client_message(msg_type.value) is True

    def test_all_android_accepted_types_are_not_valid_inbound(self):
        """No type in ANDROID_ACCEPTED_TYPES (PC→Android) is accepted as inbound."""
        for msg_type in ANDROID_ACCEPTED_TYPES:
            assert is_valid_client_message(msg_type.value) is False


# ── 4. State Machine & Connection Flow ───────────────────────────────────────


class TestStateMachineFlow:
    """End-to-end state machine: OFF → STARTING → LISTENING → CONNECTED_CLIENT."""

    def test_server_starts_in_off_state(self, qapp, signal_bus):
        """RemoteServer initializes in OFF state."""
        server = RemoteServer(signal_bus)
        assert server.state == RemoteServerState.OFF

    def test_start_transitions_to_listening(self, mock_server):
        """After start() with Tailscale mocked, server is LISTENING."""
        assert mock_server.state == RemoteServerState.LISTENING

    def test_connect_transitions_to_connected_client(self, mock_server, signal_bus):
        """Accepting a valid connection transitions to CONNECTED_CLIENT."""
        mock_server._state = RemoteServerState.LISTENING

        mock_incoming = MagicMock()
        mock_incoming.peerAddress.return_value.toString.return_value = "127.0.0.1"
        mock_server._server = MagicMock()
        mock_server._server.nextPendingConnection.return_value = mock_incoming

        with patch("workflow_app.remote.remote_server.IPValidator") as mock_val:
            mock_val.return_value.validate.return_value = True
            mock_server._on_new_connection()

        assert mock_server.state == RemoteServerState.CONNECTED_CLIENT
        signal_bus.remote_client_connected.emit.assert_called()

    def test_disconnect_transitions_back_to_listening(self, connected_server):
        """Client disconnect transitions from CONNECTED_CLIENT back to LISTENING."""
        connected_server._on_disconnected()
        assert connected_server.state == RemoteServerState.LISTENING

    def test_stop_transitions_to_off(self, connected_server, signal_bus):
        """stop() transitions to OFF regardless of current state."""
        connected_server._server = MagicMock()
        connected_server.stop()

        assert connected_server.state == RemoteServerState.OFF
        signal_bus.remote_server_stopped.emit.assert_called()

    def test_full_lifecycle_state_sequence(self, qapp, signal_bus):
        """Complete OFF → STARTING → LISTENING → CONNECTED → LISTENING → OFF."""
        emitted: list[str] = []

        with patch("workflow_app.remote.remote_server.TailscaleDetector") as mock_ts, \
             patch("workflow_app.remote.remote_server.QWebSocketServer") as mock_ws_cls:

            mock_ts.return_value.detect.return_value = TailscaleResult(
                success=True, ip="127.0.0.1", error=""
            )
            mock_ws = MagicMock()
            mock_ws.listen.return_value = True
            mock_ws.newConnection = MagicMock()
            mock_ws.newConnection.connect = MagicMock()
            mock_ws_cls.return_value = mock_ws

            server = RemoteServer(signal_bus)
            server.state_changed.connect(emitted.append)
            server.start()

        # STARTING → LISTENING
        assert "starting" in emitted
        assert "listening" in emitted

        # Simulate connect
        mock_incoming = MagicMock()
        mock_incoming.peerAddress.return_value.toString.return_value = "127.0.0.1"
        server._server = MagicMock()
        server._server.nextPendingConnection.return_value = mock_incoming

        with patch("workflow_app.remote.remote_server.IPValidator") as mock_val:
            mock_val.return_value.validate.return_value = True
            server._on_new_connection()

        assert "connected_client" in emitted

        # Disconnect
        server._on_disconnected()
        assert "listening" in emitted[emitted.index("connected_client"):]

        # Stop
        server._server = MagicMock()
        server.stop()
        assert emitted[-1] == "off"


# ── 5. Security — IP Validation ───────────────────────────────────────────────


class TestIPValidationFlow:
    """Tests that the server enforces Tailscale CGNAT IP validation."""

    def test_non_tailscale_ip_rejected(self, mock_server):
        """Connection from 192.168.x.x is rejected (not Tailscale)."""
        mock_server._state = RemoteServerState.LISTENING
        mock_incoming = MagicMock()
        mock_incoming.peerAddress.return_value.toString.return_value = "192.168.1.100"
        mock_server._server = MagicMock()
        mock_server._server.nextPendingConnection.return_value = mock_incoming

        mock_server._on_new_connection()

        mock_incoming.close.assert_called_once()
        assert mock_server.state == RemoteServerState.LISTENING  # no state change

    def test_tailscale_cgnat_ip_accepted(self, mock_server, signal_bus):
        """Connection from 100.64.x.x (Tailscale CGNAT) is accepted."""
        mock_server._state = RemoteServerState.LISTENING
        mock_incoming = MagicMock()
        mock_incoming.peerAddress.return_value.toString.return_value = "100.64.0.5"
        mock_server._server = MagicMock()
        mock_server._server.nextPendingConnection.return_value = mock_incoming

        with patch("workflow_app.remote.remote_server.IPValidator") as mock_val:
            mock_val.return_value.validate.return_value = True
            mock_server._on_new_connection()

        assert mock_server.state == RemoteServerState.CONNECTED_CLIENT

    def test_localhost_accepted_with_mocked_validator(self, mock_server, signal_bus):
        """127.0.0.1 accepted when IPValidator is mocked (test environment)."""
        mock_server._state = RemoteServerState.LISTENING
        mock_incoming = MagicMock()
        mock_incoming.peerAddress.return_value.toString.return_value = "127.0.0.1"
        mock_server._server = MagicMock()
        mock_server._server.nextPendingConnection.return_value = mock_incoming

        with patch("workflow_app.remote.remote_server.IPValidator") as mock_val:
            mock_val.return_value.validate.return_value = True
            mock_server._on_new_connection()

        assert mock_server.state == RemoteServerState.CONNECTED_CLIENT

    def test_second_client_rejected_with_policy_violation(self, connected_server):
        """Second connection attempt is rejected with close code 1008."""
        from PySide6.QtWebSockets import QWebSocketProtocol

        mock_incoming = MagicMock()
        mock_incoming.peerAddress.return_value.toString.return_value = "100.64.0.9"
        connected_server._server = MagicMock()
        connected_server._server.nextPendingConnection.return_value = mock_incoming

        with patch("workflow_app.remote.remote_server.IPValidator") as mock_val:
            mock_val.return_value.validate.return_value = True
            connected_server._on_new_connection()

        mock_incoming.close.assert_called_once_with(
            QWebSocketProtocol.CloseCode.CloseCodePolicyViolated,
            "Single client mode: já existe uma conexão ativa",
        )


# ── 6. Divergence Documentation Tests ────────────────────────────────────────


class TestKnownDivergences:
    """Validates fixed protocol divergences (DIV-001, DIV-002).

    DIV-001 and DIV-002 were fixed in output_throttle.py:
    - DIV-001: _flush() now sends {'lines': List[str]} (was {'text': str})
    - DIV-002: _emit_truncated() now sends {'lines_omitted': N} (was {'lines_skipped': N})

    These tests verify the CORRECT post-fix behavior and that it matches
    what Android MessageParser.kt expects.
    """

    def test_div001_output_throttle_now_sends_lines_not_text(self):
        """DIV-001 FIXED: OutputThrottle._flush() sends {'lines': List[str]}.

        Aligned with: protocol.py validate_payload() and Android MessageParser.kt:161.
        """
        from workflow_app.remote.output_throttle import OutputThrottle

        throttle = OutputThrottle()
        sent_payloads: list[dict] = []

        mock_bridge = MagicMock()
        mock_bridge._send_message = lambda msg_type, payload: sent_payloads.append(
            {"type": msg_type, "payload": payload}
        )
        throttle.attach(mock_bridge)

        throttle.push("line 1")
        throttle.push("line 2")
        throttle._flush()

        assert len(sent_payloads) == 1
        assert sent_payloads[0]["type"] == "output_chunk"

        payload = sent_payloads[0]["payload"]
        # FIXED behavior: must send "lines" key with a list
        assert "lines" in payload, (
            "DIV-001 regression: OutputThrottle must send {'lines': [...]} not {'text': ...}"
        )
        assert isinstance(payload["lines"], list)
        assert payload["lines"] == ["line 1", "line 2"]
        assert "text" not in payload, (
            "DIV-001 regression: 'text' key must not be present after fix"
        )

    def test_div002_output_throttle_now_sends_lines_omitted(self):
        """DIV-002 FIXED: OutputThrottle._emit_truncated() sends {'lines_omitted': N}.

        Aligned with: protocol.py validate_payload() and Android MessageParser.kt:168.
        """
        from workflow_app.remote.output_throttle import OutputThrottle

        throttle = OutputThrottle()
        sent_payloads: list[dict] = []

        mock_bridge = MagicMock()
        mock_bridge._send_message = lambda msg_type, payload: sent_payloads.append(
            {"type": msg_type, "payload": payload}
        )
        throttle.attach(mock_bridge)

        throttle._emit_truncated(100)

        assert len(sent_payloads) == 1
        assert sent_payloads[0]["type"] == "output_truncated"

        payload = sent_payloads[0]["payload"]
        # FIXED behavior: must send "lines_omitted"
        assert "lines_omitted" in payload, (
            "DIV-002 regression: OutputThrottle must send {'lines_omitted': N}"
        )
        assert payload["lines_omitted"] == 100
        assert "lines_skipped" not in payload, (
            "DIV-002 regression: 'lines_skipped' key must not be present after fix"
        )

    def test_android_messageparser_expects_lines_key(self):
        """Android MessageParser.kt expects 'lines' key in output_chunk payload.

        This test validates the CORRECT wire format that the Android side expects.
        PC must send {'lines': List[str]} for Android to render output.
        """
        # Correct format (what Android expects):
        correct_env = WsEnvelope(
            type=MessageType.OUTPUT_CHUNK.value,
            payload={"lines": ["line 1", "line 2"]},
        )
        correct_env.validate_payload()  # should pass

        wire = correct_env.to_dict()
        assert isinstance(wire["payload"]["lines"], list)

    def test_android_messageparser_expects_lines_omitted_key(self):
        """Android MessageParser.kt expects 'lines_omitted' key in output_truncated.

        PC must send {'lines_omitted': N} for Android to show truncation count.
        """
        correct_env = WsEnvelope(
            type=MessageType.OUTPUT_TRUNCATED.value,
            payload={"lines_omitted": 42},
        )
        correct_env.validate_payload()  # should pass

        wire = correct_env.to_dict()
        assert wire["payload"]["lines_omitted"] == 42


# ── 7. Enum Compatibility Cross-Platform ─────────────────────────────────────


class TestEnumCompatibilityFlow:
    """Validates that Python enums match Android WsMessageType strings.

    Android defines these in WsMessageType.kt (RemoteConstants.kt).
    Any mismatch causes silent message drops on Android side.
    """

    ANDROID_MESSAGE_TYPES = {
        # PC → Android
        "output_chunk",
        "output_truncated",
        "pipeline_state",
        "interaction_request",
        "interactive_mode_ended",
        "error",
        "control_ack",
        # Android → PC
        "control",
        "interaction_response",
        "sync_request",
    }

    ANDROID_CONTROL_ACTIONS = {"play", "pause", "skip"}

    def test_all_message_types_match_android(self):
        """Every Python MessageType value matches an Android WsMessageType constant."""
        python_types = {t.value for t in MessageType}
        assert python_types == self.ANDROID_MESSAGE_TYPES

    def test_all_control_actions_match_android(self):
        """Every Python ControlAction value matches Android ControlType constant."""
        python_actions = {a.value for a in ControlAction}
        assert python_actions == self.ANDROID_CONTROL_ACTIONS

    def test_pipeline_status_values(self):
        """Python PipelineStatus values are valid strings Android can parse."""
        expected = {
            "idle", "running", "paused", "completed", "failed",
            "cancelled", "waiting_interaction", "interactive_mode",
        }
        python_values = {s.value for s in PipelineStatus}
        assert python_values == expected

    def test_response_type_values(self):
        """Python ResponseType values match Android ResponseType enum."""
        expected = {"text", "yes", "no", "cancel"}
        python_values = {r.value for r in ResponseType}
        assert python_values == expected
