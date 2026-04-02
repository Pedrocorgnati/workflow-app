"""
PhaseTriggerEngine — contract-driven auto-actions on phase checkpoints.

Reads phase trigger definitions from PHASE-CONTRACTS.json and, when a
checkpoint command is completed, proposes additional commands to append to the
pipeline queue (scorecard, lessons, backlog generation, etc.).

Design goals:
  - deterministic (no network or model calls)
  - idempotent (do not emit duplicate actions already in queue)
  - anti-loop (do not fire same trigger twice in one pipeline execution)
"""

from __future__ import annotations

import json
from pathlib import Path

from workflow_app.domain import CommandSpec, InteractionType, ModelName


class PhaseTriggerEngine:
    """Expand queue with automatic phase-level research actions."""

    _DEFAULT_MODEL = ModelName.SONNET
    _MODEL_BY_COMMAND: dict[str, ModelName] = {
        "/cmd:experiment": ModelName.OPUS,
        "/meta:propose-mechanism": ModelName.OPUS,
        "/meta:inject-mechanism-sandbox": ModelName.OPUS,
    }

    def __init__(self, contracts_path: str | Path | None = None) -> None:
        if contracts_path is None:
            root = Path(__file__).resolve().parents[3]
            contracts_path = (
                root / "ai-forge" / "pipeline-contracts" / "PHASE-CONTRACTS.json"
            )
        self._contracts_path = Path(contracts_path)
        self._contracts = self._load_contracts()

    def _load_contracts(self) -> dict:
        if not self._contracts_path.exists():
            return {}
        try:
            return json.loads(self._contracts_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    @staticmethod
    def _base_command(command_line: str) -> str:
        return command_line.strip().split(" ", 1)[0]

    def _pick_model(self, command_line: str) -> ModelName:
        return self._MODEL_BY_COMMAND.get(
            self._base_command(command_line),
            self._DEFAULT_MODEL,
        )

    def check_and_expand(
        self,
        completed_command: str,
        existing_commands: list[str],
        *,
        fired_triggers: set[str] | None = None,
        config_path: str = "",
    ) -> tuple[str | None, list[CommandSpec]]:
        """Return (trigger_id, new_specs) for the completed command.

        Args:
            completed_command: command that just completed successfully.
            existing_commands: command names already in queue (for dedupe).
            fired_triggers: trigger IDs already fired in this pipeline run.
            config_path: project config to propagate into auto actions.
        """
        fired = fired_triggers or set()
        phase_triggers = self._contracts.get("phase_triggers", {})
        if not isinstance(phase_triggers, dict):
            return None, []

        for trigger_id, cfg in phase_triggers.items():
            if trigger_id in fired:
                continue
            if not isinstance(cfg, dict):
                continue
            if cfg.get("on_command_success") != completed_command:
                continue

            actions = cfg.get("auto_actions", [])
            if not isinstance(actions, list):
                return trigger_id, []

            existing = set(existing_commands)
            new_specs: list[CommandSpec] = []
            for action in actions:
                if not isinstance(action, str):
                    continue
                if action in existing:
                    continue
                new_specs.append(
                    CommandSpec(
                        name=action,
                        model=self._pick_model(action),
                        interaction_type=InteractionType.AUTO,
                        position=0,
                        config_path=config_path,
                    )
                )
            return trigger_id, new_specs
        return None, []

    def inject_phase_actions_into_queue(
        self,
        commands: list[CommandSpec],
    ) -> list[CommandSpec]:
        """Compile-time injection of phase auto-actions into queue.

        This path does not depend on runtime "command completed" detection.
        It rewrites the queue upfront by inserting trigger actions immediately
        after each checkpoint command.
        """
        phase_triggers = self._contracts.get("phase_triggers", {})
        if not isinstance(phase_triggers, dict) or not commands:
            return list(commands)

        trigger_by_checkpoint: dict[str, dict] = {}
        for _, cfg in phase_triggers.items():
            if not isinstance(cfg, dict):
                continue
            checkpoint = cfg.get("on_command_success")
            if isinstance(checkpoint, str):
                trigger_by_checkpoint[checkpoint] = cfg

        existing_names = {c.name for c in commands}
        out: list[CommandSpec] = []
        position = 1

        for spec in commands:
            out.append(
                CommandSpec(
                    name=spec.name,
                    model=spec.model,
                    interaction_type=spec.interaction_type,
                    position=position,
                    is_optional=spec.is_optional,
                    estimated_seconds=spec.estimated_seconds,
                    phase=spec.phase,
                    config_path=spec.config_path,
                )
            )
            position += 1

            cfg = trigger_by_checkpoint.get(spec.name)
            if not cfg:
                continue

            actions = cfg.get("auto_actions", [])
            if not isinstance(actions, list):
                continue

            for action in actions:
                if not isinstance(action, str):
                    continue
                if action in existing_names:
                    continue
                out.append(
                    CommandSpec(
                        name=action,
                        model=self._pick_model(action),
                        interaction_type=InteractionType.AUTO,
                        position=position,
                        config_path=spec.config_path,
                    )
                )
                position += 1
                existing_names.add(action)

        return out
