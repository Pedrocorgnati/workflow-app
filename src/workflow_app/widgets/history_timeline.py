"""History timeline widget for the per-module detail view (T-038).

Canonical source: ``detailed.md §9.3`` (DCP-9.3 — click-to-load behavior) plus
``delivery.schema.json`` ``HistoryEntry`` definition. The view is the vertical
timeline requested by TASK-038 (``GIVEN tab History -> THEN timeline vertical
com cada transicao (ator, data, reason)``).

A ``HistoryTimeline`` is a passive container: ``ModuleDetailView`` hands it a
pre-resolved ``list[HistoryEntry]`` via ``set_history`` and the widget renders
one row per entry. The color of each marker follows ``STATE_COLORS`` from
``views/kanban.py`` so the transition target is visually consistent with the
Kanban view.
"""

from __future__ import annotations

from typing import List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from workflow_app.models.delivery import HistoryEntry

_TEXT_PRIMARY = "#F4F4F5"
_TEXT_MUTED = "#A1A1AA"
_ITEM_BG = "#18181B"
_ITEM_BORDER = "#3F3F46"
_MARKER_SIZE = 10


class HistoryItem(QFrame):
    """Single history row (from -> to, timestamp, author, note)."""

    def __init__(
        self,
        entry: HistoryEntry,
        marker_color: str,
        index: int,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._entry = entry
        self._marker_color = marker_color

        self.setObjectName("HistoryItem")
        self.setProperty("testid", f"history-item-{index}")
        self.setStyleSheet(
            f"QFrame#HistoryItem {{"
            f"  background-color: {_ITEM_BG};"
            f"  border-left: 2px solid {_ITEM_BORDER};"
            f"  padding: 0px;"
            f"}}"
        )
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(10)

        marker = QLabel()
        marker.setFixedSize(_MARKER_SIZE, _MARKER_SIZE)
        marker.setStyleSheet(
            f"background-color: {self._marker_color};"
            f" border-radius: {_MARKER_SIZE // 2}px;"
            f" border: none;"
        )
        layout.addWidget(marker, alignment=Qt.AlignmentFlag.AlignTop)

        text_column = QVBoxLayout()
        text_column.setContentsMargins(0, 0, 0, 0)
        text_column.setSpacing(2)

        transition_label = QLabel(
            f"{self._entry.from_}  →  {self._entry.to}"
        )
        transition_label.setStyleSheet(
            f"color: {_TEXT_PRIMARY}; font-size: 12px; font-weight: 700;"
            f" background: transparent; border: none;"
        )
        text_column.addWidget(transition_label)

        timestamp_label = QLabel(self._entry.at)
        timestamp_label.setStyleSheet(
            f"color: {_TEXT_MUTED}; font-size: 10px;"
            f" font-family: 'JetBrains Mono', 'Consolas', monospace;"
            f" background: transparent; border: none;"
        )
        text_column.addWidget(timestamp_label)

        author = self._entry.by or "unknown"
        note = self._entry.note or ""
        note_text = f"{author}: {note}" if note else author
        note_label = QLabel(note_text)
        note_label.setWordWrap(True)
        note_label.setStyleSheet(
            f"color: {_TEXT_MUTED}; font-size: 11px;"
            f" background: transparent; border: none;"
        )
        text_column.addWidget(note_label)

        layout.addLayout(text_column, stretch=1)


class HistoryTimeline(QWidget):
    """Vertical timeline of ``HistoryEntry`` records.

    Usage::

        timeline = HistoryTimeline()
        timeline.set_history(module_state.history)
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._items: List[HistoryItem] = []

        self.setObjectName("HistoryTimeline")
        self.setProperty("testid", "history-timeline")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet(
            "QScrollArea { background-color: #0F0F11; border: none; }"
        )

        self._content = QWidget()
        self._content.setStyleSheet("background-color: #0F0F11;")
        self._content_layout = QVBoxLayout(self._content)
        self._content_layout.setContentsMargins(8, 8, 8, 8)
        self._content_layout.setSpacing(6)
        self._content_layout.addStretch(1)

        self._empty_label = QLabel("Nenhuma transicao registrada.")
        self._empty_label.setStyleSheet(
            f"color: {_TEXT_MUTED}; font-size: 11px;"
            f" background: transparent; border: none; padding: 12px;"
        )
        self._empty_label.setProperty("testid", "history-timeline-empty")
        self._empty_label.hide()

        self._scroll.setWidget(self._content)
        root.addWidget(self._scroll)
        root.addWidget(self._empty_label)

    def set_history(self, history: List[HistoryEntry]) -> None:
        """Render ``history`` in chronological order (oldest at top)."""
        self.clear()

        if not history:
            self._scroll.hide()
            self._empty_label.show()
            return

        self._scroll.show()
        self._empty_label.hide()

        # Late import to avoid a circular dependency with ``views.kanban``.
        from workflow_app.views.kanban import STATE_COLORS

        insert_position = self._content_layout.count() - 1  # before stretch
        for index, entry in enumerate(history):
            marker_color = STATE_COLORS.get(entry.to, "#6B7280")
            item = HistoryItem(
                entry=entry,
                marker_color=marker_color,
                index=index,
                parent=self._content,
            )
            self._content_layout.insertWidget(insert_position, item)
            insert_position += 1
            self._items.append(item)

    def clear(self) -> None:
        """Remove all rendered history items."""
        for item in self._items:
            self._content_layout.removeWidget(item)
            item.setParent(None)
            item.deleteLater()
        self._items.clear()
        self._empty_label.hide()
        self._scroll.show()

    @property
    def items(self) -> List[HistoryItem]:
        return list(self._items)


__all__ = ["HistoryTimeline", "HistoryItem"]
