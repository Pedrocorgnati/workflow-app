"""State column widget for the Kanban view (T-036).

Renders one of the 9 DCP states (`pending`, `creation`, `execution`, `revision`,
`qa`, `deploy`, `done`, `blocked`, `rework`) as a vertical column with:

  - a colored header carrying the localized label + card count
  - a scrollable body that stacks ``ModuleCard`` widgets

The column is a passive container: the ``KanbanView`` owner drives insert /
clear through ``add_card`` / ``clear``. The color scheme follows DCP-9.3
(colors are supplied by the caller so the mapping lives in one place — see
``views/kanban.py``).
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from workflow_app.models.delivery import ModuleStateLiteral
from workflow_app.widgets.module_card import ModuleCard

_COLUMN_BG = "#1C1C1F"
_HEADER_TEXT = "#FFFFFF"
_COUNT_BG = "rgba(0, 0, 0, 0.25)"
_MIN_COLUMN_WIDTH = 210


class StateColumn(QWidget):
    """Single Kanban column for one DCP state.

    Usage::

        column = StateColumn("execution", "Execucao", "#FBBF24")
        column.add_card(ModuleCard(...))
        column.count()  # -> 1
        column.clear()
    """

    def __init__(
        self,
        state: ModuleStateLiteral,
        display_label: str,
        color: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._state = state
        self._display_label = display_label
        self._color = color
        self._cards: list[ModuleCard] = []

        self.setProperty("testid", f"kanban-col-{state}")
        self.setMinimumWidth(_MIN_COLUMN_WIDTH)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        self._setup_ui()
        self._update_header_text()

    # ─────────────────────────────────────────────────────────── UI ──── #

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header ───────────────────────────────────────────────────── #
        self._header = QFrame()
        self._header.setObjectName("StateColumnHeader")
        self._header.setFixedHeight(32)
        self._header.setStyleSheet(
            f"QFrame#StateColumnHeader {{"
            f"  background-color: {self._color};"
            f"  border-top-left-radius: 6px;"
            f"  border-top-right-radius: 6px;"
            f"}}"
        )
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(10, 0, 8, 0)
        header_layout.setSpacing(6)

        self._label = QLabel()
        self._label.setStyleSheet(
            f"color: {_HEADER_TEXT}; font-size: 12px; font-weight: 700;"
            f" background: transparent; border: none;"
        )
        header_layout.addWidget(self._label)
        header_layout.addStretch(1)

        self._count_badge = QLabel("0")
        self._count_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._count_badge.setMinimumWidth(22)
        self._count_badge.setStyleSheet(
            f"color: {_HEADER_TEXT}; font-size: 11px; font-weight: 700;"
            f" background-color: {_COUNT_BG}; border-radius: 9px;"
            f" padding: 2px 6px;"
        )
        header_layout.addWidget(self._count_badge)

        root.addWidget(self._header)

        # ── Scroll area (per TASK-036 Hint: usar QScrollArea por coluna) ─ #
        self._scroll = QScrollArea()
        self._scroll.setObjectName("StateColumnScroll")
        self._scroll.setWidgetResizable(True)
        self._scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._scroll.setStyleSheet(
            f"QScrollArea#StateColumnScroll {{"
            f"  background-color: {_COLUMN_BG};"
            f"  border: 1px solid #27272A;"
            f"  border-top: none;"
            f"  border-bottom-left-radius: 6px;"
            f"  border-bottom-right-radius: 6px;"
            f"}}"
        )

        self._scroll_content = QWidget()
        self._scroll_content.setStyleSheet(f"background-color: {_COLUMN_BG};")
        self._cards_layout = QVBoxLayout(self._scroll_content)
        self._cards_layout.setContentsMargins(8, 8, 8, 8)
        self._cards_layout.setSpacing(6)
        self._cards_layout.addStretch(1)

        self._scroll.setWidget(self._scroll_content)
        root.addWidget(self._scroll, stretch=1)

    def _update_header_text(self) -> None:
        self._label.setText(self._display_label)
        self._count_badge.setText(str(len(self._cards)))

    # ────────────────────────────────────────────────────────── API ──── #

    @property
    def state(self) -> ModuleStateLiteral:
        return self._state

    def count(self) -> int:
        return len(self._cards)

    def add_card(self, card: ModuleCard) -> None:
        """Insert a card at the end of the column (before the stretch)."""
        insert_index = self._cards_layout.count() - 1  # before the stretch
        self._cards_layout.insertWidget(insert_index, card)
        self._cards.append(card)
        self._update_header_text()

    def clear(self) -> None:
        """Remove all cards from this column."""
        for card in self._cards:
            self._cards_layout.removeWidget(card)
            card.setParent(None)
            card.deleteLater()
        self._cards.clear()
        self._update_header_text()


__all__ = ["StateColumn"]
