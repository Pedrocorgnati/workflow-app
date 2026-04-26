"""
Domain enums and dataclasses for Workflow App (module-02/TASK-1).

These are the shared types used throughout the entire application.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field

# ─── Enums ──────────────────────────────────────────────────────────────── #


class CommandStatus(str, enum.Enum):
    """Lifecycle states of a single command in the pipeline."""
    PENDENTE = "pendente"
    EXECUTANDO = "executando"
    CONCLUIDO = "concluido"
    ERRO = "erro"
    PULADO = "pulado"
    INCERTO = "incerto"


class PipelineStatus(str, enum.Enum):
    """Lifecycle states of a pipeline execution."""
    CRIADO = "criado"
    NAO_INICIADO = "nao_iniciado"
    EXECUTANDO = "executando"
    PAUSADO = "pausado"
    CONCLUIDO = "concluido"
    CANCELADO = "cancelado"
    INTERROMPIDO = "interrompido"
    INCERTO = "incerto"


class ModelName(str, enum.Enum):
    """Supported Claude model names (UI display name)."""
    OPUS = "Opus"
    SONNET = "Sonnet"
    HAIKU = "Haiku"


class ModelType(str, enum.Enum):
    """Supported Claude model types (DB/backend key, matches ModelName)."""
    OPUS = "opus"
    SONNET = "sonnet"
    HAIKU = "haiku"


class InteractionType(str, enum.Enum):
    """How the command handles user interaction (UI/legacy)."""
    AUTO = "auto"           # Runs automatically, no user input needed
    INTERACTIVE = "inter"   # Requires user input during execution


class EffortLevel(str, enum.Enum):
    """Claude Code `/effort` levels mirrored as CLI flag values."""
    LOW = "low"
    STANDARD = "medium"
    HIGH = "high"
    MAX = "max"


class CommandInteractionType(str, enum.Enum):
    """How the command handles user interaction (DB/backend key)."""
    SEM_INTERACAO = "sem_interacao"   # Runs automatically
    INTERATIVO = "interativo"         # Requires user input during execution
    TIMEOUT = "timeout"               # Interactive with timeout fallback


class TemplateType(str, enum.Enum):
    """Template category."""
    FACTORY = "factory"    # Built-in/factory templates
    CUSTOM = "custom"      # User-created templates


class LogLevel(str, enum.Enum):
    """Log severity levels."""
    DEBUG = "debug"
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class PermissionMode(str, enum.Enum):
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
    estimated_seconds: int | None = None       # Time estimate (optional)
    phase: str = "F?"                              # Pipeline phase (F1, F2, ...)
    config_path: str = ""                         # e.g. ".claude/projects/meu-projeto.json"
    effort: EffortLevel = EffortLevel.STANDARD    # Claude Code /effort level

    def display_name(self) -> str:
        """Return formatted display string."""
        return self.name

    def model_badge_text(self) -> str:
        """Return short model name for badge display."""
        return self.model.value

    def interaction_badge_text(self) -> str:
        """Return short interaction type for badge display."""
        return "→ auto" if self.interaction_type == InteractionType.AUTO else "↔ inter"

    def effort_badge_text(self) -> str:
        """Return short effort level for badge display."""
        return self.effort.value


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


@dataclass
class TemplateDTO:
    """Data Transfer Object for a pipeline template."""
    id: int | None
    name: str
    description: str = ""
    template_type: TemplateType = TemplateType.CUSTOM
    is_factory: bool = False
    sha256: str | None = None
    commands: list[CommandSpec] = field(default_factory=list)


@dataclass
class ValidationReport:
    """Result of a dry-run validation pass."""
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    # Private: populated by DryRunValidator with Suggestion objects for actionable UI.
    # Not part of the public constructor — set directly after creation.
    _suggestion_objects: list = field(default_factory=list, init=False, repr=False)

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0


@dataclass
class PipelineMetricsRecord:
    """Point-in-time snapshot of pipeline metrics for history/export."""
    pipeline_id: int
    total_commands: int
    completed_commands: int
    failed_commands: int
    skipped_commands: int
    elapsed_seconds: int
    tokens_input: int = 0
    tokens_output: int = 0
    cost_usd: float = 0.0


@dataclass
class FilterSpec:
    """Filter criteria for history queries."""
    status: PipelineStatus | None = None
    project_path: str | None = None
    date_from: str | None = None     # ISO date string YYYY-MM-DD
    date_to: str | None = None
    limit: int = 50
    offset: int = 0


@dataclass
class PipelineResumeContext:
    """Context needed to resume an interrupted pipeline execution."""
    pipeline_id: int
    last_completed_command_index: int
    project_config_path: str
    commands: list[CommandSpec] = field(default_factory=list)
