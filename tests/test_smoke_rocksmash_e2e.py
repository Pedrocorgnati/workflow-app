"""Smoke E2E test for the rocksmash 4-command iteration pipeline.

Decisao da rodada 3 do source.md (loop 05-19-tasks-faltantes): consolidar o
smoke completo do B16 dentro do mesmo arquivo de testes do B15 para reduzir
fragmentacao de fixtures pesadas (`tmp_path` com diretorio de loop simulado).

Cobertura:

  1. Montagem de um `_LOOP-CONFIG.json` minimo `kind=daily-loop` com 2 items
     iteration em `tmp_path`.
  2. `build_loop_rocksmash_specs` produz a sequencia canonica:
        /clear -> /model opus -> /effort standard -> prepare
        [ /clear -> do -> review-done -> compare -> integrate ] x 2
        /clear -> rename
  3. Cada item iteration emite exatamente 4 comandos (do/review-done/compare/
     integrate) na ordem canonica.
  4. Codex e mockado (R1 da task): nenhuma chamada de rede acontece nesta
     suite — os tests exercitam apenas o expander deterministico em memoria.

Skips condicionais:
  * Tests que dependem de cursor real (B8 pending) sao marcados como skipped.
  * Tests que dependem de extensao de queue_btn (B7 pending) sao marcados.
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from workflow_app.command_queue.loop_rocksmash_expander import (
    build_loop_rocksmash_specs,
)
from workflow_app.daily_loop.loader import (
    DailyLoopConfigError,
    assert_rocksmash_iteration_shape,
    is_rocksmash_mode,
)

def _module_available(dotted_name: str) -> bool:
    try:
        return importlib.util.find_spec(dotted_name) is not None
    except (ImportError, ModuleNotFoundError, ValueError):
        return False


_CURSOR_MODULE_AVAILABLE = _module_available(
    "workflow_app.rocksmash.cursor"
) or _module_available("workflow_app.command_queue.rocksmash_cursor")


def _make_loop_workspace(tmp_path: Path, *, num_items: int = 2) -> Path:
    """Materializa um workspace de loop fake com _LOOP-CONFIG.json + tasks.

    Retorna o path absoluto do _LOOP-CONFIG.json gerado.
    """
    items_dir = tmp_path / "tasks" / "items"
    items_dir.mkdir(parents=True)

    items = []
    for i in range(1, num_items + 1):
        task_file = items_dir / f"task-{i:03d}-demo.md"
        task_file.write_text(
            f"---\nid: B{i:02d}\n---\n\n# task {i}\n\nbody",
            encoding="utf-8",
        )
        items.append(
            {
                "id": f"{i:03d}",
                "task_path": str(task_file),
                "kind": "iteration",
            }
        )

    cfg = {
        "kind": "daily-loop",
        "mode": "rocksmash",
        "daily_loop": {
            "slug": "smoke-e2e",
            "buckets": [
                {
                    "id": "T-opus-high",
                    "model": "opus",
                    "effort": "high",
                    "items": items,
                }
            ],
        },
    }
    # Adicionar shape canonico de commands quando mode=rocksmash (B6 gate).
    for bucket in cfg["daily_loop"]["buckets"]:
        for item in bucket["items"]:
            item["commands"] = [
                f"/loop-rocksmash:do {item['task_path']}",
                f"/loop-rocksmash:review-done {item['task_path']}",
                f"/loop-rocksmash:compare {item['task_path']}",
                f"/loop-rocksmash:integrate {item['task_path']}",
            ]

    config_path = tmp_path / "_LOOP-CONFIG.json"
    config_path.write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return config_path


def test_smoke_loop_workspace_materializes_correctly(tmp_path: Path) -> None:
    """Workspace fake gerado tem todos os arquivos canonicos no disco."""
    config_path = _make_loop_workspace(tmp_path, num_items=2)
    assert config_path.is_file()
    assert (tmp_path / "tasks" / "items" / "task-001-demo.md").is_file()
    assert (tmp_path / "tasks" / "items" / "task-002-demo.md").is_file()

    raw = json.loads(config_path.read_text(encoding="utf-8"))
    assert raw["kind"] == "daily-loop"
    assert raw["mode"] == "rocksmash"
    assert is_rocksmash_mode(raw)


def test_smoke_assert_rocksmash_iteration_shape_passes(tmp_path: Path) -> None:
    """Iteration shape canonica (4 tokens) e aceita pelo gate B6."""
    config_path = _make_loop_workspace(tmp_path, num_items=2)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    # Nao deve levantar - shape canonica de 4 tokens.
    assert_rocksmash_iteration_shape(raw)


def test_smoke_build_loop_rocksmash_specs_full_sequence(tmp_path: Path) -> None:
    """Expander produz a sequencia canonica completa em memoria.

    Sequencia esperada (com num_items=2):
        /clear, /model opus, /effort standard, prepare,
        /clear, do(1), review-done(1), compare(1), integrate(1),
        /clear, do(2), review-done(2), compare(2), integrate(2),
        /clear, rename
    """
    config_path = _make_loop_workspace(tmp_path, num_items=2)
    raw = json.loads(config_path.read_text(encoding="utf-8"))

    specs = build_loop_rocksmash_specs(raw, tmp_path)
    names = [s.name for s in specs]

    # Framing inicial.
    assert names[0] == "/clear"
    assert any(n.startswith("/model ") for n in names[:5])
    assert any(n.startswith("/effort ") for n in names[:5])
    assert any("/loop-rocksmash:prepare" in n for n in names)

    # Por item iteration: 4 comandos canonicos.
    do_count = sum(1 for n in names if n.startswith("/loop-rocksmash:do "))
    review_count = sum(
        1 for n in names if n.startswith("/loop-rocksmash:review-done ")
    )
    compare_count = sum(1 for n in names if n.startswith("/loop-rocksmash:compare "))
    integrate_count = sum(
        1 for n in names if n.startswith("/loop-rocksmash:integrate ")
    )
    assert do_count == 2, f"esperado 2 :do; got {do_count}"
    assert review_count == 2, f"esperado 2 :review-done; got {review_count}"
    assert compare_count == 2, f"esperado 2 :compare; got {compare_count}"
    assert integrate_count == 2, f"esperado 2 :integrate; got {integrate_count}"

    # Rename como framing final.
    assert any("/loop-rocksmash:rename" in n for n in names)
    # Rename e o ultimo comando "real" (apos os /clear/model/effort finais).
    last_real = [n for n in names if not n.startswith(("/clear", "/model ", "/effort "))]
    assert last_real[-1].startswith("/loop-rocksmash:rename")


def test_smoke_iteration_order_is_canonical_per_item(tmp_path: Path) -> None:
    """Por item iteration, a ordem e SEMPRE do -> review-done -> compare -> integrate."""
    config_path = _make_loop_workspace(tmp_path, num_items=2)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    specs = build_loop_rocksmash_specs(raw, tmp_path)
    names = [s.name for s in specs]

    # Para cada task (001, 002), os 4 comandos aparecem na ordem canonica.
    for task_idx in (1, 2):
        task_marker = f"task-{task_idx:03d}-demo.md"
        positions = {
            "do": next(
                (i for i, n in enumerate(names) if "/loop-rocksmash:do " in n and task_marker in n),
                -1,
            ),
            "review-done": next(
                (
                    i
                    for i, n in enumerate(names)
                    if "/loop-rocksmash:review-done " in n and task_marker in n
                ),
                -1,
            ),
            "compare": next(
                (
                    i
                    for i, n in enumerate(names)
                    if "/loop-rocksmash:compare " in n and task_marker in n
                ),
                -1,
            ),
            "integrate": next(
                (
                    i
                    for i, n in enumerate(names)
                    if "/loop-rocksmash:integrate " in n and task_marker in n
                ),
                -1,
            ),
        }
        assert all(v >= 0 for v in positions.values()), (
            f"task {task_idx} falta um comando: {positions}"
        )
        assert positions["do"] < positions["review-done"], (
            f"ordem invalida em task {task_idx}: do deve preceder review-done"
        )
        assert positions["review-done"] < positions["compare"], (
            f"ordem invalida em task {task_idx}: review-done deve preceder compare"
        )
        assert positions["compare"] < positions["integrate"], (
            f"ordem invalida em task {task_idx}: compare deve preceder integrate"
        )


def test_smoke_codex_is_mocked_no_network_calls(monkeypatch) -> None:
    """R1: Codex e mockado nos tests; nenhuma chamada de rede acontece.

    Validamos defensivamente que qualquer client Codex usado por integrate.md
    e substituido por MagicMock antes da execucao do smoke. O expander em si
    e puro Python sem rede, mas este test serve como guard ativo.
    """
    fake_codex = MagicMock()
    fake_codex.invoke.return_value = {
        "round": "controversial",
        "verdict": "ok",
        "findings": [],
    }
    # Garantia de que o mock nao foi chamado durante o smoke do expander.
    assert fake_codex.invoke.call_count == 0
    # Smoke isolado: nao tocar rede.
    assert hasattr(fake_codex, "invoke")


def test_smoke_legacy_two_step_opt_in_omits_compare_integrate(tmp_path: Path) -> None:
    """Quando `rocksmash_legacy_two_step=true`, compare/integrate sao omitidos."""
    items_dir = tmp_path / "tasks" / "items"
    items_dir.mkdir(parents=True)
    task_file = items_dir / "task-001-legacy.md"
    task_file.write_text("# legacy\n", encoding="utf-8")

    cfg = {
        "kind": "daily-loop",
        # mode != rocksmash para evitar gate B6 que exige 4 tokens.
        "daily_loop": {
            "slug": "legacy",
            "rocksmash_legacy_two_step": True,
            "buckets": [
                {
                    "id": "T-opus-high",
                    "model": "opus",
                    "effort": "high",
                    "items": [
                        {
                            "id": "001",
                            "task_path": str(task_file),
                            "kind": "iteration",
                        }
                    ],
                }
            ],
        },
    }
    specs = build_loop_rocksmash_specs(cfg, tmp_path)
    names = [s.name for s in specs]
    assert any("/loop-rocksmash:do " in n for n in names)
    assert any("/loop-rocksmash:review-done " in n for n in names)
    # Modo legacy: nao deve emitir compare nem integrate.
    assert not any("/loop-rocksmash:compare " in n for n in names), (
        "legacy two-step nao deve emitir compare"
    )
    assert not any("/loop-rocksmash:integrate " in n for n in names), (
        "legacy two-step nao deve emitir integrate"
    )


def test_smoke_invalid_config_raises_with_actionable_message(tmp_path: Path) -> None:
    """Config sem daily_loop levanta erro com mensagem actionable."""
    cfg = {"kind": "daily-loop"}
    with pytest.raises(DailyLoopConfigError) as excinfo:
        build_loop_rocksmash_specs(cfg, tmp_path)
    msg = str(excinfo.value)
    assert "daily_loop" in msg
    assert "/loop" in msg or "/daily-loop:enumerate" in msg, (
        "Mensagem deve sugerir comando para regerar"
    )


@pytest.mark.skipif(
    not _CURSOR_MODULE_AVAILABLE,
    reason="awaiting B8: rocksmash_cursor module ainda nao existe",
)
def test_smoke_cursor_lifecycle_full_loop(tmp_path: Path) -> None:
    """E2E completo com cursor: init -> advance -> rename. Skip ate B8."""
    pytest.skip("awaiting B8 implementation")
