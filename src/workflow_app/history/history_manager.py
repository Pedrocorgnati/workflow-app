"""
HistoryManager — Paginated history queries and metrics (module-14/TASK-1).

Provides:
  - list_executions(): paginated list with optional FilterSpec
  - get_execution_detail(): single execution with commands eager-loaded
  - get_metrics(): aggregate counters for the metrics bar
  - export_execution_markdown(): markdown summary for a given execution
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from sqlalchemy.orm import sessionmaker

from workflow_app.db.models import CommandExecution, PipelineExecution
from workflow_app.domain import CommandStatus, FilterSpec, PipelineStatus


@dataclass
class PaginatedResult:
    """Result of a paginated history query."""

    items: list
    total_count: int
    page: int
    page_size: int
    total_pages: int


class HistoryManager:
    """Camada de acesso a dados para histórico de execuções."""

    def __init__(self, session_factory: sessionmaker) -> None:
        self._session_factory = session_factory

    # ─── Public API ─────────────────────────────────────────────────── #

    def list_executions(
        self,
        filter_spec: FilterSpec | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> PaginatedResult:
        """Lista execuções paginadas com filtros opcionais.

        Args:
            filter_spec: Filtros de status, data e projeto. None = sem filtros.
            page: Número da página (começa em 1).
            page_size: Itens por página.

        Returns:
            PaginatedResult com itens detachados (seguros fora da sessão).
        """
        with self._session_factory() as session:
            query = session.query(PipelineExecution).order_by(
                PipelineExecution.created_at.desc()
            )

            if filter_spec is not None:
                if filter_spec.status is not None:
                    # Accept both PipelineStatus enum and plain string
                    status_val = (
                        filter_spec.status.value
                        if isinstance(filter_spec.status, PipelineStatus)
                        else str(filter_spec.status)
                    )
                    query = query.filter(PipelineExecution.status == status_val)

                if filter_spec.date_from:
                    query = query.filter(
                        PipelineExecution.created_at >= filter_spec.date_from
                    )
                if filter_spec.date_to:
                    query = query.filter(
                        PipelineExecution.created_at <= filter_spec.date_to
                    )
                if filter_spec.project_path:
                    query = query.filter(
                        PipelineExecution.project_config_path
                        == filter_spec.project_path
                    )

            total = query.count()
            offset = (page - 1) * page_size
            items = query.offset(offset).limit(page_size).all()
            total_pages = math.ceil(total / page_size) if total else 1

            # Detach so objects are usable after session closes
            for item in items:
                session.expunge(item)

        return PaginatedResult(
            items=list(items),
            total_count=total,
            page=page,
            page_size=page_size,
            total_pages=total_pages,
        )

    def get_execution_detail(
        self, pipeline_exec_id: int
    ) -> PipelineExecution | None:
        """Retorna execução com comandos eager-loaded.

        Returns:
            PipelineExecution detachado com .commands populado, ou None.
        """
        with self._session_factory() as session:
            pe = session.get(PipelineExecution, pipeline_exec_id)
            if pe is None:
                return None

            # Eager-load the commands relationship before detaching
            commands = list(pe.commands)
            session.expunge_all()

        # Re-attach commands list to the detached pe instance
        pe.commands = commands
        return pe

    def get_metrics(self) -> dict:
        """Agrega métricas globais de autoavaliação.

        Returns:
            Dict com: total_pipelines, completed_pipelines,
                      total_commands, error_commands, success_rate.
        """
        with self._session_factory() as session:
            total_pipelines = session.query(PipelineExecution).count()
            completed = (
                session.query(PipelineExecution)
                .filter(
                    PipelineExecution.status == PipelineStatus.CONCLUIDO.value
                )
                .count()
            )
            total_commands = session.query(CommandExecution).count()
            error_commands = (
                session.query(CommandExecution)
                .filter(
                    CommandExecution.status == CommandStatus.ERRO.value
                )
                .count()
            )

        success_rate = (
            round(
                (total_commands - error_commands) / total_commands * 100, 1
            )
            if total_commands
            else 0.0
        )
        return {
            "total_pipelines": total_pipelines,
            "completed_pipelines": completed,
            "total_commands": total_commands,
            "error_commands": error_commands,
            "success_rate": success_rate,
        }

    def export_execution_markdown(self, pipeline_exec_id: int) -> str:
        """Gera string markdown com resumo da execução.

        Args:
            pipeline_exec_id: ID da PipelineExecution a exportar.

        Returns:
            String markdown. Salvar externamente com QFileDialog.
        """
        pe = self.get_execution_detail(pipeline_exec_id)
        if pe is None:
            return "# Execução não encontrada\n"

        created = (
            pe.created_at.strftime("%Y-%m-%d %H:%M") if pe.created_at else "—"
        )
        lines = [
            f"# Resumo da Execução ID {pe.id}",
            "",
            f"**Data:** {created}",
            f"**Status:** {pe.status.upper()}",
            "",
            "## Comandos",
            "",
            "| # | Comando | Modelo | Status | Duração |",
            "|---|---------|--------|--------|---------|",
        ]
        commands = sorted(
            getattr(pe, "commands", []), key=lambda c: c.position
        )
        for cmd in commands:
            dur = (
                f"{cmd.elapsed_seconds}s"
                if getattr(cmd, "elapsed_seconds", None)
                else "—"
            )
            model = getattr(cmd, "model", "—") or "—"
            lines.append(
                f"| {cmd.position + 1} | {cmd.command_name}"
                f" | {model} | {cmd.status} | {dur} |"
            )

        return "\n".join(lines)
