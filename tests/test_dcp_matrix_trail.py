"""Unit tests for ``workflow_app.models.dcp_matrix_trail`` (task-023 / ST019).

Covers:
- TrailEntry summary + flip shapes (round-trip with alias).
- Cap-and-archive on default 200 and custom ``trail_max_entries``.
- Idempotency: same hash within TTL -> NO-OP; different hash -> run;
  TTL expired -> run.
- ``compute_input_sha256`` determinism.
- ``record_summary`` appends with stats.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from workflow_app.models import dcp_matrix_trail as trail_mod
from workflow_app.models.dcp_command_matrix import (
    ArtifactsState,
    DcpCommandMatrix,
    ModuleEntry,
    TrailEntry,
)
from workflow_app.models.dcp_matrix_trail import (
    TTL_PER_GATE,
    append_trail_entry,
    check_idempotency,
    compute_input_sha256,
    mark_gate_run,
    record_summary,
)


def _empty_matrix(trail_max_entries: int = 200) -> DcpCommandMatrix:
    now = datetime.now(timezone.utc)
    return DcpCommandMatrix(
        schema_version="1.0.1",
        trail_max_entries=trail_max_entries,
        command_index=[],
        modules={
            "m1": ModuleEntry(filter=[], loop_multiplier={}),
        },
        created_at=now,
        created_by="test",
        last_mutated_at=now,
    )


def test_trail_entry_summary_shape() -> None:
    entry = TrailEntry.model_validate(
        {
            "ts": "2026-05-15T14:32:18Z",
            "gate": "congruence",
            "run_id": "uuid-1",
            "bits_evaluated": 412,
            "bits_flipped_1_to_0": 3,
            "bits_flipped_0_to_1": 0,
            "run_duration_ms": 892,
            "input_sha256": "abc",
        }
    )
    payload = json.loads(entry.model_dump_json(by_alias=True))
    assert payload["bits_evaluated"] == 412
    assert payload["bits_flipped_1_to_0"] == 3
    assert payload["input_sha256"] == "abc"
    assert payload["command_index"] is None


def test_trail_entry_flip_shape() -> None:
    entry = TrailEntry.model_validate(
        {
            "ts": "2026-05-15T14:32:18Z",
            "gate": "congruence",
            "run_id": "uuid-1",
            "command_index": 47,
            "from": 1,
            "to": 0,
            "reason": "predicate_false:x",
            "predicate": "x",
        }
    )
    assert entry.from_value == 1
    assert entry.to_value == 0
    dumped = json.loads(entry.model_dump_json(by_alias=True))
    assert dumped["from"] == 1
    assert dumped["to"] == 0
    assert "from_value" not in dumped
    assert "to_value" not in dumped


def test_cap_200_archives() -> None:
    matrix = _empty_matrix()
    for i in range(200):
        append_trail_entry(
            matrix,
            "m1",
            {"ts": datetime.now(timezone.utc), "gate": "congruence", "run_id": f"r-{i}"},
        )
    assert len(matrix.modules["m1"].trail) == 200
    assert matrix.modules["m1"].trail_archive == []

    append_trail_entry(
        matrix,
        "m1",
        {"ts": datetime.now(timezone.utc), "gate": "congruence", "run_id": "r-201"},
    )
    assert len(matrix.modules["m1"].trail_archive) == 1
    assert len(matrix.modules["m1"].trail_archive[0].entries) == 200
    assert len(matrix.modules["m1"].trail) == 1


def test_cap_custom_via_trail_max_entries() -> None:
    matrix = _empty_matrix(trail_max_entries=10)
    for i in range(10):
        append_trail_entry(
            matrix,
            "m1",
            {"ts": datetime.now(timezone.utc), "gate": "temporality", "run_id": f"r-{i}"},
        )
    assert len(matrix.modules["m1"].trail) == 10
    append_trail_entry(
        matrix,
        "m1",
        {"ts": datetime.now(timezone.utc), "gate": "temporality", "run_id": "r-overflow"},
    )
    assert len(matrix.modules["m1"].trail_archive) == 1
    assert len(matrix.modules["m1"].trail) == 1


def test_idempotency_same_hash_within_ttl_returns_false() -> None:
    matrix = _empty_matrix()
    mark_gate_run(matrix, "m1", "congruence", "hash-A")
    assert check_idempotency(matrix, "m1", "congruence", "hash-A", ttl_seconds=60) is False


def test_idempotency_different_hash_returns_true() -> None:
    matrix = _empty_matrix()
    mark_gate_run(matrix, "m1", "congruence", "hash-A")
    assert check_idempotency(matrix, "m1", "congruence", "hash-B", ttl_seconds=60) is True


def test_idempotency_ttl_expired_returns_true(monkeypatch: pytest.MonkeyPatch) -> None:
    matrix = _empty_matrix()
    mark_gate_run(matrix, "m1", "congruence", "hash-A")
    base = matrix.modules["m1"].artifacts.congruence_last_run_at
    assert base is not None

    def _future() -> datetime:
        return base + timedelta(seconds=70)

    monkeypatch.setattr(trail_mod, "_now_utc", _future)
    assert check_idempotency(matrix, "m1", "congruence", "hash-A", ttl_seconds=60) is True


def test_compute_input_sha256_determinista() -> None:
    h1 = compute_input_sha256([0, 1, 0], {"a": 1}, {"x": "y"})
    h2 = compute_input_sha256([0, 1, 0], {"a": 1}, {"x": "y"})
    h3 = compute_input_sha256([0, 1, 0], {"a": 1}, {"x": "z"})
    assert h1 == h2
    assert h1 != h3
    assert len(h1) == 64


def test_record_summary_appends_with_stats() -> None:
    matrix = _empty_matrix()
    record_summary(
        matrix,
        "m1",
        "congruence",
        run_id="run-1",
        stats={
            "bits_evaluated": 412,
            "bits_flipped_1_to_0": 3,
            "bits_flipped_0_to_1": 0,
            "run_duration_ms": 892,
            "input_sha256": "abc",
        },
    )
    last = matrix.modules["m1"].trail[-1]
    assert last.gate == "congruence"
    assert last.run_id == "run-1"
    assert last.bits_evaluated == 412
    assert last.bits_flipped_1_to_0 == 3
    assert last.run_duration_ms == 892
    assert last.input_sha256 == "abc"


def test_ttl_map_is_immutable() -> None:
    """``TTL_PER_GATE`` is wrapped in ``MappingProxyType`` so it cannot be
    mutated at runtime (AC-G4)."""

    with pytest.raises(TypeError):
        TTL_PER_GATE["congruence"] = 999  # type: ignore[index]


# ─────────────────────────────────────────────────────────────────────────────
# Polymorphic dispatch — dict-shaped matrix (consumers em .claude/commands/_lib)
# ─────────────────────────────────────────────────────────────────────────────


def _empty_matrix_dict(trail_max_entries: int = 200) -> dict:
    """Dict-shape compativel com os consumers que carregam matrix via json.load."""

    return {
        "schema_version": "1.0.1",
        "trail_max_entries": trail_max_entries,
        "command_index": [],
        "modules": {
            "m1": {
                "filter": [],
                "loop_multiplier": {},
                "trail": [],
                "trail_archive": [],
                "artifacts": {},
                "directive_boundaries": [],
            }
        },
        "created_at": "2026-05-16T00:00:00Z",
        "created_by": "test",
        "last_mutated_at": "2026-05-16T00:00:00Z",
    }


def test_append_trail_entry_dict_summary_shape() -> None:
    """Summary entry escrito via dict path mantem shape JSON estavel
    (sem null-fields, datetime serializado como string ISO)."""

    matrix = _empty_matrix_dict()
    append_trail_entry(
        matrix,
        "m1",
        {
            "ts": datetime(2026, 5, 16, 14, 0, 0, tzinfo=timezone.utc),
            "gate": "congruence",
            "run_id": "run-A",
            "bits_evaluated": 100,
            "bits_flipped_1_to_0": 2,
            "bits_flipped_0_to_1": 0,
            "run_duration_ms": 123,
            "input_sha256": "deadbeef",
        },
    )
    assert len(matrix["modules"]["m1"]["trail"]) == 1
    entry = matrix["modules"]["m1"]["trail"][0]
    # exclude_none=True garante que campos flip-only (command_index, from, to)
    # nao aparecem em summary entries.
    assert "command_index" not in entry
    assert "from" not in entry
    assert "to" not in entry
    assert entry["gate"] == "congruence"
    assert entry["bits_evaluated"] == 100
    assert entry["input_sha256"] == "deadbeef"
    # last_mutated_at bumped no top-level.
    assert matrix["last_mutated_at"].endswith("Z")


def test_append_trail_entry_dict_flip_shape() -> None:
    """Flip entry escrito via dict path preserva from/to (aliases pydantic)
    e nao polui com summary-only fields."""

    matrix = _empty_matrix_dict()
    append_trail_entry(
        matrix,
        "m1",
        {
            "ts": datetime(2026, 5, 16, 14, 0, 0, tzinfo=timezone.utc),
            "gate": "temporality",
            "run_id": "run-B",
            "command_index": 42,
            "from": 1,
            "to": 0,
            "reason": "rule_violated:R3 [cmd=/mkt:portfolio-add]",
            "predicate": "R3",
        },
    )
    entry = matrix["modules"]["m1"]["trail"][0]
    assert entry["from"] == 1
    assert entry["to"] == 0
    assert entry["command_index"] == 42
    assert entry["predicate"] == "R3"
    # Summary-only fields ausentes em flip.
    assert "bits_evaluated" not in entry
    assert "run_duration_ms" not in entry


def test_append_trail_entry_dict_cap_archives() -> None:
    """Cap-and-archive funciona via dict path: ao atingir trail_max_entries
    o trail e movido para trail_archive como snapshot."""

    matrix = _empty_matrix_dict(trail_max_entries=5)
    for i in range(5):
        append_trail_entry(
            matrix,
            "m1",
            {
                "ts": datetime(2026, 5, 16, 14, 0, i, tzinfo=timezone.utc),
                "gate": "congruence",
                "run_id": f"r-{i}",
            },
        )
    assert len(matrix["modules"]["m1"]["trail"]) == 5
    assert matrix["modules"]["m1"]["trail_archive"] == []

    # 6th append triggers archive (check happens BEFORE append).
    append_trail_entry(
        matrix,
        "m1",
        {
            "ts": datetime(2026, 5, 16, 14, 0, 5, tzinfo=timezone.utc),
            "gate": "congruence",
            "run_id": "r-overflow",
        },
    )
    assert len(matrix["modules"]["m1"]["trail_archive"]) == 1
    assert len(matrix["modules"]["m1"]["trail_archive"][0]["entries"]) == 5
    assert matrix["modules"]["m1"]["trail_archive"][0]["archived_at"].endswith("Z")
    assert len(matrix["modules"]["m1"]["trail"]) == 1
    assert matrix["modules"]["m1"]["trail"][0]["run_id"] == "r-overflow"


def test_append_trail_entry_dict_uses_default_cap_when_missing() -> None:
    """Quando trail_max_entries esta ausente do dict, default canonico (200)
    e aplicado pelo helper _archive_trail_if_needed_dict."""

    matrix = _empty_matrix_dict()
    matrix.pop("trail_max_entries")  # simula matriz legacy sem campo
    # Pre-popula 199 — proximo append NAO deve arquivar ainda (199 < 200).
    matrix["modules"]["m1"]["trail"] = [
        {"ts": "2026-05-16T14:00:00Z", "gate": "congruence", "run_id": f"r-{i}"}
        for i in range(199)
    ]
    append_trail_entry(
        matrix,
        "m1",
        {
            "ts": datetime(2026, 5, 16, 14, 0, 0, tzinfo=timezone.utc),
            "gate": "congruence",
            "run_id": "r-200",
        },
    )
    assert len(matrix["modules"]["m1"]["trail"]) == 200
    assert matrix["modules"]["m1"]["trail_archive"] == []


def test_append_trail_entry_rejects_invalid_matrix_type() -> None:
    """API levanta TypeError para shapes nao suportados (lista, tuple, etc).

    Schema validation roda antes da dispatch — entry precisa ser canonica
    para que o erro seja sobre o matrix shape, nao sobre o payload.
    """

    valid_entry = {
        "ts": datetime(2026, 5, 16, 14, 0, 0, tzinfo=timezone.utc),
        "gate": "congruence",
        "run_id": "r-1",
    }
    with pytest.raises(TypeError, match="must be DcpCommandMatrix or dict"):
        append_trail_entry(["not", "a", "matrix"], "m1", valid_entry)


def test_record_summary_dict_dispatch() -> None:
    """record_summary delega para append_trail_entry e suporta dict
    polimorficamente."""

    matrix = _empty_matrix_dict()
    record_summary(
        matrix,
        "m1",
        "meta-completeness",
        run_id="run-meta-1",
        stats={
            "bits_evaluated": 50,
            "bits_flipped_1_to_0": 0,
            "bits_flipped_0_to_1": 0,
            "run_duration_ms": 42,
            "input_sha256": "cafebabe",
        },
    )
    assert len(matrix["modules"]["m1"]["trail"]) == 1
    entry = matrix["modules"]["m1"]["trail"][0]
    assert entry["gate"] == "meta-completeness"
    assert entry["run_id"] == "run-meta-1"
    assert entry["bits_evaluated"] == 50
    assert entry["input_sha256"] == "cafebabe"
