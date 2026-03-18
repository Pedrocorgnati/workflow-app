"""
MetricsCollector — thread-safe singleton for tracking RemoteServer operational metrics.

Counters:
  connections_total     — lifetime client connections accepted
  messages_received     — inbound messages dispatched to SignalBridge
  messages_sent         — outbound text frames sent to client
  bytes_received        — total bytes received (pre-size-check)
  bytes_sent            — total bytes sent
  rate_limit_drops      — messages discarded by rate limiter
  dedup_drops           — messages discarded as duplicates

Latency:
  Moving average over the last 100 round-trip ping→pong intervals (ms).

Usage::

    mc = MetricsCollector.instance()
    mc.record_connection()
    mc.record_message_received(len_bytes)
    snapshot = mc.snapshot()  # returns a copy — thread-safe read
    mc.reset()                # on server start
"""

from __future__ import annotations

import dataclasses
import logging
import threading
import time
from collections import deque

logger = logging.getLogger(__name__)

# Moving average window size for latency measurements
_LATENCY_WINDOW = 100


@dataclasses.dataclass
class RemoteMetrics:
    """Immutable snapshot of current RemoteServer metrics."""

    connections_total: int = 0
    messages_received: int = 0
    messages_sent: int = 0
    bytes_received: int = 0
    bytes_sent: int = 0
    rate_limit_drops: int = 0
    dedup_drops: int = 0
    avg_latency_ms: float = 0.0
    uptime_s: float = 0.0


class MetricsCollector:
    """Thread-safe singleton that records RemoteServer operational metrics.

    Use ``MetricsCollector.instance()`` to obtain the shared collector.
    All public methods are safe to call from any thread.
    """

    _instance: MetricsCollector | None = None
    _lock: threading.Lock = threading.Lock()

    # ── Singleton ─────────────────────────────────────────────────────────────

    @classmethod
    def instance(cls) -> MetricsCollector:
        """Return the process-wide singleton (double-checked locking)."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls._create()
        return cls._instance

    @classmethod
    def _create(cls) -> MetricsCollector:
        obj = object.__new__(cls)
        obj._metric_lock = threading.Lock()
        obj._connections_total = 0
        obj._messages_received = 0
        obj._messages_sent = 0
        obj._bytes_received = 0
        obj._bytes_sent = 0
        obj._rate_limit_drops = 0
        obj._dedup_drops = 0
        obj._latency_samples: deque[float] = deque(maxlen=_LATENCY_WINDOW)
        obj._start_time: float = time.monotonic()
        return obj

    def __init__(self) -> None:
        # Prevent direct instantiation
        raise RuntimeError("Use MetricsCollector.instance() instead of direct construction")

    # ── Record methods (called from RemoteServer) ─────────────────────────────

    def record_connection(self) -> None:
        """Increment connection counter. Call when a client is accepted."""
        with self._metric_lock:
            self._connections_total += 1

    def record_message_received(self, byte_count: int = 0) -> None:
        """Increment inbound message counter and add to bytes_received."""
        with self._metric_lock:
            self._messages_received += 1
            self._bytes_received += byte_count

    def record_message_sent(self, byte_count: int = 0) -> None:
        """Increment outbound message counter and add to bytes_sent."""
        with self._metric_lock:
            self._messages_sent += 1
            self._bytes_sent += byte_count

    def record_rate_limit_drop(self) -> None:
        """Increment rate-limit discard counter."""
        with self._metric_lock:
            self._rate_limit_drops += 1

    def record_dedup_drop(self) -> None:
        """Increment deduplication discard counter."""
        with self._metric_lock:
            self._dedup_drops += 1

    def record_latency(self, latency_ms: float) -> None:
        """Add a latency sample (ping→pong RTT in milliseconds)."""
        with self._metric_lock:
            self._latency_samples.append(latency_ms)

    # ── Read methods ─────────────────────────────────────────────────────────

    def snapshot(self) -> RemoteMetrics:
        """Return an immutable copy of current metrics. Thread-safe."""
        with self._metric_lock:
            avg = (
                sum(self._latency_samples) / len(self._latency_samples)
                if self._latency_samples
                else 0.0
            )
            return RemoteMetrics(
                connections_total=self._connections_total,
                messages_received=self._messages_received,
                messages_sent=self._messages_sent,
                bytes_received=self._bytes_received,
                bytes_sent=self._bytes_sent,
                rate_limit_drops=self._rate_limit_drops,
                dedup_drops=self._dedup_drops,
                avg_latency_ms=round(avg, 2),
                uptime_s=round(time.monotonic() - self._start_time, 1),
            )

    def reset(self) -> None:
        """Reset all counters and restart uptime. Call on server (re)start."""
        with self._metric_lock:
            self._connections_total = 0
            self._messages_received = 0
            self._messages_sent = 0
            self._bytes_received = 0
            self._bytes_sent = 0
            self._rate_limit_drops = 0
            self._dedup_drops = 0
            self._latency_samples.clear()
            self._start_time = time.monotonic()
        logger.debug("MetricsCollector: counters reset")
