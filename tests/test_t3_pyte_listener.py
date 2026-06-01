"""Regression tests for the T3 (Codex) listener tripwires on the pyte engine.

2026-06-01: T3 deixou de ser um XtermOutputPanel (xterm.js/QWebEngine) e passou
a ser um OutputPanel pyte com `channel_override="workspace_xterm"` — os tres
terminais (T1/T2/T3) agora usam o mesmo engine. Estes testes pinam que a troca
de engine NAO reabriu os bugs que o XtermOutputPanel havia fechado em 2026-05-30
(silent-green / stuck-yellow no T3):

  * o canal logico continua "workspace_xterm" (dot/notify/recovery do Codex);
  * o idle timer heuristico arma para workspace_xterm (verde-por-silencio);
  * o early-exit watcher (Camada 3) dispara via arm_dispatch_window;
  * o scanner de padrao fatal (Camada 1) emite vermelho;
  * helpers (/clear, cd, launcher codex) ficam isentos de EARLY_EXIT;
  * o T3 NAO assina os sinais de dispatch do T2 (anti-eco).

Contrato: ai-forge/rules/workflow-app-listeners.md §3 + §15 + §16.1.
Paridade com tests/test_xterm_tripwire.py (suite legada do XtermOutputPanel).
"""

from __future__ import annotations

import pytest

from workflow_app.output_panel.output_panel import OutputPanel
from workflow_app.signal_bus import signal_bus


@pytest.fixture()
def panel(qapp):
    # T3 = OutputPanel pyte no canal workspace_xterm. NAO mostrado: o shell
    # so inicia em showEvent/ensure_shell_started, entao nenhum subprocesso e
    # spawneado aqui — os tripwires operam sobre _on_chunk/_on_idle_timeout.
    p = OutputPanel(workspace_mode=True, channel_override="workspace_xterm")
    yield p
    p.shutdown()


@pytest.fixture()
def capture():
    fails: list[tuple[str, str]] = []
    idles: list[str] = []
    _on_fail = lambda c, r: fails.append((c, r))
    _on_idle = idles.append
    signal_bus.terminal_force_failed.connect(_on_fail)
    signal_bus.terminal_force_idle.connect(_on_idle)
    yield fails, idles
    signal_bus.terminal_force_failed.disconnect(_on_fail)
    signal_bus.terminal_force_idle.disconnect(_on_idle)


def test_channel_is_workspace_xterm(panel):
    assert panel._channel == "workspace_xterm"
    assert panel._shell._extra_env["WF_CHANNEL_OVERRIDE"] == "workspace_xterm"


def test_idle_timer_arms_on_output(panel):
    # Verde-por-silencio: igual ao T1 (interactive), o T3 arma o idle timer a
    # cada chunk. Sem isto o dot do Codex ficaria preso em amarelo.
    assert not panel._idle_timer.isActive()
    panel._on_chunk("alguma saida do codex\n")
    assert panel._idle_timer.isActive()


def test_early_exit_after_dispatch_emits_red(panel, capture):
    fails, idles = capture
    panel.arm_dispatch_window("/loop:iteraction:execute-task --task 1")
    panel._on_chunk("boom\n")  # poucos bytes (< 512)
    panel._on_idle_timeout()
    assert ("workspace_xterm", "EARLY_EXIT") in fails
    assert "workspace_xterm" not in idles  # NAO e silent-green


def test_enough_output_goes_green_not_red(panel, capture):
    fails, idles = capture
    panel.arm_dispatch_window("cmd")
    panel._on_chunk("x" * 600)  # > 512 bytes => comando real rodou
    panel._on_idle_timeout()
    assert "workspace_xterm" in idles
    assert not any(c == "workspace_xterm" for c, _ in fails)


def test_no_dispatch_goes_green(panel, capture):
    fails, idles = capture
    panel._dispatch_ts = None
    panel._on_chunk("idle prompt repaint")
    panel._on_idle_timeout()
    assert "workspace_xterm" in idles
    assert not any(c == "workspace_xterm" for c, _ in fails)


def test_fatal_pattern_emits_red(panel, capture):
    fails, _ = capture
    panel.arm_dispatch_window("cmd")
    panel._on_chunk("Error: 429 too many requests (rate limit)")
    assert ("workspace_xterm", "RATE_LIMIT") in fails


def test_arm_dispatch_resets_failure_window(panel):
    panel.arm_dispatch_window("cmd-a")
    panel._on_chunk("rate limit")
    assert panel._last_failure_reason == "RATE_LIMIT"
    # Novo dispatch reabre a janela (paridade com _run_shell_command).
    panel.arm_dispatch_window("cmd-b")
    assert panel._last_failure_reason is None
    assert panel._bytes_since_dispatch == 0


def test_helper_command_does_not_open_early_exit_window(panel, capture):
    fails, idles = capture
    panel.arm_dispatch_window("/clear")
    assert panel._dispatch_ts is None
    panel._on_idle_timeout()
    assert "workspace_xterm" in idles
    assert not any(c == "workspace_xterm" for c, _ in fails)


def test_codex_launcher_helper_does_not_open_early_exit_window(panel, capture):
    # O launcher `codex-high` (metrics_bar emite em run_command_in_workspace_xterm)
    # e helper: nao deve armar EARLY_EXIT (o Codex sobe e fica no prompt).
    fails, idles = capture
    panel.arm_dispatch_window("codex-high")
    assert panel._dispatch_ts is None
    panel._on_idle_timeout()
    assert "workspace_xterm" in idles
    assert not any(c == "workspace_xterm" for c, _ in fails)


def test_t3_does_not_subscribe_to_t2_dispatch(panel):
    # Anti-eco: o T3 (workspace_xterm) NAO assina os sinais de dispatch do T2
    # (workspace). Se assinasse, este emit armaria _dispatch_ts via
    # _run_shell_command. Permanecendo None, provamos que o guard funciona.
    assert panel._dispatch_ts is None
    signal_bus.run_command_in_workspace_terminal.emit("echo from T2")
    assert panel._dispatch_ts is None
