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
  - Inv 2 (modo LEGADO, default): o eixo Worker e avaliado ANTES do eixo
    Main-LLM. `main_llm` vive em `RoutingState` para a UI/telemetria, mas a
    classificacao escolhe apenas entre despachar a um worker (T2/T3) ou cair em
    Claude/T1. Por isso "T1 verde via Main Kimi/Codex" da matriz (secao 11,
    linhas 5-6) resolve para Provider.CLAUDE.
    No modo ROUTER V2 (item 010, atras de kill-switch — ver `classify_provider`)
    essa invariante e deliberadamente SUPERADA: a familia do Main participa da
    decisao e vence o worker na colisao. Enquanto o V2 nao for default, Inv 2
    continua valendo no caminho de producao.
  - Inv 3: o provider por item NUNCA altera quais comandos entram na lista. Este
    modulo nao toca lista/ordem/matrix; so classifica um spec ja enfileirado.
  - Inv 8: `local-action` nao e comando de provider e nunca vai para T1/T2/T3.

Pureza (source.md secao 12): sem import de Qt, sem I/O em tempo de chamada. As
dependencias sao as duas whitelists puras, os helpers de feature flag
(`workflow_app.config.feature_flags`, que resolvem o ambiente UMA vez no boot do
processo e depois so leem constante congelada) e, apenas para tipagem, o
`CommandSpec`. A leitura de ambiente e do modulo de flags, nao deste; aqui nao
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

# Import direto do modulo de flags (NUNCA via `workflow_app.config`, que arrasta
# `ConfigBar`/Qt e quebraria o teste de pureza). Aliases com `_` porque o
# snapshot legado compara `dir(provider_router)` contra fixture versionada:
# qualquer binding publico novo neste modulo e regressao de superficie.
from workflow_app.config.feature_flags import (
    llm_config_v2_enabled as _llm_config_v2_enabled,
)
from workflow_app.config.feature_flags import (
    provider_router_v2_enabled as _provider_router_v2_enabled,
)

if TYPE_CHECKING:
    # Tipagem apenas: importar em runtime acoplaria o router pure ao modulo de
    # dominio sem necessidade (classify_provider usa duck typing: spec.kind,
    # spec.name, spec.kimi_eligible).
    from workflow_app.domain import CommandSpec


# Diretivas de sessao do Claude Code. Nunca sao elegiveis a worker por whitelist;
# equivalem a cair no fallback Claude (source.md secao 7.1 regra 2 + secao 5
# invariantes 6 e 7).
_SESSION_DIRECTIVES: frozenset[str] = frozenset({"/clear", "/model", "/effort"})

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

    Dois modos, escolhidos pelos kill-switches congelados no boot. O modo V2 so
    vale quando o global do item 002 (:func:`llm_config_v2_enabled`) E o
    especifico do item 010 (:func:`provider_router_v2_enabled`) respondem ambos
    ``True``; qualquer outro estado cai no legado (fail-closed, "ausente =
    legado" na tabela P2 do source.md do loop
    08-11-llm-config-multillm-expansion). Os nomes das env vars vivem uma unica
    vez em ``workflow_app.config.feature_flags``; este modulo nunca os repete.

    Modo LEGADO (default; invariante 2 preservada — `main_llm` nao participa):
      1. `spec.kind == "local-action"` -> CLAUDE (invariante 8: nunca a worker).
      2. Diretiva `/clear` | `/model` | `/effort` -> CLAUDE (nao elegivel a
         worker por whitelist; equivale ao fallback da regra 7).
      3. Nenhum worker ativo -> CLAUDE.
      4. Kimi worker ativo E (kimi_eligible OU is_kimi_compatible) -> KIMI.
      5. Codex worker ativo E is_codex_compatible -> CODEX.
      6. Kimi e Codex elegiveis ao mesmo tempo -> Kimi vence (regra 4 precede a 5).
      7. Sem elegibilidade worker -> CLAUDE.

    Modo V2 (item 010): a regra 3 vira "familia do comando == familia do Main
    -> CLAUDE", porque T1 executa o Main e nao faz sentido mandar a um worker um
    comando que o proprio Main ja roda. As regras 4-7 seguem identicas ("nenhum
    worker ativo" continua caindo em CLAUDE pelo fallback da regra 7, ja que 4 e
    5 exigem worker ligado).

    Enquanto o mesmo provider puder estar simultaneamente como Main e como
    Worker, os dois modos discordam nessa colisao (legado: worker vence, fix
    2026-05-30; V2: Main vence). Por isso a divergencia mora atras do
    kill-switch, e nao no caminho default.

    Assume ``spec`` e ``state`` nao-None (contrato; entrada invalida e
    comportamento indefinido).
    """
    # Regra 1: local-action nunca vai para terminal worker.
    if spec.kind == "local-action":
        return Provider.CLAUDE

    name = normalize_command_name(spec.name)

    # Regra 2: diretivas de sessao caem no fallback Claude.
    if name in _SESSION_DIRECTIVES:
        return Provider.CLAUDE

    if _llm_config_v2_enabled() and _provider_router_v2_enabled():
        # Regra 3 em modo V2 (item 010): se a familia do comando bate com a
        # familia do Main, o comando pertence ao terminal principal (T1 roda o
        # Main selecionado). Familia do comando vem das whitelists reais + flag.
        command_family = _command_family(spec, name)
        main_family, _main_variant = _classify_family_variant(state.main_llm)
        if command_family != "unknown" and command_family == main_family:
            return Provider.CLAUDE
    elif (
        not state.kimi_worker_enabled
        and not state.codex_worker_enabled
        and not state.qwen_worker_enabled
        and not state.grok_worker_enabled
    ):
        # Regra 3 legada: sem nenhum worker ativo, so existe o destino Claude/T1.
        return Provider.CLAUDE

    # Regra 4 (+ 6): Kimi tem precedencia (familia T2). is_kimi_compatible OU
    # o flag herdado kimi_eligible do item de loop ja basta.
    if state.kimi_worker_enabled and (spec.kimi_eligible or is_kimi_compatible(name)):
        return Provider.KIMI

    # Regra 4b: Qwen worker (familia T2, apos Kimi — PW-02).
    # Mesma elegibilidade que Kimi (kimi_eligible OU is_kimi_compatible).
    if state.qwen_worker_enabled and (spec.kimi_eligible or is_kimi_compatible(name)):
        return Provider.QWEN

    # Regra 5: Codex (familia T3) so quando T2 nao venceu acima.
    if state.codex_worker_enabled and is_codex_compatible(name):
        return Provider.CODEX

    # Regra 5b: Grok worker (familia T3, apos Codex — PW-02).
    # Mesma elegibilidade que Codex (is_codex_compatible).
    if state.grok_worker_enabled and is_codex_compatible(name):
        return Provider.GROK

    # Regra 7: fallback.
    return Provider.CLAUDE


def _command_family(spec: "CommandSpec", name: str) -> str:
    """Determina a familia do provider de um comando.

    Usa as whitelists reais (is_kimi_compatible, is_codex_compatible) e o flag
    ``kimi_eligible``. Retorna a familia (``"kimi"``, ``"codex"``, ``"claude"``)
    ou ``"unknown"`` quando nenhuma whitelist casa.
    """
    if spec.kimi_eligible or is_kimi_compatible(name):
        return "kimi"
    if is_codex_compatible(name):
        return "codex"
    return "unknown"
