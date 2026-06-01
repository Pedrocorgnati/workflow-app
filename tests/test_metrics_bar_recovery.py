"""Integration tests for the red-listener auto-recovery in MetricsBar.

Mirrors the existing test_metrics_bar.py pattern: a real SignalBus + a
MetricsBar wired to it. The 2s timer is fired deterministically via
`_fire_recovery_prompt` rather than waiting wall-clock.

Migracao TASK 07 (loop 06-01-listener-recovery-command): o passo final de
`_fire_recovery_prompt` deixou de colar o prompt-cru por canal e passou a
emitir o sinal semantico `request_recovery_command(channel, reason,
context_file)` apos gravar um snapshot diagnostico (TASK 05). Os testes de
fire agora monkeypatcham `_repo_root_path` para um tmp_path para nao escrever
em `blacksmith/recovery/context/` do repo real.

Contract: ai-forge/rules/workflow-app-listeners.md (auto-recovery section)
+ signal_bus.request_recovery_command (channel/reason/context_file).
"""

from __future__ import annotations

import pytest

from workflow_app.metrics_bar.metrics_bar import MetricsBar
from workflow_app.signal_bus import SignalBus


@pytest.fixture()
def mb(qapp):
    bus = SignalBus()
    bar = MetricsBar(bus)
    bar._btn_autocast.setChecked(True)  # autocast ON (recovery precondition)
    return bar


def _capture_recovery_signal(bar):
    """Connect a sink to request_recovery_command and return the capture list
    of (channel, reason, context_file) tuples."""
    captured = []
    bar._signal_bus.request_recovery_command.connect(
        lambda ch, rs, cf: captured.append((ch, rs, cf))
    )
    return captured


def _force_failed(bar, channel, reason, autocast_on=True):
    bar._btn_autocast.setChecked(autocast_on)
    bar._recovery_attempted.discard(channel)
    bar._dot_for(channel).set_state("idle")
    bar._on_terminal_force_failed(channel, reason)


# ── Scheduling gates ─────────────────────────────────────────────────────── #


def test_semantic_failure_with_autocast_on_schedules_recovery(mb):
    _force_failed(mb, "interactive", "BLOCKED", autocast_on=True)
    timer = mb._recovery_timer.get("interactive")
    assert timer is not None and timer.isActive()
    assert mb._recovery_reason["interactive"] == "BLOCKED"


@pytest.mark.parametrize(
    "reason", ["RATE_LIMIT", "AUTH_INVALID_API_KEY", "EARLY_EXIT",
               "CREDIT_BALANCE_LOW", "USAGE_LIMIT_REACHED", "notify"],
)
def test_non_semantic_failure_does_not_schedule(mb, reason):
    _force_failed(mb, "interactive", reason, autocast_on=True)
    timer = mb._recovery_timer.get("interactive")
    assert not (timer and timer.isActive())


def test_autocast_off_does_not_schedule(mb):
    _force_failed(mb, "workspace", "BLOCKED", autocast_on=False)
    timer = mb._recovery_timer.get("workspace")
    assert not (timer and timer.isActive())


# ── Firing emits the semantic signal (TASK 07) ───────────────────────────── #


@pytest.mark.parametrize(
    "channel,reason",
    [
        ("interactive", "BLOCKED"),
        ("workspace", "RESSALVAS"),
        ("workspace_xterm", "VERIFY_FAILED"),
    ],
)
def test_fire_emits_request_recovery_command(mb, tmp_path, monkeypatch, channel, reason):
    monkeypatch.setattr(mb, "_repo_root_path", lambda: tmp_path)
    captured = _capture_recovery_signal(mb)
    # The old paste paths MUST stay silent now.
    paste = []
    mb._signal_bus.run_command_in_terminal.connect(paste.append)
    mb._signal_bus.run_command_in_workspace_xterm.connect(paste.append)
    mb._signal_bus.kimi_blue_arrow_dispatched.connect(
        lambda p, d: paste.append(p)
    )
    _force_failed(mb, channel, reason)
    mb._fire_recovery_prompt(channel)
    assert len(captured) == 1
    got_channel, got_reason, context_file = captured[0]
    assert got_channel == channel
    assert got_reason == reason
    # Contract: context_file exists on disk and ends in ".md".
    assert context_file.endswith(".md")
    assert (tmp_path / "blacksmith" / "recovery" / "context").is_dir()
    from pathlib import Path

    assert Path(context_file).is_file()
    assert channel in mb._recovery_attempted
    assert paste == []  # no raw prompt was pasted by MetricsBar


def test_fire_aborts_without_emit_when_reason_not_in_enum(mb, tmp_path, monkeypatch):
    monkeypatch.setattr(mb, "_repo_root_path", lambda: tmp_path)
    captured = _capture_recovery_signal(mb)
    toasts = []
    mb._signal_bus.toast_requested.connect(
        lambda msg, kind: toasts.append((msg, kind))
    )
    # Force red but with a reason outside RECOVERY_REASONS (no silent FAILURE
    # fallback): scheduler would not arm this, so set state directly.
    mb._dot_for("interactive").set_state("failed")
    mb._recovery_reason["interactive"] = "EARLY_EXIT"  # infra reason, excluded
    mb._fire_recovery_prompt("interactive")
    assert captured == []  # no signal emitted
    assert any(kind == "warning" for _, kind in toasts)  # Zero Silencio


def test_fire_aborts_without_emit_when_reason_missing(mb, tmp_path, monkeypatch):
    monkeypatch.setattr(mb, "_repo_root_path", lambda: tmp_path)
    captured = _capture_recovery_signal(mb)
    mb._dot_for("workspace").set_state("failed")
    mb._recovery_reason.pop("workspace", None)  # no reason recorded at all
    mb._fire_recovery_prompt("workspace")
    assert captured == []


def test_fire_aborts_when_snapshot_cannot_be_written(mb, monkeypatch):
    # repo_root None ⇒ snapshot helper returns None ⇒ no signal (cannot honour
    # the request_recovery_command contract without a valid context_file).
    monkeypatch.setattr(mb, "_repo_root_path", lambda: None)
    captured = _capture_recovery_signal(mb)
    toasts = []
    mb._signal_bus.toast_requested.connect(
        lambda msg, kind: toasts.append((msg, kind))
    )
    _force_failed(mb, "interactive", "BLOCKED")
    mb._fire_recovery_prompt("interactive")
    assert captured == []
    assert any(kind == "warning" for _, kind in toasts)
    # Loop guard still set before the abort (no infinite re-arm).
    assert "interactive" in mb._recovery_attempted


def test_snapshot_content_is_diagnostic(mb, tmp_path, monkeypatch):
    monkeypatch.setattr(mb, "_repo_root_path", lambda: tmp_path)
    captured = _capture_recovery_signal(mb)
    mb._signal_bus.main_llm_changed.emit("codex")
    _force_failed(mb, "interactive", "BLOCKED")
    mb._fire_recovery_prompt("interactive")
    from pathlib import Path

    body = Path(captured[0][2]).read_text(encoding="utf-8")
    assert "Recovery Context Snapshot" in body
    assert "channel: interactive" in body
    assert "reason: BLOCKED" in body
    assert "llm: codex" in body  # main_llm tracked into the snapshot


# ── LLM resolution per channel ───────────────────────────────────────────── #


def test_main_llm_changed_caches_for_interactive(mb):
    mb._signal_bus.main_llm_changed.emit("codex")
    assert mb._main_llm == "codex"
    assert mb._llm_for_channel("interactive") == "codex"
    # Workers are fixed regardless of Main LLM.
    assert mb._llm_for_channel("workspace") == "kimi"
    assert mb._llm_for_channel("workspace_xterm") == "codex"


def test_main_kimi_reason_carried_into_signal(mb, tmp_path, monkeypatch):
    # Post-migration: MetricsBar no longer phrases the prompt per Main LLM;
    # it emits (channel, reason, context_file) and the dispatch handler
    # (TASK 08) builds/validates the command. We only assert the reason and
    # the resolved LLM (snapshot) reflect Main Kimi in T1.
    monkeypatch.setattr(mb, "_repo_root_path", lambda: tmp_path)
    captured = _capture_recovery_signal(mb)
    mb._signal_bus.main_llm_changed.emit("kimi")
    _force_failed(mb, "interactive", "RESSALVAS")
    mb._fire_recovery_prompt("interactive")
    assert captured and captured[0][1] == "RESSALVAS"
    from pathlib import Path

    body = Path(captured[0][2]).read_text(encoding="utf-8")
    assert "llm: kimi" in body


# ── Loop guard ───────────────────────────────────────────────────────────── #


def test_loop_guard_blocks_second_recovery_in_same_streak(mb):
    mb._recovery_attempted.add("interactive")
    mb._btn_autocast.setChecked(True)
    mb._dot_for("interactive").set_state("idle")
    mb._on_terminal_force_failed("interactive", "BLOCKED")
    timer = mb._recovery_timer.get("interactive")
    assert not (timer and timer.isActive())


def test_recovery_reset_on_green_clears_guard(mb):
    mb._recovery_attempted.add("workspace")
    mb._on_dot_recovery_reset("workspace", False)  # busy=False ⇒ green/human-clear
    assert "workspace" not in mb._recovery_attempted


def test_recovery_reset_ignores_busy_true(mb):
    mb._recovery_attempted.add("workspace")
    mb._on_dot_recovery_reset("workspace", True)  # set_busy(True) must NOT clear
    assert "workspace" in mb._recovery_attempted


# ── Fire aborts when dot no longer red ───────────────────────────────────── #


def test_fire_aborts_if_dot_not_failed(mb):
    captured = _capture_recovery_signal(mb)
    mb._recovery_reason["interactive"] = "BLOCKED"
    mb._dot_for("interactive").set_state("idle")  # human cleared during the 2s
    mb._fire_recovery_prompt("interactive")
    assert not captured


# ── New dispatch / failure cancels a pending recovery timer ──────────────── #


def test_release_idle_lock_cancels_pending_recovery(mb):
    _force_failed(mb, "interactive", "BLOCKED")
    assert mb._recovery_timer["interactive"].isActive()
    mb._release_idle_lock("interactive")
    assert not mb._recovery_timer["interactive"].isActive()
