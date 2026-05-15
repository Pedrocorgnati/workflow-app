"""
QueueProgressRing - widget circular discreto que conta entradas da
`queue-command-list` (modelo discreto, nao temporal).

Cada entrada de `queue-command-list` ja eh um `CommandSpec` (inclui /clear,
/model, /effort e o comando real). A proporcao "scaffolding rapido +
comando real lento" eh ESPERADA e ACEITAVEL: o ring nao mede tempo, mede
progresso discreto de etapas (ver _DECISIONS-ITERS-9-11.md > Iter 11 > GAP 4.4).

testid: "queue-progress-ring"
tooltip: <= 60 chars
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import QWidget


class QueueProgressRing(QWidget):
    """Ring discreto. Total = entradas totais; Done = entradas ja executadas."""

    _COLOR_TRACK = QColor("#27272A")
    _COLOR_FILL = QColor("#FBBF24")
    _COLOR_TEXT = QColor("#D4D4D8")
    _COLOR_MUTE = QColor("#71717A")

    _DEFAULT_DIAMETER = 36
    _STROKE_WIDTH = 16

    progress_changed = Signal(int, int)  # done, total

    def __init__(self, parent: QWidget | None = None, *, diameter: int = _DEFAULT_DIAMETER) -> None:
        super().__init__(parent)
        self.setObjectName("QueueProgressRing")
        self.setProperty("testid", "queue-progress-ring")
        self._diameter = max(20, int(diameter))
        self.setFixedSize(self._diameter, self._diameter)
        self.setToolTip("Progresso discreto: etapas concluidas / total")
        self._done = 0
        self._total = 0

    # ------------------------------------------------------------------ API

    def set_progress(self, done: int, total: int) -> None:
        done = max(0, int(done))
        total = max(0, int(total))
        if done > total:
            done = total
        if done == self._done and total == self._total:
            return
        self._done = done
        self._total = total
        self.update()
        self.progress_changed.emit(done, total)

    def done(self) -> int:
        return self._done

    def total(self) -> int:
        return self._total

    def fraction(self) -> float:
        if self._total <= 0:
            return 0.0
        return self._done / self._total

    # ---------------------------------------------------------------- paint

    def paintEvent(self, _event) -> None:  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        pad = self._STROKE_WIDTH
        rect = QRectF(pad / 2, pad / 2, self._diameter - pad, self._diameter - pad)

        # Track
        pen = QPen(self._COLOR_TRACK)
        pen.setWidth(self._STROKE_WIDTH)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(pen)
        painter.drawArc(rect, 0, 360 * 16)

        # Fill arc
        if self._total > 0 and self._done > 0:
            span = int(360 * 16 * self.fraction())
            fill_pen = QPen(self._COLOR_FILL)
            fill_pen.setWidth(self._STROKE_WIDTH)
            fill_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(fill_pen)
            # Start at top (90deg in Qt units = 90 * 16) and go clockwise (-span)
            painter.drawArc(rect, 90 * 16, -span)

        # Center text: percentual concluido ou "-" quando vazio
        if self._total <= 0:
            text = "-"
            color = self._COLOR_MUTE
        else:
            pct = int(round(self.fraction() * 100))
            text = f"{pct}%"
            color = self._COLOR_TEXT
        painter.setPen(color)
        font = painter.font()
        font.setPointSize(max(6, int(self._diameter / 5)))
        painter.setFont(font)
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
