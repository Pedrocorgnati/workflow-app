"""
RemoteServer — QWebSocketServer lifecycle manager.

Responsibilities:
- Inherit QObject and expose state_changed Signal for UI binding.
- Bind QWebSocketServer to the Tailscale interface (100.x.x.x) via TailscaleDetector.
- Accept exactly one client connection (Android app).
- Reject second connections and non-Tailscale IPs with close code 1008 (Policy Violation).
- Enforce RemoteServerState transitions via _set_state() — all state changes emit state_changed.
- Apply inbound message pipeline: size check → rate limit → JSON parse → dedup → whitelist → dispatch.
- Delegate inbound messages to SignalBridge via handle_incoming(raw).
- Expose send_text() and send_message(WsEnvelope) for outbound messages.
- Expose address property with "ip:port" when active.

Requires PySide6-QtWebSockets (pip install PySide6-Addons or full PySide6).
"""

from __future__ import annotations

import collections
import enum
import json
import logging
import time

from PySide6.QtCore import QObject, QTimer, Signal, Slot
from PySide6.QtNetwork import QHostAddress
from PySide6.QtWebSockets import QWebSocket, QWebSocketProtocol, QWebSocketServer

from workflow_app.remote.constants import (
    DEDUP_SET_LIMIT,
    MAX_MESSAGE_BYTES,
    PORT_SCAN_RANGE,
    RATE_LIMIT_MSG_PER_S,
)
from workflow_app.remote.heartbeat_manager import HeartbeatManager
from workflow_app.remote.ip_validator import IPValidator
from workflow_app.remote.metrics import MetricsCollector
from workflow_app.remote.protocol import WsEnvelope, is_valid_client_message
from workflow_app.remote.tailscale import TailscaleDetector

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("workflow_app.remote.audit")


class RemoteServerState(enum.Enum):
    OFF = "off"
    STARTING = "starting"
    LISTENING = "listening"
    CONNECTED_CLIENT = "connected_client"


class _RateLimiter:
    """Fixed-window rate limiter — correct for single-client mode (no sliding window needed).

    Resets the counter once per second. Any message beyond the limit in the same
    1-second window is rejected.
    """

    def __init__(self, limit: int = RATE_LIMIT_MSG_PER_S) -> None:
        self._limit = limit
        self._count = 0
        self._window_start = time.monotonic()

    def check(self) -> bool:
        """Return True if the message is within the rate limit; False if exceeded."""
        now = time.monotonic()
        if now - self._window_start >= 1.0:
            self._count = 0
            self._window_start = now
        if self._count >= self._limit:
            return False
        self._count += 1
        return True


class RemoteServer(QObject):
    """Manages a single-client QWebSocketServer for remote pipeline control.

    Usage::

        server = RemoteServer(signal_bus)
        ok = server.start()   # binds to Tailscale interface, auto-selects port
        server.stop()
    """

    state_changed = Signal(str)  # emits RemoteServerState.value on every transition

    def __init__(self, signal_bus, parent=None) -> None:
        super().__init__(parent)
        self._signal_bus = signal_bus
        self._server: QWebSocketServer | None = None
        self._client: QWebSocket | None = None
        self._heartbeat = HeartbeatManager(self)
        self._bridge = None  # set by attach_bridge()
        self._state = RemoteServerState.OFF
        self._address: str = ""

        # Rate limiting — fixed 1s window, reset per message
        self._rate_limiter = _RateLimiter()

        # Deduplication — FIFO OrderedDict bounded to DEDUP_SET_LIMIT entries
        self._seen_ids: collections.OrderedDict[str, None] = collections.OrderedDict()

        # Metrics
        self._metrics = MetricsCollector.instance()
        self._last_error_time: float | None = None  # monotonic timestamp of last error

        # Periodic metrics logging — 5 min interval, started in start()
        self._metrics_timer = QTimer(self)
        self._metrics_timer.setInterval(5 * 60 * 1000)  # 5 minutes in ms
        self._metrics_timer.timeout.connect(self._log_metrics)

        # Wire signal bus toggle to start()/stop()
        signal_bus.remote_mode_toggle_requested.connect(self._on_mode_toggle)

    # ── Public API ────────────────────────────────────────────────────────────

    def start(self) -> bool:
        """Detect Tailscale IP, create server, bind with port fallback.

        Returns True on success, False if Tailscale is not active or no port
        was available.
        """
        self._set_state(RemoteServerState.STARTING)
        self._metrics.reset()
        self._last_error_time = None

        result = TailscaleDetector().detect()
        if not result.success:
            logger.error("RemoteServer: %s", result.error)
            self._signal_bus.toast_requested.emit(
                "Tailscale não detectado. Instale e ative o Tailscale para usar o Modo Remoto.",
                "error",
            )
            self._set_state(RemoteServerState.OFF)
            self._signal_bus.remote_server_stopped.emit()
            return False

        self._server = QWebSocketServer(
            "WorkflowRemote",
            QWebSocketServer.SslMode.NonSecureMode,
            self,
        )
        self._server.newConnection.connect(self._on_new_connection)

        host_addr = QHostAddress(result.ip)
        for port in PORT_SCAN_RANGE:
            if self._server.listen(host_addr, port):
                addr = f"{result.ip}:{port}"
                self._address = addr
                self._set_state(RemoteServerState.LISTENING)
                logger.info("RemoteServer: listening at %s", addr)
                self._metrics_timer.start()
                self._signal_bus.remote_server_started.emit(addr)
                self._signal_bus.toast_requested.emit(
                    f"Servidor remoto ativo em {addr}",
                    "success",
                )
                return True
            logger.debug("RemoteServer: port %d busy, trying next", port)
            self._signal_bus.toast_requested.emit(
                f"Porta {port} em uso. Tentando próxima...",
                "info",
            )

        logger.error(
            "RemoteServer: all ports %d-%d are busy",
            PORT_SCAN_RANGE.start,
            PORT_SCAN_RANGE.stop - 1,
        )
        self._signal_bus.toast_requested.emit(
            f"Portas {PORT_SCAN_RANGE.start}-{PORT_SCAN_RANGE.stop - 1} ocupadas. Tente mais tarde.",
            "error",
        )
        self._server.deleteLater()
        self._server = None
        self._address = ""
        self._set_state(RemoteServerState.OFF)
        self._signal_bus.remote_server_stopped.emit()
        return False

    def stop(self) -> None:
        """Disconnect client, detach bridge, close server."""
        self._metrics_timer.stop()
        self._heartbeat.stop()

        if self._client is not None:
            try:
                self._client.disconnected.disconnect(self._on_disconnected)
            except RuntimeError:
                pass  # already disconnected
            self._client.close()
            self._client.deleteLater()
            self._client = None

        if self._bridge is not None:
            self._bridge.detach()

        if self._server is not None:
            self._server.close()
            self._server.deleteLater()
            self._server = None

        self._address = ""
        self._set_state(RemoteServerState.OFF)
        self._signal_bus.remote_server_stopped.emit()
        logger.info("RemoteServer: stopped")

    def is_running(self) -> bool:
        """True if server is in LISTENING or CONNECTED_CLIENT state."""
        return self._state in (
            RemoteServerState.LISTENING,
            RemoteServerState.CONNECTED_CLIENT,
        )

    def is_healthy(self) -> bool:
        """True if server is running and no error has occurred in the last 60 seconds."""
        if not self.is_running():
            return False
        if self._last_error_time is None:
            return True
        return (time.monotonic() - self._last_error_time) > 60.0

    def has_client(self) -> bool:
        """True if an Android device is currently connected."""
        return self._state == RemoteServerState.CONNECTED_CLIENT

    def send_text(self, text: str) -> None:
        """Send a raw text frame to the connected client, if any."""
        if self._client is not None and self._client.isValid():
            self._client.sendTextMessage(text)
            self._metrics.record_message_sent(len(text.encode("utf-8")))

    def attach_bridge(self, bridge) -> None:
        """Register the SignalBridge that handles inbound messages."""
        self._bridge = bridge

    @property
    def state(self) -> RemoteServerState:
        return self._state

    @property
    def address(self) -> str:
        """Return 'ip:port' when LISTENING or CONNECTED_CLIENT, '' otherwise."""
        return self._address

    def send_message(self, envelope: WsEnvelope) -> None:
        """Serialize a WsEnvelope to JSON and send to the connected client."""
        self.send_text(json.dumps(envelope.to_dict()))

    def on_heartbeat_timeout(self) -> None:
        """Called by HeartbeatManager when pong is not received within PONG_TIMEOUT_MS.

        The socket close triggered by HeartbeatManager will fire the disconnected
        signal, which _on_disconnected() handles. This method provides a hook for
        logging and future extension.
        """
        self._last_error_time = time.monotonic()
        logger.warning("RemoteServer: heartbeat timeout — disconnect will follow")

    @Slot()
    def _log_metrics(self) -> None:
        """Periodic metrics snapshot logged at INFO level. Fired every 5 minutes."""
        m = self._metrics.snapshot()
        logger.info(
            "RemoteServer metrics — connections=%d rx=%d msgs / %d B "
            "tx=%d msgs / %d B rate_drops=%d dedup_drops=%d "
            "avg_latency=%.1f ms uptime=%.0f s healthy=%s",
            m.connections_total,
            m.messages_received,
            m.bytes_received,
            m.messages_sent,
            m.bytes_sent,
            m.rate_limit_drops,
            m.dedup_drops,
            m.avg_latency_ms,
            m.uptime_s,
            self.is_healthy(),
        )

    # ── Qt slots ──────────────────────────────────────────────────────────────

    @Slot(bool)
    def _on_mode_toggle(self, enabled: bool) -> None:
        if enabled:
            self.start()
        else:
            self.stop()

    @Slot()
    def _on_new_connection(self) -> None:
        if self._server is None:
            return

        incoming = self._server.nextPendingConnection()
        if incoming is None:
            return

        peer_ip = incoming.peerAddress().toString()

        # Validate IP against Tailscale CGNAT range 100.64.0.0/10
        if not IPValidator().validate(peer_ip):
            logger.warning(
                "RemoteServer: connection from non-Tailscale IP %s rejected", peer_ip
            )
            incoming.close(
                QWebSocketProtocol.CloseCode.CloseCodePolicyViolated,
                "IP não autorizado: apenas conexões Tailscale são aceitas",
            )
            incoming.deleteLater()
            return

        # Single-client mode — reject second connection with close code 1008
        if self._client is not None and self._client.isValid():
            logger.warning(
                "RemoteServer: second connection attempt from %s rejected", peer_ip
            )
            incoming.close(
                QWebSocketProtocol.CloseCode.CloseCodePolicyViolated,
                "Single client mode: já existe uma conexão ativa",
            )
            incoming.deleteLater()
            return

        self._client = incoming
        self._client.textMessageReceived.connect(self._on_message_received)
        self._client.disconnected.connect(self._on_disconnected)
        self._set_state(RemoteServerState.CONNECTED_CLIENT)

        self._heartbeat.start(self._client)
        if self._bridge is not None:
            self._bridge.attach(self)

        self._metrics.record_connection()
        self._signal_bus.remote_client_connected.emit()
        logger.info("RemoteServer: client connected from %s", peer_ip)

    @Slot()
    def _on_disconnected(self) -> None:
        logger.info("RemoteServer: client disconnected")
        self._heartbeat.stop()

        if self._bridge is not None:
            self._bridge.detach()

        if self._client is not None:
            self._client.deleteLater()
            self._client = None

        self._set_state(RemoteServerState.LISTENING)
        self._signal_bus.remote_client_disconnected.emit()

    @Slot(str)
    def _on_message_received(self, raw: str) -> None:
        """Inbound message pipeline: size → rate limit → JSON → dedup → whitelist → dispatch."""
        # Step 0: Size check (64 KB limit) — before any processing
        raw_bytes = raw.encode("utf-8")
        self._metrics.record_message_received(len(raw_bytes))
        if len(raw_bytes) > MAX_MESSAGE_BYTES:
            logger.warning(
                "RemoteServer: mensagem descartada (%d bytes, limite: %d)",
                len(raw_bytes),
                MAX_MESSAGE_BYTES,
            )
            return

        # Step 1: Rate limiting
        if not self._check_rate_limit():
            return

        # Step 2: JSON parse
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("RemoteServer: mensagem JSON inválida descartada")
            return

        # Step 3: Deduplication
        message_id = data.get("message_id", "")
        if message_id and not self._check_dedup(message_id):
            return  # duplicate — discard silently

        # Step 4: Whitelist (deny-by-default)
        msg_type = data.get("type", "")
        if not is_valid_client_message(msg_type):
            logger.warning(
                "RemoteServer: tipo de mensagem '%s' rejeitado (não está na whitelist)",
                msg_type,
            )
            return

        # Step 5: Dispatch to bridge (pass original raw string — bridge re-parses)
        logger.debug("RemoteServer: mensagem recebida type='%s' id='%s'", msg_type, message_id)
        self._dispatch(raw)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _set_state(self, new_state: RemoteServerState) -> None:
        """Update internal state and emit state_changed signal."""
        self._state = new_state
        self.state_changed.emit(new_state.value)

    def _check_rate_limit(self) -> bool:
        """Return False and log warning if rate limit is exceeded."""
        if not self._rate_limiter.check():
            logger.warning(
                "RemoteServer: rate limit atingido (%d msg/s) — mensagem descartada",
                RATE_LIMIT_MSG_PER_S,
            )
            self._metrics.record_rate_limit_drop()
            self._last_error_time = time.monotonic()
            return False
        return True

    def _check_dedup(self, message_id: str) -> bool:
        """Return True if message_id is new; False if already seen.

        Uses FIFO eviction (popitem(last=False)) when DEDUP_SET_LIMIT is reached,
        so the oldest entry is removed to make room for the new one.
        """
        if message_id in self._seen_ids:
            self._metrics.record_dedup_drop()
            return False  # duplicate — discard silently
        if len(self._seen_ids) >= DEDUP_SET_LIMIT:
            self._seen_ids.popitem(last=False)  # remove oldest (FIFO)
        self._seen_ids[message_id] = None
        return True

    def _dispatch(self, raw: str) -> None:
        """Forward a validated raw message to the SignalBridge."""
        if self._bridge is not None:
            self._bridge.handle_incoming(raw)
