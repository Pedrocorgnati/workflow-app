"""
DryRunValidator — offline validation of the CommandSpec queue (module-06/TASK-1).

Validates the pipeline queue without calling Claude.
Returns ValidationReport with errors, warnings, and actionable Suggestion objects.

Classes:
    Suggestion         — actionable recommendation for improving the queue
    DryRunValidator    — stateless validator; call validate(commands) → ValidationReport
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from workflow_app.domain import CommandSpec, ValidationReport

logger = logging.getLogger(__name__)


# ─── Suggestion dataclass ─────────────────────────────────────────────────── #


@dataclass
class Suggestion:
    """Actionable suggestion for improving the pipeline queue."""

    text: str                   # Display text shown in UI, e.g. "Adicionar /review-prd-flow"
    command_to_add: str         # Command name to insert, e.g. "/review-prd-flow"
    recommended_position: int   # 0-based insertion index in the queue
    reason: str = ""            # Why this command is recommended


# ─── DryRunValidator ─────────────────────────────────────────────────────── #


class DryRunValidator:
    """
    Validates a CommandSpec queue offline (no Claude API calls).

    Rules applied (in order):
      1. Empty queue → error
      2. No F2 documentation commands present → error (is_valid=False)
      3. F7 commands present without /create-task → warning
      4. Consecutive duplicate commands → warning
      5. ≥2 F2 commands present but /review-prd-flow is absent → Suggestion

    Usage::

        report = DryRunValidator().validate(commands)
        if report.has_errors:
            show_blocking_dialog(report)
        for sug in report._suggestion_objects:
            print(sug.text, "→ insert at", sug.recommended_position)
    """

    _F2_COMMANDS: frozenset[str] = frozenset({
        "/prd-create",
        "/user-stories-create",
        "/hld-create",
        "/lld-create",
        "/fdd-create",
        "/adr-create",
        "/review-prd-flow",
    })

    _F7_COMMANDS: frozenset[str] = frozenset({
        "/execute-task",
        "/auto-flow execute",
        "/review-executed-task",
        "/mobile-first-build",
        "/front-end-build",
        "/data-test-id",
        "/review-executed-module",
    })

    _CREATE_TASK_COMMANDS: frozenset[str] = frozenset({
        "/create-task",
        "/auto-flow create",
    })

    _QA_COMMANDS: frozenset[str] = frozenset({
        "/qa:prep",
        "/qa:trace",
        "/qa:report",
    })

    _DEPLOY_COMMANDS: frozenset[str] = frozenset({
        "/pre-deploy-testing",
        "/ci-cd-create",
        "/changelog-create",
    })

    def validate(self, commands: list[CommandSpec]) -> ValidationReport:
        """
        Validate the pipeline queue offline.

        Args:
            commands: ordered list of CommandSpec (may be empty)

        Returns:
            ValidationReport with ``is_valid``, ``errors``, ``warnings``,
            ``suggestions`` (display strings) and ``_suggestion_objects``
            (Suggestion dataclasses for actionable UI).
        """
        errors: list[str] = []
        warnings: list[str] = []
        suggestions: list[str] = []
        suggestion_objects: list[Suggestion] = []

        names = [cmd.name for cmd in commands]

        # ── Rule 1: empty queue ───────────────────────────────────────────── #
        if not commands:
            errors.append("Fila vazia: adicione pelo menos 1 comando")
            report = ValidationReport(
                is_valid=False,
                errors=errors,
                warnings=warnings,
                suggestions=suggestions,
            )
            report._suggestion_objects = suggestion_objects
            return report

        # ── Rule 2: no F2 documentation commands → error ──────────────────── #
        has_f2 = any(n in self._F2_COMMANDS for n in names)
        if not has_f2:
            errors.append(
                "Nenhum comando de documentação (F2) encontrado. "
                "Adicione pelo menos /prd-create ou /hld-create antes de executar."
            )
        has_f7 = any(n in self._F7_COMMANDS for n in names)

        # ── Rule 3: F7 without create-task preceding it ──────────────────── #
        first_f7_idx = next(
            (i for i, n in enumerate(names) if n in self._F7_COMMANDS), None
        )
        if first_f7_idx is not None:
            create_task_before_f7 = any(
                n in self._CREATE_TASK_COMMANDS for n in names[:first_f7_idx]
            )
            if not create_task_before_f7:
                warnings.append(
                    "execute-task encontrado sem /create-task precedente. "
                    "Adicione /create-task antes de /execute-task para organizar as subtasks"
                )

        # ── Rule 4: consecutive duplicates ───────────────────────────────── #
        for i in range(len(names) - 1):
            if names[i] == names[i + 1]:
                warnings.append(
                    f"{names[i]} aparece consecutivamente "
                    f"nas posições {i + 1} e {i + 2}"
                )

        # ── Rule 5: suggest /review-prd-flow when ≥2 F2 docs and missing ─── #
        f2_non_review_indices = [
            i for i, n in enumerate(names)
            if n in self._F2_COMMANDS and n != "/review-prd-flow"
        ]
        has_review = "/review-prd-flow" in names
        if len(f2_non_review_indices) >= 2 and not has_review:
            last_f2_idx = max(f2_non_review_indices)
            insert_pos = last_f2_idx + 1
            sug = Suggestion(
                text="Adicionar /review-prd-flow após a documentação F2",
                command_to_add="/review-prd-flow",
                recommended_position=insert_pos,
                reason="Recomendado para auditar INTAKE vs docs antes do WBS",
            )
            suggestion_objects.append(sug)
            suggestions.append(sug.text)

        # ── Sugestão QA: quando F7 presente e QA ausente ─────────────────── #
        if has_f7:
            has_qa = any(n in self._QA_COMMANDS for n in names)
            if not has_qa:
                last_f7_idx = max(
                    i for i, n in enumerate(names) if n in self._F7_COMMANDS
                )
                sug_qa = Suggestion(
                    text="Adicionar /qa:prep após os comandos de execução",
                    command_to_add="/qa:prep",
                    recommended_position=last_f7_idx + 1,
                    reason="Recomendado para validar completude após execução das tasks",
                )
                suggestion_objects.append(sug_qa)
                suggestions.append(sug_qa.text)

        is_valid = len(errors) == 0
        report = ValidationReport(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            suggestions=suggestions,
        )
        report._suggestion_objects = suggestion_objects
        return report
