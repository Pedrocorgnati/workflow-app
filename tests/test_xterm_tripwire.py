"""Regression tests for the T3 (XtermOutputPanel) failure tripwires.

Before 2026-05-30 the workspace_xterm panel had NO fatal-pattern scanner and
NO early-exit watcher: a Codex worker crash-before-notify let the 2s idle
timer flip the dot straight to GREEN (silent-green; autocast advanced as if
the command had succeeded). Gap confirmed by /mcp:kimi adversarial review.
These tests pin the ported tripwires (parity with OutputPanel T1/T2).

Contract: ai-forge/rules/workflow-app-listeners.md §3 + §15.
"""

from __future__ import annotations

import pytest

from workflow_app.signal_bus import signal_bus


@pytest.fixture()
def panel(qapp):
    # Imported lazily: QtWebEngine pulls heavy deps; keep import local so the
    # rest of the suite collects even where WebEngine is unavailable.
    from workflow_app.output_panel.xterm_output_panel import XtermOutputPanel

    return XtermOutputPanel(workspace_mode=True)


@pytest.fixture()
def capture():
    fails: list[tuple[str, str]] = []
    idles: list[str] = []
    signal_bus.terminal_force_failed.connect(lambda c, r: fails.append((c, r)))
    signal_bus.terminal_force_idle.connect(idles.append)
    yield fails, idles


def test_early_exit_after_dispatch_emits_red(panel, capture):
    fails, idles = capture
    panel._note_dispatch("/loop:iteraction:execute-task --task 1")
    panel._on_shell_output("boom\n")  # few bytes
    panel._on_idle_timeout()
    assert ("workspace_xterm", "EARLY_EXIT") in fails
    assert "workspace_xterm" not in idles  # NOT silent-green


def test_enough_output_goes_green_not_red(panel, capture):
    fails, idles = capture
    panel._note_dispatch("cmd")
    panel._on_shell_output("x" * 3000)  # > 2048 bytes ⇒ real command ran
    panel._on_idle_timeout()
    assert "workspace_xterm" in idles
    assert not any(c == "workspace_xterm" for c, _ in fails)


def test_no_dispatch_goes_green(panel, capture):
    fails, idles = capture
    panel._dispatch_ts = None
    panel._on_shell_output("idle prompt repaint")
    panel._on_idle_timeout()
    assert "workspace_xterm" in idles
    assert not fails


def test_fatal_pattern_emits_red(panel, capture):
    fails, _ = capture
    panel._note_dispatch("cmd")
    panel._on_shell_output("Error: 429 too many requests (rate limit)")
    assert ("workspace_xterm", "RATE_LIMIT") in fails


def test_soft_pattern_suppressed_after_stream(panel, capture):
    # Regressao casos 004/010/013 (paridade T3 com OutputPanel): depois de
    # kilobytes de output benigno, uma mencao a rate-limit/auth e CONTEUDO
    # renderizado, nao crash do CLI — pattern soft NAO pode forcar vermelho.
    fails, _ = capture
    panel._note_dispatch("cmd")
    panel._on_shell_output("x" * 3000)  # passa do _EARLY_EXIT_BYTES_THRESHOLD
    panel._on_shell_output(
        "Error: 429 too many requests (rate limit); Unauthorized origin rejected"
    )
    assert not any(c == "workspace_xterm" for c, _ in fails)


def test_fatal_pattern_dedupe_same_reason(panel, capture):
    fails, _ = capture
    panel._note_dispatch("cmd")
    panel._on_shell_output("rate limit hit")
    n = len([f for f in fails if f[1] == "RATE_LIMIT"])
    panel._on_shell_output("rate limit repaint again")
    n2 = len([f for f in fails if f[1] == "RATE_LIMIT"])
    assert n == 1 and n2 == 1


def test_note_dispatch_resets_failure_window(panel):
    panel._note_dispatch("cmd-a")
    panel._on_shell_output("rate limit")
    assert panel._last_failure_reason == "RATE_LIMIT"
    # A new dispatch reopens the window (parity with OutputPanel._run_shell_command).
    panel._note_dispatch("cmd-b")
    assert panel._last_failure_reason is None
    assert panel._bytes_since_dispatch == 0


def test_helper_command_does_not_open_early_exit_window(panel, capture):
    fails, idles = capture
    panel._note_dispatch("/clear")
    assert panel._dispatch_ts is None
    panel._on_idle_timeout()
    assert "workspace_xterm" in idles
    assert not any(c == "workspace_xterm" for c, _ in fails)


def test_helper_command_cd_does_not_open_early_exit_window(panel, capture):
    fails, idles = capture
    panel._note_dispatch("cd /tmp")
    assert panel._dispatch_ts is None
    panel._on_idle_timeout()
    assert "workspace_xterm" in idles
    assert not any(c == "workspace_xterm" for c, _ in fails)
