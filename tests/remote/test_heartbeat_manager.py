"""
Tests for HeartbeatManager — requires QApplication (via qapp fixture).

HeartbeatManager uses QTimer; tests mock _ping_timer and _pong_timeout_timer
after __init__ to avoid event loop dependency.

NOTE: The fixture replaces the real QTimers created in __init__ with MagicMocks
after construction. The original QTimers are orphaned but never started, so they
are harmless.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from workflow_app.remote.heartbeat_manager import HeartbeatManager


@pytest.fixture
def mock_server():
    return MagicMock()


@pytest.fixture
def manager(qapp, mock_server):
    """HeartbeatManager with mocked timers and server."""
    m = HeartbeatManager(mock_server)
    m._ping_timer = MagicMock()
    m._pong_timeout_timer = MagicMock()
    return m


# ── start ─────────────────────────────────────────────────────────────────────


def test_start_initiates_ping_timer(manager):
    mock_socket = MagicMock()
    manager.start(mock_socket)
    manager._ping_timer.start.assert_called_once()
    assert manager._socket == mock_socket


def test_start_connects_pong_signal(manager):
    mock_socket = MagicMock()
    manager.start(mock_socket)
    mock_socket.pong.connect.assert_called_once_with(manager._on_pong_received)


# ── stop ──────────────────────────────────────────────────────────────────────


def test_stop_clears_socket(manager):
    mock_socket = MagicMock()
    manager._socket = mock_socket
    manager.stop()
    assert manager._socket is None
    manager._ping_timer.stop.assert_called()
    manager._pong_timeout_timer.stop.assert_called()


def test_stop_disconnects_pong_signal(manager):
    mock_socket = MagicMock()
    manager._socket = mock_socket
    manager.stop()
    mock_socket.pong.disconnect.assert_called_once_with(manager._on_pong_received)


def test_stop_handles_destroyed_socket_gracefully(manager):
    """stop() must not raise if socket.pong.disconnect raises RuntimeError."""
    mock_socket = MagicMock()
    mock_socket.pong.disconnect.side_effect = RuntimeError("C++ object destroyed")
    manager._socket = mock_socket
    manager.stop()  # should not raise
    assert manager._socket is None


# ── _send_ping ────────────────────────────────────────────────────────────────


def test_send_ping_sends_bytes_and_starts_timeout(manager):
    mock_socket = MagicMock()
    mock_socket.isValid.return_value = True
    manager._socket = mock_socket
    manager._send_ping()
    mock_socket.ping.assert_called_once_with(b"hb")
    manager._pong_timeout_timer.start.assert_called()


def test_send_ping_with_invalid_socket_calls_stop(manager):
    """_send_ping with invalid socket must call stop() without sending ping."""
    mock_socket = MagicMock()
    mock_socket.isValid.return_value = False
    manager._socket = mock_socket
    manager._send_ping()
    mock_socket.ping.assert_not_called()
    manager._ping_timer.stop.assert_called()  # stop() was called


def test_send_ping_with_none_socket_calls_stop(manager):
    manager._socket = None
    manager._send_ping()
    manager._ping_timer.stop.assert_called()  # stop() was called


# ── _on_pong_received ─────────────────────────────────────────────────────────


def test_pong_received_cancels_timeout(manager):
    manager._on_pong_received(15, b"hb")
    manager._pong_timeout_timer.stop.assert_called()


# ── _on_pong_timeout ──────────────────────────────────────────────────────────


def test_pong_timeout_closes_socket_and_notifies_server(manager, mock_server):
    mock_socket = MagicMock()
    manager._socket = mock_socket
    manager._on_pong_timeout()
    mock_socket.close.assert_called_once_with(1001, "Pong timeout")
    mock_server.on_heartbeat_timeout.assert_called_once()


def test_pong_timeout_without_socket_does_not_raise(manager, mock_server):
    manager._socket = None
    manager._on_pong_timeout()  # should not raise
    mock_server.on_heartbeat_timeout.assert_called_once()
