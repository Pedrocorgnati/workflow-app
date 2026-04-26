"""
Shared type-mapping helpers between UI and DB layers (module-05/TASK-5).

Consolidates conversion functions used by template_manager.py and
factory_templates.py to avoid duplication.
"""

from __future__ import annotations

from workflow_app.domain import (
    CommandInteractionType,
    EffortLevel,
    InteractionType,
    ModelName,
    ModelType,
)


def model_type_to_name(model_type: str) -> ModelName:
    """Convert DB model_type string to UI ModelName enum."""
    mapping = {
        ModelType.OPUS.value: ModelName.OPUS,
        ModelType.SONNET.value: ModelName.SONNET,
        ModelType.HAIKU.value: ModelName.HAIKU,
    }
    return mapping.get(model_type.lower(), ModelName.SONNET)


def model_name_to_db(model_name: ModelName) -> str:
    """Convert UI ModelName enum to DB model_type string."""
    return model_name.value.lower()


def interaction_to_ui(interaction_type: str) -> InteractionType:
    """Convert DB interaction_type string to UI InteractionType."""
    if interaction_type in (
        CommandInteractionType.INTERATIVO.value,
        CommandInteractionType.TIMEOUT.value,
    ):
        return InteractionType.INTERACTIVE
    return InteractionType.AUTO


def interaction_to_db(interaction_type: InteractionType) -> str:
    """Convert UI InteractionType to DB interaction_type string."""
    if interaction_type == InteractionType.INTERACTIVE:
        return CommandInteractionType.INTERATIVO.value
    return CommandInteractionType.SEM_INTERACAO.value


def effort_to_db(effort: EffortLevel) -> str:
    """Convert UI EffortLevel enum to DB effort_level string."""
    return effort.value


def db_to_effort(effort_level: str | None) -> EffortLevel:
    """Convert DB effort_level string to UI EffortLevel enum.

    Unknown or missing values default to STANDARD (medium) for backward
    compatibility with rows written before the T-053 migration.
    """
    if not effort_level:
        return EffortLevel.STANDARD
    try:
        return EffortLevel(effort_level.lower())
    except ValueError:
        return EffortLevel.STANDARD


def effort_type_to_name(effort_level: str | None) -> EffortLevel:
    """Alias of db_to_effort for symmetry with `model_type_to_name`."""
    return db_to_effort(effort_level)
