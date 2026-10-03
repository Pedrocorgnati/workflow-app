"""
Domain enums and dataclasses for Workflow App (module-02/TASK-1).

These are the shared types used throughout the entire application.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field, replace
from typing import Literal, Optional

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


class ModelType(str, enum.Enum):
    """Supported Claude model types (DB/backend key, matches ModelName)."""
    OPUS = "opus"
    SONNET = "sonnet"


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
class FlagSpec:
    """Specification of a command-line flag that requires a value."""
    name: str
    label: str
    placeholder: str = ""
    multiline: bool = False
    options: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class LoopExecutionContext:
    """Correlacao de execucao de loop que viaja junto do comando (Task 15).

    Nasce no builder da fila (`daily_loop/loader.py`), entra no `CommandSpec`,
    sobrevive a snapshot/restore e chega ao dispatcher. E o unico canal legitimo
    de `item_id`: **nao inferir item a partir do texto do comando**. A inferencia
    por texto falha em todo comando que nao carrega `--item` (os expandidos de
    `cmd_complexity: single`, por exemplo) e, pior, acerta o suficiente para
    parecer confiavel enquanto atribui custo ao item errado.

    Frozen de proposito: contexto de correlacao que muda no meio do caminho
    deixa de ser correlacao. Para derivar uma variante, use `with_phase`.

    Todos os campos alem de `loop_id`/`queue_id` sao opcionais porque a mesma
    fila carrega comandos que nao pertencem a item nenhum (`/clear`, `/model`,
    `/effort`, o review final).
    """

    loop_id: str = ""
    queue_id: str = ""
    item_id: Optional[str] = None
    phase: Optional[str] = None
    bucket_id: Optional[str] = None
    mode: Optional[str] = None

    def is_item_scoped(self) -> bool:
        """True quando o comando pertence a um item concreto do loop."""
        return bool(self.item_id)

    def with_phase(self, phase: Optional[str]) -> "LoopExecutionContext":
        return replace(self, phase=phase)

    def to_dict(self) -> dict:
        """Forma serializavel para snapshot. Omite o que e nulo: snapshot com
        chave nula em todo item so engorda o arquivo."""
        d = {"loop_id": self.loop_id, "queue_id": self.queue_id}
        for campo in ("item_id", "phase", "bucket_id", "mode"):
            valor = getattr(self, campo)
            if valor:
                d[campo] = valor
        return d

    @classmethod
    def from_dict(cls, data: object) -> "Optional[LoopExecutionContext]":
        """Reconstroi a partir do snapshot. Snapshot antigo nao tem a chave e
        devolve None — a fila volta sem correlacao, exatamente como antes, em
        vez de estourar (13.1, linha Compatibilidade)."""
        if not isinstance(data, dict):
            return None
        loop_id = str(data.get("loop_id") or "")
        queue_id = str(data.get("queue_id") or "")
        if not loop_id and not queue_id and not data.get("item_id"):
            return None
        def _opt(chave: str):
            valor = data.get(chave)
            if valor is None:
                return None
            texto = str(valor).strip()
            return texto or None
        return cls(
            loop_id=loop_id,
            queue_id=queue_id,
            item_id=_opt("item_id"),
            phase=_opt("phase"),
            bucket_id=_opt("bucket_id"),
            mode=_opt("mode"),
        )


@dataclass
class CommandSpec:
    """Specification of a single command in the pipeline queue.

    This is the primary transfer object between UI components
    (MainWindow → PipelineManager).
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
    testid: str = ""                              # data-testid override for queue item widget
    blocked_reason: str = ""                      # If set, item renders as ERRO with this message
    kimi_eligible: bool = False                   # elegibilidade T2 compartilhada Kimi|Qwen|MiMo; nome mantido por compat com items[].kimi_eligible
    kind: Literal["slash", "local-action"] = "slash"  # Dispatch mode: external slash command vs in-process Python action
    local_action_id: Optional[str] = None         # Identifier into local-actions registry (only when kind=="local-action")
    # Os dois campos abaixo sao OPT-IN do dialogo "Adicionar comando" (checkboxes
    # queue-add-main-llm-N / queue-add-prompt-N), que os passa EXPLICITOS. O
    # default precisa ser False: todo produtor de pipeline (load_pipeline, loops,
    # DCP, botoes de fila) cria CommandSpec sem eles. Com default True, cada item
    # virava "prompt raw" — o step/autocast publicava `/comando` cru sob Main
    # Kimi/Qwen/Codex/Grok e o eixo Worker nunca reivindicava item nenhum
    # (ai-forge/rules/main-llm-publish.md §9, single-arrow-multifunction.md §7 D-8).
    force_main_llm: bool = False                 # When True, forces CLAUDE (green arrow); when False, allows parallel workers (blue arrow)
    is_prompt: bool = False                      # When True, sends text raw without command transformations (no /slash-executor, /skill:, etc.)
    flags_boolean: list[str] = field(default_factory=list)
    flags_with_value: list[FlagSpec] = field(default_factory=list)
    # Correlacao de loop (Task 15). None para todo comando fora de loop —
    # o campo e aditivo e nenhum caller antigo precisa saber que existe.
    loop_context: Optional[LoopExecutionContext] = None

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
