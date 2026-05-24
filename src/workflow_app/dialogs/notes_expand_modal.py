"""
NotesExpandModal — Editor expandido para o footer de anotacoes de cada terminal.

O footer de notas usa um QLineEdit (single-line) como preview compacto. Este
modal e o editor "real": abre com o texto atual, permite editar texto longo /
multilinha num QPlainTextEdit e devolve o resultado apenas quando o usuario
salva (accept). Cancelar descarta. O backing store continua sendo o QLineEdit
do footer — o caller faz `notes_input.setText(modal.text())` no accept.

Cada modal nasce ligado ao texto de uma instancia especifica de footer
(passado como `initial_text`), evitando vazamento de estado entre os dois
footers (terminal-interactive-notes e terminal-workspace-notes).
"""

from __future__ import annotations

from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QPlainTextEdit,
    QVBoxLayout,
)


class NotesExpandModal(QDialog):
    """Modal de visualizacao/edicao de uma anotacao de terminal."""

    def __init__(self, testid: str, initial_text: str = "", parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Anotacao")
        self.setProperty("testid", f"{testid}-expand-modal")
        self.setModal(True)
        self.setMinimumSize(560, 360)
        self._setup_ui(initial_text)

    def _setup_ui(self, initial_text: str) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 16, 20, 16)

        self._editor = QPlainTextEdit()
        self._editor.setProperty("testid", "notes-expand-editor")
        self._editor.setPlainText(initial_text)
        self._editor.setPlaceholderText("anotacoes")
        self._editor.setStyleSheet(
            "QPlainTextEdit {"
            "  color: #E4E4E7;"
            "  background-color: #18181B;"
            "  border: 1px solid #3F3F46;"
            "  border-radius: 4px;"
            "  font-size: 13px;"
            "  padding: 6px 8px;"
            "}"
            "QPlainTextEdit:focus { border-color: #52525B; }"
        )
        layout.addWidget(self._editor, stretch=1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save
            | QDialogButtonBox.StandardButton.Cancel
        )
        save_btn = buttons.button(QDialogButtonBox.StandardButton.Save)
        save_btn.setText("Salvar")
        save_btn.setProperty("testid", "notes-expand-save")
        save_btn.setStyleSheet(
            "QPushButton { background-color: #FBBF24; color: #18181B;"
            "  border: 1px solid #FBBF24; border-radius: 4px; padding: 6px 14px;"
            "  font-weight: 700; }"
            "QPushButton:hover { background-color: #F59E0B; }"
        )
        cancel_btn = buttons.button(QDialogButtonBox.StandardButton.Cancel)
        cancel_btn.setText("Cancelar")
        cancel_btn.setProperty("testid", "notes-expand-cancel")
        cancel_btn.setStyleSheet(
            "QPushButton { background-color: #3F3F46; color: #FAFAFA;"
            "  border: 1px solid #52525B; border-radius: 4px; padding: 6px 14px; }"
            "QPushButton:hover { background-color: #52525B; }"
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Ctrl+Enter salva (Esc ja cancela via QDialog default).
        save_shortcut = QShortcut(QKeySequence("Ctrl+Return"), self)
        save_shortcut.activated.connect(self.accept)
        save_shortcut_enter = QShortcut(QKeySequence("Ctrl+Enter"), self)
        save_shortcut_enter.activated.connect(self.accept)

        self._editor.setFocus()

    def text(self) -> str:
        """Texto editado (single-line do footer aceita \\n; caller decide uso)."""
        return self._editor.toPlainText()
