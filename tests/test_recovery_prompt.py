"""Pure unit tests for the red-listener auto-recovery prompt builder.

No Qt — these exercise workflow_app.metrics_bar.recovery_prompt directly.
Contract: ai-forge/rules/workflow-app-listeners.md (auto-recovery section)
and ai-forge/rules/llm-routing-div.md (channel→LLM binding).
"""

from __future__ import annotations

import pytest

from workflow_app.metrics_bar.recovery_prompt import (
    RECOVERY_REASONS,
    build_recovery_prompt,
    llm_for_channel,
)


# ── RECOVERY_REASONS allowlist ────────────────────────────────────────────── #


def test_semantic_reasons_in_allowlist():
    for reason in ("BLOCKED", "RESSALVAS", "VERIFY_FAILED", "EXIT_NONZERO",
                   "MISSING_ARG", "TIMEOUT"):
        assert reason in RECOVERY_REASONS


@pytest.mark.parametrize(
    "reason",
    ["AUTH_INVALID_API_KEY", "CREDIT_BALANCE_LOW", "USAGE_LIMIT_REACHED",
     "RATE_LIMIT", "EARLY_EXIT", "AUTH_LOGIN_EXPIRED"],
)
def test_infra_auth_reasons_excluded(reason):
    """Infra/auth tripwires must NOT auto-recover (CLI may be dead)."""
    assert reason not in RECOVERY_REASONS


# ── llm_for_channel: channel→LLM binding ─────────────────────────────────── #


def test_workspace_is_always_kimi():
    assert llm_for_channel("workspace", "claude") == "kimi"
    assert llm_for_channel("workspace", "codex") == "kimi"


def test_workspace_xterm_is_always_codex():
    assert llm_for_channel("workspace_xterm", "kimi") == "codex"
    assert llm_for_channel("workspace_xterm", "claude") == "codex"


@pytest.mark.parametrize("main", ["claude", "codex", "kimi"])
def test_interactive_follows_main_llm(main):
    assert llm_for_channel("interactive", main) == main


def test_interactive_unknown_main_falls_back_to_claude():
    assert llm_for_channel("interactive", "garbage") == "claude"


# ── build_recovery_prompt: structure ─────────────────────────────────────── #


@pytest.mark.parametrize("llm", ["claude", "codex", "kimi"])
@pytest.mark.parametrize("channel", ["interactive", "workspace", "workspace_xterm"])
def test_prompt_has_three_alternatives(llm, channel):
    # v2 (2026-05-31): rotulos migraram de "(a)/(b)/(c)" para
    # "CAMINHO 1/2/3 — RESOLVER/RELATORIO/PERGUNTAR". Assercoes desacopladas
    # do tracejado (em-dash) para robustez.
    p = build_recovery_prompt(llm=llm, reason="BLOCKED", channel=channel)
    assert "CAMINHO 1" in p and "RESOLVER" in p
    assert "CAMINHO 2" in p and "RELATORIO" in p
    assert "CAMINHO 3" in p and "PERGUNTAR" in p


def test_prompt_carries_reason_and_channel():
    p = build_recovery_prompt(llm="claude", reason="RESSALVAS", channel="workspace")
    assert "RESSALVAS" in p
    assert "workspace" in p


# ── build_recovery_prompt: per-LLM ask mechanism (alternative c) ─────────── #


def test_claude_uses_auq_interview_and_no_manual_blue_block():
    p = build_recovery_prompt(llm="claude", reason="BLOCKED", channel="interactive")
    assert "/skill:auq-interview" in p
    # Claude's skill self-signals blue — no manual wf-notify block needed.
    assert "wf-notify.sh --status awaiting_user" not in p


@pytest.mark.parametrize("llm,channel", [
    ("codex", "workspace_xterm"),
    ("kimi", "workspace"),
])
def test_codex_kimi_emit_manual_blue_signal_and_plain_text(llm, channel):
    p = build_recovery_prompt(llm=llm, reason="VERIFY_FAILED", channel=channel)
    # Manual blue signal block present...
    assert "wf-notify.sh" in p
    assert "--status awaiting_user" in p
    # ...phrased for the right channel default...
    assert f"WF_CHANNEL_OVERRIDE:-{channel}" in p
    # ...and explicitly NOT routed through the Claude-only skill.
    assert "/skill:auq-interview" not in p


def test_report_path_namespaced_by_channel_and_reason():
    p = build_recovery_prompt(llm="codex", reason="BLOCKED", channel="workspace_xterm")
    assert "blacksmith/recovery/workspace_xterm-BLOCKED-" in p


# ── defensive normalization ──────────────────────────────────────────────── #


def test_unknown_channel_defaults_interactive():
    # Canal invalido normaliza para "interactive"; o header v2 imprime
    # "Canal: interactive" (antes: "canal interactive" em prosa).
    p = build_recovery_prompt(llm="claude", reason="BLOCKED", channel="bogus")
    assert "Canal: interactive" in p


def test_unknown_llm_defaults_claude():
    p = build_recovery_prompt(llm="bogus", reason="BLOCKED", channel="interactive")
    assert "/skill:auq-interview" in p


def test_empty_reason_falls_back_to_failure_token():
    p = build_recovery_prompt(llm="claude", reason="", channel="interactive")
    assert "FAILURE" in p
