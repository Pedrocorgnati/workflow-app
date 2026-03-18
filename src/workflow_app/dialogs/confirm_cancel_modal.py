"""
ConfirmCancelModal — Confirmation dialog before cancelling the pipeline.

Displayed when the user clicks "Cancelar Pipeline" in the error row of a
CommandItemWidget. Requires explicit confirmation before calling
PipelineManager.cancel().
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
)


class ConfirmCancelModal(QDialog):
    """Modal confirmation dialog for pipeline cancellation."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Cancelar Pipeline")
        self.setModal(True)
        self.setMinimumWidth(360)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 20, 24, 20)

        label = QLabel(
            "Tem certeza que deseja cancelar o pipeline?\n\n"
            "O comando atual será interrompido e todos os comandos\n"
            "pendentes serão descartados. Esta ação não pode ser desfeita."
        )
        label.setWordWrap(True)
        label.setAlignment(Qt.AlignmentFlag.AlignLeft)
        label.setStyleSheet("color: #F4F4F5; font-size: 13px;")
        layout.addWidget(label)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No
        )
        yes_btn = buttons.button(QDialogButtonBox.StandardButton.Yes)
        yes_btn.setText("Cancelar Pipeline")
        yes_btn.setStyleSheet(
            "QPushButton { background-color: #7F1D1D; color: #FCA5A5;"
            "  border: 1px solid #991B1B; border-radius: 4px; padding: 6px 14px; }"
            "QPushButton:hover { background-color: #991B1B; }"
        )
        no_btn = buttons.button(QDialogButtonBox.StandardButton.No)
        no_btn.setText("Voltar")
        no_btn.setStyleSheet(
            "QPushButton { background-color: #3F3F46; color: #FAFAFA;"
            "  border: 1px solid #52525B; border-radius: 4px; padding: 6px 14px; }"
            "QPushButton:hover { background-color: #52525B; }"
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
