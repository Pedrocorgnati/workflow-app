"""Conjunto FECHADO de flags MCP suportadas (fonte canonica unica).

Qualquer token fora deste conjunto e ignorado por ``render_with_mcp_flags``
e pelo ``FlagsPanel``. Adicionar ou remover literais exige versao nova deste
modulo (Zero Assumido, MF-01, MF-02).

MF-01: ``opus`` e ``sonnet`` sao variantes de modelo do provider ``claude``,
nao providers independentes.
MF-02: nao existe flag ``--claude`` (delegar para Claude a partir de Claude
e no-op).

Item 005 (loop 08-17-systemforge-multillm-gaps-refactor): o conjunto vigente
e decidido pelo kill-switch dedicado, consultado aqui somente por
``llm_flags_v2_enabled()`` (boot-frozen, fail-closed; o nome da env var vive
uma unica vez, em ``feature_flags``). Desligado = roster legado
``_LEGACY_FLAG_ORDER`` (``--codex`` e ``--kimi``, tabela C26, mais
``--mimo``); ligado = os literais canonicos de thinking/execution
(capacidade de raciocinio, nao o CLI do T1). Todas as demais estruturas
deste modulo sao DERIVADAS do conjunto vigente, nunca reescritas por
regime — assim os dois regimes nao podem divergir.

O switch das superficies do CLI MiMo (``feature_flags.mimo_v1_enabled()``)
NAO participa daqui (plano 10-02, contrato D3): ele gateia so o radio Main,
o worker T2 e o botao ``mimod``. ``--mimo`` e ``--mimo-pro`` usam o servidor
MCP (API direta), nao o CLI, e a presenca deles no conjunto nao depende
daquele switch: quem decide e o regime acima (``--mimo`` nos dois,
``--mimo-pro`` so no v2).

Os mapas ``_FULL_*`` sao validados no import por
``_flag_maps_invariant_violations`` com ``raise`` (sobrevive a ``python -O``,
ao contrario de ``assert``): mapa incoerente derruba o import em vez de
virar flag no-op em silencio.

Este modulo continua puro: do projeto, importa apenas
``workflow_app.config.feature_flags`` (que e Qt-free) e nao toca
``os.environ`` diretamente.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from workflow_app.config.feature_flags import llm_flags_v2_enabled

# Ordem CANONICA de render na UI. Nao e alfabetica: coluna thinking (mais
# poderoso) e depois coluna execution. `queue-div-main-llm` ficou so com o
# CLI de terminal; a capacidade de raciocinio vive aqui.
_THINKING_FLAG_ORDER: tuple[str, ...] = (
    "--fable",
    "--opus",
    "--codex-ultra",
    "--mimo-pro",
    "--kimi-k3",
    "--grok-xhigh",
)
_EXECUTION_FLAG_ORDER: tuple[str, ...] = (
    "--grok",
    "--sonnet",
    "--mimo",
    "--kimi",
    "--qwen",
    "--codex",
)
_FULL_FLAG_CANONICAL_ORDER: tuple[str, ...] = (
    _THINKING_FLAG_ORDER + _EXECUTION_FLAG_ORDER
)

# Roster legado (kill-switch ausente/off), na ordem do sufixo T1
# (`FlagsPanel.checked_flags`; o painel desenha por coluna, entao a ordem
# visual e a da coluna execution, nao esta): os literais
# que existiam antes do pacote multi-LLM mais `--mimo`, que entra nos DOIS
# regimes porque substitui o `--kimi` (decisao do operador, 2026-10-02: em
# qualquer duvida entre --mimo e --kimi, a MiMo ganha; ver
# `_FULL_MIMO_SUPERSEDES`). `--mimo-pro` nao entra no legado, como `--kimi-k3`.
_LEGACY_FLAG_ORDER: tuple[str, ...] = ("--codex", "--mimo", "--kimi")
_LEGACY_MCP_FLAGS: frozenset[str] = frozenset(_LEGACY_FLAG_ORDER)

# Precedencia MiMo > Kimi (lane T2). Com as duas flags da MESMA coluna
# marcadas, a do Kimi sai do sufixo: o parser v2 dos comandos ja nao roda o
# Kimi nesse caso, e manter o literal so confundiria o payload. O supersede
# e PAREADO por coluna: `--mimo` (execution) tira so `--kimi`; `--mimo-pro`
# (thinking) tira so `--kimi-k3`. Pares cruzados nao se tiram: cada coluna
# escolhe um nivel de raciocinio diferente. Contrato: todo consumidor do
# sufixo T1 (FlagsPanel, `render_with_mcp_flags`, loop legado de checkboxes)
# le os pares de `_MIMO_SUPERSEDES`, nunca o alias abaixo.
MIMO_FLAG: str = "--mimo"
MIMO_PRO_FLAG: str = "--mimo-pro"
_MIMO_FLAG_LITERALS: frozenset[str] = frozenset({MIMO_FLAG, MIMO_PRO_FLAG})
_FULL_MIMO_SUPERSEDES: dict[str, frozenset[str]] = {
    MIMO_FLAG: frozenset({"--kimi"}),
    MIMO_PRO_FLAG: frozenset({"--kimi-k3"}),
}
# Alias de compatibilidade, citado so pelas rules (llm-routing-div.md,
# llm-flags.md): o par da coluna execution, o mesmo objeto. Nenhum outro
# modulo de src o le (guard em tests/test_mimo_flags.py): filtrar o sufixo so
# por ele deixa o par da coluna thinking (`--mimo-pro` com `--kimi-k3`)
# passar no regime v2.
MIMO_SUPERSEDES_KIMI: frozenset[str] = _FULL_MIMO_SUPERSEDES[MIMO_FLAG]

# Mapeamento flag -> provider/Main compativel (superset; filtrado abaixo).
_FULL_FLAG_LITERAL_TO_MAIN: dict[str, str] = {
    "--fable": "claude",
    "--opus": "claude",
    "--codex-ultra": "codex",
    "--mimo-pro": "mimo",
    "--kimi-k3": "kimi",
    "--grok-xhigh": "grok",
    "--grok": "grok",
    "--sonnet": "claude",
    "--mimo": "mimo",
    "--kimi": "kimi",
    "--qwen": "qwen",
    "--codex": "codex",
}

# Flags por terminal de delegacao (superset; interseccionado abaixo).
# T1 (Claude) aceita todas; T2 recebe mimo/kimi/qwen; T3 recebe codex/grok.
_FULL_FLAGS_BY_TERMINAL: dict[str, frozenset[str]] = {
    "T1": frozenset(_FULL_FLAG_CANONICAL_ORDER),
    "T2": frozenset({"--mimo", "--mimo-pro", "--kimi", "--kimi-k3", "--qwen"}),
    "T3": frozenset({"--codex", "--codex-ultra", "--grok", "--grok-xhigh"}),
}

# Provedores que tornam uma flag redundante (flag == provider do Main).
# Variantes de claude (--fable/--opus/--sonnet) nao sao redundantes sob
# Main claude: o Main escolhe o CLI do T1, a flag escolhe o raciocinio.
_FULL_REDUNDANT_FLAG_MAINS: dict[str, str] = {
    "--mimo": "mimo",
    "--mimo-pro": "mimo",
    "--kimi": "kimi",
    "--kimi-k3": "kimi",
    "--codex": "codex",
    "--codex-ultra": "codex",
    "--qwen": "qwen",
    "--grok": "grok",
    "--grok-xhigh": "grok",
}

# Auto-proxy por Main: flags que, sob aquele Main, virariam auto-consulta
# silenciosa em vez de segunda opiniao explicita. O FlagsPanel as desabilita
# com tooltip proprio (`autoproxy_tooltip`), distinto do de flag redundante.
#   - kimi (C-43 / R-40): as skills de provider do lado Kimi
#     (`.kimi/skills/codex`) sao auto-proxies do proprio Kimi; honrar a flag
#     do Codex sob Main Kimi produziria registro falso de segunda opiniao.
#   - mimo (MiMo > Kimi, 2026-10-02): com a MiMo no T1 nenhum caminho
#     escolhe o Kimi.
_FULL_AUTOPROXY_FLAGS_BY_MAIN: dict[str, frozenset[str]] = {
    "kimi": frozenset({"--codex", "--codex-ultra"}),
    "mimo": frozenset({"--kimi", "--kimi-k3"}),
}

# Mains que cada terminal de delegacao recebe (T1 aceita todos os literais).
# Base da regra (4) de `_flag_maps_invariant_violations`.
_TERMINAL_MAINS: dict[str, frozenset[str]] = {
    "T2": frozenset({"mimo", "kimi", "qwen"}),
    "T3": frozenset({"codex", "grok"}),
}


def _flag_maps_invariant_violations(
    *,
    thinking: Sequence[str] = _THINKING_FLAG_ORDER,
    execution: Sequence[str] = _EXECUTION_FLAG_ORDER,
    literal_to_main: Mapping[str, str] = _FULL_FLAG_LITERAL_TO_MAIN,
    by_terminal: Mapping[str, frozenset[str]] = _FULL_FLAGS_BY_TERMINAL,
    redundant: Mapping[str, str] = _FULL_REDUNDANT_FLAG_MAINS,
    legacy_order: Sequence[str] = _LEGACY_FLAG_ORDER,
    mimo_literals: frozenset[str] = _MIMO_FLAG_LITERALS,
    supersedes: Mapping[str, frozenset[str]] = _FULL_MIMO_SUPERSEDES,
    autoproxy: Mapping[str, frozenset[str]] = _FULL_AUTOPROXY_FLAGS_BY_MAIN,
) -> list[str]:
    """Violacoes de coerencia entre os mapas ``_FULL_*`` (funcao pura).

    Lista vazia = mapas coerentes. Os parametros existem para o teste injetar
    uma mutacao por regra; o import do modulo chama com os defaults e levanta
    ``AssertionError`` se sobrar qualquer violacao.
    """
    violations: list[str] = []
    columns = {"thinking": tuple(thinking), "execution": tuple(execution)}
    full_order = columns["thinking"] + columns["execution"]
    full = frozenset(full_order)
    column_of = {flag: name for name, col in columns.items() for flag in col}

    # (1) Literal unico: nem repetido numa coluna, nem nas duas.
    repeated = sorted({flag for flag in full_order if full_order.count(flag) > 1})
    if repeated:
        violations.append(f"literal repetido nas colunas: {repeated}")

    # (2) As chaves de literal_to_main sao exatamente o conjunto cheio.
    mapped = frozenset(literal_to_main)
    if mapped != full:
        violations.append(f"literal_to_main diverge das colunas em {sorted(mapped ^ full)}")

    # (3) T1 (Claude) aceita o conjunto cheio.
    t1 = frozenset(by_terminal.get("T1", frozenset()))
    if t1 != full:
        violations.append(f"T1 diverge das colunas em {sorted(t1 ^ full)}")

    # (4) T2/T3: o literal esta no terminal se e so se o Main dele esta.
    for terminal, mains in _TERMINAL_MAINS.items():
        got = frozenset(by_terminal.get(terminal, frozenset()))
        want = frozenset(f for f, m in literal_to_main.items() if m in mains)
        if got != want:
            violations.append(f"{terminal} diverge do Main das flags em {sorted(got ^ want)}")

    # (5) Redundante = literal_to_main sem as variantes de Claude (que
    #     escolhem raciocinio, nao CLI, e nunca redundam o Main).
    want_redundant = {f: m for f, m in literal_to_main.items() if m != "claude"}
    if dict(redundant) != want_redundant:
        diff = sorted(set(redundant.items()) ^ set(want_redundant.items()))
        violations.append(f"redundant diverge de literal_to_main em {diff}")

    # (6) Roster legado: sem repeticao, contido no conjunto cheio e com a
    #     MiMo antes do Kimi em todo par de supersede presente nele.
    legacy = tuple(legacy_order)
    if len(frozenset(legacy)) != len(legacy):
        violations.append(f"roster legado com literal repetido: {list(legacy)}")
    if not frozenset(legacy) <= full:
        unknown = sorted(frozenset(legacy) - full)
        violations.append(f"roster legado com literal fora das colunas: {unknown}")
    for mimo, losers in supersedes.items():
        for loser in sorted(losers):
            if mimo in legacy and loser in legacy and legacy.index(loser) < legacy.index(mimo):
                violations.append(f"{loser} antes de {mimo} no roster legado (MiMo > Kimi)")

    # (7) MiMo > Kimi pareado por coluna: toda flag MiMo e chave de supersede
    #     e tira exatamente as flags Kimi da propria coluna, renderizando
    #     antes delas. Par cruzado (thinking x execution) nao existe.
    want_mimo = frozenset(f for f, m in literal_to_main.items() if m == "mimo")
    if frozenset(mimo_literals) != want_mimo:
        diff = sorted(frozenset(mimo_literals) ^ want_mimo)
        violations.append(f"literais MiMo divergem de literal_to_main em {diff}")
    if frozenset(supersedes) != frozenset(mimo_literals):
        diff = sorted(frozenset(supersedes) ^ frozenset(mimo_literals))
        violations.append(f"chaves de supersede divergem dos literais MiMo em {diff}")
    for mimo, losers in supersedes.items():
        name = column_of.get(mimo)
        if name is None or literal_to_main.get(mimo) != "mimo":
            violations.append(f"chave de supersede {mimo} nao e literal MiMo das colunas")
            continue
        col = columns[name]
        kimis = frozenset(f for f in col if literal_to_main.get(f) == "kimi")
        if not losers or frozenset(losers) != kimis:
            violations.append(
                f"supersede de {mimo} tem que tirar o Kimi da coluna {name}"
                f" {sorted(kimis)}, nao {sorted(losers)}"
            )
        for loser in sorted(losers):
            if literal_to_main.get(loser) != "kimi":
                violations.append(f"{mimo} supersede {loser}, que nao e literal Kimi")
            elif column_of.get(loser) != name:
                violations.append(f"{mimo} supersede {loser} de outra coluna (par cruzado)")
            elif col.index(loser) < col.index(mimo):
                violations.append(
                    f"{loser} renderiza antes de {mimo} na coluna {name} (MiMo > Kimi)"
                )

    # (8) Auto-proxy: so literal do conjunto cheio, nunca a flag redundante
    #     sob o mesmo Main, e Main mimo desabilita todo literal Kimi.
    for main, flags in autoproxy.items():
        for flag in sorted(flags):
            if flag not in full:
                violations.append(f"auto-proxy de {main} com literal fora das colunas: {flag}")
            elif redundant.get(flag) == main:
                violations.append(f"auto-proxy de {main} inclui {flag}, redundante sob {main}")
    kimi_flags = frozenset(f for f, m in literal_to_main.items() if m == "kimi")
    missing = sorted(kimi_flags - frozenset(autoproxy.get("mimo", frozenset())))
    if missing:
        violations.append(f"Main mimo nao desabilita {missing} (MiMo > Kimi)")
    return violations


# Guarda de import: `raise`, nao `assert` (o assert some com `python -O` e o
# mapa incoerente viraria flag no-op em silencio).
_INVARIANT_VIOLATIONS: list[str] = _flag_maps_invariant_violations()
if _INVARIANT_VIOLATIONS:
    raise AssertionError("; ".join(_INVARIANT_VIOLATIONS))

# ── Conjunto vigente (decidido no boot pelo kill-switch) ─────────────── #
# Unica consulta ao kill-switch neste modulo: o regime escolhe a ordem de
# render e o resto deriva dela. O switch das superficies do CLI MiMo nao
# entra aqui (contrato D3).
_REGIME_ORDER: tuple[str, ...] = (
    _FULL_FLAG_CANONICAL_ORDER if llm_flags_v2_enabled() else _LEGACY_FLAG_ORDER
)
# Ordem e conjunto saem da MESMA tupla do regime: a paridade entre os dois e
# estrutural. Filtrar a ordem pelo conjunto derivado dela era no-op, e
# compara-los depois era guarda tautologica (nunca disparava).
_FLAG_CANONICAL_ORDER: tuple[str, ...] = _REGIME_ORDER
_SUPPORTED_MCP_FLAGS: frozenset[str] = frozenset(_FLAG_CANONICAL_ORDER)

# Guarda do roster vigente: olha o que a estrutura NAO garante. Literal
# repetido some do conjunto mas nao da ordem (o sufixo T1 sairia com o
# literal duas vezes); literal fora das colunas nao tem Main, terminal nem
# tooltip. As regras (1) e (6) cobrem os rosters declarados; esta cobre o
# que o regime de fato escolheu, inclusive um regime novo que nao passe por
# elas. `raise` pelo mesmo motivo da guarda acima.
if len(_SUPPORTED_MCP_FLAGS) != len(_FLAG_CANONICAL_ORDER) or not (
    _SUPPORTED_MCP_FLAGS <= frozenset(_FULL_FLAG_CANONICAL_ORDER)
):
    raise AssertionError(
        f"roster do regime vigente invalido: {list(_FLAG_CANONICAL_ORDER)}"
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

# Supersede MiMo > Kimi do regime vigente: so os pares com os dois lados no
# conjunto. Fonte unica dos pares para todo consumidor do sufixo T1
# (FlagsPanel, `render_with_mcp_flags`, loop legado de checkboxes).
_MIMO_SUPERSEDES: dict[str, frozenset[str]] = {
    mimo: losers & _SUPPORTED_MCP_FLAGS
    for mimo, losers in _FULL_MIMO_SUPERSEDES.items()
    if mimo in _SUPPORTED_MCP_FLAGS and losers & _SUPPORTED_MCP_FLAGS
}

# Auto-proxy do regime vigente: Main sem nenhuma flag vigente sai da tabela.
_AUTOPROXY_FLAGS_BY_MAIN: dict[str, frozenset[str]] = {
    main: flags & _SUPPORTED_MCP_FLAGS
    for main, flags in _FULL_AUTOPROXY_FLAGS_BY_MAIN.items()
    if flags & _SUPPORTED_MCP_FLAGS
}
