"""
Tests for MessageSerializer (no Qt dependency required).
"""

from __future__ import annotations

import json

import pytest

from workflow_app.remote.message_serializer import MessageSerializer


@pytest.fixture
def serializer() -> MessageSerializer:
    return MessageSerializer()


# ── serialize ─────────────────────────────────────────────────────────────────


def test_serialize_returns_valid_json(serializer):
    raw = serializer.serialize("pipeline_state", {"key": "value"})
    data = json.loads(raw)
    assert data["type"] == "pipeline_state"
    assert data["payload"] == {"key": "value"}


def test_serialize_adds_message_id(serializer):
    raw = serializer.serialize("sync_request", {})
    data = json.loads(raw)
    assert "message_id" in data
    assert len(data["message_id"]) == 36  # UUID format


def test_serialize_adds_timestamp(serializer):
    raw = serializer.serialize("control", {"action": "pause"})
    data = json.loads(raw)
    assert "timestamp" in data
    assert data["timestamp"]


def test_serialize_unique_message_ids(serializer):
    raw1 = serializer.serialize("ping", {})
    raw2 = serializer.serialize("ping", {})
    assert json.loads(raw1)["message_id"] != json.loads(raw2)["message_id"]


# ── deserialize ───────────────────────────────────────────────────────────────


def test_deserialize_valid_envelope(serializer):
    envelope = json.dumps({
        "message_id": "abc-123",
        "type": "control",
        "timestamp": "2026-01-01T00:00:00Z",
        "payload": {"action": "pause"},
    })
    result = serializer.deserialize(envelope)
    assert result is not None
    message_id, msg_type, timestamp, payload = result
    assert message_id == "abc-123"
    assert msg_type == "control"
    assert payload == {"action": "pause"}


def test_deserialize_malformed_json_returns_none(serializer):
    assert serializer.deserialize("{not valid json") is None


def test_deserialize_missing_payload_defaults_to_empty_dict(serializer):
    envelope = json.dumps({
        "message_id": "x",
        "type": "sync_request",
        "timestamp": "t",
    })
    result = serializer.deserialize(envelope)
    assert result is not None
    _, _, _, payload = result
    assert payload == {}


def test_deserialize_non_dict_payload_returns_none(serializer):
    envelope = json.dumps({
        "message_id": "x",
        "type": "bad",
        "timestamp": "t",
        "payload": "not a dict",
    })
    assert serializer.deserialize(envelope) is None


# ── Status translations ───────────────────────────────────────────────────────


def test_translate_pipeline_status_known(serializer):
    assert serializer.translate_pipeline_status("pausado") == "PAUSED"
    assert serializer.translate_pipeline_status("executando") == "RUNNING"
    assert serializer.translate_pipeline_status("concluido") == "COMPLETED"
    assert serializer.translate_pipeline_status("cancelado") == "CANCELLED"


def test_translate_pipeline_status_unknown_returns_uppercase(serializer):
    assert serializer.translate_pipeline_status("foo") == "FOO"


def test_translate_command_status_known(serializer):
    assert serializer.translate_command_status("pendente") == "PENDING"
    assert serializer.translate_command_status("erro") == "ERROR"
    assert serializer.translate_command_status("pulado") == "SKIPPED"


def test_translate_command_status_unknown_returns_uppercase(serializer):
    assert serializer.translate_command_status("xyz") == "XYZ"
