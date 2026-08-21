"""Conjunto FECHADO de flags MCP suportadas (fonte canonica unica).

Qualquer token fora deste conjunto e ignorado por ``render_with_mcp_flags``
e pelo ``FlagsPanel``. Adicionar ou remover literais exige versao nova deste
modulo (Zero Assumido, MF-01, MF-02).

MF-01: ``opus`` e ``sonnet`` sao variantes de modelo do provider ``claude``,
nao providers independentes.
MF-02: nao existe flag ``--claude`` (delegar para Claude a partir de Claude
e no-op).

Item 005 (loop 08-17-systemforge-multillm-gaps-refactor): o TAMANHO do
conjunto passou a ser decidido pelo kill-switch dedicado, consultado aqui
somente por ``llm_flags_v2_enabled()`` (boot-frozen, fail-closed; o nome da
env var vive uma unica vez, em ``feature_flags``). Ausente/off = 2 literais
legados
(``--codex`` e ``--kimi``, tabela C26); ``"1"`` = os literais canonicos
de thinking/execution (capacidade de raciocinio, nao o CLI do T1).
Todas as demais estruturas deste modulo sao DERIVADAS do conjunto vigente,
nunca reescritas por regime — assim os dois regimes nao podem divergir.

Este modulo continua puro: importa apenas ``workflow_app.config.feature_flags``
(que e Qt-free) e nao toca ``os.environ`` diretamente.
"""

from __future__ import annotations

from workflow_app.config.feature_flags import llm_flags_v2_enabled

# Ordem CANONICA de render na UI. Nao e alfabetica: coluna thinking (mais
# poderoso) e depois coluna execution. `queue-div-main-llm` ficou so com o
# CLI de terminal; a capacidade de raciocinio vive aqui.
_THINKING_FLAG_ORDER: tuple[str, ...] = (
    "--fable",
    "--opus",
    "--codex-ultra",
    "--kimi-k3",
    "--grok-xhigh",
)
_EXECUTION_FLAG_ORDER: tuple[str, ...] = (
    "--grok",
    "--sonnet",
    "--kimi",
    "--qwen",
    "--codex",
)
_FULL_FLAG_CANONICAL_ORDER: tuple[str, ...] = (
    _THINKING_FLAG_ORDER + _EXECUTION_FLAG_ORDER
)

# Roster legado (kill-switch ausente/off): so os 2 literais que existiam
# antes do pacote multi-LLM.
_LEGACY_MCP_FLAGS: frozenset[str] = frozenset({"--codex", "--kimi"})

# Mapeamento flag -> provider/Main compativel (superset; filtrado abaixo).
_FULL_FLAG_LITERAL_TO_MAIN: dict[str, str] = {
    "--fable": "claude",
    "--opus": "claude",
    "--codex-ultra": "codex",
    "--kimi-k3": "kimi",
    "--grok-xhigh": "grok",
    "--grok": "grok",
    "--sonnet": "claude",
    "--kimi": "kimi",
    "--qwen": "qwen",
    "--codex": "codex",
}

# Flags por terminal de delegacao (superset; interseccionado abaixo).
# T1 (Claude) aceita todas; T2 recebe kimi/qwen; T3 recebe codex/grok.
_FULL_FLAGS_BY_TERMINAL: dict[str, frozenset[str]] = {
    "T1": frozenset(_FULL_FLAG_CANONICAL_ORDER),
    "T2": frozenset({"--kimi", "--kimi-k3", "--qwen"}),
    "T3": frozenset({"--codex", "--codex-ultra", "--grok", "--grok-xhigh"}),
}

# Provedores que tornam uma flag redundante (flag == provider do Main).
# Variantes de claude (--fable/--opus/--sonnet) nao sao redundantes sob
# Main claude: o Main escolhe o CLI do T1, a flag escolhe o raciocinio.
_FULL_REDUNDANT_FLAG_MAINS: dict[str, str] = {
    "--kimi": "kimi",
    "--kimi-k3": "kimi",
    "--codex": "codex",
    "--codex-ultra": "codex",
    "--qwen": "qwen",
    "--grok": "grok",
    "--grok-xhigh": "grok",
}

# ── Conjunto vigente (decidido no boot pelo kill-switch) ─────────────── #
_SUPPORTED_MCP_FLAGS: frozenset[str] = (
    frozenset(_FULL_FLAG_CANONICAL_ORDER)
    if llm_flags_v2_enabled()
    else _LEGACY_MCP_FLAGS
)

_FLAG_CANONICAL_ORDER: tuple[str, ...] = (
    tuple(
        flag for flag in _FULL_FLAG_CANONICAL_ORDER if flag in _SUPPORTED_MCP_FLAGS
    )
    if llm_flags_v2_enabled()
    else ("--codex", "--kimi")
)

# Guarda de paridade: a ordem canonica e o conjunto fechado tem que descrever
# exatamente os mesmos literais. Adicionar um sem o outro e bug de import.
# Vale nos DOIS regimes porque ambas as estruturas sao derivadas.
assert frozenset(_FLAG_CANONICAL_ORDER) == _SUPPORTED_MCP_FLAGS, (
    "_FLAG_CANONICAL_ORDER divergiu de _SUPPORTED_MCP_FLAGS"
)

_FLAG_LITERAL_TO_MAIN: dict[str, str] = {
    flag: main
    for flag, main in _FULL_FLAG_LITERAL_TO_MAIN.items()
    if flag in _SUPPORTED_MCP_FLAGS
}

_FLAGS_BY_TERMINAL: dict[str, frozenset[str]] = {
    terminal: flags & _SUPPORTED_MCP_FLAGS
    for terminal, flags in _FULL_FLAGS_BY_TERMINAL.items()
}

_REDUNDANT_FLAG_MAINS: dict[str, str] = {
    flag: main
    for flag, main in _FULL_REDUNDANT_FLAG_MAINS.items()
    if flag in _SUPPORTED_MCP_FLAGS
}
