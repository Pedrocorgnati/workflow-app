from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from workflow_app.dcp.queue_derivation import derive_queue_from_matrix
from workflow_app.domain import EffortLevel, InteractionType, ModelName
from workflow_app.models.dcp_command_matrix import DcpCommandMatrix


REPO_ROOT = Path(__file__).resolve().parents[3]
MIGRATOR = REPO_ROOT / "ai-forge" / "scripts" / "migrate-dcp-matrix-canonical.py"
PROFILES = REPO_ROOT / ".claude" / "commands" / "_lib" / "specific_flow" / "profiles.py"

FOLD_IN_KEYS = ("G-deploy", "H-commit", "I-human-signoff", "I-human-mkt")


def _legacy_skeleton() -> dict:
    return {
        "schema_version": "1.0.1",
        "trail_max_entries": 200,
        "command_index": [],
        "phase_buckets": {},
        "global_filter": [],
        "global_filter_trail": [],
        "modules": {
            "module-1-foundations": {
                "filter": [],
                "loop_multiplier": {},
                "directive_boundaries": [],
                "trail": [],
                "trail_archive": [],
                "overrides_skipped": [],
                "artifacts": {"last_specific_flow": None},
            }
        },
        "fold_in_rules": {k: [] for k in FOLD_IN_KEYS},
        "current_module": "module-1-foundations",
        "execution_order": ["module-1-foundations"],
        "created_at": "2026-05-19T00:00:00Z",
        "created_by": "test:dcp-matrix-canonical",
        "last_mutated_at": "2026-05-19T00:00:00Z",
    }


def _inject_canonical_fold_in(raw: dict) -> dict:
    raw["fold_in_rules"]["H-commit"] = [
        {
            "name": "/commit:simple {commit_target}",
            "template": "/commit:simple {commit_target}",
            "phase": "H-commit",
            "model": "sonnet",
            "effort": "medium",
            "interaction": "auto",
            "source_ref": "test:H",
        }
    ]
    raw["fold_in_rules"]["I-human-signoff"] = [
        {
            "name": "/delivery:sign-off",
            "template": "/delivery:sign-off",
            "phase": "I-human-signoff",
            "model": "opus",
            "effort": "high",
            "interaction": "manual",
            "source_ref": "test:I",
        }
    ]
    return raw


def _run_migrator(matrix_path: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            str(MIGRATOR),
            "--matrix",
            str(matrix_path),
            "--profiles",
            str(PROFILES),
        ],
        capture_output=True,
        text=True,
        cwd=str(REPO_ROOT),
    )


@pytest.fixture
def migrated_raw(tmp_path: Path) -> dict:
    """Real migrator run in tmpdir; returns the rewritten matrix dict.

    Replaces the legacy synthetic fixture (TASK-013): instead of hand-crafting
    a 4-entry command_index in memory, we materialize a legacy skeleton on
    disk, invoke the real migrator binary, and load the rewritten file. This
    means the test only passes when the new producer (TASK-006/TASK-007) emits
    the canonical dual-field shape (`name` + `template`); the old producer
    (which omitted `template`) makes ``model_validate`` accept the matrix but
    fails the dual-field assertion in
    ``test_matrix_emits_dual_field_name_and_template``.
    """
    matrix_path = tmp_path / "DCP-COMMAND-MATRIX.json"
    matrix_path.write_text(json.dumps(_legacy_skeleton(), indent=2), encoding="utf-8")
    result = _run_migrator(matrix_path)
    assert result.returncode == 0, (
        f"migrator failed (exit {result.returncode}): {result.stderr.strip()}"
    )
    return json.loads(matrix_path.read_text(encoding="utf-8"))


@pytest.fixture
def migrated_matrix(migrated_raw: dict) -> DcpCommandMatrix:
    return DcpCommandMatrix.model_validate(migrated_raw)


@pytest.fixture
def matrix_with_fold_in(migrated_raw: dict) -> DcpCommandMatrix:
    """Real migrator output + canonical fold_in_rules (commit + sign-off).

    The migrator deliberately resets ``fold_in_rules`` to the empty baseline
    (Camada 3 do plan): the canonical entries are injected separately in real
    runtime. The tests that exercise fold-in metadata reuse this fixture.
    """
    return DcpCommandMatrix.model_validate(_inject_canonical_fold_in(dict(migrated_raw)))


def _find_first(matrix: DcpCommandMatrix, predicate) -> object:
    for entry in matrix.command_index:
        if predicate(entry):
            return entry
    raise AssertionError("no command_index entry matched predicate")


def test_matrix_emits_dual_field_name_and_template(migrated_matrix: DcpCommandMatrix) -> None:
    """W2 dual-field contract: every entry carries BOTH `name` and `template`.

    The new producer (TASK-007 flip) emits both fields lado a lado. Old
    producer omitted `template` (defaults to ``None``); this assertion is
    the canary that distinguishes legacy from canonical migrator output.
    """
    assert migrated_matrix.command_index, "migrator produced empty command_index"

    for entry in migrated_matrix.command_index:
        assert entry.name, f"empty name in entry: {entry!r}"
        assert entry.template is not None, (
            f"missing template (W2 dual-field) in entry: {entry!r}"
        )


def test_matrix_accepts_canonical_dcp_enums(migrated_matrix: DcpCommandMatrix) -> None:
    create_task = _find_first(
        migrated_matrix, lambda e: e.name == "/create-task {task}"
    )
    assert create_task.phase == "A-creation"
    assert create_task.model == "opus"
    assert create_task.effort == "high"

    tdd_plan = _find_first(
        migrated_matrix, lambda e: e.name == "/tdd:test-plan {module_path}"
    )
    assert tdd_plan.phase == "B-tdd"

    # Every entry's enums round-trip through the canonical Literal types.
    valid_models = {"opus", "sonnet", "haiku", None}
    valid_efforts = {"low", "medium", "high", "max", "standard", None}
    for entry in migrated_matrix.command_index:
        assert entry.model in valid_models, (
            f"non-canonical model {entry.model!r} in {entry.name!r}"
        )
        assert entry.effort in valid_efforts, (
            f"non-canonical effort {entry.effort!r} in {entry.name!r}"
        )


def test_matrix_derivation_can_return_real_commands_without_directives(
    matrix_with_fold_in: DcpCommandMatrix,
) -> None:
    specs = derive_queue_from_matrix(matrix_with_fold_in, "module-1-foundations")
    names = [spec.name for spec in specs]

    assert names, "derived queue must not be empty"
    assert "/clear" not in names
    assert not any(name.startswith("/model ") for name in names)
    assert not any(name.startswith("/effort ") for name in names)
    assert names[0] == "/create-task modules/module-1-foundations/TASK-1.md"
    assert any(name.startswith("/commit:simple") for name in names)
    assert names[-1] == "/delivery:sign-off"


def test_matrix_derivation_renders_directives_as_separate_deduped_rows(
    migrated_matrix: DcpCommandMatrix,
) -> None:
    specs = derive_queue_from_matrix(
        migrated_matrix,
        "module-1-foundations",
        include_directives=True,
    )
    names = [spec.name for spec in specs]

    assert names[:4] == [
        "/clear",
        "/model opus",
        "/effort high",
        "/create-task modules/module-1-foundations/TASK-1.md",
    ]
    assert all(" /model " not in name for name in names)
    assert names.count("/model opus") >= 2
    assert names.count("/effort high") >= 2
    assert "/model sonnet" in names
    assert "/effort medium" in names
    assert any(
        name == "/review-created-task modules/module-1-foundations/TASK-1.md"
        for name in names
    )


def test_fold_in_metadata_is_honored(matrix_with_fold_in: DcpCommandMatrix) -> None:
    specs = derive_queue_from_matrix(matrix_with_fold_in, "module-1-foundations")

    commit = next(spec for spec in specs if spec.name.startswith("/commit:simple"))
    signoff = next(spec for spec in specs if spec.name == "/delivery:sign-off")

    assert commit.model == ModelName.SONNET
    assert commit.effort == EffortLevel.STANDARD
    assert signoff.model == ModelName.OPUS
    assert signoff.effort == EffortLevel.HIGH
    assert signoff.interaction_type == InteractionType.INTERACTIVE
