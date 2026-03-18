"""
Tests for interactive input routing — pyte/PersistentShell architecture.

In the new architecture:
  - set_interactive_mode() is a no-op (input handled via terminal keyboard)
  - set_current_worker() stores reference in _pipeline_runner
  - _on_raw_key() routes key bytes to _pipeline_runner when _runner_active,
    else to _shell.send_raw
  - signal_bus integration: current_worker_changed → set_current_worker
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture()
def panel(qapp, qtbot):
    from workflow_app.output_panel.output_panel import OutputPanel
    p = OutputPanel()
    qtbot.addWidget(p)
    p.show()
    return p


class TestSetInteractiveMode:
    def test_enter_mode_no_crash(self, panel):
        """set_interactive_mode(True) is a no-op — must not crash."""
        panel.set_interactive_mode(True)

    def test_exit_mode_no_crash(self, panel):
        """set_interactive_mode(False) is a no-op — must not crash."""
        panel.set_interactive_mode(False)

    def test_cycle_no_crash(self, panel):
        """Toggling on/off/on must not crash."""
        panel.set_interactive_mode(True)
        panel.set_interactive_mode(False)
        panel.set_interactive_mode(True)


class TestSetCurrentWorker:
    def test_stores_worker_in_pipeline_runner(self, panel):
        """set_current_worker stores the worker in _pipeline_runner."""
        worker = MagicMock()
        panel.set_current_worker(worker)
        assert panel._pipeline_runner is worker

    def test_overwrites_previous_worker(self, panel):
        """Calling set_current_worker twice updates the reference."""
        w1, w2 = MagicMock(), MagicMock()
        panel.set_current_worker(w1)
        panel.set_current_worker(w2)
        assert panel._pipeline_runner is w2

    def test_set_none_clears_reference(self, panel):
        """set_current_worker(None) clears _pipeline_runner."""
        panel.set_current_worker(MagicMock())
        panel.set_current_worker(None)
        assert panel._pipeline_runner is None


class TestRawKeyRouting:
    def test_routes_to_runner_when_active(self, panel):
        """_on_raw_key sends bytes to _pipeline_runner.send_raw when runner is active."""
        mock_runner = MagicMock()
        panel.set_current_worker(mock_runner)
        panel._runner_active = True

        panel._on_raw_key(b"y\r")

        mock_runner.send_raw.assert_called_once_with(b"y\r")

    def test_routes_to_shell_when_not_active(self, panel):
        """_on_raw_key sends bytes to _shell.send_raw when runner is not active."""
        panel._runner_active = False
        with patch.object(panel._shell, "send_raw") as mock_send:
            panel._on_raw_key(b"ls\r")
            mock_send.assert_called_once_with(b"ls\r")

    def test_routes_to_shell_when_no_runner(self, panel):
        """_on_raw_key sends to _shell when _pipeline_runner is None."""
        panel._pipeline_runner = None
        panel._runner_active = True
        with patch.object(panel._shell, "send_raw") as mock_send:
            panel._on_raw_key(b"x")
            mock_send.assert_called_once_with(b"x")


class TestSignalBusCurrentWorker:
    def test_current_worker_changed_signal_updates_runner(self, panel, qtbot):
        """signal_bus.current_worker_changed → set_current_worker → _pipeline_runner."""
        from workflow_app.signal_bus import signal_bus
        mock_worker = MagicMock()
        signal_bus.current_worker_changed.emit(mock_worker)
        qtbot.wait(20)
        assert panel._pipeline_runner is mock_worker
