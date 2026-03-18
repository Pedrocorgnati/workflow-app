"""Tests for OutputPanel streaming output — pyte/PersistentShell architecture.

Covers:
  - Plain text chunks are rendered to the terminal after _flush_pyte()
  - ANSI color sequences are rendered via pyte (no raw escape codes in output)
  - clear() empties the terminal
  - _on_pipeline_started appends status message directly (bypasses pyte)
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
    """clear() empties the QTextEdit."""
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


def test_pipeline_started_shows_message(panel):
    """_on_pipeline_started appends status message directly to terminal."""
    panel._on_pipeline_started()
    text = panel._terminal.toPlainText()
    assert "Pipeline iniciado" in text


def test_pipeline_started_unflushed_data_cleared(panel):
    """Data in pyte buffer (not yet flushed) is discarded when pipeline starts."""
    panel._on_chunk("texto antigo\n")
    # No _flush_pyte() → text only in pyte buffer, not in terminal widget
    panel._on_pipeline_started()  # resets pyte, appends message directly
    text = panel._terminal.toPlainText()
    assert "Pipeline iniciado" in text
    assert "texto antigo" not in text


def test_has_pending_render_after_chunk(panel):
    """_on_chunk() sets _has_pending_render to True."""
    panel._on_chunk("something\n")
    assert panel._has_pending_render is True


def test_flush_clears_pending_render_flag(panel):
    """_flush_pyte() clears _has_pending_render."""
    panel._on_chunk("something\n")
    panel._flush_pyte()
    assert panel._has_pending_render is False
