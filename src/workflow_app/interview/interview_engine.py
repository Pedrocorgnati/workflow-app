"""
InterviewEngine — Logic for guided interview pipeline creation (module-04/TASK-1).

Stub implementation: generates a hardcoded "Projeto Novo" command list
for UI testing. Real implementation in /auto-flow execute.
"""

from __future__ import annotations

from workflow_app.domain import CommandSpec, InteractionType, ModelName


# Default "Projeto Novo" pipeline (full F1-F12)
_NOVO_PROJETO_COMMANDS: list[tuple[str, ModelName, InteractionType, bool]] = [
    ("/project-json",        ModelName.SONNET, InteractionType.AUTO,        False),
    ("/create-flow",         ModelName.HAIKU,  InteractionType.INTERACTIVE, False),
    ("/first-brief-create",  ModelName.OPUS,   InteractionType.INTERACTIVE, False),
    ("/intake:analyze",      ModelName.SONNET, InteractionType.AUTO,        True),   # optional
    ("/intake:enhance",      ModelName.OPUS,   InteractionType.INTERACTIVE, True),   # optional
    ("/prd-create",          ModelName.OPUS,   InteractionType.AUTO,        False),
    ("/user-stories-create", ModelName.SONNET, InteractionType.AUTO,        False),
    ("/hld-create",          ModelName.OPUS,   InteractionType.AUTO,        False),
    ("/lld-create",          ModelName.OPUS,   InteractionType.AUTO,        False),
    ("/review-prd-flow",     ModelName.OPUS,   InteractionType.INTERACTIVE, False),
    ("/auto-flow modules",   ModelName.OPUS,   InteractionType.INTERACTIVE, False),
    ("/auto-flow create",    ModelName.SONNET, InteractionType.AUTO,        False),
    ("/validate-pipeline",   ModelName.SONNET, InteractionType.AUTO,        False),
    ("/front-end-build",     ModelName.SONNET, InteractionType.AUTO,        False),
    ("/auto-flow execute",   ModelName.SONNET, InteractionType.AUTO,        False),
]

_FEATURE_COMMANDS: list[tuple[str, ModelName, InteractionType, bool]] = [
    ("/feature-brief-create", ModelName.OPUS,   InteractionType.INTERACTIVE, False),
    ("/fdd-create",           ModelName.OPUS,   InteractionType.AUTO,        False),
    ("/lld-create",           ModelName.OPUS,   InteractionType.AUTO,        False),
    ("/review-prd-flow",      ModelName.OPUS,   InteractionType.INTERACTIVE, False),
    ("/auto-flow execute",    ModelName.SONNET, InteractionType.AUTO,        False),
]


class InterviewEngine:
    """
    Generates command lists based on interview answers.

    TODO: Real implementation — module-04/TASK-1 (auto-flow execute)
    """

    def generate_command_list(self, answers: dict[str, str]) -> list[CommandSpec]:
        """
        Generate a CommandSpec list from interview answers.

        Args:
            answers: dict mapping question_id to answer string

        Returns:
            Ordered list of CommandSpec objects

        Raises:
            ValueError: if answers are insufficient to determine a pipeline
        """
        # TODO: Implement backend — module-04/TASK-1
        project_type = answers.get("project_type", "novo")
        if project_type == "novo":
            return self._build_from_template(_NOVO_PROJETO_COMMANDS)
        elif project_type in ("feature_grande", "feature_pequena"):
            return self._build_from_template(_FEATURE_COMMANDS)
        else:
            raise ValueError(
                f"Tipo de projeto desconhecido: '{project_type}'. "
                "Selecione uma das opções disponíveis."
            )

    def get_stub_template(self) -> list[CommandSpec]:
        """Return the default 'Projeto Novo' pipeline for UI testing."""
        return self._build_from_template(_NOVO_PROJETO_COMMANDS)

    @staticmethod
    def _build_from_template(
        template: list[tuple[str, ModelName, InteractionType, bool]]
    ) -> list[CommandSpec]:
        return [
            CommandSpec(
                name=name,
                model=model,
                interaction_type=inter,
                position=idx + 1,
                is_optional=optional,
            )
            for idx, (name, model, inter, optional) in enumerate(template)
        ]
