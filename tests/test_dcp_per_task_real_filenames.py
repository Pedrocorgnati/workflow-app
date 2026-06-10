"""Regression tests for per-task expansion driven by REAL task filenames.

Root cause (loop 06-08): the matrix consumer expanded per_task commands by
synthesizing ``TASK-{k}.md`` for ``k in range(1, loop_multiplier+1)``. Real task
files start at ``TASK-0.md``, have gaps, use decimal indices, and the count
over-counted companion artifacts — so the queue emitted commands for
non-existent files ("task N doesn't exist") AND silently dropped real tasks.

These tests pin the fix: when a wbs_root is available, the consumer enumerates
the real executable task specs (``enumerate_module_tasks``) and emits exactly
one command per real file; ``loop_multiplier`` is only a drift cross-check and a
fallback for callers without a wbs_root.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from workflow_app.dcp.queue_derivation import derive_queue_from_matrix
from workflow_app.models.dcp_command_matrix import DcpCommandMatrix


def _matrix(loop_multiplier: dict | None = None) -> DcpCommandMatrix:
    """Minimal valid matrix with per_task create-task (A) + execute-task (B3)."""
    lm = loop_multiplier if loop_multiplier is not None else {
        "A-creation": 99, "B3-execute": 99,
    }
    raw = {
        "schema_version": "1.0.1",
        "trail_max_entries": 200,
        "command_index": [
            {
                "name": "/create-task {task}",
                "template": "/create-task {task}",
                "phase": "A-creation",
                "model": "opus",
                "effort": "high",
                "interaction": "auto",
                "per_task": True,
                "per_stack": False,
                "mandatory": False,
                "source_ref": "test",
            },
            {
                "name": "/execute-task {task}",
                "template": "/execute-task {task}",
                "phase": "B3-execute",
                "model": "sonnet",
                "effort": "high",
                "interaction": "auto",
                "per_task": True,
                "per_stack": False,
                "mandatory": False,
                "source_ref": "test",
            },
        ],
        "phase_buckets": {"A-creation": [0], "B3-execute": [1]},
        "global_filter": [1, 1],
        "global_filter_trail": [],
        "modules": {
            "module-1-x": {
                "filter": [1, 1],
                "loop_multiplier": lm,
                "directive_boundaries": [],
                "trail": [],
                "trail_archive": [],
                "overrides_skipped": [],
                "artifacts": {"last_specific_flow": None},
            }
        },
        "fold_in_rules": {
            "H-commit": [], "I-human-signoff": [], "G-deploy": [], "I-human-mkt": [],
        },
        "current_module": "module-1-x",
        "execution_order": ["module-1-x"],
        "created_at": "2026-06-08T00:00:00Z",
        "created_by": "test",
        "last_mutated_at": "2026-06-08T00:00:00Z",
    }
    return DcpCommandMatrix.model_validate(raw)


def _module_dir(tmp_path: Path) -> Path:
    d = tmp_path / "modules" / "module-1-x"
    d.mkdir(parents=True)
    return d


def _task_basenames(specs, command_prefix: str) -> list[str]:
    """Ordered task basenames from rendered spec names of one command prefix."""
    out: list[str] = []
    for s in specs:
        if s.name.startswith(command_prefix + " "):
            out.append(s.name.rsplit("/", 1)[-1])
    return out


def test_real_filenames_cover_task_0_and_emit_no_ghost(tmp_path: Path) -> None:
    d = _module_dir(tmp_path)
    for k in (0, 1, 2):
        (d / f"TASK-{k}.md").touch()

    specs = derive_queue_from_matrix(_matrix(), "module-1-x", wbs_root=tmp_path)
    created = _task_basenames(specs, "/create-task")
    # TASK-0 covered; no TASK-3..TASK-99 ghosts despite loop_multiplier=99.
    assert created == ["TASK-0.md", "TASK-1.md", "TASK-2.md"]


def test_gaps_preserved_and_high_task_covered(tmp_path: Path) -> None:
    d = _module_dir(tmp_path)
    for k in (0, 1, 5, 10):
        (d / f"TASK-{k}.md").touch()

    specs = derive_queue_from_matrix(_matrix(), "module-1-x", wbs_root=tmp_path)
    created = _task_basenames(specs, "/create-task")
    # Exactly the real files, numeric-ordered: no TASK-2/3/4 ghosts, TASK-10 covered.
    assert created == ["TASK-0.md", "TASK-1.md", "TASK-5.md", "TASK-10.md"]


def test_decimal_index_supported(tmp_path: Path) -> None:
    d = _module_dir(tmp_path)
    (d / "TASK-0.md").touch()
    (d / "TASK-0.5.md").touch()
    (d / "TASK-1.md").touch()

    specs = derive_queue_from_matrix(_matrix(), "module-1-x", wbs_root=tmp_path)
    created = _task_basenames(specs, "/create-task")
    assert created == ["TASK-0.md", "TASK-0.5.md", "TASK-1.md"]


def test_companion_artifacts_excluded(tmp_path: Path) -> None:
    d = _module_dir(tmp_path)
    (d / "TASK-1.md").touch()
    (d / "TASK-2.md").touch()
    for companion in (
        "TASK-1-SCREENS.md", "TASK-1-UX.md", "TASK-1-VISUAL.md",
        "TASK-1-AUDIT.md", "TASK-1-REVIEW.md", "TASK-1-EXECUTION-REVIEW.md",
        "TASK-0-CHECKLIST.md", "TASK-1-2-INDEX.md",
    ):
        (d / companion).touch()

    specs = derive_queue_from_matrix(_matrix(), "module-1-x", wbs_root=tmp_path)
    created = _task_basenames(specs, "/create-task")
    assert created == ["TASK-1.md", "TASK-2.md"]


def test_numeric_order_not_lexicographic(tmp_path: Path) -> None:
    d = _module_dir(tmp_path)
    (d / "TASK-2.md").touch()
    (d / "TASK-10.md").touch()

    specs = derive_queue_from_matrix(_matrix(), "module-1-x", wbs_root=tmp_path)
    created = _task_basenames(specs, "/create-task")
    assert created == ["TASK-2.md", "TASK-10.md"]  # not ["TASK-10.md", "TASK-2.md"]


def test_execute_task_uses_same_real_files(tmp_path: Path) -> None:
    d = _module_dir(tmp_path)
    for k in (0, 3):
        (d / f"TASK-{k}.md").touch()

    specs = derive_queue_from_matrix(_matrix(), "module-1-x", wbs_root=tmp_path)
    executed = _task_basenames(specs, "/execute-task")
    assert executed == ["TASK-0.md", "TASK-3.md"]


def test_empty_module_dir_emits_zero_per_task(tmp_path: Path) -> None:
    d = _module_dir(tmp_path)
    # Dir exists but holds only a companion artifact -> zero executable tasks.
    (d / "TASK-0-CHECKLIST.md").touch()

    specs = derive_queue_from_matrix(_matrix(), "module-1-x", wbs_root=tmp_path)
    assert _task_basenames(specs, "/create-task") == []
    assert _task_basenames(specs, "/execute-task") == []


def test_wbs_root_none_falls_back_to_synthesis(tmp_path: Path) -> None:
    # No wbs_root: legacy count-synthesis from loop_multiplier preserved.
    specs = derive_queue_from_matrix(
        _matrix({"A-creation": 2, "B3-execute": 2}), "module-1-x"
    )
    created = _task_basenames(specs, "/create-task")
    assert created == ["TASK-1.md", "TASK-2.md"]


def test_missing_module_dir_raises_fail_loud(tmp_path: Path) -> None:
    # wbs_root set but module dir absent -> fail-loud ValueError (loop 06-09).
    # Synthesizing from a stale multiplier here fabricates phantom tasks
    # ("task N nao existe") and masks cm_id/dirname drift or a wrong wbs_root.
    # The widget catches this, toasts, and falls back to SPECIFIC-FLOW.json.
    with pytest.raises(ValueError, match="diretorio do modulo nao encontrado"):
        derive_queue_from_matrix(
            _matrix({"A-creation": 1, "B3-execute": 1}),
            "module-1-x",
            wbs_root=tmp_path,  # no modules/module-1-x created
        )


def test_loop_multiplier_drift_warns(tmp_path: Path, caplog) -> None:
    d = _module_dir(tmp_path)
    for k in (0, 1, 2):
        (d / f"TASK-{k}.md").touch()  # 3 real files vs loop_multiplier=99

    with caplog.at_level(logging.WARNING, logger="workflow_app.dcp.queue_derivation"):
        derive_queue_from_matrix(_matrix(), "module-1-x", wbs_root=tmp_path)

    assert any(
        "loop_multiplier" in r.message and "TASK-*.md reais" in r.message
        for r in caplog.records
    ), "expected a drift WARN when loop_multiplier != real task count"


def test_zero_multiplier_with_real_tasks_warns(tmp_path: Path, caplog) -> None:
    # loop_multiplier=0 but real tasks exist (0 -> N drift): stale/unmarked
    # matrix. Must WARN (and still emit the real tasks), not be suppressed.
    d = _module_dir(tmp_path)
    for k in (0, 1, 2):
        (d / f"TASK-{k}.md").touch()

    with caplog.at_level(logging.WARNING, logger="workflow_app.dcp.queue_derivation"):
        specs = derive_queue_from_matrix(
            _matrix({"A-creation": 0, "B3-execute": 0}), "module-1-x", wbs_root=tmp_path
        )

    assert _task_basenames(specs, "/create-task") == ["TASK-0.md", "TASK-1.md", "TASK-2.md"]
    assert any("loop_multiplier" in r.message for r in caplog.records), (
        "expected a drift WARN for 0 -> N (baked 0, real tasks present)"
    )


def test_foundations_pure_zero_multiplier_no_warn(tmp_path: Path, caplog) -> None:
    # loop_multiplier=0 AND no real tasks (foundations-pure): 0 == 0, no drift,
    # no warning, zero per-task commands.
    _module_dir(tmp_path)  # dir exists, empty of executable tasks

    with caplog.at_level(logging.WARNING, logger="workflow_app.dcp.queue_derivation"):
        specs = derive_queue_from_matrix(
            _matrix({"A-creation": 0, "B3-execute": 0}), "module-1-x", wbs_root=tmp_path
        )

    assert _task_basenames(specs, "/create-task") == []
    assert not any("loop_multiplier" in r.message for r in caplog.records), (
        "foundations-pure (0 == 0) must NOT emit a drift warning"
    )
