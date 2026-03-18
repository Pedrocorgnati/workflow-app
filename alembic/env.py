"""
Alembic migration environment — Workflow App.

Connects to the same SQLite database as the application
(respects DB_PATH env var and the ~/.workflow-app/workflow.db default).
"""

from __future__ import annotations

import logging
import os
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

# Import Base so Alembic can detect model changes (autogenerate).
# All models must be imported here for autogenerate to work.
from workflow_app.db.models import Base  # noqa: F401

# ---------------------------------------------------------------------------
# Alembic Config object (provides access to alembic.ini values)
# ---------------------------------------------------------------------------
config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

logger = logging.getLogger("alembic.env")

target_metadata = Base.metadata

# ---------------------------------------------------------------------------
# Resolve DB path (same logic as DatabaseManager)
# ---------------------------------------------------------------------------

_DEFAULT_DB_DIR = Path.home() / ".workflow-app"
_DEFAULT_DB_NAME = "workflow.db"


def _get_db_url() -> str:
    env_path = os.environ.get("DB_PATH")
    if env_path:
        db_path = Path(env_path)
    else:
        db_path = _DEFAULT_DB_DIR / _DEFAULT_DB_NAME
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{db_path}"


# ---------------------------------------------------------------------------
# Offline migration (no live DB connection)
# ---------------------------------------------------------------------------

def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL and not an Engine.
    Calls to context.execute() emit the given string to the script output.
    """
    url = _get_db_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # required for SQLite ALTER TABLE support
    )

    with context.begin_transaction():
        context.run_migrations()


# ---------------------------------------------------------------------------
# Online migration (live DB connection)
# ---------------------------------------------------------------------------

def run_migrations_online() -> None:
    """Run migrations in 'online' mode (connected to the actual DB)."""
    cfg_section = config.get_section(config.config_ini_section) or {}
    cfg_section["sqlalchemy.url"] = _get_db_url()

    connectable = engine_from_config(
        cfg_section,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        # render_as_batch is mandatory for SQLite because it does not support
        # ALTER COLUMN / DROP COLUMN natively. Alembic emulates these via
        # CREATE TABLE + COPY + DROP + RENAME.
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )

        with context.begin_transaction():
            context.run_migrations()


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
