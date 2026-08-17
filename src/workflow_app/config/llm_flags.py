"""Conjunto FECHADO de flags MCP suportadas (fonte canonica unica).

Qualquer token fora deste conjunto e ignorado por ``render_with_mcp_flags``
e pelo ``FlagsPanel``. Adicionar ou remover literais exige versao nova deste
modulo (Zero Assumido, MF-01, MF-02).

MF-01: ``opus`` e ``sonnet`` sao variantes de modelo do provider ``claude``,
nao providers independentes.
MF-02: nao existe flag ``--claude`` (delegar para Claude a partir de Claude
e no-op).
"""

from __future__ import annotations

# 7 literais canonicos (source.md:1266).
_SUPPORTED_MCP_FLAGS: frozenset[str] = frozenset({
    "--opus",
    "--sonnet",
    "--codex",
    "--kimi",
    "--kimi-k3",
    "--qwen",
    "--grok",
})

# Mapeamento flag -> provider/Main compativel.
_FLAG_LITERAL_TO_MAIN: dict[str, str] = {
    "--opus": "opus",
    "--sonnet": "sonnet",
    "--codex": "codex",
    "--kimi": "kimi",
    "--kimi-k3": "kimi",
    "--qwen": "qwen",
    "--grok": "grok",
}

# Flags por terminal de delegacao.
# T1 (Claude) aceita todas; T2 recebe kimi/qwen; T3 recebe codex/grok.
_FLAGS_BY_TERMINAL: dict[str, frozenset[str]] = {
    "T1": _SUPPORTED_MCP_FLAGS,
    "T2": frozenset({"--kimi", "--qwen"}),
    "T3": frozenset({"--codex", "--grok"}),
}

# Provedores que tornam uma flag redundante (flag == provider do Main).
# opus/sonnet sao variantes de claude, nao providers proprios — nenhuma flag
# e redundante sob claude.
_REDUNDANT_FLAG_MAINS: dict[str, str] = {
    "--kimi": "kimi",
    "--kimi-k3": "kimi",
    "--codex": "codex",
    "--qwen": "qwen",
    "--grok": "grok",
}
