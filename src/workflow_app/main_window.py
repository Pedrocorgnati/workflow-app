"""
MainWindow — Workflow App shell (module-01/TASK-3 + module-14/TASK-4).

Layout:
  ┌─────────────────────────────────────────────────────────────┐
  │ MetricsBar (48px)                                           │
  │ ConfigBar (48px)  [⬡ project]  [Workflow][Comandos][Toolbox]│
  ├─────────────────────────────────────────────────────────────┤
  │ ViewStack (QStackedWidget):                                 │
  │   Page 0 — Workflow:                                        │
  │     QSplitter: CommandQueueWidget(280px) | LeftTabWidget    │
  │       Tab 0: ToolboxHeader + OutputPanel                    │
  │       Tab 1: History (FilterPanel + list + detail)          │
  │   Page 1 — Comandos:                                        │
  │     TemplateBuilderWidget (full width)                      │
  │   Page 2 — Toolbox:                                         │
  │     ToolboxTab (full width)                                 │
  └─────────────────────────────────────────────────────────────┘

Window: resize(1280, 720), setMinimumSize(1024, 600)
"""

from __future__ import annotations

import logging
import sys

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QAction, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QMainWindow,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from workflow_app.command_queue.add_command_dialog import AddCommandDialog
from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
from workflow_app.config.app_state import app_state
from workflow_app.config.config_bar import ConfigBar
from workflow_app.config.config_parser import detect_config, parse_config
from workflow_app.domain import CommandSpec
from workflow_app.errors import ConfigError
from workflow_app.interview.pipeline_creator_widget import PipelineCreatorWidget
from workflow_app.metrics_bar.metrics_bar import MetricsBar
from workflow_app.metrics_bar.preferences_dialog import PreferencesDialog
from workflow_app.output_panel.output_panel import OutputPanel
from workflow_app.signal_bus import signal_bus
from workflow_app.template_builder.template_builder_widget import TemplateBuilderWidget
from workflow_app.widgets.execution_detail_panel import ExecutionDetailPanel
from workflow_app.widgets.execution_history_widget import ExecutionHistoryWidget
from workflow_app.widgets.filter_panel import FilterPanel
from workflow_app.widgets.toast_notifier import ToastNotifier
from workflow_app.widgets.toolbox_header import ToolboxHeader, ToolboxTab
from workflow_app.widgets.version_update_banner import VersionUpdateBanner

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    """Main application window."""

    _SETTINGS_GEOMETRY = "MainWindow/geometry"
    _SETTINGS_SPLITTER = "MainWindow/splitterSizes"
    _SETTINGS_LAST_CONFIG = "Project/lastConfigPath"

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SystemForge Desktop")
        self.setMinimumSize(640, 480)
        self.resize(1280, 720)
        self.setObjectName("MainWindow")

        # Pipeline execution state (RF03)
        self._pipeline_manager = None
        self._testid_overlays: list = []

        self._settings = QSettings("SystemForge", "WorkflowApp")
        self._setup_ui()
        self._setup_shortcuts()
        self._connect_signals()
        self._restore_state()
        self._attempt_startup_detection()
        self._setup_remote_server()

    # ─────────────────────────────────────────────────────────── UI ──── #

    def _setup_ui(self) -> None:
        central = QWidget()
        central.setObjectName("CentralWidget")
        central.setStyleSheet("background-color: #18181B;")
        self.setCentralWidget(central)

        root_layout = QVBoxLayout(central)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        # VersionUpdateBanner (hidden by default, shown when templates are outdated)
        self._version_banner = VersionUpdateBanner(parent=central)
        self._version_banner.update_requested.connect(self._on_version_update_requested)
        root_layout.addWidget(self._version_banner)

        # MetricsBar (48px)
        self._metrics_bar = MetricsBar(parent=self)
        root_layout.addWidget(self._metrics_bar)

        # ConfigBar (hidden — project selector moved into MetricsBar)
        self._config_bar = ConfigBar(parent=self)
        self._config_bar.hide()
        self._metrics_bar.config_change_requested.connect(self._on_config_change_requested)
        self._metrics_bar.config_unload_requested.connect(self._unload_config)

        # ── ViewStack: 3 pages switched by ConfigBar nav buttons ─────── #
        self._view_stack = QStackedWidget()
        self._view_stack.setObjectName("ViewStack")

        # ── Page 0: Workflow (splitter: CommandQueue + LeftTabWidget) ── #
        self._splitter = QSplitter(Qt.Orientation.Horizontal)
        self._splitter.setObjectName("MainSplitter")
        self._splitter.setHandleWidth(5)
        self._splitter.setChildrenCollapsible(False)
        self._splitter.setStyleSheet(
            "QSplitter::handle { background-color: #3F3F46; }"
            "QSplitter::handle:hover { background-color: #FBBF24; }"
        )

        # Left tabs: Output + Histórico only
        self._left_tabs = QTabWidget()
        self._left_tabs.setObjectName("LeftTabWidget")

        # Tab 0: Output (toolbox header + dual terminal)
        output_container = QWidget()
        output_layout = QVBoxLayout(output_container)
        output_layout.setContentsMargins(0, 0, 0, 0)
        output_layout.setSpacing(0)
        self._toolbox_header = ToolboxHeader(parent=output_container)
        output_layout.addWidget(self._toolbox_header)

        # Layout toggle button (row/column) + collapse chevron
        from PySide6.QtWidgets import QHBoxLayout as _HBox
        toggle_bar = QWidget()
        toggle_bar.setFixedHeight(22)
        toggle_bar.setStyleSheet("background-color: #1C1C1F; border-bottom: 1px solid #27272A;")
        toggle_layout = _HBox(toggle_bar)
        toggle_layout.setContentsMargins(4, 1, 4, 1)
        toggle_layout.setSpacing(2)
        toggle_layout.addStretch()
        self._layout_toggle_btn = QPushButton("\u2B95 \u25A1\u25A1")  # ⮕ □□ (side by side)
        self._layout_toggle_btn.setToolTip("Alternar layout: colunas / linhas")
        self._layout_toggle_btn.setProperty("testid", "terminal-layout-toggle")
        self._layout_toggle_btn.setFixedSize(36, 18)
        self._layout_toggle_btn.setStyleSheet(
            "QPushButton { background-color: #3F3F46; color: #A1A1AA;"
            "  border: 1px solid #52525B; border-radius: 3px;"
            "  font-size: 10px; font-weight: 700; }"
            "QPushButton:hover { background-color: #52525B; color: #FAFAFA; }"
            "QPushButton:pressed { background-color: #FBBF24; color: #18181B; }"
        )
        self._layout_toggle_btn.clicked.connect(self._toggle_terminal_layout)
        self._terminal_is_vertical = True  # starts as vertical (column)
        toggle_layout.addWidget(self._layout_toggle_btn)

        # Collapse chevron for autocast terminal
        self._autocast_collapsed = False
        self._collapse_chevron = QPushButton("\u25BE")  # ▾ expanded
        self._collapse_chevron.setToolTip("Colapsar terminal Autocast")
        self._collapse_chevron.setProperty("testid", "terminal-collapse-autocast")
        self._collapse_chevron.setFixedSize(22, 18)
        self._collapse_chevron.setStyleSheet(
            "QPushButton { background-color: #3F3F46; color: #A78BFA;"
            "  border: 1px solid #52525B; border-radius: 3px;"
            "  font-size: 10px; font-weight: 700; }"
            "QPushButton:hover { background-color: #52525B; color: #FAFAFA; }"
            "QPushButton:pressed { background-color: #FBBF24; color: #18181B; }"
        )
        self._collapse_chevron.clicked.connect(self._toggle_autocast_collapse)
        toggle_layout.addWidget(self._collapse_chevron)
        output_layout.addWidget(toggle_bar)

        # Dual terminal: splitter with interactive (top/left) + autocast (bottom/right)
        self._terminal_splitter = QSplitter(Qt.Orientation.Vertical)
        self._terminal_splitter.setHandleWidth(4)
        self._terminal_splitter.setChildrenCollapsible(False)
        self._terminal_splitter.setStyleSheet(
            "QSplitter::handle { background-color: #3F3F46; }"
            "QSplitter::handle:hover { background-color: #FBBF24; }"
        )

        from PySide6.QtWidgets import QLabel

        # Top/Left: Interactive terminal (user types here)
        self._interactive_wrapper = QWidget()
        interactive_layout = QVBoxLayout(self._interactive_wrapper)
        interactive_layout.setContentsMargins(0, 0, 0, 0)
        interactive_layout.setSpacing(0)
        interactive_label = QLabel(" INTERACTIVE")
        interactive_label.setFixedHeight(20)
        interactive_label.setStyleSheet(
            "QLabel { background-color: #1A2E05; color: #84CC16;"
            "  font-size: 10px; font-weight: 700; padding-left: 6px; }"
        )
        interactive_layout.addWidget(interactive_label)
        self._output_panel = OutputPanel(parent=self._interactive_wrapper)
        self._output_panel.setProperty("testid", "terminal-interactive")
        interactive_layout.addWidget(self._output_panel, stretch=1)
        self._terminal_splitter.addWidget(self._interactive_wrapper)

        # Bottom/Right: Autocast terminal (shows -p command output)
        self._autocast_wrapper = QWidget()
        autocast_layout = QVBoxLayout(self._autocast_wrapper)
        autocast_layout.setContentsMargins(0, 0, 0, 0)
        autocast_layout.setSpacing(0)
        autocast_label = QLabel(" AUTOCAST")
        autocast_label.setFixedHeight(20)
        autocast_label.setStyleSheet(
            "QLabel { background-color: #1E1B4B; color: #A78BFA;"
            "  font-size: 10px; font-weight: 700; padding-left: 6px; }"
        )
        autocast_layout.addWidget(autocast_label)
        self._autocast_panel = OutputPanel(parent=self._autocast_wrapper, autocast_mode=True)
        self._autocast_panel.setProperty("testid", "terminal-autocast")
        autocast_layout.addWidget(self._autocast_panel, stretch=1)
        self._terminal_splitter.addWidget(self._autocast_wrapper)

        self._terminal_splitter.setSizes([350, 350])
        output_layout.addWidget(self._terminal_splitter, stretch=1)
        self._left_tabs.addTab(output_container, "Output")

        # Tab 1: History
        self._history_panel = self._build_history_panel()
        self._left_tabs.addTab(self._history_panel, "Histórico")

        self._command_queue = CommandQueueWidget(parent=self)
        self._command_queue.setProperty("testid", "main-command-queue")
        self._splitter.addWidget(self._command_queue)
        self._splitter.setStretchFactor(0, 1)

        self._splitter.addWidget(self._left_tabs)
        self._splitter.setStretchFactor(1, 2)

        self._view_stack.addWidget(self._splitter)  # index 0

        # ── Page 1: Comandos (TemplateBuilderWidget, full width) ──────── #
        self._template_builder = TemplateBuilderWidget(parent=self)
        self._template_builder.setProperty("testid", "page-comandos")
        self._view_stack.addWidget(self._template_builder)  # index 1

        # ── Page 2: Toolbox (ToolboxTab, full width) ─────────────────── #
        self._toolbox_tab = ToolboxTab(parent=self)
        self._toolbox_tab.setProperty("testid", "page-toolbox")
        self._view_stack.addWidget(self._toolbox_tab)  # index 2

        root_layout.addWidget(self._view_stack, stretch=1)

        # Toast notification (floating, stacked, level-dependent duration)
        self._toast_notifier = ToastNotifier(central)

    def _build_history_panel(self) -> QWidget:
        """Cria o painel de histórico: FilterPanel + lista + detalhe.

        Se o DatabaseManager ainda não foi inicializado (ex: em testes),
        retorna um placeholder vazio sem levantar exceção.
        """
        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        try:
            from workflow_app.db.database_manager import db_manager
            from workflow_app.history.history_manager import HistoryManager

            history_mgr = HistoryManager(db_manager.session_factory)

            self._filter_panel = FilterPanel(parent=container)
            layout.addWidget(self._filter_panel)

            content_splitter = QSplitter(Qt.Orientation.Vertical)
            content_splitter.setChildrenCollapsible(False)

            self._history_list = ExecutionHistoryWidget(history_mgr, parent=container)
            content_splitter.addWidget(self._history_list)

            self._history_detail = ExecutionDetailPanel(history_mgr, parent=container)
            content_splitter.addWidget(self._history_detail)

            content_splitter.setSizes([300, 200])
            layout.addWidget(content_splitter, stretch=1)

            # Wire signals
            self._filter_panel.filter_changed.connect(self._history_list.apply_filter)
            self._history_list.execution_selected.connect(
                self._history_detail.load_execution
            )

        except RuntimeError:
            # db_manager not yet initialized (e.g. during tests without setup())
            from PySide6.QtWidgets import QLabel
            placeholder = QLabel("Histórico disponível após inicialização do banco.")
            placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(placeholder)

        return container

    def _setup_shortcuts(self) -> None:
        new_pipeline = QAction("Novo Pipeline", self)
        new_pipeline.setShortcut(QKeySequence("Ctrl+N"))
        new_pipeline.triggered.connect(self._open_pipeline_creator)
        self.addAction(new_pipeline)

        save_queue = QAction("Salvar Fila", self)
        save_queue.setShortcut(QKeySequence("Ctrl+S"))
        save_queue.triggered.connect(self._on_save_queue_state)
        self.addAction(save_queue)

    def _toggle_terminal_layout(self) -> None:
        """Toggle terminal splitter between vertical (column) and horizontal (row)."""
        if self._terminal_is_vertical:
            self._terminal_splitter.setOrientation(Qt.Orientation.Horizontal)
            self._layout_toggle_btn.setText("\u2B07 \u25A0\u25A0")  # ⬇ ■■ (stacked)
            self._layout_toggle_btn.setToolTip("Layout: lado a lado. Clique para empilhar")
            self._terminal_is_vertical = False
        else:
            self._terminal_splitter.setOrientation(Qt.Orientation.Vertical)
            self._layout_toggle_btn.setText("\u2B95 \u25A1\u25A1")  # ⮕ □□ (side by side)
            self._layout_toggle_btn.setToolTip("Layout: empilhado. Clique para lado a lado")
            self._terminal_is_vertical = True
        self._update_collapse_chevron()

    def _toggle_autocast_collapse(self) -> None:
        """Toggle collapse/expand of the autocast terminal."""
        if self._autocast_collapsed:
            self._autocast_wrapper.show()
            if hasattr(self, "_saved_splitter_sizes"):
                self._terminal_splitter.setSizes(self._saved_splitter_sizes)
            else:
                self._terminal_splitter.setSizes([350, 350])
            self._autocast_collapsed = False
            self._collapse_chevron.setToolTip("Colapsar terminal Autocast")
        else:
            self._saved_splitter_sizes = self._terminal_splitter.sizes()
            self._autocast_wrapper.hide()
            self._autocast_collapsed = True
            self._collapse_chevron.setToolTip("Expandir terminal Autocast")
        self._update_collapse_chevron()

    def _update_collapse_chevron(self) -> None:
        """Update chevron icon based on collapsed state."""
        if self._autocast_collapsed:
            self._collapse_chevron.setText("\u25B8")  # ▸ collapsed
        else:
            self._collapse_chevron.setText("\u25BE")  # ▾ expanded

    def _connect_signals(self) -> None:
        self._command_queue.new_pipeline_requested.connect(self._open_pipeline_creator)
        self._command_queue.add_command_requested.connect(self._open_add_command)
        self._command_queue.reorder_requested.connect(self._on_queue_reorder_requested)
        self._command_queue.save_requested.connect(self._on_save_queue_state)
        self._metrics_bar.view_changed.connect(self._on_view_changed)
        signal_bus.toast_requested.connect(self._show_toast)
        signal_bus.preferences_requested.connect(self._open_preferences)
        signal_bus.pipeline_ready.connect(self._on_pipeline_ready)
        signal_bus.history_panel_toggled.connect(self._switch_to_history_tab)
        signal_bus.pipeline_started.connect(self._switch_to_output_tab)
        signal_bus.datatest_toggled.connect(self._on_datatest_toggled)
        signal_bus.focus_interactive_terminal.connect(self._on_focus_interactive_terminal)
        signal_bus.pipeline_completed.connect(self._refresh_history_list)
        signal_bus.permission_request_received.connect(self._on_permission_request)
        # _btn_new removed — pipeline creator accessible via command queue or Ctrl+N
        # RF10: Dry Run handler
        signal_bus.dry_run_requested.connect(self._on_dry_run)
        # RF03: Pipeline execution control (guarded to prevent signal recursion)
        signal_bus.pipeline_paused.connect(self._on_pipeline_paused_for_pm)
        signal_bus.pipeline_resumed.connect(self._on_pipeline_resumed_for_pm)
        signal_bus.pipeline_retry_requested.connect(self._on_pipeline_retry_requested)
        signal_bus.pipeline_cancelled.connect(self._on_pipeline_cancel_for_pm)

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

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._settings.value(self._SETTINGS_SPLITTER):
            total = self._splitter.width()
            if total > 0:
                self._splitter.setSizes([total // 3, total * 2 // 3])

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
        # Annotate each spec with the relative config path when a project is loaded
        if app_state.has_config and app_state.config:
            import os
            abs_config = app_state.config.config_path
            project_dir = str(app_state.config.project_dir)
            try:
                rel = os.path.relpath(abs_config, project_dir)
            except ValueError:
                rel = abs_config
            for spec in commands:
                if spec.name.startswith("/model ") or spec.name == "/clear":
                    continue  # model-switch and /clear rows must never carry a config path
                spec.config_path = rel

        self._command_queue.load_pipeline(commands)
        # NOTE: do NOT emit signal_bus.pipeline_ready here — it is connected back
        # to this slot and would cause infinite recursion.
        signal_bus.pipeline_created.emit(commands)

        # RF03: Instantiate PipelineManager for this pipeline session.
        from workflow_app.db.database_manager import db_manager
        from workflow_app.pipeline.pipeline_manager import PipelineManager
        from workflow_app.sdk.sdk_adapter import SDKAdapter

        adapter = SDKAdapter()
        # cwd = raiz da systemForge (onde está .claude/commands/) para que os
        # slash commands sejam encontrados pelo claude-agent-sdk
        if app_state.has_config:
            workspace = str(app_state.config.project_dir)
        else:
            # Detect systemForge root by walking up from cwd looking for .claude/commands/
            from pathlib import Path
            _cwd = Path.cwd()
            workspace = str(_cwd)
            for p in [_cwd, *_cwd.parents]:
                if (p / ".claude" / "commands").is_dir() and (p / "CLAUDE.md").is_file():
                    workspace = str(p)
                    break
        self._pipeline_manager = PipelineManager(
            signal_bus=signal_bus,
            sdk_adapter=adapter,
            session_factory=db_manager.session_factory,
            workspace_dir=workspace,
        )
        self._pipeline_manager.set_queue(commands)
        self._command_queue.set_pipeline_manager(self._pipeline_manager)

        self._show_toast(
            f"Pipeline carregado: {len(commands)} comandos", "success"
        )

    def _on_command_added(self, spec: CommandSpec) -> None:
        # RESOLVED: G001 — append to existing queue
        self._command_queue.add_command(spec)
        self._show_toast(f"Comando adicionado: {spec.name}", "success")

    def _on_save_template(self, commands: list[CommandSpec]) -> None:
        from workflow_app.db.database_manager import db_manager
        from workflow_app.dialogs.save_template_dialog import SaveTemplateDialog
        from workflow_app.templates.template_manager import TemplateManager

        try:
            mgr = TemplateManager(db_manager)
            existing = [t.name for t in mgr.list_templates()]
        except Exception:
            existing = []

        dlg = SaveTemplateDialog(self, commands=commands, existing_names=existing)
        if dlg.exec() == SaveTemplateDialog.DialogCode.Accepted:
            try:
                mgr = TemplateManager(db_manager)
                mgr.save_custom_template(dlg.name, dlg.description, dlg.commands)
                self._show_toast(f"Template '{dlg.name}' salvo.", "success")
            except ValueError as exc:
                self._show_toast(str(exc), "error")

    def _on_config_change_requested(self, path: str) -> None:
        """Trata solicitação de troca de config vinda da ConfigBar."""
        self._load_config(path)
        if app_state.has_config and app_state.config and app_state.config.config_path == path:
            signal_bus.toast_requested.emit(
                f"Projeto carregado: {app_state.project_name}", "success"
            )

    def _on_view_changed(self, index: int) -> None:
        """Switch the main view stack (0=Workflow, 1=Comandos, 2=Toolbox)."""
        self._view_stack.setCurrentIndex(index)

    def _switch_to_output_tab(self) -> None:
        """Switch to Workflow view and activate the Output tab."""
        self._view_stack.setCurrentIndex(0)
        self._metrics_bar.set_active_view(0)
        self._left_tabs.setCurrentIndex(0)  # Output is always index 0

    def _switch_to_history_tab(self) -> None:
        """Switch to Workflow view and activate the Histórico tab."""
        self._view_stack.setCurrentIndex(0)
        self._metrics_bar.set_active_view(0)
        self._left_tabs.setCurrentIndex(1)  # Histórico is always index 1

    def _refresh_history_list(self) -> None:
        """Refresh the history list after a pipeline completes."""
        if hasattr(self, "_history_list"):
            self._history_list.refresh()

    def _show_toast(self, message: str, msg_type: str = "info") -> None:
        self._toast_notifier.show(message, msg_type)

    # ─────────────────────────────────── DataTest overlay & terminal focus ─ #

    def _on_focus_interactive_terminal(self) -> None:
        """Switch to output tab and focus the interactive terminal."""
        self._switch_to_output_tab()
        self._output_panel._terminal.setFocus()

    def _on_datatest_toggled(self, enabled: bool) -> None:
        """Toggle data-testid overlay display on all widgets."""
        if enabled:
            self._show_testid_overlays()
        else:
            self._hide_testid_overlays()

    def _show_testid_overlays(self) -> None:
        """Walk all child widgets and show floating red testid overlay labels.

        Overlays are parented to the central widget so they float beyond
        their target widget bounds. Click an overlay to copy its text.
        """
        self._hide_testid_overlays()
        from PySide6.QtCore import QPoint, QTimer
        from PySide6.QtWidgets import QApplication as _QApp, QLabel as _Lbl

        central = self.centralWidget()
        used_positions: list[tuple[int, int, int, int]] = []  # x, y, w, h

        _STYLE_NORMAL = (
            "background-color: rgba(220, 38, 38, 0.9); color: white;"
            " font-size: 11px; font-weight: 700; padding: 2px 6px;"
            " border-radius: 3px; border: none;"
        )
        _STYLE_COPIED = (
            "background-color: rgba(34, 197, 94, 0.9); color: white;"
            " font-size: 11px; font-weight: 700; padding: 2px 6px;"
            " border-radius: 3px; border: none;"
        )

        for widget in central.findChildren(QWidget):
            testid = widget.property("testid")
            if testid and not widget.property("_is_testid_overlay"):
                testid_str = str(testid)

                # Map widget position to central widget coordinates
                try:
                    pos = widget.mapTo(central, QPoint(0, 0))
                except RuntimeError:
                    continue
                x, y = pos.x(), pos.y()

                # Offset if overlapping with existing overlay
                for ux, uy, uw, uh in used_positions:
                    if abs(x - ux) < max(uw, 30) and abs(y - uy) < max(uh, 18):
                        y = uy + uh + 2

                overlay = _Lbl(testid_str, central)
                overlay.setStyleSheet(_STYLE_NORMAL)
                overlay.setProperty("_is_testid_overlay", True)
                overlay.setCursor(Qt.CursorShape.PointingHandCursor)
                overlay.setToolTip(f"Clique para copiar: {testid_str}")

                # Click to copy to clipboard with visual feedback
                def _make_click(lbl, text):
                    def _handler(_event):
                        _QApp.clipboard().setText(f'data-testid="{text}"')
                        lbl.setStyleSheet(_STYLE_COPIED)
                        QTimer.singleShot(600, lambda: lbl.setStyleSheet(_STYLE_NORMAL))
                    return _handler

                overlay.mousePressEvent = _make_click(overlay, testid_str)

                overlay.adjustSize()
                overlay.move(x, y)
                overlay.show()
                overlay.raise_()
                used_positions.append((x, y, overlay.width(), overlay.height()))
                self._testid_overlays.append(overlay)

    def _hide_testid_overlays(self) -> None:
        """Remove all testid overlay labels."""
        for overlay in self._testid_overlays:
            overlay.hide()
            overlay.deleteLater()
        self._testid_overlays.clear()

    def _on_permission_request(self, request_data: dict) -> None:
        """Show PermissionRequestDialog when the SDK needs user approval."""
        from workflow_app.dialogs.permission_request_dialog import (
            PermissionRequestDialog,
        )
        from workflow_app.sdk.sdk_adapter import SDKAdapter

        dlg = PermissionRequestDialog(parent=self, request_data=request_data)

        # Route permission response to the active PipelineManager's SDKAdapter.
        sdk_adapter: SDKAdapter | None = None
        if self._pipeline_manager is not None:
            sdk_adapter = self._pipeline_manager._sdk_adapter

        def _on_granted() -> None:
            if sdk_adapter is not None:
                sdk_adapter.respond_to_permission(True)

        def _on_rejected() -> None:
            if sdk_adapter is not None:
                sdk_adapter.respond_to_permission(False)
            self._show_toast("Permissão rejeitada.", "warning")

        dlg.permission_granted.connect(_on_granted)
        dlg.permission_rejected.connect(_on_rejected)
        dlg.exec()

    # ──────────────────────────────────────────── Config detection ──── #

    def _attempt_startup_detection(self) -> None:
        """Tenta detectar e carregar project.json automaticamente ao iniciar.

        Prioridade:
        1. Último config salvo no QSettings (persistência entre sessões)
        2. Auto-detecção via detect_config() (fallback)
        """
        from pathlib import Path

        last_path = self._settings.value(self._SETTINGS_LAST_CONFIG)
        if last_path and Path(last_path).exists():
            logger.info("Restaurando último config do QSettings: %s", last_path)
            self._load_config(last_path)
            return

        config_path = detect_config()
        if config_path:
            logger.info("Config detectado no startup: %s", config_path)
            self._load_config(config_path)
        else:
            logger.info("Nenhum config detectado no cwd. Modo sem projeto.")
            self._update_title(project_name=None)

    def _load_config(self, path: str) -> None:
        """Carrega um project.json e atualiza o estado da aplicação.

        Emite signal_bus.config_loaded em caso de sucesso.
        Exibe toast de erro em caso de falha.
        """
        try:
            config = parse_config(path)
        except (ConfigError, FileNotFoundError) as exc:
            logger.error("Falha ao carregar config '%s': %s", path, exc)
            signal_bus.toast_requested.emit(
                f"Falha ao carregar config: {exc.message if isinstance(exc, ConfigError) else str(exc)}",
                "error",
            )
            return

        app_state.set_config(config)
        self._update_title(project_name=config.project_name)
        self._settings.setValue(self._SETTINGS_LAST_CONFIG, path)
        signal_bus.config_loaded.emit(path)
        logger.info("Config carregado: projeto=%s", config.project_name)
        self._check_template_versions()  # RESOLVED: G002
        self._restore_queue_state_from_config(path)

    def _check_template_versions(self) -> None:
        """Check if factory templates are aligned with the current CLAUDE.md.  # RESOLVED: G002"""
        try:
            from workflow_app.db.database_manager import db_manager
            from workflow_app.templates.template_manager import TemplateManager
            from workflow_app.templates.version_checker import VersionChecker

            self._version_checker_mgr = TemplateManager(db_manager)
            self._version_checker = VersionChecker(self._version_checker_mgr)
            result = self._version_checker.check_factory_templates()
            if result.is_outdated:
                self._version_banner.set_outdated_names(result.outdated_names)
                self._version_banner.setVisible(True)
        except Exception:
            pass  # version check is non-critical

    def _on_version_update_requested(self) -> None:
        """Refresh factory templates with the current CLAUDE.md hash."""
        try:
            from workflow_app.db.database_manager import db_manager
            from workflow_app.templates.claude_md_hasher import compute_hash, find_claude_md
            from workflow_app.templates.factory_templates import refresh_factory_templates

            path = find_claude_md()
            new_hash = compute_hash(path) if path else None
            if new_hash:
                refresh_factory_templates(db_manager, new_hash)
                self._show_toast("Templates de fábrica atualizados.", "success")
            else:
                self._show_toast("CLAUDE.md não encontrado. Atualização cancelada.", "warning")
        except Exception as exc:
            logger.error("Erro ao atualizar templates de fábrica: %s", exc)
            self._show_toast("Falha ao atualizar templates.", "error")

    # ─────────────────────────────────── RF03: Pipeline execution control ─── #

    def _on_run_requested(self) -> None:
        """Called when ▶ is clicked — starts the active PipelineManager."""
        if self._pipeline_manager is not None:
            self._pipeline_manager.start()

    def _on_pipeline_paused_for_pm(self) -> None:
        """Guard-wrapped pause: prevents signal recursion (pm.pause() re-emits pipeline_paused)."""
        pm = self._pipeline_manager
        if pm is not None and not pm._paused:
            pm.pause()

    def _on_pipeline_resumed_for_pm(self) -> None:
        """Guard-wrapped resume: prevents signal recursion (pm.resume() re-emits pipeline_resumed)."""
        pm = self._pipeline_manager
        if pm is not None and pm._paused:
            pm.resume()

    def _on_pipeline_retry_requested(self, _index: int) -> None:
        """Retry the current ERRO command via PipelineManager."""
        if self._pipeline_manager is not None:
            self._pipeline_manager.retry_current()

    def _on_pipeline_cancel_for_pm(self) -> None:
        """Cancel the active pipeline, then clear the manager reference."""
        pm = self._pipeline_manager
        if pm is not None and pm._pipeline_exec_id is not None:
            self._pipeline_manager = None  # clear first to prevent re-entry
            pm.cancel()

    def _on_queue_reorder_requested(self, from_pos: int, to_pos: int) -> None:
        """Handle drag-and-drop reorder from CommandQueueWidget."""
        if self._pipeline_manager is None:
            return
        success = self._pipeline_manager.reorder_command(from_pos, to_pos)
        if success:
            self._refresh_queue_ui()

    def _refresh_queue_ui(self) -> None:
        """Reload the queue display from the pipeline manager's current queue."""
        if self._pipeline_manager is None:
            return
        self._command_queue.load_pipeline(self._pipeline_manager._queue)

    # ──────────────────────────────────────── RF10: Dry Run handler ─────── #

    def _on_dry_run(self) -> None:
        """Validate the current command queue offline via DryRunValidator."""
        from workflow_app.dry_run import DryRunValidator

        commands = [item.get_spec() for item in self._command_queue._items]
        if not commands:
            self._show_toast("Nenhum comando na fila para validar.", "warning")
            return

        report = DryRunValidator().validate(commands)
        if report.is_valid:
            warnings = len(report.warnings)
            msg = f"Dry Run: OK — {len(commands)} comando(s) válido(s)."
            if warnings:
                msg += f" {warnings} aviso(s)."
            self._show_toast(msg, "success")
        else:
            errors = len(report.errors)
            self._show_toast(
                f"Dry Run: {errors} erro(s) encontrado(s). Verifique a fila.", "warning"
            )

    # ──────────────────────────────────── RF11: Resume interrupted pipeline ─ #

    def _check_for_interrupted_pipeline(self) -> None:
        """After loading config, offer to resume an interrupted pipeline (RF11)."""
        try:
            from workflow_app.db.database_manager import db_manager
            from workflow_app.db.models import CommandExecution, PipelineExecution
            from workflow_app.dialogs.resume_dialog import ResumeDialog, ResumeInfo
            from workflow_app.domain import CommandStatus
            from workflow_app.pipeline.pipeline_manager import PipelineManager
            from workflow_app.sdk.sdk_adapter import SDKAdapter

            adapter = SDKAdapter()
            pm = PipelineManager(
                signal_bus=signal_bus,
                sdk_adapter=adapter,
                session_factory=db_manager.session_factory,
            )
            interrupted_id = pm.check_resume()
            if interrupted_id is None:
                return

            with db_manager.session_factory() as session:
                pipeline = session.get(PipelineExecution, interrupted_id)
                if pipeline is None:
                    return

                cmds = (
                    session.query(CommandExecution)
                    .filter_by(pipeline_id=interrupted_id)
                    .order_by(CommandExecution.position)
                    .all()
                )
                completed = [c for c in cmds if c.status == CommandStatus.CONCLUIDO.value]
                uncertain = next(
                    (c for c in cmds if c.status == CommandStatus.INCERTO.value), None
                )
                pending = [c for c in cmds if c.status == CommandStatus.PENDENTE.value]

                info = ResumeInfo(
                    pipeline_exec_id=interrupted_id,
                    last_completed_command=completed[-1].command_name if completed else None,
                    uncertain_command=uncertain.command_name if uncertain else None,
                    pending_count=len(pending),
                    total_count=len(cmds),
                    completed_count=len(completed),
                    interrupted_at=pipeline.started_at or pipeline.created_at,
                )

            dlg = ResumeDialog(info, parent=self)
            result = dlg.exec()
            choice = dlg.user_choice()

            if result == ResumeDialog.RESULT_REEXECUTE:
                self._show_toast("Selecione o pipeline para retomar a execução.", "info")
            elif choice == ResumeDialog.RESULT_SKIP:
                self._show_toast("Pipeline interrompido ignorado.", "info")
            # RESULT_CANCEL: do nothing

        except Exception:
            pass  # resume check is non-critical; never block startup

    def _on_save_queue_state(self) -> None:
        """Salva o estado atual da fila no JSON do projeto aberto."""
        import json
        from datetime import datetime
        from pathlib import Path

        if not app_state.has_config or not app_state.config:
            self._show_toast("Nenhum projeto carregado.", "warning")
            return

        queue_state = self._command_queue.get_queue_state()
        if not queue_state:
            self._show_toast("Fila vazia, nada a salvar.", "warning")
            return

        config_path = Path(app_state.config.config_path)
        try:
            with open(config_path, encoding="utf-8") as f:
                project_data = json.load(f)
        except Exception as exc:
            self._show_toast(f"Erro ao ler projeto: {exc}", "error")
            return

        project_data["queue_state"] = {
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            "commands": queue_state,
        }

        try:
            with open(config_path, "w", encoding="utf-8") as f:
                json.dump(project_data, f, ensure_ascii=False, indent=2)
            self._show_toast(f"Fila salva: {len(queue_state)} comandos.", "success")
        except Exception as exc:
            self._show_toast(f"Erro ao salvar fila: {exc}", "error")

    def _restore_queue_state_from_config(self, config_path: str) -> None:
        """Se o JSON do projeto tiver queue_state, restaura a fila silenciosamente."""
        import json

        try:
            with open(config_path, encoding="utf-8") as f:
                project_data = json.load(f)
        except Exception:
            return

        queue_state = project_data.get("queue_state")
        if not queue_state or not queue_state.get("commands"):
            return

        commands = queue_state["commands"]
        self._command_queue.restore_queue_state(commands)

        saved_at = queue_state.get("saved_at", "")[:16].replace("T", " ")
        self._show_toast(
            f"Fila restaurada: {len(commands)} comandos (salva {saved_at})", "info"
        )

    def _setup_remote_server(self) -> None:
        """Instantiate RemoteServer — listens to remote_mode_toggle_requested."""
        from workflow_app.remote.remote_server import RemoteServer
        self._remote_server = RemoteServer(signal_bus)

    def _unload_config(self) -> None:
        """Desvincula o projeto atual."""
        app_state.clear_config()
        self._settings.remove(self._SETTINGS_LAST_CONFIG)
        self._update_title(project_name=None)
        signal_bus.config_unloaded.emit()
        signal_bus.toast_requested.emit("Projeto desvinculado", "info")

    def _update_title(self, project_name: str | None) -> None:
        """Atualiza a barra de título da janela.

        Com projeto: "{project_name} — SystemForge Desktop"
        Sem projeto: "SystemForge Desktop — Sem Projeto"
        """
        if project_name:
            self.setWindowTitle(f"{project_name} — SystemForge Desktop")
        else:
            self.setWindowTitle("SystemForge Desktop — Sem Projeto")


# ──────────────────────────────────────────────────────── Entry point ─── #


def main() -> None:
    from workflow_app.core.sentry_config import init_sentry
    from workflow_app.logger import setup_logging

    setup_logging()
    init_sentry()

    app = QApplication(sys.argv)
    app.setApplicationName("SystemForge Desktop")
    app.setOrganizationName("SystemForge")

    # Apply D19 Graphite Amber theme
    from workflow_app.theme import apply_theme
    apply_theme(app)

    # Window icon
    from pathlib import Path
    icon_path = Path(__file__).parent.parent.parent / "assets" / "icon.svg"
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))

    # Initialize database (seeds factory templates on first run)
    from workflow_app.db.database_manager import db_manager
    db_manager.setup()

    # Verify SDK availability and authentication before opening main window
    from workflow_app.dialogs.critical_error_modal import CriticalErrorModal
    from workflow_app.errors import SDKNotAuthenticatedError, SDKNotAvailableError
    from workflow_app.sdk.sdk_adapter import SDKAdapter

    adapter = SDKAdapter()
    try:
        adapter.ensure_sdk_ready()
    except (SDKNotAvailableError, SDKNotAuthenticatedError) as exc:
        CriticalErrorModal.show_and_exit(exc)
        return  # sys.exit already called, prevents further execution

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
