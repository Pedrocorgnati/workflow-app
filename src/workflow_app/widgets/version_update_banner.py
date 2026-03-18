"""
VersionUpdateBanner — Inline banner shown at the top of MainWindow when factory
templates are outdated (CLAUDE.md hash diverged from stored SHA-256).

Signals:
  update_requested   — user clicked "Atualizar"
  dismissed          — user clicked the close (✕) button
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class VersionUpdateBanner(QWidget):
    """Banner that prompts the user to refresh factory templates."""

    update_requested = Signal()
    dismissed = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("VersionUpdateBanner")
        self.setFixedHeight(36)
        self.setStyleSheet(
            "background-color: #292524;"
            " border-bottom: 1px solid #78716C;"
        )
        self.setVisible(False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 8, 0)
        layout.setSpacing(8)

        icon = QLabel("⚠")
        icon.setStyleSheet("color: #F59E0B; font-size: 13px;")
        layout.addWidget(icon)

        self._message = QLabel(
            "Templates de fábrica desatualizados — CLAUDE.md foi modificado."
        )
        self._message.setStyleSheet("color: #D6D3D1; font-size: 12px;")
        layout.addWidget(self._message, stretch=1)

        update_btn = QPushButton("Atualizar")
        update_btn.setFixedHeight(24)
        update_btn.setStyleSheet(
            "QPushButton { background-color: #B45309; color: #FAFAFA;"
            "  border: none; border-radius: 4px; padding: 2px 12px;"
            "  font-size: 12px; font-weight: bold; }"
            "QPushButton:hover { background-color: #D97706; }"
        )
        update_btn.clicked.connect(self._on_update_clicked)
        layout.addWidget(update_btn)

        close_btn = QPushButton("✕")
        close_btn.setFixedSize(20, 20)
        close_btn.setStyleSheet(
            "QPushButton { background: none; color: #71717A;"
            "  border: none; font-size: 11px; }"
            "QPushButton:hover { color: #FAFAFA; }"
        )
        close_btn.clicked.connect(self._on_dismiss_clicked)
        layout.addWidget(close_btn)

    def set_outdated_names(self, names: list[str]) -> None:
        """Update the message to list which templates are outdated."""
        if names:
            preview = ", ".join(names[:2])
            suffix = "..." if len(names) > 2 else ""
            self._message.setText(
                f"Templates desatualizados: {preview}{suffix} — CLAUDE.md foi modificado."
            )

    def _on_update_clicked(self) -> None:
        self.update_requested.emit()
        self.setVisible(False)

    def _on_dismiss_clicked(self) -> None:
        self.dismissed.emit()
        self.setVisible(False)
