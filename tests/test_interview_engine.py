"""Tests for InterviewEngine."""

from __future__ import annotations

import pytest

from workflow_app.domain import CommandSpec, InteractionType, ModelName
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
