"""
Helpers for building robust Autocast process launches.

Autocast executes one real subprocess per queue item and advances only when
that subprocess exits. This module centralizes CLI-instance resolution so the
widget does not need to know shell aliases or per-instance quirks.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from workflow_app.domain import CommandSpec, InteractionType

_MODEL_MAP: dict[str, str] = {
    "Opus": "opus",
    "Sonnet": "sonnet",
    "Haiku": "haiku",
}


@dataclass(frozen=True)
class AutocastInstanceProfile:
    """Executable profile for a UI-selected CLI instance."""

    name: str
    executable: str
    prefix_args: tuple[str, ...] = ()
    env_overrides: dict[str, str] = field(default_factory=dict)
    supports_workflow_commands: bool = True


@dataclass(frozen=True)
class AutocastLaunchPlan:
    """Concrete process launch details for one queue item."""

    argv: tuple[str, ...]
    env_overrides: dict[str, str]
    display_command: str
    channel: str


def resolve_instance_profile(instance_name: str) -> AutocastInstanceProfile:
    """Resolve a UI instance name to a concrete executable profile."""
    normalized = (instance_name or "").strip() or "clauded"
    home = os.path.expanduser("~")

    profiles: dict[str, AutocastInstanceProfile] = {
        "clauded": AutocastInstanceProfile(
            name="clauded",
            executable="claude",
            prefix_args=("--dangerously-skip-permissions",),
        ),
        "clauded2": AutocastInstanceProfile(
            name="clauded2",
            executable="claude",
            prefix_args=("--dangerously-skip-permissions",),
            env_overrides={"CLAUDE_CONFIG_DIR": os.path.join(home, ".claude-email2")},
        ),
        # Codex instances are intentionally blocked for workflow slash commands.
        # They do not understand the Claude slash-command pipeline semantics.
        "codex": AutocastInstanceProfile(
            name="codex",
            executable="codex",
            supports_workflow_commands=False,
        ),
        "codex-high": AutocastInstanceProfile(
            name="codex-high",
            executable="codex-high",
            supports_workflow_commands=False,
        ),
        "codex-ultra": AutocastInstanceProfile(
            name="codex-ultra",
            executable="codex-ultra",
            supports_workflow_commands=False,
        ),
    }

    if normalized in profiles:
        return profiles[normalized]

    return AutocastInstanceProfile(name=normalized, executable=normalized)


def build_launch_plan(spec: CommandSpec, instance_name: str) -> AutocastLaunchPlan:
    """Build the concrete argv/env/channel for one Autocast command."""
    profile = resolve_instance_profile(instance_name)
    if not profile.supports_workflow_commands:
        raise ValueError(
            f"Autocast não suporta a instância '{profile.name}' para slash commands."
        )

    model_flag = _MODEL_MAP.get(spec.model.value, "sonnet")
    config_args = (spec.config_path,) if spec.config_path else ()
    command_parts = [profile.name]

    if spec.interaction_type == InteractionType.INTERACTIVE:
        argv = (
            profile.executable,
            *profile.prefix_args,
            spec.name,
            *config_args,
            "--model",
            model_flag,
        )
        command_parts.extend([spec.name, *config_args, "--model", model_flag])
    else:
        prompt = " ".join(part for part in (spec.name, spec.config_path) if part).strip()
        argv = (
            profile.executable,
            *profile.prefix_args,
            "-p",
            prompt,
            "--model",
            model_flag,
        )
        command_parts.extend(["-p", prompt, "--model", model_flag])

    # All autocast commands run in the interactive terminal channel
    channel = "interactive"

    return AutocastLaunchPlan(
        argv=argv,
        env_overrides=dict(profile.env_overrides),
        display_command=" ".join(command_parts),
        channel=channel,
    )
