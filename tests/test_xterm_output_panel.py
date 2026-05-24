"""Tests for the _PtyBridge in xterm_output_panel — Python side only.

The xterm.js front-end runs in a QWebEngineView, which is heavy and flaky
in headless CI. These tests exercise the Python bridge (_PtyBridge) that
mediates between PersistentShell and the JS terminal, without booting any
QWebEngineView.

Covers:
  - shell.output_received -> bridge.output_received forwarding (decoded str)
  - bridge.write_to_pty(text) -> shell.send_raw(text.encode("utf-8"))
  - bridge.resize_pty(cols, rows) -> shell.resize(cols, rows)
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QWidget

from workflow_app.output_panel.persistent_shell import PersistentShell
from workflow_app.output_panel.xterm_output_panel import _PtyBridge


@pytest.fixture()
def shell(qapp):
    """Real PersistentShell instance without spawning a PTY (no start())."""
    return PersistentShell()


def test_bridge_emits_output_on_shell_data(qapp, shell):
    """When shell.output_received fires, bridge.output_received re-emits the same str.

    Mirrors the connection set up inside XtermOutputPanel.__init__.
    PersistentShell.output_received already decodes bytes -> str via an
    incremental UTF-8 decoder before emitting, so the bridge just forwards.
    """
    bridge = _PtyBridge(shell=shell, channel="workspace_xterm")
    shell.output_received.connect(bridge.output_received)

    received: list[str] = []
    bridge.output_received.connect(received.append)

    payload = b"hello mundo \xc3\xa1".decode("utf-8")  # "hello mundo á"
    shell.output_received.emit(payload)

    assert received == [payload]


def test_bridge_writes_to_shell_on_input(qapp):
    """bridge.write_to_pty('hello') must call shell.send_raw(b'hello')."""
    mock_shell = MagicMock(spec=PersistentShell)
    bridge = _PtyBridge(shell=mock_shell, channel="workspace_xterm")

    bridge.write_to_pty("hello")

    mock_shell.send_raw.assert_called_once_with(b"hello")


def test_bridge_resizes_shell(qapp):
    """bridge.resize_pty(80, 24) must call shell.resize(80, 24)."""
    mock_shell = MagicMock(spec=PersistentShell)
    bridge = _PtyBridge(shell=mock_shell, channel="workspace_xterm")

    bridge.resize_pty(80, 24)

    mock_shell.resize.assert_called_once_with(80, 24)


def test_bridge_drops_degenerate_resize(qapp):
    """resize_pty with non-positive dims (collapsed 0x0 webview) is dropped.

    A collapsed QWebEngineView makes xterm.js' FitAddon emit resize(0, 0).
    Forwarding it to the PTY triggers a SIGWINCH storm that pins the
    Terminal 3 listener yellow — so the bridge must drop those.
    """
    mock_shell = MagicMock(spec=PersistentShell)
    bridge = _PtyBridge(shell=mock_shell, channel="workspace_xterm")

    bridge.resize_pty(0, 0)
    bridge.resize_pty(-1, 24)
    bridge.resize_pty(80, 0)

    mock_shell.resize.assert_not_called()


def test_bridge_does_not_start_session_on_protocol_reply(qapp):
    """A bare xterm.js terminal-report reply (CPR) must NOT start a session.

    xterm.js routes its automatic CPR/DA/DSR replies through the same
    onData channel as user keystrokes. Those carry no CR/LF and must not
    release the workspace_xterm idle lock — regression: a collapsed/idle
    Terminal 3 was pinned yellow by the CPR reply of the zsh prompt.
    The reply is still forwarded to the PTY (the shell needs it).
    """
    from workflow_app.signal_bus import signal_bus

    mock_shell = MagicMock(spec=PersistentShell)
    bridge = _PtyBridge(shell=mock_shell, channel="workspace_xterm")

    started: list[str] = []

    def _record(channel: str) -> None:
        started.append(channel)

    signal_bus.terminal_session_started.connect(_record)
    try:
        bridge.write_to_pty("\x1b[24;80R")  # CPR reply emitted by xterm.js
    finally:
        signal_bus.terminal_session_started.disconnect(_record)

    assert started == []
    mock_shell.send_raw.assert_called_once_with(b"\x1b[24;80R")


def test_bridge_starts_session_on_submitted_line(qapp):
    """A submitted command line (data carrying CR) DOES start a session."""
    from workflow_app.signal_bus import signal_bus

    mock_shell = MagicMock(spec=PersistentShell)
    bridge = _PtyBridge(shell=mock_shell, channel="workspace_xterm")

    started: list[str] = []

    def _record(channel: str) -> None:
        started.append(channel)

    signal_bus.terminal_session_started.connect(_record)
    try:
        bridge.write_to_pty("\r")
    finally:
        signal_bus.terminal_session_started.disconnect(_record)

    assert started == ["workspace_xterm"]
    mock_shell.send_raw.assert_called_once_with(b"\r")


def test_workspace_xterm_panel_binds_workspace_xterm_channel(qapp, monkeypatch):
    """T3 must export WF_CHANNEL_OVERRIDE=workspace_xterm to its PTY."""
    from workflow_app.output_panel import xterm_output_panel as xterm_module

    class FakePage:
        def setWebChannel(self, _channel):
            self.web_channel = _channel

        def runJavaScript(self, _script):
            pass

    class FakeWebEngineView(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self._page = FakePage()

        def page(self):
            return self._page

        def load(self, _url):
            pass

    class FakeWebChannel(QObject):
        def registerObject(self, name, obj):
            self.registered = (name, obj)

    class FakeShell(QObject):
        output_received = Signal(str)

        def __init__(self, *args, extra_env=None, parent=None, **kwargs):
            super().__init__(parent)
            self._extra_env = dict(extra_env or {})

        def start(self):
            pass

        def send_raw(self, _data):
            pass

        def resize(self, _cols, _rows):
            pass

    monkeypatch.setattr(xterm_module, "QWebEngineView", FakeWebEngineView)
    monkeypatch.setattr(xterm_module, "QWebChannel", FakeWebChannel)
    monkeypatch.setattr(xterm_module, "PersistentShell", FakeShell)

    panel = xterm_module.XtermOutputPanel(workspace_mode=True)
    try:
        assert panel._shell._extra_env["WF_CHANNEL_OVERRIDE"] == "workspace_xterm"
        assert panel._channel_name == "workspace_xterm"
    finally:
        panel.deleteLater()


def test_xterm_panel_ensure_shell_started_is_idempotent(qapp, monkeypatch):
    """Parallel T3 dispatch may happen while the panel is collapsed."""
    from workflow_app.output_panel import xterm_output_panel as xterm_module

    class FakePage:
        def setWebChannel(self, _channel):
            pass

    class FakeWebEngineView(QWidget):
        def __init__(self, parent=None):
            super().__init__(parent)
            self._page = FakePage()

        def page(self):
            return self._page

        def load(self, _url):
            pass

    class FakeWebChannel(QObject):
        def registerObject(self, _name, _obj):
            pass

    class FakeShell(QObject):
        output_received = Signal(str)

        def __init__(self, *args, extra_env=None, parent=None, **kwargs):
            super().__init__(parent)
            self._extra_env = dict(extra_env or {})
            self.starts = 0
            self._master_fd = None

        def start(self):
            self.starts += 1
            self._master_fd = 123

        def send_raw(self, _data):
            pass

        def resize(self, _cols, _rows):
            pass

    monkeypatch.setattr(xterm_module, "QWebEngineView", FakeWebEngineView)
    monkeypatch.setattr(xterm_module, "QWebChannel", FakeWebChannel)
    monkeypatch.setattr(xterm_module, "PersistentShell", FakeShell)

    panel = xterm_module.XtermOutputPanel(workspace_mode=True)
    try:
        panel.ensure_shell_started()
        panel.ensure_shell_started()
        assert panel._shell.starts == 1
        assert panel._shell_started is True
        assert panel._shell._master_fd == 123
    finally:
        panel.deleteLater()
