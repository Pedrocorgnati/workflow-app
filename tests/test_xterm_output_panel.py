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
    bridge = _PtyBridge(shell=shell)
    shell.output_received.connect(bridge.output_received)

    received: list[str] = []
    bridge.output_received.connect(received.append)

    payload = b"hello mundo \xc3\xa1".decode("utf-8")  # "hello mundo á"
    shell.output_received.emit(payload)

    assert received == [payload]


def test_bridge_writes_to_shell_on_input(qapp):
    """bridge.write_to_pty('hello') must call shell.send_raw(b'hello')."""
    mock_shell = MagicMock(spec=PersistentShell)
    bridge = _PtyBridge(shell=mock_shell)

    bridge.write_to_pty("hello")

    mock_shell.send_raw.assert_called_once_with(b"hello")


def test_bridge_resizes_shell(qapp):
    """bridge.resize_pty(80, 24) must call shell.resize(80, 24)."""
    mock_shell = MagicMock(spec=PersistentShell)
    bridge = _PtyBridge(shell=mock_shell)

    bridge.resize_pty(80, 24)

    mock_shell.resize.assert_called_once_with(80, 24)
