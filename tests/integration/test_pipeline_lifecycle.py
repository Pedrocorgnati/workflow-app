"""Testes de integração: Ciclo de vida completo de um pipeline.

Cobre o fluxo end-to-end de persistência:
  - Criação de PipelineExecution
  - Adição de CommandExecution com transições de status
  - Registro de ExecutionLog por nível
  - Consulta agregada via HistoryManager
  - AppConfig: escrita e leitura de preferências
"""
from __future__ import annotations

import pytest

from workflow_app.db.models import (
    AppConfig,
    CommandExecution,
    ExecutionLog,
    PipelineExecution,
    Template,
    TemplateCommand,
)
from workflow_app.domain import CommandStatus, LogLevel, PipelineStatus
from workflow_app.history.history_manager import HistoryManager

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def session(int_session_factory):
    """Session function-scoped com rollback automático."""
    s = int_session_factory()
    yield s
    s.rollback()
    s.close()


@pytest.fixture
def history_mgr(int_session_factory):
    return HistoryManager(int_session_factory)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _create_pipeline(session, status=PipelineStatus.CONCLUIDO.value, n_commands=3):
    pe = PipelineExecution(
        project_config_path="/test/lifecycle.json",
        status=status,
        commands_total=n_commands,
        commands_completed=n_commands if status == PipelineStatus.CONCLUIDO.value else 0,
    )
    session.add(pe)
    session.flush()

    cmds = []
    for i in range(1, n_commands + 1):
        cmd = CommandExecution(
            pipeline_id=pe.id,
            position=i,
            command_name=f"/cmd-{i}",
            model="sonnet",
            status=CommandStatus.CONCLUIDO.value,
            elapsed_seconds=30 * i,
            tokens_input=100 * i,
            tokens_output=50 * i,
        )
        session.add(cmd)
        cmds.append(cmd)

    session.flush()
    return pe, cmds


# ── Pipeline creation ─────────────────────────────────────────────────────────


def test_create_pipeline_persists(session):
    pe = PipelineExecution(
        project_config_path="/lifecycle/test.json",
        status=PipelineStatus.CRIADO.value,
        commands_total=0,
    )
    session.add(pe)
    session.flush()

    retrieved = session.get(PipelineExecution, pe.id)
    assert retrieved is not None
    assert retrieved.status == PipelineStatus.CRIADO.value
    assert retrieved.project_config_path == "/lifecycle/test.json"


def test_pipeline_status_transition(session):
    """Status pode ser atualizado do criado até concluido."""
    pe = PipelineExecution(
        project_config_path="/lifecycle/transition.json",
        status=PipelineStatus.CRIADO.value,
    )
    session.add(pe)
    session.flush()

    for new_status in [
        PipelineStatus.EXECUTANDO.value,
        PipelineStatus.PAUSADO.value,
        PipelineStatus.EXECUTANDO.value,
        PipelineStatus.CONCLUIDO.value,
    ]:
        pe.status = new_status
        session.flush()
        assert session.get(PipelineExecution, pe.id).status == new_status


# ── Command execution lifecycle ───────────────────────────────────────────────


def test_command_all_statuses_persist(session):
    """Todos os valores de CommandStatus devem ser persistíveis."""
    pe = PipelineExecution(
        project_config_path="/lifecycle/cmd-statuses.json",
        status=PipelineStatus.CONCLUIDO.value,
        commands_total=6,
    )
    session.add(pe)
    session.flush()

    for i, status in enumerate(CommandStatus, start=1):
        cmd = CommandExecution(
            pipeline_id=pe.id,
            position=i,
            command_name=f"/cmd-status-{status.value}",
            model="sonnet",
            status=status.value,
        )
        session.add(cmd)

    session.flush()

    cmds = (
        session.query(CommandExecution)
        .filter_by(pipeline_id=pe.id)
        .all()
    )
    persisted_statuses = {c.status for c in cmds}
    expected = {s.value for s in CommandStatus}
    assert persisted_statuses == expected


def test_command_position_ordering(session):
    """CommandExecution deve ser retornado em ordem de position."""
    pe, cmds = _create_pipeline(session, n_commands=5)

    loaded = (
        session.query(CommandExecution)
        .filter_by(pipeline_id=pe.id)
        .order_by(CommandExecution.position)
        .all()
    )
    positions = [c.position for c in loaded]
    assert positions == sorted(positions)


def test_command_elapsed_seconds_persists(session):
    pe, cmds = _create_pipeline(session, n_commands=2)

    for cmd in cmds:
        loaded = session.get(CommandExecution, cmd.id)
        assert loaded.elapsed_seconds > 0


# ── ExecutionLog ──────────────────────────────────────────────────────────────


def test_execution_log_all_levels(session):
    """Todos os LogLevel devem ser persistíveis."""
    pe, _ = _create_pipeline(session, n_commands=1)

    for level in LogLevel:
        log = ExecutionLog(
            pipeline_id=pe.id,
            level=level.value,
            message=f"Mensagem de nível {level.value}",
        )
        session.add(log)

    session.flush()

    logs = (
        session.query(ExecutionLog)
        .filter_by(pipeline_id=pe.id)
        .all()
    )
    persisted_levels = {log.level for log in logs}
    expected_levels = {level.value for level in LogLevel}
    assert expected_levels.issubset(persisted_levels)


def test_execution_log_with_command_reference(session):
    """ExecutionLog pode referenciar um CommandExecution específico."""
    pe, cmds = _create_pipeline(session, n_commands=1)
    cmd = cmds[0]

    log = ExecutionLog(
        pipeline_id=pe.id,
        command_execution_id=cmd.id,
        level=LogLevel.INFO.value,
        message="Comando concluído",
        export_path="/output/cmd-1.md",
    )
    session.add(log)
    session.flush()

    loaded = session.get(ExecutionLog, log.id)
    assert loaded.command_execution_id == cmd.id
    assert loaded.export_path == "/output/cmd-1.md"


def test_execution_log_without_command_reference(session):
    """ExecutionLog com command_execution_id=None deve persistir."""
    pe, _ = _create_pipeline(session, n_commands=1)

    log = ExecutionLog(
        pipeline_id=pe.id,
        command_execution_id=None,
        level=LogLevel.WARNING.value,
        message="Log sem comando associado",
    )
    session.add(log)
    session.flush()

    loaded = session.get(ExecutionLog, log.id)
    assert loaded.command_execution_id is None


# ── AppConfig ─────────────────────────────────────────────────────────────────


def test_app_config_write_and_read(session):
    """AppConfig deve suportar escrita e leitura de valores."""
    cfg = AppConfig(key="test.theme", value="dark")
    session.add(cfg)
    session.flush()

    loaded = session.query(AppConfig).filter_by(key="test.theme").first()
    assert loaded is not None
    assert loaded.value == "dark"


def test_app_config_update_value(session):
    """AppConfig deve suportar atualização de value."""
    cfg = AppConfig(key="test.language", value="pt-BR")
    session.add(cfg)
    session.flush()

    cfg.value = "en-US"
    session.flush()

    loaded = session.query(AppConfig).filter_by(key="test.language").first()
    assert loaded.value == "en-US"


def test_app_config_null_value(session):
    """AppConfig com value=None deve persistir (campo nullable)."""
    cfg = AppConfig(key="test.optional_setting", value=None)
    session.add(cfg)
    session.flush()

    loaded = session.query(AppConfig).filter_by(key="test.optional_setting").first()
    assert loaded is not None
    assert loaded.value is None


# ── Template → Pipeline link ───────────────────────────────────────────────────


def test_pipeline_linked_to_template(session):
    """PipelineExecution pode referenciar um Template (nullable FK)."""
    tmpl = Template(
        name="Lifecycle Template",
        description="Para teste de lifecycle",
        template_type="custom",
        is_factory=False,
    )
    session.add(tmpl)
    session.flush()

    cmd = TemplateCommand(
        template_id=tmpl.id,
        position=1,
        command_name="/prd-create",
        model_type="sonnet",
        interaction_type="sem_interacao",
    )
    session.add(cmd)

    pe = PipelineExecution(
        project_config_path="/lifecycle/with-template.json",
        status=PipelineStatus.CONCLUIDO.value,
        template_id=tmpl.id,
    )
    session.add(pe)
    session.flush()

    loaded = session.get(PipelineExecution, pe.id)
    assert loaded.template_id == tmpl.id


def test_pipeline_template_set_null_on_template_delete(session):
    """Deletar Template deve setar template_id=NULL no PipelineExecution."""
    tmpl = Template(
        name="DeleteMe Template",
        template_type="custom",
        is_factory=False,
    )
    session.add(tmpl)
    session.flush()

    pe = PipelineExecution(
        project_config_path="/lifecycle/set-null.json",
        status=PipelineStatus.CONCLUIDO.value,
        template_id=tmpl.id,
    )
    session.add(pe)
    session.flush()
    pe_id = pe.id

    session.delete(tmpl)
    session.flush()

    loaded = session.get(PipelineExecution, pe_id)
    assert loaded is not None
    assert loaded.template_id is None


# ── History Manager integration ───────────────────────────────────────────────


def test_full_lifecycle_readable_via_history_manager(int_session_factory, history_mgr):
    """Pipelines criados diretamente no DB são lidos pelo HistoryManager."""
    session = int_session_factory()
    pe = PipelineExecution(
        project_config_path="/lifecycle/history-read.json",
        status=PipelineStatus.CONCLUIDO.value,
        commands_total=2,
        commands_completed=2,
    )
    session.add(pe)
    session.flush()
    for pos in range(1, 3):
        session.add(CommandExecution(
            pipeline_id=pe.id,
            position=pos,
            command_name=f"/history-cmd-{pos}",
            model="haiku",
            status=CommandStatus.CONCLUIDO.value,
            elapsed_seconds=10,
        ))
    session.commit()
    session.close()

    detail = history_mgr.get_execution_detail(pe.id)
    assert detail is not None
    assert len(detail.commands) == 2
    assert detail.status == PipelineStatus.CONCLUIDO.value
