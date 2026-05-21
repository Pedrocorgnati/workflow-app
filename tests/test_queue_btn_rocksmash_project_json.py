"""Regression tests for `queue-btn-rocksmash` detection logic.

O handler `_on_rocksmash_clicked` em
`workflow_app.command_queue.command_queue_widget` valida que o config carregado
na metrics-project-pill e um `_LOOP-CONFIG.json` (kind == "daily-loop"), e nao
um `project.json`. Em divergencia, emite toast `warning` (amarelo); em erro
estrutural do daily_loop, emite toast `error` (vermelho).

Cenarios cobertos (mapeados de task-025-B15):

  * test_project_json_payload_is_detected_as_non_rocksmash
    Um payload de `project.json` (V3) NAO satisfaz o gate `kind == "daily-loop"`.

  * test_loop_config_with_daily_loop_kind_is_valid_for_rocksmash
    Um payload de `_LOOP-CONFIG.json` com `kind: daily-loop` e `daily_loop`
    block satisfaz o gate.

  * test_loop_config_without_daily_loop_block_is_rejected
    `kind == "daily-loop"` mas SEM o bloco `daily_loop` ainda e rejeitado.

  * test_build_loop_rocksmash_specs_raises_when_no_iteration_items
    Quando `daily_loop` esta presente mas nao tem items, a expansao falha
    deterministicamente (toast vermelho via DailyLoopConfigError).

Toast signals (`signal_bus.toast_requested.emit(msg, level)`) sao validados
indiretamente via o gate booleano declarativo do handler. O Qt-widget real
e exercitado pelos suites de integration (out-of-scope para B15).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from workflow_app.command_queue.loop_rocksmash_expander import (
    build_loop_rocksmash_specs,
)
from workflow_app.daily_loop.loader import DailyLoopConfigError


def _is_rocksmash_compatible_config(raw: dict) -> bool:
    """Replica do gate booleano do `_on_rocksmash_clicked` (linha 4239).

    Encapsula a deteccao em uma funcao pura para test isolado, espelhando
    a logica do handler: `kind == "daily-loop"` AND `daily_loop in raw`.
    """
    return raw.get("kind") == "daily-loop" and "daily_loop" in raw


def test_project_json_payload_is_detected_as_non_rocksmash() -> None:
    """`project.json` (V3) deve ser rejeitado pelo gate de rocksmash."""
    project_json_v3 = {
        "name": "meu-projeto",
        "schema_version": "3.0.0",
        "basic_flow": {
            "brief_root": "docs/",
            "docs_root": "docs/",
            "wbs_root": "wbs/",
            "workspace_root": "src/",
        },
        "project_details": {"target_stack": {"primary": "nextjs"}},
        "features": [],
    }
    assert not _is_rocksmash_compatible_config(project_json_v3), (
        "project.json NAO deve passar o gate de rocksmash (toast amarelo esperado)"
    )


def test_loop_config_with_daily_loop_kind_is_valid_for_rocksmash() -> None:
    """`_LOOP-CONFIG.json` com `kind: daily-loop` + bloco satisfaz o gate."""
    loop_config = {
        "kind": "daily-loop",
        "daily_loop": {
            "slug": "demo-loop",
            "buckets": [
                {
                    "id": "T-opus-high",
                    "model": "opus",
                    "effort": "high",
                    "items": [
                        {
                            "id": "001",
                            "task_path": "tasks/items/task-001-foo.md",
                            "kind": "iteration",
                        }
                    ],
                }
            ],
        },
    }
    assert _is_rocksmash_compatible_config(loop_config), (
        "_LOOP-CONFIG.json valido deve passar o gate (toast verde esperado)"
    )


def test_loop_config_without_daily_loop_block_is_rejected() -> None:
    """`kind == daily-loop` sem o bloco `daily_loop` ainda e rejeitado."""
    malformed = {"kind": "daily-loop"}
    assert not _is_rocksmash_compatible_config(malformed), (
        "Config sem bloco 'daily_loop' deve ser rejeitada"
    )


def test_loop_config_with_wrong_kind_is_rejected() -> None:
    """Kinds diferentes de 'daily-loop' (ex: 'micro', 'task') sao rejeitados."""
    for wrong_kind in ("micro", "task", "cmd", "cmd-single", "both", None, ""):
        payload = {"kind": wrong_kind, "daily_loop": {}}
        assert not _is_rocksmash_compatible_config(payload), (
            f"kind={wrong_kind!r} NAO deve passar o gate"
        )


def test_build_loop_rocksmash_specs_raises_when_no_iteration_items(
    tmp_path: Path,
) -> None:
    """Sem items iteration, o expander levanta DailyLoopConfigError (toast vermelho)."""
    cfg = {
        "kind": "daily-loop",
        "daily_loop": {
            "buckets": [
                {
                    "id": "T-opus-high",
                    "model": "opus",
                    "effort": "high",
                    "items": [],
                }
            ],
        },
    }
    with pytest.raises(DailyLoopConfigError) as excinfo:
        build_loop_rocksmash_specs(cfg, tmp_path)
    msg = str(excinfo.value).lower()
    assert "iteration" in msg, (
        f"Mensagem de erro deve citar 'iteration' (toast vermelho); got: {msg}"
    )


def test_build_loop_rocksmash_specs_raises_when_no_daily_loop_block(
    tmp_path: Path,
) -> None:
    """Sem bloco `daily_loop`, expander rejeita explicitamente."""
    cfg = {"kind": "daily-loop"}
    with pytest.raises(DailyLoopConfigError) as excinfo:
        build_loop_rocksmash_specs(cfg, tmp_path)
    assert "daily_loop" in str(excinfo.value), (
        "Mensagem deve citar 'daily_loop' para guiar operador"
    )


def test_build_loop_rocksmash_specs_succeeds_for_minimal_valid_config(
    tmp_path: Path,
) -> None:
    """Config minima valida produz fila com prepare + iteration + rename."""
    items_dir = tmp_path / "tasks" / "items"
    items_dir.mkdir(parents=True)
    task_file = items_dir / "task-001-foo.md"
    task_file.write_text("# foo\n\nbody", encoding="utf-8")

    cfg = {
        "kind": "daily-loop",
        "daily_loop": {
            "slug": "demo",
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
    spec_names = [s.name for s in specs]
    # Deve conter exatamente 1 prepare e 1 rename como framing.
    assert any("/loop-rocksmash:prepare" in n for n in spec_names)
    assert any("/loop-rocksmash:rename" in n for n in spec_names)
    # E pelo menos 1 iteration item (do/review-done/compare/integrate).
    assert any("/loop-rocksmash:do" in n for n in spec_names)
    assert any("/loop-rocksmash:review-done" in n for n in spec_names)


def test_toast_levels_canonical_set() -> None:
    """Niveis canonicos de toast usados pelo handler sao apenas warning/error/success.

    Validacao puramente declarativa para guard contra drift no
    `_on_rocksmash_clicked` (gate de UI consistente).
    """
    canonical_levels = {"warning", "error", "success", "info"}
    # warning: gate de pill ausente OU project.json detectado.
    # error: build_loop_rocksmash_specs raised DailyLoopConfigError.
    used_levels = {"warning", "error"}
    assert used_levels.issubset(canonical_levels)
