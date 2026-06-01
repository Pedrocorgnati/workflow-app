"""Builder do prompt de auto-recuperacao do red-listener.

Quando um listener-dot fica vermelho (failed) por uma falha SEMANTICA do
comando (BLOCKED, RESSALVAS, VERIFY_FAILED, EXIT_NONZERO, MISSING_ARG,
TIMEOUT) e o autocast estava ligado, o `MetricsBar` espera 2s e cola este
prompt no MESMO terminal que falhou, com Enter automatico.

Design do prompt v2 (2026-05-31): fortemente orientado a RESOLUCAO AUTONOMA.
O agente deve tentar resolver sem pedir ao usuario, emitir o notify de SUCESSO
(que re-arma o autocast automaticamente via _autocast_aborted_by_recovery) e
so escalar para relatorio ou pergunta em ultimo caso.

Fonte canonica do fluxo: ai-forge/rules/workflow-app-listeners.md (secao de
auto-recuperacao) + ai-forge/rules/llm-routing-div.md (canal->LLM).
Binding canal->LLM: interactive=Main LLM (radio), workspace=Kimi (T2),
workspace_xterm=Codex (T3).

Modulo PURO (sem Qt, sem IO) para ser trivialmente testavel.
"""

from __future__ import annotations

RECOVERY_REASONS: frozenset[str] = frozenset(
    {
        "BLOCKED",
        "RESSALVAS",
        "VERIFY_FAILED",
        "EXIT_NONZERO",
        "MISSING_ARG",
        "TIMEOUT",
    }
)

_VALID_CHANNELS: frozenset[str] = frozenset(
    {"interactive", "workspace", "workspace_xterm"}
)


def llm_for_channel(channel: str, main_llm: str) -> str:
    """Resolve qual LLM ocupa o canal.

    workspace      -> kimi  (Parallel Worker Kimi, T2)
    workspace_xterm-> codex (Parallel Worker Codex, T3)
    interactive    -> Main LLM (radio queue-div-main-llm): claude|codex|kimi
    """
    if channel == "workspace":
        return "kimi"
    if channel == "workspace_xterm":
        return "codex"
    return main_llm if main_llm in ("claude", "codex", "kimi") else "claude"


def _blue_signal_block(channel: str) -> str:
    """Bloco bash que emite o sinal AZUL (awaiting_user) para o canal."""
    return (
        f'wf_channel="${{WF_CHANNEL_OVERRIDE:-{channel}}}"\n'
        'wf_root="$PWD"\n'
        'while [ "$wf_root" != "/" ] && { [ ! -d "$wf_root/.claude/commands" ] '
        '|| [ ! -d "$wf_root/ai-forge" ] || [ ! -f "$wf_root/CLAUDE.md" ]; }; do\n'
        '  wf_root="${wf_root%/*}"; [ -n "$wf_root" ] || wf_root="/";\n'
        'done\n'
        '[ "$wf_root" != "/" ] && "${BASH:-bash}" '
        '"$wf_root/ai-forge/workflow-app/scripts/wf-notify.sh" '
        '--status awaiting_user "$wf_channel" 2>/dev/null || true'
    )


def _success_notify_block(channel: str) -> str:
    """Bloco bash minimo para emitir o notify de SUCESSO e re-armar o autocast.

    O agente cola e executa este bloco apos resolver o problema. O notify de
    sucesso: (a) remove o dot vermelho, (b) re-arma o autocast automaticamente
    via _autocast_aborted_by_recovery no MetricsBar.
    """
    return (
        f'wf_channel="${{WF_CHANNEL_OVERRIDE:-{channel}}}"\n'
        'wf_root="$PWD"\n'
        'while [ "$wf_root" != "/" ]; do\n'
        '  if [ -d "$wf_root/.claude/commands" ] && [ -d "$wf_root/ai-forge" ]'
        ' && [ -f "$wf_root/CLAUDE.md" ]'
        ' && [ -f "$wf_root/ai-forge/workflow-app/scripts/wf-notify.sh" ]; then\n'
        '    break\n'
        '  fi\n'
        '  wf_root="${wf_root%/*}"; [ -n "$wf_root" ] || wf_root="/"\n'
        'done\n'
        '[ "$wf_root" != "/" ] && "${BASH:-bash}" '
        '"$wf_root/ai-forge/workflow-app/scripts/wf-notify.sh" '
        '--status success --exit-code 0 "$wf_channel"'
    )


# Dica especifica por reason — instrucao concreta para o agente
_REASON_HINTS: dict[str, str] = {
    "BLOCKED": (
        "Um gate bloqueante foi acionado (PHASE-CONTRACTS, congruence-check ou "
        "temporality-check). Identifique qual condicao nao foi satisfeita, "
        "corrija-a (ajuste no delivery.json, MODULE-META.json ou arquivo alvo) "
        "e confirme que o gate passaria antes de emitir sucesso."
    ),
    "RESSALVAS": (
        "O review terminou com ressalvas que exigem decisao antes de continuar. "
        "Releia as ressalvas do output anterior, avalie se sao resolvíveis agora "
        "(ex: ajuste pontual de codigo, doc ou configuracao), corrija e confirme "
        "que os pontos criticos foram endereçados."
    ),
    "VERIFY_FAILED": (
        "A verificacao obrigatoria falhou (atomic-verifier, gate de QA, ou check "
        "de contrato). Identifique o que foi rejeitado no output anterior, corrija "
        "a causa raiz e, se possivel, reexecute a verificacao antes de emitir sucesso."
    ),
    "EXIT_NONZERO": (
        "O comando terminou com exit code diferente de zero. Veja o output de erro "
        "acima, identifique a causa (tipicamente erro de compilacao, falha de teste, "
        "ou comando inexistente) e corrija antes de emitir sucesso."
    ),
    "MISSING_ARG": (
        "Um argumento obrigatorio estava ausente. Tente inferir o valor correto do "
        "contexto disponivel nesta sessao (delivery.json, PROGRESS.md, task path "
        "visivel no output anterior). Se inferivel com certeza, reexecute com o "
        "argumento correto. Se nao tiver certeza, use o caminho PERGUNTAR abaixo."
    ),
    "TIMEOUT": (
        "O comando excedeu o timeout configurado. Avalie se o escopo pode ser "
        "reduzido (modulo especifico, subset de tasks) e reexecute com escopo menor. "
        "Se o escopo nao for reduzivel, gere o relatorio descrevendo o que ficou "
        "incompleto e o que o usuario precisa continuar manualmente."
    ),
}


def _ask_clause(llm: str, channel: str) -> str:
    """Clausula da alternativa PERGUNTAR — mecanismo por LLM."""
    if llm == "claude":
        return (
            "use /skill:auq-interview (modo inline). Esse comando JA emite o sinal "
            "azul automaticamente antes de cada pergunta. Aguarde a resposta antes "
            "de continuar."
        )
    return (
        "emita o sinal azul primeiro rodando este bloco bash uma vez:\n"
        "```bash\n"
        f"{_blue_signal_block(channel)}\n"
        "```\n"
        "Depois faca a pergunta em texto simples e aguarde a resposta."
    )


def build_recovery_prompt(*, llm: str, reason: str, channel: str) -> str:
    """Monta o prompt de auto-recuperacao colado no terminal que falhou.

    Args:
        llm: "claude" | "codex" | "kimi" — agente que ocupa o terminal.
        reason: motivo da falha (ex: BLOCKED, RESSALVAS, VERIFY_FAILED).
        channel: "interactive" | "workspace" | "workspace_xterm".

    Returns:
        Texto unico (multi-linha) pronto para colar no REPL do CLI.
        v2: orientado a resolucao autonoma. Agent deve tentar (a) sem pedir
        ao usuario; so escalona para (b)/(c) se impossivel.
    """
    if channel not in _VALID_CHANNELS:
        channel = "interactive"
    if llm not in ("claude", "codex", "kimi"):
        llm = "claude"
    reason = (reason or "FAILURE").strip() or "FAILURE"

    hint = _REASON_HINTS.get(reason, f"Diagnostique a causa da falha ({reason}) e corrija.")
    success_block = _success_notify_block(channel)
    report_path = f"blacksmith/recovery/{channel}-{reason}-<timestamp>.md"
    ask = _ask_clause(llm, channel)

    return (
        f"[AUTO-RECUPERACAO] Canal: {channel} | Falha: {reason}\n"
        "O autocast foi pausado. TENTE RESOLVER AGORA SEM PEDIR AO USUARIO.\n"
        "\n"
        f"[CONTEXTO DA FALHA: {reason}]\n"
        f"{hint}\n"
        "\n"
        "━━━ CAMINHO 1 — RESOLVER (preferido, autonomo) ━━━\n"
        "Se a falha for resolvivel nesta sessao:\n"
        "  1. Diagnostique rapidamente o que falhou (output acima).\n"
        "  2. Aplique a correcao diretamente (edit/write/bash).\n"
        "  3. Confirme que o problema foi resolvido.\n"
        "  4. Emita o notify de SUCESSO abaixo — isso remove o vermelho\n"
        "     e re-arma o autocast automaticamente:\n"
        "\n"
        "```bash\n"
        f"{success_block}\n"
        "```\n"
        "\n"
        "━━━ CAMINHO 2 — RELATORIO (se impossivel resolver agora) ━━━\n"
        "Se NAO for possivel resolver nesta sessao, crie um relatorio conciso\n"
        f"em `{report_path}` com:\n"
        "  - O que falhou e por que.\n"
        "  - O que o usuario precisa fazer passo a passo para resolver.\n"
        "NAO emita o notify de sucesso (o vermelho permanece ate o usuario agir).\n"
        "\n"
        "━━━ CAMINHO 3 — PERGUNTAR (ultima instancia) ━━━\n"
        f"Se precisar de input do usuario antes de agir, {ask}\n"
        "\n"
        "REGRAS: (1) Prefira o Caminho 1 — resolva sem pedir ajuda. "
        "(2) Zero Assumido: nao invente dados criticos; se tiver duvida sobre "
        "um valor especifico, use o Caminho 3 antes de agir. "
        "(3) Nao tente religar o autocast manualmente — o notify de SUCESSO "
        "do Caminho 1 ja faz isso automaticamente."
    )
