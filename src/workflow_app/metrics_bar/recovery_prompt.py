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
Binding canal->LLM: interactive=Main LLM (radio), workspace=worker marcado do
par T2 (mimo|kimi|qwen), workspace_xterm=worker marcado do par T3 - com
FALLBACK MARCADO no texto quando a ocupacao do par ainda nao chegou. A
resolucao nao mora mais aqui: delega a
`metrics_bar/channel_llm.resolve_channel_llm` (gap C24), inclusive o default
do par T2 vazio, que o chamador passa por `t2_default`
(`channel_llm.t2_fallback_default`).

Modulo PURO (sem Qt, sem IO) para ser trivialmente testavel.
"""

from __future__ import annotations

from workflow_app.metrics_bar.channel_llm import (
    MAIN_ROSTER,
    T2_ROSTER,
    T3_ROSTER,
    ChannelLLM,
    resolve_channel_llm,
)

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
# NAO adicionar "NO_VERDICT" aqui. NO_VERDICT (emitido por
# .claude/hooks/stop-autocast-backstop.sh quando o turno acaba sem o bloco
# "FASE FINAL - Autocast contract") e deliberadamente NAO-recuperavel: o defeito
# e do proprio agente que esqueceu de sinalizar, e auto-recuperar remendaria em
# silencio exatamente o que precisa ficar visivel ao operador. Vermelho persiste
# ate clique humano. Ver ai-forge/rules/listener-vermelho.md.

_VALID_CHANNELS: frozenset[str] = frozenset(
    {"interactive", "workspace", "workspace_xterm"}
)


def llm_for_channel(
    channel: str,
    main_llm: str,
    *,
    t2_llm: str | None = None,
    t3_llm: str | None = None,
    t2_default: str | None = None,
) -> str:
    """Resolve qual LLM ocupa o canal (delega ao resolver unico).

    workspace       -> worker marcado do par T2 (mimo|kimi|qwen); sem
                       ocupacao conhecida, cai em `t2_default` (mimo com a
                       MiMo habilitada; `None` = default legado `kimi`).
    workspace_xterm -> worker marcado do par T3 (codex|grok); sem ocupacao
                       conhecida, cai no default legado `codex`.
    interactive     -> Main LLM (radio queue-div-main-llm): qualquer slug de
                       `channel_llm.MAIN_ROSTER`
    qualquer outro  -> "claude" (o prompt SEMPRE precisa de um destinatario;
                       contrato deliberadamente divergente do de
                       `recovery_context.llm_for_channel`, que devolve
                       INDISPONIVEL porque o snapshot nunca pode inventar um).

    `t2_llm`/`t3_llm` sao keyword-only com default `None` para que os callsites
    anteriores a C24 continuem compilando - e caiam no fallback DOCUMENTADO em
    vez de num mapa fixo que mente em silencio. Quem precisa saber se o valor e
    fallback usa `llm_source_for_channel`.
    """
    return resolve_channel_llm(
        channel,
        main_llm=main_llm,
        t2_llm=t2_llm,
        t3_llm=t3_llm,
        t2_default=t2_default,
        unmapped="claude",
    ).llm


def llm_source_for_channel(
    channel: str,
    main_llm: str,
    *,
    t2_llm: str | None = None,
    t3_llm: str | None = None,
    t2_default: str | None = None,
) -> ChannelLLM:
    """Igual a `llm_for_channel`, mas devolve o resultado TIPADO.

    Quem monta texto para o operador (cabecalho do prompt, toast, linha
    `- llm:` do snapshot) precisa distinguir ocupacao viva de default legado -
    caso contrario o fallback vira certeza fingida (Zero Silencio).
    """
    return resolve_channel_llm(
        channel,
        main_llm=main_llm,
        t2_llm=t2_llm,
        t3_llm=t3_llm,
        t2_default=t2_default,
        unmapped="claude",
    )


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
    """Clausula da alternativa PERGUNTAR — mecanismo por LLM.

    MiMo, Qwen e Grok caem DE PROPOSITO no ramo generico (bloco azul +
    marcador `>>> PERGUNTA AO OPERADOR <<<`): nenhum deles tem
    `/tools:auq-interview`, que e um slash-command Claude. Registrado
    explicitamente para que a ausencia deles no ramo `claude` nao pareca
    omissao de C24.
    """
    if llm == "claude":
        return (
            "rode /tools:auq-interview no proprio terminal, SEM argumento (argumento "
            "posicional ativa o modo direto, que escreve arquivo; queremos o modo "
            "inline). Ele JA emite o sinal azul automaticamente antes de cada "
            "pergunta — nao rode bloco azul manual junto. Leve TODAS as duvidas "
            "bloqueantes de uma vez (AskUserQuestion aceita ate 4 por chamada). "
            "NAO execute a FASE FINAL do /tools:auq-interview: ela emite success e "
            "pintaria o dot de verde antes de a correcao existir."
        )
    return (
        "emita o sinal azul primeiro rodando este bloco bash uma vez:\n"
        "```bash\n"
        f"{_blue_signal_block(channel)}\n"
        "```\n"
        "Depois faca a pergunta ao operador de forma VISIVEL e inequivoca. "
        "O azul fica ORFAO (dot azul sem pergunta na tela) se a pergunta nao "
        "renderizar; portanto imprima OBRIGATORIAMENTE um bloco-marcador "
        "destacado, exatamente neste formato, e so entao aguarde a resposta:\n"
        "```\n"
        ">>> PERGUNTA AO OPERADOR <<<\n"
        "{sua pergunta, em uma linha}\n"
        "Responda no terminal e clique no dot AZUL para liberar o autocast.\n"
        "```"
    )


def build_recovery_prompt(
    *,
    llm: str,
    reason: str,
    channel: str,
    llm_source: ChannelLLM | None = None,
) -> str:
    """Monta o prompt de auto-recuperacao colado no terminal que falhou.

    Args:
        llm: agente que ocupa o terminal — qualquer slug de `MAIN_ROSTER`,
            `T2_ROSTER` ou `T3_ROSTER` (claude, codex, mimo, kimi, qwen, grok).
        reason: motivo da falha (ex: BLOCKED, RESSALVAS, VERIFY_FAILED).
        channel: "interactive" | "workspace" | "workspace_xterm".
        llm_source: resultado tipado de `llm_source_for_channel`, quando o
            chamador o tem. Fallback marcado prefixa o cabecalho; ausencia do
            argumento nao inventa marca nenhuma.

    Returns:
        Texto unico (multi-linha) pronto para colar no REPL do CLI.
        v2: orientado a resolucao autonoma. Agent deve tentar (a) sem pedir
        ao usuario; so escalona para (b)/(c) se impossivel.
    """
    if channel not in _VALID_CHANNELS:
        channel = "interactive"
    # Uniao dos rosters dos tres canais (Main + par T2 + par T3), nao so o
    # Main. O clamp anterior a ("claude", "codex", "kimi") era C24
    # reaparecendo DENTRO do builder: um Qwen corretamente resolvido no T2
    # ainda viraria "claude" aqui. A uniao impede que um slug valido de par
    # (ex.: mimo no T2) volte a ser clampado se um dia faltar no Main.
    if llm not in (MAIN_ROSTER | T2_ROSTER | T3_ROSTER):
        llm = "claude"
    reason = (reason or "FAILURE").strip() or "FAILURE"
    fallback_note = ""
    if llm_source is not None and llm_source.is_fallback and llm_source.note:
        fallback_note = f"[{llm_source.note}]\n"

    hint = _REASON_HINTS.get(reason, f"Diagnostique a causa da falha ({reason}) e corrija.")
    success_block = _success_notify_block(channel)
    report_path = f"blacksmith/recovery/{channel}-{reason}-<timestamp>.md"
    ask = _ask_clause(llm, channel)

    return (
        f"{fallback_note}"
        f"[AUTO-RECUPERACAO] Canal: {channel} | Falha: {reason} | LLM: {llm}\n"
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
        "━━━ CAMINHO 3 — PERGUNTAR (quando a barreira e decisao humana) ━━━\n"
        "Se NAO conseguir resolver E o motivo for que a correcao depende de uma\n"
        "resposta ou decisao que so o operador pode dar (escopo, prioridade,\n"
        "comportamento esperado, valor de configuracao, qual de dois caminhos\n"
        f"incompativeis seguir), {ask}\n"
        "\n"
        "Depois que o operador responder, o ciclo NAO acaba na resposta:\n"
        "  1. Aplique as correcoes que as respostas destravaram.\n"
        "  2. Valide (reexecute o gate/teste/condicao que falhou).\n"
        "  3. Validou -> emita o notify de SUCESSO do Caminho 1 (verde).\n"
        "  4. Nao validou -> NAO emita sucesso. Resposta obtida nao e correcao\n"
        "     aplicada; caia para o Caminho 2 (RELATORIO).\n"
        "\n"
        "REGRAS: (1) Prefira o Caminho 1 — resolva sem pedir ajuda. "
        "(2) Zero Assumido: nao invente dados criticos; se tiver duvida sobre "
        "um valor especifico, use o Caminho 3 antes de agir. "
        "(3) Barreira TECNICA (credencial, rede, permissao, ferramenta) e "
        "Caminho 2; barreira de DECISAO HUMANA e Caminho 3 — nao escreva "
        "relatorio pedindo ao operador que decida algo que ele responderia "
        "agora no terminal aberto. "
        "(4) Nao tente religar o autocast manualmente — o notify de SUCESSO "
        "do Caminho 1 ja faz isso automaticamente."
    )
