"""
Protocol enums and types for the Workflow Mobile WebSocket protocol.

These are the *formal* protocol definitions for the wire format.
- Enum values are always English strings (Android mirrors them in RemoteConstants.kt).
- CommandStatus / PipelineStatus here are PROTOCOL enums (EN values).
  Do NOT confuse with workflow_app.domain.CommandStatus / PipelineStatus (PT values).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

# ── Message types ─────────────────────────────────────────────────────────────


class MessageType(str, Enum):
    """All valid message type strings in both directions."""

    # PC → Android
    OUTPUT_CHUNK = "output_chunk"
    OUTPUT_TRUNCATED = "output_truncated"
    PIPELINE_STATE = "pipeline_state"
    INTERACTION_REQUEST = "interaction_request"
    INTERACTIVE_MODE_ENDED = "interactive_mode_ended"
    ERROR = "error"
    CONTROL_ACK = "control_ack"
    # Android → PC
    CONTROL = "control"
    INTERACTION_RESPONSE = "interaction_response"
    SYNC_REQUEST = "sync_request"


class ControlAction(str, Enum):
    """Actions a client can send in a 'control' message."""

    PLAY = "play"
    PAUSE = "pause"
    SKIP = "skip"


class ResponseType(str, Enum):
    """Possible answer types for an interaction_response message."""

    TEXT = "text"
    YES = "yes"
    NO = "no"
    CANCEL = "cancel"


# ── Protocol-level status enums (English values) ─────────────────────────────


class CommandStatus(str, Enum):
    """CommandStatus for the WebSocket remote protocol (EN values).

    Distinct from workflow_app.domain.CommandStatus which uses PT values.
    """

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class PipelineStatus(str, Enum):
    """PipelineStatus for the WebSocket remote protocol (EN values).

    Distinct from workflow_app.domain.PipelineStatus which uses PT values.
    """

    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    WAITING_INTERACTION = "waiting_interaction"
    INTERACTIVE_MODE = "interactive_mode"


# ── Envelope ──────────────────────────────────────────────────────────────────


@dataclass
class WsEnvelope:
    """Top-level wrapper for every message in both directions.

    Provides to_dict/from_dict helpers for JSON serialisation.
    """

    type: str  # MessageType.value
    payload: dict[str, Any]
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "message_id": self.message_id,
            "type": self.type,
            "timestamp": self.timestamp,
            "payload": self.payload,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WsEnvelope:
        message_id = data["message_id"]
        if message_id is None:
            raise ValueError("message_id cannot be None")
        type_str = data["type"]
        valid_types = {t.value for t in MessageType}
        if type_str not in valid_types:
            raise ValueError(f"Unknown message type: {type_str!r}")
        payload = data.get("payload", {})
        if payload is None or not isinstance(payload, dict):
            raise TypeError(
                f"payload must be a dict, got {type(payload).__name__}"
            )
        return cls(
            message_id=message_id,
            type=type_str,
            timestamp=data["timestamp"],
            payload=payload,
        )

    def validate_payload(self) -> None:
        """Validate that payload contains required fields for this message type.

        Raises KeyError if a required field is missing from the payload.
        Raises ValueError if a field has an incompatible type.
        """
        payload = self.payload
        t = self.type

        if t == MessageType.OUTPUT_CHUNK.value:
            if "lines" not in payload:
                raise KeyError("output_chunk payload missing required field: 'lines'")
            if not isinstance(payload["lines"], list):
                raise ValueError("output_chunk 'lines' must be a list")
        elif t == MessageType.OUTPUT_TRUNCATED.value:
            if "lines_omitted" not in payload:
                raise KeyError("output_truncated payload missing required field: 'lines_omitted'")
        elif t == MessageType.PIPELINE_STATE.value:
            if "status" not in payload:
                raise KeyError("pipeline_state payload missing required field: 'status'")
            if "command_queue" not in payload:
                raise KeyError("pipeline_state payload missing required field: 'command_queue'")
        elif t == MessageType.INTERACTION_REQUEST.value:
            if "prompt" not in payload:
                raise KeyError("interaction_request payload missing required field: 'prompt'")
        elif t == MessageType.ERROR.value:
            if "message" not in payload:
                raise KeyError("error payload missing required field: 'message'")
        elif t == MessageType.CONTROL_ACK.value:
            if "action" not in payload:
                raise KeyError("control_ack payload missing required field: 'action'")
            if "accepted" not in payload:
                raise KeyError("control_ack payload missing required field: 'accepted'")
        elif t == MessageType.CONTROL.value:
            if "action" not in payload:
                raise KeyError("control payload missing required field: 'action'")
        elif t == MessageType.INTERACTION_RESPONSE.value:
            if "text" not in payload:
                raise KeyError("interaction_response payload missing required field: 'text'")
            if "response_type" not in payload:
                raise KeyError(
                    "interaction_response payload missing required field: 'response_type'"
                )
        # interactive_mode_ended and sync_request: empty payload {} is valid


# ── Whitelists (deny-by-default) ──────────────────────────────────────────────

# Types the PC server accepts from an Android client
PC_ACCEPTED_TYPES: frozenset = frozenset(
    {
        MessageType.SYNC_REQUEST,
        MessageType.CONTROL,
        MessageType.INTERACTION_RESPONSE,
    }
)

# Types the Android client accepts from the PC server
ANDROID_ACCEPTED_TYPES: frozenset = frozenset(
    {
        MessageType.OUTPUT_CHUNK,
        MessageType.OUTPUT_TRUNCATED,
        MessageType.PIPELINE_STATE,
        MessageType.INTERACTION_REQUEST,
        MessageType.INTERACTIVE_MODE_ENDED,
        MessageType.ERROR,
        MessageType.CONTROL_ACK,
    }
)


def is_valid_client_message(msg_type: str) -> bool:
    """Return True if *msg_type* is accepted by the PC server from the client."""
    return msg_type in {t.value for t in PC_ACCEPTED_TYPES}
