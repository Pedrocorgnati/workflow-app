"""Tests for MetricsBar shell (module-13/TASK-1)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QApplication

from workflow_app.config.app_state import app_state
from workflow_app.config.config_parser import PipelineConfig
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


def test_height_is_38px(bar):
    assert bar.height() == 38


def test_codex_instance_button_launches_codex_high(bar):
    bar._on_instance_clicked(0, "codex")

    bar._signal_bus.instance_selected.emit.assert_called_with("codex")
    bar._signal_bus.run_command_in_workspace_xterm.emit.assert_called_with("codex-high")
    bar._signal_bus.run_command_in_terminal.emit.assert_not_called()
    bar._signal_bus.run_command_in_workspace_terminal.emit.assert_not_called()


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

    def test_proj_refresh_not_hidden_after_project_loaded(self, bar):
        bar._apply_project_loaded("my-project")
        assert not bar._proj_refresh.isHidden()

    def test_proj_x_uses_red_style(self, bar):
        assert "#EF4444" in bar._proj_x.styleSheet()

    def test_proj_refresh_emits_active_config_path(self, bar, tmp_path):
        config_path = str(tmp_path / "project.json")
        emitted: list[str] = []
        bar.config_reload_requested.connect(emitted.append)
        app_state.set_config(
            PipelineConfig(
                config_path=config_path,
                project_name="my-project",
                brief_root="brief",
                docs_root="docs",
                wbs_root="wbs",
                workspace_root="workspace",
            )
        )
        try:
            bar._on_proj_refresh()
        finally:
            app_state.clear_config()
        assert emitted == [config_path]

    def test_proj_refresh_does_not_reload_loop_slot(self, bar, tmp_path):
        loop_path = str(tmp_path / "_LOOP-CONFIG.json")
        emitted: list[str] = []
        bar.config_reload_requested.connect(emitted.append)
        app_state.clear_all()
        app_state.set_loop_config(
            PipelineConfig(
                config_path=loop_path,
                project_name="loop",
                brief_root="",
                docs_root="",
                wbs_root="",
                workspace_root="",
            )
        )
        try:
            bar._on_proj_refresh()
        finally:
            app_state.clear_all()
        assert emitted == []

    def test_project_pill_not_hidden_after_project_loaded(self, bar):
        bar._apply_project_loaded("my-project")
        assert not bar._project_pill.isHidden()

    def test_proj_select_btn_hidden_after_project_loaded(self, bar):
        bar._apply_project_loaded("my-project")
        assert bar._proj_select_btn.isHidden()

    def test_proj_select_emits_project_config_change_requested(self, bar, tmp_path):
        config_path = tmp_path / "project.json"
        config_path.write_text("{}")
        emitted_project: list[str] = []
        emitted_config: list[str] = []
        emitted_loop: list[str] = []
        bar.project_config_change_requested.connect(emitted_project.append)
        bar.config_change_requested.connect(emitted_config.append)
        bar.loop_config_change_requested.connect(emitted_loop.append)

        with patch(
            "workflow_app.metrics_bar.metrics_bar.QFileDialog.getOpenFileName",
            return_value=(str(config_path), ""),
        ):
            bar._on_proj_select()

        assert emitted_project == [str(config_path)]
        assert emitted_loop == []
        # Compat bridge ainda dispara para integração legada.
        assert emitted_config == [str(config_path)]

    def test_project_picker_with_loop_only_starts_in_project_fallback(self, bar, tmp_path):
        loop_path = tmp_path / "blacksmith" / "loop" / "_LOOP-CONFIG.json"
        projects_dir = tmp_path / ".claude" / "projects"
        selected_project = projects_dir / "project.json"
        loop_path.parent.mkdir(parents=True)
        projects_dir.mkdir(parents=True)
        loop_path.write_text("{}", encoding="utf-8")
        selected_project.write_text("{}", encoding="utf-8")
        app_state.clear_all()
        app_state.set_loop_config(
            PipelineConfig(
                config_path=str(loop_path),
                project_name="loop",
                brief_root="",
                docs_root="",
                wbs_root="",
                workspace_root="",
            )
        )
        captured_start_dirs: list[str] = []

        def fake_dialog(parent, title, start_dir, file_filter):
            captured_start_dirs.append(start_dir)
            return (str(selected_project), "")

        with patch.object(bar, "_resolve_walk_up", return_value=str(projects_dir)):
            with patch(
                "workflow_app.metrics_bar.metrics_bar.QFileDialog.getOpenFileName",
                side_effect=fake_dialog,
            ):
                try:
                    bar._on_proj_select()
                finally:
                    app_state.clear_all()

        assert captured_start_dirs == [str(projects_dir)]

    def test_project_picker_with_project_and_loop_starts_in_project_dir(self, bar, tmp_path):
        project_path = tmp_path / "project" / ".claude" / "project.json"
        loop_path = tmp_path / "blacksmith" / "loop" / "_LOOP-CONFIG.json"
        project_path.parent.mkdir(parents=True)
        loop_path.parent.mkdir(parents=True)
        project_path.write_text("{}", encoding="utf-8")
        loop_path.write_text("{}", encoding="utf-8")
        app_state.clear_all()
        app_state.set_project_config(
            PipelineConfig(
                config_path=str(project_path),
                project_name="project",
                brief_root="brief",
                docs_root="docs",
                wbs_root="wbs",
                workspace_root="workspace",
            )
        )
        app_state.set_loop_config(
            PipelineConfig(
                config_path=str(loop_path),
                project_name="loop",
                brief_root="",
                docs_root="",
                wbs_root="",
                workspace_root="",
            )
        )
        captured_start_dirs: list[str] = []

        def fake_dialog(parent, title, start_dir, file_filter):
            captured_start_dirs.append(start_dir)
            return (str(project_path), "")

        with patch(
            "workflow_app.metrics_bar.metrics_bar.QFileDialog.getOpenFileName",
            side_effect=fake_dialog,
        ):
            try:
                bar._on_proj_select()
            finally:
                app_state.clear_all()

        assert captured_start_dirs == [str(project_path.parent)]

    def test_loop_select_emits_loop_config_change_requested(self, bar, tmp_path):
        loop_path = tmp_path / "_LOOP-CONFIG.json"
        loop_path.write_text(
            '{"iteration_template":"x","items":[],"finalization":{},"schema_version":"1.0.0","name":"loop"}'
        )
        emitted_loop: list[str] = []
        emitted_config: list[str] = []
        emitted_project: list[str] = []
        bar.loop_config_change_requested.connect(emitted_loop.append)
        bar.config_change_requested.connect(emitted_config.append)
        bar.project_config_change_requested.connect(emitted_project.append)

        with patch(
            "workflow_app.metrics_bar.metrics_bar.QFileDialog.getOpenFileName",
            return_value=(str(loop_path), ""),
        ):
            bar._on_loop_select()

        assert emitted_loop == [str(loop_path)]
        assert emitted_project == []
        assert emitted_config == [str(loop_path)]

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

    def test_project_loaded_keeps_loop_selector_available(self, bar):
        bar._apply_project_loaded("my-project")
        assert bar._proj_select_btn.isHidden()
        assert not bar._loop_select_btn.isHidden()
        assert not bar._proj_open_btn.isHidden()


class TestMetricsBarLoopPill:
    """Loop pill is a separate attachment surface from the project pill."""

    def test_loop_pill_hidden_on_init(self, bar):
        assert bar._loop_pill.isHidden()

    def test_loop_loaded_shows_loop_pill_only(self, bar):
        bar._apply_loop_loaded("my-loop")
        assert not bar._loop_pill.isHidden()
        assert bar._loop_select_btn.isHidden()
        assert bar._loop_name_lbl.text() == "my-loop"
        assert bar._project_pill.isHidden()

    def test_loop_empty_restores_loop_selector(self, bar):
        bar._apply_loop_loaded("my-loop")
        bar._apply_loop_empty()
        assert bar._loop_pill.isHidden()
        assert not bar._loop_select_btn.isHidden()

    def test_loop_refresh_emits_active_loop_path(self, bar, tmp_path):
        config_path = str(tmp_path / "_LOOP-CONFIG.json")
        emitted: list[str] = []
        bar.loop_config_reload_requested.connect(emitted.append)
        app_state.set_loop_config(
            PipelineConfig(
                config_path=config_path,
                project_name="my-loop",
                brief_root="",
                docs_root="",
                wbs_root="",
                workspace_root="",
            )
        )
        try:
            bar._on_loop_refresh()
        finally:
            app_state.clear_loop()
        assert emitted == [config_path]

    def test_loop_unload_emits_granular_signal(self, bar):
        emitted: list[bool] = []
        bar.loop_config_unload_requested.connect(lambda: emitted.append(True))
        bar._on_loop_unload()
        assert emitted == [True]

    def test_loop_loaded_toast_reads_loop_config_when_project_exists(
        self, bar, tmp_path
    ):
        project_cfg = PipelineConfig(
            config_path=str(tmp_path / ".claude" / "project.json"),
            project_name="project",
            brief_root="brief",
            docs_root="docs",
            wbs_root="wbs",
            workspace_root="workspace",
        )
        loop_root = tmp_path / "blacksmith" / "loop-archives" / "loop-a"
        loop_root.mkdir(parents=True)
        (loop_root / "PROGRESS.md").write_text(
            "\n".join([
                "# Progress",
                "Total: 2 items | Done: 1 | Pending: 1 | Failed: 0",
                "",
                "| ID  | Status | Target | Bucket | Updated |",
                "|-----|--------|--------|--------|---------|",
                "| 001 | [x]    | a.md   | T      | now     |",
                "| 002 | [ ]    | b.md   | T      | -       |",
            ]),
            encoding="utf-8",
        )
        loop_cfg = PipelineConfig(
            config_path=str(loop_root / "_LOOP-CONFIG.json"),
            project_name="loop-a",
            brief_root="",
            docs_root="",
            wbs_root="",
            workspace_root="",
        )
        app_state.set_project_config(project_cfg)
        app_state.set_loop_config(loop_cfg)
        try:
            bar._emit_loop_loaded_toast(
                {"kind": "daily-loop", "daily_loop": {"slug": "loop-a"}},
                "daily-loop",
            )
        finally:
            app_state.clear_all()

        bar._signal_bus.toast_requested.emit.assert_called_with(
            "Daily loop carregado (loop-a): 1 pendente(s). "
            "Clique `queue-btn-daily-loop` na barra de queue para enfileirar.",
            "info",
        )


# ──────────────────────────────── nav buttons ─── #


class TestMetricsBarNavButtons:
    """Navigation buttons exist, are enabled, and have text."""

    def test_btn_workflow_exists(self, bar):
        assert hasattr(bar, "_btn_workflow")
        assert bar._btn_workflow.isEnabled()

    def test_btn_comandos_exists(self, bar):
        assert hasattr(bar, "_btn_comandos")
        assert bar._btn_comandos.isEnabled()

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


# ──────────────────── Remote signals decoupled (regression — 2026-05-12) ─── #


class TestMetricsBarRemoteSignalsDecoupled:
    """Regression guard: MetricsBar must NOT subscribe to remote_* signals.

    Modo Remoto foi removido em 2026-05-12 (commit 6756483). RemoteServer
    e SignalBus.remote_* permanecem como contrato backend, mas MetricsBar
    nao deve ter affordances nem conexoes para esses sinais. Este teste
    impede reintroducao acidental do acoplamento UI<->remote.
    """

    REMOTE_SIGNALS = (
        "remote_server_started",
        "remote_server_stopped",
        "remote_client_connected",
        "remote_client_disconnected",
    )

    def test_no_connect_on_remote_signals(self, bar):
        """_connect_signals() must not call .connect() on any remote_* signal."""
        for sig_name in self.REMOTE_SIGNALS:
            sig = getattr(bar._signal_bus, sig_name)
            assert sig.connect.call_count == 0, (
                f"Regression: MetricsBar reconnected SignalBus.{sig_name} — "
                f"Modo Remoto foi removido em 2026-05-12 e nao deve voltar."
            )

    def test_no_remote_ui_affordances(self, bar):
        """MetricsBar must not expose the removed remote UI widgets."""
        for attr in (
            "_btn_remote",
            "_btn_copy_ip",
            "_lbl_remote_addr",
            "_lbl_connection_badge",
            "_btn_toolbox",
        ):
            assert not hasattr(bar, attr), (
                f"Regression: MetricsBar voltou a expor {attr} — "
                f"affordance removida em 2026-05-12."
            )

    def test_no_remote_handlers(self, bar):
        """MetricsBar must not expose the removed remote slot handlers."""
        for attr in (
            "_on_remote_server_started",
            "_on_remote_server_stopped",
            "_on_remote_client_connected",
            "_on_remote_client_disconnected",
            "_on_remote_toggled",
            "_on_copy_ip",
        ):
            assert not hasattr(bar, attr), (
                f"Regression: MetricsBar voltou a expor {attr} — "
                f"handler removido em 2026-05-12."
            )

# ──────────────────────── Authoritative idle lock (GAP-fix) ─── #


class TestMetricsBarAuthoritativeIdle:
    """Lock-based idle suppression for TUIs with continuous repaint (Rich, etc.)."""

    def test_enter_authoritative_idle_sets_green_and_lock(self, bar):
        bar._enter_authoritative_idle("workspace")
        assert bar._idle_locked["workspace"] is True
        assert bar._dot_workspace.is_busy is False

    def test_enter_authoritative_idle_stops_hardening_timer(self, bar):
        bar._idle_timer_workspace.start()
        assert bar._idle_timer_workspace.isActive()
        bar._enter_authoritative_idle("workspace")
        assert not bar._idle_timer_workspace.isActive()

    def test_terminal_activity_ignored_when_locked(self, bar):
        bar._enter_authoritative_idle("workspace")
        bar._dot_workspace.set_busy(False)
        bar._on_terminal_activity("workspace")
        assert bar._dot_workspace.is_busy is False

    def test_failed_state_is_not_cleared_by_late_idle_success(self, bar):
        """Failure wins: a later success/idle notify cannot turn red green."""
        bar._release_idle_lock("workspace")
        bar._dot_workspace.set_state("failed")
        bar._enter_authoritative_idle("workspace")
        assert bar._dot_workspace.state == "failed"
        assert bar._idle_locked["workspace"] is False

    def test_failed_state_is_not_cleared_by_prompt_activity(self, bar):
        """Prompt repaint chunks after a failure cannot clear the red dot."""
        bar._release_idle_lock("workspace")
        bar._dot_workspace.set_state("failed")
        bar._on_terminal_activity("workspace")
        assert bar._dot_workspace.state == "failed"

    def test_overall_listener_failed_wins_over_awaiting_user(self, bar):
        """Aggregate dot must preserve the canonical priority:
        failed > awaiting_user > busy > idle.
        """
        bar._dot_interactive.set_state("failed")
        bar._dot_workspace.set_state("awaiting_user")
        bar._dot_workspace_xterm.set_state("idle")
        bar._update_overall_listener()
        assert bar._dot_general.state == "failed"

    def test_release_idle_lock_allows_activity_to_turn_yellow(self, bar):
        bar._enter_authoritative_idle("workspace")
        bar._release_idle_lock("workspace")
        bar._on_terminal_activity("workspace")
        assert bar._dot_workspace.is_busy is True

    def test_terminal_session_started_releases_lock(self, bar):
        bar._enter_authoritative_idle("workspace")
        bar._on_terminal_session_started("workspace")
        assert bar._idle_locked["workspace"] is False
        assert bar._dot_workspace.is_busy is True

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
        assert bar._dot_workspace.is_busy is False
        assert bar._dot_interactive.is_busy is False

    def test_click_at_startup_does_not_flip_dot_yellow(self, bar):
        """Clicking the Kimi terminal generates an ANSI repaint chunk that
        reaches `_on_terminal_activity`. With lock=True at rest, that chunk
        must be ignored and the dot stays green. Reproduces the bug where
        clicking Kimi flipped the dot yellow even with no command running.
        """
        bar._on_terminal_activity("workspace")
        assert bar._dot_workspace.is_busy is False
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
        assert bar._dot_workspace.is_busy is True
        assert bar._idle_locked["workspace"] is False
        assert bar._idle_timer_workspace.isActive()

    def test_hardening_soft_timer_promotes_to_locked_idle(self, bar):
        """Soft 3s timer expiry → green + lock."""
        bar._release_idle_lock("workspace")
        bar._arm_hardening("workspace")
        bar._idle_timer_workspace.timeout.emit()
        assert bar._dot_workspace.is_busy is False
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
        assert bar._dot_workspace.is_busy is True
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
        assert bar._dot_workspace.is_busy is True

    def test_t3_notify_during_session_reprocessed_on_session_finished(self, qapp):
        """Regression: T3 could stay yellow after a valid success notify.

        The idle notify can arrive while ``_session_active`` is still true.
        That first read must not consume the run_id permanently; when the
        session finishes, the same payload is reprocessed and arms T3 hardening.
        """
        import json
        import time
        from workflow_app.signal_bus import SignalBus

        bus = SignalBus()
        mb = MetricsBar(bus)
        bus.run_command_in_workspace_xterm.emit("/loop-rocksmash:compare task.md")
        assert mb._awaiting_notify["workspace_xterm"] is True

        mb._on_terminal_session_started("workspace_xterm")
        assert mb._session_active["workspace_xterm"] is True

        notify_path = mb._notify_files["workspace_xterm"]
        notify_path.write_text(json.dumps({
            "channel": "workspace_xterm",
            "state": "idle",
            "iat": time.time(),
            "exp": time.time() + 10.0,
            "run_id": "t3-session-race-success",
        }))
        mb._on_notify_file_changed(str(notify_path))

        assert mb._awaiting_notify["workspace_xterm"] is True
        assert mb._last_processed_run_id["workspace_xterm"] != "t3-session-race-success"
        assert not mb._idle_timer_workspace_xterm.isActive()

        mb._on_terminal_session_finished("workspace_xterm")

        assert mb._awaiting_notify["workspace_xterm"] is False
        assert mb._last_processed_run_id["workspace_xterm"] == "t3-session-race-success"
        assert mb._idle_timer_workspace_xterm.isActive()
        cap = mb._hardcap_timer.get("workspace_xterm")
        assert cap is not None and cap.isActive()

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
        assert bar._is_helper_command("codex-high") is True
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
        scheduled_seq = mb._dispatch_seq["interactive"]
        mb._helper_auto_idle("interactive", scheduled_seq)
        # Soft timer must be armed but lock not yet flipped
        assert mb._idle_timer_interactive.isActive()
        assert mb._idle_locked["interactive"] is False
        # Now simulate 3s of silence: soft fires → green + lock
        mb._idle_timer_interactive.timeout.emit()
        assert mb._idle_locked["interactive"] is True
        assert mb._dot_interactive.is_busy is False

    def test_listener_helper_pulse_cycles_dot_without_terminal_write(self, qapp):
        """Codex/Kimi main: /model and /effort emit listener_helper_pulse,
        which must cycle the dot busy→green exactly like a real helper
        dispatch (release lock, go busy, arm soft hardening) but WITHOUT any
        terminal write — so the autocast loop advances.
        """
        from workflow_app.signal_bus import SignalBus
        bus = SignalBus()
        mb = MetricsBar(bus)
        terminal_writes: list[str] = []
        bus.run_command_in_terminal.connect(terminal_writes.append)
        try:
            bus.listener_helper_pulse.emit("interactive")
        finally:
            bus.run_command_in_terminal.disconnect(terminal_writes.append)
        # No terminal write — the directive was suppressed.
        assert terminal_writes == []
        # But the dot pulsed busy and the lock was released, same as a helper.
        assert mb._idle_locked["interactive"] is False
        assert mb._dot_interactive.is_busy is True
        # And the 1s helper auto-idle path arms hardening → eventual green.
        scheduled_seq = mb._dispatch_seq["interactive"]
        mb._helper_auto_idle("interactive", scheduled_seq)
        assert mb._idle_timer_interactive.isActive()
        mb._idle_timer_interactive.timeout.emit()
        assert mb._idle_locked["interactive"] is True
        assert mb._dot_interactive.is_busy is False

    def test_listener_helper_pulse_ignores_unknown_channel(self, qapp):
        """Defensive: an unrecognized channel is a no-op (no crash)."""
        from workflow_app.signal_bus import SignalBus
        bus = SignalBus()
        mb = MetricsBar(bus)
        bus.listener_helper_pulse.emit("does-not-exist")  # must not raise

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
        mb._helper_auto_idle("interactive", mb._dispatch_seq["interactive"])
        mb._helper_auto_idle("workspace", mb._dispatch_seq["workspace"])
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

    def test_interactive_skills_use_hardening_with_hardcap(self, qapp, tmp_path):
        """Interactive (Claude Code or Kimi) uses soft 3s timer PLUS a 5s
        hardcap. Kimi CLI emits invisible cursor/CPR chunks at its prompt
        that reset the soft timer indefinitely; the hardcap guarantees the
        dot eventually turns green even under constant PTY activity."""
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
        # Hardcap 5s ALSO armed — prevents Kimi "yellow forever" bug
        cap = mb._hardcap_timer.get("interactive")
        assert cap is not None and cap.isActive()
        assert cap.interval() == 5_000

    def test_workspace_xterm_skills_use_hardening_with_hardcap(self, qapp, tmp_path):
        """T3 (workspace_xterm, Codex worker) takes the SAME soft+hardcap
        path as T1. Any continuously-animating CLI in T3 would otherwise
        reset the soft timer forever (same class of bug as Kimi-in-T1).
        Enforces 'each terminal reaches its own listener' for T3."""
        import json, time
        from workflow_app.signal_bus import SignalBus
        bus = SignalBus()
        mb = MetricsBar(bus)
        bus.run_command_in_workspace_xterm.emit("/skill:test")
        notify_path = mb._notify_files["workspace_xterm"]
        notify_path.write_text(json.dumps({
            "channel": "workspace_xterm",
            "state": "idle",
            "iat": time.time(),
            "exp": time.time() + 10.0,
        }))
        mb._on_notify_file_changed(str(notify_path))
        assert mb._idle_timer_workspace_xterm.isActive()
        cap = mb._hardcap_timer.get("workspace_xterm")
        assert cap is not None and cap.isActive()
        assert cap.interval() == 5_000

    def test_directory_changed_recovers_missed_interactive_notify(self, qapp, tmp_path):
        """Atomic os.replace can surface only as a directoryChanged (not a
        fileChanged) on some inotify backends. _on_notify_directory_changed
        must reprocess existing payloads so a valid idle notify is never
        left unread — otherwise the dot is stuck yellow despite a correct
        on-disk file. This is the defense-in-depth backstop for the
        Kimi-in-T1 fix.

        The payload carries a `run_id` because the canonical writer
        (notify-terminal-idle.py) ALWAYS emits one; the rescan recovery
        lowers the notify-authoritative fence only for run_id-bearing,
        never-consumed notifies (§15.6) — exactly this case."""
        import json, time
        from workflow_app.signal_bus import SignalBus
        bus = SignalBus()
        mb = MetricsBar(bus)
        bus.run_command_in_terminal.emit("/skill:test")
        # Write a fresh idle payload WITHOUT calling _on_notify_file_changed
        # (simulating the swallowed fileChanged). run_id present = canonical.
        notify_path = mb._notify_files["interactive"]
        notify_path.write_text(json.dumps({
            "channel": "interactive",
            "state": "idle",
            "iat": time.time(),
            "exp": time.time() + 10.0,
            "run_id": "recovered-missed-1",
        }))
        assert not mb._idle_timer_interactive.isActive()  # nothing processed yet
        # Only the directory event fires.
        mb._on_notify_directory_changed(str(notify_path.parent))
        cap = mb._hardcap_timer.get("interactive")
        assert cap is not None and cap.isActive(), (
            "directoryChanged must recover the missed interactive notify"
        )
        # Idempotent: once green+locked, a second directory event is a no-op.
        mb._enter_authoritative_idle("interactive")
        assert mb._idle_locked["interactive"] is True
        mb._on_notify_directory_changed(str(notify_path.parent))
        assert mb._idle_locked["interactive"] is True
        assert mb._dot_interactive.is_busy is False

    def test_directory_changed_does_not_green_running_command(self, qapp, tmp_path):
        """A directoryChanged reprocess must NOT flip a freshly-dispatched
        command green: the stale previous-command notify is rejected by the
        epoch fence (iat <= current epoch)."""
        import json, time
        from workflow_app.signal_bus import SignalBus
        bus = SignalBus()
        mb = MetricsBar(bus)
        notify_path = mb._notify_files["interactive"]
        # Old notify written BEFORE the new dispatch (iat in the past).
        old_iat = time.time() - 5.0
        notify_path.write_text(json.dumps({
            "channel": "interactive",
            "state": "idle",
            "iat": old_iat,
            "exp": time.time() + 10.0,
        }))
        # New command dispatched now → bumps epoch past old_iat, dot busy.
        bus.run_command_in_terminal.emit("/skill:running")
        assert mb._dot_interactive.is_busy is True
        # Directory event reprocesses the stale notify → must be fenced out.
        mb._on_notify_directory_changed(str(notify_path.parent))
        assert "interactive" not in mb._hardcap_timer or not mb._hardcap_timer["interactive"].isActive()
        assert mb._dot_interactive.is_busy is True  # still running, still yellow

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
        assert bar._dot_workspace.is_busy is True
        assert bar._idle_locked["workspace"] is False
        # Fire hardcap directly
        bar._hardcap_timer["workspace"].timeout.emit()
        assert bar._idle_locked["workspace"] is True
        assert bar._dot_workspace.is_busy is False

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
        assert mb._dot_workspace.is_busy is False
        assert mb._dot_interactive.is_busy is False
        # Dispatch must flip both yellow synchronously
        bus.run_command_in_workspace_terminal.emit("/clear")
        assert mb._dot_workspace.is_busy is True, (
            "Workspace dispatch must force dot yellow synchronously, even "
            "if the CLI processes the command silently (no PTY chunks)."
        )
        bus.run_command_in_terminal.emit("/clear")
        assert mb._dot_interactive.is_busy is True

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
        assert bar._dot_workspace.is_busy is True
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
        assert mb._dot_workspace.is_busy is True

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
        assert bar._dot_interactive.is_busy is True
        # Activity on workspace is still suppressed by its lock
        bar._dot_workspace.set_busy(False)
        bar._on_terminal_activity("workspace")
        assert bar._dot_workspace.is_busy is False


class TestNotifyAuthoritativeFenceAntiCascade:
    """Regression guard for the catastrophic command-stacking cascade.

    Root cause: T1 (interactive) and T3 (workspace_xterm) green not only via
    the authoritative `wf-notify.sh` file but ALSO via a pure PTY-silence
    heuristic (OutputPanel/XtermOutputPanel 2s idle timer -> terminal_force_idle
    -> _on_force_idle -> _arm_hardening -> green). While a real command runs a
    long, output-quiet tool (a blocking `Using Shell`/Bash whose CLI spinner
    freezes), that silence path false-greens the dot ~5s in, the autocast
    verde+verde gate fires the NEXT queue item into the still-busy CLI, the
    paste echoes a chunk + silence, it false-greens again -> N commands stack
    unsubmitted in the input box.

    Fix: `_awaiting_notify[channel]` raised on every real (non-helper) dispatch
    suppresses `_on_force_idle` for that channel until an authoritative notify
    (idle/failed/awaiting_user) or a fatal/early-exit tripwire resolves the dot.
    See ai-forge/rules/workflow-app-listeners.md §15.3.
    """

    # ── Fence is raised/lowered correctly ─────────────────────────────── #

    def test_real_dispatch_raises_fence_interactive(self, qapp):
        from workflow_app.signal_bus import SignalBus
        bus = SignalBus()
        mb = MetricsBar(bus)
        assert mb._awaiting_notify["interactive"] is False
        bus.run_command_in_terminal.emit("/skill:slash-executor /loop:iteraction:execute-task")
        assert mb._awaiting_notify["interactive"] is True
        assert mb._dot_interactive.is_busy is True

    def test_real_dispatch_raises_fence_workspace_xterm(self, qapp):
        from workflow_app.signal_bus import SignalBus
        bus = SignalBus()
        mb = MetricsBar(bus)
        bus.run_command_in_workspace_xterm.emit("/skill:qa:trace")
        assert mb._awaiting_notify["workspace_xterm"] is True
        assert mb._dot_workspace_xterm.is_busy is True

    def test_helper_dispatch_does_not_raise_fence(self, qapp):
        """Helpers (/clear /model /effort, cd, CLI launches) green via their own
        auto-idle timer and must NOT raise the fence (they never notify)."""
        from workflow_app.signal_bus import SignalBus
        bus = SignalBus()
        mb = MetricsBar(bus)
        for helper in ("/clear", "/model opus", "/effort high", "cd foo", "kimid"):
            bus.run_command_in_terminal.emit(helper)
            assert mb._awaiting_notify["interactive"] is False, (
                f"helper {helper!r} must not raise the notify fence"
            )

    def test_listener_helper_pulse_lowers_fence(self, qapp):
        """A suppressed /model|/effort pulse (Codex/Kimi main) is a helper —
        it must lower the fence so its auto-idle green path is not blocked."""
        from workflow_app.signal_bus import SignalBus
        bus = SignalBus()
        mb = MetricsBar(bus)
        # First a real command raises the fence...
        bus.run_command_in_terminal.emit("/skill:foo")
        assert mb._awaiting_notify["interactive"] is True
        # ...then a helper pulse on the same channel lowers it.
        bus.listener_helper_pulse.emit("interactive")
        assert mb._awaiting_notify["interactive"] is False

    # ── THE cascade: silence must NOT green a running command ─────────── #

    def test_force_idle_suppressed_while_awaiting_notify_interactive(self, qapp):
        """Core repro: real command dispatched, PTY goes silent -> force_idle.
        The dot must STAY yellow and NO hardening must arm (no path to green)."""
        from workflow_app.signal_bus import SignalBus
        bus = SignalBus()
        mb = MetricsBar(bus)
        bus.run_command_in_terminal.emit("/skill:long-silent-task")
        assert mb._dot_interactive.is_busy is True
        # Simulate many rounds of PTY silence (OutputPanel idle timeout).
        for _ in range(5):
            mb._on_force_idle("interactive")
        assert mb._dot_interactive.is_busy is True, (
            "silence must not green a command awaiting its notify (cascade root)"
        )
        assert not mb._idle_timer_interactive.isActive(), (
            "force_idle must not arm hardening while the notify fence is up"
        )
        assert "interactive" not in mb._hardcap_timer or not mb._hardcap_timer["interactive"].isActive()

    def test_force_idle_suppressed_while_awaiting_notify_xterm(self, qapp):
        """Same guard for T3 (Codex worker). T3's idle-timeout emits
        session_finished + force_idle together; the fence must survive that."""
        from workflow_app.signal_bus import SignalBus
        bus = SignalBus()
        mb = MetricsBar(bus)
        bus.run_command_in_workspace_xterm.emit("/skill:long-silent-task")
        assert mb._dot_workspace_xterm.is_busy is True
        # T3 idle-timeout order: session_finished THEN force_idle.
        mb._on_terminal_session_finished("workspace_xterm")
        mb._on_force_idle("workspace_xterm")
        assert mb._dot_workspace_xterm.is_busy is True, (
            "session_finished must not lower the fence and let silence green T3"
        )
        assert not mb._idle_timer_workspace_xterm.isActive()

    # ── The legit silence heuristic still works (direct typing) ───────── #

    def test_force_idle_greens_when_not_awaiting_notify(self, bar):
        """Direct typing into T1 (no app dispatch) leaves the fence down, so the
        silence heuristic must still arm hardening and green Claude normally."""
        bar._release_idle_lock("interactive")
        assert bar._awaiting_notify["interactive"] is False
        bar._on_force_idle("interactive")
        assert bar._idle_timer_interactive.isActive(), (
            "with no command awaiting notify, silence must still arm hardening"
        )

    # ── Authoritative notify lowers the fence and greens ──────────────── #

    def test_notify_idle_clears_fence_and_greens(self, qapp, tmp_path):
        import json, time
        from workflow_app.signal_bus import SignalBus
        bus = SignalBus()
        mb = MetricsBar(bus)
        bus.run_command_in_terminal.emit("/skill:test")
        assert mb._awaiting_notify["interactive"] is True
        notify_path = mb._notify_files["interactive"]
        notify_path.write_text(json.dumps({
            "channel": "interactive", "state": "idle",
            "iat": time.time(), "exp": time.time() + 10.0,
            "run_id": "run-notify-clear-1",
        }))
        mb._on_notify_file_changed(str(notify_path))
        # Notify arms hardening; fence still up until the dot actually greens.
        assert mb._idle_timer_interactive.isActive()
        # Soft timer fires (true silence) -> authoritative idle -> green + clear.
        mb._idle_timer_interactive.timeout.emit()
        assert mb._dot_interactive.is_busy is False
        assert mb._awaiting_notify["interactive"] is False

    def test_failure_notify_clears_fence(self, qapp):
        from workflow_app.signal_bus import SignalBus
        bus = SignalBus()
        mb = MetricsBar(bus)
        bus.run_command_in_terminal.emit("/skill:test")
        assert mb._awaiting_notify["interactive"] is True
        mb._on_terminal_force_failed("interactive", "VERIFY_FAILED")
        assert mb._awaiting_notify["interactive"] is False
        assert mb._dot_interactive.state == "failed"

    def test_awaiting_user_notify_clears_fence(self, qapp):
        from workflow_app.signal_bus import SignalBus
        bus = SignalBus()
        mb = MetricsBar(bus)
        bus.run_command_in_terminal.emit("/skill:test")
        assert mb._awaiting_notify["interactive"] is True
        mb._on_terminal_awaiting_user("interactive")
        assert mb._awaiting_notify["interactive"] is False
        assert mb._dot_interactive.state == "awaiting_user"

    # ── End-to-end: autocast must not fire the next item on silence ───── #

    def test_autocast_does_not_fire_next_on_silence_then_fires_on_notify(self, qapp, tmp_path):
        """Full cascade guard. Autocast running; a real command is dispatched.
        Repeated PTY silence must NOT re-open the verde+verde gate. Only the
        authoritative notify greens the dot and fires exactly one next step."""
        import json, time
        from workflow_app.signal_bus import SignalBus
        bus = SignalBus()
        mb = MetricsBar(bus)
        fires: list[int] = []
        bus.autocast_step_requested.connect(lambda: fires.append(1))

        # Arm autocast (setChecked triggers _on_autocast_toggled) and consume
        # the initial fire from toggling it on.
        mb._btn_autocast.setChecked(True)
        fires.clear()
        mb._autocast_phase = "running"

        # A real command is dispatched on T1 (the item the autocast just fired).
        bus.run_command_in_terminal.emit("/skill:slash-executor /loop:iteraction:execute-task")
        assert mb._dot_interactive.is_busy is True

        # Long, output-quiet tool call: 5 rounds of PTY silence.
        for _ in range(5):
            mb._on_force_idle("interactive")
        assert mb._dot_interactive.is_busy is True
        assert fires == [], (
            "autocast must NOT fire the next item while the command is still "
            "running (this is exactly the command-stacking cascade)"
        )

        # Command genuinely finishes -> authoritative notify -> green.
        notify_path = mb._notify_files["interactive"]
        notify_path.write_text(json.dumps({
            "channel": "interactive", "state": "idle",
            "iat": time.time(), "exp": time.time() + 10.0,
            "run_id": "run-e2e-1",
        }))
        mb._on_notify_file_changed(str(notify_path))
        mb._idle_timer_interactive.timeout.emit()  # true silence -> green
        assert mb._dot_interactive.is_busy is False
        # The verde+verde debounce timer is now armed; fire it -> exactly one step.
        assert mb._autocast_fire_timer.isActive()
        mb._autocast_fire_timer.timeout.emit()
        assert fires == [1], "exactly one next item fires, after the notify"


class TestAutocastPassiveModeOnEnable:
    """Request 2026-06: ligar o autocast manualmente NAO dispara o primeiro
    [Rodar proximo]. O modo e passivo — so avanca quando o LISTENER chamar
    (dot verde apos um comando concluir). O disparo AGENDADO mantem o kickoff."""

    def test_manual_toggle_does_not_fire_first_step(self, qapp):
        from workflow_app.signal_bus import SignalBus
        bus = SignalBus()
        mb = MetricsBar(bus)
        fires: list[int] = []
        bus.autocast_step_requested.connect(lambda: fires.append(1))

        # Liga manualmente (como o usuario clicando no autocast-btn).
        mb._btn_autocast.setChecked(True)

        assert fires == [], (
            "ligar o autocast manualmente NAO pode disparar o primeiro play"
        )
        assert mb._btn_autocast.isChecked() is True
        assert mb._autocast_phase == "running", "fica armado/escutando"
        # O arm-timer NAO foi iniciado (so inicia ao disparar um step), entao
        # o autocast nao se auto-desliga por timeout enquanto espera o listener.
        assert not (
            hasattr(mb, "_autocast_arm_timer") and mb._autocast_arm_timer.isActive()
        )

    def test_advances_on_listener_green_after_manual_toggle(self, qapp, tmp_path):
        import json, time
        from workflow_app.signal_bus import SignalBus
        bus = SignalBus()
        mb = MetricsBar(bus)
        fires: list[int] = []
        bus.autocast_step_requested.connect(lambda: fires.append(1))

        # Liga passivo. Depois um comando ja em execucao conclui (listener).
        mb._btn_autocast.setChecked(True)
        assert fires == []

        bus.run_command_in_terminal.emit("/skill:slash-executor /loop:iteraction:execute-task")
        assert mb._dot_interactive.is_busy is True

        notify_path = mb._notify_files["interactive"]
        notify_path.write_text(json.dumps({
            "channel": "interactive", "state": "idle",
            "iat": time.time(), "exp": time.time() + 10.0,
            "run_id": "run-passive-1",
        }))
        mb._on_notify_file_changed(str(notify_path))
        mb._idle_timer_interactive.timeout.emit()
        assert mb._dot_interactive.is_busy is False
        assert mb._autocast_fire_timer.isActive(), "listener verde arma o proximo"
        mb._autocast_fire_timer.timeout.emit()
        assert fires == [1], "primeiro play dispara SO quando o listener chama"

    def test_scheduled_autocast_kickoff_fires_first_step(self, qapp):
        from workflow_app.signal_bus import SignalBus
        bus = SignalBus()
        mb = MetricsBar(bus)
        fires: list[int] = []
        bus.autocast_step_requested.connect(lambda: fires.append(1))

        # O disparo AGENDADO mantem o kickoff (inicia a fila no horario marcado).
        mb._fire_schedule_autocast()

        assert mb._btn_autocast.isChecked() is True
        assert fires == [1], "o autocast agendado dispara o primeiro play"
        # E o flag de kickoff volta a False (so vale para o disparo agendado).
        assert mb._autocast_kickoff_on_enable is False
