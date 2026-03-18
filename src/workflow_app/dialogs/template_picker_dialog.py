"""
TemplatePickerDialog — Modal dialog for selecting a pipeline template.

Shows all available templates (factory + custom) with name and description.
On Accepted, the selected template's CommandSpec list is available via .commands.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
)

from workflow_app.domain import CommandSpec

logger = logging.getLogger(__name__)


class TemplatePickerDialog(QDialog):
    """Modal dialog for picking a template from the template library."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Escolher Template")
        self.setModal(True)
        self.setMinimumSize(460, 360)

        self._commands: list[CommandSpec] = []
        self._template_data: list[tuple[int, str, str]] = []  # (id, name, description)

        self._setup_ui()
        self._load_templates()

    # ─────────────────────────────────────────────────────── properties ── #

    @property
    def commands(self) -> list[CommandSpec]:
        return self._commands

    # ──────────────────────────────────────────────────────── UI setup ── #

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(24, 20, 24, 20)

        title = QLabel("Selecione um template")
        title.setStyleSheet("color: #FAFAFA; font-size: 14px; font-weight: bold;")
        layout.addWidget(title)

        subtitle = QLabel("Templates de fábrica e customizados disponíveis:")
        subtitle.setStyleSheet("color: #A1A1AA; font-size: 12px;")
        layout.addWidget(subtitle)

        self._list = QListWidget()
        self._list.setStyleSheet(
            "QListWidget { background-color: #18181B; border: 1px solid #3F3F46;"
            "  border-radius: 8px; }"
            "QListWidget::item { color: #FAFAFA; padding: 10px 12px;"
            "  border-bottom: 1px solid #3F3F46; }"
            "QListWidget::item:selected { background-color: #3F3F46; }"
            "QListWidget::item:hover { background-color: #27272A; }"
        )
        self._list.itemDoubleClicked.connect(self._on_use_clicked)
        layout.addWidget(self._list, stretch=1)

        self._empty_label = QLabel("Nenhum template disponível.")
        self._empty_label.setStyleSheet("color: #71717A; font-size: 13px;")
        self._empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._empty_label.setVisible(False)
        layout.addWidget(self._empty_label)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch()

        self._cancel_btn = QPushButton("Cancelar")
        self._cancel_btn.setStyleSheet(
            "QPushButton { background-color: #3F3F46; color: #FAFAFA;"
            "  border: 1px solid #52525B; border-radius: 4px; padding: 6px 16px; }"
            "QPushButton:hover { background-color: #52525B; }"
        )
        self._cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(self._cancel_btn)

        self._use_btn = QPushButton("Usar Template →")
        self._use_btn.setDefault(True)
        self._use_btn.setEnabled(False)
        self._use_btn.setStyleSheet(
            "QPushButton { background-color: #B45309; color: #FAFAFA;"
            "  border: 1px solid #D97706; border-radius: 4px; padding: 6px 16px;"
            "  font-weight: bold; }"
            "QPushButton:hover { background-color: #D97706; }"
            "QPushButton:disabled { background-color: #27272A; color: #52525B;"
            "  border-color: #3F3F46; }"
        )
        self._use_btn.clicked.connect(self._on_use_clicked)
        btn_row.addWidget(self._use_btn)

        layout.addLayout(btn_row)

        self._list.itemSelectionChanged.connect(self._on_selection_changed)

    # ──────────────────────────────────────────────────────── data ── #

    def _load_templates(self) -> None:
        try:
            from workflow_app.templates.template_manager import TemplateManager

            tm = TemplateManager()
            templates = tm.list_templates()
        except Exception:
            logger.exception("TemplatePickerDialog: failed to load templates")
            templates = []

        if not templates:
            self._list.setVisible(False)
            self._empty_label.setVisible(True)
            return

        for dto in templates:
            badge = "🏭 " if dto.is_factory else "✏️ "
            label = f"{badge}{dto.name}"
            if dto.description:
                label += f"\n{dto.description}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, dto.id)
            self._list.addItem(item)

    # ──────────────────────────────────────────────────────── handlers ── #

    def _on_selection_changed(self) -> None:
        self._use_btn.setEnabled(bool(self._list.selectedItems()))

    def _on_use_clicked(self) -> None:
        selected = self._list.selectedItems()
        if not selected:
            return
        template_id: int = selected[0].data(Qt.ItemDataRole.UserRole)
        try:
            from workflow_app.templates.template_manager import TemplateManager

            tm = TemplateManager()
            dto = tm.load_template(template_id)
            self._commands = dto.commands
            self.accept()
        except Exception:
            logger.exception("TemplatePickerDialog: failed to load template id=%d", template_id)
