"""
BoilerplatePathDialog — Modal para capturar o caminho do repositorio legado
que sera convertido em boilerplate via /auto-flow boilerplate.

Diferente dos demais botoes do CommandQueueWidget, o pipeline boilerplate nao
le project.json (metrics-project-pill). O usuario cola aqui o caminho do repo
(ex: output/workspace/free-sites/marciosantosadvogado.com) e este path vira o
argumento do /boilerplate:scan; os 8 passos seguintes recebem o staging path
derivado (output/boilerplates/_staging/{basename}).
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)


class BoilerplatePathDialog(QDialog):
    """Modal simples QLineEdit + Submit para capturar o repo path."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Boilerplate — Repo Path")
        self.setModal(True)
        self.setFixedSize(560, 220)
        self._repo_path = ""
        self._setup_ui()

    @property
    def repo_path(self) -> str:
        """Repo path normalizado (expanduser aplicado, trailing slash removido)."""
        return self._repo_path

    def _setup_ui(self) -> None:
        self.setStyleSheet("background-color: #18181B;")

        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(24, 20, 24, 20)

        title = QLabel("Caminho do repositorio legado")
        title.setStyleSheet("color: #FAFAFA; font-size: 14px; font-weight: bold;")
        layout.addWidget(title)

        subtitle = QLabel(
            "Cole o path do repo a ser convertido em boilerplate.\n"
            "Ex: output/workspace/free-sites/marciosantosadvogado.com"
        )
        subtitle.setStyleSheet("color: #A1A1AA; font-size: 11px;")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        self._input = QLineEdit()
        self._input.setPlaceholderText(
            "output/workspace/free-sites/algum-site.com"
        )
        self._input.setStyleSheet(
            "background-color: #3F3F46; color: #FAFAFA;"
            " border: 1px solid #52525B; border-radius: 4px;"
            " padding: 6px 10px; font-size: 13px; font-family: monospace;"
        )
        self._input.setFixedHeight(38)
        self._input.textChanged.connect(self._on_text_changed)
        self._input.returnPressed.connect(self._on_confirm)
        layout.addWidget(self._input)

        self._error_label = QLabel("")
        self._error_label.setStyleSheet("color: #F87171; font-size: 10px;")
        self._error_label.setFixedHeight(14)
        layout.addWidget(self._error_label)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()

        btn_cancel = QPushButton("Cancelar")
        btn_cancel.setFixedHeight(32)
        btn_cancel.setStyleSheet(
            "QPushButton { background-color: #3F3F46; color: #A1A1AA;"
            "  border: 1px solid #52525B; border-radius: 4px;"
            "  padding: 0 16px; font-size: 12px; }"
            "QPushButton:hover { background-color: #52525B; color: #FAFAFA; }"
        )
        btn_cancel.clicked.connect(self.reject)
        btn_row.addWidget(btn_cancel)

        self._btn_confirm = QPushButton("Submit")
        self._btn_confirm.setProperty("testid", "boilerplate-path-submit")
        self._btn_confirm.setFixedHeight(32)
        self._btn_confirm.setEnabled(False)
        self._btn_confirm.setStyleSheet(
            "QPushButton { background-color: #166534; color: #FAFAFA;"
            "  border: none; border-radius: 4px;"
            "  padding: 0 16px; font-size: 12px; font-weight: 700; }"
            "QPushButton:hover { background-color: #15803D; }"
            "QPushButton:disabled { background-color: #3F3F46; color: #52525B; }"
        )
        self._btn_confirm.clicked.connect(self._on_confirm)
        btn_row.addWidget(self._btn_confirm)

        layout.addLayout(btn_row)

    # ── Slots ── #

    def _validate(self, normalized: str) -> tuple[bool, str]:
        """Retorna (is_valid, error_msg). Bloqueia paths traversal-equivalente."""
        if not normalized:
            return (False, "")
        try:
            p = Path(normalized).expanduser()
        except (OSError, RuntimeError):
            return (False, "Path invalido.")
        basename = p.name
        if not basename or basename in {".", ".."}:
            return (False, "Basename invalido (use o caminho do diretorio do repo).")
        return (True, "")

    def _on_text_changed(self, text: str) -> None:
        normalized = text.strip().rstrip("/")
        is_valid, err = self._validate(normalized)
        self._btn_confirm.setEnabled(is_valid)

        _base = (
            "background-color: #3F3F46; color: #FAFAFA;"
            " border-radius: 4px; padding: 6px 10px;"
            " font-size: 13px; font-family: monospace;"
        )
        if not normalized:
            self._error_label.setText("")
            self._input.setStyleSheet(f"{_base} border: 1px solid #52525B;")
        elif is_valid:
            self._error_label.setText("")
            self._input.setStyleSheet(f"{_base} border: 1px solid #22C55E;")
        else:
            self._error_label.setText(err)
            self._input.setStyleSheet(f"{_base} border: 1px solid #EF4444;")

    def _on_confirm(self) -> None:
        if not self._btn_confirm.isEnabled():
            return
        raw = self._input.text().strip().rstrip("/")
        is_valid, _ = self._validate(raw)
        if not is_valid:
            return
        # Expanduser para suportar ~ — mantem relativo se for relativo,
        # absolutiza se comecar com ~ ou for absoluto.
        self._repo_path = str(Path(raw).expanduser())
        self.accept()
