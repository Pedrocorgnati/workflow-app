"""Leitor do manifesto canonico de fases de `/loop` e `/kimi-loop`.

Fonte de verdade: `ai-forge/rules/loop-phase-manifest.json`.

Antes deste modulo, a anatomia da preparacao vivia em seis listas literais
dentro de `command_queue_widget.py` (tres modos x duas lanes), e a prosa das
rules repetia contagens a mao — foi assim que `loop-rules.md` passou a
declarar 5, 6, 7 e 8 fases ao mesmo tempo para a mesma coisa. Aqui existe um
lugar so: o builder renderiza a partir do manifesto e o teste valida o
manifesto contra os snapshots congelados.

Falha e ruidosa de proposito: manifesto ausente, mal formado, lane/modo
desconhecido ou placeholder nao declarado levantam `LoopPhaseManifestError`.
Fila de comando montada por adivinhacao e pior do que fila que nao monta.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

MANIFEST_RELPATH = "ai-forge/rules/loop-phase-manifest.json"

_PLACEHOLDER_RE = re.compile(r"\{[a-z_]+\}")


class LoopPhaseManifestError(RuntimeError):
    """Manifesto ausente, invalido ou consultado fora do contrato."""


def _repo_root() -> Path:
    """Raiz do monorepo a partir deste modulo.

    Caminho nominal: `<repo>/ai-forge/workflow-app/src/workflow_app/command_queue/`
    (6 niveis). Quando o pacote e instalado fora do monorepo, o walk-up procura
    o primeiro ancestral que realmente contem o manifesto, em vez de confiar na
    contagem de niveis.
    """
    here = Path(__file__).resolve()
    nominal = here.parents[5]
    if (nominal / MANIFEST_RELPATH).is_file():
        return nominal
    for parent in here.parents:
        if (parent / MANIFEST_RELPATH).is_file():
            return parent
    return nominal


def manifest_path() -> Path:
    return _repo_root() / MANIFEST_RELPATH


@lru_cache(maxsize=1)
def load_manifest() -> dict[str, Any]:
    path = manifest_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise LoopPhaseManifestError(
            f"manifesto de fases nao encontrado em {path}: {exc}. "
            "A anatomia da fila /loop vem desse arquivo; sem ele o builder "
            "nao adivinha as fases."
        ) from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LoopPhaseManifestError(
            f"manifesto de fases invalido em {path}: {exc}"
        ) from exc
    _validate(data, path)
    return data


def _validate(data: dict[str, Any], path: Path) -> None:
    if not isinstance(data, dict) or "lanes" not in data:
        raise LoopPhaseManifestError(f"{path}: sem bloco 'lanes'.")
    catalog = data.get("phase_catalog", {})
    if not isinstance(catalog, dict):
        raise LoopPhaseManifestError(f"{path}: 'phase_catalog' deve ser objeto.")
    conhecidos = {"{mode_flag}", "{path}", "{slug}"}
    for lane_id, lane in data["lanes"].items():
        prefix = lane.get("command_prefix")
        if not isinstance(prefix, str) or not prefix.startswith("/"):
            raise LoopPhaseManifestError(
                f"{path}: lane '{lane_id}' sem 'command_prefix' valido."
            )
        modes = lane.get("modes")
        if not isinstance(modes, dict) or not modes:
            raise LoopPhaseManifestError(
                f"{path}: lane '{lane_id}' sem 'modes'."
            )
        for mode, fases in modes.items():
            if not isinstance(fases, list) or not fases:
                raise LoopPhaseManifestError(
                    f"{path}: lane '{lane_id}' modo '{mode}' sem fases."
                )
            for pos, entry in enumerate(fases, start=1):
                fase = entry.get("phase") if isinstance(entry, dict) else None
                args = entry.get("args", "") if isinstance(entry, dict) else None
                if not fase or args is None:
                    raise LoopPhaseManifestError(
                        f"{path}: lane '{lane_id}' modo '{mode}' posicao {pos} "
                        "sem 'phase'/'args'."
                    )
                if fase not in catalog:
                    raise LoopPhaseManifestError(
                        f"{path}: fase '{fase}' ({lane_id} {mode}) ausente do "
                        "phase_catalog. Toda fase enfileirada precisa declarar "
                        "requires/produces."
                    )
                desconhecidos = set(_PLACEHOLDER_RE.findall(args)) - conhecidos
                if desconhecidos:
                    raise LoopPhaseManifestError(
                        f"{path}: lane '{lane_id}' modo '{mode}' fase '{fase}' "
                        f"usa placeholder nao declarado: {sorted(desconhecidos)}"
                    )


def lanes() -> list[str]:
    return sorted(load_manifest()["lanes"])


def modes(lane: str) -> list[str]:
    return sorted(_lane(lane)["modes"])


def _lane(lane: str) -> dict[str, Any]:
    data = load_manifest()
    try:
        return data["lanes"][lane]
    except KeyError:
        raise LoopPhaseManifestError(
            f"lane desconhecida '{lane}'; disponiveis: {sorted(data['lanes'])}"
        ) from None


def phases(lane: str, mode: str) -> list[dict[str, Any]]:
    lane_data = _lane(lane)
    try:
        return lane_data["modes"][mode]
    except KeyError:
        raise LoopPhaseManifestError(
            f"modo desconhecido '{mode}' na lane '{lane}'; "
            f"disponiveis: {sorted(lane_data['modes'])}"
        ) from None


def phase_count(lane: str, mode: str) -> int:
    return len(phases(lane, mode))


def build_sub_names(lane: str, mode: str, *, path_arg: str, slug: str) -> list[str]:
    """Renderiza a lista ordenada de comandos de preparacao.

    Substitui exatamente as seis listas literais que existiam no widget. A
    saida e byte-a-byte igual a delas — e os snapshots da linha de base sao
    quem prova isso.
    """
    prefix = _lane(lane)["command_prefix"]
    nomes: list[str] = []
    for entry in phases(lane, mode):
        args = (
            entry["args"]
            .replace("{mode_flag}", mode)
            .replace("{path}", path_arg)
            .replace("{slug}", slug)
        )
        nome = f"{prefix}:{entry['phase']}"
        nomes.append(f"{nome} {args}".rstrip() if args else nome)
    return nomes
