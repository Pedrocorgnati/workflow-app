"""Database model CRUD tests (module-02/TASK-7)."""

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
from workflow_app.domain import CommandStatus

# ── Template ──────────────────────────────────────────────────────────────────


class TestTemplate:
    def test_create(self, db_session):
        tmpl = Template(name="my-template", description="desc")
        db_session.add(tmpl)
        db_session.flush()
        assert tmpl.id is not None

    def test_unique_name(self, db_session):
        from sqlalchemy.exc import IntegrityError

        db_session.add(Template(name="dup-name"))
        db_session.flush()
        db_session.add(Template(name="dup-name"))
        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()

    def test_read(self, db_session):
        tmpl = Template(name="readable", description="hello")
        db_session.add(tmpl)
        db_session.flush()

        fetched = db_session.get(Template, tmpl.id)
        assert fetched is not None
        assert fetched.name == "readable"
        assert fetched.description == "hello"

    def test_update(self, db_session):
        tmpl = Template(name="updatable")
        db_session.add(tmpl)
        db_session.flush()

        tmpl.description = "new desc"
        db_session.flush()

        fetched = db_session.get(Template, tmpl.id)
        assert fetched.description == "new desc"

    def test_delete_cascades_commands(self, db_session):
        tmpl = Template(name="with-commands")
        db_session.add(tmpl)
        db_session.flush()

        cmd = TemplateCommand(
            template_id=tmpl.id,
            position=0,
            command_name="echo hi",
        )
        db_session.add(cmd)
        db_session.flush()
        cmd_id = cmd.id

        db_session.delete(tmpl)
        db_session.flush()

        assert db_session.get(TemplateCommand, cmd_id) is None


# ── TemplateCommand ───────────────────────────────────────────────────────────


class TestTemplateCommand:
    def test_create(self, db_session):
        tmpl = Template(name="tc-tmpl")
        db_session.add(tmpl)
        db_session.flush()

        cmd = TemplateCommand(
            template_id=tmpl.id,
            position=0,
            command_name="echo hello",
            model_type="sonnet",
        )
        db_session.add(cmd)
        db_session.flush()
        assert cmd.id is not None

    def test_unique_position_per_template(self, db_session):
        from sqlalchemy.exc import IntegrityError

        tmpl = Template(name="pos-tmpl")
        db_session.add(tmpl)
        db_session.flush()

        db_session.add(TemplateCommand(template_id=tmpl.id, position=0, command_name="a"))
        db_session.flush()
        db_session.add(TemplateCommand(template_id=tmpl.id, position=0, command_name="b"))
        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()


# ── PipelineExecution ─────────────────────────────────────────────────────────


class TestPipelineExecution:
    def test_create(self, db_session):
        pe = PipelineExecution(project_config_path="/tmp/p.json", status="criado")
        db_session.add(pe)
        db_session.flush()
        assert pe.id is not None

    def test_defaults(self, db_session):
        pe = PipelineExecution(project_config_path="/tmp/p.json", status="criado")
        db_session.add(pe)
        db_session.flush()

        assert pe.commands_total == 0
        assert pe.commands_completed == 0
        assert pe.commands_failed == 0
        assert pe.commands_skipped == 0

    def test_update_status(self, db_session):
        pe = PipelineExecution(project_config_path="/tmp/p.json", status="criado")
        db_session.add(pe)
        db_session.flush()

        pe.status = "executando"
        db_session.flush()

        fetched = db_session.get(PipelineExecution, pe.id)
        assert fetched.status == "executando"


# ── CommandExecution ──────────────────────────────────────────────────────────


class TestCommandExecution:
    def _pipeline(self, session):
        pe = PipelineExecution(project_config_path="/tmp/p.json", status="executando")
        session.add(pe)
        session.flush()
        return pe

    def test_create(self, db_session):
        pe = self._pipeline(db_session)
        ce = CommandExecution(
            pipeline_id=pe.id,
            position=0,
            command_name="echo hi",
            status=CommandStatus.PENDENTE.value,
        )
        db_session.add(ce)
        db_session.flush()
        assert ce.id is not None

    def test_defaults(self, db_session):
        pe = self._pipeline(db_session)
        ce = CommandExecution(
            pipeline_id=pe.id, position=0, command_name="cmd", status="pendente"
        )
        db_session.add(ce)
        db_session.flush()

        assert ce.is_optional is False
        assert ce.tokens_input == 0
        assert ce.tokens_output == 0

    def test_relationship_to_pipeline(self, db_session):
        pe = self._pipeline(db_session)
        ce = CommandExecution(
            pipeline_id=pe.id, position=0, command_name="cmd", status="pendente"
        )
        db_session.add(ce)
        db_session.flush()

        fetched_pe = db_session.get(PipelineExecution, pe.id)
        assert len(fetched_pe.commands) == 1
        assert fetched_pe.commands[0].id == ce.id


# ── AppConfig ─────────────────────────────────────────────────────────────────


class TestAppConfig:
    def test_set_and_get(self, db_session):
        cfg = AppConfig(key="theme", value="dark")
        db_session.add(cfg)
        db_session.flush()

        from sqlalchemy import select

        result = db_session.execute(
            select(AppConfig).where(AppConfig.key == "theme")
        ).scalar_one_or_none()
        assert result is not None
        assert result.value == "dark"

    def test_unique_key(self, db_session):
        from sqlalchemy.exc import IntegrityError

        db_session.add(AppConfig(key="unique-key", value="v1"))
        db_session.flush()
        db_session.add(AppConfig(key="unique-key", value="v2"))
        with pytest.raises(IntegrityError):
            db_session.flush()
        db_session.rollback()


# ── ExecutionLog ──────────────────────────────────────────────────────────────


class TestExecutionLog:
    def test_create_pipeline_log(self, db_session):
        pe = PipelineExecution(project_config_path="/tmp/p.json", status="criado")
        db_session.add(pe)
        db_session.flush()

        log = ExecutionLog(pipeline_id=pe.id, level="info", message="started")
        db_session.add(log)
        db_session.flush()
        assert log.id is not None
        assert log.command_execution_id is None

    def test_create_command_log(self, db_session):
        pe = PipelineExecution(project_config_path="/tmp/p.json", status="executando")
        db_session.add(pe)
        db_session.flush()

        ce = CommandExecution(
            pipeline_id=pe.id, position=0, command_name="cmd", status="executando"
        )
        db_session.add(ce)
        db_session.flush()

        log = ExecutionLog(
            pipeline_id=pe.id,
            command_execution_id=ce.id,
            level="error",
            message="failed",
        )
        db_session.add(log)
        db_session.flush()
        assert log.command_execution_id == ce.id


# ── Session isolation ─────────────────────────────────────────────────────────


class TestPipelineTemplateRelationship:
    """Verify PipelineExecution.template_id FK and bidirectional relationship."""

    def test_pipeline_with_template(self, db_session):
        tmpl = Template(name="linked-tmpl")
        db_session.add(tmpl)
        db_session.flush()

        pe = PipelineExecution(
            template_id=tmpl.id,
            project_config_path="/tmp/p.json",
            status="criado",
        )
        db_session.add(pe)
        db_session.flush()

        assert pe.template is not None
        assert pe.template.name == "linked-tmpl"

    def test_template_executions_relationship(self, db_session):
        tmpl = Template(name="with-execs")
        db_session.add(tmpl)
        db_session.flush()

        pe = PipelineExecution(
            template_id=tmpl.id,
            project_config_path="/tmp/p.json",
            status="criado",
        )
        db_session.add(pe)
        db_session.flush()

        db_session.refresh(tmpl)
        assert len(tmpl.executions) == 1
        assert tmpl.executions[0].id == pe.id

    def test_pipeline_without_template(self, db_session):
        pe = PipelineExecution(
            project_config_path="/tmp/p.json",
            status="criado",
        )
        db_session.add(pe)
        db_session.flush()
        assert pe.template_id is None
        assert pe.template is None

    def test_template_delete_sets_null(self, db_session):
        tmpl = Template(name="will-delete")
        db_session.add(tmpl)
        db_session.flush()

        pe = PipelineExecution(
            template_id=tmpl.id,
            project_config_path="/tmp/p.json",
            status="criado",
        )
        db_session.add(pe)
        db_session.flush()

        db_session.delete(tmpl)
        db_session.flush()
        db_session.expire(pe)

        fetched = db_session.get(PipelineExecution, pe.id)
        assert fetched is not None
        assert fetched.template_id is None


class TestCommandExecutionLogs:
    """Verify CommandExecution.logs and ExecutionLog.command relationships."""

    def test_command_has_logs(self, db_session):
        pe = PipelineExecution(project_config_path="/tmp/p.json", status="executando")
        db_session.add(pe)
        db_session.flush()

        ce = CommandExecution(
            pipeline_id=pe.id, position=0, command_name="cmd", status="executando"
        )
        db_session.add(ce)
        db_session.flush()

        log = ExecutionLog(
            pipeline_id=pe.id,
            command_execution_id=ce.id,
            level="info",
            message="test log",
        )
        db_session.add(log)
        db_session.flush()

        db_session.refresh(ce)
        assert len(ce.logs) == 1
        assert ce.logs[0].message == "test log"

    def test_log_has_command_relationship(self, db_session):
        pe = PipelineExecution(project_config_path="/tmp/p.json", status="executando")
        db_session.add(pe)
        db_session.flush()

        ce = CommandExecution(
            pipeline_id=pe.id, position=0, command_name="cmd", status="executando"
        )
        db_session.add(ce)
        db_session.flush()

        log = ExecutionLog(
            pipeline_id=pe.id,
            command_execution_id=ce.id,
            level="error",
            message="failed",
        )
        db_session.add(log)
        db_session.flush()

        db_session.refresh(log)
        assert log.command is not None
        assert log.command.id == ce.id


class TestExecutionLogNewFields:
    """Verify summary_content and export_path fields on ExecutionLog."""

    def test_summary_content(self, db_session):
        pe = PipelineExecution(project_config_path="/tmp/p.json", status="executando")
        db_session.add(pe)
        db_session.flush()

        log = ExecutionLog(
            pipeline_id=pe.id,
            level="info",
            message="done",
            summary_content="Pipeline completed with 5/5 commands.",
        )
        db_session.add(log)
        db_session.flush()
        assert log.summary_content == "Pipeline completed with 5/5 commands."

    def test_export_path(self, db_session):
        pe = PipelineExecution(project_config_path="/tmp/p.json", status="executando")
        db_session.add(pe)
        db_session.flush()

        log = ExecutionLog(
            pipeline_id=pe.id,
            level="info",
            message="exported",
            export_path="/tmp/logs/run-42.md",
        )
        db_session.add(log)
        db_session.flush()
        assert log.export_path == "/tmp/logs/run-42.md"

    def test_fields_nullable_by_default(self, db_session):
        pe = PipelineExecution(project_config_path="/tmp/p.json", status="executando")
        db_session.add(pe)
        db_session.flush()

        log = ExecutionLog(pipeline_id=pe.id, level="info", message="basic")
        db_session.add(log)
        db_session.flush()
        assert log.summary_content is None
        assert log.export_path is None


class TestIndexesExist:
    """Verify composite indexes are defined on models."""

    def test_pipeline_status_started_index(self, tmp_db_manager):
        from sqlalchemy import inspect
        inspector = inspect(tmp_db_manager.engine)
        indexes = inspector.get_indexes("pipeline_executions")
        index_names = {idx["name"] for idx in indexes}
        assert "ix_pipeline_executions_status_started" in index_names

    def test_execution_logs_pipeline_timestamp_index(self, tmp_db_manager):
        from sqlalchemy import inspect
        inspector = inspect(tmp_db_manager.engine)
        indexes = inspector.get_indexes("execution_logs")
        index_names = {idx["name"] for idx in indexes}
        assert "ix_execution_logs_pipeline_timestamp" in index_names

    def test_command_executions_pipeline_position_index(self, tmp_db_manager):
        from sqlalchemy import inspect
        inspector = inspect(tmp_db_manager.engine)
        indexes = inspector.get_indexes("command_executions")
        index_names = {idx["name"] for idx in indexes}
        assert "ix_command_executions_pipeline_position" in index_names

    def test_template_commands_template_id_index(self, tmp_db_manager):
        from sqlalchemy import inspect
        inspector = inspect(tmp_db_manager.engine)
        indexes = inspector.get_indexes("template_commands")
        index_names = {idx["name"] for idx in indexes}
        assert "ix_template_commands_template_id" in index_names


class TestSessionIsolation:
    """Verify that each test gets a clean slate via the SAVEPOINT mechanism."""

    def test_first_inserts_record(self, db_session):
        tmpl = Template(name="isolation-test-record")
        db_session.add(tmpl)
        db_session.flush()
        assert tmpl.id is not None

    def test_second_does_not_see_previous_record(self, db_session):
        """The record from the previous test must have been rolled back."""
        from sqlalchemy import select

        result = db_session.execute(
            select(Template).where(Template.name == "isolation-test-record")
        ).scalar_one_or_none()
        # Should be None because the previous test was rolled back
        assert result is None
