"""
SQLAlchemy models for Workflow App (module-02/TASK-2).

Entities:
  - Template: pipeline templates with commands
  - TemplateCommand: individual commands within a template
  - PipelineExecution: record of a pipeline run
  - CommandExecution: record of a single command run
  - AppConfig: key-value configuration store
  - ExecutionLog: structured log entries for pipeline runs
"""

from __future__ import annotations

import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy models."""
    pass


class Template(Base):
    """Pipeline template — a named collection of commands."""

    __tablename__ = "templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    template_type: Mapped[str] = mapped_column(String(50), nullable=False, default="custom")
    is_factory: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    # Relationships
    commands: Mapped[list[TemplateCommand]] = relationship(
        "TemplateCommand",
        back_populates="template",
        cascade="all, delete-orphan",
        order_by="TemplateCommand.position",
    )
    executions: Mapped[list[PipelineExecution]] = relationship(
        "PipelineExecution", back_populates="template"
    )

    def __repr__(self) -> str:
        return f"<Template id={self.id} name={self.name!r} type={self.template_type}>"


class TemplateCommand(Base):
    """A single command entry within a Template."""

    __tablename__ = "template_commands"
    __table_args__ = (
        UniqueConstraint("template_id", "position", name="uq_template_position"),
        Index("ix_template_commands_template_id", "template_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("templates.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    command_name: Mapped[str] = mapped_column(String(255), nullable=False)
    model_type: Mapped[str] = mapped_column(String(50), nullable=False, default="sonnet")
    interaction_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="sem_interacao"
    )
    estimated_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_optional: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    # Relationships
    template: Mapped[Template] = relationship("Template", back_populates="commands")

    def __repr__(self) -> str:
        return (
            f"<TemplateCommand id={self.id} template_id={self.template_id}"
            f" pos={self.position} cmd={self.command_name!r}>"
        )


class PipelineExecution(Base):
    """Record of a complete pipeline run."""

    __tablename__ = "pipeline_executions"
    __table_args__ = (
        Index("ix_pipeline_executions_status_started", "status", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("templates.id", ondelete="SET NULL"), nullable=True
    )
    project_config_path: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="criado")
    permission_mode: Mapped[str] = mapped_column(
        String(50), nullable=False, default="acceptEdits"
    )
    commands_total: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    commands_completed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    commands_failed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    commands_skipped: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_input: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_output: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    started_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    # Relationships
    template: Mapped[Template | None] = relationship(
        "Template", back_populates="executions"
    )
    commands: Mapped[list[CommandExecution]] = relationship(
        "CommandExecution",
        back_populates="pipeline",
        cascade="all, delete-orphan",
        order_by="CommandExecution.position",
    )
    logs: Mapped[list[ExecutionLog]] = relationship(
        "ExecutionLog",
        back_populates="pipeline",
        cascade="all, delete-orphan",
        order_by="ExecutionLog.created_at",
    )

    def __repr__(self) -> str:
        return (
            f"<PipelineExecution id={self.id} status={self.status!r}"
            f" total={self.commands_total}>"
        )


class CommandExecution(Base):
    """Record of a single command execution within a pipeline."""

    __tablename__ = "command_executions"
    __table_args__ = (
        Index("ix_command_executions_pipeline_position", "pipeline_id", "position"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pipeline_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("pipeline_executions.id", ondelete="CASCADE"), nullable=False
    )
    position: Mapped[int] = mapped_column(Integer, nullable=False)
    command_name: Mapped[str] = mapped_column(String(255), nullable=False)
    model: Mapped[str] = mapped_column(String(50), nullable=False, default="sonnet")
    interaction_type: Mapped[str] = mapped_column(
        String(50), nullable=False, default="sem_interacao"
    )
    status: Mapped[str] = mapped_column(String(50), nullable=False, default="pendente")
    is_optional: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    output_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    tokens_input: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokens_output: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    elapsed_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    started_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    # Relationships
    pipeline: Mapped[PipelineExecution] = relationship(
        "PipelineExecution", back_populates="commands"
    )
    logs: Mapped[list[ExecutionLog]] = relationship(
        "ExecutionLog", back_populates="command"
    )

    def __repr__(self) -> str:
        return (
            f"<CommandExecution id={self.id} pipeline_id={self.pipeline_id}"
            f" pos={self.position} cmd={self.command_name!r} status={self.status!r}>"
        )


class AppConfig(Base):
    """Key-value store for application configuration and user preferences."""

    __tablename__ = "app_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )

    def __repr__(self) -> str:
        return f"<AppConfig key={self.key!r} value={self.value!r}>"


class ExecutionLog(Base):
    """Structured log entry associated with a pipeline execution."""

    __tablename__ = "execution_logs"
    __table_args__ = (
        Index("ix_execution_logs_pipeline_timestamp", "pipeline_id", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    pipeline_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("pipeline_executions.id", ondelete="CASCADE"), nullable=False
    )
    command_execution_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("command_executions.id", ondelete="SET NULL"),
        nullable=True,
    )
    level: Mapped[str] = mapped_column(String(20), nullable=False, default="info")
    message: Mapped[str] = mapped_column(Text, nullable=False)
    summary_content: Mapped[str | None] = mapped_column(Text, nullable=True)
    export_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime.datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )

    # Relationships
    pipeline: Mapped[PipelineExecution] = relationship(
        "PipelineExecution", back_populates="logs"
    )
    command: Mapped[CommandExecution | None] = relationship(
        "CommandExecution", back_populates="logs"
    )

    def __repr__(self) -> str:
        return (
            f"<ExecutionLog id={self.id} pipeline_id={self.pipeline_id}"
            f" level={self.level!r} msg={self.message[:40]!r}>"
        )
