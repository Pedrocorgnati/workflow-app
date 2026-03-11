"""
Domain enums and dataclasses for Workflow App (module-02/TASK-1).

These are the shared types used throughout the entire application.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Optional


# ─── Enums ──────────────────────────────────────────────────────────────── #


class CommandStatus(enum.Enum):
    """Lifecycle states of a single command in the pipeline."""
    PENDENTE = "pendente"
    EXECUTANDO = "executando"
    CONCLUIDO = "concluido"
    ERRO = "erro"
    PULADO = "pulado"
    INCERTO = "incerto"


class PipelineStatus(enum.Enum):
    """Lifecycle states of a pipeline execution."""
    NAO_INICIADO = "nao_iniciado"
    EXECUTANDO = "executando"
    PAUSADO = "pausado"
    CONCLUIDO = "concluido"
    CANCELADO = "cancelado"
    INCERTO = "incerto"


class ModelName(enum.Enum):
    """Supported Claude model names."""
    OPUS = "Opus"
    SONNET = "Sonnet"
    HAIKU = "Haiku"


class InteractionType(enum.Enum):
    """How the command handles user interaction."""
    AUTO = "auto"           # Runs automatically, no user input needed
    INTERACTIVE = "inter"   # Requires user input during execution


class PermissionMode(enum.Enum):
    """Claude agent permission modes."""
    ACCEPT_EDITS = "acceptEdits"
    BYPASS_PERMISSIONS = "bypassPermissions"
    DEFAULT = "default"


# ─── Dataclasses ─────────────────────────────────────────────────────────── #


@dataclass
class CommandSpec:
    """Specification of a single command in the pipeline queue.

    This is the primary transfer object between UI components
    (PipelineCreatorWidget → MainWindow → PipelineManager).
    """
    name: str                                     # e.g. "/prd-create"
    model: ModelName = ModelName.SONNET           # Claude model to use
    interaction_type: InteractionType = InteractionType.AUTO
    position: int = 0                             # 1-based index in queue
    is_optional: bool = False                     # Can be removed by user in review
    estimated_seconds: Optional[int] = None       # Time estimate (optional)

    def display_name(self) -> str:
        """Return formatted display string."""
        return self.name

    def model_badge_text(self) -> str:
        """Return short model name for badge display."""
        return self.model.value

    def interaction_badge_text(self) -> str:
        """Return short interaction type for badge display."""
        return "→ auto" if self.interaction_type == InteractionType.AUTO else "↔ inter"


@dataclass
class ProjectConfig:
    """Parsed configuration from a project.json file."""
    path: str                        # Absolute path to the .json file
    name: str                        # Project name
    workspace_root: str              # workspace_root from basic_flow
    docs_root: str                   # docs_root from basic_flow
    wbs_root: str                    # wbs_root from basic_flow
    brief_root: str                  # brief_root from basic_flow
    permission_mode: PermissionMode = PermissionMode.ACCEPT_EDITS


@dataclass
class ExecutionMetrics:
    """Live metrics for the current pipeline run."""
    total_commands: int = 0
    completed_commands: int = 0
    failed_commands: int = 0
    elapsed_seconds: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    estimated_cost_usd: float = 0.0

    @property
    def progress_fraction(self) -> float:
        if self.total_commands == 0:
            return 0.0
        return self.completed_commands / self.total_commands
