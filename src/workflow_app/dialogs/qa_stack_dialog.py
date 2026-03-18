"""
QAStackDialog — Modal for choosing a stack-specific QA template.

Shows 5 buttons: [Next.js] [TypeScript] [Python] [Android] [React Native].
On click, emits the selected QA template via .selected_template and accepts.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QGridLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from workflow_app.domain import CommandSpec
from workflow_app.templates.quick_templates import QA_STACK_TEMPLATES


class QAStackDialog(QDialog):
    """Modal dialog with stack options for the QA button."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("QA — Escolha a stack")
        self.setModal(True)
        self.setFixedSize(420, 240)

        self._selected: list[CommandSpec] = []
        self._setup_ui()

    @property
    def selected_template(self) -> list[CommandSpec]:
        return self._selected

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 20, 24, 20)

        title = QLabel("Qual stack auditar?")
        title.setStyleSheet("color: #FAFAFA; font-size: 15px; font-weight: bold;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        subtitle = QLabel("QA base + auditoria completa da stack escolhida.")
        subtitle.setStyleSheet("color: #A1A1AA; font-size: 12px;")
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(subtitle)

        grid = QGridLayout()
        grid.setSpacing(8)

        _btn_style = (
            "QPushButton { background-color: #3F3F46; color: #D4D4D8;"
            "  border: 1px solid #52525B; border-radius: 6px;"
            "  padding: 10px 16px; font-size: 13px; font-weight: 600; }"
            "QPushButton:hover { background-color: #52525B; color: #FAFAFA; }"
            "QPushButton:pressed { background-color: #FBBF24; color: #18181B;"
            "  border-color: #FBBF24; }"
        )

        stacks = [
            ("Next.js", 0, 0),
            ("TypeScript", 0, 1),
            ("Python", 0, 2),
            ("Android", 1, 0),
            ("React Native", 1, 1),
        ]

        for stack_name, row, col in stacks:
            template = QA_STACK_TEMPLATES[stack_name]
            btn = QPushButton(stack_name)
            btn.setToolTip(f"QA + {stack_name} review ({len(template)} comandos)")
            btn.setStyleSheet(_btn_style)
            btn.clicked.connect(lambda checked=False, t=template: self._on_stack_selected(t))
            grid.addWidget(btn, row, col)

        layout.addLayout(grid)
        layout.addStretch()

    def _on_stack_selected(self, template: list[CommandSpec]) -> None:
        self._selected = list(template)
        self.accept()
