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
    llm_source_for_channel,
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


def test_legacy_regime_workspace_defaults_to_kimi():
    """Sem sinal de ocupacao (t2_llm=None), T2 continua respondendo `kimi`.

    Regime legado = kill-switch SF_PARALLEL_WORKERS_V2 desligado, onde qwen e
    grok nem aparecem na UI e nenhuma ocupacao chega. G-2 (nao-regressao): o
    comportamento observavel tem que ser byte-identico ao anterior ao gap C24.
    """
    assert llm_for_channel("workspace", "claude") == "kimi"
    assert llm_for_channel("workspace", "codex") == "kimi"


def test_legacy_regime_workspace_xterm_defaults_to_codex():
    assert llm_for_channel("workspace_xterm", "kimi") == "codex"
    assert llm_for_channel("workspace_xterm", "claude") == "codex"


def test_occupancy_overrides_legacy_default():
    """G-1 (verdade): com ocupacao real, o par responde quem esta la."""
    assert llm_for_channel("workspace", "claude", t2_llm="qwen") == "qwen"
    assert llm_for_channel("workspace_xterm", "claude", t3_llm="grok") == "grok"
    assert llm_for_channel("workspace", "claude", t2_llm="kimi") == "kimi"


def test_empty_pair_falls_back_marked():
    """Par vazio nao vira certeza: cai no default, mas marcado como fallback."""
    src = llm_source_for_channel("workspace", "claude", t2_llm="")
    assert src.llm == "kimi"
    assert src.is_fallback
    assert "nenhum worker marcado" in src.note


def test_no_signal_and_empty_pair_have_distinct_notes():
    """G-3 (Zero Silencio): as duas ausencias sao distinguiveis no texto."""
    sem_sinal = llm_source_for_channel("workspace", "claude")
    vazio = llm_source_for_channel("workspace", "claude", t2_llm="")
    assert sem_sinal.is_fallback and vazio.is_fallback
    assert sem_sinal.note != vazio.note


def test_prompt_header_carries_fallback_note():
    """A marca de fallback chega ao texto colado, nao morre no dataclass."""
    src = llm_source_for_channel("workspace", "claude")
    prompt = build_recovery_prompt(
        llm="kimi", reason="BLOCKED", channel="workspace", llm_source=src
    )
    assert prompt.splitlines()[0] == f"[{src.note}]"
    assert "[AUTO-RECUPERACAO]" in prompt


def test_prompt_header_has_no_note_when_live():
    src = llm_source_for_channel("workspace", "claude", t2_llm="qwen")
    prompt = build_recovery_prompt(
        llm="qwen", reason="BLOCKED", channel="workspace", llm_source=src
    )
    assert prompt.splitlines()[0].startswith("[AUTO-RECUPERACAO]")
    assert "LLM: qwen" in prompt.splitlines()[0]


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
    # Slug canonico: o comando vive em .claude/commands/tools/auq-interview.md.
    # "/skill:auq-interview" nunca existiu em disco (nao ha
    # .claude/commands/skill/auq-interview.md) - era slug morto.
    assert "/tools:auq-interview" in p
    assert "/skill:auq-interview" not in p
    # Claude's skill self-signals blue — no manual wf-notify block needed.
    assert "wf-notify.sh --status awaiting_user" not in p


@pytest.mark.parametrize("llm,channel", [
    ("codex", "workspace_xterm"),
    ("kimi", "workspace"),
])
def test_codex_kimi_emit_manual_blue_signal_and_visible_marker(llm, channel):
    p = build_recovery_prompt(llm=llm, reason="VERIFY_FAILED", channel=channel)
    # Manual blue signal block present...
    assert "wf-notify.sh" in p
    assert "--status awaiting_user" in p
    # ...phrased for the right channel default...
    assert f"WF_CHANNEL_OVERRIDE:-{channel}" in p
    # ...the question renders via a VISIBLE marker block (FIX-CL2-CASE020:
    # evita azul orfao — dot azul sem pergunta na tela)...
    assert ">>> PERGUNTA AO OPERADOR <<<" in p
    assert "clique no dot AZUL" in p
    # ...and explicitly NOT routed through the Claude-only command.
    assert "/tools:auq-interview" not in p
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
    assert "/tools:auq-interview" in p


def test_empty_reason_falls_back_to_failure_token():
    p = build_recovery_prompt(llm="claude", reason="", channel="interactive")
    assert "FAILURE" in p


# -- CAMINHO 3: entrevista -> correcao -> verde (loop de fechamento) -------- #


@pytest.mark.parametrize("llm,channel", [
    ("claude", "interactive"),
    ("codex", "workspace_xterm"),
    ("kimi", "workspace"),
])
def test_ask_path_closes_the_loop_back_to_green(llm, channel):
    """PERGUNTAR nao termina na resposta: aplica, valida, e so entao emite verde."""
    p = build_recovery_prompt(llm=llm, reason="BLOCKED", channel=channel)
    assert "o ciclo NAO acaba na resposta" in p
    assert "Aplique as correcoes que as respostas destravaram" in p
    assert "Valide" in p
    # Guarda: resposta obtida != correcao aplicada.
    assert "Resposta obtida nao e correcao" in p


def test_ask_path_trigger_is_human_decision_not_generic_doubt():
    p = build_recovery_prompt(llm="claude", reason="RESSALVAS", channel="interactive")
    assert "decisao humana" in p
    assert "so o operador pode dar" in p
    # Barreira tecnica continua sendo RELATORIO, nao entrevista.
    assert "Barreira TECNICA" in p


def test_claude_branch_forbids_running_auq_final_phase():
    """A FASE FINAL do auq-interview emite success e pintaria verde cedo demais."""
    p = build_recovery_prompt(llm="claude", reason="BLOCKED", channel="interactive")
    assert "NAO execute a FASE FINAL do /tools:auq-interview" in p


def test_claude_branch_calls_auq_without_arguments():
    """Argumento posicional ativa modo direto (escreve arquivo); queremos inline."""
    p = build_recovery_prompt(llm="claude", reason="BLOCKED", channel="interactive")
    assert "SEM argumento" in p
    assert "modo inline" in p
