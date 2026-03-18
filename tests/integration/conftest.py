"""Configuração específica para testes de integração."""
from __future__ import annotations

from contextlib import contextmanager
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from workflow_app.db.models import Base


@pytest.fixture(scope="session")
def integration_db_path(tmp_path_factory):
    """Banco SQLite dedicado para testes de integração."""
    return str(tmp_path_factory.mktemp("integration_db") / "integration.db")


# ── Shared engine / session factory ───────────────────────────────────────────


@pytest.fixture(scope="module")
def int_engine(tmp_path_factory):
    """Engine SQLite em arquivo temporário (módulo-scoped)."""
    tmp = tmp_path_factory.mktemp("int")
    engine = create_engine(
        f"sqlite:///{tmp}/integration.db",
        connect_args={"check_same_thread": False},
    )

    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_conn, _):
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture(scope="module")
def int_session_factory(int_engine):
    """sessionmaker compatível com SQLAlchemy 2.x (context manager)."""
    return sessionmaker(bind=int_engine, expire_on_commit=False)


@pytest.fixture(scope="module")
def int_db_manager(int_session_factory):
    """Mock de DatabaseManager que delega get_session() a uma sessionmaker real."""
    mgr = MagicMock()

    @contextmanager
    def _get_session():
        session = int_session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    mgr.get_session = _get_session
    return mgr
