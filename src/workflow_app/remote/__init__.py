"""
Remote control package — Workflow Mobile feature.

Exposes the PC-side WebSocket bridge that allows an Android app
to monitor and control pipeline execution over Tailscale.

Public surface:
  RemoteServer   — QWebSocketServer lifecycle manager
  SignalBridge   — bidirectional bridge (SignalBus ↔ WebSocket protocol)
  protocol       — formal enum definitions (MessageType, ControlAction, …)
  constants      — shared numeric constants
"""

from __future__ import annotations

from workflow_app.remote.constants import (
    ALLOWED_CONTROL_ACTIONS,
    ALLOWED_INBOUND_TYPES,
    BACKGROUND_DISCONNECT_MIN,
    BACKOFF_INITIAL_S,
    BACKOFF_MAX_S,
    DEDUP_SET_LIMIT,
    DEFAULT_PORT,
    MAX_BATCH_KB,
    MAX_BUFFER_LINES,
    MAX_PAYLOAD_BYTES,
    MAX_RETRY_ATTEMPTS,
    PING_INTERVAL_S,
    PORT_RANGE_SIZE,
    PORT_SCAN_RANGE,
    RATE_LIMIT_MSG_PER_S,
    SYNC_OUTPUT_LINES,
    TAILSCALE_ADDR_PREFIX,
    THROTTLE_ANDROID_MS,
    THROTTLE_PC_MS,
)
from workflow_app.remote.message_serializer import MessageSerializer
from workflow_app.remote.protocol import (
    ANDROID_ACCEPTED_TYPES,
    PC_ACCEPTED_TYPES,
    CommandStatus,
    ControlAction,
    MessageType,
    PipelineStatus,
    ResponseType,
    WsEnvelope,
    is_valid_client_message,
)
from workflow_app.remote.remote_server import RemoteServer
from workflow_app.remote.signal_bridge import SignalBridge
from workflow_app.remote.snapshot_builder import SnapshotBuilder

__all__ = [
    "RemoteServer",
    "SignalBridge",
    "SnapshotBuilder",
    "MessageSerializer",
    # protocol
    "MessageType",
    "ControlAction",
    "ResponseType",
    "CommandStatus",
    "PipelineStatus",
    "WsEnvelope",
    "PC_ACCEPTED_TYPES",
    "ANDROID_ACCEPTED_TYPES",
    "is_valid_client_message",
    # constants
    "THROTTLE_PC_MS",
    "THROTTLE_ANDROID_MS",
    "MAX_BATCH_KB",
    "MAX_BUFFER_LINES",
    "SYNC_OUTPUT_LINES",
    "PING_INTERVAL_S",
    "MAX_PAYLOAD_BYTES",
    "RATE_LIMIT_MSG_PER_S",
    "DEDUP_SET_LIMIT",
    "BACKOFF_INITIAL_S",
    "BACKOFF_MAX_S",
    "MAX_RETRY_ATTEMPTS",
    "BACKGROUND_DISCONNECT_MIN",
    "DEFAULT_PORT",
    "PORT_SCAN_RANGE",
    "PORT_RANGE_SIZE",
    "TAILSCALE_ADDR_PREFIX",
    "ALLOWED_INBOUND_TYPES",
    "ALLOWED_CONTROL_ACTIONS",
]
