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
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from workflow_app.domain import CommandSpec, InteractionType, ModelName

logger = logging.getLogger(__name__)


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
        self._benchmark_path = self._contracts_path.with_name("BENCHMARK-CONTRACTS.json")
        self._contracts = self._load_contracts()
        self.last_pending_notice: dict[str, str] | None = None

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

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
            "+00:00", "Z"
        )

    @staticmethod
    def _pending_key(trigger_id: str, missing_artifact: str) -> str:
        safe_trigger = re.sub(r"[^A-Za-z0-9_.:@-]+", "_", trigger_id)
        safe_artifact = re.sub(r"[^A-Za-z0-9_.:@/-]+", "_", missing_artifact)
        return f"{safe_trigger}|{safe_artifact}"

    def _pipeline_research_dir(self, config_path: str) -> Path:
        docs_root = self._docs_root_from_config(config_path)
        if docs_root is not None:
            return docs_root / "_pipeline-research"
        return self._contracts_path.parent / "_pipeline-research"

    def _docs_root_from_config(self, config_path: str) -> Path | None:
        if not config_path:
            return None
        path = Path(config_path)
        if not path.exists():
            return None
        try:
            cfg = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        docs_root = None
        if isinstance(cfg.get("basic_flow"), dict):
            docs_root = cfg["basic_flow"].get("docs_root")
        if not docs_root:
            docs_root = cfg.get("docs_root")
        if not isinstance(docs_root, str) or not docs_root.strip():
            return None
        return Path(docs_root)

    def _pending_path(self, config_path: str) -> Path:
        return self._pipeline_research_dir(config_path) / "_PENDING.md"

    def _remove_pending_entry(
        self,
        *,
        trigger_id: str,
        missing_artifact: str,
        config_path: str,
    ) -> None:
        pending_path = self._pending_path(config_path)
        if not pending_path.exists():
            return
        key = self._pending_key(trigger_id, missing_artifact)
        try:
            content = pending_path.read_text(encoding="utf-8")
        except OSError:
            return
        pattern = re.compile(
            rf"\n?<!-- phase-trigger-pending: {re.escape(key)} -->.*?"
            rf"<!-- /phase-trigger-pending: {re.escape(key)} -->\n?",
            re.DOTALL,
        )
        updated = pattern.sub("\n", content).rstrip() + "\n"
        if updated != content:
            pending_path.write_text(updated, encoding="utf-8")

    def _write_pending_entry(
        self,
        *,
        trigger_id: str,
        missing_artifact: str,
        config_path: str,
    ) -> bool:
        pending_path = self._pending_path(config_path)
        key = self._pending_key(trigger_id, missing_artifact)
        timestamp = self._utc_now()
        notice = {
            "trigger_id": trigger_id,
            "missing_artifact": missing_artifact,
            "config_path": config_path,
            "pending_path": str(pending_path),
        }
        action = (
            "Restaurar ou validar o artefato de bootstrap antes de permitir "
            "injecao automatica de phase_triggers."
        )
        entry = (
            f"<!-- phase-trigger-pending: {key} -->\n"
            f"## Pending phase trigger - {trigger_id}\n\n"
            f"- trigger_id: `{trigger_id}`\n"
            f"- missing_artifact: `{missing_artifact}`\n"
            f"- config_path: `{config_path}`\n"
            f"- timestamp_utc: `{timestamp}`\n"
            f"- acao_recomendada: {action}\n"
            f"<!-- /phase-trigger-pending: {key} -->\n"
        )
        try:
            pending_path.parent.mkdir(parents=True, exist_ok=True)
            if pending_path.exists():
                content = pending_path.read_text(encoding="utf-8")
            else:
                content = "# Pipeline Research Pending\n\n"
            if f"<!-- phase-trigger-pending: {key} -->" not in content:
                if not content.endswith("\n"):
                    content += "\n"
                pending_path.write_text(
                    content.rstrip() + "\n\n" + entry,
                    encoding="utf-8",
                )
        except OSError as exc:
            notice["pending_error"] = str(exc)
            self.last_pending_notice = notice
            logger.warning(
                "PhaseTriggerEngine: pending write failed; suppressing injection "
                "trigger_id=%s missing_artifact=%s config_path=%s pending_path=%s "
                "error=%s",
                trigger_id,
                missing_artifact,
                config_path,
                pending_path,
                exc,
            )
            return False

        self.last_pending_notice = notice
        return True

    def _bootstrap_guard_ready(self, *, trigger_id: str, config_path: str) -> bool:
        missing_artifact = str(self._benchmark_path)
        if self._benchmark_path.exists():
            self._remove_pending_entry(
                trigger_id=trigger_id,
                missing_artifact=missing_artifact,
                config_path=config_path,
            )
            return True

        wrote_pending = self._write_pending_entry(
            trigger_id=trigger_id,
            missing_artifact=missing_artifact,
            config_path=config_path,
        )
        logger.warning(
            "PhaseTriggerEngine: bootstrap guard absent; suppressing injection "
            "trigger_id=%s missing_artifact=%s config_path=%s pending_path=%s",
            trigger_id,
            missing_artifact,
            config_path,
            self.last_pending_notice["pending_path"] if self.last_pending_notice else "",
        )
        if not wrote_pending:
            logger.warning(
                "PhaseTriggerEngine: bootstrap guard pending marker unavailable; "
                "injection remains suppressed trigger_id=%s missing_artifact=%s "
                "config_path=%s",
                trigger_id,
                missing_artifact,
                config_path,
            )
        return False

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

            if not self._bootstrap_guard_ready(trigger_id=trigger_id, config_path=config_path):
                return trigger_id, []

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
                    effort=spec.effort,
                    testid=spec.testid,
                    blocked_reason=spec.blocked_reason,
                    kimi_eligible=spec.kimi_eligible,
                    kind=getattr(spec, "kind", "slash"),
                    local_action_id=getattr(spec, "local_action_id", None),
                    flags_boolean=list(spec.flags_boolean),
                    flags_with_value=list(spec.flags_with_value),
                )
            )
            position += 1

            cfg = trigger_by_checkpoint.get(spec.name)
            if not cfg:
                continue

            trigger_id = ""
            for candidate_id, candidate_cfg in phase_triggers.items():
                if candidate_cfg is cfg:
                    trigger_id = str(candidate_id)
                    break
            if not trigger_id:
                trigger_id = spec.name
            if not self._bootstrap_guard_ready(
                trigger_id=trigger_id,
                config_path=spec.config_path,
            ):
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
