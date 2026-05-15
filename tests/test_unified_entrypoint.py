"""Tests for unified entrypoint (Parte 4).

Valida que queue-btn-loop, queue-btn-daily-loop e queue-btn-cmd-single
compartilham o mesmo handler e o mesmo modal DoublePhaseArgumentDialog.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtWidgets import QApplication

from workflow_app.command_queue.double_phase_button import DoublePhaseButton
from workflow_app.command_queue.double_phase_dialog import DoublePhaseArgumentDialog
from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
from workflow_app.domain import CommandSpec, FlagSpec, ModelName, InteractionType


# ---------------------------------------------------------------------------
# DoublePhaseButton with structured flags
# ---------------------------------------------------------------------------


def test_double_phase_button_passes_flags_to_dialog(qapp):
    """DoublePhaseButton deve repassar flags_boolean/flags_with_value ao dialog."""
    received = {}

    def capture_dialog(**kwargs):
        received.update(kwargs)
        dlg = MagicMock()
        dlg.submitted = MagicMock()
        dlg.exec = MagicMock()
        return dlg

    btn = DoublePhaseButton(
        label="loop",
        pipeline_name="/loop",
        flags_boolean=["force"],
        flags_with_value=[FlagSpec(name="name", label="Nome")],
        pill=None,
        on_command_ready=lambda x: None,
    )

    with patch("workflow_app.command_queue.double_phase_button.DoublePhaseArgumentDialog", side_effect=capture_dialog):
        btn._on_clicked()

    assert received.get("flags_boolean") == ["force"]
    assert len(received.get("flags_with_value", [])) == 1
    assert received["flags_with_value"][0].name == "name"


# ---------------------------------------------------------------------------
# Unified handler dispatch
# ---------------------------------------------------------------------------


def test_unified_handler_dispatches_loop(qapp):
    """_on_unified_command_ready deve delegar /loop para _on_loop_command_ready."""
    widget = CommandQueueWidget()
    with patch.object(widget, "_on_loop_command_ready") as mock_loop:
        widget._on_unified_command_ready("/loop --task tasks.md")
        mock_loop.assert_called_once_with("/loop --task tasks.md")
    widget.deleteLater()


def test_unified_handler_dispatches_daily_loop(qapp):
    """_on_unified_command_ready deve delegar /daily-loop para _on_daily_loop_command_ready."""
    widget = CommandQueueWidget()
    with patch.object(widget, "_on_daily_loop_command_ready") as mock_daily:
        widget._on_unified_command_ready("/daily-loop descricao")
        mock_daily.assert_called_once_with("/daily-loop descricao")
    widget.deleteLater()


def test_unified_handler_fallback_for_unknown(qapp):
    """Comandos desconhecidos devem ser adicionados via add_command."""
    widget = CommandQueueWidget()
    with patch.object(widget, "add_command") as mock_add:
        widget._on_unified_command_ready("/custom arg")
        mock_add.assert_called_once()
        spec = mock_add.call_args[0][0]
        assert isinstance(spec, CommandSpec)
        assert spec.name == "/custom arg"
    widget.deleteLater()


# ---------------------------------------------------------------------------
# Widget tree: cmd-single uses DoublePhaseButton
# ---------------------------------------------------------------------------


def test_cmd_single_is_double_phase_button(qapp):
    """queue-btn-cmd-single deve ser uma instancia de DoublePhaseButton."""
    widget = CommandQueueWidget()
    # Encontra o header_widget que contem os botoes
    header = widget.header_widget
    btn = None
    for child in header.findChildren(DoublePhaseButton):
        if child.property("testid") == "queue-btn-cmd-single":
            btn = child
            break
    assert btn is not None, "queue-btn-cmd-single DoublePhaseButton nao encontrado"
    assert isinstance(btn, DoublePhaseButton)
    widget.deleteLater()


def test_loop_and_daily_loop_are_double_phase_buttons(qapp):
    """queue-btn-loop e queue-btn-daily-loop devem ser DoublePhaseButton."""
    widget = CommandQueueWidget()
    header = widget.header_widget
    testids = {"queue-btn-loop", "queue-btn-daily-loop"}
    found = set()
    for child in header.findChildren(DoublePhaseButton):
        tid = child.property("testid")
        if tid in testids:
            found.add(tid)
    assert found == testids, f"Botoes faltando: {testids - found}"
    widget.deleteLater()


# ---------------------------------------------------------------------------
# Modal class uniformity
# ---------------------------------------------------------------------------


def test_all_three_buttons_open_same_dialog_class(qapp):
    """Clique nos 3 botoes deve instanciar DoublePhaseArgumentDialog."""
    widget = CommandQueueWidget()
    header = widget.header_widget

    for testid in ("queue-btn-loop", "queue-btn-daily-loop", "queue-btn-cmd-single"):
        btn = None
        for child in header.findChildren(DoublePhaseButton):
            if child.property("testid") == testid:
                btn = child
                break
        assert btn is not None, f"{testid} nao encontrado"

        with patch("workflow_app.command_queue.double_phase_button.DoublePhaseArgumentDialog") as mock_dlg:
            mock_instance = MagicMock()
            mock_instance.submitted = MagicMock()
            mock_instance.exec = MagicMock()
            mock_dlg.return_value = mock_instance
            btn._on_clicked()
            mock_dlg.assert_called_once()
            assert mock_dlg.call_args.kwargs.get("pipeline_name") in ("/loop", "/daily-loop")

    widget.deleteLater()
