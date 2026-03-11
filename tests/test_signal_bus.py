"""Tests for SignalBus singleton."""

from __future__ import annotations

from workflow_app.signal_bus import signal_bus


def test_signal_bus_has_toast_signal():
    assert hasattr(signal_bus, "toast_requested")


def test_signal_bus_has_pipeline_signals():
    assert hasattr(signal_bus, "pipeline_ready")
    assert hasattr(signal_bus, "pipeline_started")
    assert hasattr(signal_bus, "pipeline_completed")
    assert hasattr(signal_bus, "pipeline_cancelled")


def test_toast_signal(qapp):
    received = []
    signal_bus.toast_requested.connect(lambda msg, t: received.append((msg, t)))
    signal_bus.toast_requested.emit("test message", "info")
    assert ("test message", "info") in received


def test_metrics_signal(qapp):
    received = []
    signal_bus.metrics_updated.connect(lambda c, t: received.append((c, t)))
    signal_bus.metrics_updated.emit(3, 10)
    assert (3, 10) in received
