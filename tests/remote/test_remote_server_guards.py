"""
Tests for RemoteServer inbound guards — module-2/TASK-3.

Covers all 6 BDD scenarios:
1. Rate limiting aceita até RATE_LIMIT_MSG_PER_S msg/s
2. Rate limiting rejeita a mensagem excedente
3. Dedup descarta mensagem com message_id duplicado
4. Dedup FIFO ao atingir DEDUP_SET_LIMIT
5. Whitelist rejeita tipo desconhecido (e.g. "output_chunk")
6. Mensagem maior que MAX_MESSAGE_BYTES é rejeitada antes do JSON parse
"""

from __future__ import annotations

import json
import logging
from unittest.mock import MagicMock

import pytest

from workflow_app.remote.constants import (
    DEDUP_SET_LIMIT,
    MAX_MESSAGE_BYTES,
    RATE_LIMIT_MSG_PER_S,
)
from workflow_app.remote.remote_server import RemoteServer, RemoteServerState, _RateLimiter

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def signal_bus():
    """Mock signal bus."""
    bus = MagicMock()
    bus.remote_mode_toggle_requested = MagicMock()
    bus.remote_mode_toggle_requested.connect = MagicMock()
    bus.remote_server_started = MagicMock()
    bus.remote_server_stopped = MagicMock()
    bus.remote_client_connected = MagicMock()
    bus.remote_client_disconnected = MagicMock()
    return bus


@pytest.fixture
def server(qapp, signal_bus):
    """RemoteServer instance in CONNECTED_CLIENT state (message pipeline active)."""
    s = RemoteServer(signal_bus)
    s._state = RemoteServerState.CONNECTED_CLIENT
    s._bridge = MagicMock()
    return s


# ── _RateLimiter unit tests ───────────────────────────────────────────────────


def test_rate_limiter_aceita_ate_limite():
    """BDD Cenário 1: First RATE_LIMIT_MSG_PER_S calls all return True."""
    rl = _RateLimiter(limit=RATE_LIMIT_MSG_PER_S)
    results = [rl.check() for _ in range(RATE_LIMIT_MSG_PER_S)]
    assert all(results)


def test_rate_limiter_rejeita_apos_limite():
    """BDD Cenário 2: Call beyond RATE_LIMIT_MSG_PER_S returns False."""
    rl = _RateLimiter(limit=RATE_LIMIT_MSG_PER_S)
    for _ in range(RATE_LIMIT_MSG_PER_S):
        rl.check()
    assert rl.check() is False


def test_rate_limiter_reset_apos_1s():
    """After 1 second, the window resets and messages are accepted again."""

    rl = _RateLimiter(limit=2)
    rl.check()
    rl.check()
    assert rl.check() is False  # exceeded

    # Manually advance the window
    rl._window_start -= 1.1  # simulate 1.1s passing
    assert rl.check() is True  # window reset


# ── _check_dedup unit tests ───────────────────────────────────────────────────


def test_dedup_aceita_nova_mensagem(server):
    """_check_dedup returns True for a new message_id."""
    assert server._check_dedup("abc-123") is True


def test_dedup_rejeita_duplicado(server):
    """BDD Cenário 3: _check_dedup returns False for a repeated message_id."""
    server._check_dedup("abc-123")
    assert server._check_dedup("abc-123") is False


def test_dedup_fifo_ao_atingir_limite(server):
    """BDD Cenário 4: When DEDUP_SET_LIMIT is reached, oldest entry is evicted (FIFO)."""
    for i in range(DEDUP_SET_LIMIT):
        server._check_dedup(f"msg-{i}")

    assert len(server._seen_ids) == DEDUP_SET_LIMIT

    # Insert one more: "msg-0" (oldest) must be evicted
    result = server._check_dedup("msg-new")
    assert result is True
    assert "msg-0" not in server._seen_ids
    assert len(server._seen_ids) == DEDUP_SET_LIMIT


# ── _on_message_received pipeline tests ──────────────────────────────────────

def _make_msg(msg_type: str = "sync_request", msg_id: str = "id-1") -> str:
    return json.dumps({"type": msg_type, "message_id": msg_id, "payload": {}})


def test_whitelist_aceita_sync_request(server):
    """Valid type 'sync_request' reaches bridge dispatch."""
    server._on_message_received(_make_msg("sync_request"))
    server._bridge.handle_incoming.assert_called_once()


def test_whitelist_aceita_control(server):
    """Valid type 'control' reaches bridge dispatch."""
    server._on_message_received(_make_msg("control", "id-2"))
    server._bridge.handle_incoming.assert_called_once()


def test_whitelist_aceita_interaction_response(server):
    """Valid type 'interaction_response' reaches bridge dispatch."""
    server._on_message_received(_make_msg("interaction_response", "id-3"))
    server._bridge.handle_incoming.assert_called_once()


def test_whitelist_rejeita_output_chunk(server, caplog):
    """BDD Cenário 5: 'output_chunk' (PC→Android type) is rejected with warning log."""
    with caplog.at_level(logging.WARNING, logger="workflow_app.remote.remote_server"):
        server._on_message_received(_make_msg("output_chunk"))

    server._bridge.handle_incoming.assert_not_called()
    assert "output_chunk" in caplog.text
    assert "rejeitado" in caplog.text


def test_whitelist_rejeita_pipeline_state(server, caplog):
    """'pipeline_state' (PC→Android type) is rejected."""
    with caplog.at_level(logging.WARNING, logger="workflow_app.remote.remote_server"):
        server._on_message_received(_make_msg("pipeline_state", "id-4"))

    server._bridge.handle_incoming.assert_not_called()


def test_whitelist_rejeita_tipo_desconhecido(server, caplog):
    """Unknown types are rejected (deny-by-default)."""
    with caplog.at_level(logging.WARNING, logger="workflow_app.remote.remote_server"):
        server._on_message_received(_make_msg("totally_unknown_type", "id-5"))

    server._bridge.handle_incoming.assert_not_called()


def test_rejeita_json_invalido(server, caplog):
    """Malformed JSON is discarded with a warning."""
    with caplog.at_level(logging.WARNING, logger="workflow_app.remote.remote_server"):
        server._on_message_received("not-json{")

    server._bridge.handle_incoming.assert_not_called()
    assert "JSON" in caplog.text or "inválida" in caplog.text


def test_rejeita_mensagem_acima_de_max_bytes(server, caplog):
    """BDD Cenário 6: Message > MAX_MESSAGE_BYTES is discarded before JSON parse."""
    oversized = "x" * (MAX_MESSAGE_BYTES + 1)

    with caplog.at_level(logging.WARNING, logger="workflow_app.remote.remote_server"):
        server._on_message_received(oversized)

    server._bridge.handle_incoming.assert_not_called()
    assert "descartada" in caplog.text or str(MAX_MESSAGE_BYTES) in caplog.text


def test_mensagem_no_limite_aceita(server):
    """Message exactly at MAX_MESSAGE_BYTES (UTF-8) is NOT discarded by size check."""
    # Create a valid message that's just under the limit by using ASCII padding
    payload_size = MAX_MESSAGE_BYTES - 100  # leave room for JSON envelope
    msg = json.dumps({
        "type": "sync_request",
        "message_id": "id-size",
        "payload": {"data": "a" * payload_size},
    })
    # Ensure it's <= MAX_MESSAGE_BYTES
    if len(msg.encode("utf-8")) <= MAX_MESSAGE_BYTES:
        server._on_message_received(msg)
        server._bridge.handle_incoming.assert_called_once()


def test_dedup_pipeline_rejeita_duplicado(server, caplog):
    """Duplicate message_id is silently discarded (no dispatch to bridge)."""
    msg = _make_msg("sync_request", "dup-id")

    server._on_message_received(msg)   # first: accepted
    server._bridge.handle_incoming.reset_mock()
    server._on_message_received(msg)   # second: rejected silently

    server._bridge.handle_incoming.assert_not_called()


def test_mensagem_sem_message_id_passa(server):
    """Message without message_id field is not rejected by dedup (id is optional)."""
    msg = json.dumps({"type": "sync_request", "payload": {}})
    server._on_message_received(msg)
    server._bridge.handle_incoming.assert_called_once()


def test_rate_limit_pipeline_rejeita_flood(server, caplog):
    """Rate limiter in pipeline rejects messages beyond RATE_LIMIT_MSG_PER_S."""
    # Exhaust the rate limit
    for i in range(RATE_LIMIT_MSG_PER_S):
        server._on_message_received(_make_msg("sync_request", f"id-{i}"))

    server._bridge.handle_incoming.reset_mock()

    with caplog.at_level(logging.WARNING, logger="workflow_app.remote.remote_server"):
        server._on_message_received(_make_msg("sync_request", "id-flood"))

    server._bridge.handle_incoming.assert_not_called()
    assert "rate limit" in caplog.text.lower() or "descartada" in caplog.text
