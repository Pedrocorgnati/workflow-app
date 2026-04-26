"""Module card widget for the Kanban view (T-036).

Renders a single module as a clickable card with:
  - module_id (bold) + attempt badge
  - module_type icon + label
  - last_transition timestamp (ISO short form)
  - colored border matching the module state (per DCP-9.3)

The card emits ``clicked(module_id: str)`` on mouse press. Integration with a
full detail view is deferred to T-038; the Kanban view connects this signal to
a toast placeholder in T-036.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QVBoxLayout, QWidget

from workflow_app.models.delivery import ModuleState, ModuleType

# ── Module type icons (per DCP-5.4 module_type enum, 10 valores) ──────────── #

MODULE_TYPE_ICONS: dict[ModuleType, str] = {
    "foundations":  "\U0001F3D7",  # 🏗
    "landing-page": "\U0001F3AF",  # 🎯
    "dashboard":    "\U0001F4CA",  # 📊
    "crud":         "\U0001F5C3",  # 🗃
    "auth":         "\U0001F510",  # 🔐
    "integration":  "\U0001F50C",  # 🔌
    "payment":      "\U0001F4B3",  # 💳
    "backoffice":   "\u2699",      # ⚙
    "infra-only":   "\U0001F6E0",  # 🛠
    "api-only":     "\U0001F517",  # 🔗
}

_TEXT_PRIMARY = "#F4F4F5"
_TEXT_MUTED = "#A1A1AA"
_CARD_BG = "#18181B"
_CARD_BG_HOVER = "#27272A"


def _format_last_transition(iso_ts: str) -> str:
    """Return a short form of an ISO-8601 UTC timestamp (``YYYY-MM-DD HH:MM``).

    Defensive: if parsing fails we fall back to the raw string so the UI never
    crashes on unexpected input.
    """
    if not iso_ts:
        return ""
    # Input shape from the model: ``YYYY-MM-DDTHH:MM:SS(.sss)?Z``
    date_part = iso_ts[:10]
    time_part = iso_ts[11:16] if len(iso_ts) >= 16 else ""
    if date_part and time_part:
        return f"{date_part} {time_part}"
    return iso_ts


class ModuleCard(QFrame):
    """Clickable card representing one module in the Kanban.

    Usage::

        card = ModuleCard("module-1-dashboard", state, border_color="#FBBF24")
        card.clicked.connect(lambda mid: print(f"clicked {mid}"))
    """

    clicked = Signal(str)

    def __init__(
        self,
        module_id: str,
        module_state: ModuleState,
        border_color: str,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._module_id = module_id
        self._module_state = module_state
        self._border_color = border_color

        self.setProperty("testid", f"kanban-card-{module_id}")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setObjectName("ModuleCard")
        self._apply_style()
        self._setup_ui()

    # ─────────────────────────────────────────────────────────── UI ──── #

    def _apply_style(self) -> None:
        self.setStyleSheet(
            f"QFrame#ModuleCard {{"
            f"  background-color: {_CARD_BG};"
            f"  border: 2px solid {self._border_color};"
            f"  border-radius: 6px;"
            f"}}"
            f"QFrame#ModuleCard:hover {{"
            f"  background-color: {_CARD_BG_HOVER};"
            f"}}"
        )

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 6, 8, 6)
        layout.setSpacing(4)

        # Line 1: module_id + attempt badge
        line1 = QHBoxLayout()
        line1.setContentsMargins(0, 0, 0, 0)
        line1.setSpacing(6)

        id_label = QLabel(self._module_id)
        id_label.setStyleSheet(
            f"color: {_TEXT_PRIMARY}; font-size: 12px; font-weight: 700;"
            f" background: transparent; border: none;"
        )
        line1.addWidget(id_label)
        line1.addStretch(1)

        attempt_label = QLabel(f"#{self._module_state.attempt}")
        attempt_label.setStyleSheet(
            f"color: {self._border_color}; font-size: 11px; font-weight: 700;"
            f" background: transparent; border: none;"
        )
        line1.addWidget(attempt_label)
        layout.addLayout(line1)

        # Line 2: module_type icon + label
        type_icon = MODULE_TYPE_ICONS.get(self._module_state.module_type, "\u25A0")
        type_label = QLabel(f"{type_icon}  {self._module_state.module_type}")
        type_label.setStyleSheet(
            f"color: {_TEXT_MUTED}; font-size: 11px;"
            f" background: transparent; border: none;"
        )
        layout.addWidget(type_label)

        # Line 3: last_transition (ISO short)
        transition_label = QLabel(
            _format_last_transition(self._module_state.last_transition)
        )
        transition_label.setStyleSheet(
            f"color: {_TEXT_MUTED}; font-size: 10px;"
            f" font-family: 'JetBrains Mono', 'Consolas', monospace;"
            f" background: transparent; border: none;"
        )
        layout.addWidget(transition_label)

    # ────────────────────────────────────────────────────────── API ──── #

    @property
    def module_id(self) -> str:
        return self._module_id

    @property
    def border_color(self) -> str:
        return self._border_color

    # ─────────────────────────────────────────────────────── Events ──── #

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self._module_id)
        super().mousePressEvent(event)


__all__ = ["MODULE_TYPE_ICONS", "ModuleCard"]
