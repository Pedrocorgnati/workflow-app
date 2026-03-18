"""Tests for MetricsBar progress, badges, token and git info (module-13/TASK-3)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from workflow_app.core.metrics_timer import MetricsSnapshot
from workflow_app.metrics_bar.metrics_bar import MetricsBar


@pytest.fixture()
def bar(qapp):
    bus = MagicMock()
    return MetricsBar(bus)


# ── _on_metrics_snapshot ─────────────────────────────────────────────────── #


def test_snapshot_does_not_crash_on_progress(bar):
    """_on_metrics_snapshot with total/completed does not crash (progress label removed)."""
    snap = MetricsSnapshot(total_commands=10, completed_commands=4, error_commands=0)
    bar._on_metrics_snapshot(snap)  # no _lbl_progress — should not raise


def test_snapshot_shows_error_badge(bar):
    snap = MetricsSnapshot(total_commands=10, completed_commands=3, error_commands=2)
    bar._on_metrics_snapshot(snap)
    assert not bar._lbl_errors.isHidden()
    assert "2 erros" in bar._lbl_errors.text()


def test_snapshot_hides_error_badge_when_zero(bar):
    # Set then clear errors
    bar.set_errors_badge(1)
    snap = MetricsSnapshot(total_commands=5, completed_commands=2, error_commands=0)
    bar._on_metrics_snapshot(snap)
    assert bar._lbl_errors.isHidden()


def test_snapshot_updates_token_label(bar):
    snap = MetricsSnapshot(
        total_commands=5,
        completed_commands=2,
        tokens_input=5000,
        tokens_output=2000,
        cost_estimate_usd=0.05,
    )
    bar._on_metrics_snapshot(snap)
    assert not bar._lbl_tokens.isHidden()
    assert "↑5k" in bar._lbl_tokens.text()


# ── _on_token_update ─────────────────────────────────────────────────────── #


def test_token_update_formats_correctly(bar):
    bar._on_token_update(5000, 2000, 0.05)
    assert "↑5k" in bar._lbl_tokens.text()
    assert "↓2k" in bar._lbl_tokens.text()
    assert "$0.05" in bar._lbl_tokens.text()
    assert not bar._lbl_tokens.isHidden()


def test_token_update_small_values(bar):
    bar._on_token_update(500, 200, 0.01)
    assert "↑500" in bar._lbl_tokens.text()
    assert "↓200" in bar._lbl_tokens.text()


# ── _on_git_info_updated ─────────────────────────────────────────────────── #


def test_git_info_becomes_visible(bar):
    bar._on_git_info_updated("abc1234 fix: update prompt")
    assert not bar._lbl_git_info.isHidden()
    assert "abc1234" in bar._lbl_git_info.text()


def test_git_info_empty_hides_label(bar):
    bar._on_git_info_updated("abc1234 fix: something")
    bar._on_git_info_updated("")
    assert bar._lbl_git_info.isHidden()


# ── set_progress_text (backward-compat stub) ─────────────────────────────── #


def test_set_progress_text_no_crash(bar):
    """set_progress_text() is a backward-compat no-op — must not crash."""
    bar.set_progress_text(3, 10)
    bar.set_progress_text(0, 0)
    bar.set_progress_text(10, 10)
