"""
PermissionRequestDialog — Dialog shown when the SDK requests user permission
to perform an action (e.g. write file, execute command) in manual mode.

Signals:
  permission_granted   — emitted when user clicks "Permitir"
  permission_rejected  — emitted when user clicks "Rejeitar"
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)


class PermissionRequestDialog(QDialog):
    """Modal dialog for SDK permission requests in manual permission mode."""

    permission_granted = Signal()
    permission_rejected = Signal()

    def __init__(self, parent=None, *, request_data: dict | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Permissão Solicitada")
        self.setModal(True)
        self.setMinimumWidth(420)
        self.setObjectName("PermissionRequestDialog")
        self.setStyleSheet("background-color: #1C1917; color: #FAFAF9;")

        self._request_data = request_data or {}
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)

        # Header
        header = QLabel("O agente Claude solicita permissão para executar uma ação:")
        header.setWordWrap(True)
        header.setStyleSheet("color: #D6D3D1; font-size: 13px;")
        layout.addWidget(header)

        # Action description
        description = self._request_data.get(
            "description",
            self._request_data.get("action", str(self._request_data) or "Ação não especificada"),
        )
        desc_label = QLabel(description)
        desc_label.setWordWrap(True)
        desc_label.setStyleSheet(
            "color: #FAFAF9; font-size: 13px; font-weight: 600;"
            " background-color: #292524; border: 1px solid #57534E;"
            " border-radius: 4px; padding: 8px;"
        )
        layout.addWidget(desc_label)

        layout.addSpacing(4)

        # Buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()

        reject_btn = QPushButton("Rejeitar")
        reject_btn.setFixedHeight(32)
        reject_btn.setStyleSheet(
            "QPushButton { background-color: #3F3F46; color: #FAFAF9;"
            "  border: 1px solid #57534E; border-radius: 4px; padding: 4px 16px;"
            "  font-size: 13px; }"
            "QPushButton:hover { background-color: #52525B; }"
        )
        reject_btn.clicked.connect(self._on_reject_clicked)
        btn_row.addWidget(reject_btn)

        allow_btn = QPushButton("Permitir")
        allow_btn.setDefault(True)
        allow_btn.setFixedHeight(32)
        allow_btn.setStyleSheet(
            "QPushButton { background-color: #16A34A; color: #FAFAF9;"
            "  border: none; border-radius: 4px; padding: 4px 16px;"
            "  font-size: 13px; font-weight: 600; }"
            "QPushButton:hover { background-color: #15803D; }"
        )
        allow_btn.clicked.connect(self._on_allow_clicked)
        btn_row.addWidget(allow_btn)

        layout.addLayout(btn_row)

    def _on_allow_clicked(self) -> None:
        self.permission_granted.emit()
        self.accept()

    def _on_reject_clicked(self) -> None:
        self.permission_rejected.emit()
        self.reject()
