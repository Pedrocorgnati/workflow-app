"""
QueueExpander — Automatic queue expansion on trigger commands (module-12/TASK-5).

When /modules:review-created or /auto-flow completes, enumerate the real
executable task specs per module and add matching execute commands to the
pipeline. When /deploy-flow completes, append post-deploy verification commands.

Task enumeration routes through the canonical `enumerate_module_tasks` (same
engine the DCP queue derivation + offline generator use): only
`TASK-<int|decimal>.md` count as executable tasks; companion artifacts
(`TASK-1-SCREENS.md`, `TASK-1-AUDIT.md`, `TASK-1-REVIEW.md`, ...) are excluded so
`/auto-flow execute` never enqueues a non-task .md (loop 06-08).
"""

from __future__ import annotations

from pathlib import Path

from workflow_app.dcp.task_enum import enumerate_module_tasks
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
        ModelName.SONNET,
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
        """Enumerate executable task specs per module and create execute specs.

        Routes through the canonical `enumerate_module_tasks` per module dir
        (numeric-ordered, companion artifacts excluded) instead of a flat
        `glob("module-*/TASK-*.md")`, so `/auto-flow execute` only enqueues real
        tasks. Modules are visited in sorted order for determinism.
        """
        modules_dir = self._wbs_root / "modules"
        if not modules_dir.exists():
            return []

        existing_set = set(existing)
        new_specs: list[CommandSpec] = []
        for module_dir in sorted(p for p in modules_dir.glob("module-*") if p.is_dir()):
            for task_name in enumerate_module_tasks(module_dir):
                cmd_name = f"/auto-flow execute {module_dir.name}/{task_name}"
                if cmd_name not in existing_set:
                    new_specs.append(CommandSpec(
                        name=cmd_name,
                        model=ModelName.SONNET,
                        interaction_type=InteractionType.AUTO,
                        position=0,  # will be re-indexed by PipelineManager
                    ))

        return new_specs

    def _expand_deploy(self, existing: list[str]) -> list[CommandSpec]:
        """Return post-deploy commands not already in the queue."""
        existing_set = set(existing)
        return [
            spec
            for spec in _DEPLOY_EXPANSION
            if spec.name not in existing_set
        ]
