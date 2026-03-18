"""
StatusBadge — Colored dot indicator for command status.

Colors per DESIGN.md section 2.3:
  Pendente   → #52525B
  Executando → #3B82F6 (pulsing animation)
  Concluido  → #22C55E
  Erro       → #EF4444
  Pulado     → #52525B (with strikethrough text)
  Incerto    → #FBBF24
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from workflow_app.domain import CommandStatus

_STATUS_COLOR: dict[CommandStatus, str] = {
    CommandStatus.PENDENTE:   "#52525B",
    CommandStatus.EXECUTANDO: "#3B82F6",
    CommandStatus.CONCLUIDO:  "#22C55E",
    CommandStatus.ERRO:       "#EF4444",
    CommandStatus.PULADO:     "#52525B",
    CommandStatus.INCERTO:    "#FBBF24",
}

_STATUS_SYMBOL: dict[CommandStatus, str] = {
    CommandStatus.PENDENTE:   "○",
    CommandStatus.EXECUTANDO: "⊙",
    CommandStatus.CONCLUIDO:  "✓",
    CommandStatus.ERRO:       "✕",
    CommandStatus.PULADO:     "─",
    CommandStatus.INCERTO:    "?",
}


class StatusDot(QWidget):
    """8px colored dot indicator that pulses when EXECUTANDO."""

    def __init__(self, status: CommandStatus = CommandStatus.PENDENTE, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(10, 10)
        self._color = QColor(_STATUS_COLOR[status])
        self._opacity = 1.0
        self._pulse_timer: QTimer | None = None
        self._pulse_rising = False

        if status == CommandStatus.EXECUTANDO:
            self._start_pulse()

    def set_status(self, status: CommandStatus) -> None:
        self._color = QColor(_STATUS_COLOR[status])
        if status == CommandStatus.EXECUTANDO:
            self._start_pulse()
        else:
            self._stop_pulse()
            self._opacity = 1.0
        self.update()

    def _start_pulse(self) -> None:
        if self._pulse_timer is None:
            self._pulse_timer = QTimer(self)
            self._pulse_timer.setInterval(50)
            self._pulse_timer.timeout.connect(self._tick_pulse)
            self._opacity = 0.5
        self._pulse_timer.start()

    def _stop_pulse(self) -> None:
        if self._pulse_timer:
            self._pulse_timer.stop()

    def _tick_pulse(self) -> None:
        step = 0.04
        if self._pulse_rising:
            self._opacity = min(1.0, self._opacity + step)
            if self._opacity >= 1.0:
                self._pulse_rising = False
        else:
            self._opacity = max(0.5, self._opacity - step)
            if self._opacity <= 0.5:
                self._pulse_rising = True
        self.update()

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self._color)
        color.setAlphaF(self._opacity)
        painter.setBrush(color)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.drawEllipse(1, 1, 8, 8)
