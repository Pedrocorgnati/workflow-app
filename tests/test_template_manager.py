"""Tests for TemplateManager (module-05/TASK-1)."""

from __future__ import annotations

import pytest

from workflow_app.db.models import Template
from workflow_app.domain import (
    CommandSpec,
    InteractionType,
    ModelName,
    TemplateDTO,
    TemplateType,
)
from workflow_app.templates.template_manager import TemplateManager

# ─── Fixtures ───────────────────────────────────────────────────────────────── #


@pytest.fixture
def tm(tmp_db_manager):
    """TemplateManager backed by a temporary on-disk database."""
    return TemplateManager(database_manager=tmp_db_manager)


@pytest.fixture
def sample_commands():
    """Minimal list of CommandSpec for testing."""
    return [
        CommandSpec(
            name="/prd-create",
            model=ModelName.OPUS,
            interaction_type=InteractionType.AUTO,
            position=1,
            is_optional=False,
        ),
        CommandSpec(
            name="/hld-create",
            model=ModelName.SONNET,
            interaction_type=InteractionType.INTERACTIVE,
            position=2,
            is_optional=True,
        ),
    ]


# ─── list_templates ─────────────────────────────────────────────────────────── #


def test_list_templates_has_factory_by_default(tm):
    """DatabaseManager.setup() seeds 10 factory templates automatically."""
    result = tm.list_templates()
    assert len(result) == 10
    assert all(t.is_factory for t in result)


def test_list_templates_returns_dtos(tm, sample_commands):
    tm.save_custom_template("Meu Template", "desc", sample_commands)
    result = tm.list_templates()
    custom = [t for t in result if not t.is_factory]
    assert len(custom) == 1
    dto = custom[0]
    assert isinstance(dto, TemplateDTO)
    assert dto.name == "Meu Template"
    assert dto.template_type == TemplateType.CUSTOM
    assert dto.is_factory is False
    assert dto.commands == []  # list view omits commands


def test_list_templates_factory_first(tm, sample_commands):
    """Factory templates appear before custom ones."""
    tm.save_custom_template("Custom Z", "desc", sample_commands)
    result = tm.list_templates()
    # Factory templates come first (10), then custom (1)
    factory_count = sum(1 for t in result if t.is_factory)
    assert factory_count == 10
    assert result[-1].is_factory is False
    assert result[-1].name == "Custom Z"


# ─── load_template ──────────────────────────────────────────────────────────── #


def test_load_template_with_commands(tm, sample_commands):
    tid = tm.save_custom_template("Load Test", "desc", sample_commands, sha256="abc123")
    dto = tm.load_template(tid)
    assert dto.name == "Load Test"
    assert dto.sha256 == "abc123"
    assert len(dto.commands) == 2
    assert dto.commands[0].name == "/prd-create"
    assert dto.commands[0].model == ModelName.OPUS
    assert dto.commands[0].interaction_type == InteractionType.AUTO
    assert dto.commands[0].position == 1
    assert dto.commands[1].name == "/hld-create"
    assert dto.commands[1].model == ModelName.SONNET
    assert dto.commands[1].interaction_type == InteractionType.INTERACTIVE
    assert dto.commands[1].is_optional is True


def test_load_template_not_found(tm):
    with pytest.raises(ValueError, match="não encontrado"):
        tm.load_template(999)


# ─── save_custom_template ───────────────────────────────────────────────────── #


def test_save_returns_id(tm, sample_commands):
    tid = tm.save_custom_template("Save Test", "desc", sample_commands)
    assert isinstance(tid, int)
    assert tid > 0


def test_save_duplicate_name_raises(tm, sample_commands):
    tm.save_custom_template("Duplicate", "desc", sample_commands)
    with pytest.raises(ValueError, match="já existente"):
        tm.save_custom_template("Duplicate", "other", sample_commands)


def test_save_empty_name_raises(tm, sample_commands):
    with pytest.raises(ValueError, match="vazio"):
        tm.save_custom_template("", "desc", sample_commands)


def test_save_whitespace_name_raises(tm, sample_commands):
    with pytest.raises(ValueError, match="vazio"):
        tm.save_custom_template("   ", "desc", sample_commands)


def test_save_empty_commands_raises(tm):
    with pytest.raises(ValueError, match="pelo menos 1"):
        tm.save_custom_template("No Cmds", "desc", [])


def test_save_with_sha256(tm, sample_commands):
    tid = tm.save_custom_template("SHA Test", "desc", sample_commands, sha256="deadbeef" * 8)
    dto = tm.load_template(tid)
    assert dto.sha256 == "deadbeef" * 8


# ─── delete_template ────────────────────────────────────────────────────────── #


def test_delete_custom_template(tm, sample_commands):
    tid = tm.save_custom_template("To Delete", "desc", sample_commands)
    before = len(tm.list_templates())
    tm.delete_template(tid)
    after = len(tm.list_templates())
    assert after == before - 1


def test_delete_not_found_raises(tm):
    with pytest.raises(ValueError, match="não encontrado"):
        tm.delete_template(999)


def test_delete_factory_raises(tm, tmp_db_manager):
    with tmp_db_manager.get_session() as session:
        factory = Template(
            name="Factory Prot",
            description="protected",
            template_type="factory",
            is_factory=True,
        )
        session.add(factory)
        session.commit()
        fid = factory.id

    with pytest.raises(PermissionError, match="fábrica"):
        tm.delete_template(fid)


# ─── check_version ──────────────────────────────────────────────────────────── #


def test_check_version_matching(tm, sample_commands):
    tid = tm.save_custom_template("Ver Match", "d", sample_commands, sha256="aaa")
    assert tm.check_version(tid, "aaa") is True


def test_check_version_divergent(tm, sample_commands):
    tid = tm.save_custom_template("Ver Div", "d", sample_commands, sha256="aaa")
    assert tm.check_version(tid, "bbb") is False


def test_check_version_no_hash(tm, sample_commands):
    tid = tm.save_custom_template("Ver None", "d", sample_commands)
    assert tm.check_version(tid, "anything") is False


def test_check_version_not_found(tm):
    assert tm.check_version(999, "hash") is False


# ─── update_sha256 ──────────────────────────────────────────────────────────── #


def test_update_sha256(tm, sample_commands):
    tid = tm.save_custom_template("Upd SHA", "d", sample_commands, sha256="old")
    tm.update_sha256(tid, "new_hash")
    assert tm.check_version(tid, "new_hash") is True


def test_update_sha256_nonexistent(tm):
    # Should not raise, just silently skip
    tm.update_sha256(999, "hash")


# ─── Type mapping round-trip ────────────────────────────────────────────────── #


def test_model_type_roundtrip(tm):
    """Save with ModelName.HAIKU → load back as ModelName.HAIKU."""
    cmds = [
        CommandSpec(name="/test", model=ModelName.HAIKU, position=1),
    ]
    tid = tm.save_custom_template("Model RT", "d", cmds)
    dto = tm.load_template(tid)
    assert dto.commands[0].model == ModelName.HAIKU


def test_interaction_type_roundtrip(tm):
    """Save with InteractionType.INTERACTIVE → load back as INTERACTIVE."""
    cmds = [
        CommandSpec(
            name="/test",
            interaction_type=InteractionType.INTERACTIVE,
            position=1,
        ),
    ]
    tid = tm.save_custom_template("Inter RT", "d", cmds)
    dto = tm.load_template(tid)
    assert dto.commands[0].interaction_type == InteractionType.INTERACTIVE
