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
    QPushButton,
)

from workflow_app.command_queue.double_phase_dialog import (
    SLUG_RE,
    AutoGrowTextEdit,
    DoublePhaseArgumentDialog,
    PathMdFieldWidget,
    RadioGroupWithSummary,
    _parse_argument_hint,
)

STUDY_HINT = (
    '"<duvida>" [path.md] [--loop <path.md>] [--name <slug>] '
    "[--simple|--deep|--heavy]"
)


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


def test_parser_full_study_hint_now_with_loop():
    """Hint canonico do queue-btn-study apos task-021: 5 tokens.

    `[--loop <path.md>]` vira `checkbox_with_path_md`; demais kinds preservados.
    """
    tokens = _parse_argument_hint(STUDY_HINT)
    kinds = [t.kind for t in tokens]
    assert kinds == [
        "freetext",
        "input",
        "checkbox_with_path_md",
        "checkbox_with_value",
        "enum_flag",
    ]
    # checkbox_with_path_md carrega flag em .key (sem placeholder em .options).
    cbp = tokens[2]
    assert cbp.key == "--loop"
    # checkbox_with_value carrega flag em .key e placeholder em .options[0].
    cbv = tokens[3]
    assert cbv.key == "--name"
    assert cbv.options == ["slug"]


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
    """Hint canonico (com --loop) instancia 1 freetext, 1 input, 1 path picker,
    2 checkboxes (--loop + --name) e 1 enum_flag.
    """
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
    # QLineEdits: line interno de [path.md] + line interno de [--loop <path.md>]
    # + line do checkbox_with_value ([--name <slug>]). Total 3.
    assert len(dlg.findChildren(QLineEdit)) == 3
    # 2 checkboxes: --loop + --name.
    assert len(dlg.findChildren(QCheckBox)) == 2
    # 2 PathMdFieldWidget: [path.md] e [--loop <path.md>].
    assert len(dlg.findChildren(PathMdFieldWidget)) == 2
    rgs = dlg.findChildren(RadioGroupWithSummary)
    assert len(rgs) == 1
    assert rgs[0].button_group().exclusive() is True
    dlg.deleteLater()


# ---------------------------------------------------------------------------
# task-021: checkbox_with_path_md ([--flag <path.md>] / [--flag <path>])
# ---------------------------------------------------------------------------


def test_parser_checkbox_with_path_md_detects_kind():
    """[--loop <path.md>] vira checkbox_with_path_md com key=--loop."""
    tokens = _parse_argument_hint("[--loop <path.md>]")
    assert len(tokens) == 1
    assert tokens[0].kind == "checkbox_with_path_md"
    assert tokens[0].key == "--loop"


def test_parser_checkbox_with_path_md_accepts_short_path_placeholder():
    """[--loop <path>] (sem .md) tambem vira checkbox_with_path_md."""
    tokens = _parse_argument_hint("[--loop <path>]")
    assert len(tokens) == 1
    assert tokens[0].kind == "checkbox_with_path_md"
    assert tokens[0].key == "--loop"


def test_parser_path_md_legacy_still_works():
    """[--tasklist <path.md>] -> checkbox_with_path_md (novo); [path.md] sem
    -- continua caindo em input (regressao do parser preservada).
    """
    tokens = _parse_argument_hint("[path.md]")
    assert len(tokens) == 1
    # [path.md] nao tem '<>' nem '--' prefix -> input simples (regra atual).
    assert tokens[0].kind == "input"


def test_render_input_path_md_uses_picker_button(qapp):
    """[path.md] renderiza row com input e botao de lupa."""
    dlg = DoublePhaseArgumentDialog(
        pipeline_name="/study",
        argument_hint="[path.md]",
        default_md_dir="",
        radio_summaries={},
    )
    pws = dlg.findChildren(PathMdFieldWidget)
    assert len(pws) == 1
    buttons = pws[0].findChildren(QPushButton)
    assert buttons[0].text() == "🔍"
    assert buttons[0].property("testid") == "double-phase-path-md-browse"
    dlg.deleteLater()


def test_path_md_browse_starts_in_brainstorm_and_sets_path(qapp, monkeypatch):
    """Picker abre em brainstorm como atalho, mas continua QFileDialog normal."""
    captured: dict[str, str] = {}

    def fake_get_open_file_name(parent, title, start_dir, file_filter):
        captured["start_dir"] = start_dir
        captured["filter"] = file_filter
        return ("/tmp/outro-lugar/task.md", "")

    monkeypatch.setattr(
        "workflow_app.command_queue.double_phase_dialog.QFileDialog.getOpenFileName",
        fake_get_open_file_name,
    )
    pw = PathMdFieldWidget(default_md_dir="")
    pw._browse()

    assert captured["start_dir"].endswith("brainstorm")
    assert captured["filter"] == "Markdown (*.md);;All Files (*)"
    assert pw.text() == "/tmp/outro-lugar/task.md"
    pw.deleteLater()


def test_confirm_checkbox_with_path_md_emits_flag_value(qapp):
    """Checkbox marcado + path nao vazio -> '--loop {path}' no comando final."""
    dlg = DoublePhaseArgumentDialog(
        pipeline_name="/study",
        argument_hint="[--loop <path.md>]",
        default_md_dir="",
        radio_summaries={},
    )
    chks = dlg.findChildren(QCheckBox)
    assert len(chks) == 1
    pws = dlg.findChildren(PathMdFieldWidget)
    assert len(pws) == 1
    chk = chks[0]
    pw = pws[0]

    chk.setChecked(True)
    pw.set_text("foo.md")

    spy = QSignalSpy(dlg.submitted)
    dlg._on_confirm()
    assert spy.count() == 1
    assert spy.at(0)[0] == "/study --loop foo.md"
    dlg.deleteLater()


def test_confirm_checkbox_with_path_md_quotes_path_with_spaces(qapp):
    """Path com espaco e quoted no comando final."""
    dlg = DoublePhaseArgumentDialog(
        pipeline_name="/study",
        argument_hint="[--loop <path.md>]",
        default_md_dir="",
        radio_summaries={},
    )
    chk = dlg.findChild(QCheckBox)
    pw = dlg.findChild(PathMdFieldWidget)
    chk.setChecked(True)
    pw.set_text("minha pasta/foo.md")

    spy = QSignalSpy(dlg.submitted)
    dlg._on_confirm()
    assert spy.at(0)[0] == '/study --loop "minha pasta/foo.md"'
    dlg.deleteLater()


def test_confirm_checkbox_with_path_md_empty_blocks_submit(qapp):
    """Checkbox marcado + picker vazio -> submit bloqueado (task-022 AC1).

    Comportamento anterior emitia '/study --loop' graceful; agora a lane
    de validacao bloqueia submit porque `/study --loop` exige path.
    """
    dlg = DoublePhaseArgumentDialog(
        pipeline_name="/study",
        argument_hint="[--loop <path.md>]",
        default_md_dir="",
        radio_summaries={},
    )
    chk = dlg.findChild(QCheckBox)
    chk.setChecked(True)

    spy = QSignalSpy(dlg.submitted)
    dlg._on_confirm()
    assert spy.count() == 0
    assert dlg._btn_confirm is not None
    assert dlg._btn_confirm.isEnabled() is False
    dlg.deleteLater()


def test_confirm_checkbox_with_path_md_unchecked_omits_flag(qapp):
    """Checkbox desmarcado -> --loop ausente do comando final."""
    dlg = DoublePhaseArgumentDialog(
        pipeline_name="/study",
        argument_hint="[--loop <path.md>]",
        default_md_dir="",
        radio_summaries={},
    )
    pw = dlg.findChild(PathMdFieldWidget)
    pw.set_text("foo.md")

    spy = QSignalSpy(dlg.submitted)
    dlg._on_confirm()
    assert spy.at(0)[0] == "/study"
    dlg.deleteLater()


def test_render_checkbox_with_path_md_picker_hidden_until_toggle(qapp):
    """PathMdFieldWidget comeca oculto; ao marcar checkbox, fica visivel."""
    dlg = DoublePhaseArgumentDialog(
        pipeline_name="/study",
        argument_hint="[--loop <path.md>]",
        default_md_dir="",
        radio_summaries={},
    )
    chk = dlg.findChild(QCheckBox)
    pw = dlg.findChild(PathMdFieldWidget)
    # Estado inicial: picker oculto.
    assert pw.isVisible() is False
    # Marca: picker fica visivel (apos show do dialog).
    dlg.show()
    qapp.processEvents()
    chk.setChecked(True)
    qapp.processEvents()
    assert pw.isVisible() is True
    # Desmarca: oculta de novo, texto preservado.
    pw.set_text("foo.md")
    chk.setChecked(False)
    qapp.processEvents()
    assert pw.isVisible() is False
    assert pw.text() == "foo.md"
    dlg.deleteLater()


# ---------------------------------------------------------------------------
# task-022: lane de validacao no modal (AC1, AC2, AC3, AC7d)
# ---------------------------------------------------------------------------

STUDY_VALIDATION_HINT = "[--loop <path.md>] [--name <slug>]"


def test_validation_slug_re_accepts_valid_kebab_case():
    """SLUG_RE casa kebab-case minusculo 1-50 chars."""
    assert SLUG_RE.match("foo")
    assert SLUG_RE.match("foo-bar")
    assert SLUG_RE.match("05-15-study-flow-upgrade")
    assert SLUG_RE.match("a" * 50)
    # Rejeita uppercase, espaco, prefixo invalido, > 50 chars.
    assert SLUG_RE.match("Foo") is None
    assert SLUG_RE.match("foo bar") is None
    assert SLUG_RE.match("-foo") is None
    assert SLUG_RE.match("a" * 51) is None


def test_validation_blocks_submit_when_loop_path_empty(qapp):
    """AC1: --loop marcado + path vazio -> submit bloqueado + label visivel."""
    dlg = DoublePhaseArgumentDialog(
        pipeline_name="/study",
        argument_hint=STUDY_VALIDATION_HINT,
        default_md_dir="",
        radio_summaries={},
    )
    chks = dlg.findChildren(QCheckBox)
    chk_loop = next(c for c in chks if "--loop" in c.text())
    chk_loop.setChecked(True)

    spy = QSignalSpy(dlg.submitted)
    dlg._on_confirm()
    assert spy.count() == 0
    assert dlg._btn_confirm is not None
    assert dlg._btn_confirm.isEnabled() is False
    # Label do --loop renderizada e visivel (chave: indice do token --loop).
    loop_idx = next(
        i for i, tok in enumerate(dlg._tokens)
        if tok.kind == "checkbox_with_path_md" and tok.key == "--loop"
    )
    err_lbl = dlg._error_labels[loop_idx]
    # `isVisible` requer ancestor visivel; usar `isHidden`+text para
    # validar que a label foi tornada visivel logicamente.
    assert err_lbl.isHidden() is False
    assert "path .md exigido" in err_lbl.text()
    dlg.deleteLater()


def test_validation_blocks_submit_when_name_slug_invalid(qapp):
    """AC2: --name marcado + slug invalido -> submit bloqueado + label visivel."""
    dlg = DoublePhaseArgumentDialog(
        pipeline_name="/study",
        argument_hint=STUDY_VALIDATION_HINT,
        default_md_dir="",
        radio_summaries={},
    )
    chks = dlg.findChildren(QCheckBox)
    chk_name = next(c for c in chks if "--name" in c.text())
    chk_name.setChecked(True)
    # Encontra o QLineEdit do --name (kind checkbox_with_value).
    name_idx = next(
        i for i, tok in enumerate(dlg._tokens)
        if tok.kind == "checkbox_with_value" and tok.key == "--name"
    )
    _chk, edit = dlg._widgets[name_idx]
    edit.setText("Foo Bar")  # Caracteres invalidos (uppercase + espaco).

    spy = QSignalSpy(dlg.submitted)
    dlg._on_confirm()
    assert spy.count() == 0
    assert dlg._btn_confirm is not None
    assert dlg._btn_confirm.isEnabled() is False
    err_lbl = dlg._error_labels[name_idx]
    assert err_lbl.isHidden() is False
    assert "slug exigido" in err_lbl.text()
    dlg.deleteLater()


def test_validation_enables_submit_when_all_valid(qapp):
    """AC3: ambos validos -> submit habilitado e emite comando."""
    dlg = DoublePhaseArgumentDialog(
        pipeline_name="/study",
        argument_hint=STUDY_VALIDATION_HINT,
        default_md_dir="",
        radio_summaries={},
    )
    chks = dlg.findChildren(QCheckBox)
    chk_loop = next(c for c in chks if "--loop" in c.text())
    chk_name = next(c for c in chks if "--name" in c.text())
    chk_loop.setChecked(True)
    chk_name.setChecked(True)

    loop_idx = next(
        i for i, tok in enumerate(dlg._tokens)
        if tok.kind == "checkbox_with_path_md" and tok.key == "--loop"
    )
    name_idx = next(
        i for i, tok in enumerate(dlg._tokens)
        if tok.kind == "checkbox_with_value" and tok.key == "--name"
    )
    _, pw = dlg._widgets[loop_idx]
    pw.set_text("foo.md")
    _, edit = dlg._widgets[name_idx]
    edit.setText("valid-slug")

    assert dlg._btn_confirm is not None
    assert dlg._btn_confirm.isEnabled() is True

    spy = QSignalSpy(dlg.submitted)
    dlg._on_confirm()
    assert spy.count() == 1
    assert spy.at(0)[0] == "/study --loop foo.md --name valid-slug"
    dlg.deleteLater()


def test_validation_no_errors_when_checkboxes_unchecked(qapp):
    """AC7d: nenhum checkbox marcado -> botao habilitado mesmo com edits vazios."""
    dlg = DoublePhaseArgumentDialog(
        pipeline_name="/study",
        argument_hint=STUDY_VALIDATION_HINT,
        default_md_dir="",
        radio_summaries={},
    )
    # Nenhum checkbox marcado por default.
    assert dlg._btn_confirm is not None
    assert dlg._btn_confirm.isEnabled() is True
    spy = QSignalSpy(dlg.submitted)
    dlg._on_confirm()
    assert spy.count() == 1
    assert spy.at(0)[0] == "/study"
    dlg.deleteLater()
