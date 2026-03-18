"""
AddCommandDialog — Modal to add a new command to the queue.

Fields:
  - Comando * (QLineEdit, e.g. /prd-create)
  - Modelo (QComboBox: Opus, Sonnet, Haiku)
  - Tipo de Interação (QComboBox: Automático, Interativo)

Footer: [Cancelar] [Adicionar] (disabled if command empty)
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from workflow_app.domain import CommandSpec, InteractionType, ModelName


class AddCommandDialog(QDialog):
    """Dialog for adding a new command to the pipeline queue."""

    command_added = Signal(object)  # CommandSpec

    def __init__(self, next_position: int = 1, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._next_position = next_position
        self.setWindowTitle("Adicionar Comando")
        self.setMinimumSize(440, 280)
        self.setModal(True)
        self.setStyleSheet("background-color: #18181B;")
        self._setup_ui()

    # ─────────────────────────────────────────────────────────── UI ──── #

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header
        header = QWidget()
        header.setObjectName("DialogHeader")
        header.setFixedHeight(56)
        header.setStyleSheet(
            "background-color: #27272A; border-bottom: 1px solid #3F3F46;"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(16, 0, 16, 0)
        title = QLabel("Adicionar Comando")
        title.setStyleSheet("font-size: 16px; font-weight: 700; color: #FAFAFA;")
        hl.addWidget(title)
        hl.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(28, 28)
        close_btn.setStyleSheet(
            "QPushButton { background-color: transparent; border: none; color: #A1A1AA; }"
            "QPushButton:hover { background-color: #3F3F46; color: #FAFAFA; }"
        )
        close_btn.clicked.connect(self.reject)
        hl.addWidget(close_btn)
        root.addWidget(header)

        # Body
        body = QWidget()
        body.setStyleSheet("background-color: #18181B;")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(24, 20, 24, 20)
        bl.setSpacing(16)

        # Command input
        cmd_label = QLabel("Comando *")
        cmd_label.setStyleSheet("color: #FAFAFA; font-size: 13px; font-weight: 600;")
        bl.addWidget(cmd_label)
        self._cmd_input = QLineEdit()
        self._cmd_input.setPlaceholderText("ex: /prd-create")
        self._cmd_input.setStyleSheet(
            "background-color: #27272A; color: #FAFAFA;"
            " border: 1px solid #3F3F46; border-radius: 4px; padding: 8px 10px;"
        )
        self._cmd_input.textChanged.connect(self._on_text_changed)
        bl.addWidget(self._cmd_input)

        # Model combo
        model_label = QLabel("Modelo")
        model_label.setStyleSheet("color: #FAFAFA; font-size: 13px; font-weight: 600;")
        bl.addWidget(model_label)
        self._model_combo = QComboBox()
        self._model_combo.addItems(["Opus", "Sonnet", "Haiku"])
        self._model_combo.setCurrentIndex(0)
        self._model_combo.setStyleSheet(
            "background-color: #27272A; color: #FAFAFA;"
            " border: 1px solid #3F3F46; border-radius: 4px; padding: 8px 10px;"
        )
        bl.addWidget(self._model_combo)

        # Interaction type combo
        inter_label = QLabel("Tipo de Interação")
        inter_label.setStyleSheet("color: #FAFAFA; font-size: 13px; font-weight: 600;")
        bl.addWidget(inter_label)
        self._inter_combo = QComboBox()
        self._inter_combo.addItems(["Interativo", "Automático"])
        self._inter_combo.setCurrentIndex(0)
        self._inter_combo.setStyleSheet(
            "background-color: #27272A; color: #FAFAFA;"
            " border: 1px solid #3F3F46; border-radius: 4px; padding: 8px 10px;"
        )
        bl.addWidget(self._inter_combo)

        root.addWidget(body, stretch=1)

        # Footer
        footer = QWidget()
        footer.setObjectName("DialogFooter")
        footer.setFixedHeight(56)
        footer.setStyleSheet(
            "background-color: #27272A; border-top: 1px solid #3F3F46;"
        )
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(24, 0, 24, 0)
        fl.setSpacing(8)
        fl.addStretch()

        cancel_btn = QPushButton("Cancelar")
        cancel_btn.setStyleSheet(
            "QPushButton { background-color: #3F3F46; color: #FAFAFA;"
            "  border: none; border-radius: 4px; padding: 8px 16px; }"
            "QPushButton:hover { background-color: #52525B; }"
        )
        cancel_btn.clicked.connect(self.reject)
        fl.addWidget(cancel_btn)

        self._add_btn = QPushButton("Adicionar")
        self._add_btn.setObjectName("PrimaryButton")
        self._add_btn.setEnabled(False)
        self._add_btn.setStyleSheet(
            "QPushButton { background-color: #FBBF24; color: #18181B;"
            "  font-weight: 700; border: none; border-radius: 4px; padding: 8px 20px; }"
            "QPushButton:hover { background-color: #FDE68A; }"
            "QPushButton:disabled { background-color: #78350F; color: #92400E; }"
        )
        self._add_btn.clicked.connect(self._on_add)
        fl.addWidget(self._add_btn)
        root.addWidget(footer)

    # ─────────────────────────────────────────────────────── Slots ───── #

    def _on_text_changed(self, text: str) -> None:
        self._add_btn.setEnabled(bool(text.strip()))

    def _on_add(self) -> None:
        name = self._cmd_input.text().strip()
        if not name:
            return

        model_map = {"Opus": ModelName.OPUS, "Sonnet": ModelName.SONNET, "Haiku": ModelName.HAIKU}
        inter_map = {"Interativo": InteractionType.INTERACTIVE, "Automático": InteractionType.AUTO}

        model = model_map.get(self._model_combo.currentText(), ModelName.SONNET)
        inter = inter_map.get(self._inter_combo.currentText(), InteractionType.INTERACTIVE)

        spec = CommandSpec(
            name=name,
            model=model,
            interaction_type=inter,
            position=self._next_position,
        )
        self.command_added.emit(spec)
        self.accept()
