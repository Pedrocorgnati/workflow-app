from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


def _ensure_task_manager_desktop_importable() -> None:
    ai_forge_root = Path(__file__).resolve().parents[4]
    task_manager_root = ai_forge_root / "task-manager-desktop"
    if str(task_manager_root) not in sys.path:
        sys.path.insert(0, str(task_manager_root))


class BrainstormMdReaderDialog(QDialog):
    """Modal para ler e editar o .md selecionado no brainstorm-md-picker."""

    def __init__(self, md_path: str | Path, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _ensure_task_manager_desktop_importable()
        from task_manager_desktop.ui.markdown_reader import MarkdownReader

        self._md_path = Path(md_path)
        self.setProperty("testid", "brainstorm-md-reader-dialog")
        self.setWindowTitle(self._md_path.name)
        self.setModal(True)
        self.resize(980, 720)

        self._reader = MarkdownReader(repo=None, parent=self)
        self._reader.setProperty("testid", "brainstorm-md-reader")
        self._reader.show_document(str(self._md_path))

        mode_row = QWidget(self)
        mode_row.setProperty("testid", "brainstorm-md-reader-mode-row")
        mode_layout = QHBoxLayout(mode_row)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.setSpacing(6)

        self._preview_btn = QPushButton("Preview", self)
        self._preview_btn.setProperty("testid", "brainstorm-md-reader-preview")
        self._preview_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._edit_btn = QPushButton("Editar", self)
        self._edit_btn.setProperty("testid", "brainstorm-md-reader-edit")
        self._edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        mode_layout.addStretch(1)
        mode_layout.addWidget(self._preview_btn)
        mode_layout.addWidget(self._edit_btn)

        self._buttons = QDialogButtonBox(self)
        self._save_btn = self._buttons.addButton("Salvar", QDialogButtonBox.ButtonRole.ApplyRole)
        self._save_btn.setProperty("testid", "brainstorm-md-reader-save")
        self._close_btn = self._buttons.addButton(QDialogButtonBox.StandardButton.Close)
        self._close_btn.setProperty("testid", "brainstorm-md-reader-close")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        layout.addWidget(mode_row)
        layout.addWidget(self._reader, 1)
        layout.addWidget(self._buttons)

        self._preview_btn.clicked.connect(self._show_preview)
        self._edit_btn.clicked.connect(self._show_editor)
        self._save_btn.clicked.connect(self._reader._on_save_clicked)
        self._close_btn.clicked.connect(self.accept)
        self._show_editor()

    def _show_preview(self) -> None:
        text = self._reader._editor.toPlainText()
        self._reader._pane._viewer.set_document(text, is_markdown=True)
        self._reader._stack.setCurrentIndex(self._reader._IDX_VIEWER)

    def _show_editor(self) -> None:
        self._reader._stack.setCurrentIndex(self._reader._IDX_EDITOR)
        self._reader._editor.setFocus(Qt.FocusReason.ShortcutFocusReason)
