"""
MainWindow — Workflow App shell (module-01/TASK-3).

Layout:
  ┌─────────────────────────────────────────────────┐
  │ MetricsBar (48px)                               │
  │ ConfigBar (36px)                                │
  ├────────────────────────────┬────────────────────┤
  │ OutputPanel (flex)         │ CommandQueueWidget  │
  │                            │ (280px)            │
  └────────────────────────────┴────────────────────┘

Window: resize(1280, 720), setMinimumSize(1024, 600)
Splitter: OutputPanel flex (stretch=1) | CommandQueue (min 240, max 360, default 280)
"""

from __future__ import annotations

import sys

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QKeySequence, QAction
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
from workflow_app.command_queue.add_command_dialog import AddCommandDialog
from workflow_app.config.config_bar import ConfigBar
from workflow_app.domain import CommandSpec
from workflow_app.interview.pipeline_creator_widget import PipelineCreatorWidget
from workflow_app.metrics_bar.metrics_bar import MetricsBar
from workflow_app.metrics_bar.preferences_dialog import PreferencesDialog
from workflow_app.output_panel.output_panel import OutputPanel
from workflow_app.signal_bus import signal_bus
from workflow_app.widgets.notification_banner import ToastNotification


class MainWindow(QMainWindow):
    """Main application window."""

    _SETTINGS_GEOMETRY = "MainWindow/geometry"
    _SETTINGS_SPLITTER = "MainWindow/splitterSizes"

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Workflow App")
        self.setMinimumSize(1024, 600)
        self.resize(1280, 720)
        self.setObjectName("MainWindow")

        self._settings = QSettings("SystemForge", "WorkflowApp")
        self._setup_ui()
        self._setup_shortcuts()
        self._connect_signals()
        self._restore_state()

    # ─────────────────────────────────────────────────────────── UI ──── #

    def _setup_ui(self) -> None:
        central = QWidget()
        central.setObjectName("CentralWidget")
        central.setStyleSheet("background-color: #18181B;")
        self.setCentralWidget(central)

        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # MetricsBar (48px)
        self._metrics_bar = MetricsBar(parent=self)
        root_layout.addWidget(self._metrics_bar)

        # ConfigBar (36px)
        self._config_bar = ConfigBar(parent=self)
        root_layout.addWidget(self._config_bar)

        # Splitter: OutputPanel | CommandQueue
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setObjectName("MainSplitter")
        self._splitter.setHandleWidth(1)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setStyleSheet(
            "QSplitter::handle { background-color: #52525B; width: 1px; }"
        )

        self._output_panel = OutputPanel(parent=self)
        self._splitter.addWidget(self._output_panel)
        self._splitter.setStretchFactor(0, 1)

        self._command_queue = CommandQueueWidget(parent=self)
        self._splitter.addWidget(self._command_queue)
        self._splitter.setStretchFactor(1, 0)

        root_layout.addWidget(self._splitter, stretch=1)

        # Toast notification (floating)
        self._toast = ToastNotification(parent=central)

    def _setup_shortcuts(self) -> None:
        new_pipeline = QAction("Novo Pipeline", self)
        new_pipeline.setShortcut(QKeySequence("Ctrl+N"))
        new_pipeline.triggered.connect(self._open_pipeline_creator)
        self.addAction(new_pipeline)

    def _connect_signals(self) -> None:
        self._command_queue.new_pipeline_requested.connect(self._open_pipeline_creator)
        self._command_queue.add_command_requested.connect(self._open_add_command)
        signal_bus.toast_requested.connect(self._show_toast)
        signal_bus.preferences_requested.connect(self._open_preferences)
        signal_bus.pipeline_ready.connect(self._on_pipeline_ready)
        self._metrics_bar._btn_new.clicked.connect(self._open_pipeline_creator)

    # ─────────────────────────────────────────────────────── State ───── #

    def _save_state(self) -> None:
        self._settings.setValue(self._SETTINGS_GEOMETRY, self.saveGeometry())
        self._settings.setValue(self._SETTINGS_SPLITTER, self._splitter.sizes())

    def _restore_state(self) -> None:
        geometry = self._settings.value(self._SETTINGS_GEOMETRY)
        if geometry:
            self.restoreGeometry(geometry)
        splitter_sizes = self._settings.value(self._SETTINGS_SPLITTER)
        if splitter_sizes:
            try:
                self._splitter.setSizes([int(s) for s in splitter_sizes])
            except (ValueError, TypeError):
                pass

    def closeEvent(self, event) -> None:  # noqa: N802
        self._save_state()
        super().closeEvent(event)

    # ─────────────────────────────────────────────────────── Slots ───── #

    def _open_pipeline_creator(self) -> None:
        dialog = PipelineCreatorWidget(parent=self)
        dialog.pipeline_ready.connect(self._on_pipeline_ready)
        dialog.save_as_template_requested.connect(self._on_save_template)
        dialog.exec()

    def _open_add_command(self) -> None:
        next_pos = len(self._command_queue._items) + 1
        dialog = AddCommandDialog(next_position=next_pos, parent=self)
        dialog.command_added.connect(self._on_command_added)
        dialog.exec()

    def _open_preferences(self) -> None:
        dialog = PreferencesDialog(parent=self)
        if dialog.exec():
            settings = dialog.get_settings()
            self._output_panel.set_max_lines(settings["buffer_lines"])

    def _on_pipeline_ready(self, commands: list[CommandSpec]) -> None:
        self._command_queue.load_pipeline(commands)
        signal_bus.pipeline_ready.emit(commands)
        self._metrics_bar._btn_run.setEnabled(True)
        self._show_toast(
            f"Pipeline carregado: {len(commands)} comandos", "success"
        )

    def _on_command_added(self, spec: CommandSpec) -> None:
        # TODO: Add to existing queue — module-11 integration
        pass

    def _on_save_template(self, commands: list[CommandSpec]) -> None:
        # TODO: Open SaveTemplateDialog — module-05 integration
        self._show_toast("Template salvo (stub)", "info")

    def _show_toast(self, message: str, msg_type: str = "info") -> None:
        self._toast.show_toast(message, msg_type)


# ──────────────────────────────────────────────────────── Entry point ─── #


def main() -> None:
    app = QApplication(sys.argv)
    app.setApplicationName("Workflow App")
    app.setOrganizationName("SystemForge")

    # Apply D19 Graphite Amber theme
    from workflow_app.theme import apply_theme
    apply_theme(app)

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
