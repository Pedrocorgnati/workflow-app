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
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget


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

        # Coluna central: percentual (topo) + count label (embutido externamente
        # via embed_count_label, ex: queue-count-label do MetricsBar).
        self._pct_label = QLabel("-", self)
        self._pct_label.setObjectName("QueueProgressRingPct")
        self._pct_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pct_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._pct_label.setStyleSheet(
            "background: transparent; color: #D4D4D8;"
            " font-size: 11px; font-weight: 600;"
        )

        self._count_label: QLabel | None = None

        self._center_layout = QVBoxLayout(self)
        self._center_layout.setContentsMargins(0, 0, 0, 0)
        self._center_layout.setSpacing(0)
        self._center_layout.addStretch(1)
        self._center_layout.addWidget(
            self._pct_label, alignment=Qt.AlignmentFlag.AlignCenter,
        )
        self._center_layout.addStretch(1)

    # ------------------------------------------------------------------ API

    def embed_count_label(self, label: QLabel) -> None:
        """Reparenteia o QLabel externo de count (queue-count-label) para
        dentro do ring, posicionado em coluna abaixo do percentual.

        Idempotente: chamadas subsequentes sao no-op se ja embutido.
        """
        if self._count_label is label:
            return
        if self._count_label is not None:
            self._center_layout.removeWidget(self._count_label)
        label.setParent(self)
        label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        # Limpa restricoes externas e aplica fonte menor centralizada.
        label.setFixedSize(0, 0)
        label.setMinimumSize(0, 0)
        label.setMaximumSize(16777215, 16777215)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label.setStyleSheet(
            "background: transparent; color: #A1A1AA;"
            " font-size: 10px; font-weight: 600;"
        )
        # Reordena: stretch / pct / count / stretch (centralizados como coluna).
        while self._center_layout.count():
            self._center_layout.takeAt(0)
        self._center_layout.addStretch(1)
        self._center_layout.addWidget(
            self._pct_label, alignment=Qt.AlignmentFlag.AlignCenter,
        )
        self._center_layout.addWidget(
            label, alignment=Qt.AlignmentFlag.AlignCenter,
        )
        self._center_layout.addStretch(1)
        self._count_label = label

    def set_progress(self, done: int, total: int) -> None:
        done = max(0, int(done))
        total = max(0, int(total))
        if done > total:
            done = total
        if done == self._done and total == self._total:
            return
        self._done = done
        self._total = total
        self._refresh_pct_label()
        self.update()
        self.progress_changed.emit(done, total)

    def _refresh_pct_label(self) -> None:
        if self._total <= 0:
            self._pct_label.setText("-")
            self._pct_label.setStyleSheet(
                "background: transparent; color: #71717A;"
                " font-size: 11px; font-weight: 600;"
            )
        else:
            pct = int(round(self.fraction() * 100))
            self._pct_label.setText(f"{pct}%")
            self._pct_label.setStyleSheet(
                "background: transparent; color: #D4D4D8;"
                " font-size: 11px; font-weight: 600;"
            )

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

        # Textos centrais (percentual + queue-count-label) renderizados via
        # QLabels filhos em _center_layout. Ver __init__ e embed_count_label.
