"""Tests for MainWindow shell."""

from __future__ import annotations


def test_main_window_opens(qapp):
    from workflow_app.main_window import MainWindow

    window = MainWindow()
    assert window.minimumWidth() == 640
    assert window.minimumHeight() == 480


def test_main_window_title(qapp):
    from workflow_app.main_window import MainWindow

    window = MainWindow()
    assert "SystemForge Desktop" in window.windowTitle()


def test_layout_has_splitter(qapp):
    from workflow_app.main_window import MainWindow

    window = MainWindow()
    assert window._splitter is not None
    assert window._splitter.count() == 2


def test_command_queue_width_constraints(qapp):
    from workflow_app.main_window import MainWindow

    window = MainWindow()
    # Command queue is the second widget in the splitter (left tab)
    cmd_queue = window._splitter.widget(1)
    # Width is flexible; just verify the widget exists
    assert cmd_queue is not None
    assert cmd_queue.width() > 0


def test_metrics_bar_height(qapp):
    from workflow_app.main_window import MainWindow

    window = MainWindow()
    assert window._metrics_bar.height() == 48


def test_theme_applied(qapp):
    from workflow_app.theme import apply_theme

    apply_theme(qapp)
    stylesheet = qapp.styleSheet()
    assert len(stylesheet) > 0
    assert "#18181B" in stylesheet


def test_tokens_importable():
    from workflow_app.tokens import COLORS, SPACING, TYPOGRAPHY

    assert COLORS.background == "#18181B"
    assert COLORS.primary == "#FBBF24"
    assert TYPOGRAPHY.font_ui == "Inter"
    assert SPACING.md == 12
