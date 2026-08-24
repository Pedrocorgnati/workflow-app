"""Linha de base da anatomia da fila do /loop, congelada ANTES de refatorar.

Fonte: Task 06 do estudo 08-24 (10.3 P0-C, 11.1, 12.2.6, 12.2.7).

Por que snapshot e nao assert pontual: a Task 07 vai trocar listas literais por
um manifesto. Sem uma linha de base byte-a-byte, qualquer reordenacao ou fase
perdida na refatoracao passa despercebida. Estes snapshots existem para provar
que a refatoracao NAO muda a fila.

Regenerar (so quando a mudanca de fila for INTENCIONAL e revisada):

    UPDATE_LOOP_ANATOMY_SNAPSHOTS=1 pytest tests/test_loop_anatomy_snapshots.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
from workflow_app.command_queue.loop_rocksmash_expander import (
    build_loop_rocksmash_specs,
)
from workflow_app.signal_bus import signal_bus

SNAPSHOTS = Path(__file__).parent / "snapshots" / "loop_anatomy"
SLUG = "08-24-fixture-anatomy"


def _is_directive(name: str) -> bool:
    return name == "/clear" or name.startswith(("/model ", "/effort "))


def _serialize(specs) -> dict:
    rows = [
        {
            "position": s.position,
            "name": s.name,
            "model": getattr(s.model, "value", str(s.model)),
            "effort": getattr(s.effort, "value", None) if s.effort else None,
            "interaction_type": getattr(
                s.interaction_type, "value", str(s.interaction_type)
            ),
        }
        for s in specs
    ]
    phases = [r["name"] for r in rows if not _is_directive(r["name"])]
    return {
        "total_specs": len(rows),
        "phase_count": len(phases),
        "phases": phases,
        "specs": rows,
    }


def _assert_snapshot(name: str, payload: dict) -> dict:
    path = SNAPSHOTS / f"{name}.json"
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if os.environ.get("UPDATE_LOOP_ANATOMY_SNAPSHOTS") == "1":
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")
        return payload
    assert path.is_file(), (
        f"snapshot ausente: {path}. Gere com "
        "UPDATE_LOOP_ANATOMY_SNAPSHOTS=1 e revise o diff antes de commitar."
    )
    esperado = json.loads(path.read_text(encoding="utf-8"))
    assert payload == esperado, (
        f"anatomia da fila mudou em '{name}'. Se a mudanca e intencional, "
        "regenere o snapshot e explique a mudanca no commit."
    )
    return payload


def _capture(widget, command_line: str):
    captured = []

    def _handler(specs):
        captured.append(specs)

    signal_bus.pipeline_ready.connect(_handler)
    try:
        with patch.object(widget, "_canonical_loop_slug", return_value=SLUG), patch.object(
            widget, "_existing_loop_slug_from_path", return_value=None
        ):
            widget._on_loop_command_ready(command_line)
    finally:
        signal_bus.pipeline_ready.disconnect(_handler)
    assert captured, f"pipeline_ready nao emitiu specs para {command_line!r}"
    return captured[-1]


# --------------------------------------------------------------------------
# 12.2.6 — contagem real vigente: 8 fases em task, 7 em cmd, 10 em both.
#
# Mudou na Task 27 do estudo 08-24: `/loop:feature-design` entrou depois de
# `review` e antes de `integrated-architecture` em --task e --both. Fica FORA
# de --cmd (que cria slash-commands, nao feature de produto), por isso --cmd
# permanece em 7. A fonte da anatomia continua sendo
# ai-forge/rules/loop-phase-manifest.json; estes numeros sao a trava.
# --------------------------------------------------------------------------

CONTAGEM_VIGENTE = {"--task": 8, "--cmd": 7, "--both": 10}


@pytest.mark.parametrize("mode, esperado", sorted(CONTAGEM_VIGENTE.items()))
def test_snapshot_modo_prep(qapp, mode: str, esperado: int):
    widget = CommandQueueWidget()
    try:
        specs = _capture(widget, f"/loop {mode} source.md")
        payload = _serialize(specs)
        assert payload["phase_count"] == esperado, (
            f"{mode} deveria ter {esperado} fases; got {payload['phase_count']}: "
            f"{payload['phases']}"
        )
        _assert_snapshot(f"prep{mode.replace('--', '_')}", payload)
    finally:
        widget.deleteLater()


def test_prep_nao_injeta_review_done_no_caminho_canonico(qapp):
    """12.2.7 — o caminho canonico normal NAO injeta `review_done_command`.

    A injecao existe apenas no fallback legado (config sem `commands` por item),
    coberto por `test_daily_loop_loader.py`. Se ela vazar para a preparacao, a
    fila ganha uma fase fantasma que ninguem declarou.
    """
    widget = CommandQueueWidget()
    try:
        for mode in CONTAGEM_VIGENTE:
            names = [s.name for s in _capture(widget, f"/loop {mode} source.md")]
            assert not any("review-done" in n for n in names), (
                f"{mode} injetou review-done no caminho canonico: {names}"
            )
            assert not any("review_done" in n for n in names)
    finally:
        widget.deleteLater()


# --------------------------------------------------------------------------
# 12.2.6 — variantes cmd-single create/update, com e sem mcp-flags
# --------------------------------------------------------------------------


def _cmd_single_case(
    qapp, tmp_path: Path, *, action: str, mcp_flags: bool
) -> dict:
    """Monta um workspace minimo e captura a sub-pipeline --cmd-single.

    `action` sai de disco: `/cmd:update` quando o comando alvo ja existe,
    `/cmd:create` quando nao. `mcp_flags` controla a existencia de
    `.claude/commands/auto-improove/mcp-flags.md`, que e o gate do ultimo passo.
    """
    base = tmp_path / f"{action}-{'mcp' if mcp_flags else 'nomcp'}"
    (base / ".claude" / "commands" / "loop").mkdir(parents=True)
    if mcp_flags:
        (base / ".claude" / "commands" / "auto-improove").mkdir(parents=True)
        (base / ".claude" / "commands" / "auto-improove" / "mcp-flags.md").write_text(
            "# /auto-improove:mcp-flags\n", encoding="utf-8"
        )
    if action == "update":
        (base / ".claude" / "commands" / "loop" / "alvo.md").write_text(
            "# /loop:alvo\n", encoding="utf-8"
        )
    source = base / "source-cmd.md"
    source.write_text(
        "---\ncmd_target: /loop:alvo\n---\n\n# /loop:alvo\n\nDescricao minima.\n",
        encoding="utf-8",
    )

    widget = CommandQueueWidget()
    try:
        # app_state sem projeto carregado: o widget cai na descoberta por
        # walk-up ate o primeiro ancestral com `.claude/`, que aqui e `base`.
        # Sem isso o teste mediria o repo real, nao o workspace da fixture.
        with patch.object(
            widget, "_resolve_relative_md", return_value=source
        ), patch(
            "workflow_app.config.app_state.app_state"
        ) as fake_state:
            fake_state.has_config = False
            fake_state.config = None
            specs = _capture(widget, f"/loop --cmd-single {source}")
        payload = _serialize(specs)
    finally:
        widget.deleteLater()

    # o path absoluto do tmp_path muda a cada execucao: normalizar antes de
    # congelar, senao o snapshot nunca bate duas vezes.
    def _scrub(text: str) -> str:
        return text.replace(str(source), "{SOURCE_MD}").replace(str(base), "{BASE}")

    payload["phases"] = [_scrub(p) for p in payload["phases"]]
    for row in payload["specs"]:
        row["name"] = _scrub(row["name"])
    return payload


@pytest.mark.parametrize("action", ["create", "update"])
@pytest.mark.parametrize("mcp_flags", [True, False], ids=["com-mcp", "sem-mcp"])
def test_snapshot_cmd_single(qapp, tmp_path, action: str, mcp_flags: bool):
    payload = _cmd_single_case(qapp, tmp_path, action=action, mcp_flags=mcp_flags)
    esperado_cmd = f"/cmd:{action} "
    assert any(p.startswith(esperado_cmd) for p in payload["phases"]), payload["phases"]
    tem_mcp = any("auto-improove:mcp-flags" in p for p in payload["phases"])
    assert tem_mcp is mcp_flags, (
        "passo mcp-flags deve existir se e somente se o comando existe em disco"
    )
    sufixo = "com_mcp_flags" if mcp_flags else "sem_mcp_flags"
    _assert_snapshot(f"cmd_single_{action}_{sufixo}", payload)


# --------------------------------------------------------------------------
# rocksmash — quadrupla por item de iteracao (nao par)
# --------------------------------------------------------------------------


def _rocksmash_config(n_itens: int) -> dict:
    """Config rocksmash canonica minima (shape B6: 4 comandos por iteracao).

    Construida aqui, e nao lida de `tests/fixtures/loop/`, porque a fixture
    `rocksmash-execucao-parcial.json` congela de proposito o shape legado de
    1 comando por item — util para testar o validador, inutil para medir a
    fila que o expander produz no caminho canonico.
    """
    verbos = ("do", "review-done", "compare", "integrate")
    itens = []
    for i in range(1, n_itens + 1):
        iid = f"{i:03d}"
        task_path = f"tasks/items/task-{iid}.md"
        itens.append(
            {
                "id": iid,
                "kind": "iteration",
                "state": "not_started",
                "task_path": task_path,
                "target": task_path,
                "commands": [
                    f"/loop-rocksmash:{v} --task {task_path}" for v in verbos
                ],
            }
        )
    return {
        "schema_version": "3.0.0",
        "name": "anatomy-rocksmash",
        "project": "fixture",
        "kind": "daily-loop",
        "mode": "rocksmash",
        "daily_loop": {
            "version": "3.0.0",
            "slug": "anatomy-rocksmash",
            "loop_root": "anatomy-rocksmash",
            "progress_path": "PROGRESS.md",
            "tasks_dir": "tasks",
            "log_path": "_LOOP-LOG.md",
            "total_items": n_itens,
            "clear_between_items": True,
            "do_command": "/loop:noop-fallback",
            "buckets": [
                {
                    "id": "T-opus-high",
                    "model": "opus",
                    "effort": "high",
                    "task_file": "tasks/T-opus-high.md",
                    "items": itens,
                }
            ],
            "items_index": {it["id"]: dict(it) for it in itens},
        },
    }


def test_snapshot_rocksmash_quadrupla(qapp, tmp_path):
    """A iteracao rocksmash e QUADRUPLA, nao par.

    `_on_rocksmash_clicked` ainda documenta "N pares do + review-done"; o
    expander emite do/review-done/compare/integrate. Este snapshot congela o
    comportamento real para que a Task 08 corrija a documentacao sem risco de
    "corrigir" o codigo para o texto errado.
    """
    n_itens = 3
    raw = _rocksmash_config(n_itens)
    loop_root = tmp_path / "rocksmash-loop"
    (loop_root / "tasks" / "items").mkdir(parents=True)
    for item in raw["daily_loop"]["buckets"][0]["items"]:
        (loop_root / item["task_path"]).write_text(
            f"# task {item['id']}\n", encoding="utf-8"
        )
    (loop_root / "_LOOP-CONFIG.json").write_text(
        json.dumps(raw, ensure_ascii=False), encoding="utf-8"
    )

    specs = build_loop_rocksmash_specs(raw, loop_root)
    payload = _serialize(specs)
    payload["phases"] = [
        p.replace(str(loop_root), "{LOOP_ROOT}") for p in payload["phases"]
    ]
    for row in payload["specs"]:
        row["name"] = row["name"].replace(str(loop_root), "{LOOP_ROOT}")

    verbos = ["do", "review-done", "compare", "integrate"]
    contagens = {
        v: sum(1 for p in payload["phases"] if p.startswith(f"/loop-rocksmash:{v} "))
        for v in verbos
    }
    assert contagens == {v: n_itens for v in verbos}, (
        "rocksmash e QUADRUPLA por item (do/review-done/compare/integrate), "
        f"nao par: {contagens}"
    )
    assert payload["phases"][0].startswith("/loop-rocksmash:prepare")
    assert payload["phases"][-1].startswith("/loop-rocksmash:rename")
    _assert_snapshot("rocksmash_quadrupla", payload)
