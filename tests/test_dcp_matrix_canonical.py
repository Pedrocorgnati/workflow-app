from __future__ import annotations

from datetime import datetime, timezone

from workflow_app.dcp.queue_derivation import derive_queue_from_matrix
from workflow_app.domain import EffortLevel, InteractionType, ModelName
from workflow_app.models.dcp_command_matrix import DcpCommandMatrix


def _matrix(raw_overrides: dict | None = None) -> DcpCommandMatrix:
    raw = {
        "schema_version": "1.0.1",
        "trail_max_entries": 200,
        "command_index": [
            {
                "name": "/create-task {task}",
                "phase": "A-creation",
                "model": "opus",
                "effort": "high",
                "interaction": "manual",
                "per_task": True,
                "mandatory": True,
                "source_ref": "test:A",
            },
            {
                "name": "/review-created-task {task}",
                "phase": "A-creation",
                "model": "opus",
                "effort": "high",
                "interaction": "auto",
                "per_task": True,
                "mandatory": True,
                "source_ref": "test:A-review",
            },
            {
                "name": "/tdd:test-plan {module_path}",
                "phase": "B-tdd",
                "model": "sonnet",
                "effort": "medium",
                "interaction": "auto",
                "source_ref": "test:B-tdd",
            },
            {
                "name": "/dcp:directive-injector --module {module_n}",
                "phase": "B-dcp",
                "model": "sonnet",
                "effort": "max",
                "interaction": "headless",
                "source_ref": "test:B-dcp",
            },
        ],
        "phase_buckets": {
            "A-creation": [0, 1],
            "B-tdd": [2],
            "B-dcp": [3],
        },
        "global_filter": [1, 1, 1, 1],
        "global_filter_trail": [],
        "modules": {
            "module-1-foundations": {
                "filter": [1, 1, 1, 1],
                "loop_multiplier": {"A-creation": 1, "B-tdd": 1, "B-dcp": 1},
                "directive_boundaries": [],
                "trail": [],
                "trail_archive": [],
                "overrides_skipped": [],
                "artifacts": {"last_specific_flow": None},
            }
        },
        "fold_in_rules": {
            "H-commit": [
                {
                    "name": "/commit:simple {commit_target}",
                    "phase": "H-commit",
                    "model": "sonnet",
                    "effort": "medium",
                    "interaction": "auto",
                    "source_ref": "test:H",
                }
            ],
            "I-human-signoff": [
                {
                    "name": "/delivery:sign-off",
                    "phase": "I-human-signoff",
                    "model": "opus",
                    "effort": "high",
                    "interaction": "manual",
                    "source_ref": "test:I",
                }
            ],
            "G-deploy": [],
            "I-human-mkt": [],
        },
        "current_module": "module-1-foundations",
        "execution_order": ["module-1-foundations"],
        "created_at": datetime(2026, 5, 19, tzinfo=timezone.utc).isoformat(),
        "created_by": "test",
        "last_mutated_at": datetime(2026, 5, 19, tzinfo=timezone.utc).isoformat(),
    }
    if raw_overrides:
        raw.update(raw_overrides)
    return DcpCommandMatrix.model_validate(raw)


def test_matrix_accepts_canonical_dcp_enums() -> None:
    matrix = _matrix()

    assert matrix.command_index[2].phase == "B-tdd"
    assert matrix.command_index[3].phase == "B-dcp"
    assert matrix.command_index[3].model == "sonnet"
    assert matrix.command_index[3].effort == "max"
    assert matrix.command_index[0].interaction == "manual"


def test_matrix_derivation_can_return_real_commands_without_directives() -> None:
    specs = derive_queue_from_matrix(_matrix(), "module-1-foundations")
    names = [spec.name for spec in specs]

    assert "/clear" not in names
    assert not any(name.startswith("/model ") for name in names)
    assert not any(name.startswith("/effort ") for name in names)
    assert names[-2].startswith("/commit:simple")
    assert names[-1] == "/delivery:sign-off"


def test_matrix_derivation_renders_directives_as_separate_deduped_rows() -> None:
    specs = derive_queue_from_matrix(
        _matrix(),
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
    assert names[4] == "/review-created-task modules/module-1-foundations/TASK-1.md"
    assert all(" /model " not in name for name in names)
    assert names.count("/model opus") == 2
    assert names.count("/effort high") == 2
    assert "/model sonnet" in names
    assert "/effort max" in names
    assert "/model sonnet" in names
    assert "/effort medium" in names


def test_fold_in_metadata_is_honored() -> None:
    specs = derive_queue_from_matrix(_matrix(), "module-1-foundations")

    commit = next(spec for spec in specs if spec.name.startswith("/commit:simple"))
    signoff = next(spec for spec in specs if spec.name == "/delivery:sign-off")

    assert commit.model == ModelName.SONNET
    assert commit.effort == EffortLevel.STANDARD
    assert signoff.model == ModelName.OPUS
    assert signoff.effort == EffortLevel.HIGH
    assert signoff.interaction_type == InteractionType.INTERACTIVE
