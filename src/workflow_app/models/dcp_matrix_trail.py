"""Trail helpers for DCP-COMMAND-MATRIX (st-04 / task-023).

Public API:

- ``TTL_PER_GATE`` — canonical TTL per gate (seconds). Immutable mapping.
- ``compute_input_sha256(filter_list, command_index_serialized, enriched_meta)``
  — deterministic 64-hex hash for idempotency.
- ``check_idempotency(matrix, module_id, gate, input_sha256, ttl_seconds)``
  — ``True`` means caller MUST run (hash differs OR TTL expired OR first run);
  ``False`` means NO-OP.
- ``mark_gate_run(matrix, module_id, gate, input_sha256)`` — after a non-NO-OP
  run, persist ``{gate}_last_input_sha256`` and ``{gate}_last_run_at`` so the
  next call within TTL becomes a NO-OP.
- ``append_trail_entry(matrix, module_id, entry)`` — append a single
  ``TrailEntry``-shaped dict to ``modules[id].trail`` with cap-and-archive.
- ``record_summary(matrix, module_id, gate, run_id, stats)`` — write the
  per-run summary event (1 per gate run).

Cap canonical: ``matrix.trail_max_entries`` (default 200). When ``len(trail)``
reaches the cap, the whole list is moved to ``trail_archive`` as a
``TrailSnapshot`` and reset to ``[]``. Helpers are NOT thread-safe by
themselves — callers must own the cooperative file lock from
``runtime_context`` before mutating the matrix.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from types import MappingProxyType
from typing import Any, Iterable, Mapping

from .dcp_command_matrix import DcpCommandMatrix, TrailEntry, TrailSnapshot

__all__ = [
    "TTL_PER_GATE",
    "append_trail_entry",
    "record_summary",
    "check_idempotency",
    "mark_gate_run",
    "compute_input_sha256",
]


TTL_PER_GATE: Mapping[str, int] = MappingProxyType(
    {
        "congruence": 60,
        "temporality": 60,
        "meta-completeness": 300,
        "directive-injector": 60,
    }
)


def _now_utc() -> datetime:
    """Tz-aware UTC ``now`` — never use ``datetime.now()`` directly in helpers
    (naive vs aware subtraction is a known footgun, see task-023 R2)."""
    return datetime.now(timezone.utc)


def _gate_field_suffix(gate: str) -> str:
    return gate.replace("-", "_")


def _archive_trail_if_needed(matrix: DcpCommandMatrix, module_id: str) -> None:
    module = matrix.modules[module_id]
    cap = matrix.trail_max_entries
    if len(module.trail) >= cap:
        snapshot = TrailSnapshot(archived_at=_now_utc(), entries=list(module.trail))
        module.trail_archive.append(snapshot)
        module.trail = []


def _archive_trail_if_needed_dict(matrix: dict, module_id: str) -> None:
    """Dict-shaped variant of ``_archive_trail_if_needed`` for callers that load
    the matrix as plain ``json`` (e.g. ``dcp_*_check.py`` consumers)."""

    module = matrix["modules"][module_id]
    cap = matrix.get("trail_max_entries", 200)
    trail = module.setdefault("trail", [])
    if len(trail) >= cap:
        snapshot = {
            "archived_at": _now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "entries": list(trail),
        }
        module.setdefault("trail_archive", []).append(snapshot)
        module["trail"] = []


def append_trail_entry(
    matrix: Any,
    module_id: str,
    entry: Mapping[str, Any],
) -> None:
    """Append a single trail entry. Archive-on-cap is checked BEFORE append.

    Polymorphic dispatch: accepts both ``DcpCommandMatrix`` (pydantic, used by
    ``workflow-app``) and ``dict`` (used by ``.claude/commands/_lib/dcp_*.py``
    consumers that load the matrix via ``json.load``). In both branches, the
    entry is validated through ``TrailEntry.model_validate`` so schema
    invariants are enforced centrally regardless of caller shape.
    """

    validated = TrailEntry.model_validate(dict(entry))

    if isinstance(matrix, DcpCommandMatrix):
        _archive_trail_if_needed(matrix, module_id)
        matrix.modules[module_id].trail.append(validated)
        matrix.last_mutated_at = _now_utc()
        return

    if isinstance(matrix, dict):
        _archive_trail_if_needed_dict(matrix, module_id)
        matrix["modules"][module_id]["trail"].append(
            validated.model_dump(by_alias=True, mode="json", exclude_none=True)
        )
        matrix["last_mutated_at"] = _now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")
        return

    raise TypeError(
        f"append_trail_entry: matrix must be DcpCommandMatrix or dict, got "
        f"{type(matrix).__name__}"
    )


def record_summary(
    matrix: Any,
    module_id: str,
    gate: str,
    run_id: str,
    stats: Mapping[str, Any],
) -> None:
    """Write the per-run summary entry (1 per gate-run). Accepts both
    ``DcpCommandMatrix`` and ``dict`` via :func:`append_trail_entry` dispatch."""

    summary: dict[str, Any] = {
        "ts": _now_utc(),
        "gate": gate,
        "run_id": run_id,
        "bits_evaluated": stats.get("bits_evaluated"),
        "bits_flipped_1_to_0": stats.get("bits_flipped_1_to_0", 0),
        "bits_flipped_0_to_1": stats.get("bits_flipped_0_to_1", 0),
        "run_duration_ms": stats.get("run_duration_ms"),
        "input_sha256": stats.get("input_sha256"),
    }
    append_trail_entry(matrix, module_id, summary)


def compute_input_sha256(
    filter_list: Iterable[Any],
    command_index_serialized: Any,
    enriched_meta: Any,
) -> str:
    """Deterministic 64-hex SHA-256 over the canonical idempotency tuple.

    ``default=str`` lets ``datetime`` and other non-JSON values serialize
    without raising; ``sort_keys=True`` removes dict-ordering ambiguity.
    """

    payload = {
        "filter": list(filter_list),
        "command_index": command_index_serialized,
        "enriched_meta": enriched_meta,
    }
    blob = json.dumps(payload, sort_keys=True, default=str, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


def check_idempotency(
    matrix: DcpCommandMatrix,
    module_id: str,
    gate: str,
    input_sha256: str,
    ttl_seconds: int,
) -> bool:
    """Return ``True`` when the caller MUST run, ``False`` when it is a NO-OP.

    Rules:
    - First run for this (module, gate) — ``True``.
    - Hash differs from last persisted — ``True``.
    - TTL expired (elapsed >= ttl_seconds) — ``True``.
    - Otherwise (same hash AND within TTL) — ``False``.
    """

    module = matrix.modules[module_id]
    art = module.artifacts
    suffix = _gate_field_suffix(gate)
    last_hash = getattr(art, f"{suffix}_last_input_sha256", None)
    last_at = getattr(art, f"{suffix}_last_run_at", None)
    if last_hash is None or last_at is None:
        return True
    elapsed = (_now_utc() - last_at).total_seconds()
    if elapsed >= ttl_seconds:
        return True
    return last_hash != input_sha256


def mark_gate_run(
    matrix: DcpCommandMatrix,
    module_id: str,
    gate: str,
    input_sha256: str,
) -> None:
    """Persist (hash, now) after a non-NO-OP gate run so the next call within
    TTL with the same hash becomes a NO-OP via :func:`check_idempotency`."""

    module = matrix.modules[module_id]
    art = module.artifacts
    suffix = _gate_field_suffix(gate)
    setattr(art, f"{suffix}_last_input_sha256", input_sha256)
    setattr(art, f"{suffix}_last_run_at", _now_utc())
    matrix.last_mutated_at = _now_utc()
