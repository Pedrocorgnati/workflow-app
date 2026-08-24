"""`_ROCKSMASH-STATE.json` — autoridade de maquina do progresso do rocksmash.

Por que um sidecar estruturado, e nao `rocksmash-progress.md`
-------------------------------------------------------------

O expander do rocksmash nao tem cursor: reabrir a fila reenfileira todas as
iteracoes e depende de idempotencia de cada subcomando para nao duplicar
efeito. Consertar isso exige uma autoridade que responda, por item E por
subfase, "isto ja foi concluido?".

`rocksmash-progress.md` nao pode ser essa autoridade: e markdown escrito por
LLM durante a execucao, com granularidade de task e sem contrato de parsing.
`metadata.last_rocksmash_*` tambem nao: sao carimbos globais de "a ultima vez
que rodou", que nao distinguem item nem subfase. Os dois continuam existindo
como **projecoes de compatibilidade** — legiveis por humano, uteis em
diagnostico — e nenhum dos dois decide retomada.

Regras de ouro
--------------

1. **Autoridade unica de maquina.** Retomada le este arquivo. Se ele nao
   existir, nao ha estado: a fila e integral, e isso e um fato observado, nao
   uma suposicao de "provavelmente nada rodou".

2. **Vinculado ao `config_hash`.** O estado vale para a config que o gerou.
   `/loop-rocksmash:rename` renumera itens; um estado de antes do rename
   descreveria `002` como um item que hoje e outro. Hash divergente marca o
   estado como **stale**, e stale nunca e consumido em silencio.

3. **Quem executa nao confirma.** O produtor de escrita e o componente que
   confirma a conclusao do item na fila (`actor="queue-confirmer"`); o
   expander e leitor. Um LLM marcando a propria subfase como concluida
   transformaria "eu acho que terminei" em fato persistido — que e exatamente
   o erro que este sidecar existe para impedir.

4. **Lock + troca atomica.** Toda escrita acontece sob `flock` exclusivo em
   `{loop_root}/.rocksmash-state.lock`, com read-modify-write dentro do mesmo
   lock, temp no mesmo diretorio, `fsync` e `os.replace`.

5. **`null` significa "nao observado".** Nunca carimbar `completed_at` com
   "agora" para preencher lacuna: um timestamp inventado e indistinguivel de
   um medido.

Schema: `rocksmash_state.schema.json` (v1.0.0).
Regras: `ai-forge/rules/rocksmash.md` secao 2.4.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

from workflow_app.daily_loop.loader import DailyLoopConfigError

SCHEMA_VERSION = "1.0.0"
STATE_FILENAME = "_ROCKSMASH-STATE.json"
LOCK_FILENAME = ".rocksmash-state.lock"

#: Ordem canonica das subfases. E a mesma do bloco emitido pelo expander;
#: divergencia entre as duas listas e bug de contrato, nao detalhe cosmetico.
SUBPHASES: tuple[str, ...] = ("do", "review-done", "compare", "integrate")
SUBPHASES_LEGACY: tuple[str, ...] = ("do", "review-done")

#: Unico ator autorizado a escrever conclusao. Ver regra de ouro 3.
QUEUE_CONFIRMER = "queue-confirmer"

#: Estados possiveis de uma subfase.
#:
#: `in_flight` existe porque a subfase e marcada ANTES do dispatch: sem ele, um
#: crash entre o efeito e a persistencia seria indistinguivel de "nunca rodou",
#: e a retomada re-executaria trabalho ja aplicado. `unknown` e o que sobra de
#: um `in_flight` cujo processo morreu — nao e "falhou" (pode ter concluido) e
#: nao e "pendente" (pode ter aplicado efeito), entao bloqueia retomada
#: automatica e exige reconciliacao.
SUBPHASE_STATUSES: tuple[str, ...] = (
    "pending",
    "in_flight",
    "completed",
    "failed",
    "unknown",
)

#: Estados que impedem retomada automatica do item. Ver `blocked_subphases`.
BLOCKING_STATUSES: tuple[str, ...] = ("in_flight", "failed", "unknown")


class RocksmashStateError(DailyLoopConfigError):
    """Erro de contrato do sidecar (stale, item/subfase desconhecidos, ator invalido)."""


# ---------------------------------------------------------------------------
# hash da config
# ---------------------------------------------------------------------------


def compute_config_hash(raw_config: dict[str, Any]) -> str:
    """SHA256 do conteudo canonico da config.

    Serializa com `sort_keys=True` e separadores fixos para que reordenacao de
    chaves — que nao muda semantica — nao invalide o estado. Mudanca de
    conteudo (ids, task_paths, buckets) muda o hash, que e exatamente o
    gatilho de stale que se quer.
    """
    blob = json.dumps(raw_config, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# modelo
# ---------------------------------------------------------------------------


@dataclass
class SubphaseState:
    status: str = "pending"
    started_at: float | None = None
    completed_at: float | None = None
    actor: str | None = None
    pid: int | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "actor": self.actor,
            "pid": self.pid,
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: Any) -> "SubphaseState":
        if not isinstance(data, dict):
            return cls()
        status = data.get("status")
        if status not in SUBPHASE_STATUSES:
            # Status desconhecido nao vira `pending`: rebaixar para pendente
            # autorizaria re-executar uma subfase cujo desfecho o arquivo nao
            # sabe descrever. `unknown` e a leitura honesta, e ela bloqueia.
            status = "pending" if status is None else "unknown"
        return cls(
            status=status,
            started_at=(
                data.get("started_at")
                if isinstance(data.get("started_at"), (int, float))
                else None
            ),
            completed_at=(
                data.get("completed_at")
                if isinstance(data.get("completed_at"), (int, float))
                else None
            ),
            actor=data.get("actor") if isinstance(data.get("actor"), str) else None,
            pid=data.get("pid") if isinstance(data.get("pid"), int) else None,
            note=data.get("note") if isinstance(data.get("note"), str) else None,
        )


@dataclass
class ItemState:
    task_path: str | None = None
    subphases: dict[str, SubphaseState] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_path": self.task_path,
            "subphases": {k: v.to_dict() for k, v in self.subphases.items()},
        }


@dataclass
class RocksmashState:
    loop_slug: str
    config_hash: str
    items: dict[str, ItemState] = field(default_factory=dict)
    created_at: float | None = None
    updated_at: float | None = None
    schema_version: str = SCHEMA_VERSION

    # -- consultas ---------------------------------------------------------

    def is_stale_for(self, raw_config: dict[str, Any]) -> bool:
        """True quando o estado descreve outra config (tipicamente pos-rename)."""
        return self.config_hash != compute_config_hash(raw_config)

    def subphase(self, item_id: str, subphase: str) -> SubphaseState:
        item = self.items.get(item_id)
        if item is None:
            raise RocksmashStateError(
                f"item '{item_id}' ausente do _ROCKSMASH-STATE.json. "
                f"Itens conhecidos: {sorted(self.items)}"
            )
        sp = item.subphases.get(subphase)
        if sp is None:
            raise RocksmashStateError(
                f"subfase '{subphase}' desconhecida para o item '{item_id}'. "
                f"Subfases do item: {sorted(item.subphases)}"
            )
        return sp

    def is_completed(self, item_id: str, subphase: str) -> bool:
        return self.subphase(item_id, subphase).status == "completed"

    def ordered_subphases(self, item_id: str) -> list[str]:
        """Subfases do item na ordem de execucao, nunca na ordem do arquivo."""
        subphases = self.items[item_id].subphases
        ordenadas = [n for n in SUBPHASES if n in subphases]
        ordenadas += [n for n in subphases if n not in SUBPHASES]
        return ordenadas

    def blocked_subphases(self) -> list[tuple[str, str, str]]:
        """[(item_id, subphase, status), ...] que impedem retomada automatica.

        `in_flight` entra porque um dispatch ainda vivo nao pode ser
        reenfileirado; `failed` e `unknown` entram porque o desfecho do efeito
        colateral nao esta estabelecido. Nos tres casos a decisao e de
        reconciliacao (`ai-forge/rules/loop-failed-reconciliation.md`), nao do
        cursor.
        """
        out: list[tuple[str, str, str]] = []
        for item_id in sorted(self.items):
            for name in self.ordered_subphases(item_id):
                status = self.items[item_id].subphases[name].status
                if status in BLOCKING_STATUSES:
                    out.append((item_id, name, status))
        return out

    def pending_subphases(self) -> list[tuple[str, str]]:
        """[(item_id, subphase), ...] na ordem canonica, so o que falta.

        `failed` NAO entra: a politica de retry de falha e a mesma do `/loop`
        (`ai-forge/rules/loop-failed-reconciliation.md`) — reabrir exige
        reconciliacao, nao reenfileiramento automatico.
        """
        out: list[tuple[str, str]] = []
        for item_id in sorted(self.items):
            subphases = self.items[item_id].subphases
            # A ordem vem de SUBPHASES, nao das chaves em disco: o JSON e
            # gravado com chaves ordenadas, e alfabetico ("compare" antes de
            # "do") nao e a ordem de execucao. Um cursor que confiasse na
            # ordem do arquivo retomaria pela subfase errada.
            for name in self.ordered_subphases(item_id):
                if subphases[name].status == "pending":
                    out.append((item_id, name))
        return out

    def summary_line(self) -> str:
        total = sum(len(i.subphases) for i in self.items.values())
        done = sum(
            1
            for i in self.items.values()
            for sp in i.subphases.values()
            if sp.status == "completed"
        )
        failed = sum(
            1
            for i in self.items.values()
            for sp in i.subphases.values()
            if sp.status == "failed"
        )
        base = f"{done}/{total} subfases concluidas"
        return f"{base}, {failed} falha(s)" if failed else base

    # -- serializacao ------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "loop_slug": self.loop_slug,
            "config_hash": self.config_hash,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "items": {k: v.to_dict() for k, v in self.items.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RocksmashState":
        if not isinstance(data, dict):
            raise RocksmashStateError("_ROCKSMASH-STATE.json nao e um objeto JSON.")
        version = data.get("schema_version")
        if version != SCHEMA_VERSION:
            raise RocksmashStateError(
                f"_ROCKSMASH-STATE.json com schema_version={version!r}; "
                f"esperado {SCHEMA_VERSION!r}. Regerar via /loop-rocksmash:prepare."
            )
        cfg_hash = data.get("config_hash")
        if not isinstance(cfg_hash, str) or len(cfg_hash) != 64:
            raise RocksmashStateError(
                "_ROCKSMASH-STATE.json sem config_hash valido (sha256 hex de 64 chars). "
                "Sem ele o estado nao pode ser vinculado a uma config."
            )
        items: dict[str, ItemState] = {}
        raw_items = data.get("items")
        if isinstance(raw_items, dict):
            for item_id, raw_item in raw_items.items():
                if not isinstance(raw_item, dict):
                    continue
                raw_sp = raw_item.get("subphases")
                subphases: dict[str, SubphaseState] = {}
                if isinstance(raw_sp, dict):
                    for name, payload in raw_sp.items():
                        subphases[str(name)] = SubphaseState.from_dict(payload)
                items[str(item_id)] = ItemState(
                    task_path=(
                        raw_item.get("task_path")
                        if isinstance(raw_item.get("task_path"), str)
                        else None
                    ),
                    subphases=subphases,
                )
        return cls(
            loop_slug=str(data.get("loop_slug") or ""),
            config_hash=cfg_hash,
            items=items,
            created_at=(
                data.get("created_at")
                if isinstance(data.get("created_at"), (int, float))
                else None
            ),
            updated_at=(
                data.get("updated_at")
                if isinstance(data.get("updated_at"), (int, float))
                else None
            ),
        )


# ---------------------------------------------------------------------------
# io
# ---------------------------------------------------------------------------


def state_path(loop_root: str | os.PathLike[str]) -> Path:
    return Path(loop_root) / STATE_FILENAME


@contextmanager
def _locked(loop_root: Path) -> Iterator[None]:
    """flock exclusivo cooperativo. Read-modify-write vive inteiro aqui dentro."""
    loop_root.mkdir(parents=True, exist_ok=True)
    lock_file = loop_root / LOCK_FILENAME
    fh = open(lock_file, "a+")
    try:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        finally:
            fh.close()


def _write_atomic(target: Path, payload: dict[str, Any]) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(target.parent), prefix=".rsstate-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
            fh.write("\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, target)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def read_state(loop_root: str | os.PathLike[str]) -> RocksmashState | None:
    """Le o sidecar. `None` quando o arquivo nao existe.

    Ausencia e um fato ("nao ha estado registrado"), nao um erro: um loop
    nunca rodado nao tem sidecar, e a fila integral e a resposta correta.
    JSON ilegivel, ao contrario, e erro — silenciar corrupcao aqui devolveria
    "nada foi feito" para um loop que talvez tenha feito tudo.
    """
    path = state_path(loop_root)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RocksmashStateError(
            f"_ROCKSMASH-STATE.json ilegivel em {path}: {exc}. "
            "Corrigir ou remover explicitamente — o expander nao assume 'nada rodou'."
        ) from exc
    return RocksmashState.from_dict(data)


def init_state(
    loop_root: str | os.PathLike[str],
    raw_config: dict[str, Any],
    iteration_items: list[tuple[str, dict[str, Any]]],
    *,
    legacy_two_step: bool = False,
    now: float | None = None,
    overwrite_stale: bool = False,
) -> RocksmashState:
    """Cria (ou devolve) o sidecar para a config atual.

    Se ja existir estado com o mesmo `config_hash`, devolve o existente sem
    tocar em disco — init e idempotente e nunca zera progresso.

    Se existir estado **stale**, levanta, a menos que `overwrite_stale=True`.
    Reinicializar em silencio apagaria o registro do que ja rodou sob a config
    anterior; a decisao de descartar e do operador.
    """
    root = Path(loop_root)
    cfg_hash = compute_config_hash(raw_config)
    subphases = SUBPHASES_LEGACY if legacy_two_step else SUBPHASES

    with _locked(root):
        existing = read_state(root)
        if existing is not None:
            if existing.config_hash == cfg_hash:
                return existing
            if not overwrite_stale:
                raise RocksmashStateError(
                    "_ROCKSMASH-STATE.json descreve outra config (stale): "
                    f"estado={existing.config_hash[:12]}..., atual={cfg_hash[:12]}.... "
                    "A config mudou (tipicamente por /loop-rocksmash:rename) e os item_ids "
                    "podem ter mudado de significado. Reconciliar ou reinicializar "
                    "explicitamente (overwrite_stale=True)."
                )

        state = RocksmashState(
            loop_slug=root.name,
            config_hash=cfg_hash,
            created_at=now,
            updated_at=now,
            items={
                str(item_id): ItemState(
                    task_path=(
                        str(item.get("task_path"))
                        if isinstance(item.get("task_path"), str)
                        else None
                    ),
                    subphases={name: SubphaseState() for name in subphases},
                )
                for item_id, item in iteration_items
            },
        )
        _write_atomic(state_path(root), state.to_dict())
        return state


def mark_subphase(
    loop_root: str | os.PathLike[str],
    raw_config: dict[str, Any],
    item_id: str,
    subphase: str,
    *,
    status: str = "completed",
    actor: str = QUEUE_CONFIRMER,
    note: str | None = None,
    now: float | None = None,
) -> RocksmashState:
    """Registra o desfecho de UMA subfase. Escritor unico: o confirmador da fila.

    Recusa qualquer `actor` diferente de `queue-confirmer`: o componente que
    executa a subfase nao pode ser o que atesta a propria conclusao (regra de
    ouro 3). Recusa tambem estado stale — gravar progresso de `002` em um
    estado onde `002` significa outra task e pior do que nao gravar.
    """
    if status not in SUBPHASE_STATUSES:
        raise RocksmashStateError(
            f"status invalido: {status!r}. Aceitos: {', '.join(SUBPHASE_STATUSES)}."
        )
    if actor != QUEUE_CONFIRMER:
        raise RocksmashStateError(
            f"actor {actor!r} nao pode escrever no _ROCKSMASH-STATE.json. "
            f"Escritor unico: {QUEUE_CONFIRMER!r} (o componente que confirma a "
            "conclusao na fila). Quem executa a subfase nao confirma a si mesmo."
        )

    root = Path(loop_root)
    with _locked(root):
        state = read_state(root)
        if state is None:
            raise RocksmashStateError(
                f"_ROCKSMASH-STATE.json ausente em {root}. "
                "Rode a inicializacao (/loop-rocksmash:prepare) antes de confirmar subfases."
            )
        if state.is_stale_for(raw_config):
            raise RocksmashStateError(
                "_ROCKSMASH-STATE.json stale: descreve outra config. "
                "Reconciliar antes de gravar progresso."
            )
        sp = state.subphase(item_id, subphase)
        sp.status = status
        terminal = status in ("completed", "failed", "unknown")
        sp.completed_at = now if terminal else None
        sp.actor = actor if terminal else None
        sp.pid = None
        sp.note = note
        state.updated_at = now
        _write_atomic(state_path(root), state.to_dict())
        return state


def _pid_alive(pid: int | None) -> bool:
    """`kill -0`: o processo existe?

    Um pid reciclado responde "vivo" para um processo que nao e o nosso dono
    original. Isso e aceito de proposito: o falso positivo faz o cursor
    BLOQUEAR (achando que ainda roda), nunca retomar por cima de trabalho
    alheio. O erro barato e preferivel ao caro.
    """
    if pid is None:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        # Existe, mas de outro usuario. Continua sendo "vivo".
        return True
    return True


def begin_subphase(
    loop_root: str | os.PathLike[str],
    raw_config: dict[str, Any],
    item_id: str,
    subphase: str,
    *,
    actor: str = QUEUE_CONFIRMER,
    pid: int | None = None,
    now: float | None = None,
) -> RocksmashState:
    """Marca a subfase como `in_flight` ANTES do dispatch.

    A assimetria e deliberada: gravar antes do efeito produz falso positivo
    barato (uma subfase marcada como em voo que nunca comecou vira `unknown` e
    pede reconciliacao), enquanto gravar depois produziria falso negativo caro
    (efeito aplicado, arquivo dizendo `pending`, retomada re-executando).

    Recusa iniciar uma subfase que ja esta `in_flight` sob um processo vivo:
    dois dispatches simultaneos da mesma subfase e exatamente o que o cursor
    existe para impedir.
    """
    if actor != QUEUE_CONFIRMER:
        raise RocksmashStateError(
            f"actor {actor!r} nao pode escrever no _ROCKSMASH-STATE.json. "
            f"Escritor unico: {QUEUE_CONFIRMER!r}."
        )
    root = Path(loop_root)
    with _locked(root):
        state = read_state(root)
        if state is None:
            raise RocksmashStateError(
                f"_ROCKSMASH-STATE.json ausente em {root}. "
                "Rode a inicializacao (/loop-rocksmash:prepare) antes de despachar subfases."
            )
        if state.is_stale_for(raw_config):
            raise RocksmashStateError(
                "_ROCKSMASH-STATE.json stale: descreve outra config. "
                "Reconciliar antes de despachar."
            )
        sp = state.subphase(item_id, subphase)
        if sp.status == "in_flight" and _pid_alive(sp.pid):
            raise RocksmashStateError(
                f"subfase {item_id}/{subphase} ja esta in_flight sob o pid {sp.pid} "
                "(processo vivo). Nao ha dispatch concorrente da mesma subfase."
            )
        sp.status = "in_flight"
        sp.started_at = now
        sp.completed_at = None
        sp.actor = actor
        sp.pid = os.getpid() if pid is None else pid
        state.updated_at = now
        _write_atomic(state_path(root), state.to_dict())
        return state


def reopen_state(
    loop_root: str | os.PathLike[str],
    *,
    now: float | None = None,
) -> RocksmashState | None:
    """Reabre o estado convertendo `in_flight` orfao em `unknown`.

    Chamado quando alguem volta a olhar o loop (expansao da fila, retomada).
    Um `in_flight` cujo processo nao existe mais e um dispatch que morreu no
    meio: nao da para afirmar que aplicou efeito nem que nao aplicou. Promover
    a `completed` inventaria conclusao; rebaixar a `pending` autorizaria
    re-execucao. `unknown` diz a verdade e bloqueia.

    `in_flight` com processo vivo e preservado — e uma execucao em andamento,
    nao um orfao.
    """
    root = Path(loop_root)
    with _locked(root):
        state = read_state(root)
        if state is None:
            return None
        mudou = False
        for item_id in sorted(state.items):
            for name, sp in state.items[item_id].subphases.items():
                if sp.status == "in_flight" and not _pid_alive(sp.pid):
                    sp.status = "unknown"
                    sp.note = (
                        f"in_flight orfao (pid {sp.pid} inexistente) promovido a unknown "
                        "na reabertura; exige reconciliacao"
                    )
                    sp.pid = None
                    sp.completed_at = None
                    mudou = True
        if mudou:
            state.updated_at = now
            _write_atomic(state_path(root), state.to_dict())
        return state
