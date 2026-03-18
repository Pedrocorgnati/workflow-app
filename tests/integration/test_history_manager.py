"""Testes de integração: HistoryManager (module-14/TASK-1).

Cobre:
  - list_executions(): paginação, filtros por status/data/projeto
  - get_execution_detail(): eager-load de commands, retorna None para ID inválido
  - get_metrics(): contadores agregados e success_rate
  - export_execution_markdown(): formato e conteúdo do markdown gerado
"""
from __future__ import annotations

import datetime

import pytest

from workflow_app.db.models import CommandExecution, ExecutionLog, PipelineExecution
from workflow_app.domain import CommandStatus, FilterSpec, LogLevel, PipelineStatus
from workflow_app.history.history_manager import HistoryManager

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def history_mgr(int_session_factory):
    return HistoryManager(int_session_factory)


@pytest.fixture(scope="module")
def seed_pipelines(int_session_factory):
    """Popula banco com pipelines em múltiplos estados."""
    session = int_session_factory()

    statuses = [
        PipelineStatus.CONCLUIDO.value,
        PipelineStatus.CONCLUIDO.value,
        PipelineStatus.INTERROMPIDO.value,
        PipelineStatus.CANCELADO.value,
        PipelineStatus.EXECUTANDO.value,
    ]
    ids = []
    for i, status in enumerate(statuses):
        pe = PipelineExecution(
            project_config_path=f"/proj/config-{i}.json",
            status=status,
            commands_total=3,
            commands_completed=3 if status == PipelineStatus.CONCLUIDO.value else 1,
            commands_failed=1 if status == PipelineStatus.INTERROMPIDO.value else 0,
        )
        session.add(pe)
        session.flush()
        ids.append(pe.id)

    # Add commands and a log to the first pipeline
    for pos in range(1, 4):
        cmd = CommandExecution(
            pipeline_id=ids[0],
            position=pos,
            command_name=f"/cmd-{pos}",
            model="sonnet",
            status=CommandStatus.CONCLUIDO.value,
            elapsed_seconds=60 * pos,
        )
        session.add(cmd)

    # Add an error command to the interrupted pipeline
    err_cmd = CommandExecution(
        pipeline_id=ids[2],
        position=1,
        command_name="/failing-cmd",
        model="opus",
        status=CommandStatus.ERRO.value,
        error_message="Processo encerrado",
    )
    session.add(err_cmd)
    session.flush()

    log = ExecutionLog(
        pipeline_id=ids[0],
        level=LogLevel.INFO.value,
        message="Pipeline concluído com sucesso",
    )
    session.add(log)
    session.commit()
    session.close()
    return ids  # [concluido, concluido, interrompido, cancelado, executando]


# ── list_executions ───────────────────────────────────────────────────────────


def test_list_executions_returns_all(history_mgr, seed_pipelines):
    result = history_mgr.list_executions()
    assert result.total_count >= len(seed_pipelines)
    assert isinstance(result.items, list)


def test_list_executions_filter_by_status_concluido(history_mgr, seed_pipelines):
    result = history_mgr.list_executions(
        FilterSpec(status=PipelineStatus.CONCLUIDO)
    )
    for item in result.items:
        assert item.status == PipelineStatus.CONCLUIDO.value


def test_list_executions_filter_by_status_string(history_mgr, seed_pipelines):
    """Aceita string direta além do enum."""
    result = history_mgr.list_executions(
        FilterSpec(status="concluido")
    )
    for item in result.items:
        assert item.status == "concluido"


def test_list_executions_filter_nonexistent_status(history_mgr, seed_pipelines):
    result = history_mgr.list_executions(FilterSpec(status="nao_existe"))
    assert result.total_count == 0
    assert result.items == []


def test_list_executions_filter_by_project_path(history_mgr, seed_pipelines):
    target_path = f"/proj/config-{0}.json"
    result = history_mgr.list_executions(FilterSpec(project_path=target_path))
    assert result.total_count >= 1
    for item in result.items:
        assert item.project_config_path == target_path


def test_list_executions_filter_by_date_range(history_mgr, seed_pipelines):
    future = datetime.datetime.now() + datetime.timedelta(days=1)
    past = datetime.datetime.now() - datetime.timedelta(days=1)

    result = history_mgr.list_executions(
        FilterSpec(date_from=past, date_to=future)
    )
    assert result.total_count >= len(seed_pipelines)


def test_list_executions_date_from_future_returns_empty(history_mgr, seed_pipelines):
    far_future = datetime.datetime.now() + datetime.timedelta(days=365)
    result = history_mgr.list_executions(FilterSpec(date_from=far_future))
    assert result.total_count == 0


# ── Pagination ────────────────────────────────────────────────────────────────


def test_list_executions_pagination_page_size(history_mgr, seed_pipelines):
    result = history_mgr.list_executions(page=1, page_size=2)
    assert len(result.items) <= 2
    assert result.page == 1
    assert result.page_size == 2


def test_list_executions_pagination_total_pages(history_mgr, seed_pipelines):
    result = history_mgr.list_executions(page=1, page_size=2)
    import math
    expected_pages = math.ceil(result.total_count / 2) if result.total_count else 1
    assert result.total_pages == expected_pages


def test_list_executions_pagination_second_page(history_mgr, seed_pipelines):
    page1 = history_mgr.list_executions(page=1, page_size=2)
    page2 = history_mgr.list_executions(page=2, page_size=2)

    ids_page1 = {item.id for item in page1.items}
    ids_page2 = {item.id for item in page2.items}
    assert ids_page1.isdisjoint(ids_page2)


def test_list_executions_beyond_last_page_empty(history_mgr, seed_pipelines):
    result = history_mgr.list_executions(page=99999, page_size=50)
    assert result.items == []


# ── get_execution_detail ──────────────────────────────────────────────────────


def test_get_execution_detail_loads_commands(history_mgr, seed_pipelines):
    pipeline_id = seed_pipelines[0]
    detail = history_mgr.get_execution_detail(pipeline_id)

    assert detail is not None
    assert detail.id == pipeline_id
    assert len(detail.commands) == 3
    positions = [c.position for c in detail.commands]
    assert positions == sorted(positions)


def test_get_execution_detail_commands_status(history_mgr, seed_pipelines):
    pipeline_id = seed_pipelines[0]
    detail = history_mgr.get_execution_detail(pipeline_id)

    for cmd in detail.commands:
        assert cmd.status == CommandStatus.CONCLUIDO.value


def test_get_execution_detail_error_command(history_mgr, seed_pipelines):
    """Pipeline interrompido deve ter command com status erro."""
    interrupted_id = seed_pipelines[2]
    detail = history_mgr.get_execution_detail(interrupted_id)

    assert detail is not None
    error_cmds = [c for c in detail.commands if c.status == CommandStatus.ERRO.value]
    assert len(error_cmds) == 1
    assert error_cmds[0].error_message == "Processo encerrado"


def test_get_execution_detail_nonexistent_returns_none(history_mgr):
    result = history_mgr.get_execution_detail(999999)
    assert result is None


# ── get_metrics ───────────────────────────────────────────────────────────────


def test_get_metrics_structure(history_mgr, seed_pipelines):
    metrics = history_mgr.get_metrics()
    expected_keys = {
        "total_pipelines",
        "completed_pipelines",
        "total_commands",
        "error_commands",
        "success_rate",
    }
    assert expected_keys == set(metrics.keys())


def test_get_metrics_counts_non_negative(history_mgr, seed_pipelines):
    metrics = history_mgr.get_metrics()
    assert metrics["total_pipelines"] >= 0
    assert metrics["completed_pipelines"] >= 0
    assert metrics["total_commands"] >= 0
    assert metrics["error_commands"] >= 0


def test_get_metrics_success_rate_range(history_mgr, seed_pipelines):
    metrics = history_mgr.get_metrics()
    assert 0.0 <= metrics["success_rate"] <= 100.0


def test_get_metrics_completed_le_total(history_mgr, seed_pipelines):
    metrics = history_mgr.get_metrics()
    assert metrics["completed_pipelines"] <= metrics["total_pipelines"]


def test_get_metrics_errors_le_total_commands(history_mgr, seed_pipelines):
    metrics = history_mgr.get_metrics()
    assert metrics["error_commands"] <= metrics["total_commands"]


# ── export_execution_markdown ─────────────────────────────────────────────────


def test_export_markdown_contains_id(history_mgr, seed_pipelines):
    pipeline_id = seed_pipelines[0]
    md = history_mgr.export_execution_markdown(pipeline_id)

    assert str(pipeline_id) in md
    assert "# Resumo da Execução" in md


def test_export_markdown_contains_status(history_mgr, seed_pipelines):
    pipeline_id = seed_pipelines[0]
    md = history_mgr.export_execution_markdown(pipeline_id)

    assert "CONCLUIDO" in md.upper()


def test_export_markdown_contains_command_table(history_mgr, seed_pipelines):
    pipeline_id = seed_pipelines[0]
    md = history_mgr.export_execution_markdown(pipeline_id)

    assert "| # |" in md
    assert "/cmd-1" in md


def test_export_markdown_nonexistent_returns_not_found(history_mgr):
    md = history_mgr.export_execution_markdown(999999)
    assert "não encontrada" in md.lower()
