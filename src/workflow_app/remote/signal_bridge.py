"""
SignalBridge — bidirectional bridge between SignalBus/PipelineManager
and the Workflow Mobile WebSocket protocol.

Inbound (Android → PC):
  control              → PipelineManager.pause/resume/skip
  interaction_response → PipelineManager.send_interactive_response
  sync_request         → build_snapshot() → pipeline_state

Outbound (PC → Android):
  pipeline_state       → on status changes or sync_request
  output_chunk         → via OutputThrottle (batched 100 ms)
  output_truncated     → when buffer overflows
  interaction_request  → when interactive prompt or permission is needed
  command_status_changed → per-command status updates
  error                → validation errors

Idempotency:
  Each inbound message_id is tracked in _processed_ids.
  Duplicates are silently discarded.

First-response-wins:
  _pending_interaction tracks the active InteractionPayload.
  Once resolved, any additional interaction_response returns an error.
"""

from __future__ import annotations

import logging
import uuid
from collections import deque
from typing import TYPE_CHECKING

from workflow_app.remote.constants import (
    ALLOWED_CONTROL_ACTIONS,
    ALLOWED_INBOUND_TYPES,
    SYNC_OUTPUT_LINES,
)
from workflow_app.remote.dtos import InteractionPayload
from workflow_app.remote.message_serializer import MessageSerializer
from workflow_app.remote.output_throttle import OutputThrottle

if TYPE_CHECKING:
    from workflow_app.pipeline.pipeline_manager import PipelineManager
    from workflow_app.remote.remote_server import RemoteServer
    from workflow_app.signal_bus import SignalBus

logger = logging.getLogger(__name__)
audit_logger = logging.getLogger("workflow_app.remote.audit")

# Max message_id deduplication window
_MAX_PROCESSED_IDS = 1000


class SignalBridge:
    """Bidirectional bridge between SignalBus signals and the WebSocket protocol.

    Usage::

        bridge = SignalBridge(signal_bus=signal_bus, pipeline_manager=pm)
        server.attach_bridge(bridge)   # done automatically on client connect
    """

    def __init__(
        self,
        *,
        signal_bus: SignalBus,
        pipeline_manager: PipelineManager,
    ) -> None:
        self._signal_bus = signal_bus
        self._pipeline_mgr = pipeline_manager
        self._serializer = MessageSerializer()
        self._throttle = OutputThrottle()
        self._throttle.attach(self)

        self._server: RemoteServer | None = None
        self._pending_interaction: InteractionPayload | None = None
        self._processed_ids: deque[str] = deque(maxlen=_MAX_PROCESSED_IDS)

        # Output line buffer for snapshot (last SYNC_OUTPUT_LINES lines)
        self._output_lines: deque[str] = deque(maxlen=SYNC_OUTPUT_LINES)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def attach(self, server: RemoteServer) -> None:
        """Connect to SignalBus signals. Called when Android client connects."""
        self._server = server
        self._throttle.start()
        self._connect_signals()
        logger.debug("SignalBridge: attached")

    def detach(self) -> None:
        """Disconnect from SignalBus signals. Called on client disconnect."""
        self._throttle.stop()
        self._disconnect_signals()
        self._server = None
        self._pending_interaction = None
        logger.debug("SignalBridge: detached")

    # ── Inbound handling ──────────────────────────────────────────────────────

    def handle_incoming(self, raw: str) -> None:
        """Parse, validate and dispatch an inbound WebSocket message."""
        result = self._serializer.deserialize(raw)
        if result is None:
            self._send_error("INVALID_MESSAGE", "Malformed JSON")
            return

        message_id, msg_type, _timestamp, payload = result

        # Deduplication
        if message_id in self._processed_ids:
            logger.debug("SignalBridge: duplicate message_id=%s ignored", message_id)
            return
        self._processed_ids.append(message_id)

        # Whitelist check
        if msg_type not in ALLOWED_INBOUND_TYPES:
            logger.warning("SignalBridge: unknown message type=%s", msg_type)
            self._send_error(
                "UNKNOWN_MESSAGE_TYPE",
                f"Unknown type: {msg_type}",
                ref_message_id=message_id,
            )
            return

        # Dispatch
        if msg_type == "control":
            self._handle_control(payload, message_id)
        elif msg_type == "interaction_response":
            self._handle_interaction_response(payload, message_id)
        elif msg_type == "sync_request":
            self._handle_sync_request()

    # ── Snapshot ──────────────────────────────────────────────────────────────

    def build_snapshot(self) -> dict:
        """Build a PipelineSnapshot dict from current PipelineManager state."""
        pm = self._pipeline_mgr
        current_index = getattr(pm, "_current_index", 0)
        queue_raw: list = getattr(pm, "_queue", [])
        paused: bool = getattr(pm, "_paused", False)

        # Determine pipeline status
        if paused:
            pipeline_status_en = "PAUSED"
        elif current_index < len(queue_raw):
            pipeline_status_en = "RUNNING"
        else:
            pipeline_status_en = "NOT_STARTED"

        queue_items = []
        for i, cmd in enumerate(queue_raw):
            queue_items.append({
                "index": i,
                "label": cmd.name if hasattr(cmd, "name") else str(cmd),
                "status": "RUNNING" if i == current_index and not paused else "PENDING",
            })

        pending = None
        if self._pending_interaction is not None:
            pi = self._pending_interaction
            pending = {
                "request_id": pi.request_id,
                "interaction_type": pi.interaction_type,
                "prompt": pi.prompt,
                "status": pi.status,
                "metadata": pi.metadata,
            }

        return {
            "pipeline_status": pipeline_status_en,
            "current_index": current_index,
            "queue": queue_items,
            "output_buffer": "\n".join(self._output_lines),
            "pending_interaction": pending,
        }

    # ── Outbound convenience ──────────────────────────────────────────────────

    def _send_message(self, msg_type: str, payload: dict) -> None:
        if self._server is not None:
            text = self._serializer.serialize(msg_type, payload)
            self._server.send_text(text)

    def _send_error(
        self,
        code: str,
        message: str,
        ref_message_id: str | None = None,
    ) -> None:
        payload: dict = {"code": code, "message": message}
        if ref_message_id:
            payload["ref_message_id"] = ref_message_id
        self._send_message("error", payload)

    # ── Signal handlers (PC → Android) ───────────────────────────────────────

    def _on_pipeline_status_changed(self, pipeline_id: int, status_pt: str) -> None:
        snapshot = self.build_snapshot()
        # Override status with the actual emitted value
        snapshot["pipeline_status"] = self._serializer.translate_pipeline_status(status_pt)
        self._send_message("pipeline_state", snapshot)

    def _on_command_started(self, index: int) -> None:
        self._send_message(
            "command_status_changed",
            {"index": index, "status": "RUNNING"},
        )

    def _on_command_completed(self, index: int) -> None:
        self._send_message(
            "command_status_changed",
            {"index": index, "status": "COMPLETED"},
        )

    def _on_command_failed(self, index: int, error: str) -> None:
        self._send_message(
            "command_status_changed",
            {"index": index, "status": "ERROR", "error": error},
        )

    def _on_output_chunk(self, text: str) -> None:
        # Accumulate for snapshot
        for line in text.splitlines():
            self._output_lines.append(line)
        # Forward to throttle
        self._throttle.push(text)

    def _on_interactive_prompt(self, prompt: str) -> None:
        request_id = str(uuid.uuid4())
        self._pending_interaction = InteractionPayload(
            request_id=request_id,
            interaction_type="text_input",
            prompt=prompt,
            status="pending",
        )
        self._send_message(
            "interaction_request",
            {
                "request_id": request_id,
                "interaction_type": "text_input",
                "prompt": prompt,
                "status": "pending",
                "metadata": {},
            },
        )

    def _on_permission_request(self, data: dict) -> None:
        request_id = str(uuid.uuid4())
        prompt = data.get("prompt", "Approve?")
        self._pending_interaction = InteractionPayload(
            request_id=request_id,
            interaction_type="permission",
            prompt=prompt,
            status="pending",
            metadata=data,
        )
        self._send_message(
            "interaction_request",
            {
                "request_id": request_id,
                "interaction_type": "permission",
                "prompt": prompt,
                "status": "pending",
                "metadata": data,
            },
        )

    def _on_command_skipped(self, index: int) -> None:
        self._send_message(
            "command_status_changed",
            {"index": index, "status": "SKIPPED"},
        )

    def _on_pipeline_error(self, pipeline_id: int, message: str) -> None:
        self._send_message(
            "error",
            {"code": "PIPELINE_ERROR", "message": message},
        )

    def _on_interactive_mode_ended(self) -> None:
        if self._pending_interaction is not None:
            request_id = self._pending_interaction.request_id
            self._pending_interaction.status = "resolved_elsewhere"
            self._send_message(
                "interaction_request",
                {
                    "request_id": request_id,
                    "interaction_type": self._pending_interaction.interaction_type,
                    "prompt": self._pending_interaction.prompt,
                    "status": "resolved_elsewhere",
                    "metadata": self._pending_interaction.metadata,
                },
            )
            self._pending_interaction = None

    # ── Inbound handlers (Android → PC) ──────────────────────────────────────

    def _handle_control(self, payload: dict, message_id: str) -> None:
        action = payload.get("action", "")
        if action not in ALLOWED_CONTROL_ACTIONS:
            logger.warning("SignalBridge: invalid control action=%s", action)
            self._send_error(
                "INVALID_COMMAND",
                f"Invalid action: {action}",
                ref_message_id=message_id,
            )
            return

        logger.info(
            "SignalBridge: control action=%s received from mobile (msg=%s)",
            action,
            message_id,
        )
        audit_logger.info(
            "AUDIT control action='%s' msg_id='%s'",
            action,
            message_id,
        )
        pm = self._pipeline_mgr
        if action == "pause":
            pm.pause()
        elif action == "play":
            if getattr(pm, "_paused", False):
                pm.resume()
        elif action == "skip":
            pm.skip_current()

    def _handle_interaction_response(self, payload: dict, message_id: str) -> None:
        request_id = payload.get("request_id", "")
        value = payload.get("value", "")

        if self._pending_interaction is None:
            self._send_error(
                "INTERACTION_ALREADY_RESOLVED",
                "No pending interaction",
                ref_message_id=message_id,
            )
            return

        if self._pending_interaction.request_id != request_id:
            self._send_error(
                "INTERACTION_ALREADY_RESOLVED",
                "Interaction ID mismatch or already resolved",
                ref_message_id=message_id,
            )
            return

        if self._pending_interaction.status != "pending":
            self._send_error(
                "INTERACTION_ALREADY_RESOLVED",
                "Interaction already resolved",
                ref_message_id=message_id,
            )
            return

        interaction_type = self._pending_interaction.interaction_type
        self._pending_interaction.status = "resolved"

        accepted = self._pipeline_mgr.send_interactive_response(
            request_id=request_id,
            value=value,
            response_type=interaction_type,
        )

        if accepted:
            logger.info(
                "SignalBridge: interaction %s resolved via mobile (type=%s)",
                request_id,
                interaction_type,
            )
            # Audit log — intentionally omits 'value' to protect user input
            audit_logger.info(
                "AUDIT interaction_response resolved request_id='%s' type='%s'",
                request_id,
                interaction_type,
            )
            self._send_message(
                "interaction_request",
                {
                    "request_id": request_id,
                    "interaction_type": interaction_type,
                    "prompt": self._pending_interaction.prompt,
                    "status": "resolved",
                    "metadata": self._pending_interaction.metadata,
                },
            )
            self._pending_interaction = None
        else:
            self._send_error(
                "INTERACTION_ALREADY_RESOLVED",
                "Desktop resolved first",
                ref_message_id=message_id,
            )

    def _handle_sync_request(self) -> None:
        snapshot = self.build_snapshot()
        self._send_message("pipeline_state", snapshot)

    # ── Signal connect / disconnect ───────────────────────────────────────────

    def _connect_signals(self) -> None:
        bus = self._signal_bus
        bus.pipeline_status_changed.connect(self._on_pipeline_status_changed)
        bus.command_started.connect(self._on_command_started)
        bus.command_completed.connect(self._on_command_completed)
        bus.command_failed.connect(self._on_command_failed)
        bus.command_skipped.connect(self._on_command_skipped)
        bus.output_chunk_received.connect(self._on_output_chunk)
        bus.interactive_prompt_received.connect(self._on_interactive_prompt)
        bus.permission_request_received.connect(self._on_permission_request)
        bus.interactive_mode_ended.connect(self._on_interactive_mode_ended)
        bus.pipeline_error_occurred.connect(self._on_pipeline_error)

    def _disconnect_signals(self) -> None:
        bus = self._signal_bus
        try:
            bus.pipeline_status_changed.disconnect(self._on_pipeline_status_changed)
            bus.command_started.disconnect(self._on_command_started)
            bus.command_completed.disconnect(self._on_command_completed)
            bus.command_failed.disconnect(self._on_command_failed)
            bus.command_skipped.disconnect(self._on_command_skipped)
            bus.output_chunk_received.disconnect(self._on_output_chunk)
            bus.interactive_prompt_received.disconnect(self._on_interactive_prompt)
            bus.permission_request_received.disconnect(self._on_permission_request)
            bus.interactive_mode_ended.disconnect(self._on_interactive_mode_ended)
            bus.pipeline_error_occurred.disconnect(self._on_pipeline_error)
        except RuntimeError:
            # Qt objects may be partially destroyed during shutdown — ignore
            pass
