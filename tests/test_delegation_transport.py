"""Tests for delegation_transport module (item 013).

Covers:
  - ST001: TransportResult type with invariant enforcement.
  - ST002: delegate_command function with all provider paths.
  - ST003: should_fallback canonical trigger (C-44).
  - ST004: Fixture-based tests for both fallback states.
  - ST005: Regression against existing command_queue tests.

Criteria (from task-013):
  - C-35..C-39, C-41, C-42, C-44 (fallback: ok==False OR parsed empty).
  - C-46 (step_id correlatable with step:<step_id> prefix in topic).
  - R-41 (timeout becomes lost step, not silent degradation).
"""
from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest

from workflow_app.command_queue.delegation_transport import (
    TransportResult,
    build_kernel_dispatch,
    delegate_command,
    should_fallback,
    _build_topic,
)
from workflow_app.command_queue.provider_router import Provider
from workflow_app.domain import CommandSpec, ModelName


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #

@pytest.fixture()
def spec() -> CommandSpec:
    """Minimal CommandSpec for delegation tests."""
    return CommandSpec(
        name="/blog:stockpile-status",
        model=ModelName.SONNET,
        position=1,
        kimi_eligible=True,
    )


@pytest.fixture()
def spec_claude_only() -> CommandSpec:
    """CommandSpec that is NOT kimi_eligible (Claude-only command)."""
    return CommandSpec(
        name="/prd-create",
        model=ModelName.SONNET,
        position=2,
        kimi_eligible=False,
    )


# --------------------------------------------------------------------------- #
# ST001 — TransportResult type                                                #
# --------------------------------------------------------------------------- #

class TestTransportResult:
    """TransportResult dataclass with invariant enforcement."""

    def test_transport_result_success_has_parsed(self):
        """success() factory produces ok=True with parsed filled, error=None."""
        result = TransportResult.success({"result": "ok"}, "step:001")
        assert result.ok is True
        assert result.parsed == {"result": "ok"}
        assert result.error is None
        assert result.step_id == "step:001"

    def test_transport_result_failure_has_error(self):
        """failure() factory produces ok=False with error filled, parsed=None."""
        result = TransportResult.failure("timeout", "step:002")
        assert result.ok is False
        assert result.error == "timeout"
        assert result.parsed is None
        assert result.step_id == "step:002"

    def test_transport_result_invariant_success_rejects_none_parsed(self):
        """success() with parsed=None raises ValueError (invariant enforcement)."""
        with pytest.raises(ValueError, match="non-empty parsed"):
            TransportResult.success(None, "step:003")

    def test_transport_result_invariant_failure_rejects_empty_error(self):
        """failure() with empty error raises ValueError (invariant enforcement)."""
        with pytest.raises(ValueError, match="non-empty error"):
            TransportResult.failure("", "step:004")

    def test_transport_result_frozen(self):
        """TransportResult is immutable (frozen dataclass)."""
        result = TransportResult.success({"ok": True}, "step:005")
        with pytest.raises(AttributeError):
            result.ok = False  # type: ignore[misc]

    def test_transport_result_direct_construction_valid(self):
        """Direct construction with valid invariant works (for edge cases)."""
        result = TransportResult(
            ok=True, parsed={"data": 1}, error=None, step_id="step:006"
        )
        assert result.ok is True
        assert result.parsed == {"data": 1}

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"ok": True, "parsed": None, "error": None},
            {"ok": True, "parsed": {}, "error": None},
            {"ok": True, "parsed": {"data": 1}, "error": "unexpected"},
            {"ok": False, "parsed": None, "error": None},
            {"ok": False, "parsed": {"data": 1}, "error": "failed"},
        ],
    )
    def test_transport_result_direct_construction_rejects_invalid(self, kwargs):
        """The invariant applies to direct construction, not only factories."""
        with pytest.raises(ValueError, match="TransportResult"):
            TransportResult(step_id="invalid", **kwargs)


# --------------------------------------------------------------------------- #
# ST002 — delegate_command function                                           #
# --------------------------------------------------------------------------- #

class TestDelegateCommand:
    """delegate_command with all provider paths."""

    def test_delegate_command_claude_rejected(self, spec):
        """Provider.CLAUDE is not a delegation target -> ok=False."""
        result = delegate_command(
            spec, Provider.CLAUDE, active_flags=[], step_id="s-claude"
        )
        assert result.ok is False
        assert "not-a-delegation-target" in result.error
        assert result.step_id == "s-claude"

    def test_delegate_command_unknown_provider_rejected(self, spec):
        """Provider.QWEN (unknown target) -> ok=False."""
        result = delegate_command(
            spec, Provider.QWEN, active_flags=[], step_id="s-qwen"
        )
        assert result.ok is False
        assert "unknown-delegation-target" in result.error

    def test_delegate_command_kimi_without_dispatch_is_not_success(self, spec):
        """KIMI preparation without a dispatcher is an explicit failure."""
        result = delegate_command(
            spec, Provider.KIMI, active_flags=[], step_id="s-kimi-prep"
        )
        assert result.ok is False
        assert result.error == "dispatch-not-configured"

    def test_delegate_command_codex_without_dispatch_is_not_success(self, spec):
        """CODEX preparation without a dispatcher is an explicit failure."""
        result = delegate_command(
            spec, Provider.CODEX, active_flags=[], step_id="s-codex-prep"
        )
        assert result.ok is False
        assert result.error == "dispatch-not-configured"

    def test_delegate_command_kimi_success_with_dispatch(self, spec):
        """KIMI path with successful dispatch_fn -> ok=True."""
        captured = {}

        def mock_dispatch(text, provider, topic):
            captured.update(text=text, provider=provider, topic=topic)
            return {"status": "dispatched", "provider": "kimi"}

        result = delegate_command(
            spec, Provider.KIMI,
            active_flags=[], step_id="s-kimi-ok",
            dispatch_fn=mock_dispatch,
        )
        assert result.ok is True
        assert result.parsed["status"] == "dispatched"
        assert "/skill:" in captured["text"]
        assert captured["provider"] is Provider.KIMI
        assert captured["topic"] == "step:s-kimi-ok:blog:stockpile-status"

    def test_delegate_command_codex_success_with_dispatch(self, spec):
        """CODEX path with successful dispatch_fn -> ok=True."""
        def mock_dispatch(text, provider, topic):
            return {"status": "dispatched", "provider": "codex"}

        result = delegate_command(
            spec, Provider.CODEX,
            active_flags=[], step_id="s-codex-ok",
            dispatch_fn=mock_dispatch,
        )
        assert result.ok is True
        assert result.parsed["status"] == "dispatched"

    def test_delegate_command_kimi_adaptation_failure(self, spec_claude_only):
        """KIMI path with non-slash command -> adapt_to_kimi raises ValueError."""
        # Create a spec with a name that doesn't start with /
        bad_spec = CommandSpec(
            name="not-a-slash-command",
            model=ModelName.SONNET,
            position=3,
        )
        result = delegate_command(
            bad_spec, Provider.KIMI,
            active_flags=[], step_id="s-kimi-fail",
        )
        assert result.ok is False
        assert "kimi-adaptation-failed" in result.error

    def test_delegate_command_timeout(self, spec):
        """Timeout returns TransportResult.failure('timeout', step_id) (R-41)."""
        release = threading.Event()

        def slow_dispatch(text, provider, topic):
            release.wait(timeout=5)
            return {"status": "too-late"}

        started = time.monotonic()
        result = delegate_command(
            spec, Provider.CODEX,
            active_flags=[], step_id="s-timeout",
            dispatch_fn=slow_dispatch,
            timeout_seconds=0.1,
        )
        elapsed = time.monotonic() - started
        release.set()
        assert result.ok is False
        assert result.error == "timeout"
        assert result.step_id == "s-timeout"
        assert elapsed < 0.5

    def test_delegate_command_dispatch_exception(self, spec):
        """Dispatch raising an exception -> ok=False with error details."""
        def failing_dispatch(text, provider, topic):
            raise RuntimeError("connection-refused")

        result = delegate_command(
            spec, Provider.CODEX,
            active_flags=[], step_id="s-exception",
            dispatch_fn=failing_dispatch,
        )
        assert result.ok is False
        assert "dispatch-error" in result.error
        assert "connection-refused" in result.error

    def test_delegate_command_dispatch_returns_empty(self, spec):
        """Dispatch returning empty dict -> ok=False (fallback trigger)."""
        def empty_dispatch(text, provider, topic):
            return {}

        result = delegate_command(
            spec, Provider.CODEX,
            active_flags=[], step_id="s-empty",
            dispatch_fn=empty_dispatch,
        )
        assert result.ok is False
        assert "dispatch-returned-empty" in result.error

    def test_delegate_command_step_id_in_topic(self, spec):
        """step_id appears as prefix step:<step_id> in topic (C-46, R-42)."""
        captured = {}

        def dispatch(text, provider, topic):
            captured["topic"] = topic
            return {"status": "dispatched"}

        result = delegate_command(
            spec, Provider.KIMI,
            active_flags=[], step_id="abc123",
            dispatch_fn=dispatch,
        )
        assert result.ok is True
        assert captured["topic"].startswith("step:abc123:")


# --------------------------------------------------------------------------- #
# ST003 — should_fallback (C-44)                                              #
# --------------------------------------------------------------------------- #

class TestShouldFallback:
    """should_fallback canonical trigger (C-44)."""

    def test_should_fallback_ok_false(self):
        """ok=False -> should_fallback returns True."""
        result = TransportResult.failure("err", "s1")
        assert should_fallback(result) is True

    def test_should_fallback_parsed_empty_none(self):
        """parsed=None (even with ok=True) -> should_fallback returns True."""
        result = SimpleNamespace(ok=True, parsed=None)
        assert should_fallback(result) is True

    def test_should_fallback_parsed_empty_dict(self):
        """parsed={} (even with ok=True) -> should_fallback returns True."""
        result = SimpleNamespace(ok=True, parsed={})
        assert should_fallback(result) is True

    def test_should_fallback_ok_true_with_parsed(self):
        """ok=True with non-empty parsed -> should_fallback returns False."""
        result = TransportResult.success({"r": 1}, "s3")
        assert should_fallback(result) is False


# --------------------------------------------------------------------------- #
# ST004 — Fixture-based fallback states (C-44)                                #
# --------------------------------------------------------------------------- #

class TestFallbackFixtures:
    """Parametrized fixtures covering both fallback trigger states (C-44)."""

    @pytest.fixture(params=[
        pytest.param(
            TransportResult.failure("explicit-error", "fix-fail"),
            id="ok-false",
        ),
        pytest.param(
            SimpleNamespace(ok=True, parsed=None),
            id="parsed-empty",
        ),
    ])
    def fallback_result(self, request):
        """Fixture producing a TransportResult that triggers fallback."""
        return request.param

    def test_fallback_fixture_triggers_fallback(self, fallback_result):
        """Every fixture param must trigger should_fallback == True."""
        assert should_fallback(fallback_result) is True

    def test_fallback_fixture_ok_false(self):
        """Explicit fixture: ok=False -> should_fallback() == True."""
        result = TransportResult.failure("err", "s-fixture-1")
        assert should_fallback(result) is True

    def test_fallback_fixture_parsed_empty(self):
        """Explicit fixture: parsed=None -> should_fallback() == True."""
        result = SimpleNamespace(ok=True, parsed=None)
        assert should_fallback(result) is True


# --------------------------------------------------------------------------- #
# _build_topic helper (C-46)                                                  #
# --------------------------------------------------------------------------- #

class TestBuildTopic:
    """Topic construction with step_id prefix (C-46, R-42)."""

    def test_topic_contains_step_prefix(self, spec):
        """Topic starts with step:<step_id>:"""
        topic = _build_topic("abc", spec)
        assert topic.startswith("step:abc:")

    def test_topic_contains_command_head(self, spec):
        """Topic includes the command head (namespace:action format)."""
        topic = _build_topic("001", spec)
        # /blog:stockpile-status -> blog:stockpile-status
        assert "blog:stockpile-status" in topic

    def test_topic_simple_command(self):
        """Simple command (no namespace) produces clean topic."""
        simple_spec = CommandSpec(name="/qa:prep", model=ModelName.SONNET, position=1)
        topic = _build_topic("xyz", simple_spec)
        assert topic == "step:xyz:qa:prep"


# --------------------------------------------------------------------------- #
# Item 014 - neutral-kernel dispatch integration                              #
# --------------------------------------------------------------------------- #


class TestKernelDispatchIntegration:
    """Envelope -> kernel outcome -> TransportResult integration."""

    def test_delegate_command_with_kernel_dispatch_success(self, spec):
        captured = {}

        def kernel_runner(request):
            captured["request"] = request
            return {"terminal": "ok", "ok": True, "parsed": {"answer": "done"}}

        result = delegate_command(
            spec,
            Provider.CODEX,
            active_flags=[],
            step_id="kernel-success",
            dispatch_fn=build_kernel_dispatch(kernel_runner),
        )
        assert result.ok is True
        assert result.parsed == {"answer": "done"}
        assert captured["request"].topic.startswith("step:kernel-success:")
        assert captured["request"].provider == "codex"

    def test_delegate_command_with_kernel_dispatch_timeout_is_lost_step(self, spec):
        def kernel_runner(request):
            return {
                "terminal": "timeout",
                "ok": False,
                "parsed": None,
                "stderr": "timeout after 0.1s",
            }

        result = delegate_command(
            spec,
            Provider.CODEX,
            active_flags=[],
            step_id="kernel-timeout",
            dispatch_fn=build_kernel_dispatch(kernel_runner),
        )
        assert result == TransportResult.failure("timeout", "kernel-timeout")
        assert should_fallback(result) is True

    def test_delegate_command_with_kernel_empty_parsed_triggers_fallback(self, spec):
        def kernel_runner(request):
            return {
                "terminal": "empty-parsed",
                "ok": False,
                "parsed": None,
                "stderr": "provider returned no structured result",
            }

        result = delegate_command(
            spec,
            Provider.KIMI,
            active_flags=[],
            step_id="kernel-empty",
            dispatch_fn=build_kernel_dispatch(kernel_runner),
        )
        assert result.error == "empty-parsed"
        assert should_fallback(result) is True
