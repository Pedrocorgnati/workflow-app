"""
BriefTemplateDialog — Modal for choosing between New Project and Feature brief.

Shows two buttons: [New] and [Feature]. On click, emits the selected template
via the .selected_template property and accepts the dialog.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from workflow_app.domain import CommandSpec
from workflow_app.templates.quick_templates import (
    TEMPLATE_BRIEF_FEATURE,
    TEMPLATE_BRIEF_NEW,
)


class BriefTemplateDialog(QDialog):
    """Modal dialog with [New] and [Feature] options for the Brief button."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Brief — Escolha o tipo")
        self.setModal(True)
        self.setFixedSize(380, 200)

        self._selected: list[CommandSpec] = []
        self._setup_ui()

    @property
    def selected_template(self) -> list[CommandSpec]:
        return self._selected

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 20, 24, 20)

        title = QLabel("Qual tipo de brief?")
        title.setStyleSheet("color: #FAFAFA; font-size: 15px; font-weight: bold;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("Escolha o fluxo que será carregado na fila de comandos.")
        subtitle.setStyleSheet("color: #A1A1AA; font-size: 12px;")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        layout.addStretch()

        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        _big_btn = (
            "QPushButton {{ background-color: {bg}; color: #FAFAFA;"
            "  border: 1px solid {border}; border-radius: 6px;"
            "  padding: 12px 24px; font-size: 14px; font-weight: 700; }}"
            "QPushButton:hover {{ background-color: {hover}; }}"
        )

        btn_new = QPushButton("New")
        btn_new.setToolTip("Projeto novo completo (F1→F3, ~27 comandos)")
        btn_new.setStyleSheet(_big_btn.format(
            bg="#B45309", border="#D97706", hover="#D97706",
        ))
        btn_new.clicked.connect(self._on_new)
        btn_row.addWidget(btn_new)

        btn_feature = QPushButton("Feature")
        btn_feature.setToolTip("Feature em projeto existente (~27 comandos)")
        btn_feature.setStyleSheet(_big_btn.format(
            bg="#3F3F46", border="#52525B", hover="#52525B",
        ))
        btn_feature.clicked.connect(self._on_feature)
        btn_row.addWidget(btn_feature)

        layout.addLayout(btn_row)
        layout.addStretch()

    def _on_new(self) -> None:
        self._selected = list(TEMPLATE_BRIEF_NEW)
        self.accept()

    def _on_feature(self) -> None:
        self._selected = list(TEMPLATE_BRIEF_FEATURE)
        self.accept()
