"""Tests for T-053: effort roundtrip through TemplateManager save→load→update.

Ensures CommandSpec.effort survives DB persistence in all 4 levels.
"""

from __future__ import annotations

import pytest

from workflow_app.domain import (
    CommandSpec,
    EffortLevel,
    InteractionType,
    ModelName,
)
from workflow_app.templates.template_manager import TemplateManager


@pytest.fixture
def tm(tmp_db_manager):
    return TemplateManager(database_manager=tmp_db_manager)


def _make_spec(name: str, position: int, effort: EffortLevel) -> CommandSpec:
    return CommandSpec(
        name=name,
        model=ModelName.OPUS,
        interaction_type=InteractionType.AUTO,
        position=position,
        effort=effort,
    )


def test_roundtrip_all_effort_levels(tm):
    """Save → load preserves effort for every EffortLevel value."""
    commands = [
        _make_spec("/clear", 1, EffortLevel.LOW),
        _make_spec("/prd-create", 2, EffortLevel.STANDARD),
        _make_spec("/lld-create", 3, EffortLevel.HIGH),
        _make_spec("/final-review", 4, EffortLevel.MAX),
    ]
    tid = tm.save_custom_template("Effort Roundtrip", "desc", commands)
    loaded = tm.load_template(tid)
    assert len(loaded.commands) == 4
    assert loaded.commands[0].effort == EffortLevel.LOW
    assert loaded.commands[1].effort == EffortLevel.STANDARD
    assert loaded.commands[2].effort == EffortLevel.HIGH
    assert loaded.commands[3].effort == EffortLevel.MAX


def test_default_effort_standard_when_spec_omits_it(tm):
    """CommandSpec without explicit effort defaults to STANDARD end-to-end."""
    commands = [
        CommandSpec(
            name="/prd-create",
            model=ModelName.OPUS,
            interaction_type=InteractionType.AUTO,
            position=1,
        ),
    ]
    tid = tm.save_custom_template("Default Effort", "desc", commands)
    loaded = tm.load_template(tid)
    assert loaded.commands[0].effort == EffortLevel.STANDARD


def test_update_custom_template_preserves_new_effort(tm):
    """update_custom_template replaces commands and persists new effort values."""
    original = [_make_spec("/prd-create", 1, EffortLevel.STANDARD)]
    tid = tm.save_custom_template("Update Effort", "desc", original)

    updated = [
        _make_spec("/prd-create", 1, EffortLevel.MAX),
        _make_spec("/lld-create", 2, EffortLevel.HIGH),
    ]
    tm.update_custom_template(tid, updated)

    loaded = tm.load_template(tid)
    assert len(loaded.commands) == 2
    assert loaded.commands[0].effort == EffortLevel.MAX
    assert loaded.commands[1].effort == EffortLevel.HIGH


def test_double_roundtrip_idempotent(tm):
    """save → load → update → load preserves effort identically."""
    commands = [
        _make_spec("/prd-create", 1, EffortLevel.HIGH),
        _make_spec("/lld-create", 2, EffortLevel.MAX),
    ]
    tid = tm.save_custom_template("Double Roundtrip", "desc", commands)
    first = tm.load_template(tid)

    tm.update_custom_template(tid, first.commands)
    second = tm.load_template(tid)

    assert [c.effort for c in second.commands] == [c.effort for c in first.commands]
    assert second.commands[0].effort == EffortLevel.HIGH
    assert second.commands[1].effort == EffortLevel.MAX
