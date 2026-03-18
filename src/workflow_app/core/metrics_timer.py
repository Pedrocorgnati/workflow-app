"""
ElapsedTimer and EstimateCalculator — pipeline timing utilities (module-13/TASK-2).

ElapsedTimer: counts elapsed seconds (driven by QTimer.timeout in MetricsBar).
EstimateCalculator: estimates remaining time from recent completion rate.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass

# ─── MetricsSnapshot ─────────────────────────────────────────────────────── #


@dataclass
class MetricsSnapshot:
    """Snapshot of pipeline metrics emitted via signal_bus.metrics_snapshot."""

    total_commands: int = 0
    completed_commands: int = 0
    error_commands: int = 0
    tokens_input: int = 0
    tokens_output: int = 0
    cost_estimate_usd: float = 0.0


# ─── ElapsedTimer ────────────────────────────────────────────────────────── #


class ElapsedTimer:
    """Tracks elapsed seconds for a pipeline execution.

    Designed to be driven by a QTimer that calls tick() every second.
    """

    def __init__(self) -> None:
        self._elapsed: int = 0
        self._running: bool = False

    # ── Properties ───────────────────────────────────────────────────── #

    @property
    def elapsed(self) -> int:
        """Total elapsed seconds since last reset."""
        return self._elapsed

    @property
    def running(self) -> bool:
        """True when the timer is active."""
        return self._running

    # ── Control ──────────────────────────────────────────────────────── #

    def start(self) -> None:
        """Mark timer as running."""
        self._running = True

    def stop(self) -> None:
        """Mark timer as stopped (does NOT reset elapsed)."""
        self._running = False

    def tick(self) -> None:
        """Increment elapsed by 1 second. Call from QTimer.timeout."""
        self._elapsed += 1

    def reset(self) -> None:
        """Reset elapsed to 0 and stop the timer."""
        self._elapsed = 0
        self._running = False

    # ── Formatting ───────────────────────────────────────────────────── #

    @staticmethod
    def format(seconds: int) -> str:
        """Format seconds as MM:SS (or HH:MM:SS when >= 1 hour).

        >>> ElapsedTimer.format(0)
        '00:00'
        >>> ElapsedTimer.format(65)
        '01:05'
        >>> ElapsedTimer.format(3661)
        '01:01:01'
        """
        h = seconds // 3600
        m = (seconds % 3600) // 60
        s = seconds % 60
        if h:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"


# ─── EstimateCalculator ──────────────────────────────────────────────────── #


class EstimateCalculator:
    """Estimates remaining pipeline time from recent completion rate.

    Uses a sliding window of completion events to compute the average
    time per command, then multiplies by remaining commands.
    """

    def __init__(self, window_seconds: float = 300.0) -> None:
        self._window: float = window_seconds
        self._completions: deque[float] = deque()

    def record_completion(self, event_time: float | None = None) -> None:
        """Record a command completion event.

        Args:
            event_time: Monotonic timestamp (default: current time).
        """
        t = event_time if event_time is not None else time.monotonic()
        self._completions.append(t)
        # Prune events outside the sliding window
        cutoff = t - self._window
        while self._completions and self._completions[0] < cutoff:
            self._completions.popleft()

    def calculate(self, remaining_commands: int) -> float | None:
        """Estimate remaining seconds based on recent completion rate.

        Returns None when there is insufficient data (fewer than 2 events).
        Returns 0.0 when remaining_commands is 0.
        """
        if remaining_commands <= 0:
            return 0.0
        if len(self._completions) < 2:
            return None
        span = self._completions[-1] - self._completions[0]
        if span <= 0:
            return None
        rate = (len(self._completions) - 1) / span  # commands per second
        return remaining_commands / rate

    @staticmethod
    def format(seconds: float | None) -> str:
        """Format estimated seconds as a human-readable string.

        >>> EstimateCalculator.format(None)
        ''
        >>> EstimateCalculator.format(0)
        '~0 min restantes'
        >>> EstimateCalculator.format(65)
        '~1 min restantes'
        >>> EstimateCalculator.format(3600)
        '~60 min restantes'
        """
        if seconds is None:
            return ""
        minutes = max(0, int(seconds // 60))
        return f"~{minutes} min restantes"
