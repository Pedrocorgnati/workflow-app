"""Pytest configuration for Workflow App tests."""

from __future__ import annotations

import sys

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from workflow_app.db.database_manager import DatabaseManager
from workflow_app.db.models import Base

# ── Qt ────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def qapp():
    """Session-scoped QApplication for PySide6 tests."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app


# ── Database ──────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def db_engine():
    """Session-scoped in-memory SQLite engine shared across all DB tests."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )

    # Enable foreign keys in SQLite
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db_session(db_engine):
    """Function-scoped database session with automatic rollback via SAVEPOINT.

    Uses nested transactions so each test runs in isolation without
    recreating the schema.
    """
    connection = db_engine.connect()
    # Begin outer transaction
    transaction = connection.begin()
    # Create a SAVEPOINT for nested transaction
    nested = connection.begin_nested()

    Session = sessionmaker(bind=connection, expire_on_commit=False)
    session = Session()

    # Restart the nested transaction if it ends (e.g. after flush)
    @event.listens_for(session, "after_transaction_end")
    def restart_savepoint(sess, trans):
        nonlocal nested
        if not trans.nested and trans is not nested:
            return
        nested = connection.begin_nested()

    yield session

    session.close()
    # Roll back to the savepoint, then roll back the outer transaction
    transaction.rollback()
    connection.close()


@pytest.fixture
def tmp_db_manager(tmp_path):
    """Function-scoped DatabaseManager using a temporary on-disk SQLite file."""
    db_path = tmp_path / "test_workflow.db"
    manager = DatabaseManager()
    manager.setup(db_path=str(db_path))
    yield manager
    manager.close()
