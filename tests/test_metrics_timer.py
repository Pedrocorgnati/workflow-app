"""Tests for ElapsedTimer and EstimateCalculator (module-13/TASK-2)."""

from __future__ import annotations

from workflow_app.core.metrics_timer import ElapsedTimer, EstimateCalculator

# ── ElapsedTimer ─────────────────────────────────────────────────────────── #


def test_elapsed_starts_at_zero():
    timer = ElapsedTimer()
    assert timer.elapsed == 0


def test_tick_increments_elapsed():
    timer = ElapsedTimer()
    timer.tick()
    assert timer.elapsed == 1


def test_tick_multiple_times():
    timer = ElapsedTimer()
    for _ in range(5):
        timer.tick()
    assert timer.elapsed == 5


def test_reset_clears_elapsed():
    timer = ElapsedTimer()
    timer.tick()
    timer.tick()
    timer.reset()
    assert timer.elapsed == 0


def test_start_sets_running():
    timer = ElapsedTimer()
    timer.start()
    assert timer.running is True


def test_stop_clears_running():
    timer = ElapsedTimer()
    timer.start()
    timer.stop()
    assert timer.running is False


def test_reset_also_stops():
    timer = ElapsedTimer()
    timer.start()
    timer.tick()
    timer.reset()
    assert timer.running is False
    assert timer.elapsed == 0


# ── ElapsedTimer.format ──────────────────────────────────────────────────── #


def test_format_zero():
    assert ElapsedTimer.format(0) == "00:00"


def test_format_65_seconds():
    assert ElapsedTimer.format(65) == "01:05"


def test_format_one_hour():
    assert ElapsedTimer.format(3661) == "01:01:01"


def test_format_exactly_one_minute():
    assert ElapsedTimer.format(60) == "01:00"


# ── EstimateCalculator ───────────────────────────────────────────────────── #


def test_calculate_no_data_returns_none():
    calc = EstimateCalculator()
    assert calc.calculate(5) is None


def test_calculate_one_event_returns_none():
    calc = EstimateCalculator()
    calc.record_completion()
    assert calc.calculate(5) is None


def test_calculate_zero_remaining_returns_zero():
    calc = EstimateCalculator()
    calc.record_completion(0.0)
    calc.record_completion(5.0)
    assert calc.calculate(0) == 0.0


def test_calculate_with_two_events():
    calc = EstimateCalculator()
    # 2 commands completed in 10 seconds → rate = 0.1 cmd/s
    calc.record_completion(0.0)
    calc.record_completion(10.0)
    # 5 remaining → 50 seconds
    result = calc.calculate(5)
    assert result is not None
    assert abs(result - 50.0) < 1.0


# ── EstimateCalculator.format ────────────────────────────────────────────── #


def test_format_none_returns_empty():
    assert EstimateCalculator.format(None) == ""


def test_format_zero_seconds():
    assert EstimateCalculator.format(0) == "~0 min restantes"


def test_estimate_format_65_seconds():
    assert EstimateCalculator.format(65) == "~1 min restantes"


def test_format_3600_seconds():
    assert EstimateCalculator.format(3600) == "~60 min restantes"
