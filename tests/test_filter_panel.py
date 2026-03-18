"""Tests for FilterPanel (module-14/TASK-6 — GAP-006)."""

from __future__ import annotations

from PySide6.QtCore import QDate

from workflow_app.domain import FilterSpec, PipelineStatus
from workflow_app.widgets.filter_panel import FilterPanel


def test_initial_status_is_todos(qtbot):
    panel = FilterPanel()
    qtbot.addWidget(panel)
    assert panel._status_combo.currentText() == "Todos"
    assert panel._status_combo.currentData() is None


def test_emit_filter_with_status(qtbot):
    panel = FilterPanel()
    qtbot.addWidget(panel)

    # Select a specific status
    for i in range(panel._status_combo.count()):
        if panel._status_combo.itemData(i) == PipelineStatus.CONCLUIDO:
            panel._status_combo.setCurrentIndex(i)
            break

    received = []
    panel.filter_changed.connect(lambda spec: received.append(spec))
    panel._emit_filter()

    assert len(received) == 1
    assert received[0].status == PipelineStatus.CONCLUIDO


def test_emit_filter_todos_status(qtbot):
    panel = FilterPanel()
    qtbot.addWidget(panel)
    panel._status_combo.setCurrentIndex(0)

    received = []
    panel.filter_changed.connect(lambda spec: received.append(spec))
    panel._emit_filter()

    assert len(received) == 1
    assert received[0].status is None


def test_emit_filter_includes_dates(qtbot):
    panel = FilterPanel()
    qtbot.addWidget(panel)
    panel._date_from.setDate(QDate(2026, 1, 1))
    panel._date_to.setDate(QDate(2026, 3, 11))

    received = []
    panel.filter_changed.connect(lambda spec: received.append(spec))
    panel._emit_filter()

    assert received[0].date_from == "2026-01-01"
    assert received[0].date_to == "2026-03-11"


def test_clear_resets_combo_and_emits(qtbot):
    panel = FilterPanel()
    qtbot.addWidget(panel)

    # Change status to something other than Todos
    panel._status_combo.setCurrentIndex(1)

    received = []
    panel.filter_changed.connect(lambda spec: received.append(spec))
    panel._clear_filters()

    assert panel._status_combo.currentIndex() == 0
    assert len(received) == 1
    assert received[0].status is None


def test_filter_spec_construction(qtbot):
    panel = FilterPanel()
    qtbot.addWidget(panel)

    received = []
    panel.filter_changed.connect(lambda spec: received.append(spec))
    panel._emit_filter()

    spec = received[0]
    assert isinstance(spec, FilterSpec)
    assert spec.date_from is not None
    assert spec.date_to is not None
