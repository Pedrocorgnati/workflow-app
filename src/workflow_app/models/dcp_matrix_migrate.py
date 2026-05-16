"""Migration helper for DCP-COMMAND-MATRIX schema (st-04 / task-023).

``migrate_trail_schema(matrix_dict)`` converts a v1.0.0 dict to v1.0.1
in place AND returns it. The function is idempotent: running it again on an
already-migrated dict is a no-op.

v1.0.0 -> v1.0.1 changes:

1. ``schema_version`` bumped to ``"1.0.1"``.
2. Top-level ``trail_max_entries`` defaults to ``200`` if missing.
3. ``modules[id].artifacts`` gains two optional fields when missing:
   - ``meta_completeness_last_input_sha256: None``
   - ``meta_completeness_last_run_at: None``
4. Each ``TrailEntry`` (in ``modules[id].trail`` and
   ``modules[id].trail_archive[].entries``) is rewritten:
   - ``at`` -> ``ts``.
   - If ``details: {gate: X, ...}`` is present, promote any matching field to
     the top level (``bits_evaluated``, ``run_duration_ms``, ``input_sha256``,
     ``command_index``, ``from``/``to``, ``reason``, ``predicate``,
     ``action``) and drop ``details``.
   - A synthetic ``run_id`` is filled with a deterministic placeholder
     (``legacy-<gate>-<index>``) when missing.
"""

from __future__ import annotations

import uuid
from typing import Any, Mapping

__all__ = ["migrate_trail_schema"]


_PROMOTABLE_FIELDS = (
    "bits_evaluated",
    "bits_flipped_1_to_0",
    "bits_flipped_0_to_1",
    "run_duration_ms",
    "input_sha256",
    "command_index",
    "from",
    "to",
    "reason",
    "predicate",
    "action",
)


def _migrate_entry(entry: dict[str, Any], gate_hint: str, idx: int) -> dict[str, Any]:
    if "at" in entry and "ts" not in entry:
        entry["ts"] = entry.pop("at")

    details = entry.pop("details", None)
    if isinstance(details, Mapping):
        for key in _PROMOTABLE_FIELDS:
            if key in details and key not in entry:
                value = details[key]
                if key in {"bits_evaluated", "bits_flipped_1_to_0", "bits_flipped_0_to_1", "run_duration_ms", "command_index"}:
                    try:
                        entry[key] = int(value)
                    except (TypeError, ValueError):
                        entry[key] = value
                elif key in {"from", "to"}:
                    try:
                        entry[key] = int(value)
                    except (TypeError, ValueError):
                        entry[key] = value
                else:
                    entry[key] = value

    if "gate" not in entry:
        entry["gate"] = gate_hint
    if "run_id" not in entry:
        gate_label = entry.get("gate", gate_hint) or "unknown"
        entry["run_id"] = f"legacy-{gate_label}-{idx}"
    return entry


def migrate_trail_schema(matrix_dict: dict[str, Any]) -> dict[str, Any]:
    """Migrate a v1.0.0 matrix dict to v1.0.1 in place. Idempotent."""

    if not isinstance(matrix_dict, dict):
        raise TypeError("matrix_dict must be a dict (parsed JSON object)")

    matrix_dict["schema_version"] = "1.0.1"
    matrix_dict.setdefault("trail_max_entries", 200)

    modules = matrix_dict.get("modules") or {}
    for module in modules.values():
        if not isinstance(module, dict):
            continue
        artifacts = module.setdefault("artifacts", {})
        artifacts.setdefault("meta_completeness_last_input_sha256", None)
        artifacts.setdefault("meta_completeness_last_run_at", None)

        trail = module.get("trail") or []
        for idx, entry in enumerate(trail):
            if isinstance(entry, dict):
                _migrate_entry(entry, gate_hint=entry.get("gate", "unknown"), idx=idx)

        archive = module.get("trail_archive") or []
        for snap_idx, snapshot in enumerate(archive):
            if not isinstance(snapshot, dict):
                continue
            for idx, entry in enumerate(snapshot.get("entries") or []):
                if isinstance(entry, dict):
                    _migrate_entry(
                        entry,
                        gate_hint=entry.get("gate", "unknown"),
                        idx=snap_idx * 1000 + idx,
                    )

    return matrix_dict


def _legacy_run_id_for(prefix: str = "legacy") -> str:  # pragma: no cover
    """Convenience helper for tests that want a fresh UUID-shaped placeholder."""

    return f"{prefix}-{uuid.uuid4()}"
