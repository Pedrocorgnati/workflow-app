"""Tests for MainWindow shell."""

from __future__ import annotations


def test_main_window_opens(qapp):
    from workflow_app.main_window import MainWindow

    window = MainWindow()
    assert window.minimumWidth() == 1024
    assert window.minimumHeight() == 600


def test_main_window_title(qapp):
    from workflow_app.main_window import MainWindow

    window = MainWindow()
    assert "Workflow App" in window.windowTitle()


def test_layout_has_splitter(qapp):
    from workflow_app.main_window import MainWindow

    window = MainWindow()
    assert window._splitter is not None
    assert window._splitter.count() == 2


def test_command_queue_width_constraints(qapp):
    from workflow_app.main_window import MainWindow

    window = MainWindow()
    # Command queue is the second widget in the splitter
    cmd_queue = window._splitter.widget(1)
    # setFixedWidth(280) locks width to 280
    assert cmd_queue.width() == 280


def test_metrics_bar_height(qapp):
    from workflow_app.main_window import MainWindow

    window = MainWindow()
    assert window._metrics_bar.height() == 48
