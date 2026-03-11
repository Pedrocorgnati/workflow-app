"""
TemplateManager — CRUD for pipeline templates (module-05/TASK-1).

TODO: Implement backend — module-05 (auto-flow execute)
"""

from __future__ import annotations

from workflow_app.domain import CommandSpec


class TemplateManager:
    """
    Manages pipeline templates (factory + user-created).

    Factory templates (4):
    - "Projeto Novo" — full F1-F12
    - "Feature Grande" — PRD + LLD + WBS + execução
    - "Feature Pequena" — intake rápido + FDD + execute
    - "Refactor" — análise + refactor + testes

    TODO: Implement backend — module-05 (auto-flow execute)
    """

    def list_templates(self) -> list[dict]:
        """Return all templates (factory + user-defined)."""
        # TODO: Implement backend — module-05/TASK-1
        return []

    def get_template(self, template_id: int) -> list[CommandSpec]:
        """Load a template by ID and return CommandSpec list."""
        # TODO: Implement backend — module-05/TASK-1
        raise NotImplementedError("module-05/TASK-1 not yet implemented — run /auto-flow execute")

    def save_template(self, name: str, commands: list[CommandSpec]) -> None:
        """Save a user-defined template."""
        # TODO: Implement backend — module-05/TASK-1
        raise NotImplementedError("module-05/TASK-1 not yet implemented — run /auto-flow execute")

    def delete_template(self, template_id: int) -> None:
        """Delete a user-defined template (factory templates cannot be deleted)."""
        # TODO: Implement backend — module-05/TASK-1
        raise NotImplementedError("module-05/TASK-1 not yet implemented — run /auto-flow execute")
