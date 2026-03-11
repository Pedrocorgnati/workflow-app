"""
MetricsBar — 48px top toolbar for pipeline controls and metrics.

Layout (left to right):
  [+] [▶] [⏸] │ N/M [progress bar] HH:MM:SS │ ~Xk tokens [err badge] │ [🕐][▤][⚙]

Specs:
  Height: 48px fixed
  Background: #27272A
  Border-bottom: 1px solid #3F3F46
  Buttons: 32×32px
"""

from __future__ import annotations

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QWidget,
)

from workflow_app.signal_bus import signal_bus


class MetricsBar(QWidget):
    """48px pipeline control and metrics toolbar."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MetricsBar")
        self.setFixedHeight(48)
        self.setStyleSheet(
            "background-color: #27272A; border-bottom: 1px solid #3F3F46;"
        )

        self._elapsed_seconds = 0
        self._total = 0
        self._completed = 0
        self._errors = 0
        self._tokens = 0
        self._running = False

        self._elapsed_timer = QTimer(self)
        self._elapsed_timer.setInterval(1000)
        self._elapsed_timer.timeout.connect(self._on_tick)

        self._setup_ui()
        self._connect_signals()

    # ─────────────────────────────────────────────────────────── UI ──── #

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(4)

        # ── Controls ──────────────────────────────────────────────────── #
        self._btn_new = self._make_icon_btn("＋", "Novo Pipeline (Ctrl+N)")
        self._btn_run = self._make_icon_btn("▶", "Iniciar / Retomar (Ctrl+R)")
        self._btn_pause = self._make_icon_btn("⏸", "Pausar (Ctrl+P)")
        self._btn_run.setEnabled(False)
        self._btn_pause.setEnabled(False)

        layout.addWidget(self._btn_new)
        layout.addWidget(self._btn_run)
        layout.addWidget(self._btn_pause)
        layout.addWidget(self._make_separator())

        # ── Progress area ─────────────────────────────────────────────── #
        self._counter_label = QLabel("0/0")
        self._counter_label.setObjectName("MetricsBarCounter")
        self._counter_label.setStyleSheet(
            "color: #FBBF24; font-size: 12px; font-weight: 600;"
            " min-width: 36px;"
        )
        layout.addWidget(self._counter_label)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 100)
        self._progress_bar.setValue(0)
        self._progress_bar.setFixedHeight(6)
        self._progress_bar.setMinimumWidth(80)
        self._progress_bar.setMaximumWidth(160)
        self._progress_bar.setTextVisible(False)
        layout.addWidget(self._progress_bar)

        self._elapsed_label = QLabel("00:00")
        self._elapsed_label.setObjectName("MetricsBarValue")
        self._elapsed_label.setStyleSheet(
            "color: #FAFAFA; font-size: 14px; font-family: monospace;"
            " font-weight: 600; min-width: 56px;"
        )
        layout.addWidget(self._elapsed_label)
        layout.addWidget(self._make_separator())

        # ── Token counter ─────────────────────────────────────────────── #
        self._tokens_label = QLabel()
        self._tokens_label.setObjectName("MetricsBarLabel")
        self._tokens_label.setStyleSheet("color: #71717A; font-size: 12px;")
        self._tokens_label.setVisible(False)
        layout.addWidget(self._tokens_label)

        # ── Error badge ───────────────────────────────────────────────── #
        self._error_badge = QLabel()
        self._error_badge.setStyleSheet(
            "background-color: #EF4444; color: white; font-size: 11px;"
            " border-radius: 10px; padding: 2px 8px; font-weight: 600;"
        )
        self._error_badge.setVisible(False)
        layout.addWidget(self._error_badge)

        layout.addStretch(1)

        # ── Right controls ────────────────────────────────────────────── #
        self._btn_history = self._make_icon_btn("🕐", "Histórico")
        self._btn_history.setToolTip("Histórico de execuções")
        self._btn_dry_run = self._make_icon_btn("▤", "Dry Run")
        self._btn_dry_run.setToolTip("Validar sem executar")
        self._btn_prefs = self._make_icon_btn("⚙", "Preferências")
        self._btn_prefs.setToolTip("Preferências")

        layout.addWidget(self._btn_history)
        layout.addWidget(self._btn_dry_run)
        layout.addWidget(self._btn_prefs)

    def _make_icon_btn(self, icon: str, tooltip: str) -> QPushButton:
        btn = QPushButton(icon)
        btn.setObjectName("IconButton")
        btn.setFixedSize(32, 32)
        btn.setToolTip(tooltip)
        btn.setStyleSheet(
            "QPushButton { background-color: transparent; border: none;"
            "  border-radius: 4px; font-size: 15px; color: #FAFAFA; }"
            "QPushButton:hover { background-color: #3F3F46; }"
            "QPushButton:disabled { color: #52525B; }"
        )
        return btn

    def _make_separator(self) -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFixedWidth(1)
        sep.setStyleSheet("background-color: #3F3F46; margin: 8px 4px;")
        return sep

    # ─────────────────────────────────────────────────────── Signals ─── #

    def _connect_signals(self) -> None:
        self._btn_new.clicked.connect(self._on_new_pipeline)
        self._btn_run.clicked.connect(self._on_run)
        self._btn_pause.clicked.connect(self._on_pause)
        self._btn_history.clicked.connect(signal_bus.history_panel_toggled)
        self._btn_prefs.clicked.connect(signal_bus.preferences_requested)

        signal_bus.pipeline_started.connect(self._on_pipeline_started)
        signal_bus.pipeline_paused.connect(self._on_pipeline_paused)
        signal_bus.pipeline_resumed.connect(self._on_pipeline_resumed)
        signal_bus.pipeline_completed.connect(self._on_pipeline_completed)
        signal_bus.pipeline_cancelled.connect(self._on_pipeline_stopped)
        signal_bus.pipeline_ready.connect(self._on_pipeline_ready)
        signal_bus.metrics_updated.connect(self._on_metrics_updated)

    # ─────────────────────────────────────────────────────── Slots ───── #

    def _on_new_pipeline(self) -> None:
        signal_bus.toast_requested.emit("Criar novo pipeline", "info")

    def _on_run(self) -> None:
        if self._running:
            signal_bus.pipeline_resumed.emit()
        else:
            signal_bus.pipeline_started.emit()

    def _on_pause(self) -> None:
        signal_bus.pipeline_paused.emit()

    def _on_pipeline_ready(self, commands: list) -> None:
        self._total = len(commands)
        self._completed = 0
        self._errors = 0
        self._update_counter()
        self._btn_run.setEnabled(True)

    def _on_pipeline_started(self) -> None:
        self._running = True
        self._elapsed_timer.start()
        self._btn_run.setEnabled(False)
        self._btn_pause.setEnabled(True)

    def _on_pipeline_paused(self) -> None:
        self._running = False
        self._elapsed_timer.stop()
        self._btn_run.setEnabled(True)
        self._btn_pause.setEnabled(False)

    def _on_pipeline_resumed(self) -> None:
        self._on_pipeline_started()

    def _on_pipeline_completed(self) -> None:
        self._running = False
        self._elapsed_timer.stop()
        self._btn_run.setEnabled(False)
        self._btn_pause.setEnabled(False)

    def _on_pipeline_stopped(self) -> None:
        self._on_pipeline_completed()

    def _on_metrics_updated(self, completed: int, total: int) -> None:
        self._completed = completed
        self._total = total
        self._update_counter()

    def _on_tick(self) -> None:
        self._elapsed_seconds += 1
        hours = self._elapsed_seconds // 3600
        minutes = (self._elapsed_seconds % 3600) // 60
        seconds = self._elapsed_seconds % 60
        if hours:
            self._elapsed_label.setText(f"{hours:02d}:{minutes:02d}:{seconds:02d}")
        else:
            self._elapsed_label.setText(f"{minutes:02d}:{seconds:02d}")
        signal_bus.elapsed_tick.emit(self._elapsed_label.text())

    def _update_counter(self) -> None:
        self._counter_label.setText(f"{self._completed}/{self._total}")
        pct = int(self._completed / self._total * 100) if self._total else 0
        self._progress_bar.setValue(pct)

    def update_tokens(self, tokens: int) -> None:
        """Update token counter display."""
        self._tokens = tokens
        if tokens > 0:
            self._tokens_label.setText(f"~{tokens / 1000:.1f}k tok")
            self._tokens_label.setVisible(True)

    def update_errors(self, count: int) -> None:
        """Update error badge count."""
        self._errors = count
        if count > 0:
            self._error_badge.setText(f"{count} erro{'s' if count > 1 else ''}")
            self._error_badge.setVisible(True)
        else:
            self._error_badge.setVisible(False)
