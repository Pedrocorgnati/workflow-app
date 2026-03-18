"""Tests for ExecutionDetailPanel (module-14/TASK-3)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from workflow_app.history.history_manager import HistoryManager
from workflow_app.widgets.execution_detail_panel import ExecutionDetailPanel


def test_load_execution_not_found(qtbot):
    mgr = MagicMock(spec=HistoryManager)
    mgr.get_execution_detail.return_value = None
    panel = ExecutionDetailPanel(mgr)
    qtbot.addWidget(panel)
    panel.load_execution(999)
    assert "não encontrada" in panel._header_label.text()


def test_load_execution_updates_header(qtbot):
    pe = MagicMock()
    pe.id = 1
    pe.created_at = datetime(2026, 3, 11, 10, 0, tzinfo=timezone.utc)
    pe.status = "concluido"
    pe.commands = []

    mgr = MagicMock(spec=HistoryManager)
    mgr.get_execution_detail.return_value = pe
    panel = ExecutionDetailPanel(mgr)
    qtbot.addWidget(panel)
    panel.load_execution(1)
    assert "CONCLUIDO" in panel._header_label.text()
    assert "ID 1" in panel._header_label.text()


def test_load_execution_shows_commands(qtbot):
    cmd = MagicMock()
    cmd.position = 0
    cmd.command_name = "/test-cmd"
    cmd.status = "concluido"
    cmd.model = "sonnet"
    cmd.elapsed_seconds = 5

    pe = MagicMock()
    pe.id = 2
    pe.created_at = datetime(2026, 3, 11, 10, 0, tzinfo=timezone.utc)
    pe.status = "concluido"
    pe.commands = [cmd]

    mgr = MagicMock(spec=HistoryManager)
    mgr.get_execution_detail.return_value = pe
    panel = ExecutionDetailPanel(mgr)
    qtbot.addWidget(panel)
    panel.load_execution(2)
    assert panel._commands_list.count() == 1
    assert "/test-cmd" in panel._commands_list.item(0).text()


def test_initial_state_no_exec_id(qtbot):
    mgr = MagicMock(spec=HistoryManager)
    panel = ExecutionDetailPanel(mgr)
    qtbot.addWidget(panel)
    assert panel._current_exec_id is None
    assert "Selecione" in panel._header_label.text()


def test_export_markdown_calls_manager(qtbot, monkeypatch):
    """GAP-008: Export flow calls mgr.export_execution_markdown."""
    mgr = MagicMock(spec=HistoryManager)
    mgr.export_execution_markdown.return_value = "# Report"
    panel = ExecutionDetailPanel(mgr)
    qtbot.addWidget(panel)
    panel._current_exec_id = 5

    # Mock QFileDialog to return a temp path
    import tempfile
    from pathlib import Path

    tmp = Path(tempfile.mktemp(suffix=".md"))
    from PySide6.QtWidgets import QFileDialog

    monkeypatch.setattr(
        QFileDialog, "getSaveFileName", staticmethod(lambda *a, **kw: (str(tmp), ""))
    )
    panel._export_markdown()
    mgr.export_execution_markdown.assert_called_once_with(5)
    assert tmp.exists()
    assert tmp.read_text() == "# Report"
    tmp.unlink()


def test_color_coding_erro_red(qtbot):
    """GAP-009: Commands with ERRO status get red foreground."""
    from PySide6.QtCore import Qt

    from workflow_app.domain import CommandStatus

    cmd = MagicMock()
    cmd.position = 0
    cmd.command_name = "/fail-cmd"
    cmd.status = CommandStatus.ERRO.value
    cmd.model = None
    cmd.elapsed_seconds = None

    pe = MagicMock()
    pe.id = 10
    pe.created_at = datetime(2026, 3, 11, 10, 0, tzinfo=timezone.utc)
    pe.status = "erro"
    pe.commands = [cmd]

    mgr = MagicMock(spec=HistoryManager)
    mgr.get_execution_detail.return_value = pe
    panel = ExecutionDetailPanel(mgr)
    qtbot.addWidget(panel)
    panel.load_execution(10)

    item = panel._commands_list.item(0)
    assert item.foreground().color() == Qt.GlobalColor.red


def test_color_coding_concluido_green(qtbot):
    """GAP-009: Commands with CONCLUIDO status get green foreground."""
    from PySide6.QtCore import Qt

    from workflow_app.domain import CommandStatus

    cmd = MagicMock()
    cmd.position = 0
    cmd.command_name = "/ok-cmd"
    cmd.status = CommandStatus.CONCLUIDO.value
    cmd.model = None
    cmd.elapsed_seconds = None

    pe = MagicMock()
    pe.id = 11
    pe.created_at = datetime(2026, 3, 11, 10, 0, tzinfo=timezone.utc)
    pe.status = "concluido"
    pe.commands = [cmd]

    mgr = MagicMock(spec=HistoryManager)
    mgr.get_execution_detail.return_value = pe
    panel = ExecutionDetailPanel(mgr)
    qtbot.addWidget(panel)
    panel.load_execution(11)

    item = panel._commands_list.item(0)
    assert item.foreground().color() == Qt.GlobalColor.green


def test_load_execution_error_handling(qtbot):
    """GAP-003: DB error in load_execution shows error in header."""
    mgr = MagicMock(spec=HistoryManager)
    mgr.get_execution_detail.side_effect = RuntimeError("DB crash")
    panel = ExecutionDetailPanel(mgr)
    qtbot.addWidget(panel)
    panel.load_execution(99)
    assert "Erro ao carregar execução" in panel._header_label.text()
