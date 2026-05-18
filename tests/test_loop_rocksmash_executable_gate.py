"""Regression tests for gate RP-EXEC-01 (rocksmash_executable flag).

Gate vive em `.claude/commands/loop-rocksmash/prepare.md` PASSO 4: itens em
buckets nao referenciados pelo `iteration_template` ganham
`rocksmash_executable: false` e ficam fora da fila gerada pelo workflow-app
(`loop_rocksmash_expander.build_loop_rocksmash_specs`).

Cenarios cobertos (mapeados do loop 05-16-loop-rocksmash-prepare-includes-infra-items):

  * test_prepare_md_declares_rp_exec_gate
    A spec `prepare.md` declara o id `RP-EXEC-01`, a regra de gravacao
    (`rocksmash_executable: false` em buckets nao-referenciados) e o filtro
    canonico para consumers (`not it.get('archived') and it.get('rocksmash_executable', True)`).

  * test_consumer_specs_declare_rp_exec_gate
    `do.md`, `review-done.md` e `rename.md` mencionam o gate RP-EXEC-01 como
    defesa em profundidade (skip silencioso para nao desperdicar iteracoes
    opus-high em items filtrados).

  * test_expander_skips_non_executable_items
    `build_loop_rocksmash_specs` NAO enfileira items com
    `rocksmash_executable: False`; items sem o flag (loops legacy) sao
    tratados como executaveis (retro-compat).

  * test_expander_skips_archived_items
    Itens com `archived: True` continuam sendo filtrados (paridade com
    comportamento pre-2026-05-17; gate RP-EXEC-01 nao quebra essa garantia).

  * test_expander_raises_when_all_items_non_executable
    Quando TODOS os items sao nao-executaveis, expander levanta
    `DailyLoopConfigError` mencionando RP-EXEC-01 para guiar o operador.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from workflow_app.command_queue.loop_rocksmash_expander import (
    build_loop_rocksmash_specs,
)
from workflow_app.daily_loop.loader import DailyLoopConfigError


def _repo_root() -> Path:
    cur = Path(__file__).resolve()
    for parent in cur.parents:
        if (parent / ".claude" / "commands" / "loop-rocksmash" / "prepare.md").is_file():
            return parent
    raise RuntimeError(
        f"Could not locate .claude/commands/loop-rocksmash/prepare.md above {cur}"
    )


@pytest.fixture(scope="module")
def prepare_md_text() -> str:
    return (_repo_root() / ".claude" / "commands" / "loop-rocksmash" / "prepare.md").read_text(
        encoding="utf-8"
    )


@pytest.fixture(scope="module")
def do_md_text() -> str:
    return (_repo_root() / ".claude" / "commands" / "loop-rocksmash" / "do.md").read_text(
        encoding="utf-8"
    )


@pytest.fixture(scope="module")
def review_done_md_text() -> str:
    return (_repo_root() / ".claude" / "commands" / "loop-rocksmash" / "review-done.md").read_text(
        encoding="utf-8"
    )


@pytest.fixture(scope="module")
def rename_md_text() -> str:
    return (_repo_root() / ".claude" / "commands" / "loop-rocksmash" / "rename.md").read_text(
        encoding="utf-8"
    )


def test_prepare_md_declares_rp_exec_gate(prepare_md_text: str) -> None:
    assert "RP-EXEC-01" in prepare_md_text, (
        "Gate id 'RP-EXEC-01' ausente de prepare.md — regressao do fix de "
        "2026-05-17. Restaurar gate RP-EXEC-01 no PASSO 4."
    )
    assert "rocksmash_executable" in prepare_md_text, (
        "prepare.md deve declarar a flag 'rocksmash_executable'"
    )
    # Filter pattern canonico que os consumers usam.
    assert (
        "not it.get('archived') and it.get('rocksmash_executable', True)"
        in prepare_md_text
    ), "Filtro canonico ausente do prepare.md (pattern citado para consumers)"
    # Precedente loop deve estar mencionado para audit trail.
    assert "05-16-loop-rocksmash-prepare-includes-infra-items" in prepare_md_text, (
        "prepare.md deve citar loop precedente que motivou o fix"
    )


def test_consumer_specs_declare_rp_exec_gate(
    do_md_text: str, review_done_md_text: str, rename_md_text: str
) -> None:
    for name, text in [
        ("do.md", do_md_text),
        ("review-done.md", review_done_md_text),
        ("rename.md", rename_md_text),
    ]:
        assert "RP-EXEC-01" in text, (
            f"{name} deve referenciar gate RP-EXEC-01 como defesa em profundidade"
        )
        assert "rocksmash_executable" in text, (
            f"{name} deve mencionar a flag 'rocksmash_executable'"
        )


def _config_skeleton(items_v3: list[dict]) -> dict:
    return {
        "kind": "daily-loop",
        "daily_loop": {
            "buckets": [
                {
                    "id": "T-opus-high",
                    "model": "opus",
                    "effort": "high",
                    "items": items_v3,
                }
            ],
        },
    }


def test_expander_skips_non_executable_items(tmp_path: Path) -> None:
    items_dir = tmp_path / "tasks" / "items"
    items_dir.mkdir(parents=True)
    executable_task = items_dir / "task-001-foo.md"
    skipped_task = items_dir / "task-002-bar.md"
    executable_task.write_text("# foo\n\nbody", encoding="utf-8")
    skipped_task.write_text("# bar\n\nbody", encoding="utf-8")

    cfg = _config_skeleton(
        [
            {
                "id": "001",
                "task_path": str(executable_task),
                "kind": "iteration",
                "rocksmash_executable": True,
            },
            {
                "id": "002",
                "task_path": str(skipped_task),
                "kind": "iteration",
                "rocksmash_executable": False,
            },
        ]
    )
    specs = build_loop_rocksmash_specs(cfg, tmp_path)
    rendered = [s.name for s in specs]
    assert any("task-001-foo.md" in n for n in rendered), (
        "item executavel deveria estar enfileirado"
    )
    assert not any("task-002-bar.md" in n for n in rendered), (
        "item com rocksmash_executable=False deveria estar fora da fila"
    )


def test_expander_skips_archived_items(tmp_path: Path) -> None:
    items_dir = tmp_path / "tasks" / "items"
    items_dir.mkdir(parents=True)
    active_task = items_dir / "task-001-foo.md"
    archived_task = items_dir / "task-002.split.md"
    active_task.write_text("# foo\n\nbody", encoding="utf-8")
    archived_task.write_text("# bar (archived)\n\nbody", encoding="utf-8")

    cfg = _config_skeleton(
        [
            {
                "id": "001",
                "task_path": str(active_task),
                "kind": "iteration",
            },
            {
                "id": "002",
                "task_path": str(archived_task),
                "kind": "iteration",
                "archived": True,
            },
        ]
    )
    specs = build_loop_rocksmash_specs(cfg, tmp_path)
    rendered = [s.name for s in specs]
    assert any("task-001-foo.md" in n for n in rendered)
    assert not any("task-002.split.md" in n for n in rendered)


def test_expander_raises_when_all_items_non_executable(tmp_path: Path) -> None:
    items_dir = tmp_path / "tasks" / "items"
    items_dir.mkdir(parents=True)
    skipped = items_dir / "task-001-infra.md"
    skipped.write_text("# infra\n\nbody", encoding="utf-8")

    cfg = _config_skeleton(
        [
            {
                "id": "001",
                "task_path": str(skipped),
                "kind": "iteration",
                "rocksmash_executable": False,
            }
        ]
    )
    with pytest.raises(DailyLoopConfigError) as excinfo:
        build_loop_rocksmash_specs(cfg, tmp_path)
    msg = str(excinfo.value)
    assert "RP-EXEC-01" in msg, (
        f"Mensagem deveria citar RP-EXEC-01 para guiar operador; got: {msg}"
    )


def test_expander_treats_missing_flag_as_executable(tmp_path: Path) -> None:
    """Loops legacy (pre-2026-05-17) sem o flag continuam sendo enfileirados."""
    items_dir = tmp_path / "tasks" / "items"
    items_dir.mkdir(parents=True)
    legacy_task = items_dir / "task-001-legacy.md"
    legacy_task.write_text("# legacy\n\nbody", encoding="utf-8")

    cfg = _config_skeleton(
        [
            {
                "id": "001",
                "task_path": str(legacy_task),
                "kind": "iteration",
                # No rocksmash_executable flag (legacy)
            }
        ]
    )
    specs = build_loop_rocksmash_specs(cfg, tmp_path)
    rendered = [s.name for s in specs]
    assert any("task-001-legacy.md" in n for n in rendered), (
        "item legacy (sem flag) deve ser tratado como executavel (default True)"
    )
