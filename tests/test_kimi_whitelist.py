"""Pure-logic tests for the Claude→Kimi command adapter and whitelist."""

from __future__ import annotations

import pytest

from workflow_app.command_queue.kimi_whitelist import (
    KIMI_COMPATIBLE_COMMANDS,
    adapt_to_kimi,
    is_kimi_compatible,
)


class TestWhitelist:
    def test_whitelist_size_matches_progress_md(self):
        # progress.md tem 36 KIMI_OK + 1 KIMI_PREFERRED = 37 comandos
        assert len(KIMI_COMPATIBLE_COMMANDS) == 37

    def test_known_compatible_commands(self):
        for cmd in ("/secrets-scan", "/qa:prep", "/env-creation", "/sync:github"):
            assert is_kimi_compatible(cmd), f"{cmd} should be Kimi-compatible"

    def test_known_incompatible_commands(self):
        # Comandos KEEP_CLAUDE de progress.md
        for cmd in (
            "/review-executed-module",
            "/qa:trace",
            "/validate-roles",
            "/validate-billing",
            "/execute-task",
            "/back-end-build",
            "/front-end-build",
            "/build-verify",
            "/gate:frontend-runtime",
            "/commit:simple",
        ):
            assert not is_kimi_compatible(cmd), f"{cmd} should NOT be Kimi-compatible"

    def test_compatibility_ignores_args(self):
        assert is_kimi_compatible("/qa:prep --module 1")
        assert is_kimi_compatible("/seed-data-create .claude/projects/foo.json")

    def test_empty_input_is_incompatible(self):
        assert not is_kimi_compatible("")
        assert not is_kimi_compatible("   ")


class TestAdapter:
    def test_simple_command_no_args(self):
        out = adapt_to_kimi("/secrets-scan")
        assert out == "Lê .claude/commands/secrets-scan.md e executa esse fluxo"

    def test_command_with_namespace_colon(self):
        out = adapt_to_kimi("/qa:prep")
        # ":" → "/" no path
        assert out == "Lê .claude/commands/qa/prep.md e executa esse fluxo"

    def test_command_with_args(self):
        out = adapt_to_kimi("/qa:prep --module 1 .claude/projects/foo.json")
        expected = (
            "Lê .claude/commands/qa/prep.md e executa esse fluxo "
            "com argumentos: --module 1 .claude/projects/foo.json"
        )
        assert out == expected

    def test_command_preserves_config_path(self):
        out = adapt_to_kimi("/seed-data-create .claude/projects/foo.json")
        assert ".claude/projects/foo.json" in out
        assert ".claude/commands/seed-data-create.md" in out

    def test_command_with_double_namespace(self):
        # /backend:scan tem só um nível, mas valida o mecanismo
        out = adapt_to_kimi("/backend:scan --module 2")
        assert out == (
            "Lê .claude/commands/backend/scan.md e executa esse fluxo "
            "com argumentos: --module 2"
        )

    def test_invalid_input_raises(self):
        with pytest.raises(ValueError):
            adapt_to_kimi("")
        with pytest.raises(ValueError):
            adapt_to_kimi("   ")
        with pytest.raises(ValueError):
            adapt_to_kimi("not-a-slash-command")
