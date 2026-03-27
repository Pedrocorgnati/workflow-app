"""
Tests for OutputPanel public API — pyte/PersistentShell architecture.

Covers:
  - append_output adds text to the terminal widget
  - clear() resets the terminal display
  - set_max_lines updates _max_lines
  - set_interactive_mode is a no-op (input handled via terminal keyboard)
  - set_current_worker stores the runner reference
  - _on_pipeline_started / _on_pipeline_completed do not crash
"""
from __future__ import annotations

import pytest

from workflow_app.output_panel.output_panel import (
    DEFAULT_MAX_LINES,
    OutputPanel,
)


@pytest.fixture()
def panel(qapp, qtbot):
    p = OutputPanel()
    qtbot.addWidget(p)
    p.show()
    return p


class TestOutputPanelInitialState:
    def test_terminal_widget_exists(self, panel):
        """OutputPanel creates _terminal widget on init."""
        assert panel._terminal is not None

    def test_default_max_lines(self, panel):
        """_max_lines defaults to DEFAULT_MAX_LINES."""
        assert panel._max_lines == DEFAULT_MAX_LINES

    def test_pipeline_runner_none_on_init(self, panel):
        """_pipeline_runner is None before any worker is set."""
        assert panel._pipeline_runner is None


class TestOutputPanelAppendOutput:
    def test_append_shows_text(self, panel, qtbot):
        """append_output inserts text into the terminal widget."""
        panel.append_output("Hello World\n")
        panel._flush_pyte()
        assert "Hello World" in panel._terminal.toPlainText()

    def test_append_multiple_chunks(self, panel, qtbot):
        """Multiple append_output calls accumulate text."""
        panel.append_output("line-A\n")
        panel.append_output("line-B\n")
        panel._flush_pyte()
        text = panel._terminal.toPlainText()
        assert "line-A" in text
        assert "line-B" in text

    def test_append_does_not_crash_on_empty(self, panel):
        """append_output with empty string does not crash."""
        panel.append_output("")


class TestOutputPanelClear:
    def test_clear_does_not_crash(self, panel):
        """clear() runs without errors."""
        panel.append_output("some text\n")
        panel._flush_pyte()
        panel.clear()

    def test_clear_empties_terminal(self, panel):
        """clear() empties the terminal."""
        panel.append_output("some output\n")
        panel._flush_pyte()
        panel.clear()
        assert panel._terminal.toPlainText() == ""


class TestOutputPanelSetMaxLines:
    def test_set_max_lines_updates_attribute(self, panel):
        """set_max_lines() updates _max_lines."""
        panel.set_max_lines(500)
        assert panel._max_lines == 500


class TestOutputPanelInteractiveMode:
    def test_set_interactive_mode_true_no_crash(self, panel):
        """set_interactive_mode(True) is a no-op and does not crash."""
        panel.set_interactive_mode(True)

    def test_set_interactive_mode_false_no_crash(self, panel):
        """set_interactive_mode(False) is a no-op and does not crash."""
        panel.set_interactive_mode(False)

    def test_set_interactive_mode_cycle_no_crash(self, panel):
        """Toggling interactive mode on/off/on does not crash."""
        panel.set_interactive_mode(True)
        panel.set_interactive_mode(False)
        panel.set_interactive_mode(True)


class TestOutputPanelWorker:
    def test_set_current_worker_stores_reference(self, panel):
        """set_current_worker() stores the worker in _pipeline_runner."""
        mock_worker = object()
        panel.set_current_worker(mock_worker)
        assert panel._pipeline_runner is mock_worker

    def test_set_current_worker_none_clears_reference(self, panel):
        """set_current_worker(None) clears the runner reference."""
        panel.set_current_worker(object())
        panel.set_current_worker(None)
        assert panel._pipeline_runner is None


class TestOutputPanelSignalIntegration:
    def test_on_pipeline_started_no_crash(self, panel):
        """_on_pipeline_started() does not crash."""
        panel._on_pipeline_started()

    def test_on_pipeline_completed_no_crash(self, panel):
        """_on_pipeline_completed() does not crash."""
        panel._on_pipeline_completed()

    def test_on_pipeline_error_no_crash(self, panel):
        """_on_pipeline_error() does not crash."""
        panel._on_pipeline_error(1, "something went wrong")
