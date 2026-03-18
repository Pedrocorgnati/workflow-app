"""
Base widgets for Workflow App (module-02/TASK-5).

Provides reusable widgets that appear throughout the UI:
  - StatusBadge:       colored dot + text label for CommandStatus
  - ModelBadge:        colored pill badge for ModelType
  - TimerWidget:       MM:SS stopwatch using QTimer
  - ProgressBarWidget: "X/Y" counter + amber progress bar
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QWidget,
)

from workflow_app.domain import CommandStatus, ModelType

# ── Palette (Graphite Amber theme) ──────────────────────────────────────────

_STATUS_COLORS: dict[CommandStatus, tuple[str, str]] = {
    # (dot_color, display_text)
    CommandStatus.PENDENTE:   ("#6B7280", "Pendente"),
    CommandStatus.EXECUTANDO: ("#FBBF24", "Executando"),
    CommandStatus.CONCLUIDO:  ("#22C55E", "Concluido"),
    CommandStatus.ERRO:       ("#EF4444", "Erro"),
    CommandStatus.PULADO:     ("#60A5FA", "Pulado"),
    CommandStatus.INCERTO:    ("#F97316", "Incerto"),
}

_MODEL_COLORS: dict[ModelType, tuple[str, str]] = {
    # (bg_color, display_label)
    ModelType.OPUS:   ("#7C3AED", "Opus"),
    ModelType.SONNET: ("#2563EB", "Sonnet"),
    ModelType.HAIKU:  ("#16A34A", "Haiku"),
}

_SURFACE = "#27272A"
_TEXT_PRIMARY = "#F4F4F5"
_TEXT_MUTED = "#A1A1AA"


# ── StatusBadge ─────────────────────────────────────────────────────────────

class StatusBadge(QWidget):
    """Composite widget: colored dot + text label for CommandStatus.

    Example:
        badge = StatusBadge(CommandStatus.EXECUTANDO)
        badge.set_status(CommandStatus.CONCLUIDO)
    """

    _DOT_SIZE = 8  # px

    def __init__(
        self,
        status: CommandStatus = CommandStatus.PENDENTE,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._status = status
        self._setup_ui()
        self._apply_status()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        self._dot = QLabel()
        self._dot.setFixedSize(self._DOT_SIZE, self._DOT_SIZE)

        self._label = QLabel()
        self._label.setStyleSheet(f"color: {_TEXT_PRIMARY}; font-size: 11px;")

        layout.addWidget(self._dot)
        layout.addWidget(self._label)

    def _apply_status(self) -> None:
        color, text = _STATUS_COLORS.get(
            self._status, ("#6B7280", str(self._status.value))
        )
        self._dot.setStyleSheet(
            f"background-color: {color};"
            f" border-radius: {self._DOT_SIZE // 2}px;"
        )
        self._label.setText(text)

    def set_status(self, status: CommandStatus) -> None:
        """Update the status and repaint."""
        self._status = status
        self._apply_status()

    @property
    def status(self) -> CommandStatus:
        return self._status


# ── ModelBadge ──────────────────────────────────────────────────────────────

class ModelBadge(QLabel):
    """Colored badge pill for ModelType.

    Example:
        badge = ModelBadge(ModelType.OPUS)
        badge.set_model(ModelType.HAIKU)
    """

    def __init__(
        self,
        model: ModelType = ModelType.SONNET,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._model = model
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setContentsMargins(6, 2, 6, 2)
        self._apply_model()

    def _apply_model(self) -> None:
        bg, label = _MODEL_COLORS.get(
            self._model, ("#374151", str(self._model.value))
        )
        self.setText(label)
        self.setStyleSheet(
            f"background-color: {bg}; color: #FFFFFF;"
            f" border-radius: 4px; padding: 1px 6px;"
            f" font-size: 11px; font-weight: 600;"
        )

    def set_model(self, model: ModelType) -> None:
        """Update the displayed model."""
        self._model = model
        self._apply_model()

    @property
    def model_type(self) -> ModelType:
        return self._model


# ── TimerWidget ─────────────────────────────────────────────────────────────

class TimerWidget(QLabel):
    """Stopwatch displaying MM:SS. Updates every second via QTimer.

    Example:
        timer = TimerWidget()
        timer.start()   # begin counting
        timer.stop()    # pause
        timer.reset()   # reset to 00:00 and stop
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._elapsed_seconds: int = 0
        self._running: bool = False
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            f"color: {_TEXT_MUTED}; font-size: 13px; letter-spacing: 1px;"
            " font-family: 'JetBrains Mono', 'Consolas', monospace;"
        )
        self._render()

    def _tick(self) -> None:
        self._elapsed_seconds += 1
        self._render()

    def _render(self) -> None:
        minutes, seconds = divmod(self._elapsed_seconds, 60)
        self.setText(f"{minutes:02d}:{seconds:02d}")

    def start(self) -> None:
        """Start or resume the stopwatch."""
        if not self._running:
            self._running = True
            self._timer.start()

    def stop(self) -> None:
        """Pause the stopwatch (keeps accumulated time)."""
        if self._running:
            self._running = False
            self._timer.stop()

    def reset(self) -> None:
        """Reset the time to zero and stop the stopwatch."""
        self.stop()
        self._elapsed_seconds = 0
        self._render()

    def set_elapsed(self, seconds: int) -> None:
        """Set the elapsed time directly (useful for restoring pipeline state)."""
        self._elapsed_seconds = seconds
        self._render()

    @property
    def elapsed_seconds(self) -> int:
        return self._elapsed_seconds


# ── ProgressBarWidget ────────────────────────────────────────────────────────

class ProgressBarWidget(QWidget):
    """Progress bar with 'X/Y' counter text and amber fill.

    Example:
        pb = ProgressBarWidget()
        pb.update_progress(3, 10)  # shows "3/10" + 30%
    """

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._completed = 0
        self._total = 0
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self._label = QLabel("0/0")
        self._label.setStyleSheet(
            f"color: {_TEXT_MUTED}; font-size: 11px;"
        )
        self._label.setFixedWidth(50)
        self._label.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        self._bar = QProgressBar()
        self._bar.setRange(0, 100)
        self._bar.setValue(0)
        self._bar.setTextVisible(False)
        self._bar.setFixedHeight(6)
        self._bar.setStyleSheet(
            f"QProgressBar {{ background-color: {_SURFACE};"
            " border: none; border-radius: 3px; }"
            "QProgressBar::chunk { background-color: #FBBF24; border-radius: 3px; }"
        )

        layout.addWidget(self._label)
        layout.addWidget(self._bar, stretch=1)

    def update_progress(self, completed: int, total: int) -> None:
        """Update the progress display.

        Args:
            completed: commands completed (or with error/skip).
            total: total commands in the pipeline.
        """
        self._completed = completed
        self._total = total
        self._label.setText(f"{completed}/{total}")
        percentage = int((completed / total) * 100) if total > 0 else 0
        self._bar.setValue(percentage)

    def reset(self) -> None:
        self.update_progress(0, 0)
