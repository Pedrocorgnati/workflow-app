"""
EditCommandTypeDialog — Modal to edit model and interaction_type of a CommandSpec.

Fields:
  - Modelo (QComboBox: Opus, Sonnet, Haiku)
  - Tipo de Interação (QComboBox: Interativo, Automático)

Footer: [Cancelar] [Salvar]
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from workflow_app.domain import CommandSpec, EffortLevel, InteractionType, ModelName


class EditCommandTypeDialog(QDialog):
    """Dialog for editing the model and interaction type of a command in the queue."""

    command_updated = Signal(object)  # CommandSpec (updated copy)

    def __init__(self, spec: CommandSpec, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._spec = spec
        self.setWindowTitle("Editar Tipo de Comando")
        self.setMinimumSize(380, 270)
        self.setModal(True)
        self.setStyleSheet("background-color: #18181B;")
        self._setup_ui()

    # ──────────────────────────────────────────────────────── UI ──── #

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
        title = QLabel(f"Editar: {self._spec.name}")
        title.setStyleSheet("font-size: 14px; font-weight: 700; color: #FAFAFA;")
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

        combo_style = (
            "background-color: #27272A; color: #FAFAFA;"
            " border: 1px solid #3F3F46; border-radius: 4px; padding: 6px 10px;"
        )
        label_style = "color: #FAFAFA; font-size: 13px; font-weight: 600;"

        # Model combo
        model_label = QLabel("Modelo")
        model_label.setStyleSheet(label_style)
        bl.addWidget(model_label)
        self._model_combo = QComboBox()
        self._model_combo.addItems(["Opus", "Sonnet", "Haiku"])
        self._model_combo.setCurrentText(self._spec.model.value)
        self._model_combo.setStyleSheet(combo_style)
        bl.addWidget(self._model_combo)

        # Interaction type combo
        inter_label = QLabel("Tipo de Interação")
        inter_label.setStyleSheet(label_style)
        bl.addWidget(inter_label)
        self._inter_combo = QComboBox()
        self._inter_combo.addItems(["Interativo", "Automático"])
        current_inter = (
            "Interativo"
            if self._spec.interaction_type == InteractionType.INTERACTIVE
            else "Automático"
        )
        self._inter_combo.setCurrentText(current_inter)
        self._inter_combo.setStyleSheet(combo_style)
        bl.addWidget(self._inter_combo)

        # Effort combo
        effort_label = QLabel("Effort (/effort)")
        effort_label.setStyleSheet(label_style)
        bl.addWidget(effort_label)
        self._effort_combo = QComboBox()
        self._effort_combo.addItems(["low", "medium", "high", "max"])
        self._effort_combo.setCurrentText(self._spec.effort.value)
        self._effort_combo.setStyleSheet(combo_style)
        bl.addWidget(self._effort_combo)

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

        save_btn = QPushButton("Salvar")
        save_btn.setObjectName("PrimaryButton")
        save_btn.setStyleSheet(
            "QPushButton { background-color: #FBBF24; color: #18181B;"
            "  font-weight: 700; border: none; border-radius: 4px; padding: 8px 20px; }"
            "QPushButton:hover { background-color: #FDE68A; }"
        )
        save_btn.clicked.connect(self._on_save)
        fl.addWidget(save_btn)
        root.addWidget(footer)

    # ───────────────────────────────────────────────────── Slots ───── #

    def _on_save(self) -> None:
        model_map = {
            "Opus": ModelName.OPUS,
            "Sonnet": ModelName.SONNET,
            "Haiku": ModelName.HAIKU,
        }
        inter_map = {
            "Interativo": InteractionType.INTERACTIVE,
            "Automático": InteractionType.AUTO,
        }
        effort_map = {
            "low": EffortLevel.LOW,
            "medium": EffortLevel.STANDARD,
            "high": EffortLevel.HIGH,
            "max": EffortLevel.MAX,
        }
        import dataclasses

        updated = dataclasses.replace(
            self._spec,
            model=model_map.get(self._model_combo.currentText(), self._spec.model),
            interaction_type=inter_map.get(
                self._inter_combo.currentText(), self._spec.interaction_type
            ),
            effort=effort_map.get(self._effort_combo.currentText(), self._spec.effort),
        )
        self.command_updated.emit(updated)
        self.accept()
