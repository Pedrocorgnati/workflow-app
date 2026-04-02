"""
DryRunValidator — offline validation of the CommandSpec queue (module-06/TASK-1).

Validates the pipeline queue without calling Claude.
Returns ValidationReport with errors, warnings, and actionable Suggestion objects.

Classes:
    Suggestion         — actionable recommendation for improving the queue
    DryRunValidator    — stateless validator; call validate(commands) → ValidationReport
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path

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

    # Novos comandos críticos introduzidos no fluxo
    _CANONICAL_GATE_COMMANDS: tuple[str, ...] = (
        "/intake-conformity-check",
        "/validate-pipeline",
    )

    _FRONTEND_RUNTIME_CHAIN: tuple[str, ...] = (
        "/front-end-review",
        "/gate:frontend-runtime",
        "/build-verify",
    )

    _SEMANTIC_QA_COMMANDS: tuple[str, ...] = (
        "/brief-vs-frontend-review",
    )

    def _load_phase_contracts(self) -> dict:
        """Load PHASE-CONTRACTS.json from workflow-app if available.

        Falls back to an empty dict when file is missing or invalid.
        """
        root = Path(__file__).resolve().parents[3]
        contracts_path = (
            root / "ai-forge" / "pipeline-contracts" / "PHASE-CONTRACTS.json"
        )
        if not contracts_path.exists():
            return {}
        try:
            return json.loads(contracts_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Falha ao carregar PHASE-CONTRACTS.json: %s", exc)
            return {}

    @staticmethod
    def _first_index(names: list[str], commands: tuple[str, ...] | list[str]) -> int | None:
        idx = [i for i, n in enumerate(names) if n in set(commands)]
        return min(idx) if idx else None

    @staticmethod
    def _has_any(names: list[str], commands: tuple[str, ...] | list[str]) -> bool:
        commands_set = set(commands)
        return any(n in commands_set for n in names)

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
        phase_contracts = self._load_phase_contracts()

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

        # ── Rule 6: canonical pre-F7 gate when execution exists ────────────── #
        has_execution = self._has_any(names, tuple(self._F7_COMMANDS))
        if has_execution:
            for gate_cmd in self._CANONICAL_GATE_COMMANDS:
                if gate_cmd not in names:
                    errors.append(
                        f"Comando obrigatório ausente antes da execução: {gate_cmd}."
                    )
                    sug = Suggestion(
                        text=f"Adicionar {gate_cmd} antes do primeiro comando de execução",
                        command_to_add=gate_cmd,
                        recommended_position=max(0, (first_f7_idx or 0)),
                        reason="Gate canônico PRE-F7 obrigatório para reduzir regressões",
                    )
                    suggestion_objects.append(sug)
                    suggestions.append(sug.text)

        # ── Rule 7: front-end runtime chain enforcement ───────────────────── #
        has_fe_or_verify = self._has_any(names, self._FRONTEND_RUNTIME_CHAIN)
        if has_fe_or_verify:
            missing_chain = [c for c in self._FRONTEND_RUNTIME_CHAIN if c not in names]
            for cmd_name in missing_chain:
                warnings.append(
                    f"Cadeia de runtime incompleta: falta {cmd_name} "
                    "(front-end-review -> gate:frontend-runtime -> build-verify)."
                )
            if not missing_chain:
                idx_review = names.index("/front-end-review")
                idx_gate = names.index("/gate:frontend-runtime")
                idx_verify = names.index("/build-verify")
                if not (idx_review < idx_gate < idx_verify):
                    errors.append(
                        "Ordem inválida da cadeia de runtime: esperado "
                        "/front-end-review -> /gate:frontend-runtime -> /build-verify."
                    )

        # ── Rule 8: semantic QA command suggestion/check ──────────────────── #
        has_qa = self._has_any(names, tuple(self._QA_COMMANDS))
        if has_qa and "/brief-vs-frontend-review" not in names:
            warnings.append(
                "QA presente sem /brief-vs-frontend-review. "
                "Adicione revisão semântica final do front contra INTAKE."
            )
            qa_insert = max(i for i, n in enumerate(names) if n in self._QA_COMMANDS) + 1
            sug_sem = Suggestion(
                text="Adicionar /brief-vs-frontend-review após a sequência de QA",
                command_to_add="/brief-vs-frontend-review",
                recommended_position=qa_insert,
                reason="Reduz divergência de copy/regras visíveis no front",
            )
            suggestion_objects.append(sug_sem)
            suggestions.append(sug_sem.text)

        # ── Rule 9: contract-driven required commands (optional, additive) ── #
        if phase_contracts:
            try:
                phases = phase_contracts.get("phases", {})
                pre_f7 = phases.get("pre_f7_gate", {})
                required = pre_f7.get("required_commands", [])
                if has_execution:
                    for cmd_name in required:
                        if cmd_name not in names:
                            msg = f"Contrato de fase: comando obrigatório ausente: {cmd_name}."
                            if pre_f7.get("blocking_if_missing", False):
                                if msg not in errors:
                                    errors.append(msg)
                            elif msg not in warnings:
                                warnings.append(msg)
            except Exception as exc:  # defensive: validator never hard-crashes
                logger.warning("Falha ao aplicar PHASE-CONTRACTS.json: %s", exc)

        is_valid = len(errors) == 0
        report = ValidationReport(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings,
            suggestions=suggestions,
        )
        report._suggestion_objects = suggestion_objects
        return report
