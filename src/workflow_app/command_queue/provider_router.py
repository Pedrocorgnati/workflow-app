"""
Provider router — pure decision module for the single multifunction queue arrow.

Source of truth: blacksmith/loop-archives/06-02-seta-unica-multi-llm-queue/source.md
secao 7.1 (contrato) + secao 11 (matriz) + secao 12 (impacto por arquivo).

Centraliza a decisao de provider (Claude/Kimi/Codex) de UM item da fila numa
funcao PURA e testavel. Segunda etapa do defense-in-depth (source.md secao 13:
router depois da whitelist, antes da UI). O widget (`command_queue_widget.py`,
task 004) consome `classify_provider` para colorir o botao unico e escolher o
terminal de destino, mas NUNCA delega a decisao a frontmatter ou a matrix DCP.

Invariantes preservadas (source.md secao 5):
  - Inv 2 (regime unico): o eixo Worker e avaliado ANTES do eixo Main-LLM.
    `main_llm` vive em `RoutingState` para a UI/telemetria, mas a classificacao
    escolhe apenas entre despachar a um worker (T2/T3) ou cair em Claude/T1.
    Por isso "T1 verde via Main Kimi/Codex" da matriz (secao 11, linhas 5-6)
    resolve para Provider.CLAUDE.
    O modo ROUTER V2 (item 010), que superava esta invariante fazendo a familia
    do Main vencer o worker na colisao, foi REVOGADO pela decisao D3 do item 006
    do loop 08-17-systemforge-multillm-gaps-refactor (gap C7): existe um unico
    regime, e nele o worker vence sempre.
  - Inv 3: o provider por item NUNCA altera quais comandos entram na lista. Este
    modulo nao toca lista/ordem/matrix; so classifica um spec ja enfileirado.
  - Inv 8: `local-action` nao e comando de provider e nunca vai para T1/T2/T3.

Pureza (source.md secao 12): sem import de Qt, sem I/O em tempo de chamada. As
dependencias sao as duas whitelists puras e, apenas para tipagem, o
`CommandSpec`. Desde a remocao do ramo Router V2 (item 006 do loop
08-17-systemforge-multillm-gaps-refactor, gap C7) este modulo nao le nenhuma
feature flag: a decisao nao depende mais de ambiente, nem congelado no boot. A leitura de ambiente e do modulo de flags, nao deste; aqui nao
ha `os.environ` nem estado mutavel. `classify_provider` assume `spec` e `state`
validos (nao-None); validacao de schema e responsabilidade do caller no step
path (task 004). O comportamento com entrada invalida e indefinido por contrato.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

from workflow_app.command_queue.codex_whitelist import is_codex_compatible
from workflow_app.command_queue.kimi_whitelist import is_kimi_compatible

if TYPE_CHECKING:
    # Tipagem apenas: importar em runtime acoplaria o router pure ao modulo de
    # dominio sem necessidade (classify_provider usa duck typing: spec.kind,
    # spec.name, spec.kimi_eligible).
    from workflow_app.domain import CommandSpec


# Diretivas de sessao. Nunca sao elegiveis a worker por whitelist; equivalem a
# cair no fallback Claude (source.md secao 7.1 regra 2 + secao 5 invariantes 6
# e 7).
#
# `/reasoning` entrou em 2026-08-17 (C27) e FICA, mesmo depois da revogacao da
# traducao que o produzia (decisao D-C27-2, mesmo dia). Ele existe hoje so como
# residuo: filas salvas naquela janela podem trazer `/reasoning yes`. Sem ele
# aqui, essa linha escapa da regra 2, cai no fallback CLAUDE por outro caminho
# e — pior — `render_with_mcp_flags` passa a considera-la elegivel a sufixo,
# rendendo `/reasoning yes --codex` na fila. Uma diretiva de sessao nunca recebe
# flag, em qualquer dialeto, nem quando o dialeto ja morreu.
_SESSION_DIRECTIVES: frozenset[str] = frozenset(
    {"/clear", "/model", "/effort", "/reasoning"}
)

# --------------------------------------------------------------------------- #
# Tabela de classificacao por familia e variante (item 010)                    #
# --------------------------------------------------------------------------- #
#
# Cada provider conhecido pertence a uma FAMILIA (grupo de providers com
# identidade de comando compartilhada) e a uma VARIANTE (identificador do
# provider dentro da familia). A familia e usada para comparar o comando com
# o Main LLM selecionado: se a familia do comando bate com a familia do Main,
# o comando pertence ao terminal principal (T1 / Provider.CLAUDE).
#
# +-----------+----------+--------------------------------------------------+
# | Provider  | Familia  | Variante                                         |
# +-----------+----------+--------------------------------------------------+
# | claude    | claude   | claude                                           |
# | kimi      | kimi     | kimi                                             |
# | codex     | codex    | codex                                            |
# | qwen      | qwen     | qwen                                             |
# | (outro)   | unknown  | unknown                                          |
# +-----------+----------+--------------------------------------------------+
#
# Regra de roteamento com Main (item 010):
#   1. local-action / diretiva de sessao -> CLAUDE (precede tudo).
#   2. Familia do comando == familia do Main -> CLAUDE (T1 roda o Main).
#   3. Kimi worker ativo E (kimi_eligible OU is_kimi_compatible) -> KIMI.
#   4. Codex worker ativo E is_codex_compatible -> CODEX.
#   5. Fallback -> CLAUDE.
#
# A etapa 2 e a mudanca do item 010: o Main selecionado agora participa da
# decisao. Antes, main_llm era campo de telemetria ignorado pelo router.
#
# --------------------------------------------------------------------------- #
# Gap C4 — degenerada POR DESIGN, nao mapeamento pela metade                    #
# (item 003 do loop 08-17-systemforge-multillm-gaps-refactor)                   #
# --------------------------------------------------------------------------- #
#
# (a) Os 5 pares 1:1 abaixo (familia == variante para todo provider) sao
#     INTENCIONAIS. Nao ha familia com duas variantes hoje porque nao ha dois
#     providers com identidade de comando compartilhada; o eixo variante existe
#     no formato do valor, nao nos dados.
#
# (b) A tabela vale principalmente como ROSTER DE PARIDADE: e ela que
#     `TestMapParity` cruza com o enum `Provider`, `_PROVIDER_BTN_STYLE`,
#     `_PROVIDER_LABEL` e `_PROVIDER_DEST` (em `tests/test_command_queue_widget.py`
#     e `tests/test_loop_0811_item018.py`). Provider novo que entre no enum sem
#     entrar aqui — ou vice-versa — fica vermelho nos dois arquivos.
#
# (c) A coluna `variante` da UI NAO e alimentada por esta tabela. Por isso C4 e
#     ruido estrutural DOCUMENTADO, nao defeito de runtime: nada em producao le
#     o segundo elemento da tupla para decidir roteamento (`classify_provider`
#     descarta com `_main_variant`). O eixo de variante de verdade e escopo
#     integral do item 004; nada dele foi criado aqui.
#
# (d) Evidencia de que o retorno degenerado nunca e observado com entrada de
#     variante: os dois unicos produtores de `main_llm` so emitem os 5 slugs de
#     provider — `_resolve_interactive_main_llm` (`command_queue_widget.py`,
#     codex|qwen|grok|kimi|claude) e `_current_llm_provider` (`main_window.py`,
#     com clamp contra `_MAIN_LLM_SLUGS`). Nenhum slug de variante (`opus`,
#     `sonnet`, `kimi-k3`) alcanca `_classify_family_variant`.
#
# MF-01 (nenhuma flag e redundante sob Main claude, porque `opus`/`sonnet` sao
# variantes de claude e nao providers proprios) JA esta garantido em outro
# ponto: `_REDUNDANT_FLAG_MAINS` em `workflow_app/config/llm_flags.py:69`, que
# omite deliberadamente `--opus`/`--sonnet` e carrega o comentario
# correspondente (consumidor unico: `llm_config/flags_panel.py`). Guard novo
# aqui seria redundante e nao foi criado.
_PROVIDER_FAMILIES: dict[str, tuple[str, str]] = {
    "claude": ("claude", "claude"),
    "kimi": ("kimi", "kimi"),
    "codex": ("codex", "codex"),
    "qwen": ("qwen", "qwen"),
    "grok": ("grok", "grok"),
}


class Provider(str, Enum):
    """Provider efetivo do clique no botao unico da queue.

    str-Enum para serializar direto em logs/telemetria e comparar com strings
    cruas sem `.value`.
    """

    CLAUDE = "claude"
    KIMI = "kimi"
    CODEX = "codex"
    QWEN = "qwen"
    GROK = "grok"


@dataclass(frozen=True)
class RoutingState:
    """Estado de roteamento avaliado no momento do clique.

    `kimi_worker_enabled` / `codex_worker_enabled` sao os checkboxes de worker
    (T2/T3). `main_llm` e o Main LLM do T1 ("claude" | "kimi" | "codex" |
    "qwen").

    No modo LEGADO (default) `main_llm` NAO participa da classificacao
    (invariante 2: o eixo Worker decide; o Main-LLM no T1 e sempre o fallback
    verde/T1) e existe so para UI/telemetria. No modo ROUTER V2 (item 010, atras
    de kill-switch) ele passa a participar: familia do comando == familia do
    Main -> T1. Ver `classify_provider` para o contrato completo dos dois modos.
    """

    kimi_worker_enabled: bool
    codex_worker_enabled: bool
    main_llm: str
    qwen_worker_enabled: bool = False
    grok_worker_enabled: bool = False


def normalize_command_name(name: str) -> str:
    """Reduz um comando a sua cabeca (primeiro token), descartando flags/args.

    Espelha o matching das whitelists (`.strip().split(None, 1)[0]`) para que a
    deteccao de diretiva da regra 2 use a mesma normalizacao. Entrada vazia ou so
    com espacos retorna "".
    """
    if not name or not name.strip():
        return ""
    return name.strip().split(None, 1)[0]


def _classify_family_variant(provider_name: str) -> tuple[str, str]:
    """Classifica um provider em (familia, variante).

    Familia agrupa providers com identidade de comando compartilhada. Variante
    identifica o provider especifico dentro da familia. Providers desconhecidos
    retornam ``("unknown", "unknown")``.

    Tabela completa em ``_PROVIDER_FAMILIES`` (item 010).
    """
    return _PROVIDER_FAMILIES.get(provider_name.lower(), ("unknown", "unknown"))


def __getattr__(name: str) -> object:
    """Preserva o nome publico `classify_family_variant` sem entrar em `dir()`.

    O item 010 criou `classify_family_variant` como funcao publica. O snapshot
    legado (`tests/fixtures/llm_config_legacy_snapshot.json`) trava a superficie
    observavel via `dir(provider_router)` com as flags ausentes, e um binding
    publico novo no `__dict__` do modulo e regressao de superficie por esse
    contrato. PEP 562 concilia os dois: o acesso por atributo continua
    funcionando para quem depender do nome publico, mas o nome nao aparece em
    `dir()` (o `__getattr__` em si comeca com `_` e e filtrado pelo snapshot).
    """
    if name == "classify_family_variant":
        return _classify_family_variant
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def classify_provider(spec: "CommandSpec", state: RoutingState) -> Provider:
    """Classifica o provider efetivo de UM item da fila (funcao pura).

    REGIME UNICO (invariante 2 preservada — `main_llm` nao participa da
    decisao):
      0. `is_prompt=True` -> CLAUDE (prompt simples, texto raw sem transformacoes)
      1. `force_main_llm=True` -> CLAUDE (verde/T1), ignora workers
      2. `spec.kind == "local-action"` -> CLAUDE (invariante 8: nunca a worker).
      3. Diretiva `/clear` | `/model` | `/effort` -> CLAUDE (nao elegivel a
         worker por whitelist; equivale ao fallback da regra 7).
      4. Nenhum worker ativo -> CLAUDE.
      5. Kimi worker ativo E (kimi_eligible OU is_kimi_compatible) -> KIMI.
      5b. Qwen worker ativo E a mesma elegibilidade T2 -> QWEN (apos Kimi, PW-02).
      6. Codex worker ativo E is_codex_compatible -> CODEX.
      6b. Grok worker ativo E is_codex_compatible -> GROK (apos Codex, PW-02).
      7. Kimi e Codex elegiveis ao mesmo tempo -> Kimi vence (regra 5 precede a 6).
      8. Sem elegibilidade worker -> CLAUDE.

    Prompts simples (`is_prompt=True`) sempre roteiam para T1 sem passar por
    workers ou transformacoes de comando. Texto e enviado raw ao terminal
    interactive, independente do Main LLM selecionado.

    O campo `force_main_llm` (addicionar comando UI) sobrepoe as regras 5-8:
      - Se `force_main_llm=True`, sempre retorna CLAUDE (verde/T1),
        ignorando completamente workers elegiveis.
      - Se `force_main_llm=False`, segue o fluxo normal acima (pode ir a worker).

    Quando o MESMO provider ocupa Main e Worker, o **worker vence**, sempre, sem
    condicionar a switch nenhum. Ate o item 006 do loop
    08-17-systemforge-multillm-gaps-refactor (gap C7, decisao D3) existia um
    segundo regime, o Router V2 (item 010), atras do kill-switch global do item
    002 mais um kill-switch proprio, no qual a familia do Main vencia o worker
    nessa colisao. Esse regime foi REVOGADO e removido junto com o seu switch:
    nunca rodou fora de teste (a env var nao era setada em lugar nenhum do repo) e
    contradizia ``ai-forge/rules/llm-routing-div.md``, que trata "avaliar o eixo
    Main antes do eixo Worker" como anti-pattern.

    A ordem de avaliacao das regras 5/5b/6/6b/7/8 nao mudou com a revogacao.

    Assume ``spec`` e ``state`` nao-None (contrato; entrada invalida e
    comportamento indefinido).
    """
    # Regra 0: prompt simples -> CLAUDE (texto raw, sem transformacoes)
    if spec.is_prompt:
        return Provider.CLAUDE

    # Regra 0b: force_main_llm sobrepoe o roteamento normal
    if spec.force_main_llm:
        return Provider.CLAUDE

    # Regra 1: local-action nunca vai para terminal worker.
    if spec.kind == "local-action":
        return Provider.CLAUDE

    name = normalize_command_name(spec.name)

    # Regra 2: diretivas de sessao caem no fallback Claude.
    if name in _SESSION_DIRECTIVES:
        return Provider.CLAUDE

    if (
        not state.kimi_worker_enabled
        and not state.codex_worker_enabled
        and not state.qwen_worker_enabled
        and not state.grok_worker_enabled
    ):
        # Regra 3 legada: sem nenhum worker ativo, so existe o destino Claude/T1.
        return Provider.CLAUDE

    # Regra 5 (+ 7): Kimi tem precedencia (familia T2). is_kimi_compatible OU
    # o flag herdado kimi_eligible do item de loop ja basta.
    if state.kimi_worker_enabled and (spec.kimi_eligible or is_kimi_compatible(name)):
        return Provider.KIMI

    # Regra 5b: Qwen worker (familia T2, apos Kimi — PW-02).
    # Mesma elegibilidade que Kimi (kimi_eligible OU is_kimi_compatible).
    if state.qwen_worker_enabled and (spec.kimi_eligible or is_kimi_compatible(name)):
        return Provider.QWEN

    # Regra 6: Codex (familia T3) so quando T2 nao venceu acima.
    if state.codex_worker_enabled and is_codex_compatible(name):
        return Provider.CODEX

    # Regra 6b: Grok worker (familia T3, apos Codex — PW-02).
    # Mesma elegibilidade que Codex (is_codex_compatible).
    if state.grok_worker_enabled and is_codex_compatible(name):
        return Provider.GROK

    # Regra 8: fallback.
    return Provider.CLAUDE
