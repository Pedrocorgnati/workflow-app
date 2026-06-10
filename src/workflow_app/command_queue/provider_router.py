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
  - Inv 2: o eixo Worker e avaliado ANTES do eixo Main-LLM. `main_llm` vive em
    `RoutingState` para a UI/telemetria, mas a classificacao escolhe apenas entre
    despachar a um worker (T2/T3) ou cair em Claude/T1. Por isso "T1 verde via
    Main Kimi/Codex" da matriz (secao 11, linhas 5-6) resolve para Provider.CLAUDE.
  - Inv 3: o provider por item NUNCA altera quais comandos entram na lista. Este
    modulo nao toca lista/ordem/matrix; so classifica um spec ja enfileirado.
  - Inv 8: `local-action` nao e comando de provider e nunca vai para T1/T2/T3.

Pureza (source.md secao 12): sem import de Qt, sem side effect, sem I/O. As
unicas dependencias sao as duas whitelists puras e (apenas para tipagem) o
`CommandSpec`. `classify_provider` assume `spec` e `state` validos (nao-None);
validacao de schema e responsabilidade do caller no step path (task 004). O
comportamento com entrada invalida e indefinido por contrato.
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


# Diretivas de sessao do Claude Code. Nunca sao elegiveis a worker por whitelist;
# equivalem a cair no fallback Claude (source.md secao 7.1 regra 2 + secao 5
# invariantes 6 e 7).
_SESSION_DIRECTIVES: frozenset[str] = frozenset({"/clear", "/model", "/effort"})


class Provider(str, Enum):
    """Provider efetivo do clique no botao unico da queue.

    str-Enum para serializar direto em logs/telemetria e comparar com strings
    cruas sem `.value`.
    """

    CLAUDE = "claude"
    KIMI = "kimi"
    CODEX = "codex"


@dataclass(frozen=True)
class RoutingState:
    """Estado de roteamento avaliado no momento do clique.

    `kimi_worker_enabled` / `codex_worker_enabled` sao os checkboxes de worker
    (T2/T3). `main_llm` e o Main LLM do T1 ("claude" | "kimi" | "codex"); fica
    aqui para UI/telemetria mas NAO participa da classificacao (invariante 2: o
    eixo Worker decide; o Main-LLM no T1 e sempre o fallback verde/T1).
    """

    kimi_worker_enabled: bool
    codex_worker_enabled: bool
    main_llm: str


def normalize_command_name(name: str) -> str:
    """Reduz um comando a sua cabeca (primeiro token), descartando flags/args.

    Espelha o matching das whitelists (`.strip().split(None, 1)[0]`) para que a
    deteccao de diretiva da regra 2 use a mesma normalizacao. Entrada vazia ou so
    com espacos retorna "".
    """
    if not name or not name.strip():
        return ""
    return name.strip().split(None, 1)[0]


def classify_provider(spec: "CommandSpec", state: RoutingState) -> Provider:
    """Classifica o provider efetivo de UM item da fila (funcao pura).

    Ordem das regras (source.md secao 7.1; a ordem importa):
      1. `spec.kind == "local-action"` -> CLAUDE (invariante 8: nunca a worker).
      2. Diretiva `/clear` | `/model` | `/effort` -> CLAUDE (nao elegivel a
         worker por whitelist; equivale ao fallback da regra 7).
      3. Nenhum worker ativo -> CLAUDE.
      4. Kimi worker ativo E (kimi_eligible OU is_kimi_compatible) -> KIMI.
      5. Codex worker ativo E is_codex_compatible -> CODEX.
      6. Kimi e Codex elegiveis ao mesmo tempo -> Kimi vence (regra 4 precede a 5).
      7. Sem elegibilidade worker -> CLAUDE.

    O eixo Worker (regras 4-6) e avaliado antes do eixo Main-LLM (invariante 2):
    `state.main_llm` nao participa da decisao. Assume `spec` e `state` nao-None
    (contrato; entrada invalida e comportamento indefinido).
    """
    # Regra 1: local-action nunca vai para terminal worker.
    if spec.kind == "local-action":
        return Provider.CLAUDE

    name = normalize_command_name(spec.name)

    # Regra 2: diretivas de sessao caem no fallback Claude.
    if name in _SESSION_DIRECTIVES:
        return Provider.CLAUDE

    # Regra 3: sem nenhum worker ativo, so existe o destino Claude/T1.
    if not state.kimi_worker_enabled and not state.codex_worker_enabled:
        return Provider.CLAUDE

    # Regra 4 (+ 6): Kimi tem precedencia. is_kimi_compatible OU o flag herdado
    # kimi_eligible do item de loop ja basta.
    if state.kimi_worker_enabled and (spec.kimi_eligible or is_kimi_compatible(name)):
        return Provider.KIMI

    # Regra 5: Codex so quando Kimi nao venceu acima.
    if state.codex_worker_enabled and is_codex_compatible(name):
        return Provider.CODEX

    # Regra 7: fallback.
    return Provider.CLAUDE
