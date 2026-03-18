"""
HeartbeatManager — sends RFC 6455 pings on a fixed interval.

Ping/pong cycle:
- _ping_timer fires every PING_INTERVAL_S → _send_ping()
- _send_ping() sends ping and starts _pong_timeout_timer (one-shot, 10s)
- pong received → _on_pong_received() cancels timeout timer
- No pong in 10s → _on_pong_timeout() closes socket, notifies server
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QTimer
from PySide6.QtWebSockets import QWebSocket

from workflow_app.remote.constants import PING_INTERVAL_S

logger = logging.getLogger(__name__)

PONG_TIMEOUT_MS = 10_000  # 10 seconds


class HeartbeatManager:
    """Manages ping/pong RFC 6455 to keep WebSocket connection alive.

    Usage::

        hb = HeartbeatManager(remote_server)
        hb.start(websocket)   # call after client connects
        hb.stop()             # call before/after client disconnects
    """

    def __init__(self, remote_server=None) -> None:
        self._server = remote_server
        self._socket: QWebSocket | None = None

        # Periodic ping timer (every PING_INTERVAL_S seconds)
        self._ping_timer = QTimer()
        self._ping_timer.setInterval(PING_INTERVAL_S * 1000)
        self._ping_timer.timeout.connect(self._send_ping)

        # One-shot pong timeout timer (10s after each ping)
        self._pong_timeout_timer = QTimer()
        self._pong_timeout_timer.setSingleShot(True)
        self._pong_timeout_timer.setInterval(PONG_TIMEOUT_MS)
        self._pong_timeout_timer.timeout.connect(self._on_pong_timeout)

    def start(self, websocket: QWebSocket) -> None:
        """Attach to *websocket* and begin pinging."""
        self._socket = websocket
        self._socket.pong.connect(self._on_pong_received)
        self._ping_timer.start()
        logger.debug("HeartbeatManager: started (interval=%ds)", PING_INTERVAL_S)

    def stop(self) -> None:
        """Stop timers, disconnect pong signal, and release websocket reference."""
        self._ping_timer.stop()
        self._pong_timeout_timer.stop()
        if self._socket is not None:
            try:
                self._socket.pong.disconnect(self._on_pong_received)
            except RuntimeError:
                pass  # socket already destroyed
        self._socket = None
        logger.debug("HeartbeatManager: stopped")

    # ── Private ──────────────────────────────────────────────────────────────

    def _send_ping(self) -> None:
        """Send ping and start the pong timeout timer."""
        if self._socket is None or not self._socket.isValid():
            self.stop()
            return
        self._socket.ping(b"hb")
        self._pong_timeout_timer.start()
        logger.debug("HeartbeatManager: ping sent")

    def _on_pong_received(self, elapsed_time: int, payload: bytes) -> None:
        """Cancel pong timeout — client is alive."""
        self._pong_timeout_timer.stop()
        logger.debug("HeartbeatManager: pong received (elapsed=%dms)", elapsed_time)

    def _on_pong_timeout(self) -> None:
        """No pong in PONG_TIMEOUT_MS — close socket and notify server."""
        logger.warning("HeartbeatManager: pong timeout, closing socket")
        if self._socket is not None:
            self._socket.close(1001, "Pong timeout")
        if self._server is not None:
            self._server.on_heartbeat_timeout()
