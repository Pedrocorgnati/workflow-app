"""Pytest configuration for Workflow App tests."""

from __future__ import annotations

import sys

import pytest


@pytest.fixture(scope="session")
def qapp():
    """Session-scoped QApplication for PySide6 tests."""
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication(sys.argv)
    yield app
