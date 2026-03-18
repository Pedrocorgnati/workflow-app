"""
DTOs (data transfer objects) for the Workflow Mobile WebSocket protocol.

All classes are pure Python dataclasses — no Qt dependency.
The MessageSerializer converts between these objects and JSON strings.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# ── Queue / Snapshot ─────────────────────────────────────────────────────────
# NOTE: WsEnvelope is defined in protocol.py (canonical location)


@dataclass
class QueueItem:
    """Single command entry in the pipeline queue snapshot."""

    index: int    # 0-based position in queue
    label: str    # display name, e.g. "/prd-create"
    status: str   # English CommandStatus value (PENDING, RUNNING, …)


@dataclass
class InteractionPayload:
    """Describes a pending or resolved interactive prompt."""

    request_id: str           # UUID v4
    interaction_type: str     # "text_input" | "permission"
    prompt: str               # human-readable question
    status: str               # "pending" | "resolved" | "resolved_elsewhere"
    metadata: dict = field(default_factory=dict)


@dataclass
class PipelineSnapshot:
    """Full pipeline state sent on sync_request or status changes."""

    pipeline_status: str                    # English PipelineStatus value
    current_index: int
    queue: list[QueueItem] = field(default_factory=list)
    output_buffer: str = ""                 # last SYNC_OUTPUT_LINES lines
    pending_interaction: InteractionPayload | None = None


# ── Inbound payloads (Android → PC) ─────────────────────────────────────────


@dataclass
class ControlPayload:
    """Payload for a "control" message."""

    action: str   # "play" | "pause" | "skip"


@dataclass
class InteractionResponsePayload:
    """Payload for an "interaction_response" message."""

    request_id: str
    value: str   # free text or "approve" | "deny"


# ── Outbound payloads (PC → Android) ────────────────────────────────────────


@dataclass
class OutputTruncatedPayload:
    """Signals that some output lines were dropped."""

    lines_skipped: int


@dataclass
class ErrorPayload:
    """Error notification sent to Android."""

    code: str
    message: str
    ref_message_id: str | None = None
