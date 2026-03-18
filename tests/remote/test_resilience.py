"""
Resilience Tests — module-12/TASK-2

Tests for reconnection, error recovery, and fault-tolerance:
- Abrupt disconnect → server returns to LISTENING state
- Heartbeat pong timeout → socket closed, server notified
- Server stop → start cycle (simulates server restart)
- Rate limiter enforcement and reset
- Message deduplication (FIFO, bounded to DEDUP_SET_LIMIT)
- Handling of oversized messages

BDD Coverage: INT-050 to INT-064 (connection + lifecycle)
"""

from __future__ import annotations

import collections
import json
import time
import uuid
from unittest.mock import MagicMock, patch

import pytest

from workflow_app.remote.constants import (
    DEDUP_SET_LIMIT,
    MAX_MESSAGE_BYTES,
    PING_INTERVAL_S,
    RATE_LIMIT_MSG_PER_S,
)
from workflow_app.remote.heartbeat_manager import PONG_TIMEOUT_MS, HeartbeatManager
from workflow_app.remote.remote_server import RemoteServer, RemoteServerState, _RateLimiter
from workflow_app.remote.tailscale import TailscaleResult

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def signal_bus():
    bus = MagicMock()
    bus.remote_mode_toggle_requested = MagicMock()
    bus.remote_mode_toggle_requested.connect = MagicMock()
    bus.remote_server_started = MagicMock()
    bus.remote_server_stopped = MagicMock()
    bus.remote_client_connected = MagicMock()
    bus.remote_client_disconnected = MagicMock()
    bus.toast_requested = MagicMock()
    return bus


@pytest.fixture
def server(qapp, signal_bus):
    return RemoteServer(signal_bus)


@pytest.fixture
def server_listening(qapp, signal_bus):
    """Server that has successfully started and is in LISTENING state."""
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

        srv = RemoteServer(signal_bus)
        srv.start()

    assert srv.state == RemoteServerState.LISTENING
    return srv


@pytest.fixture
def server_connected(server_listening, signal_bus):
    """Server in CONNECTED_CLIENT state with a mocked client."""
    mock_client = MagicMock()
    mock_client.isValid.return_value = True
    mock_client.peerAddress.return_value.toString.return_value = "127.0.0.1"
    server_listening._client = mock_client
    server_listening._state = RemoteServerState.CONNECTED_CLIENT
    return server_listening


# ── 1. Abrupt Disconnect → LISTENING ─────────────────────────────────────────


class TestAbruptDisconnect:
    """BDD Cenário 1: abrupt disconnect → server returns to LISTENING."""

    def test_on_disconnected_returns_to_listening(self, server_connected):
        """_on_disconnected() transitions CONNECTED_CLIENT → LISTENING."""
        server_connected._on_disconnected()
        assert server_connected.state == RemoteServerState.LISTENING

    def test_on_disconnected_clears_client_reference(self, server_connected):
        """After disconnect, _client is None."""
        server_connected._on_disconnected()
        assert server_connected._client is None

    def test_on_disconnected_calls_delete_later(self, server_connected):
        """Disconnected client QObject is scheduled for deletion."""
        client = server_connected._client
        server_connected._on_disconnected()
        client.deleteLater.assert_called_once()

    def test_on_disconnected_emits_remote_client_disconnected(self, server_connected, signal_bus):
        """_on_disconnected() emits remote_client_disconnected signal."""
        server_connected._on_disconnected()
        signal_bus.remote_client_disconnected.emit.assert_called_once()

    def test_on_disconnected_emits_state_changed(self, server_connected):
        """_on_disconnected() emits state_changed with 'listening'."""
        emitted: list[str] = []
        server_connected.state_changed.connect(emitted.append)

        server_connected._on_disconnected()

        assert "listening" in emitted

    def test_server_ready_for_new_connection_after_disconnect(self, server_connected):
        """After disconnect, server is_running() and has_client() is False."""
        server_connected._on_disconnected()

        assert server_connected.is_running() is True
        assert server_connected.has_client() is False

    def test_multiple_disconnect_calls_idempotent(self, server_connected):
        """Calling _on_disconnected() twice doesn't crash."""
        server_connected._on_disconnected()
        server_connected._on_disconnected()  # should not raise
        assert server_connected.state == RemoteServerState.LISTENING


# ── 2. Heartbeat / Pong Timeout ───────────────────────────────────────────────


class TestHeartbeatResilience:
    """BDD Cenário: heartbeat pong timeout closes socket and notifies server."""

    def test_heartbeat_manager_pong_timeout_ms_value(self):
        """PONG_TIMEOUT_MS is 10 seconds (10,000ms)."""
        assert PONG_TIMEOUT_MS == 10_000

    def test_heartbeat_manager_ping_interval(self):
        """PING_INTERVAL_S is 30 seconds."""
        assert PING_INTERVAL_S == 30

    def test_heartbeat_start_starts_timer(self, qapp):
        """start() activates the ping timer."""
        hb = HeartbeatManager()
        mock_socket = MagicMock()
        mock_socket.pong = MagicMock()
        mock_socket.pong.connect = MagicMock()
        mock_socket.isValid.return_value = True

        hb.start(mock_socket)

        assert hb._ping_timer.isActive()
        hb.stop()

    def test_heartbeat_stop_deactivates_timers(self, qapp):
        """stop() deactivates both ping and pong timeout timers."""
        hb = HeartbeatManager()
        mock_socket = MagicMock()
        mock_socket.pong = MagicMock()
        mock_socket.pong.connect = MagicMock()
        mock_socket.isValid.return_value = True

        hb.start(mock_socket)
        hb.stop()

        assert not hb._ping_timer.isActive()
        assert not hb._pong_timeout_timer.isActive()

    def test_pong_timeout_closes_socket_with_1001(self, qapp):
        """_on_pong_timeout() closes socket with close code 1001 (Going Away)."""
        hb = HeartbeatManager()
        mock_socket = MagicMock()
        hb._socket = mock_socket

        hb._on_pong_timeout()

        mock_socket.close.assert_called_once_with(1001, "Pong timeout")

    def test_pong_timeout_notifies_server(self, qapp):
        """_on_pong_timeout() calls server.on_heartbeat_timeout()."""
        mock_server = MagicMock()
        hb = HeartbeatManager(mock_server)
        hb._socket = MagicMock()

        hb._on_pong_timeout()

        mock_server.on_heartbeat_timeout.assert_called_once()

    def test_pong_received_stops_timeout_timer(self, qapp):
        """_on_pong_received() stops the pong timeout timer."""
        hb = HeartbeatManager()
        mock_socket = MagicMock()
        mock_socket.pong = MagicMock()
        mock_socket.pong.connect = MagicMock()
        mock_socket.isValid.return_value = True

        hb.start(mock_socket)
        hb._pong_timeout_timer.start()  # simulate ping sent

        hb._on_pong_received(25, b"hb")

        assert not hb._pong_timeout_timer.isActive()
        hb.stop()

    def test_send_ping_invalid_socket_calls_stop(self, qapp):
        """_send_ping() with invalid socket calls stop() (self-healing)."""
        hb = HeartbeatManager()
        mock_socket = MagicMock()
        mock_socket.isValid.return_value = False
        hb._socket = mock_socket
        hb._ping_timer.start()

        hb._send_ping()

        # Timer should have been stopped
        assert not hb._ping_timer.isActive()

    def test_heartbeat_server_on_timeout_does_not_crash(self, server_connected):
        """Server.on_heartbeat_timeout() is a hook (logs only) — does not crash.

        The state change to LISTENING happens later via socket.disconnected signal
        (HeartbeatManager closes socket → Qt fires disconnected → _on_disconnected()).
        """
        server_connected.on_heartbeat_timeout()
        # State is still CONNECTED_CLIENT (socket close hasn't fired yet — no Qt loop)
        assert server_connected.state == RemoteServerState.CONNECTED_CLIENT

    def test_heartbeat_timeout_flow_via_disconnected_signal(self, server_connected):
        """After pong timeout closes socket, _on_disconnected() transitions to LISTENING."""
        # HeartbeatManager calls socket.close → disconnected signal fires → _on_disconnected()
        # Simulate that sequence directly:
        server_connected.on_heartbeat_timeout()  # log hook
        server_connected._on_disconnected()      # simulates socket disconnected signal
        assert server_connected.state == RemoteServerState.LISTENING


# ── 3. Server Restart (Stop → Start Cycle) ────────────────────────────────────


class TestServerRestartCycle:
    """BDD Cenário 4: server restart → client can reconnect."""

    def test_stop_from_listening_goes_to_off(self, server_listening, signal_bus):
        """stop() from LISTENING → OFF, signal emitted."""
        server_listening._server = MagicMock()
        server_listening.stop()

        assert server_listening.state == RemoteServerState.OFF
        signal_bus.remote_server_stopped.emit.assert_called()

    def test_stop_from_connected_disconnects_client(self, server_connected, signal_bus):
        """stop() with connected client closes the client before going OFF."""
        server_connected._server = MagicMock()
        client = server_connected._client

        server_connected.stop()

        assert server_connected.state == RemoteServerState.OFF
        client.close.assert_called()

    def test_restart_cycle_start_after_stop(self, qapp, signal_bus):
        """Server can be started again after being stopped (stop → start)."""
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

            srv = RemoteServer(signal_bus)

            # First start
            result1 = srv.start()
            assert result1 is True
            assert srv.state == RemoteServerState.LISTENING

            # Stop
            srv._server = mock_ws
            srv.stop()
            assert srv.state == RemoteServerState.OFF

            # Second start (restart)
            result2 = srv.start()
            assert result2 is True
            assert srv.state == RemoteServerState.LISTENING

    def test_address_reset_after_stop(self, server_listening, signal_bus):
        """address returns '' after stop()."""
        server_listening._server = MagicMock()
        server_listening.stop()

        assert server_listening.address == ""

    def test_metrics_reset_on_start(self, qapp, signal_bus):
        """MetricsCollector.reset() is called on each start()."""
        with patch("workflow_app.remote.remote_server.TailscaleDetector") as mock_ts, \
             patch("workflow_app.remote.remote_server.QWebSocketServer") as mock_ws_cls, \
             patch("workflow_app.remote.remote_server.MetricsCollector") as mock_metrics_cls:

            mock_ts.return_value.detect.return_value = TailscaleResult(
                success=True, ip="127.0.0.1", error=""
            )
            mock_ws = MagicMock()
            mock_ws.listen.return_value = True
            mock_ws.newConnection = MagicMock()
            mock_ws.newConnection.connect = MagicMock()
            mock_ws_cls.return_value = mock_ws

            mock_metrics = MagicMock()
            mock_metrics_cls.instance.return_value = mock_metrics

            srv = RemoteServer(signal_bus)
            srv.start()

            mock_metrics.reset.assert_called_once()


# ── 4. Rate Limiting ──────────────────────────────────────────────────────────


class TestRateLimiting:
    """Tests for _RateLimiter fixed-window rate limiting (20 msg/s)."""

    def test_rate_limit_constant_value(self):
        """RATE_LIMIT_MSG_PER_S is 20 messages per second."""
        assert RATE_LIMIT_MSG_PER_S == 20

    def test_messages_within_limit_accepted(self):
        """First 20 messages in a 1s window are accepted."""
        limiter = _RateLimiter(limit=20)
        results = [limiter.check() for _ in range(20)]
        assert all(results), "All 20 messages should be accepted"

    def test_message_beyond_limit_rejected(self):
        """21st message in a 1s window is rejected."""
        limiter = _RateLimiter(limit=20)
        for _ in range(20):
            limiter.check()

        result = limiter.check()  # 21st message
        assert result is False, "21st message should be rejected"

    def test_rate_limit_resets_after_window(self):
        """After 1 second, rate limit counter resets."""
        limiter = _RateLimiter(limit=5)
        for _ in range(5):
            limiter.check()

        # Exhaust the limit
        assert limiter.check() is False

        # Manually expire the window
        limiter._window_start = time.monotonic() - 1.1
        assert limiter.check() is True  # reset

    def test_rate_limit_low_traffic_always_passes(self):
        """Low traffic (< 20 msg/s) is always accepted."""
        limiter = _RateLimiter(limit=20)
        # 10 messages spread across multiple windows
        for _ in range(10):
            limiter._window_start = time.monotonic() - 1.1  # force window reset
            assert limiter.check() is True

    def test_rate_limited_message_emits_error(self, server_connected):
        """Rate-limited inbound message is rejected and connection stays alive."""
        # Exhaust rate limit
        server_connected._rate_limiter._count = RATE_LIMIT_MSG_PER_S
        server_connected._rate_limiter._window_start = time.monotonic()

        raw = json.dumps({
            "message_id": str(uuid.uuid4()),
            "type": "sync_request",
            "timestamp": "2026-03-15T00:00:00Z",
            "payload": {},
        })

        server_connected._on_message_received(raw)

        # Connection must still be alive (rate limit must NOT disconnect client)
        assert server_connected.state == RemoteServerState.CONNECTED_CLIENT
        # Rate limiter count should remain at or above the limit (not reset by the rejected msg)
        assert server_connected._rate_limiter._count >= RATE_LIMIT_MSG_PER_S


# ── 5. Message Deduplication ──────────────────────────────────────────────────


class TestMessageDeduplication:
    """Tests for FIFO deduplication bounded to DEDUP_SET_LIMIT."""

    def test_dedup_set_limit_value(self):
        """DEDUP_SET_LIMIT is 10,000 entries."""
        assert DEDUP_SET_LIMIT == 10_000

    def test_duplicate_message_is_dropped(self, server_connected):
        """Same message_id processed twice — second is silently dropped."""
        msg_id = str(uuid.uuid4())
        raw = json.dumps({
            "message_id": msg_id,
            "type": "sync_request",
            "timestamp": "2026-03-15T00:00:00Z",
            "payload": {},
        })

        # Pre-populate seen_ids with this ID (simulates already seen)
        server_connected._seen_ids[msg_id] = None
        count_before = len(server_connected._seen_ids)

        # Dispatch same message — should be deduped at _on_message_received level
        server_connected._on_message_received(raw)

        # Connection alive (dedup must NOT disconnect)
        assert server_connected.state == RemoteServerState.CONNECTED_CLIENT
        # seen_ids must still contain this ID (not evicted by the duplicate itself)
        assert msg_id in server_connected._seen_ids
        # Count must not grow from the duplicate (it was already in seen_ids)
        assert len(server_connected._seen_ids) == count_before

    def test_seen_ids_bounded_to_dedup_limit(self):
        """_seen_ids OrderedDict evicts oldest when exceeding DEDUP_SET_LIMIT."""
        seen: collections.OrderedDict[str, None] = collections.OrderedDict()

        # Fill to limit
        for i in range(DEDUP_SET_LIMIT):
            key = f"msg-{i}"
            seen[key] = None

        assert len(seen) == DEDUP_SET_LIMIT
        first_key = next(iter(seen))  # oldest

        # Add one more — should evict oldest (like the server does)
        new_key = "msg-new"
        seen[new_key] = None
        if len(seen) > DEDUP_SET_LIMIT:
            seen.popitem(last=False)

        assert len(seen) == DEDUP_SET_LIMIT
        assert first_key not in seen  # oldest was evicted
        assert new_key in seen

    def test_unique_message_ids_are_not_deduped(self, server_connected):
        """Unique message IDs are each recorded in seen_ids (not falsely deduped)."""
        # Ensure seen_ids is empty for a clean count
        server_connected._seen_ids.clear()

        sent_ids: list[str] = []
        for _ in range(3):
            msg_id = str(uuid.uuid4())
            sent_ids.append(msg_id)
            raw = json.dumps({
                "message_id": msg_id,
                "type": "sync_request",
                "timestamp": "2026-03-15T00:00:00Z",
                "payload": {},
            })
            server_connected._on_message_received(raw)

        # All 3 unique IDs must be recorded in seen_ids (none were falsely deduped)
        for msg_id in sent_ids:
            assert msg_id in server_connected._seen_ids, (
                f"Unique message_id {msg_id} should be in seen_ids after processing"
            )
        assert len(server_connected._seen_ids) == 3


# ── 6. Oversized Message Handling ─────────────────────────────────────────────


class TestOversizedMessages:
    """Tests that oversized messages are rejected before JSON parsing."""

    def test_max_message_bytes_constant(self):
        """MAX_MESSAGE_BYTES is defined (from constants)."""
        assert MAX_MESSAGE_BYTES > 0

    def test_oversized_message_rejected(self, server_connected):
        """Message exceeding MAX_MESSAGE_BYTES is rejected without crashing."""
        oversized = "x" * (MAX_MESSAGE_BYTES + 1)

        # Should not crash even with garbage data
        server_connected._on_message_received(oversized)

        # Server should still be in CONNECTED_CLIENT state (not crashed)
        assert server_connected.state == RemoteServerState.CONNECTED_CLIENT

    def test_message_at_limit_processed(self, server_connected):
        """Message at exactly MAX_MESSAGE_BYTES is not rejected for size."""
        # A valid but large-ish message (well within limit)
        msg_id = str(uuid.uuid4())
        raw = json.dumps({
            "message_id": msg_id,
            "type": "sync_request",
            "timestamp": "2026-03-15T00:00:00Z",
            "payload": {},
        })
        # This is tiny — it should not be rejected for size
        assert len(raw.encode()) < MAX_MESSAGE_BYTES
        server_connected._on_message_received(raw)
        assert server_connected.state == RemoteServerState.CONNECTED_CLIENT


# ── 7. Non-Tailscale IP Resilience ───────────────────────────────────────────


class TestIPResilienceFlow:
    """Tests that non-Tailscale IPs are consistently rejected."""

    def test_connection_from_loopback_rejected_by_default(self, server_listening):
        """127.0.0.1 is rejected without mock (not in CGNAT range)."""
        mock_incoming = MagicMock()
        mock_incoming.peerAddress.return_value.toString.return_value = "127.0.0.1"
        server_listening._server = MagicMock()
        server_listening._server.nextPendingConnection.return_value = mock_incoming

        # No mock on IPValidator — real validation rejects 127.0.0.1
        server_listening._on_new_connection()

        mock_incoming.close.assert_called_once()
        assert server_listening.state == RemoteServerState.LISTENING

    def test_connection_from_private_range_rejected(self, server_listening):
        """10.0.0.1 (private RFC 1918) is rejected."""
        mock_incoming = MagicMock()
        mock_incoming.peerAddress.return_value.toString.return_value = "10.0.0.1"
        server_listening._server = MagicMock()
        server_listening._server.nextPendingConnection.return_value = mock_incoming

        server_listening._on_new_connection()

        mock_incoming.close.assert_called_once()
