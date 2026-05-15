"""Tests for structured flag specs in quick_templates.py.

Validates migration from argument_hint string parsing to FlagSpec-based
declarations for /loop, /daily-loop, /daily and /study.
"""

from __future__ import annotations

import pytest

from workflow_app.domain import CommandSpec, FlagSpec
from workflow_app.templates.quick_templates import COMMAND_FLAG_SPECS


# ---------------------------------------------------------------------------
# Migration coverage
# ---------------------------------------------------------------------------


def test_loop_spec_exists():
    assert "/loop" in COMMAND_FLAG_SPECS


def test_daily_loop_spec_exists():
    assert "/daily-loop" in COMMAND_FLAG_SPECS


def test_daily_spec_exists():
    assert "/daily" in COMMAND_FLAG_SPECS


def test_study_spec_exists():
    assert "/study" in COMMAND_FLAG_SPECS


# ---------------------------------------------------------------------------
# /loop flags
# ---------------------------------------------------------------------------


def test_loop_flags_with_value():
    spec = COMMAND_FLAG_SPECS["/loop"]
    names = [f.name for f in spec.flags_with_value]
    assert "task" in names
    assert "cmd" in names
    assert "cmd-single" in names
    assert "both" in names
    assert "name" in names


def test_loop_name_flag_has_slug_placeholder():
    spec = COMMAND_FLAG_SPECS["/loop"]
    name_flag = next(f for f in spec.flags_with_value if f.name == "name")
    assert name_flag.placeholder == "slug"


def test_loop_no_literal_angle_brackets_in_placeholders():
    """Placeholder text must NOT contain literal < or > characters."""
    spec = COMMAND_FLAG_SPECS["/loop"]
    for flag in spec.flags_with_value:
        assert "<" not in flag.placeholder, f"flag {flag.name} has < in placeholder"
        assert ">" not in flag.placeholder, f"flag {flag.name} has > in placeholder"


# ---------------------------------------------------------------------------
# /study flags
# ---------------------------------------------------------------------------


def test_study_mode_flag_is_enum():
    spec = COMMAND_FLAG_SPECS["/study"]
    mode_flag = next(f for f in spec.flags_with_value if f.name == "mode")
    assert mode_flag.options == ["--simple", "--deep", "--heavy"]


# ---------------------------------------------------------------------------
# Serialization guard
# ---------------------------------------------------------------------------


def _serialize(spec: CommandSpec, values: dict[str, str]) -> str:
    """Build command line from spec + provided values."""
    parts = [spec.name]
    for flag in spec.flags_with_value:
        val = values.get(flag.name, "").strip()
        if not val:
            continue
        if flag.options and val not in flag.options:
            continue
        parts.append(f"--{flag.name} {val}")
    for boolean in spec.flags_boolean:
        if boolean in values.get("_booleans", []):
            parts.append(boolean)
    return " ".join(parts)


def test_serialize_loop_no_angle_brackets_when_filled():
    spec = COMMAND_FLAG_SPECS["/loop"]
    cmd = _serialize(spec, {"task": "tasks.md", "name": "my-loop"})
    assert "<" not in cmd
    assert ">" not in cmd
    assert cmd == "/loop --task tasks.md --name my-loop"


def test_serialize_loop_omits_empty_flags():
    spec = COMMAND_FLAG_SPECS["/loop"]
    cmd = _serialize(spec, {"task": "tasks.md"})
    assert "name" not in cmd
    assert "--task tasks.md" in cmd


def test_serialize_study_enum_mode():
    spec = COMMAND_FLAG_SPECS["/study"]
    cmd = _serialize(spec, {"mode": "--deep", "name": "research-1"})
    assert "<" not in cmd
    assert ">" not in cmd
    assert "--deep" in cmd
