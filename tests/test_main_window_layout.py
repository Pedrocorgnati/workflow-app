"""TASK-1 layout refactor regression tests.

Cobre AC-1.1, AC-1.3, AC-1.4: ToolboxHeader removido, queue-progress-ring
presente em listeners-frame, autocast e schedule-autocast btns expostos na
play bar do CommandQueueWidget.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QApplication, QPushButton

from workflow_app.command_queue.command_queue_widget import (
    CommandQueueWidget,
    ResponsiveButtonFlowLayout,
)
from workflow_app.metrics_bar.metrics_bar import MetricsBar
from workflow_app.signal_bus import signal_bus
from workflow_app.widgets.queue_progress_ring import QueueProgressRing


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def _find_by_testid(parent, testid: str):
    for w in parent.findChildren(QPushButton):
        if w.property("testid") == testid:
            return w
    return None


def _find_widget_by_testid(parent, testid: str):
    from PySide6.QtWidgets import QWidget

    for w in [parent, *parent.findChildren(QWidget)]:
        if w.property("testid") == testid:
            return w
    return None


def test_main_window_no_toolbox_header_attr(app):
    """AC-1.1: MainWindow nao deve mais ter _toolbox_header."""
    from workflow_app.main_window import MainWindow
    win = MainWindow()
    assert not hasattr(win, "_toolbox_header"), "ToolboxHeader nao foi removido"


def test_metrics_bar_has_queue_progress_ring(app):
    """Refactor 2026-05-17 power-bi-section: o ring continua owned por
    MetricsBar (signal pipelines preservados), mas nao e mais filho do
    listeners-frame — virou IRMAO dentro do power-bi-section montado em
    MainWindow._build_output_toolbar. Aqui (sem MainWindow), o ring fica
    sem parent ate ser reparenteado pelo PowerBiSection.
    """
    mb = MetricsBar()
    assert hasattr(mb, "_queue_progress_ring")
    assert isinstance(mb._queue_progress_ring, QueueProgressRing)
    assert mb._queue_progress_ring.parent() is None


def test_command_queue_has_autocast_buttons(app):
    """AC-1.4: autocast e schedule-autocast vivem agora na play bar."""
    cq = CommandQueueWidget()
    assert _find_by_testid(cq, "autocast-btn") is not None
    assert _find_by_testid(cq, "schedule-autocast-btn") is not None


def test_output_toolbar_left_splits_insertions_controls(app):
    """output-toolbar-left separa abas primarias do bloco Insercoes/rotas/gear."""
    cq = CommandQueueWidget()
    header = cq.header_widget

    primary = _find_widget_by_testid(header, "output-toolbar-left-primary-tabs")
    insertions = _find_widget_by_testid(header, "output-toolbar-left-insertions-controls")
    assert primary is not None
    assert insertions is not None

    insertions_tab = _find_widget_by_testid(header, "queue-tab-terminal-insertions")
    assert insertions_tab is not None
    assert insertions_tab.parentWidget() is insertions

    for testid in (
        "queue-tab-pipelines",
        "queue-tab-workflow",
        "queue-tab-auxiliar",
        "queue-tab-daily-routine",
    ):
        tab = _find_widget_by_testid(header, testid)
        assert tab is not None
        assert tab.parentWidget() is primary


def test_output_toolbar_left_subtabs_use_responsive_flow(app):
    """Subtabs internas quebram linha e compactam sem renderizar mais de 4 linhas."""
    from PySide6.QtWidgets import QWidget

    cq = CommandQueueWidget()
    assert isinstance(cq._subtab_paths_layout, ResponsiveButtonFlowLayout)
    assert isinstance(cq._subtab_prompts_layout, ResponsiveButtonFlowLayout)
    assert isinstance(cq._subtab_rules_layout, ResponsiveButtonFlowLayout)

    path_buttons = [QPushButton("path-a"), QPushButton("path-b")]
    second_row_buttons = [QPushButton("repo rules")]
    cq.populate_paths_subtab(path_buttons, second_row_buttons)
    assert cq._subtab_paths_layout.count() == 3

    parent = QWidget()
    layout = ResponsiveButtonFlowLayout(parent, spacing=4, max_lines=4)
    for i in range(18):
        btn = QPushButton(f"btn-{i}")
        btn.setFixedHeight(28)
        btn.setMinimumWidth(64)
        layout.addWidget(btn)

    layout.setGeometry(QRect(0, 0, 180, 200))
    y_positions = {
        layout.itemAt(i).widget().geometry().y()
        for i in range(layout.count())
    }
    widths = [
        layout.itemAt(i).widget().geometry().width()
        for i in range(layout.count())
    ]
    max_right = max(
        layout.itemAt(i).widget().geometry().right()
        for i in range(layout.count())
    )

    assert len(y_positions) <= 4
    assert min(widths) < 64
    assert max_right < 180


def test_autocast_toggle_signal_proxied(app):
    """AC-1.4: clicar autocast na play bar emite autocast_toggle_requested."""
    cq = CommandQueueWidget()
    received: list[bool] = []
    signal_bus.autocast_toggle_requested.connect(received.append)
    btn = _find_by_testid(cq, "autocast-btn")
    btn.setChecked(True)
    btn.setChecked(False)
    assert received[-2:] == [True, False]


def test_schedule_autocast_signal_proxied(app):
    """AC-1.4: clicar agendar emite schedule_autocast_requested."""
    cq = CommandQueueWidget()
    received: list[int] = []
    signal_bus.schedule_autocast_requested.connect(lambda: received.append(1))
    btn = _find_by_testid(cq, "schedule-autocast-btn")
    btn.click()
    assert received[-1] == 1
