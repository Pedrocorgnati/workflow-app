"""Tests for MetricsBar shell (module-13/TASK-1)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication

from workflow_app.metrics_bar.metrics_bar import MetricsBar


@pytest.fixture()
def bar(qapp):
    bus = MagicMock()
    return MetricsBar(bus)


# ── Initial state ────────────────────────────────────────────────────────── #


def test_prefs_btn_enabled_on_init(bar):
    """Preferences button is enabled on init."""
    assert bar._btn_prefs.isEnabled() is True


def test_tokens_label_hidden_on_init(bar):
    """Token label is hidden until tokens arrive."""
    assert bar._lbl_tokens.isHidden()


def test_errors_badge_hidden_on_init(bar):
    """Error badge is hidden until errors occur."""
    assert bar._lbl_errors.isHidden()


def test_height_is_48px(bar):
    assert bar.height() == 48


# ── set_progress_text (backward-compat stub) ─────────────────────────────── #


def test_set_progress_text_no_crash(bar):
    """set_progress_text is a no-op stub — must not crash."""
    bar.set_progress_text(3, 10)
    bar.set_progress_text(0, 0)


def test_set_progress_text_any_values(bar):
    """set_progress_text accepts any integers without error."""
    bar.set_progress_text(100, 100)


# ── set_elapsed_text (backward-compat stub) ──────────────────────────────── #


def test_set_elapsed_text_no_crash(bar):
    """set_elapsed_text is a no-op stub — must not crash."""
    bar.set_elapsed_text("01:23:45")


def test_set_elapsed_text_empty_no_crash(bar):
    """set_elapsed_text with empty string does not crash."""
    bar.set_elapsed_text("")


# ── set_tokens_text ──────────────────────────────────────────────────────── #


def test_set_tokens_text_updates_and_shows(bar):
    bar.set_tokens_text("↑5k ↓2k $0.05")
    assert bar._lbl_tokens.text() == "↑5k ↓2k $0.05"
    assert not bar._lbl_tokens.isHidden()


# ── set_errors_badge ─────────────────────────────────────────────────────── #


def test_set_errors_badge_nonzero_shows(bar):
    bar.set_errors_badge(2)
    assert not bar._lbl_errors.isHidden()
    assert "2" in bar._lbl_errors.text()


def test_set_errors_badge_zero_hides(bar):
    bar.set_errors_badge(3)
    bar.set_errors_badge(0)
    assert bar._lbl_errors.isHidden()


# ── set_estimate_text (backward-compat stub) ─────────────────────────────── #


def test_set_estimate_text_no_crash(bar):
    """set_estimate_text is a no-op stub — must not crash."""
    bar.set_estimate_text("~5 min restantes")
    bar.set_estimate_text("")


# ────────────────────────────────── _on_metrics_snapshot (GAP-005) ─── #


class TestMetricsBarSnapshotHandlers:
    """_on_metrics_snapshot updates token/error widgets."""

    def test_snapshot_no_crash_on_progress(self, bar):
        from workflow_app.core.metrics_timer import MetricsSnapshot
        snap = MetricsSnapshot(total_commands=10, completed_commands=4, error_commands=0)
        bar._on_metrics_snapshot(snap)  # must not raise

    def test_snapshot_shows_error_badge(self, bar):
        from workflow_app.core.metrics_timer import MetricsSnapshot
        snap = MetricsSnapshot(total_commands=10, completed_commands=3, error_commands=2)
        bar._on_metrics_snapshot(snap)
        assert not bar._lbl_errors.isHidden()
        assert "2 erros" in bar._lbl_errors.text()

    def test_snapshot_hides_error_badge_when_zero(self, bar):
        from workflow_app.core.metrics_timer import MetricsSnapshot
        bar.set_errors_badge(1)
        snap = MetricsSnapshot(total_commands=5, completed_commands=2, error_commands=0)
        bar._on_metrics_snapshot(snap)
        assert bar._lbl_errors.isHidden()

    def test_snapshot_shows_token_label_when_nonzero(self, bar):
        from workflow_app.core.metrics_timer import MetricsSnapshot
        snap = MetricsSnapshot(
            total_commands=5, completed_commands=2,
            tokens_input=5000, tokens_output=2000, cost_estimate_usd=0.05,
        )
        bar._on_metrics_snapshot(snap)
        assert not bar._lbl_tokens.isHidden()
        assert "↑5k" in bar._lbl_tokens.text()

    def test_snapshot_does_not_show_token_label_when_zero(self, bar):
        from workflow_app.core.metrics_timer import MetricsSnapshot
        snap = MetricsSnapshot(total_commands=5, completed_commands=2,
                               tokens_input=0, tokens_output=0)
        bar._on_metrics_snapshot(snap)
        assert bar._lbl_tokens.isHidden()

    def test_multiple_snapshots_accumulate_errors(self, bar):
        from workflow_app.core.metrics_timer import MetricsSnapshot
        snap1 = MetricsSnapshot(total_commands=5, completed_commands=1, error_commands=1)
        snap2 = MetricsSnapshot(total_commands=5, completed_commands=2, error_commands=3)
        bar._on_metrics_snapshot(snap1)
        bar._on_metrics_snapshot(snap2)
        assert "3 erros" in bar._lbl_errors.text()

    def test_snapshot_no_crash_minimal(self, bar):
        from workflow_app.core.metrics_timer import MetricsSnapshot
        bar._on_metrics_snapshot(MetricsSnapshot())

    def test_snapshot_resume_clears_errors(self, bar):
        from workflow_app.core.metrics_timer import MetricsSnapshot
        bar.set_errors_badge(5)
        snap = MetricsSnapshot(total_commands=10, error_commands=0)
        bar._on_metrics_snapshot(snap)
        assert bar._lbl_errors.isHidden()

    def test_snapshot_zero_tokens_keeps_label_hidden(self, bar):
        from workflow_app.core.metrics_timer import MetricsSnapshot
        snap = MetricsSnapshot(total_commands=1, tokens_input=0, tokens_output=0)
        bar._on_metrics_snapshot(snap)
        assert bar._lbl_tokens.isHidden()


# ─────────────────────────── _on_token_update (GAP-006) ─── #


class TestMetricsBarTokenUpdate:
    """_on_token_update formats and displays token counts."""

    def test_formats_thousands(self, bar):
        bar._on_token_update(5000, 2000, 0.05)
        assert "↑5k" in bar._lbl_tokens.text()
        assert "↓2k" in bar._lbl_tokens.text()

    def test_formats_small_values(self, bar):
        bar._on_token_update(500, 200, 0.01)
        assert "↑500" in bar._lbl_tokens.text()
        assert "↓200" in bar._lbl_tokens.text()

    def test_includes_cost(self, bar):
        bar._on_token_update(1000, 500, 0.07)
        assert "$0.07" in bar._lbl_tokens.text()

    def test_shows_label(self, bar):
        bar._on_token_update(100, 50, 0.01)
        assert not bar._lbl_tokens.isHidden()

    def test_zero_cost(self, bar):
        bar._on_token_update(0, 0, 0.0)
        assert "$0.00" in bar._lbl_tokens.text()


# ──────────────────────────────── nav buttons ─── #


class TestMetricsBarNavButtons:
    """Navigation buttons exist, are enabled, and have text."""

    def test_btn_workflow_exists(self, bar):
        assert hasattr(bar, "_btn_workflow")
        assert bar._btn_workflow.isEnabled()

    def test_btn_comandos_exists(self, bar):
        assert hasattr(bar, "_btn_comandos")
        assert bar._btn_comandos.isEnabled()

    def test_btn_toolbox_exists(self, bar):
        assert hasattr(bar, "_btn_toolbox")
        assert bar._btn_toolbox.isEnabled()


# ──────────────────────── tool_use handlers (GAP-007) ─── #


class TestMetricsBarToolUse:
    """_on_tool_use_started/completed update counter and tooltip (GAP-007 fix)."""

    def test_tool_use_started_increments_count(self, bar):
        bar._on_tool_use_started("Read")
        assert bar._tool_use_count == 1
        assert "Tools: 1" in bar._tool_use_label.text()
        assert not bar._tool_use_label.isHidden()

    def test_tool_use_started_accumulates(self, bar):
        bar._on_tool_use_started("Read")
        bar._on_tool_use_started("Write")
        assert bar._tool_use_count == 2

    def test_tool_use_completed_sets_tooltip(self, bar):
        bar._on_tool_use_completed("Read", 150)
        assert "Read" in bar._tool_use_label.toolTip()
        assert "150" in bar._tool_use_label.toolTip()


# ──────────────────────── signal bus wiring ─── #


class TestMetricsBarSignalWiring:
    """Signal bus is stored and tool_use count starts at 0."""

    def test_tool_use_count_starts_zero(self, bar):
        assert bar._tool_use_count == 0

    def test_signal_bus_stored(self, bar):
        assert bar._signal_bus is not None


# ──────────────────── Remote feedback: copy/badge (module-5 audit) ─── #


class TestMetricsBarRemoteFeedback:
    """Copy IP, connection badge and remote server handlers (module-5 audit)."""

    def test_on_remote_server_started_shows_addr_and_button(self, bar):
        bar._on_remote_server_started("100.64.1.2:8765")
        assert bar._lbl_remote_addr.text() == "100.64.1.2:8765"
        assert not bar._lbl_remote_addr.isHidden()
        assert not bar._btn_copy_ip.isHidden()
        assert bar._btn_remote.isChecked()

    def test_on_remote_server_stopped_hides_all(self, bar):
        bar._on_remote_server_started("100.64.1.2:8765")
        bar._on_remote_client_connected()
        bar._on_remote_server_stopped()
        assert not bar._lbl_remote_addr.isVisible()
        assert not bar._btn_copy_ip.isVisible()
        assert not bar._lbl_connection_badge.isVisible()
        assert not bar._btn_remote.isChecked()

    def test_on_remote_client_connected_shows_badge(self, bar):
        bar._on_remote_client_connected()
        assert not bar._lbl_connection_badge.isHidden()

    def test_on_remote_client_disconnected_hides_badge(self, bar):
        bar._on_remote_client_connected()
        bar._on_remote_client_disconnected()
        assert not bar._lbl_connection_badge.isVisible()

    def test_on_copy_ip_copies_to_clipboard(self, bar, qapp):
        bar._on_remote_server_started("100.64.1.2:8765")
        bar._on_copy_ip()
        assert QApplication.clipboard().text() == "100.64.1.2:8765"

    def test_on_copy_ip_shows_feedback(self, bar):
        bar._on_remote_server_started("100.64.1.2:8765")
        bar._on_copy_ip()
        assert bar._btn_copy_ip.text() == "✓"
        assert bar._btn_copy_ip.toolTip() == "Copiado!"

    def test_on_remote_toggled_off_hides_widgets(self, bar):
        bar._on_remote_server_started("100.64.1.2:8765")
        bar._on_remote_toggled(False)
        assert not bar._lbl_remote_addr.isVisible()
        assert not bar._btn_copy_ip.isVisible()
        assert not bar._lbl_connection_badge.isVisible()

    def test_copy_ip_noop_when_empty(self, bar, qapp):
        """Copy does nothing when address label is empty."""
        QApplication.clipboard().setText("previous")
        bar._on_copy_ip()
        assert QApplication.clipboard().text() == "previous"
