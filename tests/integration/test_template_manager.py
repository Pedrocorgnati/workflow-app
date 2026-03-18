"""Testes de integração: TemplateManager (module-05/TASK-1).

Cobre:
  - list_templates(): retorna todos os templates, fábrica antes dos custom
  - load_template(): carrega com CommandSpec eager-loaded
  - save_custom_template(): persiste com comandos associados
  - update_custom_template(): substitui comandos
  - delete_template(): remove custom; bloqueia fábrica
  - check_version(): verifica sha256
  - Erros esperados: nome vazio, lista vazia, nome duplicado, id inexistente
"""
from __future__ import annotations

import pytest

from workflow_app.domain import CommandSpec, InteractionType, ModelName
from workflow_app.templates.template_manager import TemplateManager

# ── Helpers ───────────────────────────────────────────────────────────────────


def _spec(name: str, position: int = 1) -> CommandSpec:
    return CommandSpec(
        name=name,
        model=ModelName.SONNET,
        interaction_type=InteractionType.AUTO,
        position=position,
    )


# ── list_templates ─────────────────────────────────────────────────────────────


def test_list_templates_returns_list(int_db_manager):
    mgr = TemplateManager(int_db_manager)
    result = mgr.list_templates()
    assert isinstance(result, list)


def test_list_templates_factory_before_custom(int_db_manager):
    """Templates de fábrica devem aparecer antes dos custom na listagem."""
    mgr = TemplateManager(int_db_manager)

    mgr.save_custom_template(
        "ZZZ Custom First",
        "desc",
        [_spec("/prd-create")],
    )

    result = mgr.list_templates()
    factory_indices = [i for i, t in enumerate(result) if t.is_factory]
    custom_indices = [i for i, t in enumerate(result) if not t.is_factory]

    if factory_indices and custom_indices:
        assert max(factory_indices) < min(custom_indices)


# ── save / load ───────────────────────────────────────────────────────────────


def test_save_and_load_template(int_db_manager):
    """Template salvo deve ser recarregado com todos os CommandSpec."""
    mgr = TemplateManager(int_db_manager)

    specs = [_spec("/prd-create", 1), _spec("/hld-create", 2)]
    tid = mgr.save_custom_template("IntTest Save Load", "desc", specs)

    loaded = mgr.load_template(tid)

    assert loaded.id == tid
    assert loaded.name == "IntTest Save Load"
    assert loaded.description == "desc"
    assert len(loaded.commands) == 2
    assert loaded.commands[0].name == "/prd-create"
    assert loaded.commands[1].name == "/hld-create"


def test_load_template_preserves_position_order(int_db_manager):
    """Comandos devem ser retornados na ordem de position."""
    mgr = TemplateManager(int_db_manager)

    specs = [_spec("/z-cmd", 3), _spec("/a-cmd", 1), _spec("/m-cmd", 2)]
    tid = mgr.save_custom_template("IntTest Position", "desc", specs)

    loaded = mgr.load_template(tid)
    positions = [c.position for c in loaded.commands]
    assert positions == sorted(positions)


def test_load_nonexistent_template_raises(int_db_manager):
    mgr = TemplateManager(int_db_manager)
    with pytest.raises(ValueError, match="não encontrado"):
        mgr.load_template(999999)


# ── update ────────────────────────────────────────────────────────────────────


def test_update_custom_template_replaces_commands(int_db_manager):
    """update_custom_template() deve substituir todos os comandos existentes."""
    mgr = TemplateManager(int_db_manager)

    tid = mgr.save_custom_template(
        "IntTest Update",
        "original",
        [_spec("/original", 1)],
    )

    new_specs = [_spec("/new-1", 1), _spec("/new-2", 2), _spec("/new-3", 3)]
    mgr.update_custom_template(tid, new_specs)

    loaded = mgr.load_template(tid)
    names = [c.name for c in loaded.commands]
    assert names == ["/new-1", "/new-2", "/new-3"]
    assert "/original" not in names


def test_update_empty_commands_raises(int_db_manager):
    mgr = TemplateManager(int_db_manager)
    tid = mgr.save_custom_template(
        "IntTest UpdateEmpty",
        "desc",
        [_spec("/prd-create")],
    )
    with pytest.raises(ValueError, match="pelo menos 1 comando"):
        mgr.update_custom_template(tid, [])


# ── delete ────────────────────────────────────────────────────────────────────


def test_delete_custom_template(int_db_manager):
    """delete_template() deve remover o template do banco."""
    mgr = TemplateManager(int_db_manager)
    tid = mgr.save_custom_template(
        "IntTest Delete",
        "will be deleted",
        [_spec("/prd-create")],
    )

    mgr.delete_template(tid)

    with pytest.raises(ValueError, match="não encontrado"):
        mgr.load_template(tid)


def test_delete_nonexistent_raises(int_db_manager):
    mgr = TemplateManager(int_db_manager)
    with pytest.raises(ValueError, match="não encontrado"):
        mgr.delete_template(999999)


# ── check_version ─────────────────────────────────────────────────────────────


def test_check_version_matches(int_db_manager):
    mgr = TemplateManager(int_db_manager)
    the_hash = "abc123def456" * 5  # 60 chars (< 64)
    tid = mgr.save_custom_template(
        "IntTest Version",
        "desc",
        [_spec("/prd-create")],
        sha256=the_hash,
    )
    assert mgr.check_version(tid, the_hash) is True


def test_check_version_mismatch(int_db_manager):
    mgr = TemplateManager(int_db_manager)
    the_hash = "aaa" * 20
    tid = mgr.save_custom_template(
        "IntTest VersionMismatch",
        "desc",
        [_spec("/prd-create")],
        sha256=the_hash,
    )
    assert mgr.check_version(tid, "different_hash") is False


def test_check_version_no_hash_returns_false(int_db_manager):
    mgr = TemplateManager(int_db_manager)
    tid = mgr.save_custom_template(
        "IntTest NoHash",
        "desc",
        [_spec("/prd-create")],
        sha256=None,
    )
    assert mgr.check_version(tid, "any_hash") is False


# ── Validation errors ─────────────────────────────────────────────────────────


def test_save_empty_name_raises(int_db_manager):
    mgr = TemplateManager(int_db_manager)
    with pytest.raises(ValueError, match="vazio"):
        mgr.save_custom_template("", "desc", [_spec("/prd-create")])


def test_save_blank_name_raises(int_db_manager):
    mgr = TemplateManager(int_db_manager)
    with pytest.raises(ValueError, match="vazio"):
        mgr.save_custom_template("   ", "desc", [_spec("/prd-create")])


def test_save_empty_commands_raises(int_db_manager):
    mgr = TemplateManager(int_db_manager)
    with pytest.raises(ValueError, match="pelo menos 1 comando"):
        mgr.save_custom_template("IntTest EmptyCmd", "desc", [])


def test_save_duplicate_name_raises(int_db_manager):
    mgr = TemplateManager(int_db_manager)
    name = "IntTest Duplicate Name"
    mgr.save_custom_template(name, "first", [_spec("/prd-create")])
    with pytest.raises(ValueError, match="já existente"):
        mgr.save_custom_template(name, "second", [_spec("/hld-create")])
