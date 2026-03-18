"""
SnapshotBuilder — accumulates pipeline state for sync_request responses.

Maintains a circular buffer of the last SYNC_OUTPUT_LINES output lines
and explicit pipeline state, enabling idempotent snapshot generation.

Responsibilities:
- Keep a deque(maxlen=SYNC_OUTPUT_LINES) output buffer.
- Track current pipeline_status, command_queue, and pending_interaction.
- Produce a WsEnvelope(type=pipeline_state) snapshot on demand.

Usage::

    builder = SnapshotBuilder()
    builder.add_output_line("some text")
    builder.update_pipeline_status("running")
    builder.update_command_queue([{"index": 0, "label": "/prd-create", "status": "RUNNING"}])
    envelope = builder.build_snapshot()   # WsEnvelope(type="pipeline_state", payload={...})
"""

from __future__ import annotations

import logging
from collections import deque

from workflow_app.remote.constants import SYNC_OUTPUT_LINES
from workflow_app.remote.protocol import MessageType, WsEnvelope

logger = logging.getLogger(__name__)


class SnapshotBuilder:
    """Builds idempotent pipeline state snapshots for sync_request responses.

    State is updated via explicit setter methods called by SignalBridge.
    The output buffer is a circular deque capped at SYNC_OUTPUT_LINES (500).

    Multiple calls to build_snapshot() with unchanged state produce payloads
    with equal content (message_id and timestamp differ by design — they are
    generated fresh in each WsEnvelope).
    """

    def __init__(self) -> None:
        # Circular buffer of the last SYNC_OUTPUT_LINES lines for reconnection sync
        self._output_buffer: deque[str] = deque(maxlen=SYNC_OUTPUT_LINES)
        # Pipeline state tracking
        self._pipeline_status: str = "idle"
        self._command_queue: list[dict] = []
        self._pending_interaction: dict | None = None

    # ── State update API (called by SignalBridge) ─────────────────────────────

    def add_output_line(self, text: str) -> None:
        """Append a line to the circular buffer.

        When the buffer is full (SYNC_OUTPUT_LINES entries), the oldest line
        is automatically evicted by deque(maxlen=...).
        """
        self._output_buffer.append(text)

    def update_pipeline_status(self, status: str) -> None:
        """Update the current pipeline status string (EN value)."""
        self._pipeline_status = status

    def update_command_queue(self, queue: list[dict]) -> None:
        """Replace the tracked command queue."""
        self._command_queue = queue

    def set_pending_interaction(self, interaction: dict | None) -> None:
        """Set or clear the pending interaction.

        Pass None to indicate no active interaction.
        """
        self._pending_interaction = interaction

    # ── Snapshot generation ───────────────────────────────────────────────────

    def build_snapshot(self) -> WsEnvelope:
        """Build an idempotent WsEnvelope snapshot of current pipeline state.

        Returns a WsEnvelope(type=pipeline_state) with payload:
            pipeline_status   — current status string
            command_queue     — copy of the command queue list
            output_history    — copy of the circular output buffer
            pending_interaction — current pending interaction or None

        Copies are returned to prevent mutation of internal state.
        This method does not modify any internal attribute (pure/idempotent).
        """
        payload = {
            "pipeline_status": self._pipeline_status,
            "command_queue": list(self._command_queue),
            "output_history": list(self._output_buffer),
            "pending_interaction": self._pending_interaction,
        }
        envelope = WsEnvelope(
            type=MessageType.PIPELINE_STATE.value,
            payload=payload,
        )
        logger.debug(
            "SnapshotBuilder: snapshot built — status=%s, output_lines=%d, pending=%s",
            self._pipeline_status,
            len(self._output_buffer),
            self._pending_interaction is not None,
        )
        return envelope
