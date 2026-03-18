"""
QueueExpander — Automatic queue expansion on trigger commands (module-12/TASK-5).

When /modules:review-created or /auto-flow completes, glob TASK-*.md from
wbs_root and add matching execute commands to the pipeline.
When /deploy-flow completes, append post-deploy verification commands.
"""

from __future__ import annotations

from pathlib import Path

from workflow_app.domain import CommandSpec, InteractionType, ModelName

# Static expansion for deploy-flow trigger
_DEPLOY_EXPANSION: list[CommandSpec] = [
    CommandSpec(
        "/post-deploy-verify",
        ModelName.SONNET,
        InteractionType.AUTO,
        position=0,
    ),
    CommandSpec(
        "/changelog-create",
        ModelName.HAIKU,
        InteractionType.AUTO,
        position=0,
    ),
]

# Trigger commands that expand the queue from the modules directory
_UPDATE_FLOW_TRIGGERS: frozenset[str] = frozenset({
    "/modules:review-created",
    "/auto-flow",
})


class QueueExpander:
    """Detects expansion triggers and returns new CommandSpec objects to enqueue."""

    def __init__(self, wbs_root: str) -> None:
        self._wbs_root = Path(wbs_root)

    def check_and_expand(
        self,
        command_name: str,
        existing_commands: list[str],
    ) -> list[CommandSpec]:
        """Check if command_name triggers expansion and return new specs.

        Args:
            command_name: The command that just completed.
            existing_commands: Command names already in the queue (to avoid duplicates).

        Returns:
            List of new CommandSpec to append.  Empty list if no expansion needed.
        """
        if command_name in _UPDATE_FLOW_TRIGGERS:
            return self._expand_from_modules(existing_commands)
        if command_name == "/deploy-flow":
            return self._expand_deploy(existing_commands)
        return []

    # ─────────────────────────────────────────────────────── Helpers ─── #

    def _expand_from_modules(self, existing: list[str]) -> list[CommandSpec]:
        """Glob TASK-*.md under wbs_root/modules and create execute specs."""
        modules_dir = self._wbs_root / "modules"
        if not modules_dir.exists():
            return []

        existing_set = set(existing)
        task_paths = sorted(modules_dir.glob("module-*/TASK-*.md"))

        new_specs: list[CommandSpec] = []
        for path in task_paths:
            cmd_name = f"/auto-flow execute {path.parent.name}/{path.name}"
            if cmd_name not in existing_set:
                spec = CommandSpec(
                    name=cmd_name,
                    model=ModelName.SONNET,
                    interaction_type=InteractionType.AUTO,
                    position=0,  # will be re-indexed by PipelineManager
                )
                new_specs.append(spec)

        return new_specs

    def _expand_deploy(self, existing: list[str]) -> list[CommandSpec]:
        """Return post-deploy commands not already in the queue."""
        existing_set = set(existing)
        return [
            spec
            for spec in _DEPLOY_EXPANSION
            if spec.name not in existing_set
        ]
