"""Tests for the versioned provider transport envelope.

Item 004 invariants covered here: schema versioning, deterministic JSON
round-trip, fail-closed input validation, correlatable step IDs and typed
terminal results.  Item 014 invariants intentionally left for its integration
tests: kernel-outcome conversion, exhaustive parity with the kernel terminal
enum, argv/cwd/env process boundaries and concrete bridge dispatch.
"""

from __future__ import annotations

import json

import pytest

from workflow_app.command_queue.provider_transport_envelope import (
    EnvelopeValidationError,
    ProviderTransportRequest,
    ProviderTransportResult,
    SCHEMA_VERSION,
    TransportErrorCode,
    TransportTerminal,
    decode_request,
    decode_result,
    encode_request,
    encode_result,
    result_from_kernel_outcome,
)


def request() -> ProviderTransportRequest:
    return ProviderTransportRequest(
        step_id="004-a",
        provider="qwen",
        command_text="/daily:scan --check",
        topic="step:004-a:daily:scan",
    )


def test_request_round_trip_is_versioned_and_deterministic() -> None:
    encoded = encode_request(request())
    assert json.loads(encoded)["schema_version"] == SCHEMA_VERSION
    assert encode_request(decode_request(encoded)) == encoded


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("step_id", ""),
        ("provider", None),
        ("command_text", "  "),
        ("topic", 42),
    ],
)
def test_request_rejects_invalid_required_field(field: str, value: object) -> None:
    payload = json.loads(encode_request(request()))
    payload[field] = value
    with pytest.raises(EnvelopeValidationError, match=field):
        decode_request(payload)


def test_request_rejects_unknown_version_and_fields() -> None:
    payload = json.loads(encode_request(request()))
    payload["schema_version"] = "2.0.0"
    with pytest.raises(EnvelopeValidationError, match="unsupported schema_version"):
        decode_request(payload)
    payload = json.loads(encode_request(request()))
    payload["surprise"] = True
    with pytest.raises(EnvelopeValidationError, match="unknown request fields"):
        decode_request(payload)


def test_request_requires_correlatable_topic() -> None:
    payload = json.loads(encode_request(request()))
    payload["topic"] = "daily:scan"
    with pytest.raises(EnvelopeValidationError, match="step:<step_id>"):
        decode_request(payload)


def test_success_result_round_trip() -> None:
    result = ProviderTransportResult(
        step_id="004-a",
        terminal=TransportTerminal.OK,
        parsed={"status": "done"},
    )
    assert decode_result(encode_result(result)) == result


@pytest.mark.parametrize(
    "terminal",
    [terminal for terminal in TransportTerminal if terminal is not TransportTerminal.OK],
)
def test_failure_result_has_typed_error(terminal: TransportTerminal) -> None:
    error = TransportErrorCode(terminal.value)
    result = ProviderTransportResult(
        step_id="004-a", terminal=terminal, error=error, detail="provider failed"
    )
    assert decode_result(encode_result(result)) == result


def test_result_rejects_terminal_invariant_violation() -> None:
    with pytest.raises(EnvelopeValidationError, match="terminal ok"):
        ProviderTransportResult(step_id="004-a", terminal=TransportTerminal.OK)
    with pytest.raises(EnvelopeValidationError, match="requires error=timeout"):
        ProviderTransportResult(step_id="004-a", terminal=TransportTerminal.TIMEOUT)


def test_result_rejects_unknown_terminal() -> None:
    payload = {
        "schema_version": SCHEMA_VERSION,
        "step_id": "004-a",
        "terminal": "mystery",
        "parsed": None,
        "error": "error",
        "detail": None,
    }
    with pytest.raises(EnvelopeValidationError, match="invalid result shape"):
        decode_result(payload)


@pytest.mark.parametrize("terminal", list(TransportTerminal))
def test_envelope_terminal_results_cover_kernel_outcomes(
    terminal: TransportTerminal,
) -> None:
    """Item 014: every neutral-kernel terminal has one typed envelope result."""

    outcome = {
        "terminal": terminal.value,
        "ok": terminal is TransportTerminal.OK,
        "parsed": {"answer": "ok"} if terminal is TransportTerminal.OK else None,
        "stderr": "provider failure" if terminal is not TransportTerminal.OK else "",
    }
    result = result_from_kernel_outcome("014-a", outcome)
    assert result.terminal is terminal
    if terminal is TransportTerminal.OK:
        assert result.parsed == {"answer": "ok"}
        assert result.error is None
    else:
        assert result.error is TransportErrorCode(terminal.value)
        assert result.parsed is None


def test_kernel_outcome_rejects_unknown_or_incoherent_terminal() -> None:
    with pytest.raises(EnvelopeValidationError, match="unknown kernel terminal"):
        result_from_kernel_outcome("014-a", {"terminal": "future", "ok": False})
    with pytest.raises(EnvelopeValidationError, match="requires ok=True"):
        result_from_kernel_outcome(
            "014-a", {"terminal": "ok", "ok": False, "parsed": {"answer": "x"}}
        )
