"""Tests for the autocast failure-abort flow (3 camadas).

Covers the path that stops the autocast loop when a dispatched command
fails without a real successful completion:

  - Camada 1: OutputPanel scans PTY chunks for known fatal patterns
    (subscription disabled, credit balance, rate limit, etc.) and emits
    `terminal_force_failed`.
  - Camada 2: MetricsBar handles `terminal_force_failed` -> turns the dot
    red, emits `autocast_abort_requested`; `_on_dot_busy_changed` guards
    against firing the next step while any dot is `failed`/`awaiting_user`;
    `CommandQueueWidget` unchecks the autocast button on abort; the dot
    accepts a mouse click to clear `failed` back to idle.
  - Camada 3: when a programmatic dispatch is followed by a short, quiet
    idle window (CLI died early without matching a known pattern), the
    idle timeout emits `terminal_force_failed("EARLY_EXIT")`.

These tests use the real Qt event loop (qtbot/qapp) but a MagicMock
signal bus where useful, since MetricsBar accepts injection.
"""
from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from workflow_app.metrics_bar.metrics_bar import MetricsBar, TerminalStatusDot
from workflow_app.output_panel.output_panel import OutputPanel
from workflow_app.signal_bus import signal_bus


@pytest.fixture()
def bar(qapp):
    return MetricsBar(MagicMock())


@pytest.fixture()
def panel(qapp, qtbot):
    p = OutputPanel()
    qtbot.addWidget(p)
    p.show()
    return p


class TestCamada2DotState:
    def test_set_failed_changes_color_and_tooltip(self, qapp):
        dot = TerminalStatusDot(channel="interactive", label="L")
        dot.set_state("failed")
        assert dot.state == "failed"
        assert "falhou" in dot.toolTip()

    def test_mouse_press_on_failed_returns_idle(self, qapp):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtGui import QMouseEvent

        dot = TerminalStatusDot(channel="interactive", label="L")
        dot.set_state("failed")

        seen = []
        dot.busy_changed.connect(lambda c, b: seen.append((c, b)))

        ev = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPoint(5, 5),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        dot.mousePressEvent(ev)
        assert dot.state == "idle"
        assert seen == [("interactive", False)]

    def test_mouse_press_on_awaiting_user_returns_busy(self, qapp):
        from PySide6.QtCore import QPoint, Qt
        from PySide6.QtGui import QMouseEvent

        dot = TerminalStatusDot(channel="workspace", label="L")
        dot.set_state("awaiting_user")

        seen = []
        dot.busy_changed.connect(lambda c, b: seen.append((c, b)))

        ev = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPoint(5, 5),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        dot.mousePressEvent(ev)
        assert dot.state == "busy"
        assert seen == [("workspace", True)]


class TestCamada2HandlerAndGuard:
    def test_handler_sets_dot_failed_and_aborts(self, bar):
        bar._on_terminal_force_failed("interactive", "AUTH_SUBSCRIPTION_DISABLED")
        assert bar._dot_interactive.state == "failed"
        bar._signal_bus.autocast_abort_requested.emit.assert_called_once_with(
            "listener-failure", "interactive"
        )

    def test_busy_changed_guard_blocks_when_failed(self, bar):
        # Simula autocast ON + fase running + dot interactive failed.
        bar._btn_autocast.setChecked(True)
        bar._autocast_phase = "running"
        bar._dot_interactive.set_state("failed")
        # Outros dots green.
        bar._dot_workspace.set_state("idle")
        bar._dot_workspace_xterm.set_state("idle")
        # Reset do fire timer (singleshot) — se for disparado teste falha.
        bar._ensure_autocast_timers()
        bar._autocast_fire_timer.stop()
        # Chama o handler como se dot tivesse acabado de virar verde.
        bar._on_dot_busy_changed("workspace", False)
        assert not bar._autocast_fire_timer.isActive(), (
            "Autocast fire timer NAO pode armar enquanto existe dot failed"
        )

    def test_busy_changed_guard_blocks_when_awaiting_user(self, bar):
        bar._btn_autocast.setChecked(True)
        bar._autocast_phase = "running"
        bar._dot_workspace.set_state("awaiting_user")
        bar._dot_interactive.set_state("idle")
        bar._dot_workspace_xterm.set_state("idle")
        bar._ensure_autocast_timers()
        bar._autocast_fire_timer.stop()
        bar._on_dot_busy_changed("interactive", False)
        assert not bar._autocast_fire_timer.isActive()


class TestCamada1PatternMatcher:
    @pytest.mark.parametrize(
        "chunk, expected_reason",
        [
            (
                "Your organization has disabled Claude subscription access for Claude Code",
                "AUTH_SUBSCRIPTION_DISABLED",
            ),
            ("Use an Anthropic API key instead", "AUTH_API_KEY_REQUIRED"),
            ("Invalid API key. Please run /login.", "AUTH_INVALID_API_KEY"),
            ("Your credit balance is too low to access the API.", "CREDIT_BALANCE_LOW"),
            ("Usage limit reached for your plan", "USAGE_LIMIT_REACHED"),
            ("429 Too Many Requests", "RATE_LIMIT"),
        ],
    )
    def test_known_pattern_emits_force_failed(self, panel, qtbot, chunk, expected_reason):
        emitted: list[tuple[str, str]] = []
        signal_bus.terminal_force_failed.connect(
            lambda c, r: emitted.append((c, r))
        )
        try:
            panel._scan_chunk_for_fatal(chunk)
        finally:
            try:
                signal_bus.terminal_force_failed.disconnect()
            except (RuntimeError, TypeError):
                pass
        assert emitted == [(panel._channel, expected_reason)]
        # Idempotente: chunk repetido nao reemite.
        emitted.clear()
        signal_bus.terminal_force_failed.connect(
            lambda c, r: emitted.append((c, r))
        )
        try:
            panel._scan_chunk_for_fatal(chunk)
        finally:
            try:
                signal_bus.terminal_force_failed.disconnect()
            except (RuntimeError, TypeError):
                pass
        assert emitted == []

    def test_clean_chunk_does_not_fire(self, panel):
        emitted: list[tuple[str, str]] = []
        signal_bus.terminal_force_failed.connect(
            lambda c, r: emitted.append((c, r))
        )
        try:
            panel._scan_chunk_for_fatal("Running: npm test\nOK 42 passed")
        finally:
            try:
                signal_bus.terminal_force_failed.disconnect()
            except (RuntimeError, TypeError):
                pass
        assert emitted == []


class TestCamada3EarlyExitWatcher:
    def test_idle_after_short_quiet_dispatch_fires_early_exit(self, panel):
        # Simula dispatch programatico (sem usar PTY real).
        panel._dispatch_ts = time.monotonic()  # agora
        panel._bytes_since_dispatch = 200       # bem abaixo do threshold
        panel._last_failure_reason = None

        emitted: list[tuple[str, str]] = []
        idle_emitted: list[str] = []
        signal_bus.terminal_force_failed.connect(
            lambda c, r: emitted.append((c, r))
        )
        signal_bus.terminal_force_idle.connect(idle_emitted.append)
        try:
            panel._on_idle_timeout()
        finally:
            try:
                signal_bus.terminal_force_failed.disconnect()
                signal_bus.terminal_force_idle.disconnect()
            except (RuntimeError, TypeError):
                pass

        assert emitted == [(panel._channel, "EARLY_EXIT")]
        assert idle_emitted == []
        assert panel._dispatch_ts is None  # janela consumida

    def test_idle_after_long_dispatch_fires_normal_idle(self, panel):
        # Dispatch ja passou da janela de 8s.
        panel._dispatch_ts = time.monotonic() - 30.0
        panel._bytes_since_dispatch = 10
        panel._last_failure_reason = None

        emitted_failed: list[tuple[str, str]] = []
        idle_emitted: list[str] = []
        signal_bus.terminal_force_failed.connect(
            lambda c, r: emitted_failed.append((c, r))
        )
        signal_bus.terminal_force_idle.connect(idle_emitted.append)
        try:
            panel._on_idle_timeout()
        finally:
            try:
                signal_bus.terminal_force_failed.disconnect()
                signal_bus.terminal_force_idle.disconnect()
            except (RuntimeError, TypeError):
                pass

        assert emitted_failed == []
        assert idle_emitted == [panel._channel]

    def test_idle_with_enough_bytes_fires_normal_idle(self, panel):
        # Dentro da janela de tempo, mas com bytes suficientes -> comando real.
        panel._dispatch_ts = time.monotonic()
        panel._bytes_since_dispatch = 8192
        panel._last_failure_reason = None

        emitted_failed: list[tuple[str, str]] = []
        idle_emitted: list[str] = []
        signal_bus.terminal_force_failed.connect(
            lambda c, r: emitted_failed.append((c, r))
        )
        signal_bus.terminal_force_idle.connect(idle_emitted.append)
        try:
            panel._on_idle_timeout()
        finally:
            try:
                signal_bus.terminal_force_failed.disconnect()
                signal_bus.terminal_force_idle.disconnect()
            except (RuntimeError, TypeError):
                pass

        assert emitted_failed == []
        assert idle_emitted == [panel._channel]

    def test_no_dispatch_recorded_fires_normal_idle(self, panel):
        # PTY ficou silencioso espontaneamente (sem dispatch programatico).
        panel._dispatch_ts = None
        panel._bytes_since_dispatch = 0

        emitted_failed: list[tuple[str, str]] = []
        idle_emitted: list[str] = []
        signal_bus.terminal_force_failed.connect(
            lambda c, r: emitted_failed.append((c, r))
        )
        signal_bus.terminal_force_idle.connect(idle_emitted.append)
        try:
            panel._on_idle_timeout()
        finally:
            try:
                signal_bus.terminal_force_failed.disconnect()
                signal_bus.terminal_force_idle.disconnect()
            except (RuntimeError, TypeError):
                pass

        assert emitted_failed == []
        assert idle_emitted == [panel._channel]

    def test_pattern_match_skips_early_exit(self, panel):
        # Pattern ja casou: idle nao deve disparar EARLY_EXIT redundante.
        panel._dispatch_ts = time.monotonic()
        panel._bytes_since_dispatch = 200
        panel._last_failure_reason = "AUTH_SUBSCRIPTION_DISABLED"

        emitted_failed: list[tuple[str, str]] = []
        idle_emitted: list[str] = []
        signal_bus.terminal_force_failed.connect(
            lambda c, r: emitted_failed.append((c, r))
        )
        signal_bus.terminal_force_idle.connect(idle_emitted.append)
        try:
            panel._on_idle_timeout()
        finally:
            try:
                signal_bus.terminal_force_failed.disconnect()
                signal_bus.terminal_force_idle.disconnect()
            except (RuntimeError, TypeError):
                pass

        assert emitted_failed == []
        assert idle_emitted == [panel._channel]

    def test_helper_command_does_not_open_early_exit_window(self, panel):
        # Helpers (/clear, /model, /effort) finish fast by design and must NOT
        # trigger EARLY_EXIT (issue: /clear on Kimi returns to prompt in <1s).
        panel._run_shell_command("/clear")
        assert panel._dispatch_ts is None
        assert panel._last_failure_reason is None
        assert panel._bytes_since_dispatch == 0

        # Because _dispatch_ts is None, idle timeout should go straight to green.
        idle_emitted: list[str] = []
        signal_bus.terminal_force_idle.connect(idle_emitted.append)
        try:
            panel._on_idle_timeout()
        finally:
            try:
                signal_bus.terminal_force_idle.disconnect()
            except (RuntimeError, TypeError):
                pass
        assert idle_emitted == [panel._channel]
