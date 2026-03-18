"""
Tests for OutputThrottle — requires QApplication (via qapp fixture).

OutputThrottle uses QTimer; all tests run in the Qt main thread.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from workflow_app.remote.constants import MAX_BATCH_KB, MAX_BUFFER_LINES
from workflow_app.remote.output_throttle import OutputThrottle


@pytest.fixture
def throttle(qapp):
    t = OutputThrottle()
    yield t
    t.stop()


@pytest.fixture
def bridge_mock():
    mock = MagicMock()
    return mock


# ── push / buffer mechanics ───────────────────────────────────────────────────


def test_push_accumulates_without_flush(throttle, bridge_mock):
    throttle.attach(bridge_mock)
    throttle.push("line 1")
    throttle.push("line 2")
    # Timer has not fired — no message sent yet
    bridge_mock._send_message.assert_not_called()


def test_push_triggers_immediate_flush_at_batch_limit(throttle, bridge_mock):
    throttle.attach(bridge_mock)
    # Push exactly MAX_BATCH_KB KB of data
    big_line = "x" * (MAX_BATCH_KB * 1024)
    throttle.push(big_line)
    bridge_mock._send_message.assert_called_once()
    call_args = bridge_mock._send_message.call_args
    assert call_args[0][0] == "output_chunk"


def test_flush_clears_buffer(throttle, bridge_mock):
    throttle.attach(bridge_mock)
    throttle.push("hello")
    throttle._flush()
    # After flush, buffer is empty
    assert throttle._buffer == []
    assert throttle._buffer_bytes == 0


def test_flush_sends_lines_list(throttle, bridge_mock):
    throttle.attach(bridge_mock)
    throttle.push("line A")
    throttle.push("line B")
    throttle._flush()
    call_args = bridge_mock._send_message.call_args
    assert call_args[0][0] == "output_chunk"
    payload = call_args[0][1]
    assert "lines" in payload, "DIV-001 fix: must send {'lines': [...]}"
    assert "line A" in payload["lines"]
    assert "line B" in payload["lines"]


def test_flush_does_nothing_when_buffer_empty(throttle, bridge_mock):
    throttle.attach(bridge_mock)
    throttle._flush()
    bridge_mock._send_message.assert_not_called()


def test_flush_does_nothing_without_bridge(throttle):
    # No bridge attached — should not raise
    throttle.push("text")
    throttle._flush()   # no error


# ── Truncation ────────────────────────────────────────────────────────────────


def test_truncation_when_buffer_exceeds_max_lines(throttle, bridge_mock):
    throttle.attach(bridge_mock)
    # Fill beyond MAX_BUFFER_LINES
    for i in range(MAX_BUFFER_LINES + 5):
        throttle._buffer.append(f"line {i}")
    throttle._buffer_bytes = 1  # non-zero so flush runs

    throttle._flush()

    calls = [c[0] for c in bridge_mock._send_message.call_args_list]
    types_sent = [c[0] for c in calls]
    assert "output_truncated" in types_sent
    assert "output_chunk" in types_sent


def test_truncation_payload_contains_lines_omitted(throttle, bridge_mock):
    throttle.attach(bridge_mock)
    extra = 10
    for i in range(MAX_BUFFER_LINES + extra):
        throttle._buffer.append(f"x{i}")
    throttle._buffer_bytes = 1

    throttle._flush()

    truncated_calls = [
        c for c in bridge_mock._send_message.call_args_list
        if c[0][0] == "output_truncated"
    ]
    assert len(truncated_calls) == 1
    assert truncated_calls[0][0][1]["lines_omitted"] == extra, (
        "DIV-002 fix: must send {'lines_omitted': N}"
    )


# ── stop ──────────────────────────────────────────────────────────────────────


def test_stop_clears_buffer(throttle, bridge_mock):
    throttle.attach(bridge_mock)
    throttle.push("data")
    throttle.stop()
    assert throttle._buffer == []
    assert throttle._buffer_bytes == 0
