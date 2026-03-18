"""
MessageSerializer — converts between Python dicts and JSON WebSocket frames.

Responsibilities:
- Add message_id (UUID v4) and timestamp to outbound messages.
- Translate PipelineStatus / CommandStatus values PT → EN (protocol uses English).
- Parse and validate inbound JSON frames.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# ── Status translation tables ─────────────────────────────────────────────────

_PIPELINE_STATUS_PT_TO_EN: dict[str, str] = {
    "criado": "CREATED",
    "nao_iniciado": "NOT_STARTED",
    "executando": "RUNNING",
    "pausado": "PAUSED",
    "concluido": "COMPLETED",
    "cancelado": "CANCELLED",
    "interrompido": "INTERRUPTED",
    "incerto": "UNCERTAIN",
}

_COMMAND_STATUS_PT_TO_EN: dict[str, str] = {
    "pendente": "PENDING",
    "executando": "RUNNING",
    "concluido": "COMPLETED",
    "erro": "ERROR",
    "pulado": "SKIPPED",
    "incerto": "UNCERTAIN",
}


class MessageSerializer:
    """Stateless serializer for the Workflow Mobile WebSocket protocol."""

    @staticmethod
    def serialize(msg_type: str, payload: dict) -> str:
        """Build a JSON envelope string ready to send over WebSocket.

        Adds message_id (UUID v4) and timestamp automatically.
        """
        envelope = {
            "message_id": str(uuid.uuid4()),
            "type": msg_type,
            "timestamp": datetime.now(tz=timezone.utc).isoformat(),
            "payload": payload,
        }
        return json.dumps(envelope, ensure_ascii=False)

    @staticmethod
    def deserialize(raw: str) -> tuple[str, str, str, dict] | None:
        """Parse a raw JSON string into (message_id, type, timestamp, payload).

        Returns None if the JSON is malformed or fields are missing.
        """
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("Remote: malformed JSON received (not parseable)")
            return None

        message_id = data.get("message_id", "")
        msg_type = data.get("type", "")
        timestamp = data.get("timestamp", "")
        payload = data.get("payload", {})

        if not isinstance(payload, dict):
            logger.warning("Remote: 'payload' is not a dict in message type=%s", msg_type)
            return None

        return message_id, msg_type, timestamp, payload

    @staticmethod
    def translate_pipeline_status(pt_value: str) -> str:
        """Convert a Portuguese PipelineStatus value to English protocol value."""
        return _PIPELINE_STATUS_PT_TO_EN.get(pt_value, pt_value.upper())

    @staticmethod
    def translate_command_status(pt_value: str) -> str:
        """Convert a Portuguese CommandStatus value to English protocol value."""
        return _COMMAND_STATUS_PT_TO_EN.get(pt_value, pt_value.upper())
