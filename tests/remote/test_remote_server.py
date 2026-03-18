"""
Tests for RemoteServer — module-2/TASK-1.

Covers BDD scenarios 1-7:
1. Bind na interface Tailscale
2. Fallback de porta
3. Conexão única (rejeição de segundo cliente)
4. State machine STOPPED → LISTENING → CONNECTED
5. Lifecycle com toggle (stop() via remote_mode_toggle_requested)
6. IP fora do range Tailscale rejeitado
7. Signal state_changed emitido em cada transição
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

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
    return bus


@pytest.fixture
def server(qapp, signal_bus):
    """RemoteServer instance with mocked signal bus."""
    return RemoteServer(signal_bus)


@pytest.fixture
def tailscale_ok():
    """Patch TailscaleDetector to return a valid IP."""
    with patch(
        "workflow_app.remote.remote_server.TailscaleDetector"
    ) as mock_cls:
        mock_cls.return_value.detect.return_value = TailscaleResult(
            success=True, ip="100.64.0.1", error=""
        )
        yield mock_cls


@pytest.fixture
def tailscale_fail():
    """Patch TailscaleDetector to return a failure."""
    with patch(
        "workflow_app.remote.remote_server.TailscaleDetector"
    ) as mock_cls:
        mock_cls.return_value.detect.return_value = TailscaleResult(
            success=False, ip="", error="Tailscale não encontrado."
        )
        yield mock_cls


# ── State machine ─────────────────────────────────────────────────────────────


def test_initial_state_is_off(server):
    """RemoteServer starts in OFF state."""
    assert server.state == RemoteServerState.OFF
    assert server.is_running() is False
    assert server.has_client() is False


# ── Cenário 1: Bind na interface Tailscale ────────────────────────────────────


def test_start_binds_to_tailscale_ip(server, tailscale_ok):
    """BDD Cenário 1: start() binds only to Tailscale IP, never 0.0.0.0."""
    with patch(
        "workflow_app.remote.remote_server.QWebSocketServer"
    ) as mock_server_cls:
        mock_ws = MagicMock()
        mock_ws.listen.return_value = True
        mock_ws.newConnection = MagicMock()
        mock_ws.newConnection.connect = MagicMock()
        mock_server_cls.return_value = mock_ws

        result = server.start()

    assert result is True
    # Verify listen was called with the Tailscale IP
    listen_calls = mock_ws.listen.call_args_list
    assert len(listen_calls) >= 1
    host_addr = listen_calls[0][0][0]  # first positional arg of first call
    assert host_addr.toString() == "100.64.0.1"


# ── Cenário 2: Fallback de porta ──────────────────────────────────────────────


def test_start_fallback_port(server, tailscale_ok):
    """BDD Cenário 2: If first port is busy, tries next ports."""
    with patch(
        "workflow_app.remote.remote_server.QWebSocketServer"
    ) as mock_server_cls:
        mock_ws = MagicMock()
        # First port busy, second succeeds
        mock_ws.listen.side_effect = [False, True]
        mock_ws.newConnection = MagicMock()
        mock_ws.newConnection.connect = MagicMock()
        mock_server_cls.return_value = mock_ws

        result = server.start()

    assert result is True
    assert mock_ws.listen.call_count == 2


def test_start_all_ports_busy(server, tailscale_ok, signal_bus):
    """If all ports are busy, start() returns False and emits remote_server_stopped."""
    with patch(
        "workflow_app.remote.remote_server.QWebSocketServer"
    ) as mock_server_cls:
        mock_ws = MagicMock()
        mock_ws.listen.return_value = False
        mock_ws.newConnection = MagicMock()
        mock_ws.newConnection.connect = MagicMock()
        mock_server_cls.return_value = mock_ws

        result = server.start()

    assert result is False
    signal_bus.remote_server_stopped.emit.assert_called_once()
    assert server.state == RemoteServerState.OFF


# ── Cenário 3: Conexão única ─────────────────────────────────────────────────


def test_second_client_rejected_with_1008(server, qapp):
    """BDD Cenário 3: Second connection attempt is rejected with close code 1008."""
    # Set up: server is in CONNECTED_CLIENT state with a valid client
    mock_existing_client = MagicMock()
    mock_existing_client.isValid.return_value = True
    server._client = mock_existing_client
    server._state = RemoteServerState.CONNECTED_CLIENT

    mock_server = MagicMock()
    mock_incoming = MagicMock()
    mock_incoming.peerAddress.return_value.toString.return_value = "100.64.0.2"
    mock_server.nextPendingConnection.return_value = mock_incoming
    server._server = mock_server

    # Patch IPValidator to allow this IP
    with patch(
        "workflow_app.remote.remote_server.IPValidator"
    ) as mock_validator_cls:
        mock_validator_cls.return_value.validate.return_value = True
        server._on_new_connection()

    from PySide6.QtWebSockets import QWebSocketProtocol
    mock_incoming.close.assert_called_once_with(
        QWebSocketProtocol.CloseCode.CloseCodePolicyViolated,
        "Single client mode: já existe uma conexão ativa",
    )
    mock_incoming.deleteLater.assert_called_once()


# ── Cenário 4: State machine ──────────────────────────────────────────────────


def test_state_transitions_stopped_listening_connected(server, tailscale_ok):
    """BDD Cenário 4: State transitions STOPPED → LISTENING → CONNECTED."""
    assert server.state == RemoteServerState.OFF

    with patch(
        "workflow_app.remote.remote_server.QWebSocketServer"
    ) as mock_server_cls:
        mock_ws = MagicMock()
        mock_ws.listen.return_value = True
        mock_ws.newConnection = MagicMock()
        mock_ws.newConnection.connect = MagicMock()
        mock_server_cls.return_value = mock_ws

        server.start()

    assert server.state == RemoteServerState.LISTENING
    assert server.is_running() is True


# ── Cenário 5: Lifecycle com toggle ──────────────────────────────────────────


def test_toggle_off_calls_stop(server, signal_bus):
    """BDD Cenário 5: Toggle OFF calls stop() via _on_mode_toggle."""
    server._state = RemoteServerState.LISTENING
    server._server = MagicMock()
    server._server.close = MagicMock()
    server._server.deleteLater = MagicMock()

    server._on_mode_toggle(False)

    assert server.state == RemoteServerState.OFF
    signal_bus.remote_server_stopped.emit.assert_called()


def test_toggle_on_calls_start(server, tailscale_ok):
    """Toggle ON calls start()."""
    with patch.object(server, "start", return_value=True) as mock_start:
        server._on_mode_toggle(True)

    mock_start.assert_called_once()


# ── Cenário 6: IP fora do range Tailscale rejeitado ──────────────────────────


def test_non_tailscale_ip_rejected(server):
    """BDD Cenário 6: Connection from non-Tailscale IP is rejected with close code 1008."""
    mock_server = MagicMock()
    mock_incoming = MagicMock()
    mock_incoming.peerAddress.return_value.toString.return_value = "192.168.1.10"
    mock_server.nextPendingConnection.return_value = mock_incoming
    server._server = mock_server
    server._state = RemoteServerState.LISTENING

    server._on_new_connection()

    from PySide6.QtWebSockets import QWebSocketProtocol
    mock_incoming.close.assert_called_once_with(
        QWebSocketProtocol.CloseCode.CloseCodePolicyViolated,
        "IP não autorizado: apenas conexões Tailscale são aceitas",
    )
    mock_incoming.deleteLater.assert_called_once()
    # State must not change to CONNECTED
    assert server.state == RemoteServerState.LISTENING


# ── Cenário 7: state_changed emitido em cada transição ───────────────────────


def test_state_changed_signal_emitted(server, qapp):
    """BDD Cenário 7: state_changed Signal is emitted on every state transition."""
    emitted_values: list[str] = []

    server.state_changed.connect(emitted_values.append)

    server._set_state(RemoteServerState.LISTENING)
    server._set_state(RemoteServerState.CONNECTED_CLIENT)
    server._set_state(RemoteServerState.OFF)

    assert emitted_values == ["listening", "connected_client", "off"]


# ── Remote server_started format ─────────────────────────────────────────────


def test_remote_server_started_format(server, tailscale_ok, signal_bus):
    """BDD ST007: remote_server_started emits 'ip:port' format string."""
    import re

    with patch(
        "workflow_app.remote.remote_server.QWebSocketServer"
    ) as mock_server_cls:
        mock_ws = MagicMock()
        mock_ws.listen.return_value = True
        mock_ws.newConnection = MagicMock()
        mock_ws.newConnection.connect = MagicMock()
        mock_server_cls.return_value = mock_ws

        server.start()

    call_args = signal_bus.remote_server_started.emit.call_args
    assert call_args is not None
    addr = call_args[0][0]
    assert re.match(r"^100\.\d+\.\d+\.\d+:\d{4,5}$", addr), f"Bad format: {addr!r}"


# ── Tailscale not found stops server ─────────────────────────────────────────


def test_tailscale_not_found_stops_server(server, tailscale_fail, signal_bus):
    """If TailscaleDetector fails, start() returns False and emits remote_server_stopped."""
    result = server.start()

    assert result is False
    assert server.state == RemoteServerState.OFF
    signal_bus.remote_server_stopped.emit.assert_called_once()


# ── is_running / has_client ───────────────────────────────────────────────────


def test_is_running_true_when_listening(server):
    server._state = RemoteServerState.LISTENING
    assert server.is_running() is True


def test_is_running_true_when_connected(server):
    server._state = RemoteServerState.CONNECTED_CLIENT
    assert server.is_running() is True


def test_is_running_false_when_off(server):
    server._state = RemoteServerState.OFF
    assert server.is_running() is False


def test_has_client_when_connected(server):
    server._state = RemoteServerState.CONNECTED_CLIENT
    assert server.has_client() is True


def test_has_client_false_when_listening(server):
    server._state = RemoteServerState.LISTENING
    assert server.has_client() is False


# ── TASK-4: address property ─────────────────────────────────────────────────


def test_address_empty_when_off(server):
    """address returns '' in OFF state."""
    assert server.address == ""


def test_address_set_after_start(server, tailscale_ok, signal_bus):
    """address returns 'ip:port' after successful start()."""
    with patch(
        "workflow_app.remote.remote_server.QWebSocketServer"
    ) as mock_server_cls:
        mock_ws = MagicMock()
        mock_ws.listen.return_value = True
        mock_ws.newConnection = MagicMock()
        mock_ws.newConnection.connect = MagicMock()
        mock_server_cls.return_value = mock_ws

        server.start()

    assert server.address == "100.64.0.1:18765"


def test_address_empty_after_stop(server, tailscale_ok, signal_bus):
    """address returns '' after stop()."""
    with patch(
        "workflow_app.remote.remote_server.QWebSocketServer"
    ) as mock_server_cls:
        mock_ws = MagicMock()
        mock_ws.listen.return_value = True
        mock_ws.newConnection = MagicMock()
        mock_ws.newConnection.connect = MagicMock()
        mock_server_cls.return_value = mock_ws

        server.start()
        server.stop()

    assert server.address == ""


def test_address_empty_when_all_ports_busy(server, tailscale_ok, signal_bus):
    """address stays '' when all ports are busy."""
    with patch(
        "workflow_app.remote.remote_server.QWebSocketServer"
    ) as mock_server_cls:
        mock_ws = MagicMock()
        mock_ws.listen.return_value = False
        mock_ws.newConnection = MagicMock()
        mock_ws.newConnection.connect = MagicMock()
        mock_server_cls.return_value = mock_ws

        server.start()

    assert server.address == ""


# ── TASK-4: send_message ─────────────────────────────────────────────────────


def test_send_message_serializes_envelope(server):
    """send_message() serializes WsEnvelope to JSON and calls send_text()."""
    import json

    from workflow_app.remote.protocol import WsEnvelope

    mock_client = MagicMock()
    mock_client.isValid.return_value = True
    server._client = mock_client

    envelope = WsEnvelope(type="pipeline_state", payload={"status": "running"})
    server.send_message(envelope)

    mock_client.sendTextMessage.assert_called_once()
    sent_json = mock_client.sendTextMessage.call_args[0][0]
    data = json.loads(sent_json)
    assert data["type"] == "pipeline_state"
    assert data["payload"]["status"] == "running"


def test_send_message_no_client(server):
    """send_message() does not raise when no client is connected."""
    from workflow_app.remote.protocol import WsEnvelope

    envelope = WsEnvelope(type="pipeline_state", payload={})
    server.send_message(envelope)  # should not raise


# ── TASK-5: disconnect flow and signal emissions ─────────────────────────────


def test_disconnect_flow_connected_to_listening(server, signal_bus):
    """_on_disconnected() transitions from CONNECTED_CLIENT to LISTENING."""
    mock_client = MagicMock()
    server._client = mock_client
    server._state = RemoteServerState.CONNECTED_CLIENT

    server._on_disconnected()

    assert server.state == RemoteServerState.LISTENING
    assert server._client is None
    mock_client.deleteLater.assert_called_once()


def test_disconnect_emits_remote_client_disconnected(server, signal_bus):
    """_on_disconnected() emits remote_client_disconnected on SignalBus."""
    server._client = MagicMock()
    server._state = RemoteServerState.CONNECTED_CLIENT

    server._on_disconnected()

    signal_bus.remote_client_disconnected.emit.assert_called_once()


def test_connect_emits_remote_client_connected(server, signal_bus):
    """_on_new_connection() emits remote_client_connected when accepting valid client."""
    mock_server = MagicMock()
    mock_incoming = MagicMock()
    mock_incoming.peerAddress.return_value.toString.return_value = "100.64.0.2"
    mock_server.nextPendingConnection.return_value = mock_incoming
    server._server = mock_server
    server._state = RemoteServerState.LISTENING

    with patch(
        "workflow_app.remote.remote_server.IPValidator"
    ) as mock_validator_cls:
        mock_validator_cls.return_value.validate.return_value = True
        server._on_new_connection()

    signal_bus.remote_client_connected.emit.assert_called_once()
    assert server.state == RemoteServerState.CONNECTED_CLIENT


def test_send_text_no_client_no_error(server):
    """send_text() with no client does not raise."""
    server._client = None
    server.send_text("hello")  # should not raise


def test_send_text_invalid_client_no_error(server):
    """send_text() with invalid client does not send."""
    mock_client = MagicMock()
    mock_client.isValid.return_value = False
    server._client = mock_client

    server.send_text("hello")

    mock_client.sendTextMessage.assert_not_called()


def test_full_state_chain_off_listening_connected(server, tailscale_ok, signal_bus):
    """BDD C4 complete: OFF → STARTING → LISTENING → CONNECTED_CLIENT."""
    emitted: list[str] = []
    server.state_changed.connect(emitted.append)

    with patch(
        "workflow_app.remote.remote_server.QWebSocketServer"
    ) as mock_server_cls:
        mock_ws = MagicMock()
        mock_ws.listen.return_value = True
        mock_ws.newConnection = MagicMock()
        mock_ws.newConnection.connect = MagicMock()
        mock_server_cls.return_value = mock_ws

        server.start()

    assert "starting" in emitted
    assert "listening" in emitted

    # Simulate client connection
    mock_incoming = MagicMock()
    mock_incoming.peerAddress.return_value.toString.return_value = "100.64.0.5"
    server._server = MagicMock()
    server._server.nextPendingConnection.return_value = mock_incoming

    with patch(
        "workflow_app.remote.remote_server.IPValidator"
    ) as mock_validator_cls:
        mock_validator_cls.return_value.validate.return_value = True
        server._on_new_connection()

    assert "connected_client" in emitted
    assert server.state == RemoteServerState.CONNECTED_CLIENT
