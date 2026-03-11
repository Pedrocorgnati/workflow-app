"""
CommandQueueWidget — 280px right panel showing the command queue.

States:
  - Empty: "Nenhum pipeline configurado." + [Criar Pipeline] button
  - With commands: scrollable list of CommandItemWidget rows + [+] button at bottom

Width: fixed 280px (min 240px, max 360px)
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from workflow_app.command_queue.command_item_widget import CommandItemWidget
from workflow_app.domain import CommandSpec, CommandStatus
from workflow_app.signal_bus import signal_bus


class CommandQueueWidget(QWidget):
    """Right sidebar showing the pipeline command queue."""

    new_pipeline_requested = Signal()
    add_command_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("CommandQueueWidget")
        self.setMinimumWidth(240)
        self.setMaximumWidth(360)
        self.setFixedWidth(280)
        self.setStyleSheet(
            "background-color: #18181B; border-left: 1px solid #3F3F46;"
        )

        self._items: list[CommandItemWidget] = []
        self._setup_ui()
        self._connect_signals()

    # ─────────────────────────────────────────────────────────── UI ──── #

    def _setup_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Header
        header = QWidget()
        header.setObjectName("CommandQueueHeader")
        header.setFixedHeight(36)
        header.setStyleSheet(
            "background-color: #27272A; border-bottom: 1px solid #3F3F46;"
        )
        hl = QHBoxLayout(header)
        hl.setContentsMargins(12, 0, 12, 0)
        title = QLabel("Fila de Comandos")
        title.setStyleSheet(
            "color: #A1A1AA; font-size: 12px; font-weight: 600;"
            " text-transform: uppercase; letter-spacing: 0.5px;"
        )
        hl.addWidget(title)
        hl.addStretch()
        main_layout.addWidget(header)

        # Stacked content (empty state vs list)
        self._content_stack = QWidget()
        content_layout = QVBoxLayout(self._content_stack)
        content_layout.setContentsMargins(0, 0, 0, 0)
        content_layout.setSpacing(0)
        main_layout.addWidget(self._content_stack, stretch=1)

        # Empty state
        self._empty_widget = QWidget()
        el = QVBoxLayout(self._empty_widget)
        el.setAlignment(Qt.AlignmentFlag.AlignCenter)
        el.setSpacing(12)
        empty_label = QLabel("Nenhum pipeline\nconfigurado.")
        empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_label.setStyleSheet("color: #71717A; font-size: 13px;")
        el.addWidget(empty_label)

        self._create_pipeline_btn = QPushButton("Criar Pipeline")
        self._create_pipeline_btn.setStyleSheet(
            "QPushButton { background-color: transparent; color: #FBBF24;"
            "  border: 1px solid #FBBF24; border-radius: 4px;"
            "  padding: 6px 14px; font-weight: 600; }"
            "QPushButton:hover { background-color: #78350F; }"
        )
        self._create_pipeline_btn.clicked.connect(self.new_pipeline_requested)
        el.addWidget(self._create_pipeline_btn, alignment=Qt.AlignmentFlag.AlignCenter)

        # List view
        self._list_widget = QWidget()
        list_layout = QVBoxLayout(self._list_widget)
        list_layout.setContentsMargins(0, 0, 0, 0)
        list_layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("border: none; background-color: #18181B;")

        self._items_container = QWidget()
        self._items_container.setStyleSheet("background-color: #18181B;")
        self._items_layout = QVBoxLayout(self._items_container)
        self._items_layout.setContentsMargins(0, 0, 0, 0)
        self._items_layout.setSpacing(0)
        self._items_layout.addStretch()

        scroll.setWidget(self._items_container)
        list_layout.addWidget(scroll, stretch=1)

        # Add button footer
        add_bar = QWidget()
        add_bar.setStyleSheet(
            "background-color: #27272A; border-top: 1px solid #3F3F46;"
        )
        add_bar.setFixedHeight(36)
        al = QHBoxLayout(add_bar)
        al.setContentsMargins(8, 4, 8, 4)
        add_btn = QPushButton("[+] Adicionar Comando")
        add_btn.setStyleSheet(
            "QPushButton { background-color: transparent; color: #FBBF24;"
            "  border: none; font-size: 12px; }"
            "QPushButton:hover { color: #FDE68A; }"
        )
        add_btn.clicked.connect(self.add_command_requested)
        al.addWidget(add_btn)
        list_layout.addWidget(add_bar)

        content_layout.addWidget(self._empty_widget)
        content_layout.addWidget(self._list_widget)
        self._list_widget.setVisible(False)

    def _connect_signals(self) -> None:
        signal_bus.pipeline_ready.connect(self.load_pipeline)
        signal_bus.command_started.connect(self._on_command_started)
        signal_bus.command_completed.connect(self._on_command_completed)
        signal_bus.command_failed.connect(self._on_command_failed)
        signal_bus.command_skipped.connect(self._on_command_skipped)

    # ──────────────────────────────────────────────────── Public API ─── #

    def load_pipeline(self, specs: list[CommandSpec]) -> None:
        """Populate the queue with CommandSpec objects."""
        # Clear existing
        for item in self._items:
            item.setParent(None)
        self._items.clear()

        # Remove stretch before inserting
        stretch_item = self._items_layout.takeAt(self._items_layout.count() - 1)

        for spec in specs:
            item = CommandItemWidget(spec, parent=self._items_container)
            item.remove_requested.connect(self._on_remove_requested)
            item.skip_requested.connect(self._on_skip_requested)
            self._items_layout.addWidget(item)
            self._items.append(item)

        # Re-add stretch at end
        self._items_layout.addStretch()

        self._empty_widget.setVisible(False)
        self._list_widget.setVisible(True)

    def clear_queue(self) -> None:
        for item in self._items:
            item.setParent(None)
        self._items.clear()
        self._empty_widget.setVisible(True)
        self._list_widget.setVisible(False)

    def _item_at(self, position: int) -> CommandItemWidget | None:
        for item in self._items:
            if item.get_spec().position == position:
                return item
        return None

    # ─────────────────────────────────────────────────────── Slots ───── #

    def _on_command_started(self, index: int) -> None:
        item = self._item_at(index + 1)
        if item:
            item.set_status(CommandStatus.EXECUTANDO)

    def _on_command_completed(self, index: int) -> None:
        item = self._item_at(index + 1)
        if item:
            item.set_status(CommandStatus.CONCLUIDO)

    def _on_command_failed(self, index: int, _msg: str) -> None:
        item = self._item_at(index + 1)
        if item:
            item.set_status(CommandStatus.ERRO)

    def _on_command_skipped(self, index: int) -> None:
        item = self._item_at(index + 1)
        if item:
            item.set_status(CommandStatus.PULADO)

    def _on_remove_requested(self, position: int) -> None:
        item = self._item_at(position)
        if item:
            self._items_layout.removeWidget(item)
            item.setParent(None)
            self._items = [i for i in self._items if i.get_spec().position != position]
            if not self._items:
                self._empty_widget.setVisible(True)
                self._list_widget.setVisible(False)

    def _on_skip_requested(self, position: int) -> None:
        item = self._item_at(position)
        if item:
            item.set_status(CommandStatus.PULADO)
            signal_bus.command_skipped.emit(position - 1)
