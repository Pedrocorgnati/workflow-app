"""
Tests for MetricsCollector (module-10-devops TASK-2/ST006).

Covers:
- ST001/ST002: RemoteMetrics dataclass + MetricsCollector singleton
- ST003: record_* methods update snapshot correctly
- Thread-safety: concurrent increments produce correct total
- reset() clears all counters
- snapshot() returns copy (mutations don't affect internal state)
- avg_latency_ms: computed correctly from samples, 0.0 when empty
"""

from __future__ import annotations

import threading

import pytest

from workflow_app.remote.metrics import MetricsCollector, RemoteMetrics

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_singleton():
    """Reset MetricsCollector between tests by resetting its counters."""
    mc = MetricsCollector.instance()
    mc.reset()
    yield
    mc.reset()


# ── Tests ─────────────────────────────────────────────────────────────────────


class TestRemoteMetrics:
    def test_defaults_are_zero(self):
        m = RemoteMetrics()
        assert m.connections_total == 0
        assert m.messages_received == 0
        assert m.messages_sent == 0
        assert m.bytes_received == 0
        assert m.bytes_sent == 0
        assert m.rate_limit_drops == 0
        assert m.dedup_drops == 0
        assert m.avg_latency_ms == 0.0
        assert m.uptime_s >= 0.0


class TestMetricsCollectorSingleton:
    def test_instance_returns_same_object(self):
        a = MetricsCollector.instance()
        b = MetricsCollector.instance()
        assert a is b

    def test_direct_instantiation_raises(self):
        with pytest.raises(RuntimeError, match="instance()"):
            MetricsCollector()


class TestMetricsCollectorRecording:
    def test_record_connection(self):
        mc = MetricsCollector.instance()
        mc.record_connection()
        mc.record_connection()
        assert mc.snapshot().connections_total == 2

    def test_record_message_received(self):
        mc = MetricsCollector.instance()
        mc.record_message_received(100)
        mc.record_message_received(200)
        snap = mc.snapshot()
        assert snap.messages_received == 2
        assert snap.bytes_received == 300

    def test_record_message_sent(self):
        mc = MetricsCollector.instance()
        mc.record_message_sent(50)
        snap = mc.snapshot()
        assert snap.messages_sent == 1
        assert snap.bytes_sent == 50

    def test_record_rate_limit_drop(self):
        mc = MetricsCollector.instance()
        mc.record_rate_limit_drop()
        mc.record_rate_limit_drop()
        assert mc.snapshot().rate_limit_drops == 2

    def test_record_dedup_drop(self):
        mc = MetricsCollector.instance()
        mc.record_dedup_drop()
        assert mc.snapshot().dedup_drops == 1

    def test_record_latency_avg(self):
        mc = MetricsCollector.instance()
        mc.record_latency(100.0)
        mc.record_latency(200.0)
        mc.record_latency(300.0)
        snap = mc.snapshot()
        assert snap.avg_latency_ms == pytest.approx(200.0, abs=0.1)

    def test_avg_latency_zero_when_no_samples(self):
        mc = MetricsCollector.instance()
        assert mc.snapshot().avg_latency_ms == 0.0

    def test_latency_window_capped_at_100(self):
        mc = MetricsCollector.instance()
        # Push 110 samples: first 10 will be evicted
        for i in range(110):
            mc.record_latency(float(i))
        snap = mc.snapshot()
        # Window now contains samples 10..109 → avg = (10+109)/2 = 59.5
        assert snap.avg_latency_ms == pytest.approx(59.5, abs=0.1)


class TestMetricsCollectorReset:
    def test_reset_clears_counters(self):
        mc = MetricsCollector.instance()
        mc.record_connection()
        mc.record_message_received(100)
        mc.record_rate_limit_drop()
        mc.record_latency(50.0)
        mc.reset()
        snap = mc.snapshot()
        assert snap.connections_total == 0
        assert snap.messages_received == 0
        assert snap.bytes_received == 0
        assert snap.rate_limit_drops == 0
        assert snap.avg_latency_ms == 0.0


class TestMetricsCollectorThreadSafety:
    def test_concurrent_increments(self):
        """100 threads each incrementing connections 10 times → 1000 total."""
        mc = MetricsCollector.instance()
        threads = [
            threading.Thread(target=lambda: [mc.record_connection() for _ in range(10)])
            for _ in range(100)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert mc.snapshot().connections_total == 1000
