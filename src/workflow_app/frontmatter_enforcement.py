"""Typed frontmatter enforcement backed by a versioned YAML policy."""

from __future__ import annotations

import copy
from functools import lru_cache
from pathlib import Path
from typing import Any, Mapping

import yaml


POLICY_PATH = Path(__file__).with_name("frontmatter_enforcement_policy.yaml")
POLICY_VERSION = "1.0.0"
ENFORCEMENT_CLASSES = {
    "native",
    "adapter-enforced",
    "in-band-only",
    "unsupported",
}


class FrontmatterEnforcementError(ValueError):
    """Raised when policy or frontmatter fails closed."""


_TYPE_MAP: dict[str, type[Any] | tuple[type[Any], ...]] = {
    "str": str,
    "bool": bool,
    "list": list,
    "dict": dict,
    "null": type(None),
}


@lru_cache(maxsize=1)
def _load_policy() -> dict[str, Any]:
    try:
        raw = yaml.safe_load(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise FrontmatterEnforcementError(f"cannot load enforcement policy: {exc}") from exc
    if not isinstance(raw, dict) or raw.get("version") != POLICY_VERSION:
        raise FrontmatterEnforcementError(
            f"policy version must be {POLICY_VERSION!r}"
        )
    entries = raw.get("fields")
    if not isinstance(entries, list) or not entries:
        raise FrontmatterEnforcementError("policy fields must be a non-empty list")
    seen: set[str] = set()
    for position, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise FrontmatterEnforcementError(f"policy field #{position} must be an object")
        field = entry.get("field")
        class_name = entry.get("class")
        rationale = entry.get("rationale")
        types = entry.get("types")
        if not isinstance(field, str) or not field:
            raise FrontmatterEnforcementError(f"policy field #{position} has invalid name")
        if field in seen:
            raise FrontmatterEnforcementError(f"duplicate policy field: {field}")
        seen.add(field)
        if class_name not in ENFORCEMENT_CLASSES:
            raise FrontmatterEnforcementError(
                f"field {field} has invalid enforcement class: {class_name!r}"
            )
        if not isinstance(rationale, str) or "D-35" not in rationale:
            raise FrontmatterEnforcementError(
                f"field {field} must have a D-35 rationale"
            )
        if not isinstance(types, list) or not types or any(t not in _TYPE_MAP for t in types):
            raise FrontmatterEnforcementError(
                f"field {field} has invalid declared types: {types!r}"
            )
    return raw


def get_policy() -> dict[str, Any]:
    """Return a defensive copy of the validated versioned policy."""

    return copy.deepcopy(_load_policy())


def get_declared_fields() -> list[str]:
    """Return every field in policy order for closed-set tests."""

    return [entry["field"] for entry in _load_policy()["fields"]]


def _entry_by_field() -> dict[str, dict[str, Any]]:
    return {entry["field"]: entry for entry in _load_policy()["fields"]}


def _matches_declared_type(value: object, names: list[str]) -> bool:
    for name in names:
        expected = _TYPE_MAP[name]
        if name == "bool":
            if type(value) is bool:
                return True
        elif isinstance(value, expected):
            return True
    return False


def classify_fields(frontmatter_dict: Mapping[str, object]) -> dict[str, str]:
    """Validate and classify present fields, rejecting unknowns fail-closed."""

    if not isinstance(frontmatter_dict, Mapping):
        raise FrontmatterEnforcementError("frontmatter must be a mapping")
    entries = _entry_by_field()
    unknown = sorted(set(frontmatter_dict) - set(entries))
    if unknown:
        raise FrontmatterEnforcementError(f"fields absent from policy: {unknown}")
    classified: dict[str, str] = {}
    for field, value in frontmatter_dict.items():
        entry = entries[field]
        if not _matches_declared_type(value, entry["types"]):
            raise FrontmatterEnforcementError(
                f"field {field} expected one of {entry['types']}, got {type(value).__name__}"
            )
        classified[field] = entry["class"]
    return classified
