"""TASK-1 layout refactor regression tests.

Cobre AC-1.1, AC-1.3, AC-1.4: ToolboxHeader removido, queue-progress-ring
presente em listeners-frame, autocast e schedule-autocast btns expostos na
play bar do CommandQueueWidget.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QApplication, QPushButton

from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
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
