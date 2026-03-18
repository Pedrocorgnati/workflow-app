"""
ExecutionHistoryWidget — Lista paginada de execuções passadas (module-14/TASK-2).

Integra com FilterPanel via apply_filter() e emite execution_selected(int)
quando o usuário seleciona uma linha.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from workflow_app.domain import FilterSpec
from workflow_app.history.history_manager import HistoryManager, PaginatedResult


class ExecutionHistoryWidget(QWidget):
    """Lista paginada de execuções passadas do pipeline."""

    execution_selected = Signal(int)  # pipeline_exec_id

    def __init__(
        self, history_manager: HistoryManager, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._mgr = history_manager
        self._current_filter: FilterSpec | None = None
        self._current_page = 1
        self._page_size = 20
        self._setup_ui()
        self._load_page()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        self._list = QListWidget()
        self._list.currentRowChanged.connect(self._on_row_changed)
        layout.addWidget(self._list)

        # Pagination controls
        nav = QHBoxLayout()
        self._btn_prev = QPushButton("◀ Anterior")
        self._btn_prev.clicked.connect(self._prev_page)
        self._page_label = QLabel("1/1")
        self._btn_next = QPushButton("Próxima ▶")
        self._btn_next.clicked.connect(self._next_page)
        nav.addWidget(self._btn_prev)
        nav.addStretch()
        nav.addWidget(self._page_label)
        nav.addStretch()
        nav.addWidget(self._btn_next)
        layout.addLayout(nav)

    # ─── Public ─────────────────────────────────────────────────────── #

    def apply_filter(self, spec: FilterSpec) -> None:
        """Aplica filtro e recarrega da página 1."""
        self._current_filter = spec
        self._current_page = 1
        self._load_page()

    def refresh(self) -> None:
        """Recarrega a página atual (útil após nova execução concluir)."""
        self._load_page()

    # ─── Internal ───────────────────────────────────────────────────── #

    def _load_page(self) -> None:
        try:
            result = self._mgr.list_executions(
                filter_spec=self._current_filter,
                page=self._current_page,
                page_size=self._page_size,
            )
        except Exception as exc:
            self._list.clear()
            item = QListWidgetItem(f"Erro ao carregar histórico: {exc}")
            self._list.addItem(item)
            return
        self._render(result)

    def _render(self, result: PaginatedResult) -> None:
        self._list.clear()
        if not result.items:
            item = QListWidgetItem("Nenhuma execução encontrada")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            self._list.addItem(item)
            self._page_label.setText("0/0")
            self._btn_prev.setEnabled(False)
            self._btn_next.setEnabled(False)
            return
        for pe in result.items:
            created = (
                pe.created_at.strftime("%Y-%m-%d %H:%M")
                if pe.created_at
                else "—"
            )
            label = f"{created}  {pe.status.upper()}  ID={pe.id}"
            item = QListWidgetItem(label)
            item.setData(256, pe.id)  # Qt.ItemDataRole.UserRole = 256
            self._list.addItem(item)

        self._page_label.setText(f"{result.page}/{result.total_pages}")
        self._btn_prev.setEnabled(result.page > 1)
        self._btn_next.setEnabled(result.page < result.total_pages)

    def _on_row_changed(self, row: int) -> None:
        item = self._list.item(row)
        if item is not None:
            exec_id = item.data(256)
            self.execution_selected.emit(exec_id)

    def _prev_page(self) -> None:
        if self._current_page > 1:
            self._current_page -= 1
            self._load_page()

    def _next_page(self) -> None:
        self._current_page += 1
        self._load_page()
