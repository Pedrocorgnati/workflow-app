"""
Tests for SnapshotBuilder — idempotent pipeline state snapshots.

No Qt dependency required.
"""

from __future__ import annotations

import pytest

from workflow_app.remote.constants import SYNC_OUTPUT_LINES
from workflow_app.remote.protocol import MessageType
from workflow_app.remote.snapshot_builder import SnapshotBuilder

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def builder() -> SnapshotBuilder:
    return SnapshotBuilder()


# ── build_snapshot — structure ────────────────────────────────────────────────


def test_build_snapshot_returns_ws_envelope_type(builder):
    env = builder.build_snapshot()
    assert env.type == MessageType.PIPELINE_STATE.value


def test_build_snapshot_has_all_required_fields(builder):
    env = builder.build_snapshot()
    assert "pipeline_status" in env.payload
    assert "command_queue" in env.payload
    assert "output_history" in env.payload
    assert "pending_interaction" in env.payload


def test_initial_pipeline_status_is_idle(builder):
    env = builder.build_snapshot()
    assert env.payload["pipeline_status"] == "idle"


def test_initial_output_history_is_empty(builder):
    env = builder.build_snapshot()
    assert env.payload["output_history"] == []


def test_initial_command_queue_is_empty(builder):
    env = builder.build_snapshot()
    assert env.payload["command_queue"] == []


def test_initial_pending_interaction_is_none(builder):
    env = builder.build_snapshot()
    assert env.payload["pending_interaction"] is None


# ── add_output_line ───────────────────────────────────────────────────────────


def test_add_output_line_appears_in_snapshot(builder):
    builder.add_output_line("linha 1")
    builder.add_output_line("linha 2")
    env = builder.build_snapshot()
    assert "linha 1" in env.payload["output_history"]
    assert "linha 2" in env.payload["output_history"]


def test_buffer_circular_respects_maxlen(builder):
    """Adding more than SYNC_OUTPUT_LINES lines evicts the oldest entries."""
    for i in range(SYNC_OUTPUT_LINES + 50):
        builder.add_output_line(f"linha {i}")
    env = builder.build_snapshot()
    assert len(env.payload["output_history"]) == SYNC_OUTPUT_LINES
    # First 50 lines were evicted
    assert "linha 0" not in env.payload["output_history"]


def test_buffer_preserves_newest_lines(builder):
    for i in range(SYNC_OUTPUT_LINES + 10):
        builder.add_output_line(f"linha {i}")
    env = builder.build_snapshot()
    last_line = f"linha {SYNC_OUTPUT_LINES + 9}"
    assert last_line in env.payload["output_history"]


# ── update_pipeline_status ────────────────────────────────────────────────────


def test_update_pipeline_status_reflected_in_snapshot(builder):
    builder.update_pipeline_status("running")
    env = builder.build_snapshot()
    assert env.payload["pipeline_status"] == "running"


def test_update_pipeline_status_paused(builder):
    builder.update_pipeline_status("paused")
    env = builder.build_snapshot()
    assert env.payload["pipeline_status"] == "paused"


def test_update_pipeline_status_completed(builder):
    builder.update_pipeline_status("completed")
    env = builder.build_snapshot()
    assert env.payload["pipeline_status"] == "completed"


# ── update_command_queue ──────────────────────────────────────────────────────


def test_update_command_queue_reflected_in_snapshot(builder):
    queue = [
        {"index": 0, "label": "/prd-create", "status": "COMPLETED"},
        {"index": 1, "label": "/hld-create", "status": "RUNNING"},
    ]
    builder.update_command_queue(queue)
    env = builder.build_snapshot()
    assert len(env.payload["command_queue"]) == 2
    assert env.payload["command_queue"][1]["label"] == "/hld-create"


def test_update_command_queue_returns_copy(builder):
    """Mutating the returned list must not affect internal state."""
    queue = [{"index": 0, "label": "/cmd", "status": "PENDING"}]
    builder.update_command_queue(queue)
    env = builder.build_snapshot()
    env.payload["command_queue"].append({"extra": "item"})
    env2 = builder.build_snapshot()
    assert len(env2.payload["command_queue"]) == 1


# ── set_pending_interaction ───────────────────────────────────────────────────


def test_set_pending_interaction_appears_in_snapshot(builder):
    builder.set_pending_interaction({"prompt": "Confirma?", "options": ["sim", "não"]})
    env = builder.build_snapshot()
    assert env.payload["pending_interaction"]["prompt"] == "Confirma?"


def test_set_pending_interaction_none_clears_it(builder):
    builder.set_pending_interaction({"prompt": "Do it?"})
    builder.set_pending_interaction(None)
    env = builder.build_snapshot()
    assert env.payload["pending_interaction"] is None


# ── Idempotency ───────────────────────────────────────────────────────────────


def test_build_snapshot_idempotent_payloads(builder):
    """Two calls with unchanged state produce identical payloads."""
    builder.add_output_line("linha")
    builder.update_pipeline_status("running")
    env1 = builder.build_snapshot()
    env2 = builder.build_snapshot()
    assert env1.payload == env2.payload


def test_build_snapshot_unique_message_ids(builder):
    """Each snapshot has a different message_id by design."""
    env1 = builder.build_snapshot()
    env2 = builder.build_snapshot()
    assert env1.message_id != env2.message_id


def test_build_snapshot_does_not_modify_internal_state(builder):
    """build_snapshot() is pure — calling it must not change state."""
    builder.add_output_line("x")
    builder.update_pipeline_status("running")

    env1 = builder.build_snapshot()
    env2 = builder.build_snapshot()

    # Output history length unchanged
    assert len(env1.payload["output_history"]) == len(env2.payload["output_history"])
    assert env1.payload["pipeline_status"] == env2.payload["pipeline_status"]


# ── output_history returns copies ─────────────────────────────────────────────


def test_output_history_is_copy_not_reference(builder):
    """Mutating the returned list must not affect the internal buffer."""
    builder.add_output_line("original")
    env = builder.build_snapshot()
    env.payload["output_history"].append("injected")
    env2 = builder.build_snapshot()
    assert "injected" not in env2.payload["output_history"]
