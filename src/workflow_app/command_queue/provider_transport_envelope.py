"""Versioned JSON boundary for provider transport.

The envelope is deliberately provider-neutral.  It validates the payload at
the boundary and exposes terminal failures as typed values instead of relying
on exit codes or free-form text.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from enum import Enum
from typing import Any, Mapping


SCHEMA_VERSION = "1.0.0"


class EnvelopeValidationError(ValueError):
    """Raised when a transport envelope violates the versioned schema."""


class KernelDispatchError(RuntimeError):
    """Typed bridge failure propagated through the delegation transport."""

    def __init__(self, code: TransportErrorCode | str, detail: str | None = None) -> None:
        self.code = TransportErrorCode(code)
        self.detail = detail
        super().__init__(self.code.value)


class TransportTerminal(str, Enum):
    """Exhaustive terminal taxonomy shared with the provider bridge."""

    OK = "ok"
    EMPTY_PARSED = "empty-parsed"
    EXIT_NONZERO = "exit-nonzero"
    TIMEOUT = "timeout"
    BINARY_MISSING = "binary-missing"
    ERROR = "error"


class TransportErrorCode(str, Enum):
    """Typed error corresponding one-to-one with non-success terminals."""

    EMPTY_PARSED = "empty-parsed"
    EXIT_NONZERO = "exit-nonzero"
    TIMEOUT = "timeout"
    BINARY_MISSING = "binary-missing"
    ERROR = "error"


@dataclass(frozen=True)
class ProviderTransportRequest:
    """Input consumed by a provider transport lane."""

    step_id: str
    provider: str
    command_text: str
    topic: str
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_version(self.schema_version)
        _require_non_empty("step_id", self.step_id)
        _require_non_empty("provider", self.provider)
        _require_non_empty("command_text", self.command_text)
        _require_non_empty("topic", self.topic)
        if not self.topic.startswith(f"step:{self.step_id}:"):
            raise EnvelopeValidationError(
                "topic must start with the correlatable step:<step_id>: prefix"
            )


@dataclass(frozen=True)
class ProviderTransportResult:
    """Normalized terminal output returned by a provider transport lane."""

    step_id: str
    terminal: TransportTerminal
    parsed: dict[str, Any] | None = None
    error: TransportErrorCode | None = None
    detail: str | None = None
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        _require_version(self.schema_version)
        _require_non_empty("step_id", self.step_id)
        if self.terminal is TransportTerminal.OK:
            if not self.parsed or self.error is not None:
                raise EnvelopeValidationError(
                    "terminal ok requires non-empty parsed and no error"
                )
            return
        expected = TransportErrorCode(self.terminal.value)
        if self.parsed is not None or self.error is not expected:
            raise EnvelopeValidationError(
                f"terminal {self.terminal.value} requires error={expected.value} "
                "and parsed=None"
            )


def _require_version(version: object) -> None:
    if version != SCHEMA_VERSION:
        raise EnvelopeValidationError(
            f"unsupported schema_version: {version!r}; expected {SCHEMA_VERSION!r}"
        )


def _require_non_empty(field: str, value: object) -> None:
    if not isinstance(value, str) or not value.strip():
        raise EnvelopeValidationError(f"{field} must be a non-empty string")


def _load_object(payload: str | bytes | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(payload, Mapping):
        value = dict(payload)
    elif isinstance(payload, (str, bytes)):
        try:
            value = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise EnvelopeValidationError(f"invalid envelope JSON: {exc}") from exc
    else:
        raise EnvelopeValidationError("envelope must be JSON text or a mapping")
    if not isinstance(value, dict):
        raise EnvelopeValidationError("envelope root must be an object")
    return value


def encode_request(request: ProviderTransportRequest) -> str:
    """Serialize a validated request deterministically."""

    return json.dumps(asdict(request), ensure_ascii=False, sort_keys=True)


def decode_request(payload: str | bytes | Mapping[str, Any]) -> ProviderTransportRequest:
    """Parse and validate an input request fail-closed."""

    value = _load_object(payload)
    allowed = {"schema_version", "step_id", "provider", "command_text", "topic"}
    extra = set(value) - allowed
    if extra:
        raise EnvelopeValidationError(f"unknown request fields: {sorted(extra)}")
    try:
        return ProviderTransportRequest(**value)
    except TypeError as exc:
        raise EnvelopeValidationError(f"invalid request shape: {exc}") from exc


def encode_result(result: ProviderTransportResult) -> str:
    """Serialize a validated result deterministically."""

    value = asdict(result)
    value["terminal"] = result.terminal.value
    value["error"] = result.error.value if result.error is not None else None
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def decode_result(payload: str | bytes | Mapping[str, Any]) -> ProviderTransportResult:
    """Parse and validate a terminal result fail-closed."""

    value = _load_object(payload)
    allowed = {"schema_version", "step_id", "terminal", "parsed", "error", "detail"}
    extra = set(value) - allowed
    if extra:
        raise EnvelopeValidationError(f"unknown result fields: {sorted(extra)}")
    try:
        value["terminal"] = TransportTerminal(value["terminal"])
        if value.get("error") is not None:
            value["error"] = TransportErrorCode(value["error"])
        return ProviderTransportResult(**value)
    except (KeyError, TypeError, ValueError) as exc:
        raise EnvelopeValidationError(f"invalid result shape: {exc}") from exc


def result_from_kernel_outcome(
    step_id: str, outcome: Mapping[str, Any]
) -> ProviderTransportResult:
    """Normalize one provider-kernel outcome without collapsing terminals.

    This is the item 014 boundary: every terminal exposed by the neutral
    kernel maps one-to-one to this module's typed terminal taxonomy.
    """

    if not isinstance(outcome, Mapping):
        raise EnvelopeValidationError("kernel outcome must be a mapping")
    try:
        terminal = TransportTerminal(outcome["terminal"])
    except (KeyError, ValueError) as exc:
        raise EnvelopeValidationError(f"unknown kernel terminal: {outcome!r}") from exc
    parsed = outcome.get("parsed")
    if terminal is TransportTerminal.OK:
        if outcome.get("ok") is not True:
            raise EnvelopeValidationError("kernel terminal ok requires ok=True")
        if not isinstance(parsed, dict) or not parsed:
            raise EnvelopeValidationError("kernel terminal ok requires non-empty parsed object")
        return ProviderTransportResult(
            step_id=step_id,
            terminal=terminal,
            parsed=dict(parsed),
        )
    if outcome.get("ok") is not False:
        raise EnvelopeValidationError(
            f"kernel terminal {terminal.value} requires ok=False"
        )
    detail = str(outcome.get("stderr") or outcome.get("raw_output") or terminal.value)
    return ProviderTransportResult(
        step_id=step_id,
        terminal=terminal,
        error=TransportErrorCode(terminal.value),
        detail=detail,
    )
