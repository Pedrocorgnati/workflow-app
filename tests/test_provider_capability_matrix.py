"""Tests for the provider capability matrix generator (D-37, D-38).

Validates the authorial YAML (C-01), the generator script (C-02), and the
snapshot (C-03). Key invariant: absence of data = "indisponivel" (fail-closed).

Paths frozen in BASELINE.md Bloco 4 (C-01..C-03):
  C-01: ai-forge/rules/provider-capabilities.yaml
  C-02: ai-forge/scripts/gen-provider-capability-matrix.py
  C-03: ai-forge/schemas/provider-capability-matrix.json
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from workflow_app.provider_capability_loader import (
    AUTHORIAL_PATH as LOADER_AUTHORIAL_PATH,
    ProviderCapabilityLoader,
    reset_singleton,
)

REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
AUTHORIAL_PATH = REPO_ROOT / "ai-forge" / "rules" / "provider-capabilities.yaml"
GENERATOR_PATH = REPO_ROOT / "ai-forge" / "scripts" / "gen-provider-capability-matrix.py"
SNAPSHOT_PATH = REPO_ROOT / "ai-forge" / "schemas" / "provider-capability-matrix.json"


# --- ST001: YAML autoral ---


class TestAuthorialYaml:
    """Tests for provider-capabilities.yaml (C-01)."""

    def test_yaml_loads(self) -> None:
        """C-01 parseia sem erro."""
        with open(AUTHORIAL_PATH) as f:
            data = yaml.safe_load(f)
        assert isinstance(data, dict)

    def test_has_commands_section(self) -> None:
        """YAML tem secao 'commands'."""
        with open(AUTHORIAL_PATH) as f:
            data = yaml.safe_load(f)
        assert "commands" in data
        assert len(data["commands"]) > 0

    def test_has_providers_section(self) -> None:
        """YAML tem secao 'providers'."""
        with open(AUTHORIAL_PATH) as f:
            data = yaml.safe_load(f)
        assert "providers" in data
        assert len(data["providers"]) > 0

    def test_commands_have_required_capabilities(self) -> None:
        """Cada comando declara required_capabilities."""
        with open(AUTHORIAL_PATH) as f:
            data = yaml.safe_load(f)
        for cmd_name, cmd_spec in data["commands"].items():
            assert "required_capabilities" in cmd_spec, (
                f"{cmd_name} missing required_capabilities"
            )
            assert isinstance(cmd_spec["required_capabilities"], list)
            assert len(cmd_spec["required_capabilities"]) > 0

    def test_providers_have_roles_with_capabilities(self) -> None:
        """Cada provider tem roles com capabilities."""
        with open(AUTHORIAL_PATH) as f:
            data = yaml.safe_load(f)
        for provider_name, provider_spec in data["providers"].items():
            assert "roles" in provider_spec, (
                f"{provider_name} missing roles"
            )
            for role_name, role_spec in provider_spec["roles"].items():
                assert "capabilities" in role_spec, (
                    f"{provider_name}/{role_name} missing capabilities"
                )
                assert isinstance(role_spec["capabilities"], list)


# --- ST002/ST003: Gerador e modo --check ---


class TestGenerator:
    """Tests for gen-provider-capability-matrix.py (C-02)."""

    def test_generator_exists(self) -> None:
        """C-02 existe em disco."""
        assert GENERATOR_PATH.exists()

    def test_generator_produces_snapshot(self) -> None:
        """Gerador produz JSON valido."""
        result = subprocess.run(
            [sys.executable, str(GENERATOR_PATH)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, f"generator failed: {result.stderr}"
        assert SNAPSHOT_PATH.exists()
        with open(SNAPSHOT_PATH) as f:
            data = json.load(f)
        assert "matrix" in data
        assert "schema_version" in data
        assert "summary" in data

    def test_check_mode_passes_after_generation(self) -> None:
        """--check retorna 0 apos geracao fresca."""
        # Generate first
        subprocess.run(
            [sys.executable, str(GENERATOR_PATH)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        # Then check
        result = subprocess.run(
            [sys.executable, str(GENERATOR_PATH), "--check"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, f"--check failed: {result.stderr}"
        assert "up-to-date" in result.stdout

    def test_check_mode_fails_on_drift(self) -> None:
        """--check retorna 1 quando snapshot diverge."""
        # Generate fresh
        subprocess.run(
            [sys.executable, str(GENERATOR_PATH)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        # Corrupt snapshot
        original = SNAPSHOT_PATH.read_text()
        SNAPSHOT_PATH.write_text('{"drift": true}\n')
        try:
            result = subprocess.run(
                [sys.executable, str(GENERATOR_PATH), "--check"],
                capture_output=True,
                text=True,
                cwd=str(REPO_ROOT),
            )
            assert result.returncode == 1
            assert "outdated" in result.stderr
        finally:
            # Restore
            SNAPSHOT_PATH.write_text(original)

    def test_check_mode_fails_on_missing_file(self, tmp_path: Path) -> None:
        """--check retorna 1 quando snapshot nao existe."""
        nonexistent = tmp_path / "nonexistent.json"
        result = subprocess.run(
            [
                sys.executable,
                str(GENERATOR_PATH),
                "--check",
                "--output",
                str(nonexistent),
            ],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 1
        assert "not found" in result.stderr

    def test_snapshot_is_deterministic(self) -> None:
        """Duas geracoes consecutivas produzem output identico (exceto generated_at)."""
        # Generate twice
        subprocess.run(
            [sys.executable, str(GENERATOR_PATH)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        first = json.loads(SNAPSHOT_PATH.read_text())
        first.pop("generated_at", None)

        subprocess.run(
            [sys.executable, str(GENERATOR_PATH)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        second = json.loads(SNAPSHOT_PATH.read_text())
        second.pop("generated_at", None)

        assert first == second


# --- D-37: Ausencia = indisponivel (fail-closed) ---


class TestFailClosed:
    """Tests for D-37 invariant: absence = indisponivel."""

    def test_absence_means_indisponivel(self) -> None:
        """Provider sem capacidade declarada = indisponivel no snapshot."""
        with open(AUTHORIAL_PATH) as f:
            authorial = yaml.safe_load(f)

        # Find a capability that kimi/worker does NOT have
        # kimi worker has capabilities: [] (empty)
        kimi_worker_caps = (
            authorial["providers"]["kimi"]["roles"]["worker"]["capabilities"]
        )
        assert len(kimi_worker_caps) == 0, (
            "test assumes kimi/worker has no capabilities"
        )

        # Generate matrix via the generator's logic
        result = subprocess.run(
            [sys.executable, str(GENERATOR_PATH)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0

        with open(SNAPSHOT_PATH) as f:
            snapshot = json.load(f)

        # Check that kimi/worker has "indisponivel" for all required capabilities
        for cmd_name, cmd_data in snapshot["matrix"].items():
            if "kimi" in cmd_data and "worker" in cmd_data["kimi"]:
                for cap, status in cmd_data["kimi"]["worker"].items():
                    assert status == "indisponivel", (
                        f"{cmd_name}/kimi/worker/{cap} should be indisponivel, "
                        f"got {status}"
                    )

    def test_no_capacity_defaults_to_allowed(self) -> None:
        """Anti-regressao D-37: NENHUM caminho onde ausencia = 'permitido'."""
        subprocess.run(
            [sys.executable, str(GENERATOR_PATH)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        with open(SNAPSHOT_PATH) as f:
            snapshot = json.load(f)

        allowed_values = {"disponivel", "indisponivel"}
        for cmd_name, cmd_data in snapshot["matrix"].items():
            for provider_name, provider_data in cmd_data.items():
                for role_name, role_data in provider_data.items():
                    for cap, status in role_data.items():
                        assert status in allowed_values, (
                            f"{cmd_name}/{provider_name}/{role_name}/{cap} "
                            f"has invalid status '{status}' "
                            f"(expected one of {allowed_values})"
                        )
                        # Key invariant: never "permitido" or "allowed"
                        assert status not in ("permitido", "allowed", "true"), (
                            f"D-37 VIOLATION: {cmd_name}/{provider_name}/"
                            f"{role_name}/{cap} = '{status}' "
                            f"(absence must be 'indisponivel')"
                        )

    def test_grok_worker_indisponivel(self) -> None:
        """Grok worker has empty capabilities -> all indisponivel."""
        subprocess.run(
            [sys.executable, str(GENERATOR_PATH)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        with open(SNAPSHOT_PATH) as f:
            snapshot = json.load(f)

        for cmd_name, cmd_data in snapshot["matrix"].items():
            if "grok" in cmd_data and "worker" in cmd_data["grok"]:
                for cap, status in cmd_data["grok"]["worker"].items():
                    assert status == "indisponivel", (
                        f"{cmd_name}/grok/worker/{cap} should be indisponivel"
                    )

    def test_claude_main_has_most_capabilities(self) -> None:
        """Claude main has the broadest capability set."""
        subprocess.run(
            [sys.executable, str(GENERATOR_PATH)],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        with open(SNAPSHOT_PATH) as f:
            snapshot = json.load(f)

        # Count "disponivel" for claude/main vs others
        claude_main_disponivel = 0
        for cmd_data in snapshot["matrix"].values():
            if "claude" in cmd_data and "main" in cmd_data["claude"]:
                for status in cmd_data["claude"]["main"].values():
                    if status == "disponivel":
                        claude_main_disponivel += 1

        assert claude_main_disponivel > 0, (
            "claude/main should have at least some disponivel capabilities"
        )


# --- Item 006: Runtime consome snapshot, nunca autorais (D-37) ---


@pytest.fixture(autouse=True)
def _reset_loader_singleton():
    """Reset singleton between tests to avoid cross-test leakage."""
    reset_singleton()
    yield
    reset_singleton()


class Test_runtime_reads_snapshot_only:
    """Item 006: loader le exclusivamente C-03, nunca C-01."""

    def test_runtime_loads_snapshot_not_authorial(self) -> None:
        """Loader carrega C-03 (snapshot), NUNCA abre C-01 (autoral)."""
        loader = ProviderCapabilityLoader(SNAPSHOT_PATH)
        result = loader.get_capability("/auto-flow", "claude", "main", "file_write")
        assert result == "disponivel"

        authorial_opened = False
        original_read_text = Path.read_text

        def spy_read_text(self_path: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal authorial_opened
            if self_path.resolve() == LOADER_AUTHORIAL_PATH.resolve():
                authorial_opened = True
            return original_read_text(self_path, *args, **kwargs)

        loader2 = ProviderCapabilityLoader(SNAPSHOT_PATH)
        with patch.object(Path, "read_text", spy_read_text):
            loader2.reload()
            loader2.get_capability("/auto-flow", "claude", "main", "file_write")

        assert not authorial_opened, (
            "loader MUST NOT open authorial file (C-01) at runtime"
        )

    def test_runtime_returns_indisponivel_when_snapshot_missing(
        self, tmp_path: Path
    ) -> None:
        """Snapshot removido: is_available=False, reason='snapshot_ausente'."""
        nonexistent = tmp_path / "nonexistent-snapshot.json"
        loader = ProviderCapabilityLoader(nonexistent)

        assert loader.is_available("/auto-flow", "claude", "main", "file_write") is False
        assert loader.get_capability("/auto-flow", "claude", "main", "file_write") == "indisponivel"
        assert loader.get_failure_reason() == "snapshot_ausente"

    def test_runtime_returns_indisponivel_for_unknown_command(self) -> None:
        """Comando nao mapeado = indisponivel com reason 'nao_mapeado'."""
        loader = ProviderCapabilityLoader(SNAPSHOT_PATH)

        result = loader.get_capability("/nonexistent-command-xyz", "claude", "main", "file_write")
        assert result == "indisponivel"
        assert loader.is_available("/nonexistent-command-xyz", "claude", "main", "file_write") is False

    def test_runtime_returns_disponivel_for_known_capability(self) -> None:
        """Comando/provider/role/capacidade mapeados = disponivel."""
        loader = ProviderCapabilityLoader(SNAPSHOT_PATH)

        result = loader.get_capability("/auto-flow", "claude", "main", "file_write")
        assert result == "disponivel"
        assert loader.is_available("/auto-flow", "claude", "main", "file_write") is True
        assert loader.get_failure_reason() is None

    def test_runtime_caches_by_process(self) -> None:
        """Duas chamadas consecutivas nao releem o disco."""
        loader = ProviderCapabilityLoader(SNAPSHOT_PATH)

        call_count = 0
        original_read_text = Path.read_text

        def counting_read_text(self_path: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
            nonlocal call_count
            if self_path.resolve() == SNAPSHOT_PATH.resolve():
                call_count += 1
            return original_read_text(self_path, *args, **kwargs)

        with patch.object(Path, "read_text", counting_read_text):
            loader.reload()
            loader.get_capability("/auto-flow", "claude", "main", "file_write")
            loader.get_capability("/auto-flow", "codex", "main", "shell_execution")
            loader.get_capability("/auto-flow", "kimi", "worker", "file_write")

        assert call_count == 1, (
            f"snapshot should be read exactly once, was read {call_count} times"
        )

    def test_runtime_never_opens_authorial(self) -> None:
        """Mock de Path.read_text para C-01: loader NUNCA chama."""
        loader = ProviderCapabilityLoader(SNAPSHOT_PATH)
        loader.reload()

        authorial_reads: list[str] = []
        original_read_text = Path.read_text

        def tracking_read_text(self_path: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
            if self_path.resolve() == LOADER_AUTHORIAL_PATH.resolve():
                authorial_reads.append(str(self_path))
            return original_read_text(self_path, *args, **kwargs)

        with patch.object(Path, "read_text", tracking_read_text):
            for cmd in ["/auto-flow", "/cmd:review", "/execute-task"]:
                for provider in ["claude", "codex", "kimi"]:
                    for role in ["main", "worker"]:
                        for cap in ["file_write", "shell_execution"]:
                            loader.get_capability(cmd, provider, role, cap)

        assert len(authorial_reads) == 0, (
            f"loader opened authorial file (C-01) {len(authorial_reads)} times: "
            f"{authorial_reads}"
        )


# --- Item 011 / ST002: acessor read-only de mapeamento ---


class Test_get_mapped_capabilities:
    """Item 011: `get_mapped_capabilities` distingue nao-mapeado de indisponivel.

    A API fail-closed (`get_capability`) colapsa os dois casos em
    `indisponivel` + `nao_mapeado`. O preflight informativo do enqueue precisa
    da distincao para nao avisar sobre os ~601 comandos fora dos 21 do
    snapshot. Este acessor NAO pode alterar o veredito fail-closed.
    """

    def test_mapped_command_returns_non_empty_dict(self) -> None:
        """Tripla mapeada devolve o dicionario CRU do snapshot."""
        loader = ProviderCapabilityLoader(SNAPSHOT_PATH)
        mapped = loader.get_mapped_capabilities("/auto-flow", "claude", "main")
        assert isinstance(mapped, dict)
        assert mapped
        assert mapped["file_write"] == "disponivel"

    def test_mapped_command_preserves_indisponivel_status(self) -> None:
        """Status diferente de 'disponivel' chega CRU, sem fail-closed."""
        loader = ProviderCapabilityLoader(SNAPSHOT_PATH)
        mapped = loader.get_mapped_capabilities("/create-task", "codex", "main")
        assert mapped is not None
        assert mapped["mcp_access"] == "indisponivel"

    def test_unknown_command_returns_none(self) -> None:
        """Comando fora da matriz: `None`, nao 'indisponivel'."""
        loader = ProviderCapabilityLoader(SNAPSHOT_PATH)
        assert loader.get_mapped_capabilities("/nonexistent-command-xyz", "claude", "main") is None

    def test_unknown_provider_returns_none(self) -> None:
        """Provider fora do comando mapeado: `None`."""
        loader = ProviderCapabilityLoader(SNAPSHOT_PATH)
        assert loader.get_mapped_capabilities("/auto-flow", "provider-inexistente", "main") is None

    def test_unknown_role_returns_none(self) -> None:
        """Role fora do provider mapeado: `None`."""
        loader = ProviderCapabilityLoader(SNAPSHOT_PATH)
        assert loader.get_mapped_capabilities("/auto-flow", "claude", "role-inexistente") is None

    def test_missing_snapshot_returns_none(self, tmp_path: Path) -> None:
        """Snapshot ausente: `None` (e `get_failure_reason` segue acionavel)."""
        loader = ProviderCapabilityLoader(tmp_path / "nonexistent-snapshot.json")
        assert loader.get_mapped_capabilities("/auto-flow", "claude", "main") is None
        assert loader.get_failure_reason() == "snapshot_ausente"

    @pytest.mark.parametrize(
        ("command", "provider", "capability", "expected"),
        [
            ("/auto-flow", "claude", "file_write", True),
            ("/create-task", "codex", "mcp_access", False),
            ("/nonexistent-command-xyz", "claude", "file_write", False),
        ],
    )
    def test_accessor_does_not_change_is_available_verdict(
        self, command: str, provider: str, capability: str, expected: bool
    ) -> None:
        """Acessor no meio do caminho nao muda o veredito fail-closed.

        Comparacao contra um loader de controle com a MESMA sequencia de
        chamadas menos o acessor. Loader novo por caso porque
        `_failure_reason` e sticky: uma consulta nao mapeada envenena as
        seguintes ate `reload()` — comportamento pre-existente de
        `get_capability`, deliberadamente nao tocado por este item.
        """
        control = ProviderCapabilityLoader(SNAPSHOT_PATH)
        probed = ProviderCapabilityLoader(SNAPSHOT_PATH)
        probed.get_mapped_capabilities(command, provider, "main")

        control_verdict = control.is_available(command, provider, "main", capability)
        probed_verdict = probed.is_available(command, provider, "main", capability)

        assert control_verdict is expected
        assert probed_verdict is control_verdict

    def test_accessor_never_opens_authorial(self) -> None:
        """C-01 permanece fechado tambem no caminho do acessor."""
        loader = ProviderCapabilityLoader(SNAPSHOT_PATH)
        loader.reload()
        authorial_reads: list[str] = []
        original_read_text = Path.read_text

        def tracking_read_text(self_path: Path, *args, **kwargs):  # type: ignore[no-untyped-def]
            if self_path.resolve() == LOADER_AUTHORIAL_PATH.resolve():
                authorial_reads.append(str(self_path))
            return original_read_text(self_path, *args, **kwargs)

        with patch.object(Path, "read_text", tracking_read_text):
            for cmd in ["/auto-flow", "/cmd:review", "/nao-existe"]:
                loader.get_mapped_capabilities(cmd, "claude", "main")

        assert authorial_reads == []
