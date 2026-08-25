"""Escritor de runtime do `_ROCKSMASH-STATE.json` (Tasks 19 e 20).

Ate 2026-08-24 o sidecar tinha schema, lock, troca atomica, produtor e
consumidor declarados — e nenhum chamador em `src/`. `begin_subphase` e
`mark_subphase` so eram exercitados por teste, entao a "unica autoridade de
maquina" do rocksmash nascia vazia em toda execucao real e o cursor por
subfase decidia sempre a mesma coisa: rodar o bloco inteiro. Um cursor que
nunca le progresso porque ninguem grava progresso nao e um cursor.

Este modulo e a ponte que faltava. Ele traduz o `LoopExecutionContext` que o
expander passou a anexar aos `CommandSpec` (`mode == "rocksmash"`,
`item_id`, `phase` = nome da subfase) em chamadas ao escritor canonico, e
sustenta a regra de ouro do sidecar: **quem executa a subfase nao atesta a
propria conclusao**. O ator e sempre `QUEUE_CONFIRMER`, isto e, a fila —
nunca o LLM que rodou o comando.

Tres decisoes que nao sao obvias:

1. **A config e lida uma vez, no bind, e nunca mais.** O `config_hash` do
   sidecar foi calculado sobre a config de onde a fila foi expandida. Reler o
   arquivo a cada escrita faria o `/loop-rocksmash:rename` (que reescreve o
   `_LOOP-CONFIG.json` no fim do run) invalidar a marcacao das ultimas
   subfases — o estado ficaria "stale" contra a config que o proprio run
   acabou de produzir, e a ultima iteracao voltaria a ser reenfileirada.

2. **`item_id` vem SEMPRE do contexto.** Extrair item do texto do comando
   (`/loop-rocksmash:do {task_path}`) acertaria o suficiente para parecer
   confiavel enquanto atribui a subfase errada em todo caso de path
   renomeado. O contexto e o unico canal legitimo (`domain.
   LoopExecutionContext`).

3. **Falha de escrita nao e silenciosa nem fatal por conta propria.**
   `CursorWrite.error` sobe para o chamador, que decide: no `begin` a recusa
   ABORTA o dispatch (dois dispatches da mesma subfase e exatamente o que o
   cursor existe para impedir); no `finish` ela vira aviso, porque o efeito ja
   aconteceu e engolir o desfecho seria pior que registra-lo com atraso.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from workflow_app.daily_loop.rocksmash_state import (
    QUEUE_CONFIRMER,
    SUBPHASES,
    SUBPHASES_LEGACY,
    RocksmashStateError,
    begin_subphase,
    mark_subphase,
)

logger = logging.getLogger(__name__)

#: Discriminador que o expander grava em `LoopExecutionContext.mode`. E o
#: unico marcador que distingue uma fila rocksmash de uma fila `/loop` normal
#: depois que os specs sairam do expander (o `mode` persistido na config nao
#: serve: a preparacao normal nunca escreve `mode == "rocksmash"`).
ROCKSMASH_MODE = "rocksmash"

#: Prefixo do comando de framing que carrega o path da config. E o ancoradouro
#: do rebind: uma fila rocksmash restaurada de snapshot chega sem o objeto de
#: binding, mas SEMPRE com este comando, porque `_assert_expanded_queue_shape`
#: exige `:prepare` como primeiro comando nao-diretiva.
PREPARE_VERB = "/loop-rocksmash:prepare"

#: Uniao das duas listas de subfase. O modo legacy (`do` + `review-done`) e
#: rede de rollback ainda suportada (A7 de `loop-rules.md` decidiu MANTER),
#: entao o cursor tem que reconhecer as duas — filtrar so pelo canonico faria
#: um run legacy passar batido e nao gravar nada.
KNOWN_SUBPHASES: frozenset[str] = frozenset(SUBPHASES) | frozenset(SUBPHASES_LEGACY)


@dataclass(frozen=True)
class CursorWrite:
    """Resultado de uma tentativa de escrita no sidecar.

    `applied=False` com `error=None` NAO e falha: e o caminho normal de todo
    comando que nao e subfase rocksmash (diretiva, framing, fila comum). Os
    dois casos precisam ser distinguiveis, senao o chamador nao consegue
    separar "nao se aplica" de "tentou e nao deu".
    """

    applied: bool
    item_id: str | None = None
    subphase: str | None = None
    error: str | None = None


_NAO_SE_APLICA = CursorWrite(applied=False)


def scoped_subphase(ctx: Any) -> tuple[str, str] | None:
    """`(item_id, subphase)` quando `ctx` descreve uma subfase rocksmash.

    Devolve `None` para tudo o mais — incluindo comando de loop normal, que
    tambem carrega `item_id` e `phase`. Sem o teste de `mode` o cursor tentaria
    marcar subfase de um loop que nao tem sidecar nenhum, e cada item de
    `/loop` viraria um erro registrado.
    """
    if ctx is None:
        return None
    if getattr(ctx, "mode", None) != ROCKSMASH_MODE:
        return None
    item_id = getattr(ctx, "item_id", None)
    subphase = getattr(ctx, "phase", None)
    if not item_id or subphase not in KNOWN_SUBPHASES:
        return None
    return str(item_id), str(subphase)


class RocksmashRuntimeCursor:
    """Binding vivo entre a fila em execucao e o sidecar de um loop.

    Instanciado por `from_specs` quando a fila carregada e uma fila rocksmash.
    Fora disso o widget mantem `None` e nenhuma escrita acontece: uma fila que
    nao e rocksmash nao tem subfase para marcar.
    """

    def __init__(self, config_path: Path, raw_config: dict[str, Any]) -> None:
        self._config_path = Path(config_path)
        self._raw_config = raw_config

    # ────────────────────────────────────────────────────────── bind ── #

    @classmethod
    def from_specs(
        cls, specs: Iterable[Any]
    ) -> RocksmashRuntimeCursor | None:
        """Reconstroi o binding a partir da fila, ou `None`.

        O ancoradouro e o argumento de `/loop-rocksmash:prepare`, que e um path
        estrutural produzido pelo proprio expander — nao uma inferencia sobre
        qual item o comando trata. Fazer o rebind aqui, e nao no handler do
        botao, cobre de graca o caminho de snapshot/restore: uma fila rocksmash
        restaurada volta com o cursor ligado, em vez de rodar subfases sem
        gravar nada e reenfileira-las na proxima expansao.
        """
        for spec in specs or []:
            nome = str(getattr(spec, "name", "") or "")
            if not nome.startswith(PREPARE_VERB + " "):
                continue
            bruto = nome[len(PREPARE_VERB) :].strip()
            if not bruto:
                continue
            caminho = Path(bruto)
            try:
                raw = json.loads(caminho.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                # Config ilegivel: sem ela nao da para validar o `config_hash`,
                # e escrever sem validar e o unico erro que o sidecar nao pode
                # cometer. Fica sem cursor, e cursor `None` e fail-closed no
                # widget (`_begin_rocksmash_subphase`): spec COMUM da fila segue
                # despachando, spec de subfase rocksmash tem o dispatch RECUSADO
                # com toast `warning`. Nada entra em voo sem `in_flight` gravado.
                logger.warning(
                    "[rocksmash] config ilegivel em %s — cursor desligado nesta fila",
                    caminho,
                )
                return None
            if not isinstance(raw, dict):
                return None
            return cls(caminho, raw)
        return None

    @property
    def loop_root(self) -> Path:
        return self._config_path.parent

    @property
    def config_path(self) -> Path:
        return self._config_path

    # ───────────────────────────────────────────────────────── write ── #

    def begin(self, ctx: Any, *, pid: int | None = None) -> CursorWrite:
        """Marca `in_flight` ANTES do dispatch.

        A assimetria e a do proprio sidecar: gravar antes produz falso positivo
        barato (subfase em voo que nunca comecou vira `unknown` e pede
        reconciliacao); gravar depois produziria falso negativo caro (efeito
        aplicado, arquivo dizendo `pending`, retomada repetindo o trabalho).
        """
        alvo = scoped_subphase(ctx)
        if alvo is None:
            return _NAO_SE_APLICA
        item_id, subphase = alvo
        try:
            begin_subphase(
                self.loop_root,
                self._raw_config,
                item_id,
                subphase,
                actor=QUEUE_CONFIRMER,
                pid=pid,
            )
        except RocksmashStateError as exc:
            return CursorWrite(False, item_id, subphase, str(exc))
        except Exception as exc:  # noqa: BLE001 - erro de IO nao previsto
            logger.warning("[rocksmash] begin %s/%s falhou", item_id, subphase, exc_info=True)
            return CursorWrite(False, item_id, subphase, str(exc))
        return CursorWrite(True, item_id, subphase)

    def finish(
        self, ctx: Any, *, failed: bool, note: str | None = None
    ) -> CursorWrite:
        """Grava o desfecho APOS retorno autoritativo do terminal.

        "Autoritativo" aqui e o mesmo criterio da barra de metricas: verde
        pos-fence (`listener_authoritative_idle`) ou falha declarada
        (`autocast_abort_requested`). Colar texto no terminal
        (`_mark_as_sent`) nao e desfecho e esta proibido por escrito como
        gatilho — ver Regra L14.7 de `ai-forge/rules/loop-rules.md`.
        """
        alvo = scoped_subphase(ctx)
        if alvo is None:
            return _NAO_SE_APLICA
        item_id, subphase = alvo
        try:
            mark_subphase(
                self.loop_root,
                self._raw_config,
                item_id,
                subphase,
                status="failed" if failed else "completed",
                actor=QUEUE_CONFIRMER,
                note=note,
            )
        except RocksmashStateError as exc:
            return CursorWrite(False, item_id, subphase, str(exc))
        except Exception as exc:  # noqa: BLE001 - erro de IO nao previsto
            logger.warning("[rocksmash] finish %s/%s falhou", item_id, subphase, exc_info=True)
            return CursorWrite(False, item_id, subphase, str(exc))
        return CursorWrite(True, item_id, subphase)
