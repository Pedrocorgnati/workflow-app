"""Testes de regressao para o bug literal `<slug>` (Parte 5).

Valida que placeholders (<slug>, <path>, etc.) nunca aparecem literais
na string de comando final, tanto no modo estruturado quanto no legado.
"""

from __future__ import annotations

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QCheckBox

from workflow_app.command_queue.double_phase_dialog import (
    DoublePhaseArgumentDialog,
    _parse_argument_hint,
)
from workflow_app.domain import FlagSpec


# ---------------------------------------------------------------------------
# Legacy mode: checkbox com placeholder
# ---------------------------------------------------------------------------


def test_legacy_checkbox_with_placeholder_never_emits_literal(qapp):
    """[--name <slug>] (checkbox_with_value, task-022): vazio bloqueia o submit;
    preenchido emite o valor real, nunca o literal '<slug>'."""
    from PySide6.QtWidgets import QLineEdit

    dlg = DoublePhaseArgumentDialog(
        pipeline_name="/study",
        argument_hint="[--name <slug>]",
        default_md_dir="",
        radio_summaries={},
    )
    chk = dlg.findChild(QCheckBox)
    chk.setChecked(True)

    # Valor vazio: validacao de slug (task-022) bloqueia o submit.
    spy_empty = QSignalSpy(dlg.submitted)
    dlg._on_confirm()
    assert spy_empty.count() == 0

    # Valor valido: emite o slug real, jamais o placeholder literal.
    dlg.findChild(QLineEdit).setText("meu-slug")
    spy = QSignalSpy(dlg.submitted)
    dlg._on_confirm()
    assert spy.count() == 1
    cmd = spy.at(0)[0]
    assert "<slug>" not in cmd
    assert cmd == "/study --name meu-slug"
    dlg.deleteLater()


def test_legacy_checkbox_without_placeholder_emits_normally(qapp):
    """Checkbox sem placeholder deve continuar funcionando normalmente."""
    dlg = DoublePhaseArgumentDialog(
        pipeline_name="/cmd",
        argument_hint="[--force]",
        default_md_dir="",
        radio_summaries={},
    )
    chk = dlg.findChild(QCheckBox)
    chk.setChecked(True)

    spy = QSignalSpy(dlg.submitted)
    dlg._on_confirm()
    assert spy.count() == 1
    assert spy.at(0)[0] == "/cmd --force"
    dlg.deleteLater()


# ---------------------------------------------------------------------------
# Structured mode
# ---------------------------------------------------------------------------


def test_structured_flag_with_value_never_emits_placeholder(qapp):
    """Modo estruturado deve usar valor real, nunca placeholder literal."""
    dlg = DoublePhaseArgumentDialog(
        pipeline_name="/loop",
        flags_with_value=[FlagSpec(name="name", label="Nome", placeholder="slug")],
    )
    pte = dlg.findChild(type(dlg).__bases__[0])  # nao precisa
    from PySide6.QtWidgets import QPlainTextEdit, QLineEdit

    pte = dlg.findChild(QPlainTextEdit)
    pte.setPlainText("tasks.md")

    chk = dlg.findChild(QCheckBox)
    chk.setChecked(True)

    line = dlg.findChild(QLineEdit)
    line.setText("meu-slug")

    spy = QSignalSpy(dlg.submitted)
    dlg._on_confirm()
    assert spy.count() == 1
    cmd = spy.at(0)[0]
    assert "<slug>" not in cmd
    assert "<path>" not in cmd
    assert "--name meu-slug" in cmd
    dlg.deleteLater()


def test_structured_blocks_when_input_empty(qapp):
    """Flag validada (--name) marcada com input vazio bloqueia o submit (task-022).

    Contrato anterior omitia a flag; a lane de validacao task-022 passou a
    exigir slug valido, entao o submit nao emite ate o campo ser preenchido.
    """
    dlg = DoublePhaseArgumentDialog(
        pipeline_name="/loop",
        flags_with_value=[FlagSpec(name="name", label="Nome", placeholder="slug")],
    )
    from PySide6.QtWidgets import QCheckBox

    chk = dlg.findChild(QCheckBox)
    chk.setChecked(True)

    spy = QSignalSpy(dlg.submitted)
    dlg._on_confirm()
    assert spy.count() == 0
    dlg.deleteLater()


# ---------------------------------------------------------------------------
# Parser: token classification
# ---------------------------------------------------------------------------


def test_parser_checkbox_with_placeholder_classified_as_checkbox_with_value():
    """Parser classifica [--name <slug>] como checkbox_with_value (task-022)."""
    tokens = _parse_argument_hint("[--name <slug>]")
    assert len(tokens) == 1
    assert tokens[0].kind == "checkbox_with_value"
    assert tokens[0].key == "--name"
    assert tokens[0].options == ["slug"]
