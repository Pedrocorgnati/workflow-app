"""
ModelBadge — Colored pill badge for Claude model display.

Colors per DESIGN.md:
  Opus    → bg #7C3AED, text #FFFFFF
  Sonnet  → bg #2563EB, text #FFFFFF
  Haiku   → bg #059669, text #FFFFFF
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QWidget

from workflow_app.domain import ModelName

_MODEL_COLORS: dict[ModelName, tuple[str, str]] = {
    ModelName.OPUS:   ("#7C3AED", "#FFFFFF"),
    ModelName.SONNET: ("#2563EB", "#FFFFFF"),
    ModelName.HAIKU:  ("#059669", "#FFFFFF"),
}

_SHORT_NAME: dict[ModelName, str] = {
    ModelName.OPUS:   "Opus",
    ModelName.SONNET: "Son",
    ModelName.HAIKU:  "Hai",
}


class ModelBadge(QLabel):
    """Small badge showing the Claude model name with correct background color."""

    def __init__(self, model: ModelName, *, short: bool = True, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        bg, fg = _MODEL_COLORS.get(model, ("#3F3F46", "#FAFAFA"))
        text = _SHORT_NAME[model] if short else model.value
        self.setText(text)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            f"background-color: {bg}; color: {fg}; border-radius: 4px;"
            " padding: 2px 6px; font-size: 11px; font-weight: 600;"
        )
        self.setFixedHeight(18)
