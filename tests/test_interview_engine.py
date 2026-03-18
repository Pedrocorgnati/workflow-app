"""Tests for InterviewEngine."""

from __future__ import annotations

import pytest

from workflow_app.domain import CommandSpec, ModelName
from workflow_app.interview.interview_engine import InterviewEngine


def test_get_stub_template_returns_command_specs():
    engine = InterviewEngine()
    specs = engine.get_stub_template()
    assert len(specs) > 0
    assert all(isinstance(s, CommandSpec) for s in specs)


def test_stub_template_has_positions():
    engine = InterviewEngine()
    specs = engine.get_stub_template()
    positions = [s.position for s in specs]
    assert positions == list(range(1, len(specs) + 1))


def test_stub_template_first_command():
    engine = InterviewEngine()
    specs = engine.get_stub_template()
    first = specs[0]
    assert first.name == "/project-json"
    assert first.model == ModelName.SONNET
    assert first.is_optional is False


def test_generate_novo_projeto():
    engine = InterviewEngine()
    specs = engine.generate_command_list({"project_type": "novo"})
    assert len(specs) > 0
    assert specs[0].name == "/project-json"


def test_generate_feature():
    engine = InterviewEngine()
    specs = engine.generate_command_list({"project_type": "feature_grande"})
    assert len(specs) > 0
    assert specs[0].name == "/feature-brief-create"


def test_generate_unknown_raises():
    engine = InterviewEngine()
    with pytest.raises(ValueError, match="desconhecido"):
        engine.generate_command_list({"project_type": "unknown_type_xyz"})


def test_generate_refactor():
    engine = InterviewEngine()
    specs = engine.generate_command_list({"project_type": "refactor", "stack": "pyside6"})
    assert len(specs) > 0
    names = [s.name for s in specs]
    # Refactor uses PIPELINE_COMMANDS filtered, no frontend
    assert "/front-end-build" not in names
    # Should have F2 commands (mandatory)
    assert "/prd-create" in names
    assert "/review-prd-flow" in names


def test_feature_no_frontend_excludes_frontend_build():
    engine = InterviewEngine()
    specs = engine.generate_command_list({
        "project_type": "feature",
        "stack": "fastapi",
        "has_frontend": "não",
    })
    names = [s.name for s in specs]
    assert "/front-end-build" not in names
    assert "/feature-brief-create" in names


def test_feature_includes_prd_and_user_stories():
    engine = InterviewEngine()
    specs = engine.generate_command_list({"project_type": "feature", "stack": "nextjs"})
    names = [s.name for s in specs]
    assert "/prd-create" in names
    assert "/user-stories-create" in names


def test_feature_respects_active_phases():
    engine = InterviewEngine()
    specs = engine.generate_command_list({
        "project_type": "feature",
        "stack": "nextjs",
        "active_phases": ["f1"],  # only F1 + mandatory
    })
    names = [s.name for s in specs]
    assert "/feature-brief-create" in names
    # F7 commands should still appear (mandatory phase)
    assert "/auto-flow execute" in names


def test_get_stub_template_content():
    engine = InterviewEngine()
    specs = engine.get_stub_template()
    names = [s.name for s in specs]
    assert "/project-json" in names
    assert "/prd-create" in names
    assert specs[0].position == 1
    assert specs[-1].position == len(specs)
