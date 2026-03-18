"""Mock do SDKAdapter para testes E2E (module-16/TASK-2).

Simula execução de comandos Claude sem chamadas reais à API.
"""
from __future__ import annotations

from collections.abc import Generator

from workflow_app.domain import CommandSpec


class MockSDKAdapter:
    """SDKAdapter falso para testes E2E — sem chamadas ao Claude real."""

    def __init__(self) -> None:
        self._fail_commands: set[str] = set()
        self._call_counts: dict[str, int] = {}

    def configure_failure(self, command_name: str) -> None:
        """Configura um comando para falhar na primeira tentativa."""
        self._fail_commands.add(command_name)

    def execute(
        self,
        spec: CommandSpec,
        workspace_root: str,
        permission_mode: str = "acceptEdits",
    ) -> Generator[str, None, None]:
        """Simula execução de um comando."""
        key = spec.name
        count = self._call_counts.get(key, 0)
        self._call_counts[key] = count + 1

        # Falhar apenas na primeira tentativa
        should_fail = key in self._fail_commands and count == 0
        if should_fail:
            self._fail_commands.discard(key)  # remove para não falhar no retry
            raise RuntimeError(f"Erro simulado: {key}")

        yield f"[mock] {spec.name}: iniciando\n"
        yield f"[mock] {spec.name}: processando\n"
        yield f"[mock] {spec.name}: concluído\n"
