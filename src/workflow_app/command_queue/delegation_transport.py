"""Delegation transport — terminal-result transport for multi-LLM delegation.

Source of truth: blacksmith/loop-archives/08-11-llm-config-multillm-expansion/
source.md lines 450-469 (item 013).

This module implements the transport layer that carries a delegation intent
(declared by item 011's semantic delegation contract) to the target provider
(Kimi or Codex; Qwen, Grok and MiMo are refused with an explicit failure in
`delegate_command`), using the MCP envelope from item 004.

Responsibilities:
  1. Receive delegation intent (target provider + command + flags).
  2. Build the MCP envelope (item 004) with correlatable ``step_id`` (C-46).
  3. Execute transport to the remote provider.
  4. Return a terminal result (success or explicit failure) on every path.
  5. Never degrade silently (R-30, R-36).

Non-responsibilities (item 014):
  - Bridge kernel integration.
  - Signal emission to terminals (that is item 014's concern).

Criteria addressed:
  - C-35..C-39, C-41, C-42, C-44 (fallback trigger: ``ok == False`` OR
    ``parsed`` empty, with fixtures for both states).
  - C-46 (correlatable ``step_id`` with ``step:<step_id>`` prefix in topic).
  - R-41 (timeout becomes a lost step, not silent degradation).
"""

from __future__ import annotations

import concurrent.futures
import logging
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Sequence

from workflow_app.command_queue.kimi_whitelist import adapt_to_kimi
from workflow_app.command_queue.provider_transport_envelope import (
    KernelDispatchError,
    ProviderTransportRequest,
    TransportTerminal,
    result_from_kernel_outcome,
)
from workflow_app.command_queue.provider_router import Provider


# Load ai-forge/scripts bridge modules (underscored, not part of workflow_app).
# The repo root is found by walking up until ai-forge/scripts exists, instead of
# a fixed parents[N] hop: the hop silently breaks if this file ever moves depth.
def _find_scripts_dir() -> Path:  # pragma: no cover - import plumbing
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "ai-forge" / "scripts"
        if candidate.is_dir():
            return candidate
    raise ImportError(
        "ai-forge/scripts not found above "
        f"{Path(__file__).resolve()}; provider bridge modules are unreachable"
    )


_SCRIPTS_DIR = str(_find_scripts_dir())
if _SCRIPTS_DIR not in sys.path:  # pragma: no cover - import plumbing
    sys.path.insert(0, _SCRIPTS_DIR)

import _provider_adapters as adapters  # noqa: E402
import _provider_bridge_kernel as kernel  # noqa: E402

if TYPE_CHECKING:
    from workflow_app.domain import CommandSpec

logger = logging.getLogger(__name__)

# Reason codes canonicos para WARNING [delegation-degraded] (C9).
# Mantidos como constantes para garantir estabilidade de contrato com o
# executor LLM (Kimi/Codex) e com os testes de protocolo.
DELEGATION_DEGRADED_REASONS: tuple[str, ...] = (
    "no-transport",
    "binary-missing",
    "credential-missing",
)


def format_delegation_degraded_warning(
    step_id: str,
    provider: str,
    reason: str,
) -> str:
    """Produz a literal `WARNING [delegation-degraded]` (C9).

    Args:
        step_id: identificador da etapa delegada (C-46).
        provider: provider alvo (kimi, codex, grok, qwen, mimo).
        reason: um de `DELEGATION_DEGRADED_REASONS`; valores fora do enum
            ainda sao emitidos (fail-open), mas o caller deve preferir os
            reason codes canonicos.

    Returns:
        Linha literal no formato exato consumido pelos contratos de executor:
        `WARNING [delegation-degraded] step_id=<id> provider=<p> reason=<r>`.
    """
    return (
        f"WARNING [delegation-degraded] step_id={step_id} "
        f"provider={provider} reason={reason}"
    )


@dataclass(frozen=True)
class TransportResult:
    """Terminal result of a delegation transport attempt.

    Invariants (enforced by factory methods):
      - ``ok == True`` implies ``parsed is not None``.
      - ``ok == False`` implies ``error is not None``.

    Fields:
      ok: Whether the transport succeeded.
      parsed: Parsed response from the provider (None when ``ok == False``).
      error: Failure reason (None when ``ok == True``).
      step_id: Correlatable identifier (C-46).
    """

    ok: bool
    parsed: dict[str, Any] | None
    error: str | None
    step_id: str

    def __post_init__(self) -> None:
        """Enforce terminal invariants for factories and direct construction."""
        if self.ok:
            if not self.parsed or self.error is not None:
                raise ValueError(
                    "TransportResult ok=True requires non-empty parsed and error=None"
                )
            return
        if not self.error or self.parsed is not None:
            raise ValueError(
                "TransportResult ok=False requires non-empty error and parsed=None"
            )

    @classmethod
    def success(cls, parsed: dict[str, Any], step_id: str) -> TransportResult:
        """Construct a success result with validated invariant."""
        if not parsed:
            raise ValueError(
                "TransportResult.success requires non-empty parsed"
            )
        return cls(ok=True, parsed=parsed, error=None, step_id=step_id)

    @classmethod
    def failure(cls, error: str, step_id: str) -> TransportResult:
        """Construct a failure result with validated invariant."""
        if not error:
            raise ValueError(
                "TransportResult.failure requires non-empty error string"
            )
        return cls(ok=False, parsed=None, error=error, step_id=step_id)


# Type alias for the dispatch callable injected into delegate_command.
# Takes (command_text: str, provider: Provider, topic: str) and returns
# a parsed dict on success. Raises on failure.
DispatchFn = Callable[[str, Provider, str], dict[str, Any]]
KernelRunner = Callable[[ProviderTransportRequest], dict[str, Any]]


def build_kernel_dispatch(kernel_runner: KernelRunner) -> DispatchFn:
    """Build the concrete item 014 dispatch boundary around the neutral kernel.

    The caller owns the provider-specific adapter and supplies a runner that
    accepts the validated request envelope.  This transport owns normalization
    and never converts a kernel failure into a successful parsed payload.
    """

    if not callable(kernel_runner):
        raise TypeError("kernel_runner must be callable")

    def dispatch(command_text: str, provider: Provider, topic: str) -> dict[str, Any]:
        parts = topic.split(":", 2)
        if len(parts) != 3 or parts[0] != "step" or not parts[1]:
            raise KernelDispatchError("error", "invalid correlatable topic")
        request = ProviderTransportRequest(
            step_id=parts[1],
            provider=provider.value,
            command_text=command_text,
            topic=topic,
        )
        result = result_from_kernel_outcome(request.step_id, kernel_runner(request))
        if result.terminal is not TransportTerminal.OK:
            assert result.error is not None
            raise KernelDispatchError(result.error, result.detail)
        assert result.parsed is not None
        return result.parsed

    return dispatch


def run_provider_request(request: ProviderTransportRequest) -> dict[str, Any]:
    """Real kernel runner for provider delegation requests.

    Bridges the neutral ``ProviderTransportRequest`` envelope to the
    ``_provider_bridge_kernel`` + ``_provider_adapters`` stack.  Builds
    ``SpecParams`` from the request, resolves the adapter, and invokes the
    kernel with the provider's required environment.

    The Codex path always uses ``sandbox="danger-full-access"`` and an
    absolute ``cwd`` (enforced by ``CodexAdapter``); tests assert these
    kwargs are present. The same ``cwd`` goes into ``SpecParams`` and into the
    kernel call, so the argv ``--cd`` and the subprocess kwarg cannot diverge.
    """
    adapter = adapters.get_adapter(request.provider)
    cwd = str(Path(os.getcwd()).resolve())
    params = kernel.SpecParams(
        prompt=request.command_text,
        level=2,
        cwd=cwd,
    )
    return kernel.invoke_provider(
        request.provider,
        lambda: adapter.build_spec(params),
        cwd=cwd,
        timeout=kernel.DEFAULT_TIMEOUT_SECONDS,
        env_for=lambda: adapter.env(),
    )


def build_real_kernel_dispatch() -> DispatchFn:
    """Production dispatch using the real bridge-kernel runner."""
    return build_kernel_dispatch(run_provider_request)


def _build_topic(step_id: str, spec: CommandSpec) -> str:
    """Build the MCP topic with correlatable step_id prefix (C-46, R-42).

    Format: ``step:<step_id>:<command_head>``
    The step_id prefix enables correlation between request and response
    in the bridge layer (item 014).
    """
    command_head = spec.name.strip().lstrip("/").replace("/", ":")
    return f"step:{step_id}:{command_head}"


def delegate_command(
    spec: CommandSpec,
    provider: Provider,
    active_flags: Sequence[str],
    step_id: str,
    *,
    dispatch_fn: DispatchFn | None = None,
    timeout_seconds: float | None = None,
) -> TransportResult:
    """Execute delegation transport to the target provider.

    Args:
        spec: The command specification to delegate.
        provider: Target provider (kimi, codex, grok, qwen, mimo). Only KIMI
            and CODEX are delivered; QWEN, GROK and MIMO return ok=False with
            `unknown-delegation-target:<slug>` (dormant path: a future T2
            caller must add MIMO explicitly). CLAUDE is rejected.
        active_flags: Active MCP feature flags for the envelope.
        step_id: Correlatable step identifier (C-46).
        dispatch_fn: Optional callable that performs the actual dispatch.
            Signature: (command_text, provider, topic) -> parsed_dict.
            When None, returns a prepared-but-not-dispatched result (for
            item 014 to integrate with the bridge kernel).
        timeout_seconds: Optional timeout for the dispatch. When exceeded,
            returns TransportResult.failure("timeout", step_id) (R-41).

    Returns:
        TransportResult with terminal outcome (never silent degradation).
    """
    from workflow_app.command_queue.command_item_widget import (
        command_text_with_flags,
    )

    # Validate provider: CLAUDE is not a delegation target.
    if not isinstance(provider, Provider):
        return TransportResult.failure(
            f"unknown-delegation-target:{provider!r}", step_id
        )

    if provider == Provider.CLAUDE:
        return TransportResult.failure(
            "claude-is-not-a-delegation-target", step_id
        )

    if provider not in (Provider.KIMI, Provider.CODEX):
        return TransportResult.failure(
            f"unknown-delegation-target:{provider.value}", step_id
        )

    # Build the command text via the single producer (item 012).
    try:
        command_text = command_text_with_flags(
            spec, provider=provider, active_flags=active_flags
        )
    except Exception as e:
        logger.exception("Failed to render command text for delegation")
        return TransportResult.failure(
            f"command-render-failed:{e}", step_id
        )

    # Build the MCP envelope topic with step_id prefix (C-46).
    topic = _build_topic(step_id, spec)

    # Kimi path: adapt the command text for Kimi CLI.
    if provider == Provider.KIMI:
        try:
            command_text = adapt_to_kimi(command_text)
        except ValueError as e:
            return TransportResult.failure(
                f"kimi-adaptation-failed:{e}", step_id
            )

    # Preparation is not a terminal dispatch success.  Item 014 supplies a
    # concrete bridge dispatcher through this injection point.
    if dispatch_fn is None:
        return TransportResult.failure("dispatch-not-configured", step_id)

    # Execute the dispatch with optional timeout.
    try:
        if timeout_seconds is not None:
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
            try:
                future = executor.submit(
                    dispatch_fn, command_text, provider, topic
                )
                parsed = future.result(timeout=timeout_seconds)
            except concurrent.futures.TimeoutError:
                future.cancel()
                return TransportResult.failure("timeout", step_id)
            finally:
                executor.shutdown(wait=False, cancel_futures=True)
        else:
            parsed = dispatch_fn(command_text, provider, topic)

        if not parsed:
            return TransportResult.failure(
                "dispatch-returned-empty", step_id
            )

        return TransportResult.success(parsed, step_id)

    except KernelDispatchError as e:
        return TransportResult.failure(e.code.value, step_id)
    except Exception as e:
        logger.exception("Delegation dispatch failed")
        return TransportResult.failure(f"dispatch-error:{e}", step_id)


def should_fallback(result: TransportResult) -> bool:
    """Determine whether a fallback to Claude/T1 is required (C-44).

    This is the canonical fallback trigger. Returns True when:
      - ``result.ok == False`` (explicit failure), OR
      - ``result.parsed`` is empty (None or {}).

    The second condition protects against invariant violations where
    ``ok == True`` but ``parsed`` is unexpectedly empty — the gateway
    catches this and forces fallback rather than proceeding with no data.
    """
    if not result.ok:
        return True
    if not result.parsed:
        return True
    return False


def fallback_reason_from_error(error: str | None) -> str:
    """Mapeia uma mensagem de erro de transporte para reason code canonico (C9).

    Reason codes minimos: `no-transport`, `binary-missing`, `credential-missing`.
    Erros nao reconhecidos caem em `no-transport` (fail-open, nunca silencioso).
    """
    if not error:
        return "no-transport"
    low = error.lower()
    if "credential" in low or "auth" in low or "token" in low:
        return "credential-missing"
    if "binary" in low or "not found" in low or "executable" in low:
        return "binary-missing"
    return "no-transport"


def build_delegation_degraded_warning(
    result: TransportResult,
    provider: Provider,
) -> str:
    """Constroi o warning exato a partir de um TransportResult de falha (C9).

    Usado pelo caminho de fallback inline para anunciar a degradacao audivel
    antes de executar localmente. Nunca deve ser chamado para resultados OK.
    """
    reason = fallback_reason_from_error(
        result.error if result.error is not None else ""
    )
    return format_delegation_degraded_warning(
        step_id=result.step_id,
        provider=provider.value,
        reason=reason,
    )
