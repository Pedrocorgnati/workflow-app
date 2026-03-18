"""
DatabaseManager — SQLite WAL mode database manager (module-02/TASK-3).

Manages the lifecycle of the SQLite database with WAL mode enabled,
exposes a thread-safe SessionFactory and provides a get_session()
context manager for use throughout the application.

Default DB path: ~/.workflow-app/workflow.db
Override: set DB_PATH environment variable.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Generator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from workflow_app.db.models import Base

logger = logging.getLogger(__name__)

_DEFAULT_DB_DIR = Path.home() / ".workflow-app"
_DEFAULT_DB_NAME = "workflow.db"


class DatabaseManager:
    """Manages the lifecycle of the SQLite database with WAL mode.

    Typical usage (main.py):
        db = DatabaseManager()
        db.setup()

    Usage in services/workers (thread-safe):
        with db.get_session() as session:
            session.add(obj)
    """

    def __init__(self) -> None:
        self._engine: Engine | None = None
        self._session_factory: sessionmaker | None = None

    @property
    def engine(self) -> Engine:
        if self._engine is None:
            raise RuntimeError(
                "DatabaseManager not initialized. Call setup() first."
            )
        return self._engine

    @property
    def session_factory(self) -> sessionmaker:
        if self._session_factory is None:
            raise RuntimeError(
                "DatabaseManager not initialized. Call setup() first."
            )
        return self._session_factory

    def setup(self, db_path: str | None = None) -> None:
        """Initialize the engine, enable WAL mode and create tables.

        Args:
            db_path: Absolute path to the .db file. If None, uses
                     DB_PATH env var or ~/.workflow-app/workflow.db.
        """
        resolved_path = self._resolve_db_path(db_path)
        logger.info("Initializing database at: %s", resolved_path)

        # Ensure the directory exists
        resolved_path.parent.mkdir(parents=True, exist_ok=True)

        url = f"sqlite:///{resolved_path}"
        self._engine = create_engine(
            url,
            echo=False,
            connect_args={"check_same_thread": False},
        )

        # Enable WAL mode and NORMAL synchronous via connection event
        @event.listens_for(self._engine, "connect")
        def set_sqlite_pragma(dbapi_conn, connection_record):  # noqa: ANN001
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

        self._session_factory = sessionmaker(
            bind=self._engine,
            expire_on_commit=False,  # avoid lazy load after commit in threads
        )
        self.create_tables()
        self._seed_initial_data()
        logger.info("Database initialized successfully (WAL mode active).")

    def create_tables(self) -> None:
        """Create all tables registered in Base.metadata (idempotent)."""
        Base.metadata.create_all(self._engine, checkfirst=True)

    def _seed_initial_data(self) -> None:
        """Run idempotent seeds for initial data (factory templates)."""
        from workflow_app.templates.factory_templates import seed_factory_templates

        seed_factory_templates(self, sha256=None)

    @staticmethod
    def _resolve_db_path(db_path: str | None) -> Path:
        if db_path:
            return Path(db_path)
        env_path = os.environ.get("DB_PATH")
        if env_path:
            return Path(env_path)
        return _DEFAULT_DB_DIR / _DEFAULT_DB_NAME

    @contextmanager
    def get_session(self) -> Generator[Session, None, None]:
        """Context manager for sessions with automatic commit/rollback.

        Example:
            with db_manager.get_session() as session:
                session.add(template)
        """
        session: Session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    def verify_wal_mode(self) -> bool:
        """Verify that WAL mode is active (useful for tests)."""
        with self._engine.connect() as conn:
            result = conn.execute(text("PRAGMA journal_mode")).scalar()
            return result == "wal"

    def close(self) -> None:
        """Dispose the engine and clear the session factory."""
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
            self._session_factory = None


# Global instance — initialized in main.py via db_manager.setup()
db_manager = DatabaseManager()
