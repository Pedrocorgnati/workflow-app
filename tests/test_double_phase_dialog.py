"""Tests for DoublePhaseArgumentDialog (queue-btn-study e demais consumidores).

Cobre:
  - Parser: enum_flag e freetext (TASK-2 do loop queue-progress-ring-v3).
  - Render: QButtonGroup mutex para `[--simple|--deep|--heavy]`.
  - Render: AutoGrowTextEdit para `"<duvida>"` com clamp MIN/MAX.
  - Serializacao: enum_flag append do flag escolhido + freetext quoted.
"""

from __future__ import annotations

import pytest
from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QLineEdit,
)

from workflow_app.command_queue.double_phase_dialog import (
    AutoGrowTextEdit,
    DoublePhaseArgumentDialog,
    RadioGroupWithSummary,
    _parse_argument_hint,
)

STUDY_HINT = '"<duvida>" [path.md] [--name <slug>] [--simple|--deep|--heavy]'


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


def test_parser_classifies_bracketed_enum_flag_as_enum_flag():
    """[--simple|--deep|--heavy] deve virar enum_flag (nao checkbox)."""
    tokens = _parse_argument_hint("[--simple|--deep|--heavy]")
    assert len(tokens) == 1
    assert tokens[0].kind == "enum_flag"
    assert tokens[0].options == ["--simple", "--deep", "--heavy"]


def test_parser_classifies_quoted_angle_as_freetext():
    """`"<duvida>"` deve virar freetext."""
    tokens = _parse_argument_hint('"<duvida>"')
    assert len(tokens) == 1
    assert tokens[0].kind == "freetext"


def test_parser_full_study_hint():
    """Hint canonico do queue-btn-study: 4 tokens com kinds esperados."""
    tokens = _parse_argument_hint(STUDY_HINT)
    kinds = [t.kind for t in tokens]
    assert kinds == ["freetext", "input", "checkbox", "enum_flag"]


def test_parser_keeps_outside_radio_kind_for_non_bracketed_pipes():
    """--a|--b fora de colchetes mantem kind radio (compat retro)."""
    tokens = _parse_argument_hint("--a|--b")
    assert len(tokens) == 1
    assert tokens[0].kind == "radio"


# ---------------------------------------------------------------------------
# Render: enum_flag mutex
# ---------------------------------------------------------------------------


def test_enum_flag_renders_as_radio_group_with_button_group(qapp):
    """[--simple|--deep|--heavy] -> RadioGroupWithSummary com QButtonGroup."""
    dlg = DoublePhaseArgumentDialog(
        pipeline_name="/study",
        argument_hint="[--simple|--deep|--heavy]",
        default_md_dir="",
        radio_summaries={"--simple": "rapido", "--deep": "medio", "--heavy": "denso"},
    )
    radio_groups = dlg.findChildren(RadioGroupWithSummary)
    assert len(radio_groups) == 1
    rg = radio_groups[0]
    bg = rg.button_group()
    assert isinstance(bg, QButtonGroup)
    assert bg.exclusive() is True
    assert len(bg.buttons()) == 3
    dlg.deleteLater()


def test_enum_flag_mutex_only_one_button_checked_after_clicks(qapp):
    """Clicar em --deep apos --simple desmarca --simple (mutex)."""
    dlg = DoublePhaseArgumentDialog(
        pipeline_name="/study",
        argument_hint="[--simple|--deep|--heavy]",
        default_md_dir="",
        radio_summaries={},
    )
    rg = dlg.findChild(RadioGroupWithSummary)
    assert rg is not None
    buttons = rg.button_group().buttons()
    by_text = {b.text(): b for b in buttons}

    by_text["--simple"].setChecked(True)
    assert by_text["--simple"].isChecked() is True

    by_text["--deep"].setChecked(True)
    checked = [b for b in buttons if b.isChecked()]
    assert len(checked) == 1
    assert checked[0].text() == "--deep"

    by_text["--heavy"].setChecked(True)
    checked = [b for b in buttons if b.isChecked()]
    assert len(checked) == 1
    assert checked[0].text() == "--heavy"
    dlg.deleteLater()


def test_enum_flag_serializes_selected_flag_into_command_line(qapp):
    """Submit emite linha com o flag selecionado anexado ao pipeline."""
    dlg = DoublePhaseArgumentDialog(
        pipeline_name="/study",
        argument_hint="[--simple|--deep|--heavy]",
        default_md_dir="",
        radio_summaries={},
    )
    rg = dlg.findChild(RadioGroupWithSummary)
    by_text = {b.text(): b for b in rg.button_group().buttons()}
    by_text["--deep"].setChecked(True)

    spy = QSignalSpy(dlg.submitted)
    dlg._on_confirm()
    assert spy.count() == 1
    assert spy.at(0)[0] == "/study --deep"
    dlg.deleteLater()


# ---------------------------------------------------------------------------
# Render: freetext auto-grow
# ---------------------------------------------------------------------------


def test_freetext_renders_as_autogrow_textedit(qapp):
    """`"<duvida>"` -> AutoGrowTextEdit no formulario."""
    dlg = DoublePhaseArgumentDialog(
        pipeline_name="/study",
        argument_hint='"<duvida>"',
        default_md_dir="",
        radio_summaries={},
    )
    tedits = dlg.findChildren(AutoGrowTextEdit)
    assert len(tedits) == 1
    assert tedits[0].height() == AutoGrowTextEdit.MIN_HEIGHT
    # Garante que NAO renderizou como QLineEdit ou QCheckBox.
    assert dlg.findChild(QLineEdit) is None
    assert dlg.findChild(QCheckBox) is None
    dlg.deleteLater()


def test_freetext_autogrow_grows_within_clamp(qapp):
    """Texto multilinha cresce ate MAX_HEIGHT e clampa."""
    te = AutoGrowTextEdit(placeholder="<duvida>")
    te.show()
    qapp.processEvents()

    # Estado inicial: altura == MIN.
    assert te.height() == AutoGrowTextEdit.MIN_HEIGHT

    # Texto medio: cresce alguma coisa, mas dentro do range.
    te.setPlainText("linha 1\nlinha 2\nlinha 3")
    qapp.processEvents()
    h_medium = te.height()
    assert AutoGrowTextEdit.MIN_HEIGHT <= h_medium <= AutoGrowTextEdit.MAX_HEIGHT

    # Texto enorme: clampa em MAX.
    huge = "\n".join(f"linha {i}" for i in range(60))
    te.setPlainText(huge)
    qapp.processEvents()
    assert te.height() == AutoGrowTextEdit.MAX_HEIGHT

    # Esvaziar: volta a MIN.
    te.setPlainText("")
    qapp.processEvents()
    assert te.height() == AutoGrowTextEdit.MIN_HEIGHT
    te.deleteLater()


def test_freetext_serialization_quotes_text_with_spaces(qapp):
    """Conteudo com espacos e quoted; sem espacos vai cru."""
    dlg = DoublePhaseArgumentDialog(
        pipeline_name="/study",
        argument_hint='"<duvida>"',
        default_md_dir="",
        radio_summaries={},
    )
    te = dlg.findChild(AutoGrowTextEdit)
    te.setPlainText("como funciona o RAG hibrido")

    spy = QSignalSpy(dlg.submitted)
    dlg._on_confirm()
    assert spy.count() == 1
    assert spy.at(0)[0] == '/study "como funciona o RAG hibrido"'
    dlg.deleteLater()


def test_freetext_serialization_no_quotes_for_single_token(qapp):
    """Conteudo sem espacos vai sem aspas."""
    dlg = DoublePhaseArgumentDialog(
        pipeline_name="/study",
        argument_hint='"<duvida>"',
        default_md_dir="",
        radio_summaries={},
    )
    te = dlg.findChild(AutoGrowTextEdit)
    te.setPlainText("RAG")

    spy = QSignalSpy(dlg.submitted)
    dlg._on_confirm()
    assert spy.at(0)[0] == "/study RAG"
    dlg.deleteLater()


# ---------------------------------------------------------------------------
# Compat: hint completo do queue-btn-study end-to-end
# ---------------------------------------------------------------------------


def test_full_study_hint_renders_all_widget_kinds(qapp):
    """Hint canonico instancia 1 freetext, 1 input, 1 checkbox, 1 enum_flag."""
    dlg = DoublePhaseArgumentDialog(
        pipeline_name="/study",
        argument_hint=STUDY_HINT,
        default_md_dir="",
        radio_summaries={
            "--simple": "rapido",
            "--deep": "medio",
            "--heavy": "denso",
        },
    )
    assert len(dlg.findChildren(AutoGrowTextEdit)) == 1
    # path.md gera input simples (QLineEdit).
    assert len(dlg.findChildren(QLineEdit)) == 1
    # [--name <slug>] cai como checkbox (fora do escopo desta task corrigir).
    assert len(dlg.findChildren(QCheckBox)) == 1
    rgs = dlg.findChildren(RadioGroupWithSummary)
    assert len(rgs) == 1
    assert rgs[0].button_group().exclusive() is True
    dlg.deleteLater()
