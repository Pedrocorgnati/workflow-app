"""Envelope versionado de LoopLifecycleEvent (Task 15 do estudo 08-24).

Por que NAO e o FailureEvent com mais campos. O FailureEvent responde "o que
quebrou"; este responde "quanto custou e onde estavamos". Sao perguntas com
publicos e nulabilidades diferentes: falha sem item ainda e falha util, mas
custo sem item nem provider efetivo nao mede nada. Fundir os dois produziria um
envelope com metade dos campos sempre nulos - exatamente o defeito que o corte
auditado ja exibia no funil de falhas.

Regra central de correlacao (12.2.5): `item_id` NUNCA e inferido do texto do
comando. Ele nasce no builder da fila, viaja em `LoopExecutionContext` dentro do
`CommandSpec`, sobrevive a snapshot/restore e chega ao dispatcher. Inferir do
texto quebraria em todo comando que nao carrega `--item` (os expandidos de
`cmd-single`, por exemplo) e produziria correlacao silenciosamente errada -
pior que ausente, porque parece dado.

Nulabilidade por tipo de evento, nao por conveniencia:

- eventos de ITEM exigem `item_id` e `phase`;
- eventos puramente de FILA exigem os dois nulos (fila nao esta "num item");
- `provider_blocked` e contextual: pode ocorrer com ou sem item em voo;
- `provider_effective`, `model_effective` e `effort_effective` sao obrigatorios
  a partir do despacho - antes dele nao existe "efetivo", so intencao;
- `usage_tokens`, `cost` e `duration` sao nulos SOMENTE quando o provider nao os
  expoe. Nulo aqui e "nao observado", nunca "zero".
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any, Final

SCHEMA_VERSION: Final[str] = "1.0.0"

EVENT_TYPES: Final[frozenset[str]] = frozenset(
    {
        "queue_started",
        "item_dispatched",
        "item_completed",
        "item_failed",
        "queue_paused",
        "queue_resumed",
        "queue_canceled",
        "app_closed",
        "provider_blocked",
    }
)

RESULTS: Final[frozenset[str]] = frozenset(
    {"started", "succeeded", "failed", "paused", "canceled", "blocked", "unknown"}
)

#: Eventos que acontecem DENTRO de um item: `item_id` e `phase` obrigatorios.
ITEM_EVENTS: Final[frozenset[str]] = frozenset(
    {"item_dispatched", "item_completed", "item_failed"}
)

#: Eventos puramente de fila: `item_id` e `phase` tem que ser nulos. Registrar
#: um item aqui inventaria escopo que o evento nao tem.
QUEUE_EVENTS: Final[frozenset[str]] = frozenset(
    {
        "queue_started",
        "queue_paused",
        "queue_resumed",
        "queue_canceled",
        "app_closed",
    }
)

#: Contextual: bloqueio de provider pode pegar a fila parada ou um item em voo.
#: Forcar qualquer um dos dois lados produziria dado falso em metade dos casos.
CONTEXTUAL_EVENTS: Final[frozenset[str]] = frozenset({"provider_blocked"})

#: A partir daqui existe execucao real, entao provider/model/effort EFETIVOS
#: (o que foi de fato usado, nao o que a config pediu) sao obrigatorios.
DISPATCH_ONWARD: Final[frozenset[str]] = ITEM_EVENTS | CONTEXTUAL_EVENTS

#: Resultado default por tipo. Evita que o emissor escolha um `result`
#: incoerente com o evento.
_RESULT_PADRAO: Final[dict[str, str]] = {
    "queue_started": "started",
    "item_dispatched": "started",
    "item_completed": "succeeded",
    "item_failed": "failed",
    "queue_paused": "paused",
    "queue_resumed": "started",
    "queue_canceled": "canceled",
    "app_closed": "unknown",
    "provider_blocked": "blocked",
}

CAMPOS_SEMPRE_PRESENTES: Final[tuple[str, ...]] = (
    "schema_version",
    "event_id",
    "ts",
    "event_type",
    "result",
    "queue_id",
    "loop_id",
)

CAMPOS_NAO_OBSERVAVEIS: Final[tuple[str, ...]] = ("usage_tokens", "cost", "duration")


class LoopLifecycleEventError(ValueError):
    """Envelope invalido. Erro do emissor, nao do corpus."""


@dataclass(frozen=True)
class LoopExecutionContextView:
    """Projecao minima do `LoopExecutionContext` que este modulo consome.

    Declarada aqui para o modulo de telemetria nao depender de `domain.py`
    (que arrasta Qt pela cadeia de imports). Qualquer objeto com estes
    atributos serve - inclusive o `LoopExecutionContext` real.
    """

    loop_id: str
    queue_id: str
    item_id: str | None = None
    phase: str | None = None


def _nullable_str(valor: Any) -> str | None:
    if valor is None:
        return None
    texto = str(valor).strip()
    return texto or None


def _nullable_num(valor: Any) -> float | int | None:
    """`None` para ausencia. Zero legitimo (custo zero de um `/clear`) e
    preservado - o que nao pode e ausencia virar zero."""
    if valor is None or isinstance(valor, bool):
        return None
    if isinstance(valor, (int, float)):
        return valor
    try:
        return float(valor)
    except (TypeError, ValueError):
        return None


def build_lifecycle_event(
    *,
    event_type: str,
    loop_id: Any,
    queue_id: Any,
    result: str | None = None,
    context: Any = None,
    item_id: Any = None,
    phase: Any = None,
    provider_effective: Any = None,
    model_effective: Any = None,
    effort_effective: Any = None,
    usage_tokens: Any = None,
    cost: Any = None,
    duration: Any = None,
    ts: float | None = None,
    event_id: str | None = None,
) -> dict[str, Any]:
    """Monta o envelope, validando a nulabilidade por tipo.

    `context` (um `LoopExecutionContext`) tem precedencia como FONTE de
    `item_id`/`phase`: e ele que carrega a correlacao nascida no builder.
    Passar os campos soltos existe para eventos de fila e para testes.
    """
    # Alias primeiro (Task 24): `item_started` do vocabulario do estudo entra
    # e sai como `item_dispatched`, o nome canonico do envelope.
    event_type = normalize_event_type(event_type)
    if event_type not in EVENT_TYPES:
        raise LoopLifecycleEventError(f"event_type fora do enum: {event_type!r}")

    resultado = result or _RESULT_PADRAO[event_type]
    if resultado not in RESULTS:
        raise LoopLifecycleEventError(f"result fora do enum: {resultado!r}")

    loop = _nullable_str(loop_id)
    fila = _nullable_str(queue_id)
    if loop is None or fila is None:
        raise LoopLifecycleEventError(
            "loop_id e queue_id sao obrigatorios: sem eles o evento nao "
            "correlaciona com nada e nao serve a experimento de custo"
        )

    if context is not None:
        item = _nullable_str(getattr(context, "item_id", None))
        fase = _nullable_str(getattr(context, "phase", None))
        if item_id is not None:
            item = _nullable_str(item_id)
        if phase is not None:
            fase = _nullable_str(phase)
    else:
        item = _nullable_str(item_id)
        fase = _nullable_str(phase)

    if event_type in ITEM_EVENTS:
        if item is None or fase is None:
            raise LoopLifecycleEventError(
                f"{event_type} e evento de item: item_id e phase sao "
                "obrigatorios. Se a correlacao nao chegou ate aqui, o defeito "
                "esta no contexto que atravessa a fila, nao neste envelope."
            )
    elif event_type in QUEUE_EVENTS:
        if item is not None or fase is not None:
            raise LoopLifecycleEventError(
                f"{event_type} e evento puramente de fila: item_id e phase "
                "tem que ser nulos"
            )

    provider = _nullable_str(provider_effective)
    modelo = _nullable_str(model_effective)
    esforco = _nullable_str(effort_effective)
    if event_type in DISPATCH_ONWARD and event_type not in CONTEXTUAL_EVENTS:
        faltando = [
            nome
            for nome, valor in (
                ("provider_effective", provider),
                ("model_effective", modelo),
                ("effort_effective", esforco),
            )
            if valor is None
        ]
        if faltando:
            raise LoopLifecycleEventError(
                f"{event_type} ocorre a partir do despacho: {', '.join(faltando)} "
                "obrigatorio(s). Sem o valor EFETIVO nao da para atribuir custo "
                "ao tier certo."
            )

    momento = time.time() if ts is None else float(ts)
    return {
        "schema_version": SCHEMA_VERSION,
        "event_id": event_id or uuid.uuid4().hex,
        # Epoch UTC, mesma decisao do FailureEvent: consumidores existentes
        # filtram por `ts` numerico. `ts_iso` acompanha para leitura humana.
        "ts": momento,
        "ts_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(momento)),
        "event_type": event_type,
        "result": resultado,
        "queue_id": fila,
        "loop_id": loop,
        "item_id": item,
        "phase": fase,
        "provider_effective": provider,
        "model_effective": modelo,
        "effort_effective": esforco,
        # Nulos SOMENTE quando o provider nao expoe. Zero e valor, nao ausencia.
        "usage_tokens": _nullable_num(usage_tokens),
        "cost": _nullable_num(cost),
        "duration": _nullable_num(duration),
    }


# ---------------------------------------------------------------------------
# Task 24 - classificacao historica de loop e a janela `stale`
# ---------------------------------------------------------------------------
#
# Por que a classificacao mora aqui e nao no auditor de corpus: ela e uma
# funcao dos EVENTOS, e o contrato dos eventos e este modulo. O auditor le
# `PROGRESS.md`, que registra marcadores de item - nunca ciclo de vida de
# execucao. Um loop com `[ ]` pendente pode estar rodando agora, pausado ha
# uma hora, cancelado ontem ou abandonado em maio: o marcador e identico nos
# quatro casos. Foi exatamente esse colapso que produziu a metrica de
# "abandono" que o criterio 12.2.18 proibe publicar antes das definicoes.

#: Classes historicas. `active` e `stale` NAO sao dois nomes para a mesma
#: coisa: `active` afirma que ha execucao em voo; `stale` afirma que passou
#: uma janela DECLARADA sem nenhum evento. A segunda so existe com a janela.
LOOP_STATES: Final[frozenset[str]] = frozenset(
    {
        "completed",
        "completed_with_failures",
        "active",
        "stale",
        "paused",
        "canceled",
    }
)

#: Estado de saida quando a evidencia nao permite decidir. NAO pertence a
#: `LOOP_STATES` de proposito: e a recusa de classificar, nao uma classe.
#: Somar `indeterminado` a `stale` seria reintroduzir a inferencia por mtime
#: com outro nome.
STATE_INDETERMINADO: Final[str] = "indeterminado"

#: Proposta de janela, em segundos (14 dias). NAO e default silencioso:
#: `classify_loop_state` exige a janela explicitamente e nunca consulta esta
#: constante sozinha. Ela existe para dar ao operador um numero concreto para
#: ratificar ou recusar, com o racional registrado em `loop-rules.md`.
JANELA_STALE_PROPOSTA_SEGUNDOS: Final[int] = 14 * 24 * 3600

#: `True` desde a ratificacao do operador em 2026-08-24 (gate G-JANELA-STALE,
#: `loop-rules.md` secao 14.4). O valor ratificado e o proposto:
#: `JANELA_STALE_PROPOSTA_SEGUNDOS` (14 dias). Enquanto era `False`,
#: `abandonment_metrics_publishable` recusava publicar qualquer metrica de
#: abandono (criterio 12.2.18); a ratificacao derruba ESSE bloqueio e nenhum
#: outro — janela nao declarada na chamada e loop `indeterminado` no corte
#: continuam barrando a publicacao.
JANELA_STALE_RATIFICADA: Final[bool] = True

#: Data da ratificacao (ISO). Registrada em codigo para que o auditor consiga
#: dizer DESDE QUANDO a porta esta aberta sem depender de alguem lembrar de
#: ler o quadro em `loop-rules.md`.
JANELA_STALE_RATIFICADA_EM: Final[str] = "2026-08-24"

#: Valor efetivamente ratificado, em segundos. Igual a proposta: o operador
#: aceitou os 14 dias sem contraproposta. Consumidores que precisam da janela
#: acordada leem ESTA constante — `JANELA_STALE_PROPOSTA_SEGUNDOS` continua
#: significando "o numero que foi levado a mesa", nao "o numero em vigor".
JANELA_STALE_SEGUNDOS: Final[int] = JANELA_STALE_PROPOSTA_SEGUNDOS

#: Data-limite do gate G-JANELA-STALE (`loop-rules.md` secao 14.4), em ISO.
#: NAO ratifica por decurso de prazo: passar da data so faz o gate ser
#: reportado como VENCIDO, e a porta de publicacao continua fechada. A
#: constante existe para que o vencimento seja VERIFICAVEL por codigo - o
#: quadro em `loop-rules.md` prometia relatorio automatico e nao tinha um
#: unico consumidor, ou seja, o vencimento dependia de alguem lembrar.
JANELA_STALE_GATE_DEADLINE: Final[str] = "2026-09-21"


def stale_gate_status(
    *, now: float, ratified: bool = JANELA_STALE_RATIFICADA
) -> dict[str, Any]:
    """Estado do gate G-JANELA-STALE no instante `now` (epoch UTC).

    `now` e INJETADO, nunca lido do relogio aqui: o auditor de corpus e
    reproduzivel por `--as-of`, e ler o relogio dentro tornaria o mesmo corpus
    produzir relatorios diferentes em dias diferentes.

    `ratified` tambem e injetavel (default: a constante do repo). O parametro
    existe para que a propriedade "vencer o prazo NAO ratifica" continue sendo
    testavel como LOGICA da funcao depois que o operador ratificou de fato em
    2026-08-24 — sem ele, o unico teste dessa propriedade viraria uma
    tautologia sobre a decisao atual do repo e pararia de proteger o proximo
    gate que abrir.

    `expired` e informativo. Ele NAO ratifica nada e NAO desbloqueia
    `abandonment_metrics_publishable`; ratificacao por decurso de prazo e
    exatamente o default silencioso que a secao 14.4 proibe.
    """
    from datetime import datetime, timezone

    limite = datetime.strptime(JANELA_STALE_GATE_DEADLINE, "%Y-%m-%d").replace(
        tzinfo=timezone.utc
    )
    limite_ts = limite.timestamp()
    return {
        "gate": "G-JANELA-STALE",
        "deadline": JANELA_STALE_GATE_DEADLINE,
        "ratified": ratified,
        "ratified_at": JANELA_STALE_RATIFICADA_EM if ratified else None,
        "window_seconds": JANELA_STALE_SEGUNDOS if ratified else None,
        "open": not ratified,
        "expired": (not ratified) and now > limite_ts,
        "note": (
            "vencimento NAO ratifica a janela; exige renovacao explicita da "
            "data em ai-forge/rules/loop-rules.md secao 14.4"
        ),
    }

#: Eventos que encerram a fila. Ordem de precedencia em `classify_loop_state`.
_EVENTOS_TERMINAIS: Final[tuple[str, ...]] = ("queue_canceled",)

#: Alias aceito na entrada. O estudo 08-24 nomeia `item_started`; o envelope
#: da Task 15 ja tinha nomeado `item_dispatched`. Renomear o enum quebraria os
#: eventos ja emitidos; aceitar os dois nomes e normalizar para o canonico
#: preserva o corpus e atende ao vocabulario do estudo. `dispatched` continua
#: sendo o nome canonico porque e o instante em que provider/model/effort
#: EFETIVOS passam a existir - "started" seria ambiguo entre enfileirar e
#: despachar.
EVENT_TYPE_ALIASES: Final[dict[str, str]] = {"item_started": "item_dispatched"}


def normalize_event_type(event_type: str) -> str:
    """Resolve alias de `event_type`. Desconhecido passa direto (a validacao
    do enum acontece em `build_lifecycle_event`, com a mensagem certa)."""
    return EVENT_TYPE_ALIASES.get(event_type, event_type)


def classify_loop_state(
    *,
    events: list[dict[str, Any]] | tuple[dict[str, Any], ...],
    pending: int,
    failed: int = 0,
    now: float,
    stale_window_seconds: float | None,
    has_active_queue: bool = False,
) -> dict[str, Any]:
    """Classifica UM loop a partir dos seus eventos de lifecycle.

    Contrato (10.2 I5):

    - `canceled` e `paused` exigem EVENTO explicito. Nunca sao inferidos de
      ausencia de atividade.
    - `stale` exige janela declarada E ausencia de fila ativa E ausencia de
      evento dentro da janela. Sem janela o resultado e `indeterminado`.
    - `pending` sozinho nao decide nada: ele entra apenas para separar
      `completed` de `active`/`stale`, e so depois de os eventos terem
      falado.
    - Zero evento => `indeterminado` com motivo `sem_evento_de_lifecycle`.
      E o caso dos loops anteriores a esta instrumentacao: eles nao sao
      "abandonados", sao NAO MEDIDOS. A diferenca e o inteiro relatorio.

    `now` e injetado (nao lido do relogio) para a classificacao ser
    reproduzivel: o mesmo corpus com o mesmo corte tem que dar o mesmo
    resultado em qualquer maquina.
    """
    ordenados = sorted(
        (e for e in events if isinstance(e, dict)),
        key=lambda e: float(e.get("ts") or 0.0),
    )

    if not ordenados:
        return {
            "state": STATE_INDETERMINADO,
            "reason": "sem_evento_de_lifecycle",
            "decided_by": "ausencia_de_evento",
            "last_event_ts": None,
            "age_seconds": None,
        }

    ultimo = ordenados[-1]
    last_ts = float(ultimo.get("ts") or 0.0)
    idade = max(0.0, float(now) - last_ts)
    tipos = [normalize_event_type(str(e.get("event_type") or "")) for e in ordenados]

    # 1. Cancelamento e terminal e explicito.
    for terminal in _EVENTOS_TERMINAIS:
        if terminal in tipos:
            return {
                "state": "canceled",
                "reason": f"evento_{terminal}",
                "decided_by": "evento_explicito",
                "last_event_ts": last_ts,
                "age_seconds": idade,
            }

    # 2. Pausa vale enquanto nao houver retomada DEPOIS dela.
    ultimo_pause = _ultimo_indice(tipos, "queue_paused")
    ultimo_resume = _ultimo_indice(tipos, "queue_resumed")
    if ultimo_pause is not None and (
        ultimo_resume is None or ultimo_resume < ultimo_pause
    ):
        return {
            "state": "paused",
            "reason": "queue_paused_sem_resume_posterior",
            "decided_by": "evento_explicito",
            "last_event_ts": last_ts,
            "age_seconds": idade,
        }

    # 3. Sem trabalho pendente: terminou. Falha nao apaga a conclusao, so
    #    muda a classe - `completed_with_failures` continua sendo um loop que
    #    chegou ao fim, e some-lo a `completed` esconderia retrabalho.
    houve_falha = failed > 0 or "item_failed" in tipos
    if pending <= 0:
        return {
            "state": "completed_with_failures" if houve_falha else "completed",
            "reason": "sem_item_pendente",
            "decided_by": "evento_mais_marcadores",
            "last_event_ts": last_ts,
            "age_seconds": idade,
        }

    # 4. Fila viva agora: `active`, sem depender de janela nenhuma.
    if has_active_queue:
        return {
            "state": "active",
            "reason": "fila_ativa_no_corte",
            "decided_by": "fila_viva",
            "last_event_ts": last_ts,
            "age_seconds": idade,
        }

    # 5. Daqui para baixo a decisao PRECISA da janela. Sem ela, recusa.
    if stale_window_seconds is None:
        return {
            "state": STATE_INDETERMINADO,
            "reason": "janela_stale_nao_declarada",
            "decided_by": "recusa_por_falta_de_definicao",
            "last_event_ts": last_ts,
            "age_seconds": idade,
        }

    if idade > float(stale_window_seconds):
        return {
            "state": "stale",
            "reason": "sem_evento_dentro_da_janela_declarada",
            "decided_by": "janela_declarada",
            "last_event_ts": last_ts,
            "age_seconds": idade,
            "stale_window_seconds": float(stale_window_seconds),
        }

    return {
        "state": "active",
        "reason": "evento_dentro_da_janela_declarada",
        "decided_by": "janela_declarada",
        "last_event_ts": last_ts,
        "age_seconds": idade,
        "stale_window_seconds": float(stale_window_seconds),
    }


def _ultimo_indice(tipos: list[str], alvo: str) -> int | None:
    for i in range(len(tipos) - 1, -1, -1):
        if tipos[i] == alvo:
            return i
    return None


def abandonment_metrics_publishable(
    *,
    stale_window_seconds: float | None,
    window_ratified: bool = JANELA_STALE_RATIFICADA,
    states: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    """Porta do criterio 12.2.18: metrica de abandono nao sai antes das definicoes.

    Tres bloqueios independentes, cada um com motivo proprio - agregar em um
    booleano solto esconderia QUAL definicao esta faltando.
    """
    bloqueios: list[str] = []
    if stale_window_seconds is None:
        bloqueios.append("janela_stale_nao_declarada")
    if not window_ratified:
        bloqueios.append("janela_stale_nao_ratificada_pelo_operador")
    if states is not None and any(s == STATE_INDETERMINADO for s in states):
        bloqueios.append("existem_loops_indeterminados_no_corte")
    return {
        "publishable": not bloqueios,
        "blockers": bloqueios,
        "rule": "12.2.18 - nao publicar abandono antes de definir paused, "
        "canceled, active e stale",
    }
