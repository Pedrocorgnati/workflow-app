"""Parity test: the workflow-app task enumerator must match the canonical one.

`workflow_app.dcp.task_enum` lazy-imports the canonical
`specific_flow.templating.enumerate_module_tasks` and keeps a LOCAL fallback
implementing the identical rule. This guards the single-engine discipline
(dcp-cmd-list-build.md §19.2): if the local fallback ever drifts from the
canonical function, this test fails in CI.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from workflow_app.dcp import task_enum


def _populate(tmp_path: Path) -> Path:
    d = tmp_path / "modules" / "module-1-x"
    d.mkdir(parents=True)
    for name in (
        "TASK-0.md", "TASK-1.md", "TASK-2.md", "TASK-5.md", "TASK-10.md",
        "TASK-0.5.md", "TASK-001.md", "TASK-100.md",
        # companions / non-tasks that MUST be excluded:
        "TASK-1-SCREENS.md", "TASK-1-UX.md", "TASK-1-VISUAL.md",
        "TASK-1-AUDIT.md", "TASK-1-REVIEW.md", "TASK-1-EXECUTION-REVIEW.md",
        "TASK-0-CHECKLIST.md", "TASK-1-2-INDEX.md", "TASK-1-routes.md",
        "NOTES.md", "README.md",
    ):
        (d / name).touch()
    return d


def test_local_fallback_matches_canonical(tmp_path: Path) -> None:
    module_dir = _populate(tmp_path)
    canonical = task_enum._load_canonical()
    if canonical is None:
        pytest.fail(
            "canonical enumerate_module_tasks failed to import — the workflow-app "
            "tree could not reach specific_flow.templating (cross-tree sys.path)."
        )
    assert task_enum._local_enumerate(module_dir) == list(canonical(module_dir))


def test_public_enumerator_is_canonical_and_correct(tmp_path: Path) -> None:
    module_dir = _populate(tmp_path)
    result = task_enum.enumerate_module_tasks(module_dir)
    # Only canonical executable specs, numeric-ordered (Decimal key).
    assert result == [
        "TASK-0.md", "TASK-0.5.md", "TASK-001.md", "TASK-1.md",
        "TASK-2.md", "TASK-5.md", "TASK-10.md", "TASK-100.md",
    ]


def test_missing_dir_returns_empty(tmp_path: Path) -> None:
    assert task_enum.enumerate_module_tasks(tmp_path / "nope") == []
