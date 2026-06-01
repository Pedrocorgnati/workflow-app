"""Tests for DoublePhaseArgumentDialog structured mode (Parte 3 refactor).

Valida novo layout: input multiline, row de checkboxes, inputs condicionais,
sizing dinamico e ausencia de heading redundante.
"""

from __future__ import annotations

from PySide6.QtTest import QSignalSpy
from PySide6.QtWidgets import QCheckBox, QLineEdit, QPlainTextEdit, QPushButton

from workflow_app.command_queue.double_phase_dialog import (
    DoublePhaseArgumentDialog,
    PathMdFieldWidget,
)
from workflow_app.domain import FlagSpec


# ---------------------------------------------------------------------------
# Render
# ---------------------------------------------------------------------------


def test_structured_no_redundant_heading(qapp):
    """Titulo redundante /loop deve estar ausente do widget tree."""
    dlg = DoublePhaseArgumentDialog(
        pipeline_name="/loop",
        flags_boolean=["force"],
        flags_with_value=[FlagSpec(name="name", label="Nome", placeholder="slug")],
    )
    labels = dlg.findChildren(type(dlg).__bases__[0])  # nao funciona diretamente
    # Verificamos via findChildren(QLabel) e conteudo
    from PySide6.QtWidgets import QLabel
    all_labels = dlg.findChildren(QLabel)
    texts = [lb.text() for lb in all_labels]
    assert "/loop" not in texts
    dlg.deleteLater()


def test_structured_renders_main_plaintextedit(qapp):
    """Modo estruturado deve renderizar QPlainTextEdit principal."""
    dlg = DoublePhaseArgumentDialog(
        pipeline_name="/loop",
        flags_with_value=[FlagSpec(name="task", label="Task", placeholder="tasks.md")],
    )
    edits = dlg.findChildren(QPlainTextEdit)
    assert len(edits) == 1
    browse = dlg.findChild(QPushButton, None)
    assert browse is not None
    dlg.deleteLater()


def test_structured_main_input_has_md_browse_button(qapp):
    """Input principal path.md/prompt tem lupa 1:1 no fim da row."""
    dlg = DoublePhaseArgumentDialog(
        pipeline_name="/loop",
        flags_with_value=[FlagSpec(name="task", label="Task", placeholder="tasks.md")],
    )
    buttons = [
        btn for btn in dlg.findChildren(QPushButton)
        if btn.property("testid") == "double-phase-main-md-browse"
    ]
    assert len(buttons) == 1
    assert buttons[0].text() == "🔍"
    assert buttons[0].width() == buttons[0].height()
    dlg.deleteLater()


def test_structured_path_flags_use_path_md_widget(qapp):
    """Flags estruturadas com placeholder .md recebem picker de markdown."""
    dlg = DoublePhaseArgumentDialog(
        pipeline_name="/loop",
        flags_with_value=[
            FlagSpec(name="task", label="Task", placeholder="caminho/para/tasklist.md"),
            FlagSpec(name="name", label="Nome", placeholder="slug"),
        ],
    )
    assert len(dlg.findChildren(PathMdFieldWidget)) == 1
    dlg.deleteLater()


def test_structured_renders_checkbox_row(qapp):
    """Todas as flags devem aparecer como QCheckBox."""
    dlg = DoublePhaseArgumentDialog(
        pipeline_name="/loop",
        flags_boolean=["force", "dry-run"],
        flags_with_value=[FlagSpec(name="name", label="Nome")],
    )
    checkboxes = dlg.findChildren(QCheckBox)
    texts = [chk.text() for chk in checkboxes]
    assert "--force" in texts
    assert "--dry-run" in texts
    assert "--name" in texts
    dlg.deleteLater()


def test_structured_conditional_input_hidden_by_default(qapp):
    """Inputs condicionais devem comecar ocultos."""
    dlg = DoublePhaseArgumentDialog(
        pipeline_name="/loop",
        flags_with_value=[FlagSpec(name="name", label="Nome", placeholder="slug")],
    )
    lines = dlg.findChildren(QLineEdit)
    # O unico QLineEdit e o input condicional
    assert len(lines) == 1
    assert lines[0].isVisible() is False
    dlg.deleteLater()


def test_structured_conditional_input_shows_on_check(qapp):
    """Marcar checkbox deve revelar o input condicional sem recriar widget."""
    dlg = DoublePhaseArgumentDialog(
        pipeline_name="/loop",
        flags_with_value=[FlagSpec(name="name", label="Nome", placeholder="slug")],
    )
    dlg.show()
    qapp.processEvents()

    chk = dlg.findChild(QCheckBox)
    line = dlg.findChild(QLineEdit)
    assert line.isVisible() is False

    chk.setChecked(True)
    qapp.processEvents()
    assert line.isVisible() is True

    chk.setChecked(False)
    qapp.processEvents()
    assert line.isVisible() is False

    dlg.deleteLater()


def test_structured_sizing_at_least_sizehint(qapp):
    """Dialog size deve ser >= sizeHint() apos abertura."""
    dlg = DoublePhaseArgumentDialog(
        pipeline_name="/loop",
        flags_boolean=["force"],
        flags_with_value=[FlagSpec(name="name", label="Nome")],
    )
    dlg.show()
    qapp.processEvents()
    assert dlg.width() >= dlg.sizeHint().width()
    assert dlg.height() >= dlg.sizeHint().height()
    dlg.deleteLater()


# ---------------------------------------------------------------------------
# Serialization
# ---------------------------------------------------------------------------


def test_structured_serializes_main_input_and_flags(qapp):
    dlg = DoublePhaseArgumentDialog(
        pipeline_name="/loop",
        flags_boolean=["force"],
        flags_with_value=[FlagSpec(name="name", label="Nome")],
    )
    pte = dlg.findChild(QPlainTextEdit)
    pte.setPlainText("tasks.md")

    chk_force = next(c for c in dlg.findChildren(QCheckBox) if c.text() == "--force")
    chk_force.setChecked(True)

    chk_name = next(c for c in dlg.findChildren(QCheckBox) if c.text() == "--name")
    chk_name.setChecked(True)
    line = dlg.findChild(QLineEdit)
    line.setText("my-loop")

    spy = QSignalSpy(dlg.submitted)
    dlg._on_confirm()
    assert spy.count() == 1
    cmd = spy.at(0)[0]
    assert "<" not in cmd
    assert ">" not in cmd
    assert cmd == "/loop tasks.md --force --name my-loop"
    dlg.deleteLater()


def test_structured_omits_unchecked_flags(qapp):
    dlg = DoublePhaseArgumentDialog(
        pipeline_name="/loop",
        flags_with_value=[FlagSpec(name="name", label="Nome")],
    )
    pte = dlg.findChild(QPlainTextEdit)
    pte.setPlainText("tasks.md")

    spy = QSignalSpy(dlg.submitted)
    dlg._on_confirm()
    assert spy.count() == 1
    assert spy.at(0)[0] == "/loop tasks.md"
    dlg.deleteLater()


def test_structured_quotes_main_input_with_spaces(qapp):
    dlg = DoublePhaseArgumentDialog(
        pipeline_name="/daily-loop",
        flags_boolean=["reset"],
    )
    pte = dlg.findChild(QPlainTextEdit)
    pte.setPlainText("descricao com espacos")

    spy = QSignalSpy(dlg.submitted)
    dlg._on_confirm()
    assert spy.count() == 1
    assert spy.at(0)[0] == '/daily-loop "descricao com espacos"'
    dlg.deleteLater()


# ---------------------------------------------------------------------------
# Mode radio (cmd-single: "kimi analyse" | "kimi certain")
# ---------------------------------------------------------------------------


def _make_cmd_single_dialog():
    return DoublePhaseArgumentDialog(
        pipeline_name="/loop",
        fixed_flag="cmd-single",
        mode_radio=["kimi analyse", "kimi certain"],
        mode_radio_flags={"kimi analyse": "", "kimi certain": "--certain"},
        mode_radio_summaries={
            "kimi analyse": "par padrao",
            "kimi certain": "par forcado",
        },
    )


def test_mode_radio_renders_below_main_input(qapp):
    """cmd-single renderiza o radio de modo com 2 opcoes e testid proprio."""
    from workflow_app.command_queue.double_phase_dialog import RadioGroupWithSummary

    dlg = _make_cmd_single_dialog()
    radios = [
        w for w in dlg.findChildren(RadioGroupWithSummary)
        if w.property("testid") == "double-phase-mode-radio"
    ]
    assert len(radios) == 1
    assert radios[0].selected() == "kimi analyse"  # default = primeira opcao
    dlg.deleteLater()


def test_mode_radio_kimi_analyse_emits_no_extra_flag(qapp):
    """Default (kimi analyse) NAO acrescenta --certain ao comando."""
    dlg = _make_cmd_single_dialog()
    dlg._main_input.setPlainText("blacksmith/x.md")
    spy = QSignalSpy(dlg.submitted)
    dlg._on_confirm()
    assert spy.count() == 1
    line = spy.at(0)[0]
    assert line == "/loop --cmd-single blacksmith/x.md"
    assert "--certain" not in line
    dlg.deleteLater()


def test_mode_radio_kimi_certain_emits_certain_flag(qapp):
    """kimi certain acrescenta --certain apos o path."""
    dlg = _make_cmd_single_dialog()
    dlg._main_input.setPlainText("blacksmith/x.md")
    dlg._mode_radio_widget._buttons[1].setChecked(True)
    assert dlg._mode_radio_widget.selected() == "kimi certain"
    spy = QSignalSpy(dlg.submitted)
    dlg._on_confirm()
    assert spy.count() == 1
    line = spy.at(0)[0]
    assert line == "/loop --cmd-single blacksmith/x.md --certain"
    dlg.deleteLater()
