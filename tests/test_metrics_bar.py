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


# ──────────────────────────────── project pill ─── #


class TestMetricsBarProjectPill:
    """Project pill shows/hides correctly including the red X button.

    Note: isVisible() requires the full widget hierarchy to be on-screen.
    In unit tests the MetricsBar is never shown, so we use isHidden() which
    checks only whether the widget itself was explicitly hidden/shown.
    """

    def test_proj_x_not_hidden_after_project_loaded(self, bar):
        bar._apply_project_loaded("my-project")
        assert not bar._proj_x.isHidden()

    def test_project_pill_not_hidden_after_project_loaded(self, bar):
        bar._apply_project_loaded("my-project")
        assert not bar._project_pill.isHidden()

    def test_proj_select_btn_hidden_after_project_loaded(self, bar):
        bar._apply_project_loaded("my-project")
        assert bar._proj_select_btn.isHidden()

    def test_project_name_label_shows_name(self, bar):
        bar._apply_project_loaded("ai-forge")
        assert bar._project_name_lbl.text() == "ai-forge"
        assert not bar._project_name_lbl.isHidden()

    def test_project_pill_hidden_after_empty(self, bar):
        bar._apply_project_loaded("my-project")
        bar._apply_project_empty()
        assert bar._project_pill.isHidden()

    def test_proj_select_btn_not_hidden_after_empty(self, bar):
        bar._apply_project_loaded("my-project")
        bar._apply_project_empty()
        assert not bar._proj_select_btn.isHidden()

    def test_proj_x_not_hidden_after_reload(self, bar):
        """X stays not-hidden when a second project is loaded (regression guard)."""
        bar._apply_project_loaded("first-project")
        bar._apply_project_empty()
        bar._apply_project_loaded("second-project")
        assert not bar._proj_x.isHidden()


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

# ──────────────────────── Authoritative idle lock (GAP-fix) ─── #


class TestMetricsBarAuthoritativeIdle:
    """Lock-based idle suppression for TUIs with continuous repaint (Rich, etc.)."""

    def test_enter_authoritative_idle_sets_green_and_lock(self, bar):
        bar._enter_authoritative_idle("workspace")
        assert bar._idle_locked["workspace"] is True
        assert bar._dot_workspace._busy is False

    def test_enter_authoritative_idle_stops_hardening_timer(self, bar):
        bar._idle_timer_workspace.start()
        assert bar._idle_timer_workspace.isActive()
        bar._enter_authoritative_idle("workspace")
        assert not bar._idle_timer_workspace.isActive()

    def test_terminal_activity_ignored_when_locked(self, bar):
        bar._enter_authoritative_idle("workspace")
        bar._dot_workspace.set_busy(False)
        bar._on_terminal_activity("workspace")
        assert bar._dot_workspace._busy is False

    def test_release_idle_lock_allows_activity_to_turn_yellow(self, bar):
        bar._enter_authoritative_idle("workspace")
        bar._release_idle_lock("workspace")
        bar._on_terminal_activity("workspace")
        assert bar._dot_workspace._busy is True

    def test_terminal_session_started_releases_lock(self, bar):
        bar._enter_authoritative_idle("workspace")
        bar._on_terminal_session_started("workspace")
        assert bar._idle_locked["workspace"] is False
        assert bar._dot_workspace._busy is True

    def test_run_command_in_workspace_terminal_releases_lock(self, qapp):
        from workflow_app.signal_bus import SignalBus
        bus = SignalBus()
        mb = MetricsBar(bus)
        mb._enter_authoritative_idle("workspace")
        bus.run_command_in_workspace_terminal.emit("/skill:test")
        assert mb._idle_locked["workspace"] is False

    def test_run_command_in_terminal_releases_lock(self, qapp):
        from workflow_app.signal_bus import SignalBus
        bus = SignalBus()
        mb = MetricsBar(bus)
        mb._enter_authoritative_idle("interactive")
        bus.run_command_in_terminal.emit("/skill:test")
        assert mb._idle_locked["interactive"] is False

    def test_lock_persists_until_actual_dispatch(self, bar):
        """Lock must NOT auto-release on a timer — green-by-default semantics
        means the dot stays green until the user actually dispatches a
        command. The legacy 30s TTL was removed because it opened a window
        where ambient PTY clicks (Kimi mouse-click repaints) could flip the
        dot yellow incorrectly.
        """
        bar._enter_authoritative_idle("workspace")
        assert bar._idle_locked["workspace"] is True
        # No TTL timer should be created any more
        assert "workspace" not in bar._idle_lock_ttl

    def test_lock_is_true_by_default_at_startup(self, bar):
        """Green-by-default: at startup the dot is locked so ambient PTY
        chunks (e.g. Kimi mouse-click repaints) don't flip it yellow.
        """
        assert bar._idle_locked["workspace"] is True
        assert bar._idle_locked["interactive"] is True
        assert bar._dot_workspace._busy is False
        assert bar._dot_interactive._busy is False

    def test_click_at_startup_does_not_flip_dot_yellow(self, bar):
        """Clicking the Kimi terminal generates an ANSI repaint chunk that
        reaches `_on_terminal_activity`. With lock=True at rest, that chunk
        must be ignored and the dot stays green. Reproduces the bug where
        clicking Kimi flipped the dot yellow even with no command running.
        """
        bar._on_terminal_activity("workspace")
        assert bar._dot_workspace._busy is False
        assert bar._idle_locked["workspace"] is True

    # ── Hardening phase (post-notify streaming absorption) ───────────── #

    def test_arm_hardening_keeps_dot_yellow_and_starts_soft_timer(self, bar):
        """Notify file accepted (after dispatch released the lock) → dot
        stays YELLOW; soft 3s timer armed. The dot only goes green after
        the soft timer expires (3s of true PTY silence). No hardcap —
        if chunks never stop, dot stays yellow indefinitely (correct).
        """
        bar._release_idle_lock("workspace")
        bar._dot_workspace.set_busy(True)
        bar._arm_hardening("workspace")
        assert bar._dot_workspace._busy is True
        assert bar._idle_locked["workspace"] is False
        assert bar._idle_timer_workspace.isActive()

    def test_hardening_soft_timer_promotes_to_locked_idle(self, bar):
        """Soft 3s timer expiry → green + lock."""
        bar._release_idle_lock("workspace")
        bar._arm_hardening("workspace")
        bar._idle_timer_workspace.timeout.emit()
        assert bar._dot_workspace._busy is False
        assert bar._idle_locked["workspace"] is True

    def test_continuous_chunks_keep_dot_yellow_indefinitely(self, bar):
        """No hardcap by design: if chunks never stop, dot stays yellow.

        Contract: "if there's activity on the terminal, the dot does NOT
        turn green". A CLI that emits PTY bytes forever (e.g. Live status
        display, animated prompt) keeps the dot yellow indefinitely.
        """
        bar._release_idle_lock("workspace")
        bar._arm_hardening("workspace")
        # Simulate continuous chunks resetting the soft timer
        for _ in range(10):
            bar._on_terminal_activity("workspace")
        assert bar._dot_workspace._busy is True
        assert bar._idle_locked["workspace"] is False
        assert bar._idle_timer_workspace.isActive()  # still counting

    def test_command_during_hardening_cancels_soft_timer(self, qapp):
        """New command dispatched mid-hardening → soft canceled.

        Otherwise a stale hardening would promote to lock while a new
        command is actually running.
        """
        from workflow_app.signal_bus import SignalBus
        bus = SignalBus()
        mb = MetricsBar(bus)
        mb._release_idle_lock("workspace")
        mb._arm_hardening("workspace")
        assert mb._idle_timer_workspace.isActive()
        bus.run_command_in_workspace_terminal.emit("/skill:next")
        assert not mb._idle_timer_workspace.isActive()

    def test_redundant_arm_hardening_while_locked_is_noop(self, bar):
        """Notify arriving while already locked (e.g. stray notify with no
        prior dispatch) is a no-op: soft stays stopped, lock stays True."""
        bar._enter_authoritative_idle("workspace")
        assert bar._idle_locked["workspace"] is True
        bar._arm_hardening("workspace")
        assert not bar._idle_timer_workspace.isActive()
        assert bar._idle_locked["workspace"] is True

    # ── Race regressions (Codex MCP review findings) ─────────────────── #

    def test_stale_notify_after_new_command_is_rejected(self, qapp, tmp_path):
        """BLOCKER fix: notify with iat older than command epoch is dropped.

        Repro of the A/B race: command A writes notify, command B is
        dispatched before the watcher processes A's file. Without the epoch
        fence, A's late notify would re-lock the dot while B is running.
        """
        import json
        import time
        from workflow_app.signal_bus import SignalBus
        bus = SignalBus()
        mb = MetricsBar(bus)
        # Command B dispatched at time T → epoch = T
        bus.run_command_in_workspace_terminal.emit("/skill:command-b")
        epoch_after_b = mb._command_epoch["workspace"]
        assert epoch_after_b > 0
        # Stale notify from command A (iat predates B's epoch)
        notify_path = mb._notify_files["workspace"]
        notify_path.write_text(json.dumps({
            "channel": "workspace",
            "state": "idle",
            "iat": epoch_after_b - 1.0,
            "exp": time.time() + 10.0,
        }))
        mb._on_notify_file_changed(str(notify_path))
        # Lock must NOT have been re-entered
        assert mb._idle_locked["workspace"] is False

    def test_notify_during_external_session_is_ignored(self, bar, tmp_path):
        """MAJOR fix: authoritative notify during a runner-backed session
        must not seize ownership of the dot from terminal_session_*."""
        import json
        import time
        bar._on_terminal_session_started("workspace")
        assert bar._session_active["workspace"] is True
        notify_path = bar._notify_files["workspace"]
        notify_path.write_text(json.dumps({
            "channel": "workspace",
            "state": "idle",
            "iat": time.time(),
            "exp": time.time() + 10.0,
        }))
        bar._on_notify_file_changed(str(notify_path))
        # Session still owns the dot — lock must stay released, dot busy
        assert bar._idle_locked["workspace"] is False
        assert bar._dot_workspace._busy is True

    def test_notify_at_epoch_boundary_is_rejected(self, qapp):
        """Same-tick equality (iat == epoch) must reject the notify.

        With `<` comparison this would slip through and re-lock the dot.
        Codex review (round 2) flagged the boundary; fence uses `<=`.
        """
        import json
        import time
        from workflow_app.signal_bus import SignalBus
        bus = SignalBus()
        mb = MetricsBar(bus)
        bus.run_command_in_workspace_terminal.emit("/skill:cmd")
        epoch = mb._command_epoch["workspace"]
        notify_path = mb._notify_files["workspace"]
        notify_path.write_text(json.dumps({
            "channel": "workspace",
            "state": "idle",
            "iat": epoch,  # exactly at boundary
            "exp": time.time() + 10.0,
        }))
        mb._on_notify_file_changed(str(notify_path))
        assert mb._idle_locked["workspace"] is False

    # ── Helper-command auto-idle (/model, /effort, /clear) ───────────── #

    def test_is_helper_command_recognizes_helpers(self, bar):
        assert bar._is_helper_command("/model opus") is True
        assert bar._is_helper_command("/effort high") is True
        assert bar._is_helper_command("/clear") is True
        assert bar._is_helper_command("/MODEL OPUS") is True  # case-insensitive
        assert bar._is_helper_command("/skill:test") is False
        assert bar._is_helper_command("/qa:trace --module 1") is False
        assert bar._is_helper_command("") is False
        assert bar._is_helper_command("   ") is False

    def test_helper_auto_idle_arms_hardening(self, qapp):
        """Helper dispatched → after 1s auto-idle the soft hardening timer
        is armed (NOT a direct flip to green). Lock only flips after soft
        expires from 3s of true PTY silence — preserves the contract
        "if there's activity, the dot does NOT turn green".
        """
        from workflow_app.signal_bus import SignalBus
        bus = SignalBus()
        mb = MetricsBar(bus)
        bus.run_command_in_terminal.emit("/clear")
        assert mb._idle_locked["interactive"] is False
        scheduled_epoch = mb._command_epoch["interactive"]
        mb._helper_auto_idle("interactive", scheduled_epoch)
        # Soft timer must be armed but lock not yet flipped
        assert mb._idle_timer_interactive.isActive()
        assert mb._idle_locked["interactive"] is False
        # Now simulate 3s of silence: soft fires → green + lock
        mb._idle_timer_interactive.timeout.emit()
        assert mb._idle_locked["interactive"] is True
        assert mb._dot_interactive._busy is False

    def test_helper_auto_idle_skipped_when_newer_command_dispatched(self, qapp):
        """Race: /clear at t=0, real command at t=0.5 → /clear's auto-idle at
        t=1 must NOT flip the dot green over the running real command."""
        import time
        from workflow_app.signal_bus import SignalBus
        bus = SignalBus()
        mb = MetricsBar(bus)
        # Helper dispatched, schedule captures epoch_a
        bus.run_command_in_terminal.emit("/clear")
        epoch_a = mb._command_epoch["interactive"]
        # Real command dispatched a bit later → epoch advances
        time.sleep(0.01)
        bus.run_command_in_terminal.emit("/skill:long-task")
        # Late auto-idle from /clear must drop because epoch_a < current
        mb._helper_auto_idle("interactive", epoch_a)
        assert mb._idle_locked["interactive"] is False
        # Dot should NOT have been forced green by the stale auto-idle

    def test_non_helper_command_does_not_schedule_auto_idle(self, bar):
        """Real commands rely on their notify file — no auto-idle scheduled."""
        # We can't easily detect a non-scheduled QTimer.singleShot from the
        # outside, so we verify the gate function directly.
        bar._maybe_schedule_helper_auto_idle("interactive", "/skill:qa:trace")
        # Lock state should remain whatever it was (not forced)
        assert bar._idle_locked["interactive"] is True  # default

    def test_clear_via_use_kimi_dispatches_to_both_channels(self, qapp):
        """/clear with Use Kimi checked → emits to both interactive AND
        workspace, each releasing its own lock and arming hardening
        independently after 1s helper auto-idle + 3s silence."""
        from workflow_app.signal_bus import SignalBus
        bus = SignalBus()
        mb = MetricsBar(bus)
        assert mb._idle_locked["interactive"] is True
        assert mb._idle_locked["workspace"] is True
        bus.run_command_in_terminal.emit("/clear")
        bus.run_command_in_workspace_terminal.emit("/clear")
        assert mb._idle_locked["interactive"] is False
        assert mb._idle_locked["workspace"] is False
        # Helper auto-idle arms hardening on both (1s post-dispatch)
        mb._helper_auto_idle("interactive", mb._command_epoch["interactive"])
        mb._helper_auto_idle("workspace", mb._command_epoch["workspace"])
        assert mb._idle_timer_interactive.isActive()
        assert mb._idle_timer_workspace.isActive()
        # Soft expires (3s of silence) on both → green + lock
        mb._idle_timer_interactive.timeout.emit()
        mb._idle_timer_workspace.timeout.emit()
        assert mb._idle_locked["interactive"] is True
        assert mb._idle_locked["workspace"] is True

    # ── Hardening timing (Bug 2: messages still flowing after green) ─── #

    def test_soft_hardening_window_is_3_seconds(self, bar):
        """Single 3s window of true PTY silence after notify → green.
        Resets on every chunk while active."""
        assert bar._idle_timer_workspace.interval() == 3_000
        assert bar._idle_timer_interactive.interval() == 3_000

    def test_workspace_notify_uses_5s_timeout_not_hardening(self, qapp, tmp_path):
        """Workspace skills bypass hardening: notify file arrival schedules
        a fixed 5s timer to green. Avoids Kimi's never-quiet TUI bug."""
        import json, time
        from workflow_app.signal_bus import SignalBus
        bus = SignalBus()
        mb = MetricsBar(bus)
        # Simulate dispatch then notify
        bus.run_command_in_workspace_terminal.emit("/skill:test")
        notify_path = mb._notify_files["workspace"]
        notify_path.write_text(json.dumps({
            "channel": "workspace",
            "state": "idle",
            "iat": time.time(),
            "exp": time.time() + 10.0,
        }))
        mb._on_notify_file_changed(str(notify_path))
        # Soft hardening timer must NOT be armed for workspace
        assert not mb._idle_timer_workspace.isActive(), (
            "Workspace skills must bypass the chunk-watching soft timer"
        )
        # 5s post-notify timer must be armed via hardcap slot
        cap = mb._hardcap_timer.get("workspace")
        assert cap is not None and cap.isActive()
        assert cap.interval() == 5_000

    def test_interactive_skills_use_strict_hardening_no_hardcap(self, qapp, tmp_path):
        """Interactive (Claude Code) keeps the strict contract: 3s soft
        timer only, no hardcap. Claude goes truly silent at its prompt
        so soft fires reliably on its own — no extrapolation needed."""
        import json, time
        from workflow_app.signal_bus import SignalBus
        bus = SignalBus()
        mb = MetricsBar(bus)
        bus.run_command_in_terminal.emit("/skill:test")
        notify_path = mb._notify_files["interactive"]
        notify_path.write_text(json.dumps({
            "channel": "interactive",
            "state": "idle",
            "iat": time.time(),
            "exp": time.time() + 10.0,
        }))
        mb._on_notify_file_changed(str(notify_path))
        # Soft 3s armed
        assert mb._idle_timer_interactive.isActive()
        assert mb._idle_timer_interactive.interval() == 3_000
        # No hardcap entry created — strict contract preserved
        assert "interactive" not in mb._hardcap_timer

    def test_arm_hardening_without_hardcap_leaves_no_cap(self, bar):
        """Calling _arm_hardening with default hardcap_ms=None creates no
        hardcap entry — used for backward-compat calls only."""
        bar._release_idle_lock("workspace")
        bar._arm_hardening("workspace")
        assert bar._idle_timer_workspace.isActive()
        assert "workspace" not in bar._hardcap_timer

    def test_helpers_arm_with_5s_hardcap(self, bar):
        """Helpers arm hardening WITH 5s hardcap so even Kimi's invisible
        cursor/CPR chunks can't keep the dot yellow forever."""
        bar._release_idle_lock("workspace")
        bar._arm_hardening("workspace", hardcap_ms=bar._HELPER_HARDCAP_MS)
        assert bar._idle_timer_workspace.isActive()
        cap = bar._hardcap_timer.get("workspace")
        assert cap is not None
        assert cap.isActive()
        assert cap.interval() == 5_000

    def test_helper_hardcap_promotes_to_locked_idle_under_constant_chunks(self, bar):
        """Repro of Kimi's "yellow forever" bug: chunks keep arriving
        (invisible) and reset the soft timer endlessly. The hardcap
        eventually fires and forces green."""
        bar._release_idle_lock("workspace")
        bar._arm_hardening("workspace", hardcap_ms=5_000)
        # Continuous chunks reset soft but NOT hardcap
        for _ in range(10):
            bar._on_terminal_activity("workspace")
        assert bar._dot_workspace._busy is True
        assert bar._idle_locked["workspace"] is False
        # Fire hardcap directly
        bar._hardcap_timer["workspace"].timeout.emit()
        assert bar._idle_locked["workspace"] is True
        assert bar._dot_workspace._busy is False

    def test_clear_workspace_extra_delay_constant(self, bar):
        """/clear on workspace adds +1s extra to the helper auto-idle
        delay (Kimi TUI repaint takes longer than a regular helper)."""
        assert bar._HELPER_AUTO_IDLE_MS == 1_000
        assert bar._CLEAR_WORKSPACE_EXTRA_MS == 1_000

    def test_dispatch_forces_dot_yellow_immediately(self, qapp):
        """Bug repro: Kimi processes /clear silently (no PTY output), so
        without forcing yellow on dispatch the dot would never flip from
        green to yellow and the user would have no UI confirmation that
        the command was dispatched.
        """
        from workflow_app.signal_bus import SignalBus
        bus = SignalBus()
        mb = MetricsBar(bus)
        # Both dots start green (lock=True default)
        assert mb._dot_workspace._busy is False
        assert mb._dot_interactive._busy is False
        # Dispatch must flip both yellow synchronously
        bus.run_command_in_workspace_terminal.emit("/clear")
        assert mb._dot_workspace._busy is True, (
            "Workspace dispatch must force dot yellow synchronously, even "
            "if the CLI processes the command silently (no PTY chunks)."
        )
        bus.run_command_in_terminal.emit("/clear")
        assert mb._dot_interactive._busy is True

    def test_terminal_activity_alone_does_not_arm_soft_timer(self, bar):
        """Bug repro guard: long bash with intra-command sleeps would
        previously fire `terminal_force_idle` from PTY silence, arming the
        soft timer and locking the dot green mid-command.

        Now `terminal_activity` (chunk arrival) on its own must NOT arm
        the soft timer — only `_arm_hardening` (notify file path) can.
        """
        bar._release_idle_lock("workspace")
        # Simulate many chunks arriving via terminal_activity
        for _ in range(5):
            bar._on_terminal_activity("workspace")
        assert bar._dot_workspace._busy is True
        assert not bar._idle_timer_workspace.isActive(), (
            "terminal_activity alone must not arm the soft timer. "
            "Hardening only engages via notify file (_arm_hardening)."
        )

    def test_kimi_blue_arrow_bumps_workspace_epoch(self, qapp):
        """Bug repro: /clear (mirror) schedules workspace auto-idle@1s with
        scheduled_epoch=A. Blue arrow on a real command must bump the
        workspace epoch, otherwise the auto-idle fires mid-command and
        locks the dot green while Kimi is still streaming.
        """
        from workflow_app.signal_bus import SignalBus
        bus = SignalBus()
        mb = MetricsBar(bus)
        # Step 1: /clear mirror schedules workspace auto-idle
        bus.run_command_in_workspace_terminal.emit("/clear")
        epoch_after_clear = mb._command_epoch["workspace"]
        # Step 2: blue-arrow Kimi dispatch fires
        bus.kimi_blue_arrow_dispatched.emit("/skill:test-autoflow-auto", 1000)
        epoch_after_kimi = mb._command_epoch["workspace"]
        assert epoch_after_kimi > epoch_after_clear, (
            "Blue arrow must bump the workspace epoch. Without this, the "
            "/clear auto-idle scheduled before would fire mid-Kimi-command "
            "and lock the dot green prematurely."
        )
        # Step 3: simulate the late /clear auto-idle firing
        mb._helper_auto_idle("workspace", epoch_after_clear)
        # Lock must NOT have flipped (epoch advanced) — late helper drops
        assert mb._idle_locked["workspace"] is False
        # Dot is yellow because dispatch forces it yellow now (UX feedback)
        assert mb._dot_workspace._busy is True

    def test_command_epoch_never_decreases(self, bar):
        """Backward NTP step must not reset the fence below older iat values.

        `_bump_command_epoch` clamps via max() so a clock that jumps backward
        cannot let a stale notify slip past the fence.
        """
        bar._command_epoch["workspace"] = 1_000_000.0  # simulate previous bump
        # Simulate clock going backward: bump should keep the older value
        import time as _time
        # Patch time.time temporarily
        original = _time.time
        try:
            _time.time = lambda: 999_999.0  # earlier than stored epoch
            bar._bump_command_epoch("workspace")
            assert bar._command_epoch["workspace"] == 1_000_000.0
        finally:
            _time.time = original

    def test_cross_channel_lock_isolation(self, bar):
        """Releasing one channel's lock must not affect the other."""
        # Both start locked (green-by-default)
        assert bar._idle_locked["workspace"] is True
        assert bar._idle_locked["interactive"] is True
        # Release only interactive (simulate dispatch on that channel)
        bar._release_idle_lock("interactive")
        assert bar._idle_locked["interactive"] is False
        assert bar._idle_locked["workspace"] is True
        # Activity on interactive flips its dot yellow
        bar._on_terminal_activity("interactive")
        assert bar._dot_interactive._busy is True
        # Activity on workspace is still suppressed by its lock
        bar._dot_workspace.set_busy(False)
        bar._on_terminal_activity("workspace")
        assert bar._dot_workspace._busy is False
