"""Closed-set tests for typed frontmatter enforcement (item 008)."""

from __future__ import annotations

import pytest

from workflow_app.frontmatter_enforcement import (
    ENFORCEMENT_CLASSES,
    FrontmatterEnforcementError,
    classify_fields,
    get_declared_fields,
    get_policy,
)


VALID_VALUES = {
    "description": "Executa uma verificacao",
    "model": "opus",
    "argument-hint": "--name <slug>",
    "disable-model-invocation": True,
    "allowed-tools": "Read, Grep, Glob",
    "context": "fork",
    "agent": "Explore",
    "paths": ["src/**/*.py"],
    "dcp_version": "1.0.0",
    "effort": "high",
    "scope": "project",
    "mode_support": ["check", "write"],
    "state_transition": "execution->revision",
    "expected_state": {"source": "state.json", "baseline": "valid"},
    "phase_hint": "D.5",
    "has_handoff_contract": False,
    "phase": "D.5",
    "dcp_refs": ["WORKFLOW-DETAILED.md section 7"],
    "task_refs": ["T-008"],
    "autocast_template_version": "2.1.0",
    "autocast_asq_template_version": "1.0.0",
}


def invalid_value(valid: object) -> object:
    if type(valid) is bool:
        return "true"
    if isinstance(valid, str):
        return 42
    if isinstance(valid, list):
        return {"not": "a-list"}
    if isinstance(valid, dict):
        return ["not", "a-dict"]
    raise AssertionError(f"no invalid value for {valid!r}")


def test_policy_is_versioned_and_uses_only_four_classes() -> None:
    policy = get_policy()
    assert policy["version"] == "1.0.0"
    assert {entry["class"] for entry in policy["fields"]} == ENFORCEMENT_CLASSES
    assert all("D-35" in entry["rationale"] for entry in policy["fields"])


def test_closed_set_has_one_case_per_declared_field() -> None:
    assert set(get_declared_fields()) == set(VALID_VALUES)
    assert len(get_declared_fields()) == len(VALID_VALUES)


@pytest.mark.parametrize("field", sorted(VALID_VALUES))
def test_each_declared_field_has_a_valid_case(field: str) -> None:
    result = classify_fields({field: VALID_VALUES[field]})
    assert result[field] in ENFORCEMENT_CLASSES


@pytest.mark.parametrize("field", sorted(VALID_VALUES))
def test_each_declared_field_has_an_invalid_case(field: str) -> None:
    with pytest.raises(FrontmatterEnforcementError, match=field):
        classify_fields({field: invalid_value(VALID_VALUES[field])})


def test_unknown_field_fails_closed() -> None:
    with pytest.raises(FrontmatterEnforcementError, match="absent from policy"):
        classify_fields({"future_field_without_policy": "unsafe"})


def test_complete_valid_frontmatter_is_classified() -> None:
    assert set(classify_fields(VALID_VALUES)) == set(VALID_VALUES)
