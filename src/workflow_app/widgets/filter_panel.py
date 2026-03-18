"""
FilterPanel — Filtros de histórico por status, data e projeto (module-14/TASK-2).

Emite filter_changed(FilterSpec) quando o usuário clica "Filtrar" ou "Limpar".
"""

from __future__ import annotations

from PySide6.QtCore import QDate, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDateEdit,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from workflow_app.domain import FilterSpec, PipelineStatus


class FilterPanel(QWidget):
    """Painel de filtros para o histórico de execuções."""

    filter_changed = Signal(object)  # emits FilterSpec

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(8)

        # Status filter
        layout.addWidget(QLabel("Status:"))
        self._status_combo = QComboBox()
        self._status_combo.addItem("Todos", None)
        for status in PipelineStatus:
            self._status_combo.addItem(status.value.capitalize(), status)
        layout.addWidget(self._status_combo)

        # Date from
        layout.addWidget(QLabel("De:"))
        self._date_from = QDateEdit()
        self._date_from.setSpecialValueText("Qualquer")
        self._date_from.setDate(QDate.currentDate().addDays(-30))
        self._date_from.setCalendarPopup(True)
        layout.addWidget(self._date_from)

        # Date to
        layout.addWidget(QLabel("Até:"))
        self._date_to = QDateEdit()
        self._date_to.setDate(QDate.currentDate())
        self._date_to.setCalendarPopup(True)
        layout.addWidget(self._date_to)

        # Buttons
        btn_apply = QPushButton("Filtrar")
        btn_apply.clicked.connect(self._emit_filter)
        layout.addWidget(btn_apply)

        btn_clear = QPushButton("Limpar")
        btn_clear.clicked.connect(self._clear_filters)
        layout.addWidget(btn_clear)

        layout.addStretch()

    def _emit_filter(self) -> None:
        status = self._status_combo.currentData()  # PipelineStatus | None
        date_from = self._date_from.date().toString("yyyy-MM-dd")
        date_to = self._date_to.date().toString("yyyy-MM-dd")
        spec = FilterSpec(status=status, date_from=date_from, date_to=date_to)
        self.filter_changed.emit(spec)

    def _clear_filters(self) -> None:
        self._status_combo.setCurrentIndex(0)
        self._date_from.setDate(QDate.currentDate().addDays(-30))
        self._date_to.setDate(QDate.currentDate())
        self.filter_changed.emit(FilterSpec())
