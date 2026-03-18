"""Tests for DatabaseManager (module-02/TASK-7)."""

from __future__ import annotations

import pytest


class TestDatabaseManagerSetup:
    def test_setup_creates_tables(self, tmp_db_manager):
        """After setup(), get_session() must work and tables must exist."""
        from workflow_app.db.models import Template

        with tmp_db_manager.get_session() as session:
            # Should not raise — factory templates are seeded automatically
            result = session.query(Template).all()
            assert len(result) == 9  # 9 factory templates seeded

    def test_setup_idempotent(self, tmp_path):
        """Calling setup() twice must not raise."""
        from workflow_app.db.database_manager import DatabaseManager

        db_path = str(tmp_path / "idem.db")
        mgr = DatabaseManager()
        mgr.setup(db_path=db_path)
        mgr.setup(db_path=db_path)  # second call
        mgr.close()

    def test_wal_mode(self, tmp_db_manager):
        """WAL mode must be enabled for on-disk databases."""
        assert tmp_db_manager.verify_wal_mode() is True


class TestDatabaseManagerSession:
    def test_context_manager_commits(self, tmp_db_manager):
        """Changes inside get_session() are committed on exit."""
        from workflow_app.db.models import AppConfig

        with tmp_db_manager.get_session() as session:
            session.add(AppConfig(key="foo", value="bar"))

        # Open a fresh session and verify persistence
        with tmp_db_manager.get_session() as session:
            from sqlalchemy import select

            cfg = session.execute(
                select(AppConfig).where(AppConfig.key == "foo")
            ).scalar_one_or_none()
            assert cfg is not None
            assert cfg.value == "bar"

    def test_context_manager_rollback_on_error(self, tmp_db_manager):
        """Exceptions inside get_session() trigger a rollback."""
        from sqlalchemy import select

        from workflow_app.db.models import AppConfig

        with pytest.raises(ValueError, match="intentional"):
            with tmp_db_manager.get_session() as session:
                session.add(AppConfig(key="rollback-key", value="v"))
                raise ValueError("intentional")

        # Record must NOT be persisted
        with tmp_db_manager.get_session() as session:
            cfg = session.execute(
                select(AppConfig).where(AppConfig.key == "rollback-key")
            ).scalar_one_or_none()
            assert cfg is None

    def test_multiple_independent_sessions(self, tmp_db_manager):
        """Multiple sessions opened sequentially must each see committed data."""
        from sqlalchemy import select

        from workflow_app.db.models import AppConfig

        with tmp_db_manager.get_session() as s1:
            s1.add(AppConfig(key="shared-key", value="hello"))

        with tmp_db_manager.get_session() as s2:
            cfg = s2.execute(
                select(AppConfig).where(AppConfig.key == "shared-key")
            ).scalar_one_or_none()
            assert cfg is not None


class TestDatabaseManagerClose:
    def test_close_is_idempotent(self, tmp_path):
        from workflow_app.db.database_manager import DatabaseManager

        mgr = DatabaseManager()
        mgr.setup(db_path=str(tmp_path / "close.db"))
        mgr.close()
        mgr.close()  # second call must not raise
