"""workflow_app.models - pydantic models for DCP artifacts.

T-035: `delivery.json` v1 reader (model `Delivery`).
Consumers: T-036 Kanban, T-037 lock-aware UI, T-038 per-module view,
T-050 DCP cleanup + Build/Specific-Flow buttons.

task-023: `dcp_command_matrix.py` (matrix v1.0.1) + `dcp_matrix_trail.py`
(trail+idempotency helpers) + `dcp_matrix_migrate.py` (v1.0.0 -> v1.0.1).
"""

from __future__ import annotations

from .dcp_command_matrix import (
    ArtifactsState,
    BitLiteral,
    CommandIndexEntry,
    CommandRef,
    DcpCommandMatrix,
    DirectiveBoundary,
    EffortLiteral,
    FilterTrailEntry,
    FoldInRules,
    InteractionLiteral,
    ModelLiteral,
    ModuleEntry,
    PhaseLiteral,
    TrailEntry,
    TrailGateLiteral,
    TrailSnapshot,
    WithDialect,
)
from .dcp_matrix_migrate import migrate_trail_schema
from .dcp_matrix_trail import (
    TTL_PER_GATE,
    append_trail_entry,
    check_idempotency,
    compute_input_sha256,
    mark_gate_run,
    record_summary,
)
from .delivery import (
    Delivery,
    DeliveryInvariantWarning,
    ExecutionArtifact,
    ExecutionMode,
    FilesTouchedEvent,
    HistoryEntry,
    Locks,
    Metadata,
    ModuleArtifacts,
    ModuleFlags,
    ModuleState,
    ModuleStateLiteral,
    ModuleType,
    Owner,
    Project,
    QaArtifact,
    ReworkPhase,
    ReworkTarget,
    Skeleton,
)

__all__ = [
    # delivery.json v1
    "Delivery",
    "DeliveryInvariantWarning",
    "ExecutionArtifact",
    "ExecutionMode",
    "FilesTouchedEvent",
    "HistoryEntry",
    "Locks",
    "Metadata",
    "ModuleArtifacts",
    "ModuleFlags",
    "ModuleState",
    "ModuleStateLiteral",
    "ModuleType",
    "Owner",
    "Project",
    "QaArtifact",
    "ReworkPhase",
    "ReworkTarget",
    "Skeleton",
    # DCP-COMMAND-MATRIX v1.0.1
    "ArtifactsState",
    "BitLiteral",
    "CommandIndexEntry",
    "CommandRef",
    "DcpCommandMatrix",
    "DirectiveBoundary",
    "EffortLiteral",
    "FilterTrailEntry",
    "FoldInRules",
    "InteractionLiteral",
    "ModelLiteral",
    "ModuleEntry",
    "PhaseLiteral",
    "TrailEntry",
    "TrailGateLiteral",
    "TrailSnapshot",
    "WithDialect",
    # Trail helpers
    "TTL_PER_GATE",
    "append_trail_entry",
    "check_idempotency",
    "compute_input_sha256",
    "mark_gate_run",
    "record_summary",
    # Migration
    "migrate_trail_schema",
]
