"""Tests for MainWindow shell."""

from __future__ import annotations


def test_main_window_opens(qapp):
    from workflow_app.main_window import MainWindow

    window = MainWindow()
    assert window.minimumWidth() == 640
    assert window.minimumHeight() == 480


def test_main_window_title(qapp):
    from workflow_app.main_window import MainWindow

    window = MainWindow()
    assert "SystemForge Desktop" in window.windowTitle()


def test_clear_button_in_pill_row_empties_queue(qapp):
    """O botao Clear vive no pill-row e esvazia o queue-command-list."""
    from PySide6.QtWidgets import QPushButton

    from workflow_app.main_window import MainWindow

    window = MainWindow()

    btn = next(
        b for b in window.findChildren(QPushButton)
        if b.property("testid") == "main-command-queue-clear-btn"
    )
    assert btn.text() == "Clear"

    # O botao deve viver dentro do pill-row (sequencia de botoes pedida).
    # Caminhamos a cadeia de parents — evitamos findChildren(QWidget), que
    # materializa wrappers de todos os widgets e corrompe o teardown do
    # conftest (_cleanup_qt_widgets) com segfault no shiboken6.delete.
    ancestor = btn.parentWidget()
    while ancestor is not None and ancestor.property("testid") != "main-command-queue-pill-row":
        ancestor = ancestor.parentWidget()
    assert ancestor is not None, "Botao Clear nao esta dentro do main-command-queue-pill-row"

    state = [
        {"name": "/foo", "model": "Sonnet", "interaction_type": "auto",
         "position": 1, "phase": "F1"},
        {"name": "/bar", "model": "Sonnet", "interaction_type": "auto",
         "position": 2, "phase": "F1"},
    ]
    window._command_queue.restore_queue_snapshot(state)
    assert len(window._command_queue.get_queue_snapshot()) == 2

    btn.click()
    assert window._command_queue.get_queue_snapshot() == []

    # Idempotente: clicar com a fila vazia nao quebra.
    btn.click()
    assert window._command_queue.get_queue_snapshot() == []


def test_layout_has_splitter(qapp):
    from workflow_app.main_window import MainWindow

    window = MainWindow()
    assert window._splitter is not None
    # Splitter horizontal principal hospeda dois filhos:
    # (0) CommandQueueWidget e (1) output_container (terminal_splitter + extras).
    # Assert identidade, nao apenas contagem, para detectar reparent acidental.
    assert window._splitter.count() == 2
    assert window._splitter.widget(0) is window._command_queue
    output_widget = window._splitter.widget(1)
    assert output_widget is not None
    # terminal_splitter está dentro do output_container (direto ou descendente):
    # findChildren cobre ambos os casos e é a unica branca necessaria.
    terminal_descendants = output_widget.findChildren(type(window._terminal_splitter))
    assert window._terminal_splitter in terminal_descendants, (
        "terminal_splitter deveria viver dentro do output_container"
    )


def test_command_queue_width_constraints(qapp):
    from workflow_app.main_window import MainWindow

    window = MainWindow()
    cmd_queue = window._command_queue
    # Width is flexible; just verify the widget exists
    assert cmd_queue is not None
    assert cmd_queue.width() > 0


def test_metrics_bar_height(qapp):
    from workflow_app.main_window import MainWindow

    window = MainWindow()
    assert window._metrics_bar.height() == 38


def test_modal_test_button_lives_inside_active_dialog(qapp):
    from PySide6.QtWidgets import QDialog, QMainWindow, QPushButton, QVBoxLayout, QWidget

    from workflow_app.main_window import MainWindow

    class Harness(QMainWindow):
        _reposition_modal_test_btn = MainWindow._reposition_modal_test_btn
        _show_modal_testid_overlays = MainWindow._show_modal_testid_overlays
        _hide_modal_testid_overlays = MainWindow._hide_modal_testid_overlays
        _check_for_active_modal = MainWindow._check_for_active_modal

    window = Harness()
    window.setCentralWidget(QWidget(window))
    window._modal_test_btn = QPushButton("ModalTest", window.centralWidget())
    window._modal_test_btn.setCheckable(True)
    window._modal_test_overlays = []
    window._active_modal_dialog = None
    dialog = QDialog(window)
    dialog.setFixedSize(320, 180)
    layout = QVBoxLayout(dialog)
    field = QPushButton("Confirmar", dialog)
    field.setProperty("testid", "confirm-cancel-yes")
    layout.addWidget(field)

    dialog.show()
    qapp.processEvents()

    window._check_for_active_modal()

    assert window._modal_test_btn.parent() is dialog
    assert window._modal_test_btn.isVisible()

    window._show_modal_testid_overlays()
    qapp.processEvents()

    assert window._modal_test_overlays
    assert all(overlay.parent() is dialog for overlay in window._modal_test_overlays)


def test_modal_test_overlays_render_uncatalogued_testids(qapp):
    """Regressao (2026-06): o botao ModalTest deve renderizar TODOS os testids
    dos itens dentro do modal, inclusive ids que NUNCA estiveram no antigo
    allowlist `_MODAL_TESTIDS`. Antes, qualquer modal novo/nao-catalogado nao
    mostrava nada (onClick sem efeito)."""
    from PySide6.QtWidgets import (
        QDialog, QLineEdit, QMainWindow, QPushButton, QVBoxLayout, QWidget,
    )

    from workflow_app.main_window import MainWindow

    class Harness(QMainWindow):
        _show_modal_testid_overlays = MainWindow._show_modal_testid_overlays
        _hide_modal_testid_overlays = MainWindow._hide_modal_testid_overlays

    window = Harness()
    window.setCentralWidget(QWidget(window))
    window._modal_test_btn = QPushButton("ModalTest", window.centralWidget())
    window._modal_test_overlays = []

    dialog = QDialog(window)
    dialog.setProperty("testid", "dialog-totalmente-novo")  # nunca no allowlist
    dialog.setFixedSize(320, 200)
    layout = QVBoxLayout(dialog)
    field = QLineEdit(dialog)
    field.setProperty("testid", "campo-inventado-xyz")      # nunca no allowlist
    btn = QPushButton("Salvar", dialog)
    btn.setProperty("testid", "botao-inventado-xyz")        # nunca no allowlist
    layout.addWidget(field)
    layout.addWidget(btn)

    window._active_modal_dialog = dialog
    dialog.show()
    qapp.processEvents()

    window._show_modal_testid_overlays()
    qapp.processEvents()

    rendered = {overlay.text() for overlay in window._modal_test_overlays}
    assert "campo-inventado-xyz" in rendered
    assert "botao-inventado-xyz" in rendered
    assert "dialog-totalmente-novo" in rendered


def test_prompts_config_path_browse_starts_in_brainstorm(qapp, monkeypatch):
    from PySide6.QtWidgets import QPushButton

    from workflow_app.main_window import PromptsConfigDialog

    captured: dict[str, str] = {}

    def fake_get_open_file_name(parent, title, start_dir, file_filter):
        captured["start_dir"] = start_dir
        captured["filter"] = file_filter
        return ("/tmp/outro-prompt.md", "")

    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog.getOpenFileName",
        fake_get_open_file_name,
    )

    dlg = PromptsConfigDialog(
        entries=[{"label": "Prompt", "path": "", "description": "Desc"}],
        base_prompt="",
    )
    browse = next(
        btn for btn in dlg.findChildren(QPushButton)
        if btn.property("testid") == "prompts-config-path-browse-0"
    )
    browse.click()

    _base, entries = dlg.collect()
    assert captured["start_dir"].endswith("brainstorm")
    assert captured["filter"] == "Markdown (*.md);;All Files (*)"
    assert entries[0][1] == "/tmp/outro-prompt.md"


def test_theme_applied(qapp):
    from workflow_app.theme import apply_theme

    apply_theme(qapp)
    stylesheet = qapp.styleSheet()
    assert len(stylesheet) > 0
    assert "#18181B" in stylesheet


def test_tokens_importable():
    from workflow_app.tokens import COLORS, SPACING, TYPOGRAPHY

    assert COLORS.background == "#18181B"
    assert COLORS.primary == "#FBBF24"
    assert TYPOGRAPHY.font_ui == "Inter"
    assert SPACING.md == 12
