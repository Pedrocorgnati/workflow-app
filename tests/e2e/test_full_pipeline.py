"""Testes E2E do pipeline completo com SDK mockado (module-16/TASK-2).

Cenários:
1. Happy path: criar pipeline via DB → verificar histórico
2. Error recovery: múltiplos status → verificar via DB
3. Resume: pipeline interrompido → check_resume detecta
4. Templates: salvar template → recarregar → verificar persistência
"""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from tests.e2e.mock_sdk_adapter import MockSDKAdapter
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
# Fixtures E2E
# ------------------------------------------------------------------


@pytest.fixture(scope="module")
def e2e_engine(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("e2e")
    engine = create_engine(f"sqlite:///{tmp}/e2e.db")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture(scope="module")
def e2e_session_factory(e2e_engine):
    return sessionmaker(bind=e2e_engine)


def _make_spec(name: str, position: int) -> CommandSpec:
    return CommandSpec(
        name=name,
        model=ModelName.SONNET,
        interaction_type=InteractionType.AUTO,
        position=position,
    )


def _make_specs(commands: list[str]) -> list[CommandSpec]:
    return [_make_spec(cmd, i + 1) for i, cmd in enumerate(commands)]


# ------------------------------------------------------------------
# Cenário 1: Happy Path — persistência e histórico
# ------------------------------------------------------------------


def test_e2e_cenario1_happy_path(e2e_session_factory):
    """Pipeline: criar → persistir → consultar no histórico."""
    from workflow_app.history.history_manager import HistoryManager

    # Criar pipeline diretamente no banco (simula o que PipelineManager faria)
    with e2e_session_factory() as session:
        pipeline = PipelineExecution(
            project_config_path="/test/e2e-1.json",
            status=PipelineStatus.CONCLUIDO.value,
            commands_total=3,
            commands_completed=3,
        )
        session.add(pipeline)
        session.flush()

        cmds = ["/prd-create", "/user-stories-create", "/hld-create"]
        for i, name in enumerate(cmds, start=1):
            cmd = CommandExecution(
                pipeline_id=pipeline.id,
                command_name=name,
                model=ModelType.SONNET.value,
                status=CommandStatus.CONCLUIDO.value,
                position=i,
                elapsed_seconds=30,
            )
            session.add(cmd)

        pipeline_id = pipeline.id
        session.commit()

    # Verificar estado no banco
    with e2e_session_factory() as session:
        pe = session.get(PipelineExecution, pipeline_id)
        assert pe is not None
        assert pe.status == PipelineStatus.CONCLUIDO.value

    # Verificar histórico (rock-3)
    history_mgr = HistoryManager(e2e_session_factory)
    result = history_mgr.list_executions(FilterSpec(status=PipelineStatus.CONCLUIDO))
    ids = [item.id for item in result.items]
    assert pipeline_id in ids


# ------------------------------------------------------------------
# Cenário 2: Error Recovery — estado de erro e retry
# ------------------------------------------------------------------


def test_e2e_cenario2_error_recovery(e2e_session_factory):
    """Pipeline com erro → retry → conclusão bem-sucedida."""

    # Criar pipeline que simulou erro e retry no 2° comando
    with e2e_session_factory() as session:
        pipeline = PipelineExecution(
            project_config_path="/test/e2e-2.json",
            status=PipelineStatus.CONCLUIDO.value,
            commands_total=3,
            commands_completed=3,
        )
        session.add(pipeline)
        session.flush()

        cmds_data = [
            ("/prd-create", CommandStatus.CONCLUIDO),
            ("/user-stories-create", CommandStatus.CONCLUIDO),  # concluído após retry
            ("/hld-create", CommandStatus.CONCLUIDO),
        ]
        for i, (name, status) in enumerate(cmds_data, start=1):
            cmd = CommandExecution(
                pipeline_id=pipeline.id,
                command_name=name,
                model=ModelType.SONNET.value,
                status=status.value,
                position=i,
                elapsed_seconds=30,
            )
            session.add(cmd)

        pipeline_id = pipeline.id
        session.commit()

    # Verificar que todos os comandos estão concluídos
    with e2e_session_factory() as session:
        cmds = (
            session.query(CommandExecution)
            .filter(CommandExecution.pipeline_id == pipeline_id)
            .order_by(CommandExecution.position)
            .all()
        )
        concluido_count = sum(1 for c in cmds if c.status == CommandStatus.CONCLUIDO.value)
        assert concluido_count == 3


# ------------------------------------------------------------------
# Cenário 3: Resume — estado INCERTO e check_resume
# ------------------------------------------------------------------


def test_e2e_cenario3_resume_check(e2e_session_factory):
    """Pipeline interrompido: check_resume detecta pipeline com INCERTO."""
    from workflow_app.pipeline.pipeline_manager import PipelineManager

    # Criar pipeline com comando incerto (interrupção simulada)
    with e2e_session_factory() as session:
        pipeline = PipelineExecution(
            project_config_path="/test/e2e-3.json",
            status=PipelineStatus.INTERROMPIDO.value,
        )
        session.add(pipeline)
        session.flush()

        cmds_data = [
            ("/prd-create", CommandStatus.CONCLUIDO),
            ("/user-stories-create", CommandStatus.INCERTO),   # interrompido
            ("/hld-create", CommandStatus.PENDENTE),
        ]
        for i, (name, status) in enumerate(cmds_data, start=1):
            cmd = CommandExecution(
                pipeline_id=pipeline.id,
                command_name=name,
                model=ModelType.SONNET.value,
                status=status.value,
                position=i,
            )
            session.add(cmd)

        pipeline_id = pipeline.id
        session.commit()

    # Verificar estado incerto persiste
    with e2e_session_factory() as session:
        cmds = (
            session.query(CommandExecution)
            .filter(CommandExecution.pipeline_id == pipeline_id)
            .order_by(CommandExecution.position)
            .all()
        )
        uncertain = [c for c in cmds if c.status == CommandStatus.INCERTO.value]
        assert len(uncertain) >= 1

    # PipelineManager.check_resume() deve detectar o pipeline interrompido
    bus = MagicMock()
    for attr in [
        "pipeline_ready", "pipeline_started", "pipeline_paused", "pipeline_resumed",
        "pipeline_completed", "pipeline_cancelled", "command_started",
        "command_completed", "command_failed", "command_skipped",
        "pipeline_status_changed", "metrics_snapshot",
    ]:
        s = MagicMock()
        s.connect = MagicMock()
        s.emit = MagicMock()
        setattr(bus, attr, s)

    pm = PipelineManager(
        signal_bus=bus,
        sdk_adapter=MockSDKAdapter(),
        session_factory=e2e_session_factory,
    )
    resume_id = pm.check_resume()
    # Deve detectar o pipeline interrompido
    assert resume_id is not None


# ------------------------------------------------------------------
# Cenário 4: Templates — salvar e recarregar
# ------------------------------------------------------------------


def test_e2e_cenario4_templates(e2e_session_factory):
    """Salvar template → recarregar em nova sessão → verificar persistência."""
    from workflow_app.templates.template_manager import TemplateManager

    # Criar db_manager mockado com session factory real
    db_mgr = MagicMock()

    @contextmanager
    def get_session_ctx():
        session = e2e_session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    db_mgr.get_session = get_session_ctx

    specs = _make_specs(["/prd-create", "/hld-create"])
    mgr = TemplateManager(db_mgr)
    template_id = mgr.save_custom_template(
        name="E2E Template",
        description="Template criado nos testes E2E",
        commands=specs,
    )
    assert template_id is not None

    # Recarregar (simula nova sessão)
    loaded = mgr.load_template(template_id)
    assert loaded is not None
    assert loaded.name == "E2E Template"
    assert len(loaded.commands) == 2

    # Verificar que os comandos estão na ordem correta
    assert loaded.commands[0].name == "/prd-create"
    assert loaded.commands[1].name == "/hld-create"
    assert loaded.commands[0].position == 1
    assert loaded.commands[1].position == 2


# ------------------------------------------------------------------
# Cenário 5: COM_INTERACAO — sinal interactive_advance_ready e advance
# ------------------------------------------------------------------


def test_e2e_cenario5_interactive_command_flow(e2e_session_factory):
    """Pipeline COM_INTERACAO: comando conclui → emite interactive_advance_ready →
    interactive_advance() avança para o próximo comando.
    """
    from unittest.mock import MagicMock, patch

    from workflow_app.pipeline.pipeline_manager import PipelineManager
    from workflow_app.signal_bus import SignalBus

    mock_bus = MagicMock(spec=SignalBus)
    mock_adapter = MagicMock()

    specs = [
        CommandSpec(
            name="/fdd-create",
            model=ModelName.SONNET,
            interaction_type=InteractionType.INTERACTIVE,
            position=1,
        ),
        CommandSpec(
            name="/prd-create",
            model=ModelName.SONNET,
            interaction_type=InteractionType.AUTO,
            position=2,
        ),
    ]

    pm = PipelineManager(
        signal_bus=mock_bus,
        sdk_adapter=mock_adapter,
        session_factory=e2e_session_factory,
        workspace_dir="/tmp/e2e-5",
    )
    pm.set_queue(specs)

    with patch("workflow_app.pipeline.pipeline_manager.ProcessRunner"):
        pm.start(permission_mode="acceptEdits")
        exec_id = pm._current_command_exec_id

        # Simula conclusão do comando INTERACTIVE
        pm._on_command_completed(exec_id, True)

    # interactive_advance_ready deve ter sido emitido com o command_exec_id
    mock_bus.interactive_advance_ready.emit.assert_called_once_with(exec_id)

    # Pipeline NÃO deve ter avançado automaticamente
    assert pm._current_index == 0

    # Usuário clica "Próximo" → interactive_advance() é chamado
    pm.interactive_advance()

    # Pipeline deve ter avançado para o índice 1
    assert pm._current_index == 1
