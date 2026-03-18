"""Tests for HistoryManager (module-14/TASK-1)."""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from workflow_app.db.models import Base, CommandExecution, PipelineExecution
from workflow_app.domain import FilterSpec, PipelineStatus
from workflow_app.history.history_manager import HistoryManager, PaginatedResult

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def factory():
    """Fresh in-memory SQLite sessionmaker per test."""
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, expire_on_commit=False)
    yield Session
    engine.dispose()


def _add_pipeline(session, status: str = "concluido") -> PipelineExecution:
    pe = PipelineExecution(
        project_config_path="/tmp/test.json",
        status=status,
    )
    session.add(pe)
    session.commit()
    return pe


# ── list_executions ───────────────────────────────────────────────────────────


def test_list_executions_empty(factory):
    mgr = HistoryManager(factory)
    result = mgr.list_executions()
    assert isinstance(result, PaginatedResult)
    assert result.items == []
    assert result.total_count == 0
    assert result.page == 1
    assert result.total_pages == 1


def test_list_executions_paginated(factory):
    with factory() as session:
        for _ in range(25):
            session.add(
                PipelineExecution(
                    project_config_path="/tmp/test.json",
                    status="concluido",
                )
            )
        session.commit()

    mgr = HistoryManager(factory)
    result = mgr.list_executions(page=1, page_size=10)
    assert len(result.items) == 10
    assert result.total_count == 25
    assert result.total_pages == 3
    assert result.page == 1


def test_list_executions_page_2(factory):
    with factory() as session:
        for _ in range(25):
            session.add(
                PipelineExecution(
                    project_config_path="/tmp/test.json",
                    status="concluido",
                )
            )
        session.commit()

    mgr = HistoryManager(factory)
    result = mgr.list_executions(page=2, page_size=10)
    assert len(result.items) == 10
    assert result.page == 2


def test_list_executions_with_status_filter(factory):
    with factory() as session:
        for status in ["concluido", "concluido", "cancelado"]:
            session.add(
                PipelineExecution(
                    project_config_path="/tmp/test.json",
                    status=status,
                )
            )
        session.commit()

    mgr = HistoryManager(factory)
    spec = FilterSpec(status=PipelineStatus.CONCLUIDO)
    result = mgr.list_executions(filter_spec=spec)
    assert len(result.items) == 2
    for item in result.items:
        assert item.status == "concluido"


def test_list_executions_with_string_status_filter(factory):
    """FilterSpec also accepts plain string for status (backward compat)."""
    with factory() as session:
        session.add(
            PipelineExecution(
                project_config_path="/tmp/test.json",
                status="cancelado",
            )
        )
        session.add(
            PipelineExecution(
                project_config_path="/tmp/test.json",
                status="concluido",
            )
        )
        session.commit()

    mgr = HistoryManager(factory)
    # Pass plain string — should still filter correctly
    spec = FilterSpec(status="cancelado")  # type: ignore[arg-type]
    result = mgr.list_executions(filter_spec=spec)
    assert len(result.items) == 1
    assert result.items[0].status == "cancelado"


def test_list_executions_items_detached(factory):
    """Items must be usable after session closes (expunged)."""
    with factory() as session:
        session.add(
            PipelineExecution(
                project_config_path="/tmp/test.json",
                status="concluido",
            )
        )
        session.commit()

    mgr = HistoryManager(factory)
    result = mgr.list_executions()
    assert len(result.items) == 1
    # Access attributes outside session — must not raise DetachedInstanceError
    assert result.items[0].status == "concluido"


# ── get_execution_detail ──────────────────────────────────────────────────────


def test_get_execution_detail_not_found(factory):
    mgr = HistoryManager(factory)
    assert mgr.get_execution_detail(999) is None


def test_get_execution_detail_with_commands(factory):
    with factory() as session:
        pe = PipelineExecution(
            project_config_path="/tmp/test.json",
            status="concluido",
            commands_total=2,
        )
        session.add(pe)
        session.flush()
        session.add(
            CommandExecution(
                pipeline_id=pe.id,
                position=0,
                command_name="/cmd-a",
                model="sonnet",
                status="concluido",
                elapsed_seconds=5,
            )
        )
        session.add(
            CommandExecution(
                pipeline_id=pe.id,
                position=1,
                command_name="/cmd-b",
                model="opus",
                status="concluido",
                elapsed_seconds=10,
            )
        )
        session.commit()
        pe_id = pe.id

    mgr = HistoryManager(factory)
    detail = mgr.get_execution_detail(pe_id)
    assert detail is not None
    assert detail.id == pe_id
    assert len(detail.commands) == 2
    # Commands ordered by position
    assert detail.commands[0].command_name == "/cmd-a"
    assert detail.commands[1].command_name == "/cmd-b"


# ── get_metrics ───────────────────────────────────────────────────────────────


def test_get_metrics_empty(factory):
    mgr = HistoryManager(factory)
    metrics = mgr.get_metrics()
    assert metrics["total_pipelines"] == 0
    assert metrics["total_commands"] == 0
    assert metrics["success_rate"] == 0.0


def test_get_metrics_with_data(factory):
    with factory() as session:
        pe = PipelineExecution(
            project_config_path="/tmp/test.json",
            status="concluido",
            commands_total=3,
        )
        session.add(pe)
        session.flush()
        for i, status in enumerate(["concluido", "concluido", "erro"]):
            session.add(
                CommandExecution(
                    pipeline_id=pe.id,
                    position=i,
                    command_name=f"/cmd-{i}",
                    model="sonnet",
                    status=status,
                )
            )
        session.commit()

    mgr = HistoryManager(factory)
    metrics = mgr.get_metrics()
    assert metrics["total_pipelines"] == 1
    assert metrics["completed_pipelines"] == 1
    assert metrics["total_commands"] == 3
    assert metrics["error_commands"] == 1
    assert 0.0 <= metrics["success_rate"] <= 100.0


# ── export_execution_markdown ─────────────────────────────────────────────────


def test_export_markdown_not_found(factory):
    mgr = HistoryManager(factory)
    md = mgr.export_execution_markdown(999)
    assert "não encontrada" in md


def test_export_markdown_structure(factory):
    with factory() as session:
        pe = PipelineExecution(
            project_config_path="/tmp/test.json",
            status="concluido",
        )
        session.add(pe)
        session.flush()
        session.add(
            CommandExecution(
                pipeline_id=pe.id,
                position=0,
                command_name="/test-cmd",
                model="sonnet",
                status="concluido",
                elapsed_seconds=10,
            )
        )
        session.commit()
        pe_id = pe.id

    mgr = HistoryManager(factory)
    md = mgr.export_execution_markdown(pe_id)
    assert f"ID {pe_id}" in md
    assert "/test-cmd" in md
    assert "sonnet" in md
    assert "10s" in md
    assert "| # |" in md  # markdown table header
