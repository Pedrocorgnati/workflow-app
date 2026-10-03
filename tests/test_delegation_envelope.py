"""Tests for delegation envelope (C8/C9) in command_queue_widget.py.

Covers:
- executor flag parsing (`--recovery-mode`, `--delegation-runtime=`);
- OPTIONAL delegation lines in Codex envelope (emitidas so quando ha o que
  declarar: flag armada e/ou runtime declarado pelo caller);
- byte-identical payload when no executor flag is present (C-35);
- coherence between `Delegation flags:` and `Arguments:` (R-38);
- `WARNING [delegation-degraded]` producer (C9).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
from workflow_app.command_queue.delegation_transport import (
    build_delegation_degraded_warning,
    DELEGATION_DEGRADED_REASONS,
    format_delegation_degraded_warning,
    Provider,
    TransportResult,
)


class TestSplitExecutorFlags:
    """`_split_executor_flags` removes executor flags from the target command."""

    def test_no_flags_unchanged(self) -> None:
        text = "/blog:init-strategy --foo bar"
        clean, runtime, recovery = CommandQueueWidget._split_executor_flags(text)
        assert clean == text
        # Sem `--delegation-runtime=` o caller NAO declarou runtime: `None`, e
        # nao um `kimi` inventado (o executor assume a propria identidade).
        assert runtime is None
        assert recovery is False

    @pytest.mark.parametrize(
        "text",
        [
            "  /blog:init-strategy   --foo  bar  ",
            "\t/blog:init-strategy --foo\tbar\t",
            "/blog:init-strategy\n--foo  bar\n",
        ],
    )
    def test_no_flags_preserves_every_byte(self, text: str) -> None:
        """C-35 inclui whitespace nao canonico, nao so o happy path."""
        clean, runtime, recovery = CommandQueueWidget._split_executor_flags(text)
        assert clean == text
        assert runtime is None
        assert recovery is False

    def test_only_intra_flag_unchanged(self) -> None:
        text = "/loop:iteraction:execute-task --task path.md --kimi"
        clean, runtime, recovery = CommandQueueWidget._split_executor_flags(text)
        assert clean == text
        # `--kimi` e flag INTRA-comando; nao declara runtime de delegacao.
        assert runtime is None
        assert recovery is False

    def test_default_runtime_is_opt_in(self) -> None:
        """`default_runtime` continua disponivel para callers que precisem."""
        text = "/blog:init-strategy"
        _, runtime, _ = CommandQueueWidget._split_executor_flags(
            text, default_runtime="kimi"
        )
        assert runtime == "kimi"

    def test_delegation_runtime_removed(self) -> None:
        text = "--delegation-runtime=codex /blog:init-strategy --foo bar"
        clean, runtime, recovery = CommandQueueWidget._split_executor_flags(text)
        assert clean == "/blog:init-strategy --foo bar"
        assert runtime == "codex"
        assert recovery is False

    def test_recovery_mode_removed(self) -> None:
        text = "--recovery-mode /tools:listener-recovery --context-file x.md"
        clean, runtime, recovery = CommandQueueWidget._split_executor_flags(text)
        assert clean == "/tools:listener-recovery --context-file x.md"
        assert runtime is None
        assert recovery is True

    def test_canonical_order_composition(self) -> None:
        text = "--recovery-mode --delegation-runtime=codex /blog:init-strategy --kimi"
        clean, runtime, recovery = CommandQueueWidget._split_executor_flags(text)
        assert clean == "/blog:init-strategy --kimi"
        assert runtime == "codex"
        assert recovery is True

    def test_invalid_runtime_not_removed(self) -> None:
        text = "--delegation-runtime=unknown /blog:init-strategy"
        clean, runtime, recovery = CommandQueueWidget._split_executor_flags(text)
        # Valor invalido nao e removido (fail-open; executor la embaixo bloqueia).
        assert clean == text
        assert runtime is None
        assert recovery is False

    def test_leading_whitespace_preserved(self) -> None:
        text = "  --delegation-runtime=grok /foo --bar"
        clean, runtime, recovery = CommandQueueWidget._split_executor_flags(text)
        assert clean == "  /foo --bar"
        assert runtime == "grok"

    def test_target_whitespace_preserved_after_executor_flags(self) -> None:
        text = "  --recovery-mode   --delegation-runtime=codex  /foo   --bar\tbaz  "
        clean, runtime, recovery = CommandQueueWidget._split_executor_flags(text)
        assert clean == "  /foo   --bar\tbaz  "
        assert runtime == "codex"
        assert recovery is True


class TestIntraCommandFlags:
    """`_intra_command_flags` extracts intra-command flags in order."""

    def test_empty(self) -> None:
        assert CommandQueueWidget._intra_command_flags("/foo") == []

    def test_kimi(self) -> None:
        assert CommandQueueWidget._intra_command_flags("/foo --kimi") == ["--kimi"]

    def test_codex(self) -> None:
        assert CommandQueueWidget._intra_command_flags("/foo --codex") == ["--codex"]

    def test_both_in_order(self) -> None:
        assert CommandQueueWidget._intra_command_flags("/foo --kimi --codex") == [
            "--kimi",
            "--codex",
        ]

    def test_dedup(self) -> None:
        assert CommandQueueWidget._intra_command_flags("/foo --kimi --kimi") == [
            "--kimi"
        ]

    def test_literals_are_derived_from_llm_flags(self) -> None:
        """O conjunto reconhecido e DERIVADO da fonte canonica, nao copiado."""
        from workflow_app.config.llm_flags import _FLAG_CANONICAL_ORDER

        assert CommandQueueWidget._intra_command_flag_literals() == tuple(
            _FLAG_CANONICAL_ORDER
        )


_WORKFLOW_APP_ROOT = Path(__file__).resolve().parents[1]

_LITERALS_PROBE = """import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from workflow_app.command_queue.command_queue_widget import CommandQueueWidget

print(json.dumps({
    "literals": list(CommandQueueWidget._intra_command_flag_literals()),
    "envelope_all": CommandQueueWidget._intra_command_flags(
        "/foo --opus --sonnet --codex --kimi --kimi-k3 --mimo-pro --qwen --grok"
    ),
}, sort_keys=True))
"""


def _run_literals_probe(value: str | None) -> dict:
    """Boot novo: o conjunto e congelado no import, mutar env depois nao prova nada."""
    env = os.environ.copy()
    env.pop("SF_LLM_FLAGS_V2", None)
    if value is not None:
        env["SF_LLM_FLAGS_V2"] = value
    result = subprocess.run(
        [sys.executable, "-c", _LITERALS_PROBE],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_WORKFLOW_APP_ROOT),
        check=False,
    )
    assert result.returncode == 0, (
        f"probe falhou (rc={result.returncode})\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return json.loads(result.stdout)


class TestIntraCommandFlagsPerRegime:
    """O envelope acompanha o conjunto vigente nos DOIS regimes de SF_LLM_FLAGS_V2."""

    def test_legacy_regime_literals(self) -> None:
        got = _run_literals_probe(None)
        # `--mimo` entra nos dois regimes (precedencia MiMo > Kimi, 2026-10-02).
        assert got["literals"] == ["--codex", "--mimo", "--kimi"], got
        # `--qwen`, `--grok`, `--kimi-k3` e `--mimo-pro` nao existem no regime
        # legado.
        assert got["envelope_all"] == ["--codex", "--kimi"], got

    def test_v2_regime_literals(self) -> None:
        got = _run_literals_probe("1")
        assert got["literals"] == [
            "--fable",
            "--opus",
            "--codex-ultra",
            "--mimo-pro",
            "--kimi-k3",
            "--grok-xhigh",
            "--grok",
            "--sonnet",
            "--mimo",
            "--kimi",
            "--qwen",
            "--codex",
        ], got
        # Ordem de aparicao no comando, nao a ordem canonica do modulo.
        assert got["envelope_all"] == [
            "--opus",
            "--sonnet",
            "--codex",
            "--kimi",
            "--kimi-k3",
            "--mimo-pro",
            "--qwen",
            "--grok",
        ], got


class TestCodexEnvelopeDelegationLines:
    """Envelope Codex so carrega as linhas de delegacao quando ha o que declarar.

    Quando presentes, elas vem imediatamente apos `Expected listener channel:`
    e antes de `Command:`/`Instruction:`.
    """

    def _envelope_for(self, text: str) -> str:
        result = CommandQueueWidget._build_codex_slash_executor_prompt(
            text, listener_channel="workspace_xterm"
        )
        assert result is not None
        return result

    def test_no_lines_when_nothing_to_declare(self) -> None:
        """Sem flag armada e sem runtime declarado, NENHUMA das duas linhas sai."""
        envelope = self._envelope_for("/blog:init-strategy --foo bar")
        lines = envelope.splitlines()
        channel_idx = lines.index("Expected listener channel: workspace_xterm")
        assert lines[channel_idx + 1] == "Command: /blog:init-strategy --foo bar"
        assert not any(line.startswith("Delegation flags:") for line in lines)
        assert not any(
            line.startswith("Executing runtime identity:") for line in lines
        )

    def test_only_flag_line_when_runtime_undeclared(self) -> None:
        """`--kimi` e intra-comando: declara flag, nao declara runtime."""
        envelope = self._envelope_for("/blog:init-strategy --kimi")
        lines = envelope.splitlines()
        channel_idx = lines.index("Expected listener channel: workspace_xterm")
        assert lines[channel_idx + 1] == "Delegation flags: --kimi"
        assert lines[channel_idx + 2] == "Command: /blog:init-strategy --kimi"
        assert not any(
            line.startswith("Executing runtime identity:") for line in lines
        )

    def test_only_runtime_line_when_no_flag_armed(self) -> None:
        envelope = self._envelope_for(
            "--delegation-runtime=codex /blog:init-strategy --foo bar"
        )
        lines = envelope.splitlines()
        channel_idx = lines.index("Expected listener channel: workspace_xterm")
        assert lines[channel_idx + 1] == "Executing runtime identity: codex"
        assert lines[channel_idx + 2] == "Command: /blog:init-strategy --foo bar"
        assert not any(line.startswith("Delegation flags:") for line in lines)

    def test_order_of_lines_with_runtime(self) -> None:
        envelope = self._envelope_for(
            "--delegation-runtime=codex /blog:init-strategy --codex"
        )
        lines = envelope.splitlines()
        channel_idx = lines.index("Expected listener channel: workspace_xterm")
        assert lines[channel_idx + 1] == "Delegation flags: --codex"
        assert lines[channel_idx + 2] == "Executing runtime identity: codex"
        assert lines[channel_idx + 3] == "Command: /blog:init-strategy --codex"
        # Arguments nao deve conter a flag de executor.
        args_line = lines[lines.index("Command: /blog:init-strategy --codex") + 2]
        assert args_line == "Arguments: --codex"

    def test_recovery_mode_kept_in_recovery_contract(self) -> None:
        envelope = CommandQueueWidget._build_codex_slash_executor_prompt(
            "--recovery-mode /tools:listener-recovery --context-file diag.md",
            listener_channel="interactive",
            recovery_mode=True,
        )
        assert envelope is not None
        lines = envelope.splitlines()
        channel_idx = lines.index("Expected listener channel: interactive")
        # `--recovery-mode` nao declara flag nem runtime: bloco vazio.
        assert lines[channel_idx + 1] == "Recovery mode: enabled by caller"
        assert "Command: /tools:listener-recovery --context-file diag.md" in lines
        assert not any(line.startswith("Delegation flags:") for line in lines)
        assert not any(
            line.startswith("Executing runtime identity:") for line in lines
        )

    def test_coherence_flags_match_arguments(self) -> None:
        """R-38: when Delegation flags has --kimi, Arguments also has --kimi."""
        envelope = self._envelope_for(
            "--delegation-runtime=codex /blog:init-strategy --kimi --bar"
        )
        lines = envelope.splitlines()
        delegation_line = next(
            line for line in lines if line.startswith("Delegation flags:")
        )
        args_line = next(line for line in lines if line.startswith("Arguments:"))
        assert delegation_line == "Delegation flags: --kimi"
        assert "--kimi" in args_line
        assert "Command: /blog:init-strategy --kimi --bar" in lines
        assert "--delegation-runtime" not in args_line
        assert "--recovery-mode" not in args_line

    def test_arguments_without_executor_flags(self) -> None:
        envelope = self._envelope_for(
            "--recovery-mode --delegation-runtime=codex /blog:init-strategy --bar"
        )
        lines = envelope.splitlines()
        args_line = next(line for line in lines if line.startswith("Arguments:"))
        assert args_line == "Arguments: --bar"
        assert "Command: /blog:init-strategy --bar" in lines


class TestCodexEnvelopeIdentity:
    """C-35: payload byte-identical when no executor flag is present."""

    def test_payload_identical_without_executor_flags(self) -> None:
        """C-35: sem flag de executor, o envelope volta a ser o de antes do C8.

        As duas linhas do bloco de delegacao sao OPCIONAIS. Sem flag armada e
        sem runtime declarado, `Command:` cola direto em `Expected listener
        channel:` e nenhum byte novo entra no payload.
        """
        text = "/blog:init-strategy --foo bar"
        envelope = CommandQueueWidget._build_codex_slash_executor_prompt(
            text, listener_channel="interactive"
        )
        assert envelope is not None
        assert (
            f"Expected listener channel: interactive\nCommand: {text}\n" in envelope
        )
        assert "Delegation flags:" not in envelope
        assert "Executing runtime identity:" not in envelope


class TestCustomPromptEnvelope:
    """Custom-prompt directive envelope also carries delegation lines."""

    def test_goal_envelope_lines(self) -> None:
        envelope = CommandQueueWidget._build_codex_custom_prompt_prompt(
            "/goal --kimi run prompt module 8 using .claude/projects/x.json",
            listener_channel="interactive",
        )
        assert envelope is not None
        lines = envelope.splitlines()
        channel_idx = lines.index("Expected listener channel: interactive")
        assert lines[channel_idx + 1] == "Delegation flags: --kimi"
        # Nenhum `--delegation-runtime=` foi declarado: a linha de identidade
        # nao e inventada.
        assert lines[channel_idx + 2].startswith("Instruction:")
        assert not any(
            line.startswith("Executing runtime identity:") for line in lines
        )

    def test_goal_envelope_with_declared_runtime(self) -> None:
        envelope = CommandQueueWidget._build_codex_custom_prompt_prompt(
            "--delegation-runtime=grok /goal --kimi run prompt module 8 "
            "using .claude/projects/x.json",
            listener_channel="interactive",
        )
        assert envelope is not None
        lines = envelope.splitlines()
        channel_idx = lines.index("Expected listener channel: interactive")
        assert lines[channel_idx + 1] == "Delegation flags: --kimi"
        assert lines[channel_idx + 2] == "Executing runtime identity: grok"
        assert lines[channel_idx + 3].startswith("Instruction:")


class TestDelegationDegradedWarning:
    """C9: canonical WARNING [delegation-degraded] producer."""

    def test_format_exact_literal(self) -> None:
        warning = format_delegation_degraded_warning("s1", "codex", "no-transport")
        assert warning == (
            "WARNING [delegation-degraded] step_id=s1 "
            "provider=codex reason=no-transport"
        )

    @pytest.mark.parametrize("reason", DELEGATION_DEGRADED_REASONS)
    def test_reason_codes_canonical(self, reason: str) -> None:
        warning = format_delegation_degraded_warning("x", "kimi", reason)
        assert warning.startswith("WARNING [delegation-degraded]")
        assert f"reason={reason}" in warning

    def test_build_warning_from_transport_result(self) -> None:
        result = TransportResult.failure("credential missing for provider", "step-42")
        warning = build_delegation_degraded_warning(result, Provider.CODEX)
        assert warning == (
            "WARNING [delegation-degraded] step_id=step-42 "
            "provider=codex reason=credential-missing"
        )

    def test_build_warning_no_transport(self) -> None:
        result = TransportResult.failure("dispatch-not-configured", "step-7")
        warning = build_delegation_degraded_warning(result, Provider.KIMI)
        assert "reason=no-transport" in warning
