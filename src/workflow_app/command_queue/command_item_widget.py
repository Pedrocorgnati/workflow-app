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

from collections.abc import Callable

from PySide6.QtCore import QMimeData, QPoint, Qt, Signal
from PySide6.QtGui import QDrag, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMenu,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from workflow_app.domain import CommandSpec, CommandStatus, InteractionType, ModelName
from workflow_app.widgets.model_badge import ModelBadge

# Error state colours (Graphite Amber theme)
_COLOR_ERROR_BG = "#3F1010"
_COLOR_ERROR_BORDER = "#7F1D1D"
_COLOR_ERROR_TEXT = "#FCA5A5"

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
    remove_requested = Signal(int)          # position
    skip_requested = Signal(int)            # position
    edit_model_requested = Signal(int)      # position
    retry_requested = Signal(int)           # position (module-12/TASK-3)
    cancel_requested = Signal()             # no arg — cancel whole pipeline
    run_in_terminal_requested = Signal(str) # command name

    # Minimum Manhattan distance before drag begins (px)
    _DRAG_THRESHOLD = 10

    def __init__(
        self,
        spec: CommandSpec,
        can_reorder_fn: Callable[[int], bool] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setObjectName("CommandItemWidget")
        self._spec = spec
        self._status = CommandStatus.PENDENTE
        self._highlighted: bool = False
        self._can_reorder_fn: Callable[[int], bool] = can_reorder_fn or (lambda _pos: True)
        self._drag_start_pos: QPoint | None = None
        self.setMinimumHeight(44)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_context_menu)
        self._setup_ui()

    # ─────────────────────────────────────────────────────────── UI ──── #

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Main row
        main_row_widget = QWidget()
        layout = QHBoxLayout(main_row_widget)
        layout.setContentsMargins(10, 6, 10, 6)
        layout.setSpacing(8)

        # Run in terminal button (green arrow)
        self._run_btn = QPushButton("▶")
        self._run_btn.setObjectName("IconButton")
        self._run_btn.setFixedSize(16, 16)
        self._run_btn.setToolTip("Executar no terminal")
        self._run_btn.setStyleSheet(
            "QPushButton { background-color: transparent; border: none;"
            "  color: #22C55E; font-size: 10px; }"
            "QPushButton:hover { color: #86EFAC; }"
        )
        self._run_btn.clicked.connect(self._on_run_clicked)
        layout.addWidget(self._run_btn)

        # Copy button (blue clipboard icon) — copies the full command line
        self._copy_btn = QPushButton("\u29C9")
        self._copy_btn.setObjectName("IconButton")
        self._copy_btn.setFixedSize(16, 16)
        self._copy_btn.setToolTip("Copiar comando")
        self._copy_btn.setStyleSheet(
            "QPushButton { background-color: transparent; border: none;"
            "  color: #38BDF8; font-size: 12px; }"
            "QPushButton:hover { color: #7DD3FC; }"
        )
        self._copy_btn.clicked.connect(self._on_copy_clicked)
        layout.addWidget(self._copy_btn)

        # Quick-delete button (red ✕) — next to copy button on the left side
        self._delete_btn = QPushButton("✕")
        self._delete_btn.setObjectName("IconButton")
        self._delete_btn.setFixedSize(18, 18)
        self._delete_btn.setToolTip("Remover da fila")
        self._delete_btn.setStyleSheet(
            "QPushButton { background-color: transparent; border: none;"
            "  color: #EF4444; font-size: 11px; font-weight: 700; }"
            "QPushButton:hover { color: #FCA5A5; }"
            "QPushButton:pressed { color: #DC2626; }"
        )
        self._delete_btn.clicked.connect(
            lambda: self.remove_requested.emit(self._spec.position)
        )
        layout.addWidget(self._delete_btn)

        # Command name (+ optional config path) — one token per line
        parts = f"{self._spec.name} {self._spec.config_path}".strip().split()
        self._name_label = QLabel("\n".join(parts))
        self._name_label.setStyleSheet(
            "color: #FAFAFA; font-family: monospace; font-size: 11px;"
        )
        layout.addWidget(self._name_label, stretch=1)

        # Interaction type badge (auto / inter)
        interaction_text = self._spec.interaction_badge_text()
        self._interaction_badge = QLabel(interaction_text)
        _is_auto = self._spec.interaction_type == InteractionType.AUTO
        _inter_color = "#22C55E" if _is_auto else "#FBBF24"
        self._interaction_badge.setStyleSheet(
            f"color: {_inter_color}; font-size: 9px; font-weight: 600;"
            " font-family: monospace; padding: 1px 4px;"
            f" border: 1px solid {_inter_color}; border-radius: 3px;"
        )
        self._interaction_badge.setFixedHeight(18)

        # Model badge — hidden for /model and /clear commands
        self._model_badge = ModelBadge(self._spec.model, short=True, parent=self)
        _hide_badge = (
            self._spec.name.lower().startswith("/model")
            or self._spec.name.strip().lower() == "/clear"
        )
        if not _hide_badge:
            layout.addWidget(self._model_badge)
            layout.addWidget(self._interaction_badge)
        else:
            self._model_badge.setVisible(False)
            self._interaction_badge.setVisible(False)
        root.addWidget(main_row_widget)

        # Dashed separator line
        separator = QWidget()
        separator.setFixedHeight(1)
        separator.setStyleSheet(
            "border: none; border-top: 1px dashed #3F3F46; background: transparent;"
        )
        root.addWidget(separator)

        # Error row (hidden by default — shown only when status == ERRO)
        self._error_row = QWidget()
        self._error_row.setObjectName("ErrorRow")
        er_layout = QHBoxLayout(self._error_row)
        er_layout.setContentsMargins(10, 2, 10, 6)
        er_layout.setSpacing(6)

        self._error_label = QLabel()
        self._error_label.setStyleSheet(f"color: {_COLOR_ERROR_TEXT}; font-size: 11px;")
        self._error_label.setWordWrap(True)
        er_layout.addWidget(self._error_label, stretch=1)

        self._btn_retry = QPushButton("Retentar")
        self._btn_retry.setFixedWidth(72)
        self._btn_retry.setStyleSheet(
            "QPushButton { background-color: #7F1D1D; color: #FCA5A5;"
            "  border: 1px solid #991B1B; border-radius: 3px; font-size: 11px; padding: 2px 6px; }"
            "QPushButton:hover { background-color: #991B1B; }"
        )
        self._btn_retry.clicked.connect(
            lambda: self.retry_requested.emit(self._spec.position)
        )
        er_layout.addWidget(self._btn_retry)

        self._btn_skip_err = QPushButton("Pular")
        self._btn_skip_err.setFixedWidth(52)
        self._btn_skip_err.setStyleSheet(
            "QPushButton { background-color: #3F3F46; color: #A1A1AA;"
            "  border: 1px solid #52525B; border-radius: 3px; font-size: 11px; padding: 2px 6px; }"
            "QPushButton:hover { background-color: #52525B; }"
        )
        self._btn_skip_err.clicked.connect(
            lambda: self.skip_requested.emit(self._spec.position)
        )
        er_layout.addWidget(self._btn_skip_err)

        self._btn_cancel_pipeline = QPushButton("Cancelar")
        self._btn_cancel_pipeline.setFixedWidth(64)
        self._btn_cancel_pipeline.setStyleSheet(
            "QPushButton { background-color: #3F3F46; color: #A1A1AA;"
            "  border: 1px solid #52525B; border-radius: 3px; font-size: 11px; padding: 2px 6px; }"
            "QPushButton:hover { background-color: #52525B; }"
        )
        self._btn_cancel_pipeline.clicked.connect(self.cancel_requested)
        er_layout.addWidget(self._btn_cancel_pipeline)

        self._error_row.setVisible(False)
        root.addWidget(self._error_row)

        self._update_appearance()

    # ──────────────────────────────────────────────────── Public API ─── #

    def set_status(self, status: CommandStatus, error_message: str = "") -> None:
        self._status = status
        # Show error row only for ERRO state
        is_error = status == CommandStatus.ERRO
        self._error_row.setVisible(is_error)
        if is_error and error_message:
            self._error_label.setText(error_message)
        elif not is_error:
            self._error_label.clear()
        self._update_appearance()

    def get_spec(self) -> CommandSpec:
        return self._spec

    def command_text(self) -> str:
        """Return the full command text (name + config_path), space-separated."""
        return f"{self._spec.name} {self._spec.config_path}".strip()

    def set_highlighted(self, highlighted: bool) -> None:
        """Mark this item as the 'current' command (matches queue-last-command)."""
        if self._highlighted == highlighted:
            return
        self._highlighted = highlighted
        self._update_appearance()

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
        _hide_badge = (
            self._spec.name.lower().startswith("/model")
            or self._spec.name.strip().lower() == "/clear"
        )
        if not _hide_badge:
            # Re-insert badge in layout (index 2)
            self.layout().insertWidget(2, self._model_badge)
        else:
            self._model_badge.setVisible(False)

    def _on_copy_clicked(self) -> None:
        """Copy the full command line to the clipboard."""
        text = f"{self._spec.name} {self._spec.config_path}".strip()
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(text)

    def _on_run_clicked(self) -> None:
        """Emit run signal, turn button into amber dot, reveal quick-delete."""
        self.run_in_terminal_requested.emit(
            f"{self._spec.name} {self._spec.config_path}".strip()
        )
        self._mark_as_sent()

    def _mark_as_sent(self) -> None:
        """Visually mark this row as already sent to terminal."""
        self._run_btn.setText("●")
        self._run_btn.setStyleSheet(
            "QPushButton { background-color: transparent; border: none;"
            "  color: #FBBF24; font-size: 11px; }"
        )
        self._run_btn.setEnabled(False)

    def is_pending_run(self) -> bool:
        """True if this row has not yet been sent to the terminal."""
        return self._run_btn.isEnabled()

    def reset_to_pending(self) -> None:
        """Reset this row back to pending state (for loop restart)."""
        self._run_btn.setText("▶")
        self._run_btn.setStyleSheet(
            "QPushButton { background-color: transparent; border: none;"
            "  color: #22C55E; font-size: 10px; }"
            "QPushButton:hover { color: #86EFAC; }"
        )
        self._run_btn.setEnabled(True)
        self.set_status(CommandStatus.PENDENTE)

    # ─────────────────────────────────────────── Drag-and-drop source ─── #

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start_pos = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if not (event.buttons() & Qt.MouseButton.LeftButton):
            return
        if self._drag_start_pos is None:
            return
        delta = (event.position().toPoint() - self._drag_start_pos).manhattanLength()
        if delta < self._DRAG_THRESHOLD:
            return
        if not self._can_reorder_fn(self._spec.position):
            return
        drag = QDrag(self)
        mime = QMimeData()
        mime.setText(str(self._spec.position))
        drag.setMimeData(mime)
        # Renderiza o widget em um pixmap base
        base = QPixmap(self.size())
        base.fill(Qt.GlobalColor.transparent)
        self.render(base)
        # Aplica opacidade em um segundo pixmap
        pixmap = QPixmap(self.size())
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setOpacity(0.7)
        painter.drawPixmap(0, 0, base)
        painter.end()
        drag.setPixmap(pixmap)
        drag.setHotSpot(self._drag_start_pos)
        drag.exec(Qt.DropAction.MoveAction)
        self._drag_start_pos = None

    # ─────────────────────────────────────────────────────── Helpers ─── #

    def _update_appearance(self) -> None:
        # Highlight border for the row matching the last-played command
        _hl = (
            " border-top: 2px solid #E4E4E7; border-bottom: 2px solid #E4E4E7;"
            if self._highlighted else ""
        )

        if self._status == CommandStatus.PULADO:
            self._name_label.setStyleSheet(
                "color: #52525B; font-family: monospace; font-size: 11px;"
                " text-decoration: line-through;"
            )
            self.setStyleSheet(
                f"QWidget#CommandItemWidget {{ background-color: #27272A;{_hl} }}"
            )
        elif self._status == CommandStatus.EXECUTANDO:
            self._name_label.setStyleSheet(
                "color: #FAFAFA; font-family: monospace; font-size: 11px;"
            )
            self.setStyleSheet(
                f"QWidget#CommandItemWidget {{ background-color: #27272A;"
                f" border-left: 2px solid #38BDF8;{_hl} }}"
            )
        elif self._status == CommandStatus.CONCLUIDO:
            self._name_label.setStyleSheet(
                "color: #A1A1AA; font-family: monospace; font-size: 11px;"
            )
            self.setStyleSheet(
                f"QWidget#CommandItemWidget {{ background-color: #27272A;{_hl} }}"
            )
        elif self._status == CommandStatus.ERRO:
            self._name_label.setStyleSheet(
                "color: #FB7185; font-family: monospace; font-size: 11px;"
            )
            if self._highlighted:
                self.setStyleSheet(
                    f"QWidget#CommandItemWidget {{ background-color: {_COLOR_ERROR_BG};"
                    f" border: 1px solid {_COLOR_ERROR_BORDER}; border-radius: 2px;"
                    f" border-top: 2px solid #E4E4E7; border-bottom: 2px solid #E4E4E7; }}"
                )
            else:
                self.setStyleSheet(
                    f"QWidget#CommandItemWidget {{ background-color: {_COLOR_ERROR_BG};"
                    f" border: 1px solid {_COLOR_ERROR_BORDER}; border-radius: 2px; }}"
                )
        else:
            self._name_label.setStyleSheet(
                "color: #FAFAFA; font-family: monospace; font-size: 11px;"
            )
            self.setStyleSheet(
                f"QWidget#CommandItemWidget {{ background-color: #27272A;{_hl} }}"
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
