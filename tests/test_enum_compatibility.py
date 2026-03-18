"""Testes de compatibilidade de enums e formatos entre Python e Kotlin — TASK-2.

Valida:
- Valores exatos de todos os enums do protocolo (tabela canônica)
- Formato UUID v4 gerado pelo Python (uuid.uuid4())
- Forward compatibility (campos extras ignorados, não vazam para to_dict())
- Compatibilidade de formato de timestamp entre plataformas (Z vs +00:00)
"""

import re
import uuid
from datetime import datetime

import pytest

from workflow_app.remote.protocol import (
    CommandStatus,
    ControlAction,
    MessageType,
    PipelineStatus,
    ResponseType,
    WsEnvelope,
)

# ── Tabela canônica do protocolo (fonte de verdade Python) ───────────────────
#
# Nota de compatibilidade com o lado Kotlin:
# - WsMessageType contém os 10 tipos abaixo + tipos internos (PING, PONG, CONNECTED etc.)
# - ControlAction no Kotlin tem 4 valores (PLAY, PAUSE, SKIP, RESUME) — RESUME é extensão Android
# - CommandStatus não existe como enum Kotlin; o lado Android usa strings
# - PipelineViewState (Kotlin) espelha PipelineStatus com os mesmos 8 valores

PROTOCOL_ENUMS = {
    "MessageType": [
        "output_chunk",
        "output_truncated",
        "pipeline_state",
        "interaction_request",
        "interactive_mode_ended",
        "error",
        "control_ack",
        "control",
        "interaction_response",
        "sync_request",
    ],
    "CommandStatus": ["pending", "running", "completed", "failed", "skipped", "cancelled"],
    "PipelineStatus": [
        "idle",
        "running",
        "paused",
        "completed",
        "failed",
        "cancelled",
        "waiting_interaction",
        "interactive_mode",
    ],
    "ControlAction": ["play", "pause", "skip"],
    "ResponseType": ["text", "yes", "no", "cancel"],
}

ENUM_CLASSES = {
    "MessageType": MessageType,
    "CommandStatus": CommandStatus,
    "PipelineStatus": PipelineStatus,
    "ControlAction": ControlAction,
    "ResponseType": ResponseType,
}


# ── ST001: Valores exatos dos enums ──────────────────────────────────────────


@pytest.mark.parametrize("enum_name,expected_values", PROTOCOL_ENUMS.items())
def test_enum_has_exactly_expected_values(enum_name, expected_values):
    """Enum deve ter exatamente os valores listados — nem mais, nem menos."""
    enum_cls = ENUM_CLASSES[enum_name]
    actual_values = [e.value for e in enum_cls]
    assert sorted(actual_values) == sorted(expected_values), (
        f"{enum_name}: esperado {sorted(expected_values)}, encontrado {sorted(actual_values)}"
    )


@pytest.mark.parametrize("enum_name,expected_values", PROTOCOL_ENUMS.items())
def test_enum_count_matches(enum_name, expected_values):
    """Contagem de valores do enum deve ser exata."""
    enum_cls = ENUM_CLASSES[enum_name]
    assert len(enum_cls) == len(expected_values), (
        f"{enum_name}: esperado {len(expected_values)} valores, encontrado {len(enum_cls)}"
    )


def test_unknown_enum_value_raises_value_error():
    """Valor desconhecido deve lançar ValueError (não falha silenciosa)."""
    with pytest.raises(ValueError):
        MessageType("valor_desconhecido_que_nao_existe")


# ── ST003: Formato UUID v4 ────────────────────────────────────────────────────

UUID_V4_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)


def test_python_uuid4_format():
    """uuid.uuid4() gera UUID v4 no formato correto."""
    for _ in range(10):
        generated = str(uuid.uuid4())
        assert UUID_V4_PATTERN.match(generated), f"UUID inválido: {generated}"


def test_python_uuid4_version_nibble():
    """Version nibble deve ser sempre '4'."""
    for _ in range(10):
        generated = str(uuid.uuid4())
        assert generated[14] == "4", f"Version nibble incorreto: {generated}"


def test_python_uuid4_variant_bits():
    """Variant bits devem ser 8, 9, a ou b na posição 19."""
    for _ in range(10):
        generated = str(uuid.uuid4())
        assert generated[19] in "89ab", f"Variant bits incorretos: {generated}"


def test_uuid_v1_not_accepted_as_v4():
    """UUID v1 não deve passar na validação de formato v4 (version nibble != 4)."""
    uuid_v1 = str(uuid.uuid1())
    assert uuid_v1[14] == "1", f"Esperado UUID v1 com nibble 1: {uuid_v1}"
    assert not UUID_V4_PATTERN.match(uuid_v1), f"UUID v1 passou incorretamente: {uuid_v1}"


def test_ws_envelope_auto_generates_uuid4():
    """WsEnvelope gerado automaticamente usa UUID v4."""
    env = WsEnvelope(type=MessageType.SYNC_REQUEST.value, payload={})
    assert UUID_V4_PATTERN.match(env.message_id), f"message_id não é UUID v4: {env.message_id}"


# ── ST004: Forward compatibility ─────────────────────────────────────────────


def test_forward_compat_python_ignores_extra_fields():
    """Campos extras no envelope não causam erro — forward compatibility."""
    env_with_extra = {
        "message_id": "550e8400-e29b-41d4-a716-446655440009",
        "type": "sync_request",
        "timestamp": "2025-01-15T10:30:00+00:00",
        "payload": {},
        "extra_field": "deve_ser_ignorado",
        "future_feature": {"nested": True},
    }
    result = WsEnvelope.from_dict(env_with_extra)
    assert result is not None
    # Campos extras não aparecem no to_dict()
    d = result.to_dict()
    assert "extra_field" not in d
    assert "future_feature" not in d


def test_timestamp_without_milliseconds_is_accepted():
    """Timestamp sem milissegundos deve ser aceito (precisão de segundos é suficiente)."""
    ts_variants = [
        "2025-01-15T10:30:00Z",
        "2025-01-15T10:30:00.123Z",
        "2025-01-15T10:30:00.123456Z",
    ]
    for ts in ts_variants:
        parsed = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        assert parsed.tzinfo is not None, f"Timezone ausente para: {ts}"


# ── ST006: Formato de timestamp cross-platform ───────────────────────────────


def test_python_timestamp_is_iso8601_with_timezone():
    """WsEnvelope gera timestamp UTC válido com timezone."""
    env_dict = WsEnvelope(type=MessageType.SYNC_REQUEST.value, payload={}).to_dict()
    ts = env_dict["timestamp"].replace("Z", "+00:00")
    parsed = datetime.fromisoformat(ts)
    assert parsed.tzinfo is not None, "Timestamp deve ter timezone"


def test_python_timestamp_parseable_from_kotlin_format():
    """Timestamp no formato Z (gerado pelo Kotlin InstantSerializer) deve ser parseável pelo Python."""
    kotlin_style_ts = "2025-01-15T10:30:00.123456Z"
    parsed = datetime.fromisoformat(kotlin_style_ts.replace("Z", "+00:00"))
    assert parsed.year == 2025
    assert parsed.tzinfo is not None


def test_kotlin_timestamp_variants_all_accepted():
    """Python aceita todas as variantes de timestamp que Kotlin pode gerar."""
    ts_variants = [
        "2025-01-15T10:30:00Z",
        "2025-01-15T10:30:00.123Z",
        "2025-01-15T10:30:00.123456Z",
        "2025-01-15T10:30:00+00:00",
    ]
    for ts in ts_variants:
        normalized = ts.replace("Z", "+00:00")
        parsed = datetime.fromisoformat(normalized)
        assert parsed is not None, f"Falhou ao parsear: {ts}"
        assert parsed.tzinfo is not None, f"Timezone ausente: {ts}"
