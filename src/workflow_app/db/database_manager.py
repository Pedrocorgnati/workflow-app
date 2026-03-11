"""
DatabaseManager — SQLite WAL mode database manager (module-02/TASK-3).

TODO: Implement backend — module-02/TASK-3 (auto-flow execute)
"""

from __future__ import annotations


class DatabaseManager:
    """
    Manages SQLite connection with WAL mode and SQLAlchemy session factory.

    TODO: Implement backend — module-02/TASK-3 (auto-flow execute)
    """

    def __init__(self, db_path: str | None = None) -> None:
        # TODO: Implement backend
        raise NotImplementedError("module-02/TASK-3 not yet implemented — run /auto-flow execute")

    def get_session(self):
        # TODO: return sessionmaker instance
        raise NotImplementedError("module-02/TASK-3 not yet implemented — run /auto-flow execute")

    def close(self) -> None:
        # TODO: Implement backend
        raise NotImplementedError("module-02/TASK-3 not yet implemented — run /auto-flow execute")
