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
    # Severidade dos patterns (espelha _FATAL_PATTERNS em output_panel.py):
    #   hard = frase especifica de morte do CLI -> dispara em QUALQUER chunk;
    #   soft = palavra/expressao generica -> so conta como crash DENTRO da
    #          janela early-crash. Fix dos falsos-VERMELHOS dos casos
    #          004/010/013 (debug.md): conteudo benigno que apenas DISCUTE
    #          auth/rate-limit, renderizado apos kilobytes de output, nao
    #          pode forcar vermelho.
    HARD_CASES = [
        (
            "Your organization has disabled Claude subscription access for Claude Code",
            "AUTH_SUBSCRIPTION_DISABLED",
        ),
        ("Use an Anthropic API key instead", "AUTH_API_KEY_REQUIRED"),
        ("Your credit balance is too low to access the API.", "CREDIT_BALANCE_LOW"),
    ]
    SOFT_CASES = [
        ("Invalid API key. Please run /login.", "AUTH_INVALID_API_KEY"),
        ("Login expired. Please run /login.", "AUTH_LOGIN_EXPIRED"),
        ("Usage limit reached for your plan", "USAGE_LIMIT_REACHED"),
        ("429 Too Many Requests", "RATE_LIMIT"),
    ]

    @staticmethod
    def _enter_early_crash_window(panel) -> None:
        """Coloca o panel DENTRO da janela early-crash (dispatch recente,
        poucos bytes) — onde patterns soft contam como crash real do CLI."""
        panel._dispatch_ts = time.monotonic()
        panel._bytes_since_dispatch = 0
        panel._last_failure_reason = None

    @staticmethod
    def _collect(panel, chunk) -> list[tuple[str, str]]:
        emitted: list[tuple[str, str]] = []
        signal_bus.terminal_force_failed.connect(lambda c, r: emitted.append((c, r)))
        try:
            panel._scan_chunk_for_fatal(chunk)
        finally:
            try:
                signal_bus.terminal_force_failed.disconnect()
            except (RuntimeError, TypeError):
                pass
        return emitted

    @pytest.mark.parametrize("chunk, expected_reason", HARD_CASES)
    def test_hard_pattern_fires_unconditionally(self, panel, chunk, expected_reason):
        # Mesmo fora da janela (sem dispatch, muitos bytes) o hard dispara.
        panel._dispatch_ts = None
        panel._bytes_since_dispatch = 10_000
        panel._last_failure_reason = None
        assert self._collect(panel, chunk) == [(panel._channel, expected_reason)]
        # Idempotente: chunk repetido nao reemite.
        assert self._collect(panel, chunk) == []

    @pytest.mark.parametrize("chunk, expected_reason", SOFT_CASES)
    def test_soft_pattern_fires_inside_early_crash_window(self, panel, chunk, expected_reason):
        self._enter_early_crash_window(panel)
        assert self._collect(panel, chunk) == [(panel._channel, expected_reason)]
        # Idempotente dentro da mesma sessao do PTY.
        assert self._collect(panel, chunk) == []

    @pytest.mark.parametrize("chunk, reason", SOFT_CASES)
    def test_soft_pattern_suppressed_after_stream(self, panel, chunk, reason):
        # Regressao casos 004/010/013: comando ja streamou alem do threshold
        # de bytes — a palavra benigna NAO pode forcar vermelho.
        panel._dispatch_ts = time.monotonic()
        panel._bytes_since_dispatch = panel._EARLY_EXIT_BYTES_THRESHOLD + 1
        panel._last_failure_reason = None
        assert self._collect(panel, chunk) == []

    def test_soft_pattern_suppressed_when_no_dispatch(self, panel):
        # Sem dispatch programatico (prompt ocioso): soft nao dispara.
        panel._dispatch_ts = None
        panel._bytes_since_dispatch = 0
        panel._last_failure_reason = None
        assert self._collect(panel, "429 Too Many Requests") == []

    def test_suppressed_soft_does_not_latch_last_failure_reason(self, panel):
        # Soft suprimido fora da janela NAO pode marcar _last_failure_reason —
        # senao o dedupe mascararia um EARLY_EXIT (ou um soft legitimo) posterior.
        panel._dispatch_ts = time.monotonic()
        panel._bytes_since_dispatch = panel._EARLY_EXIT_BYTES_THRESHOLD + 1
        panel._last_failure_reason = None
        assert self._collect(panel, "429 Too Many Requests") == []
        assert panel._last_failure_reason is None

    def test_benign_security_spec_does_not_fire_after_stream(self, panel):
        # Casos 010+013 concretos: spec de checkout/OIDC que DISCUTE rate-limit
        # e autorizacao, renderizada depois de kilobytes de output benigno.
        panel._dispatch_ts = time.monotonic()
        panel._bytes_since_dispatch = 5_000
        panel._last_failure_reason = None
        chunk = (
            "checkRateLimit(): Rate limit: 10 req/min -> 429 rate-limit; "
            "Unauthorized origin rejected by the OIDC issuer"
        )
        assert self._collect(panel, chunk) == []

    def test_clean_chunk_does_not_fire(self, panel):
        assert self._collect(panel, "Running: npm test\nOK 42 passed") == []


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


class TestObservability009012:
    """FIX-009-012-OBS: observabilidade ADITIVA do red persistente (toolTip +
    telemetria jsonl). NAO muda estado/cor/fence — so explica 'success em disco
    + dot vermelho' (casos 009/012). Ver metrics_bar.py."""

    @pytest.fixture(autouse=True)
    def _no_telemetry_pollution(self, bar, monkeypatch):
        # Por padrao, telemetria vira no-op (nao escreve no .claude/wf-failures
        # real do repo durante os testes). O teste de escrita re-aponta p/ tmp.
        monkeypatch.setattr(bar, "_repo_root_path", lambda: None)

    def test_force_failed_records_reason_and_since(self, bar):
        bar._on_terminal_force_failed("interactive", "VERIFY_FAILED")
        assert bar._dot_interactive.state == "failed"
        assert bar._fail_reason["interactive"] == "VERIFY_FAILED"
        assert bar._fail_since.get("interactive", 0) > 0

    def test_discard_guard_enriches_tooltip_without_state_change(self, bar):
        bar._on_terminal_force_failed("interactive", "RATE_LIMIT")
        # idle chega depois (timer de silencio) -> guard de discard. Dot
        # continua VERMELHO (failure-wins); so o toolTip e enriquecido.
        bar._enter_authoritative_idle("interactive")
        assert bar._dot_interactive.state == "failed"  # estado NAO muda
        tip = bar._dot_interactive.toolTip()
        assert "falhou (RATE_LIMIT)" in tip
        assert "clique para limpar" in tip
        # NUNCA afirmar 'success descartado' — o failure-wins canonico (mesmo
        # run_id) e dropado antes de chegar aqui; afirmar success seria falso.
        assert "success" not in tip.lower()
        assert "descartad" not in tip.lower()

    def test_unknown_reason_falls_back_to_desconhecido(self, bar):
        # Dot vermelho sem reason registrada (ex: forcado por outro caminho)
        # -> toolTip neutro, nunca KeyError.
        bar._dot_interactive.set_state("failed")
        bar._enter_authoritative_idle("interactive")
        assert "falhou (desconhecido)" in bar._dot_interactive.toolTip()

    def test_recovery_reset_clears_reason(self, bar):
        bar._on_terminal_force_failed("interactive", "BLOCKED")
        bar._on_dot_recovery_reset("interactive", False)
        assert "interactive" not in bar._fail_reason
        assert "interactive" not in bar._fail_since

    def test_telemetry_writes_one_jsonl_line(self, bar, tmp_path, monkeypatch):
        import json
        monkeypatch.setattr(bar, "_repo_root_path", lambda: tmp_path)
        bar._on_terminal_force_failed("workspace", "EXIT_NONZERO")
        files = list((tmp_path / ".claude" / "wf-failures").glob("*.jsonl"))
        assert len(files) == 1
        lines = [l for l in files[0].read_text().splitlines() if l.strip()]
        assert len(lines) == 1
        rec = json.loads(lines[0])
        assert rec["channel"] == "workspace"
        assert rec["reason"] == "EXIT_NONZERO"
        assert rec["exit_code"] is None
        assert rec["command"] is None
        assert rec["duration_seconds"] is None

    def test_telemetry_noop_when_no_repo_root(self, bar):
        # _repo_root_path already None via autouse; must not raise.
        bar._append_failure_telemetry("interactive", "BLOCKED")


class TestDec014InstanceBadge:
    """DEC-014: badge PASSIVO 'N janelas neste repo'. Conta instancias vivas do
    MESMO install-dir via owner.json; visivel so quando N>1. NUNCA toca
    fence/dot/notify (observabilidade pura). Ver caso 014."""

    @staticmethod
    def _seed(dir_path, pid, install_dir):
        import json as _json
        dir_path.mkdir(parents=True, exist_ok=True)
        (dir_path / "owner.json").write_text(
            _json.dumps({"pid": pid, "install_dir": install_dir, "ts": 1.0})
        )

    def test_counts_only_alive_same_install(self, tmp_path):
        import os
        mine = "/repo/ai-forge/workflow-app"
        alive = os.getpid()
        # 2 vivas, mesmo install -> contam
        self._seed(tmp_path / f"session-{alive}-a", alive, mine)
        self._seed(tmp_path / f"session-{alive}-b", alive, mine)
        # pid morto, mesmo install -> excluida
        self._seed(tmp_path / "session-999998", 999998, mine)
        # viva, install diferente -> excluida
        self._seed(tmp_path / "session-other", alive, "/other/ai-forge/workflow-app")
        # owner.json malformado -> ignorada
        d = tmp_path / "session-bad"; d.mkdir(); (d / "owner.json").write_text("{not json")
        # session-dir sem owner.json -> ignorada
        (tmp_path / "session-empty").mkdir()
        assert MetricsBar._count_live_instances(tmp_path, mine) == 2

    def test_minimum_one_when_empty(self, tmp_path):
        assert MetricsBar._count_live_instances(tmp_path, "/x") == 1

    def test_badge_hidden_when_single(self, bar, monkeypatch):
        monkeypatch.setattr(bar, "_count_repo_instances", lambda: 1)
        bar._refresh_instance_badge()
        assert not bar._lbl_instances.isVisible()

    def test_badge_shows_count_when_multiple(self, bar, monkeypatch):
        monkeypatch.setattr(bar, "_count_repo_instances", lambda: 3)
        bar._refresh_instance_badge()
        # isVisible() pode ser False se o pai nao esta shown; valide texto+flag.
        assert "3 janelas neste repo" == bar._lbl_instances.text()
        assert not bar._lbl_instances.isHidden()

    def test_refresh_never_raises_on_count_error(self, bar, monkeypatch):
        def _boom():
            raise RuntimeError("scan failed")
        monkeypatch.setattr(bar, "_count_repo_instances", _boom)
        bar._refresh_instance_badge()  # fail-soft, nao propaga
