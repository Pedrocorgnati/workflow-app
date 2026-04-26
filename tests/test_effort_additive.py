"""Tests for T-053: /effort additive mirror in workflow-app.

Covers:
  - EffortLevel enum values mirror Claude Code /effort CLI flags
  - CommandSpec.effort defaults to STANDARD (backward compat)
  - Quick templates auto-tag HIGH-effort commands
  - Autocast CLI emits --effort flag in both interactive and auto modes
  - Mapping helpers roundtrip through DB strings
"""

from __future__ import annotations

from workflow_app.command_queue.autocast_cli import build_launch_plan
from workflow_app.domain import (
    CommandSpec,
    EffortLevel,
    InteractionType,
    ModelName,
)
from workflow_app.templates._mapping import (
    db_to_effort,
    effort_to_db,
)
from workflow_app.templates.quick_templates import (
    TEMPLATE_BRIEF_NEW,
    TEMPLATE_BUSINESS,
    TEMPLATE_DAILY,
    TEMPLATE_MODULES,
    _HIGH_EFFORT_COMMANDS,
    _resolve_effort,
)


# ─── EffortLevel enum ─────────────────────────────────────────────────────── #


def test_effort_level_values_mirror_cli():
    """EffortLevel.value must match Claude Code's --effort CLI flag values."""
    assert EffortLevel.LOW.value == "low"
    assert EffortLevel.STANDARD.value == "medium"
    assert EffortLevel.HIGH.value == "high"
    assert EffortLevel.MAX.value == "max"


def test_effort_level_all_four_levels():
    """Enum has exactly 4 levels."""
    assert len(list(EffortLevel)) == 4


# ─── CommandSpec.effort default ───────────────────────────────────────────── #


def test_command_spec_default_effort_is_standard():
    """Existing callers that omit effort still get a valid default."""
    spec = CommandSpec(
        name="/prd-create",
        model=ModelName.OPUS,
        interaction_type=InteractionType.AUTO,
        position=1,
    )
    assert spec.effort == EffortLevel.STANDARD


def test_command_spec_effort_badge_text():
    spec = CommandSpec(
        name="/prd-create",
        model=ModelName.OPUS,
        interaction_type=InteractionType.AUTO,
        position=1,
        effort=EffortLevel.HIGH,
    )
    assert spec.effort_badge_text() == "high"


# ─── Mapping helpers ──────────────────────────────────────────────────────── #


def test_effort_mapping_roundtrip_all_levels():
    for level in EffortLevel:
        assert db_to_effort(effort_to_db(level)) == level


def test_db_to_effort_null_defaults_to_standard():
    assert db_to_effort(None) == EffortLevel.STANDARD
    assert db_to_effort("") == EffortLevel.STANDARD


def test_db_to_effort_unknown_defaults_to_standard():
    assert db_to_effort("nonsense") == EffortLevel.STANDARD


def test_db_to_effort_case_insensitive():
    assert db_to_effort("HIGH") == EffortLevel.HIGH
    assert db_to_effort("Medium") == EffortLevel.STANDARD


# ─── Quick templates HIGH auto-tagging ────────────────────────────────────── #


def test_high_effort_set_not_empty():
    assert len(_HIGH_EFFORT_COMMANDS) > 0
    assert "/prd-create" in _HIGH_EFFORT_COMMANDS
    assert "/final-review" in _HIGH_EFFORT_COMMANDS


def test_resolve_effort_auto_tags_heavy_commands():
    assert _resolve_effort("/prd-create", None) == EffortLevel.HIGH
    assert _resolve_effort("/lld-create", None) == EffortLevel.HIGH


def test_resolve_effort_defaults_standard_for_light_commands():
    assert _resolve_effort("/npm-run", None) == EffortLevel.STANDARD
    assert _resolve_effort("/clear", None) == EffortLevel.STANDARD


def test_resolve_effort_override_wins():
    assert _resolve_effort("/prd-create", EffortLevel.LOW) == EffortLevel.LOW
    assert _resolve_effort("/npm-run", EffortLevel.MAX) == EffortLevel.MAX


def test_quick_templates_auto_tag_heavy_commands_as_high():
    """Heavy commands inside module-level templates must carry effort=HIGH."""
    templates = {
        "DAILY": TEMPLATE_DAILY,
        "MODULES": TEMPLATE_MODULES,
        "BUSINESS": TEMPLATE_BUSINESS,
        "BRIEF_NEW": TEMPLATE_BRIEF_NEW,
    }
    for name, specs in templates.items():
        for s in specs:
            if s.name in _HIGH_EFFORT_COMMANDS:
                assert s.effort == EffortLevel.HIGH, (
                    f"{s.name} in {name} should be HIGH, got {s.effort}"
                )
            else:
                assert s.effort == EffortLevel.STANDARD, (
                    f"{s.name} in {name} should default STANDARD, got {s.effort}"
                )


# ─── Autocast CLI --effort flag emission ──────────────────────────────────── #


def test_autocast_emits_effort_flag_interactive():
    spec = CommandSpec(
        name="/prd-create",
        model=ModelName.OPUS,
        interaction_type=InteractionType.INTERACTIVE,
        position=1,
        effort=EffortLevel.HIGH,
    )
    plan = build_launch_plan(spec, "clauded")
    assert "--effort" in plan.argv
    idx = plan.argv.index("--effort")
    assert plan.argv[idx + 1] == "high"


def test_autocast_emits_effort_flag_auto():
    spec = CommandSpec(
        name="/prd-create",
        model=ModelName.OPUS,
        interaction_type=InteractionType.AUTO,
        position=1,
        effort=EffortLevel.MAX,
    )
    plan = build_launch_plan(spec, "clauded")
    assert "--effort" in plan.argv
    idx = plan.argv.index("--effort")
    assert plan.argv[idx + 1] == "max"


def test_autocast_emits_medium_for_standard_effort():
    spec = CommandSpec(
        name="/npm-run",
        model=ModelName.SONNET,
        interaction_type=InteractionType.AUTO,
        position=1,
        effort=EffortLevel.STANDARD,
    )
    plan = build_launch_plan(spec, "clauded")
    assert "--effort" in plan.argv
    idx = plan.argv.index("--effort")
    assert plan.argv[idx + 1] == "medium"


def test_autocast_low_effort():
    spec = CommandSpec(
        name="/clear",
        model=ModelName.SONNET,
        interaction_type=InteractionType.AUTO,
        position=1,
        effort=EffortLevel.LOW,
    )
    plan = build_launch_plan(spec, "clauded")
    idx = plan.argv.index("--effort")
    assert plan.argv[idx + 1] == "low"
