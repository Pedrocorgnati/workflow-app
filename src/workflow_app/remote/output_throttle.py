"""
OutputThrottle — accumulates output_chunk text and flushes at controlled rate.

Rules (per LLD §3.2):
- QTimer fires every THROTTLE_PC_MS (100 ms) → flush accumulated buffer.
- Flush immediately when buffer size >= MAX_BATCH_KB (4 KB).
- When the buffer exceeds MAX_BUFFER_LINES on flush, truncate oldest lines
  and send an output_truncated message with the count of discarded lines.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from PySide6.QtCore import QTimer

from workflow_app.remote.constants import MAX_BATCH_KB, MAX_BUFFER_LINES, THROTTLE_PC_MS

if TYPE_CHECKING:
    from workflow_app.remote.signal_bridge import SignalBridge

logger = logging.getLogger(__name__)


class OutputThrottle:
    """Batches output text and forwards it to SignalBridge at THROTTLE_PC_MS intervals.

    Usage::

        throttle = OutputThrottle()
        throttle.attach(bridge)
        throttle.start()
        throttle.push("some text")
        throttle.stop()
    """

    def __init__(self) -> None:
        self._buffer: list[str] = []
        self._buffer_bytes: int = 0
        self._discarded_count: int = 0
        self._bridge: SignalBridge | None = None

        self._timer = QTimer()
        self._timer.setInterval(THROTTLE_PC_MS)
        self._timer.timeout.connect(self._flush)

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def attach(self, bridge: SignalBridge) -> None:
        """Register the SignalBridge that will receive flushed chunks."""
        self._bridge = bridge

    def start(self) -> None:
        """Start the flush timer."""
        self._timer.start()

    def stop(self) -> None:
        """Stop the timer and discard any buffered content."""
        self._timer.stop()
        self._buffer.clear()
        self._buffer_bytes = 0
        self._discarded_count = 0

    # ── Public API ────────────────────────────────────────────────────────────

    def push(self, text: str) -> None:
        """Add *text* to the buffer.

        Triggers an immediate flush if the buffer reaches MAX_BATCH_KB.
        """
        self._buffer.append(text)
        self._buffer_bytes += len(text.encode("utf-8"))
        self._check_batch_limit()

    # ── Private ───────────────────────────────────────────────────────────────

    def _check_batch_limit(self) -> None:
        if self._buffer_bytes >= MAX_BATCH_KB * 1024:
            logger.debug("OutputThrottle: batch limit reached (%d bytes), flushing", self._buffer_bytes)
            self._flush()

    def _flush(self) -> None:
        if not self._buffer or self._bridge is None:
            return

        # Truncate if buffer grew too large
        if len(self._buffer) > MAX_BUFFER_LINES:
            discarded = len(self._buffer) - MAX_BUFFER_LINES
            self._buffer = self._buffer[-MAX_BUFFER_LINES:]
            self._discarded_count += discarded
            self._emit_truncated(discarded)

        lines = list(self._buffer)
        self._bridge._send_message("output_chunk", {"lines": lines})

        self._buffer.clear()
        self._buffer_bytes = 0

    def _emit_truncated(self, count: int) -> None:
        if self._bridge is not None:
            self._bridge._send_message("output_truncated", {"lines_omitted": count})
