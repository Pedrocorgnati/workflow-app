"""Tests for the brainstorm `.md` picker (T2 / loop 05-21-implantation-tasklist-aba-brainstorm).

Cobertura dos 3 cenarios pytest-qt declarados na task como obrigatorios:

- Cenario 1: diretorio canonico ausente -> mkdir sucesso -> picker abre em
  blacksmith/brainstorm-mcp/ -> toast "Diretorio criado" emitido 1x.
- Cenario 2: mkdir lanca PermissionError via monkeypatch -> picker usa
  blacksmith/ -> toast warning unico.
- Cenario 3: getOpenFileName retorna path fora do repo -> self._brainstorm_md_path
  NAO muda, md_btn.setText NAO chamado, toast warning emitido.
"""

from __future__ import annotations

from pathlib import Path


def _find_md_btn(window):
    """Acha o QPushButton do picker via testid brainstorm-md-picker."""
    from PySide6.QtWidgets import QPushButton

    for btn in window.findChildren(QPushButton):
        if btn.property("testid") == "brainstorm-md-picker":
            return btn
    raise AssertionError("brainstorm-md-picker nao encontrado")


def _find_copy_path_btn(window):
    """Acha o QPushButton que copia o path selecionado pelo picker."""
    from PySide6.QtWidgets import QPushButton

    for btn in window.findChildren(QPushButton):
        if btn.property("testid") == "brainstorm-md-copy-path":
            return btn
    raise AssertionError("brainstorm-md-copy-path nao encontrado")


def _find_reader_btn(window):
    """Acha o QPushButton que abre o leitor/editor do .md selecionado."""
    from PySide6.QtWidgets import QPushButton

    for btn in window.findChildren(QPushButton):
        if btn.property("testid") == "brainstorm-md-reader-open":
            return btn
    raise AssertionError("brainstorm-md-reader-open nao encontrado")


def _find_gear_btn(window):
    """Acha o QPushButton de configuracao dos seeds brainstorm."""
    from PySide6.QtWidgets import QPushButton

    for btn in window.findChildren(QPushButton):
        if btn.property("testid") == "brainstorm-mcp-config-gear":
            return btn
    raise AssertionError("brainstorm-mcp-config-gear nao encontrado")


def _collect_toasts(request):
    """Conecta um slot a signal_bus.toast_requested e devolve a lista capturada.

    Desconecta ao fim do teste via request.addfinalizer (signals PySide6 nao
    permitem monkeypatch direto em .emit; usar .connect e o caminho idiomatico).
    """
    from workflow_app.signal_bus import signal_bus

    captured: list[tuple[str, str]] = []

    def slot(message: str, level: str) -> None:
        captured.append((message, level))

    signal_bus.toast_requested.connect(slot)
    request.addfinalizer(lambda: signal_bus.toast_requested.disconnect(slot))
    return captured


def test_picker_canonical_dir_created_emits_toast_once(qapp, monkeypatch, tmp_path, request):
    """Cenario 1: mkdir cria o diretorio canonico e emite toast info uma vez."""
    from workflow_app.main_window import MainWindow

    window = MainWindow()
    # Forcar raiz isolada em tmp_path para garantir que blacksmith/brainstorm-mcp
    # nao existe ainda. _systemforge_root e staticmethod; monkeypatch via type().
    monkeypatch.setattr(
        MainWindow, "_systemforge_root", staticmethod(lambda: tmp_path)
    )
    canonical = tmp_path / "blacksmith" / "brainstorm-mcp"
    target_md = canonical / "ideia.md"

    captured_dirs: list[str] = []

    def fake_get_open_file_name(parent, title, start_dir, file_filter):
        captured_dirs.append(start_dir)
        # Simula selecao: cria o arquivo apos o mkdir do picker.
        target_md.write_text("# nota\n", encoding="utf-8")
        return (str(target_md), "")

    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog.getOpenFileName",
        fake_get_open_file_name,
    )
    toasts = _collect_toasts(request)

    md_btn = _find_md_btn(window)
    md_btn.click()

    assert canonical.exists(), "mkdir do canonico falhou"
    assert captured_dirs == [str(canonical)]
    assert window._brainstorm_md_path == str(target_md)
    assert md_btn.text() == "ideia.md"
    info_toasts = [m for m, lvl in toasts if lvl == "info" and "Diretorio criado" in m]
    assert info_toasts == ["Diretorio criado: blacksmith/brainstorm-mcp/"]

    # Segundo clique: nao deve emitir toast de novo (idempotencia).
    target_md2 = canonical / "ideia2.md"

    def fake_get_open_file_name_2(parent, title, start_dir, file_filter):
        target_md2.write_text("# nota2\n", encoding="utf-8")
        return (str(target_md2), "")

    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog.getOpenFileName",
        fake_get_open_file_name_2,
    )
    md_btn.click()
    info_toasts_after = [m for m, lvl in toasts if lvl == "info" and "Diretorio criado" in m]
    assert info_toasts_after == ["Diretorio criado: blacksmith/brainstorm-mcp/"]


def test_copy_path_button_copies_selected_md_path(qapp, monkeypatch, tmp_path, request):
    """Botao 1:1 ao lado do picker copia o path completo do .md selecionado."""
    from workflow_app.main_window import MainWindow

    window = MainWindow()
    monkeypatch.setattr(
        MainWindow, "_systemforge_root", staticmethod(lambda: tmp_path)
    )
    canonical = tmp_path / "blacksmith" / "brainstorm-mcp"
    target_md = canonical / "ideia.md"

    def fake_get_open_file_name(parent, title, start_dir, file_filter):
        target_md.write_text("# nota\n", encoding="utf-8")
        return (str(target_md), "")

    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog.getOpenFileName",
        fake_get_open_file_name,
    )
    toasts = _collect_toasts(request)

    md_btn = _find_md_btn(window)
    copy_btn = _find_copy_path_btn(window)
    assert copy_btn.width() == 24
    assert copy_btn.height() == 24

    md_btn.click()
    qapp.clipboard().clear()
    copy_btn.click()

    assert qapp.clipboard().text() == str(target_md)
    info_toasts = [
        m for m, lvl in toasts
        if lvl == "info" and "Path do .md copiado" in m
    ]
    assert info_toasts == ["Path do .md copiado para a area de transferencia."]


def test_reader_button_sits_between_copy_and_config_buttons(qapp):
    """Botao olho fica entre copiar path e configuracao no row do picker."""
    from workflow_app.main_window import MainWindow

    window = MainWindow()
    picker_row = window._brainstorm_md_btn.parentWidget()
    layout = picker_row.layout()

    copy_btn = _find_copy_path_btn(window)
    reader_btn = _find_reader_btn(window)
    gear_btn = _find_gear_btn(window)

    assert reader_btn.width() == 24
    assert reader_btn.height() == 24
    assert layout.indexOf(copy_btn) < layout.indexOf(reader_btn) < layout.indexOf(gear_btn)


def test_reader_button_without_selection_emits_warning(qapp, request):
    """Clique no olho sem .md selecionado nao abre dialog e mostra feedback."""
    from workflow_app.main_window import MainWindow

    window = MainWindow()
    toasts = _collect_toasts(request)

    _find_reader_btn(window).click()

    warning_toasts = [
        m for m, lvl in toasts
        if lvl == "warning" and "Nenhum arquivo .md selecionado" in m
    ]
    assert warning_toasts == ["Nenhum arquivo .md selecionado para abrir no leitor."]


def test_reader_button_opens_dialog_for_selected_md(qapp, monkeypatch, tmp_path):
    """Clique no olho abre BrainstormMdReaderDialog com o path selecionado."""
    from workflow_app.main_window import MainWindow

    selected_md = tmp_path / "repo" / "blacksmith" / "brainstorm-mcp" / "ideia.md"
    selected_md.parent.mkdir(parents=True)
    selected_md.write_text("# Ideia\n", encoding="utf-8")

    opened: list[str] = []

    class FakeDialog:
        def __init__(self, md_path, parent=None):
            opened.append(str(md_path))
            self.parent = parent

        def exec(self):
            return 1

    monkeypatch.setattr(
        "workflow_app.widgets.brainstorm_md_reader_dialog.BrainstormMdReaderDialog",
        FakeDialog,
    )

    window = MainWindow()
    window._brainstorm_md_path = str(selected_md)
    _find_reader_btn(window).click()

    assert opened == [str(selected_md)]


def test_brainstorm_md_reader_dialog_edits_selected_file(qapp, qtbot, tmp_path):
    """Dialog usa MarkdownReader do task-manager-desktop e salva o .md em disco."""
    from workflow_app.widgets.brainstorm_md_reader_dialog import BrainstormMdReaderDialog

    md_path = tmp_path / "ideia.md"
    md_path.write_text("# Original\n", encoding="utf-8")

    dlg = BrainstormMdReaderDialog(md_path)
    qtbot.addWidget(dlg)

    assert dlg.property("testid") == "brainstorm-md-reader-dialog"
    assert dlg._reader.property("testid") == "brainstorm-md-reader"
    assert "# Original" in dlg._reader._editor.toPlainText()

    dlg._reader._editor.setPlainText("# Editado\n")
    dlg._save_btn.click()

    assert md_path.read_text(encoding="utf-8") == "# Editado\n"


def test_picker_mkdir_permission_error_falls_back_to_blacksmith(
    qapp, monkeypatch, tmp_path, request
):
    """Cenario 2: PermissionError no mkdir -> fallback blacksmith/ + toast warning unico."""
    from workflow_app.main_window import MainWindow

    window = MainWindow()
    monkeypatch.setattr(
        MainWindow, "_systemforge_root", staticmethod(lambda: tmp_path)
    )
    fallback_dir = tmp_path / "blacksmith"
    fallback_dir.mkdir(parents=True)
    fallback_md = fallback_dir / "x.md"
    fallback_md.write_text("# x\n", encoding="utf-8")

    original_mkdir = Path.mkdir

    def patched_mkdir(self, *args, **kwargs):
        # Bloquear somente o canonical exato; deixar tmp_path/blacksmith funcionar.
        if self.name == "brainstorm-mcp" and self.parent.name == "blacksmith":
            raise PermissionError(13, "Permission denied")
        return original_mkdir(self, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", patched_mkdir)

    captured_dirs: list[str] = []

    def fake_get_open_file_name(parent, title, start_dir, file_filter):
        captured_dirs.append(start_dir)
        return (str(fallback_md), "")

    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog.getOpenFileName",
        fake_get_open_file_name,
    )
    toasts = _collect_toasts(request)

    md_btn = _find_md_btn(window)
    md_btn.click()

    assert captured_dirs == [str(fallback_dir)]
    warning_toasts = [
        m for m, lvl in toasts
        if lvl == "warning" and "Diretorio canonico indisponivel" in m
    ]
    assert len(warning_toasts) == 1

    # Segundo clique reproduz fallback mas NAO emite toast de novo.
    md_btn.click()
    warning_toasts_after = [
        m for m, lvl in toasts
        if lvl == "warning" and "Diretorio canonico indisponivel" in m
    ]
    assert len(warning_toasts_after) == 1


def test_picker_outside_repo_rejected(qapp, monkeypatch, tmp_path, request):
    """Cenario 3: path fora do repo rejeitado, estado anterior preservado."""
    from workflow_app.main_window import MainWindow

    window = MainWindow()
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    monkeypatch.setattr(
        MainWindow, "_systemforge_root", staticmethod(lambda: repo_root)
    )

    outside_dir = tmp_path / "outside"
    outside_dir.mkdir()
    outside_md = outside_dir / "external.md"
    outside_md.write_text("# fora\n", encoding="utf-8")

    def fake_get_open_file_name(parent, title, start_dir, file_filter):
        return (str(outside_md), "")

    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog.getOpenFileName",
        fake_get_open_file_name,
    )
    toasts = _collect_toasts(request)

    md_btn = _find_md_btn(window)
    text_before = md_btn.text()
    path_before = window._brainstorm_md_path
    md_btn.click()

    # Estado preservado: nem _brainstorm_md_path nem md_btn.text mudaram.
    assert window._brainstorm_md_path == path_before
    assert md_btn.text() == text_before
    warning_toasts = [
        m for m, lvl in toasts
        if lvl == "warning" and "fora do repositorio" in m
    ]
    assert len(warning_toasts) == 1

    # Mesmo path repetido nao deve emitir novamente (dedup por outside_repo).
    md_btn.click()
    warning_toasts_after = [
        m for m, lvl in toasts
        if lvl == "warning" and "fora do repositorio" in m
    ]
    assert len(warning_toasts_after) == 1


def test_picker_cancel_preserves_existing_selection(qapp, monkeypatch, tmp_path):
    """Cancelamento do QFileDialog nao altera path, texto nem tooltip atuais."""
    from workflow_app.main_window import MainWindow

    window = MainWindow()
    repo_root = tmp_path / "repo"
    selected_md = repo_root / "blacksmith" / "brainstorm-mcp" / "selecionado.md"
    selected_md.parent.mkdir(parents=True)
    selected_md.write_text("# selecionado\n", encoding="utf-8")
    monkeypatch.setattr(
        MainWindow, "_systemforge_root", staticmethod(lambda: repo_root)
    )

    def first_selection(parent, title, start_dir, file_filter):
        return (str(selected_md), "")

    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog.getOpenFileName",
        first_selection,
    )

    md_btn = _find_md_btn(window)
    md_btn.click()

    assert window._brainstorm_md_path == str(selected_md)
    assert md_btn.text() == "selecionado.md"
    assert md_btn.toolTip() == str(selected_md)

    def cancelled(parent, title, start_dir, file_filter):
        return ("", "")

    monkeypatch.setattr(
        "PySide6.QtWidgets.QFileDialog.getOpenFileName",
        cancelled,
    )
    md_btn.click()

    assert window._brainstorm_md_path == str(selected_md)
    assert md_btn.text() == "selecionado.md"
    assert md_btn.toolTip() == str(selected_md)
