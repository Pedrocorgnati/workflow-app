"""Sidecar JSONL do `LoopLifecycleEvent` (Task 24 do estudo 08-24).

Por que este modulo existe. Ate aqui os quatro emissores de
`command_queue_widget` montavam envelopes validos e os guardavam em
`self._last_lifecycle_event` / `self._last_queue_lifecycle_event`. Nenhum
ponto de `src/` LIA esses atributos: cada evento sobrescrevia o anterior e
morria com o processo. O corpus de ciclo de vida — o unico insumo capaz de
distinguir loop `active` de `paused`, `canceled` e `stale` — nunca chegou a
existir. Sem corpus, `classify_loop_state` so tinha `PROGRESS.md`, e um `[ ]`
pendente e identico nos quatro casos. Foi esse colapso que produziu a metrica
de "abandono" que o criterio 12.2.18 proibe publicar.

Decisoes de desenho, e o motivo de cada uma:

- **Um arquivo por PID.** Duas janelas do app rodando o mesmo loop escreveriam
  intercaladas no mesmo arquivo; `dispatch_telemetry` ja resolveu isso assim e
  a correlacao entre os dois sidecars fica trivial quando ambos usam o mesmo
  criterio de particao.
- **Com rotacao.** E a lacuna que `dispatch_telemetry` deixou aberta: um
  sidecar que cresce sem teto acaba sendo apagado a mao, e a evidencia some
  justamente no loop longo, que e o unico que interessa medir. `.1` a `.5`
  preserva o passado recente sem risco de encher o disco do operador.
- **Best-effort, sempre.** Toda funcao engole a propria excecao. Telemetria
  que derruba a fila e pior que telemetria ausente — a fila e o produto, o
  sidecar e a observacao.
- **Guard de suite.** Mesma forma de `real_failure_telemetry_blocked`: a
  variavel `WF_BLOCK_REAL_LIFECYCLE_TELEMETRY`, armada no `conftest`, impede
  que 400 testes contaminem o corpus do operador com eventos sinteticos. O
  guard cede ao override explicito de diretorio, para que um teste possa
  apontar para `tmp_path` e provar que a escrita acontece de fato.

O que este modulo NAO faz: nao valida o envelope (quem valida e
`build_lifecycle_event`, que recusa evento sem `loop_id`/`queue_id`) e nao
classifica nada (quem classifica e `classify_loop_state`, a partir do que for
lido daqui).
"""

from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Any

from workflow_app.dispatch_telemetry import mask

logger = logging.getLogger(__name__)

#: Armada pelo `conftest` da suite. Enquanto valer "1", o sink recusa o
#: diretorio REAL do operador — mas nunca um diretorio dado explicitamente.
SINK_GUARD_ENV: str = "WF_BLOCK_REAL_LIFECYCLE_TELEMETRY"

#: Override explicito do diretorio de destino. Existe para teste e para
#: investigacao dirigida; nao e configuracao de produto.
SINK_DIR_ENV: str = "SF_LOOP_LIFECYCLE_DIR"

#: Teto por arquivo antes de rotacionar, e quantas geracoes ficam.
MAX_BYTES: int = 5 * 1024 * 1024
MAX_GENERATIONS: int = 5

_lock = threading.Lock()


def _default_dir() -> Path:
    return Path.home() / ".workflow-app" / "logs"


def sink_dir() -> Path | None:
    """Diretorio de destino, ou ``None`` quando a escrita esta bloqueada.

    Ordem: override explicito (sempre vence, inclusive sob guard) -> diretorio
    real do operador, desde que o guard nao esteja armado.
    """
    override = os.environ.get(SINK_DIR_ENV, "").strip()
    if override:
        return Path(override)
    if os.environ.get(SINK_GUARD_ENV) == "1":
        return None
    return _default_dir()


def sink_path() -> Path | None:
    """Arquivo desta instancia, ou ``None`` quando a escrita esta bloqueada."""
    base = sink_dir()
    if base is None:
        return None
    return base / f"loop-lifecycle-{os.getpid()}.jsonl"


def _rotate_if_needed(path: Path) -> None:
    """Roda `path` para `.1` quando ele passa de `MAX_BYTES`.

    Rotacao por tamanho, nao por data: o que precisa caber e uma investigacao,
    e uma investigacao anda por volume de eventos, nao por calendario.
    """
    try:
        if not path.exists() or path.stat().st_size < MAX_BYTES:
            return
    except OSError:
        return
    try:
        mais_antigo = path.with_suffix(path.suffix + f".{MAX_GENERATIONS}")
        if mais_antigo.exists():
            mais_antigo.unlink()
        for geracao in range(MAX_GENERATIONS - 1, 0, -1):
            origem = path.with_suffix(path.suffix + f".{geracao}")
            if origem.exists():
                origem.rename(path.with_suffix(path.suffix + f".{geracao + 1}"))
        path.rename(path.with_suffix(path.suffix + ".1"))
    except OSError:
        # Rotacao falhou: continuar anexando e melhor que perder o evento.
        logger.debug("[lifecycle] rotacao falhou em %s", path, exc_info=True)


def _termina_em_quebra(path: Path) -> bool:
    """Se a ultima linha do arquivo esta fechada.

    Um app morto no meio de um `write` deixa linha truncada SEM `\n`. O
    proximo append cola nela e transforma DOIS eventos em uma linha invalida:
    perde-se o truncado (esperado) e tambem o novo (nao esperado). Checar o
    ultimo byte custa um seek e evita corromper evento bom com evento velho.
    """
    try:
        if not path.exists() or path.stat().st_size == 0:
            return True
        with path.open("rb") as handle:
            handle.seek(-1, os.SEEK_END)
            return handle.read(1) == b"\n"
    except OSError:
        return True


def _mascarar(valor: Any) -> Any:
    """Mascara por FORMATO, nunca por nome de chave.

    `loop_id` e `phase` sao texto escolhido por gente: um slug de loop pode
    carregar qualquer coisa que o operador digitou. Mascarar por formato custa
    quase nada e nao depende de acertar a lista de nomes de campo sensiveis.
    """
    if isinstance(valor, str):
        return mask(valor)
    return valor


def record_event(event: dict[str, Any] | None) -> bool:
    """Anexa `event` ao sidecar. Devolve se a linha foi gravada.

    `None` entra e sai como `False` sem ruido: os emissores devolvem `None`
    quando o comando esta fora de loop, e isso e o caminho normal, nao erro.
    """
    if not event:
        return False
    try:
        destino = sink_path()
        if destino is None:
            return False
        registro = {chave: _mascarar(valor) for chave, valor in event.items()}
        registro["pid"] = os.getpid()
        linha = json.dumps(registro, ensure_ascii=False)
        with _lock:
            destino.parent.mkdir(parents=True, exist_ok=True)
            _rotate_if_needed(destino)
            prefixo = "" if _termina_em_quebra(destino) else "\n"
            with destino.open("a", encoding="utf-8") as handle:
                handle.write(prefixo + linha + "\n")
        return True
    except (OSError, TypeError, ValueError):
        # Sidecar indisponivel ou evento nao serializavel nao derruba a fila.
        logger.debug("[lifecycle] escrita do sidecar falhou", exc_info=True)
        return False


def read_events(path: Path | None = None) -> list[dict[str, Any]]:
    """Le um sidecar, pulando linhas corrompidas.

    Linha truncada (app morto no meio de um `write`) e esperada num sidecar
    append-only. Pular a linha preserva as outras; abortar a leitura perderia
    o corpus inteiro por causa do ultimo evento.
    """
    alvo = path or sink_path()
    if alvo is None or not alvo.exists():
        return []
    eventos: list[dict[str, Any]] = []
    try:
        with alvo.open("r", encoding="utf-8") as handle:
            for linha in handle:
                linha = linha.strip()
                if not linha:
                    continue
                try:
                    obj = json.loads(linha)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    eventos.append(obj)
    except OSError:
        return eventos
    return eventos


def _reset_for_tests() -> None:
    """Remove o sidecar desta instancia. Uso exclusivo de teste."""
    destino = sink_path()
    if destino is None:
        return
    try:
        destino.unlink()
    except OSError:
        pass
