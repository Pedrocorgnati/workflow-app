"""
CommandItemWidget — Single row in the command queue.

Visual states per DESIGN.md 2.3:
  Pendente   ○ gray   /cmd-name  [Model]
  Executando ⊙ blue   /cmd-name  [Model] ●●● (pulsing)
  Concluido  ✓ green  /cmd-name  [Model]
  Erro       ✕ red    /cmd-name  [Model]
  Pulado     ─ muted  /cmd-name (strikethrough) [Model]
  Incerto    ? amber  /cmd-name  [Model]
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QWidget,
)

from workflow_app.domain import CommandSpec, CommandStatus, ModelName
from workflow_app.widgets.model_badge import ModelBadge
from workflow_app.widgets.status_badge import StatusDot

_STATUS_SYMBOL: dict[CommandStatus, str] = {
    CommandStatus.PENDENTE:   "○",
    CommandStatus.EXECUTANDO: "⊙",
    CommandStatus.CONCLUIDO:  "✓",
    CommandStatus.ERRO:       "✕",
    CommandStatus.PULADO:     "─",
    CommandStatus.INCERTO:    "?",
}


class CommandItemWidget(QWidget):
    """One command row in the queue list."""

    # Signals
    remove_requested = Signal(int)   # position
    skip_requested = Signal(int)     # position
    edit_model_requested = Signal(int)  # position

    def __init__(self, spec: CommandSpec, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CommandItemWidget")
        self._spec = spec
        self._status = CommandStatus.PENDENTE
        self.setFixedHeight(44)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self._setup_ui()

    # ─────────────────────────────────────────────────────────── UI ──── #

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)

        # Status dot
        self._dot = StatusDot(self._status, parent=self)
        layout.addWidget(self._dot)

        # Command name
        self._name_label = QLabel(self._spec.name)
        self._name_label.setStyleSheet(
            "color: #FAFAFA; font-family: monospace; font-size: 13px;"
        )
        layout.addWidget(self._name_label, stretch=1)

        # Model badge
        self._model_badge = ModelBadge(self._spec.model, short=True, parent=self)
        layout.addWidget(self._model_badge)

        # Kebab menu button
        self._menu_btn = QPushButton("⋮")
        self._menu_btn.setObjectName("IconButton")
        self._menu_btn.setFixedSize(20, 20)
        self._menu_btn.setStyleSheet(
            "QPushButton { background-color: transparent; border: none;"
            "  color: #71717A; font-size: 14px; }"
            "QPushButton:hover { color: #FAFAFA; }"
        )
        self._menu_btn.clicked.connect(
            lambda: self._show_context_menu(self._menu_btn.mapToParent(QPoint(0, 20)))
        )
        layout.addWidget(self._menu_btn)

        self._update_appearance()

    # ──────────────────────────────────────────────────── Public API ─── #

    def set_status(self, status: CommandStatus) -> None:
        self._status = status
        self._dot.set_status(status)
        self._update_appearance()

    def get_spec(self) -> CommandSpec:
        return self._spec

    def set_model(self, model: ModelName) -> None:
        self._spec = CommandSpec(
            name=self._spec.name,
            model=model,
            interaction_type=self._spec.interaction_type,
            position=self._spec.position,
            is_optional=self._spec.is_optional,
        )
        self._model_badge.deleteLater()
        self._model_badge = ModelBadge(model, short=True, parent=self)
        # Re-insert badge in layout (index 2)
        self.layout().insertWidget(2, self._model_badge)

    # ─────────────────────────────────────────────────────── Helpers ─── #

    def _update_appearance(self) -> None:
        if self._status == CommandStatus.PULADO:
            self._name_label.setStyleSheet(
                "color: #52525B; font-family: monospace; font-size: 13px;"
                " text-decoration: line-through;"
            )
            self.setStyleSheet(
                "QWidget#CommandItemWidget { background-color: #27272A;"
                " border-bottom: 1px solid #3F3F46; }"
            )
        elif self._status == CommandStatus.EXECUTANDO:
            self._name_label.setStyleSheet(
                "color: #FAFAFA; font-family: monospace; font-size: 13px;"
            )
            self.setStyleSheet(
                "QWidget#CommandItemWidget { background-color: #27272A;"
                " border-bottom: 1px solid #3F3F46;"
                " border-left: 2px solid #38BDF8; }"
            )
        elif self._status == CommandStatus.CONCLUIDO:
            self._name_label.setStyleSheet(
                "color: #A1A1AA; font-family: monospace; font-size: 13px;"
            )
            self.setStyleSheet(
                "QWidget#CommandItemWidget { background-color: #27272A;"
                " border-bottom: 1px solid #3F3F46; }"
            )
        elif self._status == CommandStatus.ERRO:
            self._name_label.setStyleSheet(
                "color: #FB7185; font-family: monospace; font-size: 13px;"
            )
            self.setStyleSheet(
                "QWidget#CommandItemWidget { background-color: #27272A;"
                " border-bottom: 1px solid #3F3F46; }"
            )
        else:
            self._name_label.setStyleSheet(
                "color: #FAFAFA; font-family: monospace; font-size: 13px;"
            )
            self.setStyleSheet(
                "QWidget#CommandItemWidget { background-color: #27272A;"
                " border-bottom: 1px solid #3F3F46; }"
                "QWidget#CommandItemWidget:hover { background-color: #3F3F46; }"
            )

    def _show_context_menu(self, pos: QPoint) -> None:
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background-color: #27272A; border: 1px solid #3F3F46;"
            "  color: #FAFAFA; padding: 4px; }"
            "QMenu::item { padding: 6px 16px; border-radius: 4px; }"
            "QMenu::item:selected { background-color: #3F3F46; }"
            "QMenu::separator { background-color: #3F3F46; height: 1px; }"
        )
        edit_action = menu.addAction("✏ Editar Modelo")
        skip_action = menu.addAction("⏭ Marcar Pular")
        menu.addSeparator()
        remove_action = menu.addAction("🗑 Remover")
        remove_action.setData("danger")

        action = menu.exec(self.mapToGlobal(pos))
        if action == edit_action:
            self.edit_model_requested.emit(self._spec.position)
        elif action == skip_action:
            self.skip_requested.emit(self._spec.position)
        elif action == remove_action:
            self.remove_requested.emit(self._spec.position)
