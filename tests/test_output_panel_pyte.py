"""Tests for OutputPanel streaming output — pyte/TerminalCanvas architecture.

Covers:
  - Plain text chunks are rendered to the terminal after _flush_pyte()
  - ANSI color sequences are rendered via pyte (no raw escape codes in output)
  - clear() empties the terminal
  - _on_chunk accumulates multiple lines
"""
from __future__ import annotations

import pytest

from workflow_app.output_panel.output_panel import OutputPanel


@pytest.fixture()
def panel(qapp, qtbot):
    p = OutputPanel()
    qtbot.addWidget(p)
    return p


def test_plain_text_chunk_rendered(panel):
    """Plain text chunk is displayed after _flush_pyte()."""
    panel._on_chunk("Hello, World!\n")
    panel._flush_pyte()
    text = panel._terminal.toPlainText()
    assert "Hello, World!" in text


def test_ansi_color_sequence_no_escape_codes(panel):
    """ANSI colour sequences are rendered via pyte — no raw \\x1b in output."""
    panel._on_chunk("\x1b[32mSucesso\x1b[0m\n")
    panel._flush_pyte()
    text = panel._terminal.toPlainText()
    assert "\x1b" not in text


def test_ansi_color_sequence_shows_text(panel):
    """After pyte rendering, the visible text (without escape codes) is present."""
    panel._on_chunk("\x1b[32mSucesso\x1b[0m\n")
    panel._flush_pyte()
    text = panel._terminal.toPlainText()
    assert "Sucesso" in text


def test_pure_ansi_chunk_no_escape_codes(panel):
    """Chunks with only ANSI codes produce no raw escape codes in the output."""
    panel.clear()
    panel._on_chunk("\x1b[32m\x1b[0m")
    panel._flush_pyte()
    assert "\x1b" not in panel._terminal.toPlainText()


def test_clear_resets_terminal(panel):
    """clear() empties the terminal."""
    panel._on_chunk("algum texto\n")
    panel._flush_pyte()
    panel.clear()
    assert panel._terminal.toPlainText() == ""


def test_multiple_chunks_accumulate(panel):
    """Multiple chunks accumulate in the terminal without overwriting."""
    panel._on_chunk("linha-A\n")
    panel._on_chunk("linha-B\n")
    panel._flush_pyte()
    text = panel._terminal.toPlainText()
    assert "linha-A" in text
    assert "linha-B" in text


def test_pipeline_started_no_crash(panel):
    """_on_pipeline_started() does not crash."""
    panel._on_pipeline_started()


def test_has_pending_render_after_chunk(panel):
    """_on_chunk() sets _has_pending_render to True."""
    panel._on_chunk("something\n")
    assert panel._has_pending_render is True


def test_flush_clears_pending_render_flag(panel):
    """_flush_pyte() clears _has_pending_render."""
    panel._on_chunk("something\n")
    panel._flush_pyte()
    assert panel._has_pending_render is False


# Resize sync regression tests (PR1: shell-first order, mode preservation, drain cap).

import os
import threading
import time
from unittest import mock

from workflow_app.output_panel.enhanced_screen import EnhancedScreen
from workflow_app.output_panel.persistent_shell import PersistentShell


class TestResizeSync:
    """Grouped so `pytest -k resize` selects all three regression tests."""

    def test_resize_calls_shell_before_screen(self, panel, monkeypatch):
        """_apply_pending_resize must call shell.resize BEFORE screen.resize."""
        calls: list[str] = []

        if panel._shell is None:
            panel._shell = mock.MagicMock()

        def shell_resize(cols, rows):
            calls.append("shell")

        def screen_resize(lines=None, columns=None):
            calls.append("screen")

        monkeypatch.setattr(panel._shell, "resize", shell_resize)
        monkeypatch.setattr(panel._screen, "resize", screen_resize)

        panel._pending_cols = panel._cols + 10
        panel._pending_rows = panel._rows + 5
        panel._apply_pending_resize()

        assert "shell" in calls
        assert "screen" in calls
        assert calls.index("shell") < calls.index("screen"), (
            f"shell must precede screen, got {calls}"
        )

    def test_resize_preserves_pyte_modes(self):
        """EnhancedScreen.resize must preserve self.mode (pyte#95 regression).

        Sets DECOM-equivalent mode bit 6 on the screen, triggers resize, and
        asserts the mode survives. The override saves self.mode before
        super().resize() (which drops modes) and restores it.
        """
        screen = EnhancedScreen(80, 24, history=100)
        screen.set_mode(6)
        assert 6 in screen.mode, "precondition: mode 6 active before resize"
        screen.resize(40, 100)
        assert 6 in screen.mode, "resize must not drop pyte modes"

    def test_drain_does_not_block_when_streaming(self, qapp, monkeypatch):
        """PersistentShell.resize drain loop must cap below ~80ms under continuous stream.

        Uses os.pipe with a writer thread pushing bytes continuously so the
        drain loop always sees the fd ready. Internal deadline is 50ms;
        total resize() should finish under 80ms (drain cap + folga).
        """
        r, w = os.pipe()
        stop_event = threading.Event()

        def writer():
            while not stop_event.is_set():
                try:
                    os.write(w, b"x" * 256)
                except OSError:
                    break

        t = threading.Thread(target=writer, daemon=True)
        t.start()

        monkeypatch.setattr("fcntl.ioctl", lambda *a, **kw: 0)

        shell = PersistentShell(cols=80, rows=24)
        shell._master_fd = r

        try:
            t0 = time.monotonic()
            shell.resize(120, 30)
            elapsed = time.monotonic() - t0
        finally:
            stop_event.set()
            t.join(timeout=1.0)
            try:
                os.close(w)
            except OSError:
                pass
            try:
                os.close(r)
            except OSError:
                pass

        assert elapsed < 0.080, (
            f"drain must cap below 80ms, got {elapsed * 1000:.1f}ms"
        )
