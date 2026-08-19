"""Provider bridge kernel — equivalence oracle, terminal results and telemetry.

Source of truth: blacksmith/loop-archives/08-11-llm-config-multillm-expansion/
source.md lines 470-493 (item 014).

Structure mirrors the item's implementation steps:

  ST001  frozen argv oracle captured from the legacy bridge (must stay green
         against the untouched module before any code moves).
  ST002  neutral kernel: terminal outcomes, argv-list-only contract, no
         provider-caller coupling in the source.
  ST003  thin per-provider adapters (argv + env only).
  ST004  telemetry with the C-53 fields.
  ST005  legacy wrapper delegating to the kernel with proven equivalence
         (same argv, same stdout shape, same exit code).

Criteria addressed: C-53, C-47, R-41, R-43, R-50.
No real provider binary is ever invoked: ``subprocess.run`` and
``shutil.which`` are always monkeypatched.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
BRIDGE_PATH = REPO_ROOT / ".codex" / "skills" / "_lib" / "codex_provider_bridge.py"
KERNEL_PATH = REPO_ROOT / "ai-forge" / "scripts" / "_provider_bridge_kernel.py"
ADAPTERS_PATH = REPO_ROOT / "ai-forge" / "scripts" / "_provider_adapters.py"

# Deterministic binary paths substituted for shutil.which during the tests.
FAKE_CLAUDE_BIN = "/usr/bin/claude"
FAKE_KIMI_BIN = "/usr/bin/kimi"
FAKE_GROK_BIN = "/usr/bin/grok"

# The prompt is an *input* to argv construction, never rendered by it.
FROZEN_PROMPT = "PROMPT-BODY"


def test_c47_executable_provider_invocations_never_use_shell_strings() -> None:
    """C-47 targets executable calls; documentary CLI examples are out of scope."""

    process_paths = (KERNEL_PATH, ADAPTERS_PATH, BRIDGE_PATH)
    process_functions = {"run", "Popen", "call", "check_call", "check_output"}
    violations: list[str] = []
    for path in process_paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function_name = node.func.attr if isinstance(node.func, ast.Attribute) else None
            if function_name not in process_functions:
                continue
            for keyword in node.keywords:
                if keyword.arg == "shell" and isinstance(keyword.value, ast.Constant) and keyword.value.value is True:
                    violations.append(f"{path}:{node.lineno}:shell=True")
            if node.args and isinstance(node.args[0], ast.Constant) and isinstance(node.args[0].value, str):
                violations.append(f"{path}:{node.lineno}:string-command")
    assert violations == []


def _load_module(name: str, path: Path):
    """Load a module by file location (same pattern as t13-smoke-agent-path.py)."""
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise RuntimeError(f"cannot load {name} from {path}")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def bridge():
    return _load_module("codex_provider_bridge", BRIDGE_PATH)


@pytest.fixture(scope="module")
def kernel():
    if not KERNEL_PATH.is_file():
        pytest.skip(f"kernel not present yet: {KERNEL_PATH}")
    return _load_module("_provider_bridge_kernel", KERNEL_PATH)


@pytest.fixture(scope="module")
def adapters():
    if not ADAPTERS_PATH.is_file():
        pytest.skip(f"adapters not present yet: {ADAPTERS_PATH}")
    return _load_module("_provider_adapters", ADAPTERS_PATH)


@pytest.fixture
def which_stub(monkeypatch):
    """Deterministic shutil.which for claude/kimi; None for anything else."""

    def _which(name: str, *args: Any, **kwargs: Any) -> str | None:
        return {
            "claude": FAKE_CLAUDE_BIN,
            "kimi": FAKE_KIMI_BIN,
            "grok": FAKE_GROK_BIN,
        }.get(name)

    monkeypatch.setattr("shutil.which", _which)
    return _which


def _args(bridge, *argv: str):
    """Build a parsed Namespace through the real CLI surface."""
    base = [
        "--topic",
        "step:42:qa:trace",
        "--topic-type",
        "decision",
        "--focus",
        "ai-forge/scripts/_provider_bridge_kernel.py",
        "--caller",
        "codex",
        "--registry",
        "codex-personas",
    ]
    return bridge.parse_args([*base, *argv])


# --------------------------------------------------------------------------
# ST001 - frozen argv oracle (runs against the untouched legacy module)
# --------------------------------------------------------------------------


EXPECTED_CLAUDE_ARGV_LEVEL2 = [
    FAKE_CLAUDE_BIN,
    "--print",
    "--output-format",
    "json",
    "--model",
    "sonnet",
    "--effort",
    "medium",
    "--tools",
    "",
    "--no-session-persistence",
    FROZEN_PROMPT,
]

EXPECTED_CLAUDE_ARGV_LEVEL3 = [
    FAKE_CLAUDE_BIN,
    "--print",
    "--output-format",
    "json",
    "--model",
    "sonnet",
    "--effort",
    "high",
    "--tools",
    "",
    "--no-session-persistence",
    FROZEN_PROMPT,
]

EXPECTED_KIMI_ARGV_LEVEL2 = [
    FAKE_KIMI_BIN,
    "--print",
    "--output-format",
    "text",
    "--max-ralph-iterations",
    "0",
    "--model",
    "kimi-code/kimi-for-coding",
    "--no-thinking",
    "--prompt",
    FROZEN_PROMPT,
]

EXPECTED_KIMI_ARGV_LEVEL3 = [
    FAKE_KIMI_BIN,
    "--print",
    "--output-format",
    "text",
    "--max-ralph-iterations",
    "0",
    "--model",
    "kimi-code/kimi-for-coding",
    "--thinking",
    "--prompt",
    FROZEN_PROMPT,
]

EXPECTED_GROK_ARGV = [
    FAKE_GROK_BIN,
    "--single",
    FROZEN_PROMPT,
    "--model",
    "grok-4.5",
    "--output-format",
    "json",
    "--always-approve",
]

# sha256 of the rendered provider prompt for the frozen args below, with no
# agent block. Freezes the caller identity phrase plus the output contract.
FROZEN_RENDER_SHA256 = (
    "c665ab99acc16073d9e1b4b9776f25acd304896a0ae87c62e833114127258564"
)


class TestST001FrozenArgv:
    """The legacy argv is the equivalence oracle (D014-e)."""

    def test_legacy_argv_claude_frozen(self, bridge, which_stub):
        args = _args(bridge, "--provider", "claude", "--level", "2")
        spec = bridge._spec_for_provider("claude", args, FROZEN_PROMPT)
        assert spec.command == EXPECTED_CLAUDE_ARGV_LEVEL2
        assert spec.name == "claude"
        assert spec.model == "sonnet"

    def test_legacy_argv_claude_level3_frozen(self, bridge, which_stub):
        args = _args(bridge, "--provider", "claude", "--level", "3")
        spec = bridge._spec_for_provider("claude", args, FROZEN_PROMPT)
        assert spec.command == EXPECTED_CLAUDE_ARGV_LEVEL3

    def test_legacy_argv_kimi_frozen(self, bridge, which_stub):
        args = _args(bridge, "--provider", "kimi", "--level", "2")
        spec = bridge._spec_for_provider("kimi", args, FROZEN_PROMPT)
        assert spec.command == EXPECTED_KIMI_ARGV_LEVEL2
        assert spec.name == "kimi"
        assert spec.model == "kimi-code/kimi-for-coding"

    def test_legacy_argv_kimi_thinking_frozen(self, bridge, which_stub):
        args = _args(bridge, "--provider", "kimi", "--level", "3")
        spec = bridge._spec_for_provider("kimi", args, FROZEN_PROMPT)
        assert spec.command == EXPECTED_KIMI_ARGV_LEVEL3

    def test_legacy_argv_kimi_thinking_flag_frozen(self, bridge, which_stub):
        args = _args(bridge, "--provider", "kimi", "--level", "2", "--kimi-thinking")
        spec = bridge._spec_for_provider("kimi", args, FROZEN_PROMPT)
        assert spec.command == EXPECTED_KIMI_ARGV_LEVEL3

    def test_legacy_argv_dual_frozen(self, bridge, which_stub):
        args = _args(bridge, "--provider", "dual", "--level", "2")
        specs = [
            bridge._spec_for_provider(provider, args, FROZEN_PROMPT)
            for provider in ("claude", "kimi")
        ]
        assert [s.command for s in specs] == [
            EXPECTED_CLAUDE_ARGV_LEVEL2,
            EXPECTED_KIMI_ARGV_LEVEL2,
        ]

    def test_legacy_argv_is_list_of_str(self, bridge, which_stub):
        """R-43: transport is a list of argv, never a shell string."""
        args = _args(bridge, "--provider", "claude", "--level", "2")
        spec = bridge._spec_for_provider("claude", args, FROZEN_PROMPT)
        assert isinstance(spec.command, list)
        assert all(isinstance(part, str) for part in spec.command)

    def test_legacy_argv_unknown_provider_raises(self, bridge, which_stub):
        """`grok` agora e conhecido; o papel de provider desconhecido foi
        transferido para ``definitely-nonexistent-provider``."""
        args = _args(bridge, "--provider", "claude", "--level", "2")
        with pytest.raises(ValueError):
            bridge._spec_for_provider("definitely-nonexistent-provider", args, FROZEN_PROMPT)

    def test_legacy_provider_prompt_frozen(self, bridge):
        """The caller identity phrase and the output contract are frozen."""
        args = _args(bridge, "--provider", "claude", "--level", "2")
        args._agent_meta = None
        rendered = bridge._build_provider_prompt(args, "TASK TEXT")
        assert rendered.startswith(
            "You are an external reviewer called by Codex inside SystemForge.\n"
        )
        assert '"Return only JSON. No markdown fences."' in rendered
        assert '"Advisory only: do not edit files and do not run commands."' in rendered
        assert rendered.rstrip().endswith("TASK TEXT")
        # Whole-render digest: any silent drift in contract or context fails here.
        digest = hashlib.sha256(rendered.encode("utf-8")).hexdigest()
        assert digest == FROZEN_RENDER_SHA256, (
            f"provider prompt drifted; got {digest}"
        )

    def test_legacy_env_claude_strips_anthropic_prefixes(self, bridge, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-be-stripped")
        monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
        monkeypatch.setenv("PATH_KEEPER_SENTINEL", "keep-me")
        env = bridge._env_for_provider("claude")
        assert "ANTHROPIC_API_KEY" not in env
        assert "CLAUDE_CODE_USE_BEDROCK" not in env
        assert env["PATH_KEEPER_SENTINEL"] == "keep-me"

    def test_legacy_env_kimi_is_untouched(self, bridge, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-kept-for-kimi")
        env = bridge._env_for_provider("kimi")
        assert env["ANTHROPIC_API_KEY"] == "sk-kept-for-kimi"


# --------------------------------------------------------------------------
# ST002 - neutral kernel: terminal taxonomy, argv-only contract, no coupling
# --------------------------------------------------------------------------


def _spec(kernel, command: list[str] | Any = None):
    return kernel.ProviderSpec("claude", "sonnet", command or [FAKE_CLAUDE_BIN, "--print"])


class _Completed:
    def __init__(self, returncode: int, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class TestST002TerminalResults:
    """R-41: every way an invocation can end has its own terminal label."""

    def test_terminal_ok(self, kernel):
        out = kernel.run_provider(
            _spec(kernel),
            cwd=".",
            timeout=5,
            runner=lambda *a, **kw: _Completed(0, json.dumps({"verdict": "approve"})),
        )
        assert out["terminal"] == kernel.TERMINAL_OK
        assert out["ok"] is True
        assert out["parsed"] == {"verdict": "approve"}

    def test_terminal_empty_parsed_is_not_ok(self, kernel):
        """C-53: rc 0 with nothing parseable is a failure, not a success."""
        out = kernel.run_provider(
            _spec(kernel), cwd=".", timeout=5, runner=lambda *a, **kw: _Completed(0, "   ")
        )
        assert out["terminal"] == kernel.TERMINAL_EMPTY_PARSED
        assert out["ok"] is False

    def test_terminal_empty_parsed_on_empty_json_object(self, kernel):
        out = kernel.run_provider(
            _spec(kernel), cwd=".", timeout=5, runner=lambda *a, **kw: _Completed(0, "{}")
        )
        assert out["terminal"] == kernel.TERMINAL_EMPTY_PARSED
        assert out["ok"] is False

    def test_terminal_exit_nonzero(self, kernel):
        out = kernel.run_provider(
            _spec(kernel), cwd=".", timeout=5, runner=lambda *a, **kw: _Completed(2, "", "boom")
        )
        assert out["terminal"] == kernel.TERMINAL_EXIT_NONZERO
        assert out["ok"] is False
        assert out["returncode"] == 2

    def test_terminal_timeout_is_its_own_result(self, kernel):
        """R-41: a timeout must not be reported as a generic error."""

        def _raise(*a: Any, **kw: Any):
            raise subprocess.TimeoutExpired(cmd=[FAKE_CLAUDE_BIN], timeout=5)

        out = kernel.run_provider(_spec(kernel), cwd=".", timeout=5, runner=_raise)
        assert out["terminal"] == kernel.TERMINAL_TIMEOUT
        assert out["ok"] is False

    def test_terminal_binary_missing(self, kernel):
        def _raise(*a: Any, **kw: Any):
            raise FileNotFoundError("claude binary not found in PATH")

        out = kernel.run_provider(_spec(kernel), cwd=".", timeout=5, runner=_raise)
        assert out["terminal"] == kernel.TERMINAL_BINARY_MISSING
        assert out["ok"] is False

    def test_terminal_error_catch_all(self, kernel):
        def _raise(*a: Any, **kw: Any):
            raise RuntimeError("unexpected")

        out = kernel.run_provider(_spec(kernel), cwd=".", timeout=5, runner=_raise)
        assert out["terminal"] == kernel.TERMINAL_ERROR
        assert out["ok"] is False

    def test_terminal_taxonomy_is_exhaustive(self, kernel):
        assert set(kernel.TERMINAL_RESULTS) == {
            kernel.TERMINAL_OK,
            kernel.TERMINAL_EMPTY_PARSED,
            kernel.TERMINAL_EXIT_NONZERO,
            kernel.TERMINAL_TIMEOUT,
            kernel.TERMINAL_BINARY_MISSING,
            kernel.TERMINAL_ERROR,
        }

    def test_kernel_rejects_string_command(self, kernel):
        """C-47 / R-43: a shell string is never a valid transport."""
        with pytest.raises(TypeError):
            kernel.run_provider(
                kernel.ProviderSpec("claude", "sonnet", f"{FAKE_CLAUDE_BIN} --print"),
                cwd=".",
                timeout=5,
                runner=lambda *a, **kw: _Completed(0, "{}"),
            )

    def test_kernel_rejects_non_str_argv_parts(self, kernel):
        with pytest.raises(TypeError):
            kernel.run_provider(
                kernel.ProviderSpec("claude", "sonnet", [FAKE_CLAUDE_BIN, 2]),
                cwd=".",
                timeout=5,
                runner=lambda *a, **kw: _Completed(0, "{}"),
            )

    def test_kernel_never_uses_shell(self, kernel):
        seen: dict[str, Any] = {}

        def _runner(cmd: Any, **kwargs: Any):
            seen["cmd"] = cmd
            seen["kwargs"] = kwargs
            return _Completed(0, "{\"verdict\": \"approve\"}")

        kernel.run_provider(_spec(kernel), cwd=".", timeout=5, runner=_runner)
        assert isinstance(seen["cmd"], list)
        assert seen["kwargs"].get("shell", False) is False
        assert seen["kwargs"]["timeout"] == 5
        assert seen["kwargs"]["check"] is False

    def test_kernel_has_no_codex_coupling(self):
        """R-50: no Codex-specific text may live in the neutral kernel."""
        source = KERNEL_PATH.read_text(encoding="utf-8")
        for needle in (
            "called by Codex",
            "Codex is final executor",
            "codex-provider-bridge",
        ):
            assert needle not in source, f"kernel leaks caller-specific text: {needle!r}"

    def test_kernel_has_no_provider_argv(self):
        """Adapters own argv; the kernel must not know any provider's flags."""
        source = KERNEL_PATH.read_text(encoding="utf-8")
        for needle in ("--no-session-persistence", "--max-ralph-iterations", "--kimi-thinking"):
            assert needle not in source, f"kernel leaks provider argv: {needle!r}"


# --------------------------------------------------------------------------
# ST003 - thin per-provider adapters
# --------------------------------------------------------------------------


class TestST003Adapters:
    def test_adapter_claude_argv_matches_frozen(self, adapters, kernel, which_stub):
        spec = adapters.get_adapter("claude").build_spec(kernel.SpecParams(prompt=FROZEN_PROMPT))
        assert spec.command == EXPECTED_CLAUDE_ARGV_LEVEL2

    def test_adapter_kimi_argv_matches_frozen(self, adapters, kernel, which_stub):
        spec = adapters.get_adapter("kimi").build_spec(kernel.SpecParams(prompt=FROZEN_PROMPT))
        assert spec.command == EXPECTED_KIMI_ARGV_LEVEL2

    def test_adapter_codex_uses_spec_params_cwd_not_process_cwd(
        self, adapters, kernel, monkeypatch, tmp_path
    ):
        """`--cd` comes from SpecParams.cwd, never from a second Path.cwd() read."""
        monkeypatch.setattr("shutil.which", lambda name, *a, **kw: f"/usr/local/bin/{name}")
        spec = adapters.get_adapter("codex").build_spec(
            kernel.SpecParams(prompt=FROZEN_PROMPT, cwd=str(tmp_path))
        )
        cd_value = spec.command[spec.command.index("--cd") + 1]
        assert cd_value == str(tmp_path.resolve())
        assert cd_value != str(Path.cwd().resolve())
        assert spec.command[spec.command.index("--sandbox") + 1] == "danger-full-access"

    def test_adapter_codex_model_default_exists_on_machine(self, adapters, kernel, monkeypatch):
        """Default model must be the one declared in ~/.codex/config.toml."""
        monkeypatch.setattr("shutil.which", lambda name, *a, **kw: f"/usr/local/bin/{name}")
        spec = adapters.get_adapter("codex").build_spec(kernel.SpecParams(prompt=FROZEN_PROMPT))
        assert spec.model == "gpt-5.3-codex-spark"
        assert spec.command[spec.command.index("--model") + 1] == "gpt-5.3-codex-spark"

    def test_adapter_unknown_provider_raises(self, adapters):
        """`grok` agora e conhecido; o literal substituto e
        ``definitely-nonexistent-provider``."""
        with pytest.raises(ValueError):
            adapters.get_adapter("definitely-nonexistent-provider")

    def test_adapter_missing_binary_raises_filenotfound(self, adapters, kernel, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda *a, **kw: None)
        with pytest.raises(FileNotFoundError):
            adapters.get_adapter("claude").build_spec(kernel.SpecParams(prompt=FROZEN_PROMPT))

    def test_dual_expands_deterministically(self, adapters):
        assert adapters.expand_providers("dual") == ("claude", "kimi")
        assert adapters.expand_providers("claude") == ("claude",)

    def test_adapter_claude_env_strips_anthropic_prefixes(self, adapters, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-should-be-stripped")
        monkeypatch.setenv("KEEP_ME_SENTINEL", "1")
        env = adapters.get_adapter("claude").env()
        assert "ANTHROPIC_API_KEY" not in env
        assert env["KEEP_ME_SENTINEL"] == "1"

    def test_adapter_env_kimi_untouched(self, adapters, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-kept-for-kimi")
        assert adapters.get_adapter("kimi").env()["ANTHROPIC_API_KEY"] == "sk-kept-for-kimi"

    def test_adapter_grok_argv_matches_frozen(self, adapters, kernel, which_stub):
        spec = adapters.get_adapter("grok").build_spec(kernel.SpecParams(prompt=FROZEN_PROMPT))
        assert spec.command == EXPECTED_GROK_ARGV
        assert spec.name == "grok"
        assert spec.model == "grok-4.5"

    def test_adapter_grok_env_is_normalized_copy(self, adapters, monkeypatch):
        """Grok env is a normalized copy of the base env (no secret stripping)."""
        monkeypatch.setenv("GROK_API_KEY", "sk-kept-for-grok")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-kept-for-grok-too")
        env = adapters.get_adapter("grok").env()
        assert env["GROK_API_KEY"] == "sk-kept-for-grok"
        assert env["ANTHROPIC_API_KEY"] == "sk-kept-for-grok-too"

    def test_adapter_grok_missing_binary_raises_filenotfound(self, adapters, kernel, monkeypatch):
        monkeypatch.setattr("shutil.which", lambda *a, **kw: None)
        with pytest.raises(FileNotFoundError):
            adapters.get_adapter("grok").build_spec(kernel.SpecParams(prompt=FROZEN_PROMPT))

    def test_adapters_own_no_transport(self):
        """An adapter that runs a subprocess is a layering violation."""
        source = ADAPTERS_PATH.read_text(encoding="utf-8")
        for needle in ("subprocess.run", "TimeoutExpired", "emit_telemetry"):
            assert needle not in source, f"adapter owns transport/telemetry: {needle!r}"


# --------------------------------------------------------------------------
# ST004 - telemetry (C-53)
# --------------------------------------------------------------------------


def _record(kernel, **overrides: Any):
    base = dict(
        skill_id="codex-provider-bridge",
        provider="dual",
        registry="mcp-agents",
        agent_slug="hardening-engineer-rules",
        agent_path_hash8="deadbeef",
        version="epoch-1",
        exit_code=0,
        caller_runtime="codex",
        requested_provider="dual",
        actual_binary=FAKE_CLAUDE_BIN,
        provider_used="claude",
    )
    base.update(overrides)
    return kernel.TelemetryRecord(**base)


class TestST004Telemetry:
    def test_telemetry_has_c53_fields(self, kernel):
        payload = _record(kernel).as_dict()
        for field in kernel.C53_FIELDS:
            assert field in payload, f"missing C-53 field: {field}"

    def test_telemetry_preserves_t13_fields(self, kernel):
        payload = _record(kernel).as_dict()
        for field in kernel.T13_FIELDS:
            assert field in payload, f"T13 H9 field dropped: {field}"

    def test_telemetry_caller_runtime_distinct_from_requested_provider(self, kernel):
        payload = _record(kernel, caller_runtime="codex", requested_provider="claude").as_dict()
        assert payload["caller_runtime"] == "codex"
        assert payload["requested_provider"] == "claude"

    def test_telemetry_c53_fields_are_mandatory(self, kernel):
        """A record cannot be built without the C-53 fields (fail-closed, G4)."""
        with pytest.raises(TypeError):
            kernel.TelemetryRecord(
                skill_id="x",
                provider="claude",
                registry="mcp-agents",
                agent_slug=None,
                agent_path_hash8=None,
                version=None,
                exit_code=0,
            )

    def test_telemetry_is_pii_free(self, kernel):
        payload = _record(kernel).as_dict()
        assert "prompt" not in payload
        assert "focus" not in payload
        assert "topic" not in payload

    def test_telemetry_actual_binary_reflects_what_ran(self, kernel):
        outputs = [
            {"provider": "claude", "ok": True, "binary": FAKE_CLAUDE_BIN},
            {"provider": "kimi", "ok": False, "binary": FAKE_KIMI_BIN},
        ]
        assert kernel.binaries_invoked(outputs) == f"{FAKE_CLAUDE_BIN},{FAKE_KIMI_BIN}"
        assert kernel.providers_used(outputs) == "claude"

    def test_telemetry_success_requires_parsed(self, kernel):
        """C-53: exit_code 0 is only reachable when something was parsed."""
        out = kernel.run_provider(
            _spec(kernel), cwd=".", timeout=5, runner=lambda *a, **kw: _Completed(0, "no json here")
        )
        result = kernel.build_result(
            kernel.ResultMeta(
                bridge="b", provider="claude", mode="stereo", level=2,
                topic="t", topic_type="decision", focus="f", consensus_rule="r",
            ),
            [out],
        )
        assert result["ok"] is False
        assert kernel.providers_used([out]) is None

    def test_telemetry_grok_outcome_has_c53_fields(self, kernel):
        """Grok invocation through the kernel carries C-53 telemetry fields."""
        spec = kernel.ProviderSpec("grok", "grok-4.5", EXPECTED_GROK_ARGV)
        out = kernel.run_provider(
            spec,
            cwd=".",
            timeout=5,
            runner=lambda *a, **kw: _Completed(0, json.dumps({"verdict": "approve"})),
        )
        assert out["terminal"] == kernel.TERMINAL_OK
        assert out["ok"] is True
        assert out["provider"] == "grok"
        assert out["binary"] == FAKE_GROK_BIN
        assert out["returncode"] == 0

    def test_telemetry_disabled_writes_nothing(self, kernel, tmp_path):
        assert kernel.emit_telemetry(_record(kernel), telemetry_dir="", cwd=str(tmp_path)) is None


# --------------------------------------------------------------------------
# ST005 - legacy wrapper equivalence (D014-e)
# --------------------------------------------------------------------------


class TestST005WrapperEquivalence:
    """The wrapper still builds the frozen argv, now through the kernel."""

    def test_wrapper_argv_equivalence_claude(self, bridge, adapters, kernel, which_stub):
        args = _args(bridge, "--provider", "claude", "--level", "3")
        assert bridge._spec_for_provider("claude", args, FROZEN_PROMPT).command == (
            adapters.get_adapter("claude")
            .build_spec(kernel.SpecParams(prompt=FROZEN_PROMPT, level=3))
            .command
        )

    def test_wrapper_argv_equivalence_kimi(self, bridge, adapters, kernel, which_stub):
        args = _args(bridge, "--provider", "kimi", "--level", "2", "--kimi-thinking")
        assert bridge._spec_for_provider("kimi", args, FROZEN_PROMPT).command == (
            adapters.get_adapter("kimi")
            .build_spec(kernel.SpecParams(prompt=FROZEN_PROMPT, kimi_thinking=True))
            .command
        )

    def test_wrapper_argv_equivalence_dual(self, bridge, which_stub):
        args = _args(bridge, "--provider", "dual", "--level", "2")
        commands = [
            bridge._spec_for_provider(p, args, FROZEN_PROMPT).command
            for p in ("claude", "kimi")
        ]
        assert commands == [EXPECTED_CLAUDE_ARGV_LEVEL2, EXPECTED_KIMI_ARGV_LEVEL2]

    def test_wrapper_keeps_codex_identity(self, bridge):
        """R-50 inverted: the Codex text stays in the wrapper, not the kernel."""
        source = BRIDGE_PATH.read_text(encoding="utf-8")
        assert "You are an external reviewer called by Codex inside SystemForge." in source
        assert "Codex is final executor; use provider outputs as advisory evidence." in source

    def test_wrapper_stdout_shape_unchanged(self, bridge, which_stub, monkeypatch, capsys):
        args = _args(bridge, "--provider", "claude", "--level", "2", "--prompt", "hi")
        monkeypatch.setattr(
            "subprocess.run",
            lambda *a, **kw: _Completed(0, json.dumps({"verdict": "approve", "summary": "ok"})),
        )
        monkeypatch.setattr(bridge, "parse_args", lambda argv: args)
        args.telemetry_dir = ""
        exit_code = bridge.main([])
        payload = json.loads(capsys.readouterr().out)
        assert exit_code == 0
        assert payload["bridge"] == "codex-provider-bridge"
        assert payload["ok"] is True
        assert payload["summary"] == "ok"
        assert payload["provider_outputs"][0]["provider"] == "claude"
        assert payload["provider_outputs"][0]["terminal"] == "ok"
        assert payload["degraded"] is False

    def test_wrapper_exit_code_unchanged_on_success_and_failure(
        self, bridge, which_stub, monkeypatch, capsys
    ):
        """ST005/D014-e: `main` keeps `0 if ok else 1` on both branches."""
        ok_args = _args(bridge, "--provider", "claude", "--level", "2", "--prompt", "hi")
        ok_args.telemetry_dir = ""
        monkeypatch.setattr(
            "subprocess.run",
            lambda *a, **kw: _Completed(0, json.dumps({"verdict": "approve", "summary": "ok"})),
        )
        monkeypatch.setattr(bridge, "parse_args", lambda argv: ok_args)
        assert bridge.main([]) == 0
        assert json.loads(capsys.readouterr().out)["ok"] is True

        fail_args = _args(bridge, "--provider", "claude", "--level", "2", "--prompt", "hi")
        fail_args.telemetry_dir = ""
        monkeypatch.setattr("subprocess.run", lambda *a, **kw: _Completed(3, "", "boom"))
        monkeypatch.setattr(bridge, "parse_args", lambda argv: fail_args)
        exit_code = bridge.main([])
        payload = json.loads(capsys.readouterr().out)
        assert exit_code == 1
        assert payload["ok"] is False

    def test_wrapper_resolve_only_unchanged(self, bridge, monkeypatch, capsys):
        args = _args(bridge, "--provider", "claude", "--level", "2", "--resolve-only")
        args.telemetry_dir = ""
        monkeypatch.setattr(bridge, "parse_args", lambda argv: args)
        exit_code = bridge.main([])
        payload = json.loads(capsys.readouterr().out)
        assert exit_code == 0
        assert payload["ok"] is True
        assert payload["registry"] == "codex-personas"

    def test_wrapper_keeps_importable_names(self, bridge):
        """Other callers import these from this path (R-50)."""
        for name in (
            "parse_args",
            "main",
            "_resolve_agent_path",
            "_agent_race_guard",
            "_agent_frontmatter_check",
            "_agent_repo_root",
            "_build_provider_prompt",
            "_spec_for_provider",
            "_env_for_provider",
            "_run_provider",
            "_build_result",
            "_extract_json",
            "_divergence_score",
            "_read_prompt",
            "_resolve_default_agent_from_registry",
            "_emit_telemetry",
            "_now",
            "ProviderSpec",
            "DEFAULT_TIMEOUT_SECONDS",
            "REGISTRY_CHOICES",
            "AGENT_PATH_REGEX",
        ):
            assert hasattr(bridge, name), f"wrapper dropped public name: {name}"
