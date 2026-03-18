"""Tests for domain enums and dataclasses."""

from __future__ import annotations

from workflow_app.domain import (
    CommandSpec,
    CommandStatus,
    InteractionType,
    ModelName,
    PipelineStatus,
)


def test_command_spec_defaults():
    spec = CommandSpec(name="/prd-create")
    assert spec.model == ModelName.SONNET
    assert spec.interaction_type == InteractionType.AUTO
    assert spec.position == 0
    assert spec.is_optional is False


def test_command_spec_display():
    spec = CommandSpec(name="/prd-create", model=ModelName.OPUS)
    assert spec.display_name() == "/prd-create"
    assert spec.model_badge_text() == "Opus"
    assert spec.interaction_badge_text() == "→ auto"


def test_command_spec_interactive():
    spec = CommandSpec(name="/intake:enhance", interaction_type=InteractionType.INTERACTIVE)
    assert spec.interaction_badge_text() == "↔ inter"


def test_command_status_values():
    assert CommandStatus.PENDENTE.value == "pendente"
    assert CommandStatus.EXECUTANDO.value == "executando"
    assert CommandStatus.CONCLUIDO.value == "concluido"


def test_pipeline_status_values():
    assert PipelineStatus.NAO_INICIADO.value == "nao_iniciado"
    assert PipelineStatus.CONCLUIDO.value == "concluido"


def test_pipeline_status_has_interrompido():
    assert hasattr(PipelineStatus, "INTERROMPIDO")
    assert PipelineStatus.INTERROMPIDO.value == "interrompido"


def test_enum_str_mixin():
    """Enums must use str mixin for direct string comparison."""
    assert CommandStatus.PENDENTE == "pendente"
    assert PipelineStatus.CRIADO == "criado"
    assert isinstance(CommandStatus.PENDENTE, str)
