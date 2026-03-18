"""Tests for ExecutionHistoryWidget (module-14/TASK-6 — GAP-007)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

from workflow_app.domain import FilterSpec, PipelineStatus
from workflow_app.history.history_manager import HistoryManager, PaginatedResult
from workflow_app.widgets.execution_history_widget import ExecutionHistoryWidget


def _make_pe(id_: int, status: str = "concluido"):
    pe = MagicMock()
    pe.id = id_
    pe.status = status
    pe.created_at = datetime(2026, 3, 11, 10, 0, tzinfo=timezone.utc)
    return pe


def _make_result(items=None, total_count=None, page=1, page_size=20):
    items = items or []
    total = total_count if total_count is not None else len(items)
    total_pages = max(1, -(-total // page_size))  # ceil division
    return PaginatedResult(
        items=items,
        total_count=total,
        page=page,
        page_size=page_size,
        total_pages=total_pages,
    )


def test_empty_state_message(qtbot):
    mgr = MagicMock(spec=HistoryManager)
    mgr.list_executions.return_value = _make_result()
    widget = ExecutionHistoryWidget(mgr)
    qtbot.addWidget(widget)
    assert widget._list.count() == 1
    assert "Nenhuma execução encontrada" in widget._list.item(0).text()


def test_renders_items(qtbot):
    items = [_make_pe(1), _make_pe(2)]
    mgr = MagicMock(spec=HistoryManager)
    mgr.list_executions.return_value = _make_result(items)
    widget = ExecutionHistoryWidget(mgr)
    qtbot.addWidget(widget)
    assert widget._list.count() == 2
    assert "ID=1" in widget._list.item(0).text()
    assert "ID=2" in widget._list.item(1).text()


def test_pagination_buttons_disabled_single_page(qtbot):
    mgr = MagicMock(spec=HistoryManager)
    mgr.list_executions.return_value = _make_result([_make_pe(1)])
    widget = ExecutionHistoryWidget(mgr)
    qtbot.addWidget(widget)
    assert not widget._btn_prev.isEnabled()
    assert not widget._btn_next.isEnabled()


def test_pagination_next_page(qtbot):
    mgr = MagicMock(spec=HistoryManager)
    mgr.list_executions.return_value = _make_result(
        [_make_pe(i) for i in range(20)],
        total_count=40,
        page=1,
    )
    widget = ExecutionHistoryWidget(mgr)
    qtbot.addWidget(widget)
    assert widget._btn_next.isEnabled()

    mgr.list_executions.return_value = _make_result(
        [_make_pe(i) for i in range(20, 40)],
        total_count=40,
        page=2,
    )
    widget._next_page()
    assert widget._current_page == 2


def test_apply_filter_resets_page(qtbot):
    mgr = MagicMock(spec=HistoryManager)
    mgr.list_executions.return_value = _make_result()
    widget = ExecutionHistoryWidget(mgr)
    qtbot.addWidget(widget)

    widget._current_page = 3
    spec = FilterSpec(status=PipelineStatus.CONCLUIDO)
    widget.apply_filter(spec)
    assert widget._current_page == 1
    assert widget._current_filter is spec


def test_execution_selected_signal(qtbot):
    items = [_make_pe(42)]
    mgr = MagicMock(spec=HistoryManager)
    mgr.list_executions.return_value = _make_result(items)
    widget = ExecutionHistoryWidget(mgr)
    qtbot.addWidget(widget)

    received = []
    widget.execution_selected.connect(lambda eid: received.append(eid))
    widget._list.setCurrentRow(0)

    assert len(received) == 1
    assert received[0] == 42


def test_refresh_reloads_current_page(qtbot):
    mgr = MagicMock(spec=HistoryManager)
    mgr.list_executions.return_value = _make_result()
    widget = ExecutionHistoryWidget(mgr)
    qtbot.addWidget(widget)
    initial_calls = mgr.list_executions.call_count

    widget.refresh()
    assert mgr.list_executions.call_count == initial_calls + 1


def test_load_page_error_handling(qtbot):
    mgr = MagicMock(spec=HistoryManager)
    mgr.list_executions.side_effect = RuntimeError("DB error")
    widget = ExecutionHistoryWidget(mgr)
    qtbot.addWidget(widget)
    assert widget._list.count() == 1
    assert "Erro" in widget._list.item(0).text()
