"""Testes de contrato do protocolo JSON — module-11-contract-testing / TASK-1.

Valida:
- Estrutura do envelope WsEnvelope (message_id, type, timestamp, payload)
- Campos obrigatórios por tipo de mensagem (PC→Android e Android→PC)
- Rejeição de mensagens inválidas e payloads maliciosos
"""

import uuid
from datetime import datetime

import pytest

from workflow_app.remote.protocol import (
    ControlAction,
    PipelineStatus,
    ResponseType,
    WsEnvelope,
    is_valid_client_message,
)

# ── Fixtures válidos (ST001 de TASK-0) ───────────────────────────────────────

VALID_ENVELOPES = {
    "output_chunk": {
        "message_id": "550e8400-e29b-41d4-a716-446655440000",
        "type": "output_chunk",
        "timestamp": "2025-01-15T10:30:00.123456+00:00",
        "payload": {"lines": ["linha 1", "linha 2"]},
    },
    "output_truncated": {
        "message_id": "550e8400-e29b-41d4-a716-446655440001",
        "type": "output_truncated",
        "timestamp": "2025-01-15T10:30:00.123456+00:00",
        "payload": {"lines_omitted": 42},
    },
    "pipeline_state": {
        "message_id": "550e8400-e29b-41d4-a716-446655440002",
        "type": "pipeline_state",
        "timestamp": "2025-01-15T10:30:00.123456+00:00",
        "payload": {
            "status": "running",
            "command_queue": [{"index": 0, "name": "build", "status": "running"}],
        },
    },
    "interaction_request": {
        "message_id": "550e8400-e29b-41d4-a716-446655440003",
        "type": "interaction_request",
        "timestamp": "2025-01-15T10:30:00.123456+00:00",
        "payload": {"prompt": "Continuar?", "type": "confirm", "options": ["yes", "no"]},
    },
    "interactive_mode_ended": {
        "message_id": "550e8400-e29b-41d4-a716-446655440004",
        "type": "interactive_mode_ended",
        "timestamp": "2025-01-15T10:30:00.123456+00:00",
        "payload": {},
    },
    "error": {
        "message_id": "550e8400-e29b-41d4-a716-446655440005",
        "type": "error",
        "timestamp": "2025-01-15T10:30:00.123456+00:00",
        "payload": {"message": "Erro ao executar comando"},
    },
    "control_ack": {
        "message_id": "550e8400-e29b-41d4-a716-446655440006",
        "type": "control_ack",
        "timestamp": "2025-01-15T10:30:00.123456+00:00",
        "payload": {"action": "pause", "accepted": True},
    },
    "control": {
        "message_id": "550e8400-e29b-41d4-a716-446655440007",
        "type": "control",
        "timestamp": "2025-01-15T10:30:00.123456+00:00",
        "payload": {"action": "pause"},
    },
    "interaction_response": {
        "message_id": "550e8400-e29b-41d4-a716-446655440008",
        "type": "interaction_response",
        "timestamp": "2025-01-15T10:30:00.123456+00:00",
        "payload": {"text": "sim", "response_type": "yes"},
    },
    "sync_request": {
        "message_id": "550e8400-e29b-41d4-a716-446655440009",
        "type": "sync_request",
        "timestamp": "2025-01-15T10:30:00.123456+00:00",
        "payload": {},
    },
}


# ── ST001: Estrutura do envelope ─────────────────────────────────────────────


@pytest.mark.parametrize("msg_type,env", VALID_ENVELOPES.items())
def test_envelope_structure(msg_type, env):
    envelope = WsEnvelope.from_dict(env)
    d = envelope.to_dict()
    # Exatamente 4 chaves obrigatórias
    assert set(d.keys()) == {"message_id", "type", "timestamp", "payload"}
    # message_id deve ser UUID v4 válido
    parsed_uuid = uuid.UUID(d["message_id"], version=4)
    assert str(parsed_uuid) == d["message_id"]
    # timestamp deve ser ISO 8601 com timezone
    ts = d["timestamp"].replace("Z", "+00:00")
    parsed_ts = datetime.fromisoformat(ts)
    assert parsed_ts.tzinfo is not None, "Timestamp deve ter timezone"
    # payload deve ser dict (não list, não None, não string)
    assert isinstance(d["payload"], dict)


# ── ST002: Payload por tipo PC→Android ───────────────────────────────────────


def test_output_chunk_payload():
    env = WsEnvelope.from_dict(VALID_ENVELOPES["output_chunk"])
    assert isinstance(env.payload["lines"], list)
    assert all(isinstance(line, str) for line in env.payload["lines"])


def test_output_truncated_payload():
    env = WsEnvelope.from_dict(VALID_ENVELOPES["output_truncated"])
    assert isinstance(env.payload["lines_omitted"], int)
    assert env.payload["lines_omitted"] >= 0


def test_pipeline_state_payload():
    env = WsEnvelope.from_dict(VALID_ENVELOPES["pipeline_state"])
    assert env.payload["status"] in [s.value for s in PipelineStatus]
    assert isinstance(env.payload["command_queue"], list)
    for cmd in env.payload["command_queue"]:
        assert "index" in cmd and "name" in cmd and "status" in cmd


def test_interaction_request_payload():
    env = WsEnvelope.from_dict(VALID_ENVELOPES["interaction_request"])
    assert isinstance(env.payload["prompt"], str)
    assert isinstance(env.payload["type"], str)
    assert isinstance(env.payload["options"], list)


def test_interactive_mode_ended_payload():
    env = WsEnvelope.from_dict(VALID_ENVELOPES["interactive_mode_ended"])
    assert env.payload == {}


def test_error_payload():
    env = WsEnvelope.from_dict(VALID_ENVELOPES["error"])
    assert isinstance(env.payload["message"], str)
    assert len(env.payload["message"]) > 0


def test_control_ack_payload():
    env = WsEnvelope.from_dict(VALID_ENVELOPES["control_ack"])
    assert env.payload["action"] in [a.value for a in ControlAction]
    assert isinstance(env.payload["accepted"], bool)


# Rejeição de campos obrigatórios faltando (validate_payload)


def test_output_chunk_missing_lines_raises():
    bad = {**VALID_ENVELOPES["output_chunk"], "payload": {}}
    with pytest.raises((KeyError, ValueError)):
        WsEnvelope.from_dict(bad).validate_payload()


def test_pipeline_state_missing_status_raises():
    bad = {**VALID_ENVELOPES["pipeline_state"], "payload": {"command_queue": []}}
    with pytest.raises((KeyError, ValueError)):
        WsEnvelope.from_dict(bad).validate_payload()


def test_control_ack_missing_accepted_raises():
    bad = {**VALID_ENVELOPES["control_ack"], "payload": {"action": "pause"}}
    with pytest.raises((KeyError, ValueError)):
        WsEnvelope.from_dict(bad).validate_payload()


# ── ST003: Payload por tipo Android→PC ───────────────────────────────────────


def test_control_payload():
    env = WsEnvelope.from_dict(VALID_ENVELOPES["control"])
    assert env.payload["action"] in [a.value for a in ControlAction]


def test_interaction_response_payload():
    env = WsEnvelope.from_dict(VALID_ENVELOPES["interaction_response"])
    assert env.payload["response_type"] in [r.value for r in ResponseType]
    assert isinstance(env.payload["text"], str)


def test_sync_request_payload():
    env = WsEnvelope.from_dict(VALID_ENVELOPES["sync_request"])
    assert env.payload == {}


def test_is_valid_client_message():
    """Apenas os 3 tipos Android→PC são reconhecidos como válidos pelo servidor PC."""
    assert is_valid_client_message("control") is True
    assert is_valid_client_message("interaction_response") is True
    assert is_valid_client_message("sync_request") is True
    # Tipos PC→Android devem retornar False
    assert is_valid_client_message("output_chunk") is False
    assert is_valid_client_message("output_truncated") is False
    assert is_valid_client_message("pipeline_state") is False
    assert is_valid_client_message("error") is False
    assert is_valid_client_message("control_ack") is False


# ── ST005: Rejeição de payloads maliciosos/inválidos ─────────────────────────


def test_injection_in_type_field_rejected():
    """Type com código malicioso deve ser rejeitado pelo whitelist de MessageType."""
    malicious = {
        "message_id": "550e8400-e29b-41d4-a716-446655440000",
        "type": "__import__('os').system('ls')",
        "timestamp": "2025-01-15T10:30:00+00:00",
        "payload": {},
    }
    with pytest.raises((ValueError, KeyError)):
        WsEnvelope.from_dict(malicious)


def test_oversized_payload_does_not_crash():
    """Payload maior que 4096 bytes não deve causar crash — truncamento é do OutputThrottle."""
    large_payload = {"lines": ["x" * 100] * 50}  # ~5000 chars
    env = {
        "message_id": "550e8400-e29b-41d4-a716-446655440000",
        "type": "output_chunk",
        "timestamp": "2025-01-15T10:30:00+00:00",
        "payload": large_payload,
    }
    result = WsEnvelope.from_dict(env)
    assert result is not None


def test_null_message_id_rejected():
    env = {**VALID_ENVELOPES["sync_request"], "message_id": None}
    with pytest.raises((TypeError, ValueError)):
        WsEnvelope.from_dict(env)


def test_payload_as_list_rejected():
    """Payload como lista (não dict) deve ser rejeitado."""
    env = {**VALID_ENVELOPES["sync_request"], "payload": []}
    with pytest.raises((TypeError, ValueError)):
        WsEnvelope.from_dict(env)


def test_payload_as_null_rejected():
    """Payload como None deve ser rejeitado."""
    env = {**VALID_ENVELOPES["sync_request"], "payload": None}
    with pytest.raises((TypeError, ValueError)):
        WsEnvelope.from_dict(env)


# ── Delegação semântica — congruência entre 4 documentos (item 011 + Grok) ──
#
# Os documentos de roteamento multi-LLM devem declarar o mesmo
# vocabulário normativo de delegação. Este teste lê todos e falha se
# qualquer termo normativo estiver ausente em algum deles.
#
# Documentos:
#   1. ai-forge/rules/llm-routing-div.md
#   2. ai-forge/MCP/agents/executor-de-slash-commands-rules.md
#   3. .agents/skills/slash-executor.md
#   4. .grok/commands/slash-executor.md

import pathlib

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]

_DELEGATION_DOCS = [
    _REPO_ROOT / "ai-forge" / "rules" / "llm-routing-div.md",
    _REPO_ROOT / "ai-forge" / "MCP" / "agents" / "executor-de-slash-commands-rules.md",
    _REPO_ROOT / ".agents" / "skills" / "slash-executor.md",
    _REPO_ROOT / ".grok" / "commands" / "slash-executor.md",
]

# Termos normativos que TODOS os três documentos devem conter.
# Cada termo é uma tuple (label, pattern) onde pattern é buscado como substring
# case-insensitive no conteúdo do documento.
_DELEGATION_NORMATIVE_TERMS = [
    ("delegate mode", "delegate"),
    ("inline mode", "inline"),
    ("fallback-inline mode", "fallback-inline"),
    ("provider claude", "claude"),
    ("provider kimi", "kimi"),
    ("provider codex", "codex"),
    ("multi-llm-routing block", "multi-llm-routing"),
    ("fallback para Claude", "fallback inline para claude"),
    ("flag --kimi", "--kimi"),
    ("flag --codex", "--codex"),
]


def _read_doc(path: pathlib.Path) -> str:
    """Lê o conteúdo de um documento de delegação."""
    assert path.exists(), f"Documento ausente: {path}"
    return path.read_text(encoding="utf-8")


def test_delegation_docs_all_exist():
    """Os documentos de delegação devem existir no repo."""
    for doc_path in _DELEGATION_DOCS:
        assert doc_path.exists(), f"Documento ausente: {doc_path}"


def test_delegation_congruence_all_docs_share_normative_terms():
    """Cada documento de delegação deve conter todos os termos normativos.

    Falha se qualquer termo normativo estiver ausente em qualquer documento.
    Este teste prova que os contratos continuam alinhados.
    """
    failures = []
    for doc_path in _DELEGATION_DOCS:
        content = _read_doc(doc_path).lower()
        for label, pattern in _DELEGATION_NORMATIVE_TERMS:
            if pattern.lower() not in content:
                failures.append(f"{doc_path.name}: missing '{label}' ('{pattern}')")
    assert not failures, "Divergência de termos normativos de delegação:\n" + "\n".join(
        f"  - {f}" for f in failures
    )


def test_delegation_executor_codex_has_passo_2_5():
    """O executor Codex deve declarar Passo 2.5 (contrato de delegação)."""
    content = _read_doc(_DELEGATION_DOCS[1])
    assert "Passo 2.5" in content, "executor-de-slash-commands-rules.md missing Passo 2.5"


def test_delegation_executor_kimi_has_delegation_mode_clause():
    """O executor Kimi deve declarar a cláusula <DELEGATION_MODE>."""
    content = _read_doc(_DELEGATION_DOCS[2])
    assert "DELEGATION_MODE" in content, "slash-executor.md missing <DELEGATION_MODE>"


def test_delegation_executor_grok_has_delegation_mode_clause():
    """O executor Grok deve declarar a cláusula <DELEGATION_MODE>."""
    content = _read_doc(_DELEGATION_DOCS[3])
    assert "DELEGATION_MODE" in content, (
        ".grok/commands/slash-executor.md missing <DELEGATION_MODE>"
    )
    lowered = content.lower()
    for term in ("delegate", "inline", "fallback-inline", "multi-llm-routing"):
        assert term in lowered, (
            f".grok/commands/slash-executor.md missing '{term}'"
        )
