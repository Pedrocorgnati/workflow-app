"""Testes de integração: DatabaseManager (module-02/TASK-3).

Cobre:
  - setup() cria tabelas e ativa WAL mode
  - get_session() oferece commit/rollback automático
  - Cascade delete: Template → TemplateCommand
  - FK enforcement: CommandExecution sem pipeline_id válido
  - Idempotência: create_tables() não quebra em segunda chamada
"""
from __future__ import annotations

import pytest
from sqlalchemy import text

from workflow_app.db.database_manager import DatabaseManager
from workflow_app.db.models import (
    CommandExecution,
    PipelineExecution,
    Template,
    TemplateCommand,
)
from workflow_app.domain import CommandStatus, PipelineStatus

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture
def db_manager(tmp_path):
    """DatabaseManager com banco em arquivo temporário."""
    mgr = DatabaseManager()
    mgr.setup(db_path=str(tmp_path / "test.db"))
    yield mgr
    mgr.close()


# ── Setup ─────────────────────────────────────────────────────────────────────


def test_setup_creates_all_tables(db_manager):
    """Todas as tabelas devem existir após setup()."""
    with db_manager.engine.connect() as conn:
        result = conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        )
        tables = {row[0] for row in result}

    expected = {
        "templates",
        "template_commands",
        "pipeline_executions",
        "command_executions",
        "app_configs",
        "execution_logs",
    }
    assert expected.issubset(tables)


def test_wal_mode_active(db_manager):
    """WAL journal_mode deve estar ativo."""
    assert db_manager.verify_wal_mode() is True


def test_create_tables_idempotent(db_manager):
    """create_tables() pode ser chamado várias vezes sem erro."""
    db_manager.create_tables()
    db_manager.create_tables()
    assert db_manager.verify_wal_mode() is True


# ── Session / Commit ──────────────────────────────────────────────────────────


def test_get_session_commits_on_success(db_manager):
    """Dados persistidos dentro de get_session() são visíveis após commit."""
    with db_manager.get_session() as session:
        session.add(
            Template(
                name="TestCommit",
                description="desc",
                template_type="custom",
                is_factory=False,
            )
        )

    with db_manager.get_session() as session:
        t = session.query(Template).filter_by(name="TestCommit").first()
    assert t is not None
    assert t.description == "desc"


def test_get_session_rollback_on_exception(db_manager):
    """Exceção dentro de get_session() deve fazer rollback."""
    with pytest.raises(ValueError):
        with db_manager.get_session() as session:
            session.add(
                Template(
                    name="ShouldRollback",
                    description="never",
                    template_type="custom",
                    is_factory=False,
                )
            )
            session.flush()
            raise ValueError("força rollback")

    with db_manager.get_session() as session:
        t = session.query(Template).filter_by(name="ShouldRollback").first()
    assert t is None


# ── Cascade delete ────────────────────────────────────────────────────────────


def test_cascade_delete_template_removes_commands(db_manager):
    """Deletar Template deve remover TemplateCommand em cascata."""
    with db_manager.get_session() as session:
        tmpl = Template(
            name="CascadeTest",
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
        template_id = tmpl.id

    with db_manager.get_session() as session:
        tmpl = session.get(Template, template_id)
        session.delete(tmpl)

    with db_manager.get_session() as session:
        remaining = (
            session.query(TemplateCommand)
            .filter_by(template_id=template_id)
            .all()
        )
    assert remaining == []


def test_cascade_delete_pipeline_removes_commands(db_manager):
    """Deletar PipelineExecution deve remover CommandExecution em cascata."""
    with db_manager.get_session() as session:
        pe = PipelineExecution(
            project_config_path="/proj/test.json",
            status=PipelineStatus.CONCLUIDO.value,
            commands_total=1,
        )
        session.add(pe)
        session.flush()
        ce = CommandExecution(
            pipeline_id=pe.id,
            position=1,
            command_name="/prd-create",
            model="sonnet",
            status=CommandStatus.CONCLUIDO.value,
        )
        session.add(ce)
        pipeline_id = pe.id

    with db_manager.get_session() as session:
        pe = session.get(PipelineExecution, pipeline_id)
        session.delete(pe)

    with db_manager.get_session() as session:
        remaining = (
            session.query(CommandExecution)
            .filter_by(pipeline_id=pipeline_id)
            .all()
        )
    assert remaining == []


# ── Foreign keys ──────────────────────────────────────────────────────────────


def test_fk_enforcement_command_without_pipeline(db_manager):
    """Inserir CommandExecution com pipeline_id inválido deve falhar."""
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        with db_manager.get_session() as session:
            ce = CommandExecution(
                pipeline_id=99999,  # não existe
                position=1,
                command_name="/test",
                model="sonnet",
                status=CommandStatus.PENDENTE.value,
            )
            session.add(ce)
            session.flush()
