"""Unit tests for workflow_app.remote.protocol."""

import json

from workflow_app.remote.protocol import (
    ANDROID_ACCEPTED_TYPES,
    PC_ACCEPTED_TYPES,
    CommandStatus,
    MessageType,
    PipelineStatus,
    WsEnvelope,
    is_valid_client_message,
)


def test_message_type_count():
    assert len(MessageType) == 10


def test_message_type_values():
    values = {t.value for t in MessageType}
    assert "output_chunk" in values
    assert "sync_request" in values
    assert "control_ack" in values


def test_ws_envelope_to_dict():
    env = WsEnvelope(type=MessageType.OUTPUT_CHUNK.value, payload={"text": "hello"})
    d = env.to_dict()
    assert set(d.keys()) == {"message_id", "type", "timestamp", "payload"}
    json.dumps(d)  # must be JSON-serialisable


def test_ws_envelope_round_trip():
    env = WsEnvelope(type=MessageType.SYNC_REQUEST.value, payload={})
    restored = WsEnvelope.from_dict(env.to_dict())
    assert restored.message_id == env.message_id
    assert restored.type == env.type
    assert restored.timestamp == env.timestamp


def test_ws_envelope_auto_fields():
    env = WsEnvelope(type=MessageType.CONTROL.value, payload={})
    assert env.message_id  # non-empty UUID
    assert env.timestamp   # non-empty ISO timestamp


def test_whitelist_accept():
    assert is_valid_client_message("sync_request")
    assert is_valid_client_message("control")
    assert is_valid_client_message("interaction_response")


def test_whitelist_reject():
    assert not is_valid_client_message("output_chunk")
    assert not is_valid_client_message("pipeline_state")
    assert not is_valid_client_message("unknown_type")


def test_pc_accepted_types_count():
    assert len(PC_ACCEPTED_TYPES) == 3


def test_android_accepted_types_count():
    assert len(ANDROID_ACCEPTED_TYPES) == 7


def test_command_status_values_english():
    values = {s.value for s in CommandStatus}
    assert "pending" in values
    assert "running" in values
    assert "completed" in values
    assert "failed" in values
    assert "skipped" in values
    assert "cancelled" in values
    assert len(CommandStatus) == 6


def test_pipeline_status_values_english():
    assert len(PipelineStatus) == 8
    assert "idle" in {s.value for s in PipelineStatus}
    assert "waiting_interaction" in {s.value for s in PipelineStatus}


def test_no_conflict_with_domain():
    """Protocol enums must not conflict with domain.py (which uses PT values)."""
    from workflow_app.domain import CommandStatus as DomainCS
    from workflow_app.remote.protocol import CommandStatus as ProtoCS

    assert DomainCS is not ProtoCS
    assert "pendente" in {s.value for s in DomainCS}
    assert "pending" in {s.value for s in ProtoCS}


def test_barrel_import_from_package():
    from workflow_app.remote import MessageType as MT  # noqa: F401

    assert MT.OUTPUT_CHUNK.value == "output_chunk"
