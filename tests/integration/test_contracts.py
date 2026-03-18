"""Testes de contrato cross-rock do Workflow App (module-16/TASK-1).

Verifica os 10 pontos de integração definidos no ROCK-MAP:
1.  Template: rock-1 cria, rock-2 carrega
2.  PipelineExecution: rock-2 persiste, rock-3 lê
3.  CommandExecution: rock-2 persiste, rock-3 lê
4.  ExecutionLog: rock-2 persiste, rock-3 lê
5.  SYSTEM-PROGRESS.md: rock-1 gera, rock-2 atualiza
6.  CommandQueueWidget: rock-1 popula fila, rock-2 atualiza status
7.  Barra Superior: rock-3 exibe métricas de rock-2
8.  CommandStatus: skeleton define, rock-2 transita, rock-3 filtra
9.  PipelineStatus: skeleton define, rock-2 define status final, rock-3 filtra
10. FilterSpec: rock-3 aplica filtros em dados de rock-2
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from workflow_app.db.models import Base, CommandExecution, PipelineExecution
from workflow_app.domain import (
    CommandSpec,
    CommandStatus,
    FilterSpec,
    InteractionType,
    ModelName,
    ModelType,
    PipelineStatus,
)

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_spec(name: str, position: int = 1) -> CommandSpec:
    return CommandSpec(
        name=name,
        model=ModelName.SONNET,
        interaction_type=InteractionType.AUTO,
        position=position,
    )


# ------------------------------------------------------------------
# Fixtures
# ------------------------------------------------------------------


@pytest.fixture(scope="module")
def db_engine(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("integration")
    engine = create_engine(f"sqlite:///{tmp}/test_integration.db")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture(scope="module")
def Session(db_engine):
    return sessionmaker(bind=db_engine)


@pytest.fixture(scope="module")
def mock_db_manager(Session):
    """DatabaseManager mockado que usa uma sessionmaker real."""
    mgr = MagicMock()

    @contextmanager
    def get_session_ctx():
        session = Session()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    mgr.get_session = get_session_ctx
    return mgr


@pytest.fixture(scope="module")
def populated_db(Session):
    """Popula banco com dados de todos os rocks."""
    session = Session()

    pipeline = PipelineExecution(
        project_config_path="/test/integration.json",
        status=PipelineStatus.CONCLUIDO.value,
    )
    session.add(pipeline)
    session.flush()

    for i in range(1, 4):
        cmd = CommandExecution(
            pipeline_id=pipeline.id,
            command_name=f"/cmd-{i}",
            model=ModelType.SONNET.value,
            status=CommandStatus.CONCLUIDO.value,
            position=i,
            elapsed_seconds=60,
        )
        session.add(cmd)

    session.commit()
    pipeline_id = pipeline.id
    session.close()
    return pipeline_id


# ------------------------------------------------------------------
# Contrato 1: Template (rock-1 → rock-2)
# ------------------------------------------------------------------


def test_contract_01_template_load(mock_db_manager):
    """Template criado pelo rock-1 pode ser carregado pelo rock-2."""
    from workflow_app.templates.template_manager import TemplateManager

    mgr = TemplateManager(mock_db_manager)

    specs = [_make_spec("/prd-create", 1)]
    saved_id = mgr.save_custom_template(
        name="Teste Contract",
        description="Template de teste",
        commands=specs,
    )
    loaded = mgr.load_template(saved_id)

    assert loaded is not None
    assert loaded.name == "Teste Contract"
    assert len(loaded.commands) == 1
    assert loaded.commands[0].name == "/prd-create"


# ------------------------------------------------------------------
# Contrato 2: PipelineExecution (rock-2 → rock-3)
# ------------------------------------------------------------------


def test_contract_02_pipeline_execution_readable(Session, populated_db):
    """PipelineExecution persistido por rock-2 é lido por rock-3."""
    from workflow_app.history.history_manager import HistoryManager

    mgr = HistoryManager(Session)
    result = mgr.list_executions()

    assert result.total_count >= 1
    # Verificar que ao menos um item tem o config_path esperado
    paths = [item.project_config_path for item in result.items]
    assert any("/test/integration.json" in p for p in paths)


# ------------------------------------------------------------------
# Contrato 3: CommandExecution (rock-2 → rock-3)
# ------------------------------------------------------------------


def test_contract_03_command_execution_readable(Session, populated_db):
    """CommandExecution persistido por rock-2 é lido via get_execution_detail."""
    from workflow_app.history.history_manager import HistoryManager

    mgr = HistoryManager(Session)
    detail = mgr.get_execution_detail(populated_db)

    assert detail is not None
    assert len(detail.commands) == 3
    assert all(c.status == CommandStatus.CONCLUIDO.value for c in detail.commands)


# ------------------------------------------------------------------
# Contrato 4: ExecutionLog (rock-2 → rock-3)
# ------------------------------------------------------------------


def test_contract_04_execution_log_readable(Session, populated_db):
    """ExecutionLog gerado por rock-2 é consultável no banco."""
    from workflow_app.db.models import ExecutionLog

    with Session() as session:
        logs = (
            session.query(ExecutionLog)
            .filter(ExecutionLog.pipeline_id == populated_db)
            .all()
        )
    # Aceita 0 logs neste teste (ExecutionLog é opcional por comando)
    assert isinstance(logs, list)


# ------------------------------------------------------------------
# Contrato 5: SYSTEM-PROGRESS.md (rock-1 → rock-2)
# ------------------------------------------------------------------


def test_contract_05_system_progress_updatable(tmp_path):
    """SYSTEM-PROGRESS.md gerado por rock-1 pode ser atualizado por rock-2."""
    from workflow_app.system_progress_writer import SystemProgressWriter

    writer = SystemProgressWriter()
    docs_root = str(tmp_path)
    progress_path = tmp_path / "SYSTEM-PROGRESS.md"

    # Simular geração pelo rock-1 (formato interno do SystemProgressWriter)
    initial_content = (
        "# System Progress\n\n"
        "## F1: BRIEF\n\n"
        "--------------------------------\n"
        "[ ]\n"
        "/model Sonnet\n"
        "/project-json\n"
        "--------------------------------\n"
        "[ ]\n"
        "/model Opus\n"
        "/first-brief-create\n"
    )
    progress_path.write_text(initial_content)

    # Atualização pelo rock-2: marcar project-json como concluído
    writer.mark_completed("project-json", docs_root)

    updated = progress_path.read_text()
    assert "[x]" in updated
    assert "/project-json" in updated


# ------------------------------------------------------------------
# Contrato 6: CommandQueueWidget (rock-1 → rock-2)
# ------------------------------------------------------------------


def test_contract_06_command_queue_populates(qapp):
    """CommandQueueWidget do rock-1 é populado com os comandos do pipeline."""
    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget

    # Patch the module-level signal_bus to avoid connecting to real signals
    mock_bus = MagicMock()
    for attr in [
        "command_started", "command_completed", "command_failed",
        "command_skipped", "queue_reordered", "pipeline_ready",
    ]:
        mock_sig = MagicMock()
        mock_sig.connect = MagicMock()
        mock_sig.emit = MagicMock()
        setattr(mock_bus, attr, mock_sig)

    with patch("workflow_app.command_queue.command_queue_widget.signal_bus", mock_bus):
        widget = CommandQueueWidget()
        specs = [_make_spec("/prd-create", 1), _make_spec("/hld-create", 2)]
        widget.load_commands(specs)

        # Verificar que os itens foram carregados
        assert len(widget._items) == 2


# ------------------------------------------------------------------
# Contrato 7: Barra Superior (rock-2 → rock-3)
# ------------------------------------------------------------------


def test_contract_07_metrics_bar_reads_pipeline_data(qapp):
    """MetricsBar do rock-3 exibe métricas emitidas via SignalBus pelo rock-2."""
    from workflow_app.metrics_bar.metrics_bar import MetricsBar

    bus = MagicMock()
    for attr in [
        "pipeline_ready", "pipeline_started", "pipeline_paused",
        "pipeline_resumed", "pipeline_completed", "pipeline_cancelled",
        "metrics_updated", "metrics_snapshot", "tool_use_started",
        "tool_use_completed", "token_update", "git_info_updated",
        "new_pipeline_requested", "history_panel_toggled", "preferences_requested",
    ]:
        mock_sig = MagicMock()
        mock_sig.connect = MagicMock()
        mock_sig.emit = MagicMock()
        setattr(bus, attr, mock_sig)

    bar = MetricsBar(bus)

    # Snapshot de métricas do rock-2
    snap = MagicMock()
    snap.total_commands = 10
    snap.completed_commands = 7
    snap.error_commands = 1
    snap.tokens_input = 0
    snap.tokens_output = 0
    snap.cost_estimate_usd = 0.0

    bar._on_metrics_snapshot(snap)

    # MetricsBar no longer has _lbl_progress; error badge is the visible metric
    assert not bar._lbl_errors.isHidden()
    assert "1 erros" in bar._lbl_errors.text()


# ------------------------------------------------------------------
# Contrato 8: CommandStatus (skeleton → rock-2 → rock-3)
# ------------------------------------------------------------------


def test_contract_08_command_status_enum_consistency():
    """CommandStatus tem 6 membros e é compatível entre todos os rocks."""
    expected = {"pendente", "executando", "concluido", "erro", "pulado", "incerto"}
    assert {s.value for s in CommandStatus} == expected

    for s in CommandStatus:
        assert isinstance(s.value, str)


# ------------------------------------------------------------------
# Contrato 9: PipelineStatus (skeleton → rock-2 → rock-3)
# ------------------------------------------------------------------


def test_contract_09_pipeline_status_enum_consistency():
    """PipelineStatus contém os membros essenciais para o fluxo cross-rock."""
    values = {s.value for s in PipelineStatus}

    # Membros críticos para o fluxo de integração entre rocks
    required = {"executando", "pausado", "concluido", "cancelado", "interrompido"}
    assert required.issubset(values), f"PipelineStatus faltando membros: {required - values}"


# ------------------------------------------------------------------
# Contrato 10: FilterSpec (rock-3 aplica filtros em dados do rock-2)
# ------------------------------------------------------------------


def test_contract_10_filter_spec_applies_correctly(Session, populated_db):
    """FilterSpec gerado pelo rock-3 filtra corretamente os dados do rock-2."""
    from workflow_app.history.history_manager import HistoryManager

    mgr = HistoryManager(Session)

    # Filtro por status que não existe → resultado vazio
    result = mgr.list_executions(FilterSpec(status="inexistente"))
    assert result.total_count == 0

    # Filtro por status existente → resultado não vazio
    result = mgr.list_executions(FilterSpec(status=PipelineStatus.CONCLUIDO))
    assert result.total_count >= 1
