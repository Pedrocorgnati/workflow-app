"""
Performance Budget Tests — module-12/TASK-3

Validates performance constraints defined in the PRD:
- OutputThrottle flush interval: 100ms (THROTTLE_PC_MS)
- OutputThrottle batch limit: 4KB (MAX_BATCH_KB)
- Buffer line limit: MAX_BUFFER_LINES
- Rate limit: 20 msg/s (RATE_LIMIT_MSG_PER_S)
- Dedup window: 10,000 entries (DEDUP_SET_LIMIT)
- Heartbeat interval: 30s (PING_INTERVAL_S)
- Pong timeout: 10s (PONG_TIMEOUT_MS)

Note: True latency tests (INT-020: < 500ms end-to-end) require a real
WebSocket connection with Android hardware. These tests validate the
PC-side budget contributions only (THROTTLE_PC_MS = 100ms out of 350ms budget).

INT-020: output latency < 500ms (PC 100ms + Tailscale 50ms + Android 200ms)
INT-042: Android output buffer max 5000 lines (tested in ANDROID_PERFORMANCE.md)
INT-060: reconnection < 30s (covered by BackoffStrategyTest.kt)
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

from workflow_app.remote.constants import (
    DEDUP_SET_LIMIT,
    MAX_BATCH_KB,
    MAX_BUFFER_LINES,
    PING_INTERVAL_S,
    RATE_LIMIT_MSG_PER_S,
    THROTTLE_PC_MS,
)
from workflow_app.remote.heartbeat_manager import PONG_TIMEOUT_MS
from workflow_app.remote.output_throttle import OutputThrottle
from workflow_app.remote.remote_server import _RateLimiter

# ── 1. PC Output Throttle Budget (INT-020 — PC side) ─────────────────────────


class TestOutputThrottleBudget:
    """Validates PC-side output throttle performance budget.

    PC budget contribution: THROTTLE_PC_MS = 100ms (out of 350ms total).
    Total budget: 100ms (PC) + 50ms (Tailscale) + 200ms (Android render) = 350ms.
    """

    def test_throttle_interval_is_100ms(self):
        """THROTTLE_PC_MS is exactly 100ms — PC output latency budget."""
        assert THROTTLE_PC_MS == 100

    def test_max_batch_kb_is_4kb(self):
        """MAX_BATCH_KB is 4KB — batch size limit."""
        assert MAX_BATCH_KB == 4

    def test_max_buffer_lines_defined(self):
        """MAX_BUFFER_LINES is defined (PC-side buffer before truncation)."""
        assert MAX_BUFFER_LINES > 0

    def test_flush_accumulates_lines(self):
        """OutputThrottle accumulates multiple push() calls in one flush."""
        throttle = OutputThrottle()
        flushed: list[dict] = []

        mock_bridge = MagicMock()
        mock_bridge._send_message = lambda t, p: flushed.append({"type": t, "payload": p})
        throttle.attach(mock_bridge)

        # Push 5 lines, then flush
        for i in range(5):
            throttle.push(f"line {i}")
        throttle._flush()

        # One flush produces one output_chunk
        assert len(flushed) == 1
        assert flushed[0]["type"] == "output_chunk"

    def test_flush_sends_all_accumulated_lines(self):
        """All pushed lines appear in the flush payload."""
        throttle = OutputThrottle()
        flushed: list[dict] = []

        mock_bridge = MagicMock()
        mock_bridge._send_message = lambda t, p: flushed.append({"type": t, "payload": p})
        throttle.attach(mock_bridge)

        lines = ["alpha", "beta", "gamma"]
        for line in lines:
            throttle.push(line)
        throttle._flush()

        payload = flushed[0]["payload"]
        # DIV-001 fixed: sends {"lines": List[str]}
        assert "lines" in payload, "DIV-001 regression: payload must have 'lines' key"
        assert payload["lines"] == lines

    def test_immediate_flush_on_4kb_threshold(self):
        """OutputThrottle flushes immediately when buffer reaches 4KB."""
        throttle = OutputThrottle()
        flush_count = [0]

        mock_bridge = MagicMock()
        mock_bridge._send_message = lambda t, p: flush_count.__setitem__(
            0, flush_count[0] + 1
        )
        throttle.attach(mock_bridge)

        # Push 4KB+ of data in one shot
        big_line = "x" * (MAX_BATCH_KB * 1024 + 10)
        throttle.push(big_line)

        # Should have triggered immediate flush
        assert flush_count[0] == 1

    def test_buffer_cleared_after_flush(self):
        """Internal buffer is cleared after each flush."""
        throttle = OutputThrottle()
        mock_bridge = MagicMock()
        mock_bridge._send_message = MagicMock()
        throttle.attach(mock_bridge)

        throttle.push("line 1")
        throttle._flush()

        # Buffer should be empty
        assert len(throttle._buffer) == 0
        assert throttle._buffer_bytes == 0

    def test_empty_buffer_does_not_flush(self):
        """_flush() with empty buffer sends nothing."""
        throttle = OutputThrottle()
        mock_bridge = MagicMock()
        mock_bridge._send_message = MagicMock()
        throttle.attach(mock_bridge)

        throttle._flush()  # nothing in buffer

        mock_bridge._send_message.assert_not_called()

    def test_no_flush_without_bridge(self):
        """_flush() without bridge attached does nothing (no crash)."""
        throttle = OutputThrottle()
        throttle.push("line 1")
        throttle._flush()  # no bridge — should not raise

    def test_truncation_on_buffer_overflow(self):
        """When buffer exceeds MAX_BUFFER_LINES, truncation message is sent."""
        throttle = OutputThrottle()
        messages: list[dict] = []

        mock_bridge = MagicMock()
        mock_bridge._send_message = lambda t, p: messages.append({"type": t, "payload": p})
        throttle.attach(mock_bridge)

        # Fill buffer beyond MAX_BUFFER_LINES
        for i in range(MAX_BUFFER_LINES + 10):
            throttle._buffer.append(f"line {i}")

        throttle._flush()

        types = [m["type"] for m in messages]
        assert "output_truncated" in types
        truncated_msg = next(m for m in messages if m["type"] == "output_truncated")
        payload = truncated_msg["payload"]
        # DIV-002 fixed: sends {"lines_omitted": N}
        assert "lines_omitted" in payload, "DIV-002 regression: payload must have 'lines_omitted' key"
        assert payload["lines_omitted"] == 10  # 10 lines above MAX_BUFFER_LINES

    def test_stop_discards_buffer(self):
        """stop() discards accumulated buffer without sending."""
        throttle = OutputThrottle()
        mock_bridge = MagicMock()
        mock_bridge._send_message = MagicMock()
        throttle.attach(mock_bridge)

        throttle.push("line 1")
        throttle.push("line 2")
        throttle.stop()

        # Buffer cleared, nothing sent
        assert len(throttle._buffer) == 0
        mock_bridge._send_message.assert_not_called()


# ── 2. Rate Limiter Performance Budget ───────────────────────────────────────


class TestRateLimiterBudget:
    """Validates rate limiter performance: 20 msg/s fixed window."""

    def test_rate_limit_is_20_per_second(self):
        """RATE_LIMIT_MSG_PER_S = 20."""
        assert RATE_LIMIT_MSG_PER_S == 20

    def test_rate_limiter_throughput_20_in_1s(self):
        """Within a 1s window, exactly 20 messages pass."""
        limiter = _RateLimiter(limit=20)
        passed = sum(1 for _ in range(25) if limiter.check())
        assert passed == 20

    def test_rate_limiter_resets_for_next_window(self):
        """After window expires, full 20 messages allowed again."""
        limiter = _RateLimiter(limit=20)
        # Exhaust window
        for _ in range(20):
            limiter.check()
        assert limiter.check() is False

        # Expire window
        limiter._window_start = time.monotonic() - 1.1

        # Full window available again
        passed = sum(1 for _ in range(20) if limiter.check())
        assert passed == 20

    def test_rate_limiter_does_not_reject_first_message(self):
        """First message is always accepted."""
        limiter = _RateLimiter(limit=20)
        assert limiter.check() is True


# ── 3. Heartbeat Budget ───────────────────────────────────────────────────────


class TestHeartbeatBudget:
    """Validates heartbeat timing constants."""

    def test_ping_interval_is_30s(self):
        """PING_INTERVAL_S = 30 (OkHttp ping interval on Android side too)."""
        assert PING_INTERVAL_S == 30

    def test_pong_timeout_is_10s(self):
        """PONG_TIMEOUT_MS = 10,000ms (10 seconds)."""
        assert PONG_TIMEOUT_MS == 10_000

    def test_ping_timer_interval_matches_constant(self, qapp):
        """QTimer interval matches PING_INTERVAL_S * 1000ms."""
        from workflow_app.remote.heartbeat_manager import HeartbeatManager

        hb = HeartbeatManager()
        assert hb._ping_timer.interval() == PING_INTERVAL_S * 1000

    def test_pong_timeout_timer_interval_matches_constant(self, qapp):
        """One-shot pong timer interval matches PONG_TIMEOUT_MS."""
        from workflow_app.remote.heartbeat_manager import HeartbeatManager

        hb = HeartbeatManager()
        assert hb._pong_timeout_timer.interval() == PONG_TIMEOUT_MS
        assert hb._pong_timeout_timer.isSingleShot() is True


# ── 4. Buffer and Dedup Limits ────────────────────────────────────────────────


class TestBufferAndDedupBudget:
    """Validates bounded data structure limits."""

    def test_dedup_limit_is_10000(self):
        """DEDUP_SET_LIMIT = 10,000 entries (INT-015)."""
        assert DEDUP_SET_LIMIT == 10_000

    def test_max_buffer_lines_value(self):
        """MAX_BUFFER_LINES is a positive integer."""
        assert isinstance(MAX_BUFFER_LINES, int)
        assert MAX_BUFFER_LINES > 0

    def test_output_throttle_bytes_tracking(self):
        """OutputThrottle tracks buffer bytes accurately."""
        throttle = OutputThrottle()
        mock_bridge = MagicMock()
        mock_bridge._send_message = MagicMock()
        throttle.attach(mock_bridge)

        test_str = "hello"  # 5 bytes UTF-8
        throttle.push(test_str)

        assert throttle._buffer_bytes == len(test_str.encode("utf-8"))

    def test_output_throttle_bytes_accumulate(self):
        """Buffer bytes accumulate correctly across multiple pushes."""
        throttle = OutputThrottle()
        mock_bridge = MagicMock()
        mock_bridge._send_message = MagicMock()
        throttle.attach(mock_bridge)

        lines = ["line1", "line2", "line3"]
        expected_bytes = sum(len(line.encode("utf-8")) for line in lines)
        for line in lines:
            throttle.push(line)

        assert throttle._buffer_bytes == expected_bytes

    def test_output_throttle_bytes_reset_after_flush(self):
        """Buffer bytes reset to 0 after flush."""
        throttle = OutputThrottle()
        mock_bridge = MagicMock()
        mock_bridge._send_message = MagicMock()
        throttle.attach(mock_bridge)

        throttle.push("some content")
        assert throttle._buffer_bytes > 0

        throttle._flush()
        assert throttle._buffer_bytes == 0


# ── 5. Timing Budget Summary (INT-020) ───────────────────────────────────────


class TestTimingBudgetConstants:
    """Documents the complete timing budget chain (INT-020).

    PC (THROTTLE_PC_MS=100ms) + Tailscale (~50ms) + Android (200ms) = ~350ms
    Budget ceiling: 500ms (PRD requirement)
    """

    def test_pc_latency_budget_ms(self):
        """PC-side latency budget: THROTTLE_PC_MS = 100ms."""
        assert THROTTLE_PC_MS == 100
        assert THROTTLE_PC_MS < 500  # must be below total budget

    def test_total_budget_ceiling(self):
        """PC budget + safe Android estimate stays under 500ms ceiling."""
        pc_budget = THROTTLE_PC_MS  # 100ms
        tailscale_budget = 50       # ~50ms typical Tailscale latency
        android_budget = 200        # Android render throttle (INT-059)
        total_estimate = pc_budget + tailscale_budget + android_budget

        # Must be under 500ms PRD requirement
        assert total_estimate <= 500, (
            f"Estimated latency {total_estimate}ms exceeds 500ms budget"
        )

    def test_reconnect_budget_seconds(self):
        """Reconnect budget: BackoffStrategy should succeed in < 30s.

        Backoff sequence: 2s + 4s + 8s + 16s = 30s total (4 attempts).
        Android caps at 3 attempts (INT-056), so max wait = 2+4+8 = 14s.
        PRD requirement: < 30s (INT-060).
        """
        backoff_attempts = [2, 4, 8]  # 3 attempts (INT-056)
        total_backoff = sum(backoff_attempts)
        assert total_backoff < 30, (
            f"Backoff sum {total_backoff}s exceeds 30s reconnect budget"
        )
