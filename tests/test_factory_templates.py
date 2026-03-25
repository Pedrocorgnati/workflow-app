"""Tests for factory templates."""

from __future__ import annotations

import pytest

from workflow_app.domain import CommandSpec, ModelName
from workflow_app.templates.factory_templates import (
    FACTORY_TEMPLATES,
    refresh_factory_templates,
    seed_factory_templates,
)
from workflow_app.templates.quick_templates import (
    TEMPLATE_BRIEF_FEATURE,
    TEMPLATE_BRIEF_NEW,
    TEMPLATE_BUSINESS,
    TEMPLATE_DAILY,
    TEMPLATE_DEPLOY,
    TEMPLATE_JSON,
    TEMPLATE_MKT,
    TEMPLATE_MODULES,
)
from workflow_app.templates.template_manager import TemplateManager

# ─── Structure tests ────────────────────────────────────────────────────────── #


def test_eight_factory_templates_defined():
    assert len(FACTORY_TEMPLATES) == 9


def test_all_have_name_description_commands():
    for name, (description, commands) in FACTORY_TEMPLATES.items():
        assert name, f"Empty name: {name}"
        assert description, f"Empty description for: {name}"
        assert len(commands) > 0, f"No commands: {name}"


def test_json_has_1_command():
    assert len(TEMPLATE_JSON) == 1
    assert TEMPLATE_JSON[0].name == "/project-json"


def test_brief_new_has_expected_coverage():
    names = [cmd.name for cmd in TEMPLATE_BRIEF_NEW]
    assert len(TEMPLATE_BRIEF_NEW) >= 35
    assert names[0] == "/first-brief-create"
    assert names[-1] == "/review-optimization"


def test_brief_feature_has_expected_coverage():
    names = [cmd.name for cmd in TEMPLATE_BRIEF_FEATURE]
    assert len(TEMPLATE_BRIEF_FEATURE) >= 25
    assert names[0] == "/feature-brief-create"
    assert names[-1] == "/review-optimization"


def test_modules_has_expected_coverage():
    names = [cmd.name for cmd in TEMPLATE_MODULES]
    assert len(TEMPLATE_MODULES) >= 10
    assert "/modules:create-core" in names
    assert "/modules:review-created" in names


def test_deploy_has_expected_coverage():
    names = [cmd.name for cmd in TEMPLATE_DEPLOY]
    assert len(TEMPLATE_DEPLOY) >= 7
    assert "/ci-cd-create" in names
    assert "/deploy-flow" in names


def test_daily_has_5_commands():
    assert len(TEMPLATE_DAILY) == 5


def test_mkt_has_expected_coverage():
    names = [cmd.name for cmd in TEMPLATE_MKT]
    assert len(TEMPLATE_MKT) >= 5
    assert "/mkt:portfolio-add" in names
    assert "/handoff-create" in names


def test_business_has_expected_coverage():
    names = [cmd.name for cmd in TEMPLATE_BUSINESS]
    assert len(TEMPLATE_BUSINESS) >= 8
    assert "/business:sow-create" in names
    assert "/business:generate-json-project" in names


def test_all_positions_sequential():
    for name, (_, commands) in FACTORY_TEMPLATES.items():
        positions = [c.position for c in commands]
        expected = list(range(1, len(commands) + 1))
        assert positions == expected, f"Non-sequential in '{name}': {positions}"


def test_all_commands_have_valid_model():
    valid = {ModelName.OPUS, ModelName.SONNET, ModelName.HAIKU}
    for name, (_, commands) in FACTORY_TEMPLATES.items():
        for cmd in commands:
            assert cmd.model in valid, f"Invalid model '{cmd.model}' in '{name}/{cmd.name}'"


def test_brief_feature_starts_with_feature_brief():
    names = [c.name for c in TEMPLATE_BRIEF_FEATURE]
    assert names[0] == "/feature-brief-create"


def test_brief_new_starts_with_first_brief():
    names = [c.name for c in TEMPLATE_BRIEF_NEW]
    assert names[0] == "/first-brief-create"
    assert "/feature-brief-create" not in names


def test_all_commands_are_command_spec():
    for _, (_, commands) in FACTORY_TEMPLATES.items():
        for cmd in commands:
            assert isinstance(cmd, CommandSpec)


# ─── Seeding integration tests ──────────────────────────────────────────────── #


def test_seed_creates_8_templates(tmp_db_manager):
    # tmp_db_manager.setup() already calls _seed_initial_data which calls seed
    tm = TemplateManager(database_manager=tmp_db_manager)
    templates = tm.list_templates()
    factory_templates = [t for t in templates if t.is_factory]
    assert len(factory_templates) == 9


def test_seed_is_idempotent(tmp_db_manager):
    # Call seed again — should not duplicate
    seed_factory_templates(tmp_db_manager, sha256="test_hash")
    tm = TemplateManager(database_manager=tmp_db_manager)
    factory_templates = [t for t in tm.list_templates() if t.is_factory]
    assert len(factory_templates) == 9


def test_seed_brief_new_loads_with_commands(tmp_db_manager):
    tm = TemplateManager(database_manager=tmp_db_manager)
    templates = tm.list_templates()
    brief_new = next(t for t in templates if t.name == "Brief: New")
    dto = tm.load_template(brief_new.id)
    assert len(dto.commands) == len(TEMPLATE_BRIEF_NEW)
    assert dto.commands[0].name == "/first-brief-create"
    assert dto.is_factory is True


def test_seed_deploy_has_6_commands(tmp_db_manager):
    tm = TemplateManager(database_manager=tmp_db_manager)
    templates = tm.list_templates()
    deploy = next(t for t in templates if t.name == "Deploy")
    dto = tm.load_template(deploy.id)
    assert len(dto.commands) == len(TEMPLATE_DEPLOY)


def test_factory_templates_cannot_be_deleted(tmp_db_manager):
    tm = TemplateManager(database_manager=tmp_db_manager)
    templates = tm.list_templates()
    for t in templates:
        if t.is_factory:
            with pytest.raises(PermissionError):
                tm.delete_template(t.id)


def test_refresh_updates_commands(tmp_db_manager):
    """refresh_factory_templates re-inserts commands and updates sha256."""
    refresh_factory_templates(tmp_db_manager, new_hash="new_sha256_value")

    tm = TemplateManager(database_manager=tmp_db_manager)
    templates = tm.list_templates()
    for t in templates:
        if t.is_factory:
            assert t.sha256 == "new_sha256_value"

    # Verify commands are still correct after refresh
    brief_new = next(t for t in templates if t.name == "Brief: New")
    dto = tm.load_template(brief_new.id)
    assert len(dto.commands) == len(TEMPLATE_BRIEF_NEW)


def test_refresh_creates_missing_templates(tmp_db_manager):
    """If a factory template was somehow deleted from DB, refresh re-creates it."""
    from sqlalchemy import select

    from workflow_app.db.models import Template

    with tmp_db_manager.get_session() as session:
        t = session.execute(
            select(Template).where(Template.name == "Deploy")
        ).scalar_one()
        session.delete(t)
        session.commit()

    # Now refresh should re-create it
    refresh_factory_templates(tmp_db_manager, new_hash="restored_hash")

    tm = TemplateManager(database_manager=tmp_db_manager)
    templates = tm.list_templates()
    factory_names = {t.name for t in templates if t.is_factory}
    assert "Deploy" in factory_names
