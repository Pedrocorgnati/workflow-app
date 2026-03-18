"""initial schema

Revision ID: 0001
Revises: None
Create Date: 2026-03-11 00:00:00.000000

Creates all tables for the Workflow App initial schema:
  - templates
  - template_commands
  - pipeline_executions
  - command_executions
  - execution_logs
  - app_configs
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers
revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── templates ────────────────────────────────────────────────────────── #
    op.create_table(
        "templates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("template_type", sa.String(50), nullable=False, server_default="custom"),
        sa.Column("is_factory", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # ── template_commands ────────────────────────────────────────────────── #
    op.create_table(
        "template_commands",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("command_name", sa.String(255), nullable=False),
        sa.Column("model_type", sa.String(50), nullable=False, server_default="sonnet"),
        sa.Column(
            "interaction_type",
            sa.String(50),
            nullable=False,
            server_default="sem_interacao",
        ),
        sa.Column("estimated_seconds", sa.Integer(), nullable=True),
        sa.Column(
            "is_optional", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.ForeignKeyConstraint(
            ["template_id"], ["templates.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("template_id", "position", name="uq_template_position"),
    )
    op.create_index(
        "ix_template_commands_template_id", "template_commands", ["template_id"]
    )

    # ── pipeline_executions ──────────────────────────────────────────────── #
    op.create_table(
        "pipeline_executions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("template_id", sa.Integer(), nullable=True),
        sa.Column("project_config_path", sa.String(512), nullable=False),
        sa.Column("status", sa.String(50), nullable=False, server_default="criado"),
        sa.Column(
            "permission_mode",
            sa.String(50),
            nullable=False,
            server_default="acceptEdits",
        ),
        sa.Column("commands_total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "commands_completed", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("commands_failed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "commands_skipped", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("tokens_input", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_output", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cost_usd", sa.Float(), nullable=False, server_default="0.0"),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["template_id"], ["templates.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_pipeline_executions_status_started",
        "pipeline_executions",
        ["status", "started_at"],
    )

    # ── command_executions ───────────────────────────────────────────────── #
    op.create_table(
        "command_executions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("pipeline_id", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("command_name", sa.String(255), nullable=False),
        sa.Column("model", sa.String(50), nullable=False, server_default="sonnet"),
        sa.Column(
            "interaction_type",
            sa.String(50),
            nullable=False,
            server_default="sem_interacao",
        ),
        sa.Column("status", sa.String(50), nullable=False, server_default="pendente"),
        sa.Column(
            "is_optional", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("output_text", sa.Text(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("tokens_input", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_output", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("elapsed_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["pipeline_id"], ["pipeline_executions.id"], ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_command_executions_pipeline_position",
        "command_executions",
        ["pipeline_id", "position"],
    )

    # ── execution_logs ───────────────────────────────────────────────────── #
    op.create_table(
        "execution_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("pipeline_id", sa.Integer(), nullable=False),
        sa.Column("command_execution_id", sa.Integer(), nullable=True),
        sa.Column("level", sa.String(20), nullable=False, server_default="info"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("summary_content", sa.Text(), nullable=True),
        sa.Column("export_path", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["pipeline_id"], ["pipeline_executions.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["command_execution_id"],
            ["command_executions.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_execution_logs_pipeline_timestamp",
        "execution_logs",
        ["pipeline_id", "created_at"],
    )

    # ── app_configs ──────────────────────────────────────────────────────── #
    op.create_table(
        "app_configs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("key", sa.String(255), nullable=False),
        sa.Column("value", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("app_configs")
    op.drop_index("ix_execution_logs_pipeline_timestamp", table_name="execution_logs")
    op.drop_table("execution_logs")
    op.drop_index(
        "ix_command_executions_pipeline_position", table_name="command_executions"
    )
    op.drop_table("command_executions")
    op.drop_index(
        "ix_pipeline_executions_status_started", table_name="pipeline_executions"
    )
    op.drop_table("pipeline_executions")
    op.drop_index(
        "ix_template_commands_template_id", table_name="template_commands"
    )
    op.drop_table("template_commands")
    op.drop_table("templates")
