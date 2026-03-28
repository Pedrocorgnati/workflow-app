"""
InterviewEngine — Guided interview for pipeline creation (module-04/TASK-1).

Replicates the SystemForge pipeline logic:
  Maps project_type + stack + has_frontend + active_phases → list[CommandSpec]

Usage:
    engine = InterviewEngine()
    questions = engine.start_interview()          # → list[InterviewQuestion]
    commands  = engine.generate_command_list(answers)  # answers: dict
"""

from __future__ import annotations

from dataclasses import dataclass

from workflow_app.domain import CommandSpec, InteractionType, ModelName

# ─── InterviewQuestion ───────────────────────────────────────────────────── #


@dataclass
class InterviewQuestion:
    """A single question in the guided interview."""

    id: str                                 # Unique identifier, e.g. "project_type"
    question: str                           # Human-readable question text
    field_name: str                         # Key used in answers dict
    options: list[str]                      # Available choices
    hint: str | None = None              # Optional helper text shown below question
    multi_select: bool = False              # True → checkboxes, False → radio buttons
    depends_on: dict | None = None      # {field_name: expected_value} for conditional display


# ─── Pipeline command catalogue ─────────────────────────────────────────── #
#
# Tuple layout: (name, ModelName, InteractionType, is_optional, phases)
# phases: list of phase codes ("f1", "f2", …, "f12")
#

_PipelineEntry = tuple[str, ModelName, InteractionType, bool, list[str]]

PIPELINE_COMMANDS: list[_PipelineEntry] = [
    # F1 — Brief
    ("/project-json",          ModelName.SONNET, InteractionType.INTERACTIVE, False, ["f1"]),
    ("/first-brief-create",    ModelName.OPUS,   InteractionType.INTERACTIVE, False, ["f1"]),
    ("/intake:analyze",        ModelName.SONNET, InteractionType.AUTO,        True,  ["f1"]),
    ("/intake:enhance",        ModelName.OPUS,   InteractionType.INTERACTIVE, True,  ["f1"]),
    ("/tech-feasibility",      ModelName.OPUS,   InteractionType.AUTO,        True,  ["f1"]),
    # F2 — PRD
    ("/prd-create",            ModelName.OPUS,   InteractionType.AUTO,        False, ["f2"]),
    ("/user-stories-create",   ModelName.SONNET, InteractionType.AUTO,        False, ["f2"]),
    ("/hld-create",            ModelName.OPUS,   InteractionType.AUTO,        False, ["f2"]),
    ("/lld-create",            ModelName.OPUS,   InteractionType.AUTO,        False, ["f2"]),
    ("/design-create",         ModelName.OPUS,   InteractionType.AUTO,        True,  ["f2"]),
    ("/review-prd-flow",       ModelName.OPUS,   InteractionType.INTERACTIVE, False, ["f2"]),
    # F3 — SystemForge optimization
    ("/optimize:scaffolds",    ModelName.OPUS,   InteractionType.AUTO,        True,  ["f3"]),
    ("/optimize:blueprints",   ModelName.OPUS,   InteractionType.AUTO,        True,  ["f3"]),
    # F4 — WBS
    ("/auto-flow modules",     ModelName.OPUS,   InteractionType.INTERACTIVE, False, ["f4"]),
    # F5 — WBS+
    ("/auto-flow create",      ModelName.SONNET, InteractionType.AUTO,        False, ["f5"]),
    ("/validate-pipeline",     ModelName.SONNET, InteractionType.AUTO,        False, ["f5"]),
    # F7 — Execution
    ("/mobile-first-build",    ModelName.SONNET, InteractionType.AUTO,        False, ["f7", "frontend"]),
    ("/front-end-build",       ModelName.SONNET, InteractionType.AUTO,        False, ["f7", "frontend"]),
    ("/data-test-id",          ModelName.SONNET, InteractionType.AUTO,        False, ["f7", "frontend"]),
    ("/create-assets",         ModelName.HAIKU,  InteractionType.AUTO,        True,  ["f7", "frontend"]),
    ("/create-mocks",          ModelName.SONNET, InteractionType.AUTO,        True,  ["f7"]),
    ("/github-linking",        ModelName.HAIKU,  InteractionType.AUTO,        True,  ["f7"]),
    ("/auto-flow execute",     ModelName.SONNET, InteractionType.AUTO,        False, ["f7"]),
    # F8 — Complemento
    ("/env-creation",          ModelName.HAIKU,  InteractionType.AUTO,        True,  ["f8"]),
    ("/seed-data-create",      ModelName.SONNET, InteractionType.AUTO,        True,  ["f8"]),
    ("/docker-create",         ModelName.SONNET, InteractionType.AUTO,        True,  ["f8"]),
    # F9 — QA
    ("/qa:prep",               ModelName.SONNET, InteractionType.AUTO,        True,  ["f9"]),
    ("/qa:trace",              ModelName.OPUS,   InteractionType.AUTO,        True,  ["f9"]),
    ("/qa:report",             ModelName.SONNET, InteractionType.AUTO,        True,  ["f9"]),
    # F10 — Validation
    ("/review-language",       ModelName.HAIKU,  InteractionType.AUTO,        True,  ["f10"]),
    ("/validate-stack",        ModelName.HAIKU,  InteractionType.AUTO,        True,  ["f10"]),
    ("/final-review",          ModelName.SONNET, InteractionType.AUTO,        True,  ["f10"]),
    # F11 — Deploy
    ("/ci-cd-create",          ModelName.SONNET, InteractionType.AUTO,        True,  ["f11"]),
    ("/pre-deploy-testing",    ModelName.SONNET, InteractionType.AUTO,        False, ["f11"]),
    ("/monitoring-setup",      ModelName.SONNET, InteractionType.AUTO,        True,  ["f11"]),
    ("/deploy-flow",           ModelName.SONNET, InteractionType.AUTO,        True,  ["f11"]),
]

# Feature-specific subset (no HLD, starts with feature-brief)
_FEATURE_COMMANDS: list[_PipelineEntry] = [
    ("/feature-brief-create",  ModelName.OPUS,   InteractionType.INTERACTIVE, False, ["f1"]),
    ("/prd-create",            ModelName.OPUS,   InteractionType.AUTO,        False, ["f2"]),
    ("/user-stories-create",   ModelName.SONNET, InteractionType.AUTO,        False, ["f2"]),
    ("/fdd-create",            ModelName.OPUS,   InteractionType.AUTO,        False, ["f2"]),
    ("/lld-create",            ModelName.OPUS,   InteractionType.AUTO,        False, ["f2"]),
    ("/review-prd-flow",       ModelName.OPUS,   InteractionType.INTERACTIVE, False, ["f2"]),
    ("/auto-flow execute",     ModelName.SONNET, InteractionType.AUTO,        False, ["f7"]),
]

# Stack tags that indicate no frontend is needed (backend/desktop stacks)
_NO_FRONTEND_STACKS: frozenset[str] = frozenset(
    {"pyside6", "pyqt6", "tkinter", "fastapi", "django", "flask"}
)

# Phase codes that are always included regardless of selection
_MANDATORY_PHASES: frozenset[str] = frozenset({"f1", "f2", "f7"})


# ─── Standard interview questions ────────────────────────────────────────── #

_QUESTIONS: list[InterviewQuestion] = [
    InterviewQuestion(
        id="project_type",
        question="Qual é o tipo do projeto?",
        field_name="project_type",
        options=["novo", "feature", "feature_grande", "feature_pequena", "refactor"],
        hint="'novo' = projeto do zero (F1–F12). 'feature' = nova funcionalidade em projeto existente.",
    ),
    InterviewQuestion(
        id="stack",
        question="Qual é a stack principal?",
        field_name="stack",
        options=["nextjs", "pyside6", "react", "vue", "fastapi", "django", "flutter", "other"],
        hint="Isso determina se /front-end-build e /create-assets serão incluídos.",
    ),
    InterviewQuestion(
        id="has_frontend",
        question="O projeto inclui interface gráfica (frontend)?",
        field_name="has_frontend",
        options=["sim", "não"],
        hint="'não' remove os comandos de frontend da fila.",
        depends_on={"stack": "other"},  # only asked when stack is unclear
    ),
    InterviewQuestion(
        id="active_phases",
        question="Quais fases do pipeline deseja incluir?",
        field_name="active_phases",
        options=["f1", "f2", "f3", "f4", "f5", "f7", "f8", "f9", "f10", "f11"],
        hint="F1=Brief, F2=PRD, F3=Otimização, F4=WBS, F5=WBS+, F7=Execução, F8=Extras, F9=QA, F10=Validação, F11=Deploy",
        multi_select=True,
    ),
]


# ─── InterviewEngine ─────────────────────────────────────────────────────── #


class InterviewEngine:
    """
    Generates a CommandSpec list from interview answers.

    Implements the pipeline logic, mapping:
      project_type + stack + has_frontend + active_phases → list[CommandSpec]
    """

    def start_interview(self, config: dict | None = None) -> list[InterviewQuestion]:
        """
        Return the ordered list of questions for the guided interview.

        Args:
            config: Optional project config dict. If provided, pre-selects
                    defaults based on existing project settings.

        Returns:
            Ordered list of InterviewQuestion objects.
        """
        return list(_QUESTIONS)

    def generate_command_list(self, answers: dict) -> list[CommandSpec]:
        """
        Generate a CommandSpec list from interview answers.

        Args:
            answers: dict with keys:
                - project_type: str — "novo" | "feature" | "feature_grande" |
                                      "feature_pequena" | "refactor"
                - stack: str (optional) — e.g. "nextjs", "pyside6"
                - has_frontend: str (optional) — "sim" | "não"
                - active_phases: list[str] (optional) — e.g. ["f1", "f2", "f7"]

        Returns:
            Ordered list of CommandSpec objects.

        Raises:
            ValueError: if project_type is missing or unknown.
        """
        self._validate_answers(answers)

        project_type = answers.get("project_type", "novo")
        stack = answers.get("stack", "").lower()
        has_frontend_str = answers.get("has_frontend", "").lower()
        active_phases: list[str] = answers.get("active_phases", [])

        # Normalise project_type aliases
        if project_type in ("feature", "feature_grande", "feature_pequena"):
            return self._build_feature_pipeline(
                project_type, stack, has_frontend_str, active_phases
            )

        if project_type == "novo":
            return self._build_novo_pipeline(stack, has_frontend_str, active_phases)

        if project_type == "refactor":
            return self._build_refactor_pipeline(stack, active_phases)

        raise ValueError(
            f"Tipo de projeto desconhecido: '{project_type}'. "
            "Selecione uma das opções disponíveis."
        )

    # ── Private builders ─────────────────────────────────────────────── #

    def _build_novo_pipeline(
        self,
        stack: str,
        has_frontend_str: str,
        active_phases: list[str],
    ) -> list[CommandSpec]:
        include_frontend = self._should_include_frontend(stack, has_frontend_str)
        phases = self._resolve_phases(active_phases)

        entries: list[_PipelineEntry] = []
        for entry in PIPELINE_COMMANDS:
            name, model, inter, optional, cmd_phases = entry
            # Check phase membership
            if not any(p in phases for p in cmd_phases):
                continue
            # Filter frontend-only commands
            if "frontend" in cmd_phases and not include_frontend:
                continue
            entries.append(entry)

        return self._build_from_entries(entries)

    def _build_feature_pipeline(
        self,
        project_type: str,
        stack: str,
        has_frontend_str: str,
        active_phases: list[str],
    ) -> list[CommandSpec]:
        include_frontend = self._should_include_frontend(stack, has_frontend_str)
        phases = self._resolve_phases(active_phases)

        entries: list[_PipelineEntry] = []
        for entry in _FEATURE_COMMANDS:
            name, model, inter, optional, cmd_phases = entry
            if not any(p in phases for p in cmd_phases):
                continue
            entries.append(entry)

        if include_frontend and any(p in phases for p in ("f7", "frontend")):
            idx = max(len(entries) - 1, 0)
            entries.insert(idx, (
                "/mobile-first-build", ModelName.SONNET, InteractionType.AUTO, False, ["f7", "frontend"]
            ))
            entries.insert(idx + 1, (
                "/front-end-build", ModelName.SONNET, InteractionType.AUTO, False, ["f7", "frontend"]
            ))
            entries.insert(idx + 2, (
                "/data-test-id", ModelName.SONNET, InteractionType.AUTO, False, ["f7", "frontend"]
            ))
        return self._build_from_entries(entries)

    def _build_refactor_pipeline(
        self,
        stack: str,
        active_phases: list[str],
    ) -> list[CommandSpec]:
        phases = self._resolve_phases(active_phases) if active_phases else {"f2", "f7", "f9", "f10"}
        entries = [
            e for e in PIPELINE_COMMANDS
            if any(p in phases for p in e[4]) and "frontend" not in e[4]
        ]
        return self._build_from_entries(entries)

    # ── Helpers ─────────────────────────────────────────────────────── #

    def _validate_answers(self, answers: dict) -> None:
        """Raise ValueError if answers are structurally invalid."""
        if not isinstance(answers, dict):
            raise ValueError("answers must be a dict")
        project_type = answers.get("project_type")
        if not project_type:
            raise ValueError(
                "Resposta obrigatória ausente: 'project_type'. "
                "Opções: novo, feature, feature_grande, feature_pequena, refactor."
            )

    @staticmethod
    def _should_include_frontend(stack: str, has_frontend_str: str) -> bool:
        """Determine whether frontend commands should be included."""
        if stack in _NO_FRONTEND_STACKS and stack != "":
            return False
        if has_frontend_str == "não":
            return False
        # Default: include frontend unless explicitly excluded
        return True

    @staticmethod
    def _resolve_phases(active_phases: list[str]) -> set[str]:
        """Build the full set of phases to include."""
        if not active_phases:
            # Default: include F1, F2, F4, F5, F7
            return {"f1", "f2", "f4", "f5", "f7"}
        return _MANDATORY_PHASES | set(active_phases)

    @staticmethod
    def _build_from_entries(entries: list[_PipelineEntry]) -> list[CommandSpec]:
        return [
            CommandSpec(
                name=name,
                model=model,
                interaction_type=inter,
                position=idx + 1,
                is_optional=optional,
            )
            for idx, (name, model, inter, optional, _phases) in enumerate(entries)
        ]

    # ── Legacy / convenience API ─────────────────────────────────────── #

    def get_stub_template(self) -> list[CommandSpec]:
        """Return the default 'Projeto Novo' pipeline (F1-F11, all phases)."""
        return self.generate_command_list({"project_type": "novo"})
