"""
MetricsBar — 48px top toolbar for project, instance selection, navigation and metrics.

Layout (left to right):
  [project pill / Selecionar] │ [clauded] [clauded2] [codex] [codex-high] [codex-ultra] │ [Workflow] [Comandos] [Toolbox] │ (metrics) │ (stretch) │ [📡] [⚙]

Git info: overlay label, bottom-right corner, updated via git_info_updated signal.

Specs:
  Height: 48px fixed
  Background: #27272A
  Border-bottom: 1px solid #3F3F46
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

# ─── Styles ───────────────────────────────────────────────────────────────── #

_INSTANCE_SELECTED = (
    "QPushButton {"
    "  background-color: transparent;"
    "  color: #FBBF24;"
    "  border: 2px solid #FBBF24;"
    "  border-radius: 4px;"
    "  padding: 2px 10px;"
    "  font-size: 11px;"
    "  font-weight: 700;"
    "}"
    "QPushButton:hover {"
    "  background-color: rgba(251, 191, 36, 0.15);"
    "  color: #FDE68A;"
    "}"
)
_INSTANCE_UNSELECTED = (
    "QPushButton {"
    "  background-color: transparent;"
    "  color: #A1A1AA;"
    "  border: 1px solid #52525B;"
    "  border-radius: 4px;"
    "  padding: 2px 10px;"
    "  font-size: 11px;"
    "}"
    "QPushButton:hover {"
    "  color: #FAFAFA;"
    "  background-color: #3F3F46;"
    "}"
)

_NAV_ACTIVE = (
    "QPushButton {"
    "  background-color: #FBBF24;"
    "  color: #18181B;"
    "  border: none;"
    "  border-radius: 4px;"
    "  padding: 0 14px;"
    "  font-weight: 700;"
    "}"
)
_NAV_INACTIVE = (
    "QPushButton {"
    "  background-color: transparent;"
    "  color: #A1A1AA;"
    "  border: 1px solid #3F3F46;"
    "  border-radius: 4px;"
    "  padding: 0 14px;"
    "}"
    "QPushButton:hover {"
    "  color: #FAFAFA;"
    "  background-color: #3F3F46;"
    "}"
)


class MetricsBar(QWidget):
    """48px project selector, instance selection, and navigation toolbar."""

    view_changed = Signal(int)              # 0=Workflow, 1=Comandos, 2=Toolbox
    config_change_requested = Signal(str)   # path of selected .json
    config_unload_requested = Signal()      # user clicked ✕ on project pill

    def __init__(self, signal_bus=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MetricsBar")
        self.setFixedHeight(48)
        self.setStyleSheet(
            "background-color: #27272A; border-bottom: 1px solid #3F3F46;"
        )

        # Resolve signal bus: accept injected instance or fall back to singleton
        if signal_bus is None:
            from workflow_app.signal_bus import signal_bus as _default_bus
            signal_bus = _default_bus
        self._signal_bus = signal_bus

        # Internal state
        self._tool_use_count = 0
        self._active_view: int = 0
        self._selected_instance: int = 0

        self._setup_ui()
        self._setup_git_overlay()
        self._connect_signals()

        # Restore remote toggle state from persisted config
        from workflow_app.config.app_config import AppConfig
        if AppConfig.get("remote_mode_enabled", False):
            self._btn_remote.setChecked(True)

        # Reflect current project state (if a project was loaded before MetricsBar init)
        from workflow_app.config.app_state import app_state
        if app_state.has_config:
            self._apply_project_loaded(app_state.project_name)
        else:
            self._apply_project_empty()

    # ─────────────────────────────────────────────────────────── UI ──── #

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(4)

        # ── Project pill / select button ──────────────────────────────── #
        self._project_pill = QWidget()
        self._project_pill.setObjectName("ProjectPill")
        self._project_pill.setProperty("testid", "metrics-project-pill")
        self._project_pill.setFixedHeight(28)
        self._project_pill.setStyleSheet(
            "QWidget#ProjectPill { background: transparent; border: 1px solid #22C55E; border-radius: 5px; }"
        )
        _pl = QHBoxLayout(self._project_pill)
        _pl.setContentsMargins(10, 0, 6, 0)
        _pl.setSpacing(6)
        _pl.setAlignment(Qt.AlignmentFlag.AlignVCenter)
        self._project_name_lbl = QLabel("")
        self._project_name_lbl.setAlignment(
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft
        )
        self._project_name_lbl.setContentsMargins(0, 0, 0, 0)
        self._project_name_lbl.setStyleSheet(
            "color: #22C55E; font-size: 11px; font-weight: 600;"
            " border: none; background: transparent; padding: 0; margin: 0;"
        )
        _pl.addWidget(self._project_name_lbl)
        self._proj_x = QPushButton("✕")
        self._proj_x.setFixedSize(16, 16)
        self._proj_x.setToolTip("Desvincular projeto")
        self._proj_x.setCursor(Qt.CursorShape.PointingHandCursor)
        self._proj_x.setStyleSheet(
            "QPushButton { background: transparent; border: none; color: #EF4444; font-size: 12px; font-weight: 700; }"
            "QPushButton:hover { color: #FCA5A5; }"
        )
        self._proj_x.clicked.connect(self._on_proj_unload)
        _pl.addWidget(self._proj_x)

        self._proj_select_btn = QPushButton("Selecionar Projeto...")
        self._proj_select_btn.setFixedHeight(28)
        self._proj_select_btn.setStyleSheet(
            "QPushButton { background: transparent; color: #FBBF24; border: 1px solid #FBBF24;"
            "  border-radius: 5px; font-size: 11px; font-weight: 600; padding: 0 10px; }"
            "QPushButton:hover { background: rgba(251, 191, 36, 0.12); }"
        )
        self._proj_select_btn.clicked.connect(self._on_proj_select)

        layout.addWidget(self._project_pill)
        layout.addWidget(self._proj_select_btn)
        layout.addSpacing(4)
        layout.addWidget(self._make_separator())
        layout.addSpacing(4)

        # ── Instance toggle buttons (clauded group) ───────────────────── #
        _instance_names = ["clauded", "clauded2", "codex", "codex-high", "codex-ultra"]
        self._instance_btns: list[QPushButton] = []

        for i, name in enumerate(_instance_names):
            btn = QPushButton(name)
            btn.setFixedHeight(28)
            btn.clicked.connect(lambda _checked=False, idx=i, n=name: self._on_instance_clicked(idx, n))
            self._instance_btns.append(btn)
            layout.addWidget(btn)

        self._apply_instance_styles()
        layout.addSpacing(4)
        layout.addWidget(self._make_separator())
        layout.addSpacing(4)

        # ── Navigation buttons (Workflow | Comandos | Toolbox) ────────── #
        font_nav = QFont("Inter", 10)
        font_nav.setWeight(QFont.Weight.Medium)

        self._btn_workflow = QPushButton("Workflow")
        self._btn_workflow.setProperty("testid", "nav-btn-workflow")
        self._btn_workflow.setFixedHeight(28)
        self._btn_workflow.setFont(font_nav)
        self._btn_workflow.setMinimumWidth(80)
        self._btn_workflow.clicked.connect(lambda: self._on_nav_clicked(0))
        layout.addWidget(self._btn_workflow)

        self._btn_comandos = QPushButton("Comandos")
        self._btn_comandos.setProperty("testid", "nav-btn-comandos")
        self._btn_comandos.setFixedHeight(28)
        self._btn_comandos.setFont(font_nav)
        self._btn_comandos.setMinimumWidth(80)
        self._btn_comandos.clicked.connect(lambda: self._on_nav_clicked(1))
        layout.addWidget(self._btn_comandos)

        self._btn_toolbox = QPushButton("Toolbox")
        self._btn_toolbox.setProperty("testid", "nav-btn-toolbox")
        self._btn_toolbox.setFixedHeight(28)
        self._btn_toolbox.setFont(font_nav)
        self._btn_toolbox.setMinimumWidth(80)
        self._btn_toolbox.clicked.connect(lambda: self._on_nav_clicked(2))
        layout.addWidget(self._btn_toolbox)

        self._nav_btns = [self._btn_workflow, self._btn_comandos, self._btn_toolbox]
        self._apply_nav_styles()

        layout.addWidget(self._make_separator())

        # ── Token counter ─────────────────────────────────────────────── #
        self._lbl_tokens = QLabel()
        self._lbl_tokens.setObjectName("MetricsBarTokens")
        self._lbl_tokens.setStyleSheet("color: #71717A; font-size: 12px;")
        self._lbl_tokens.setVisible(False)
        layout.addWidget(self._lbl_tokens)

        # ── Tool use counter ──────────────────────────────────────────── #
        self._tool_use_label = QLabel()
        self._tool_use_label.setObjectName("MetricsBarLabel")
        self._tool_use_label.setStyleSheet("color: #71717A; font-size: 12px;")
        self._tool_use_label.setVisible(False)
        layout.addWidget(self._tool_use_label)

        # ── Error badge ───────────────────────────────────────────────── #
        self._lbl_errors = QLabel()
        self._lbl_errors.setObjectName("MetricsBarErrors")
        self._lbl_errors.setStyleSheet(
            "background-color: #EF4444; color: white; font-size: 11px;"
            " border-radius: 10px; padding: 2px 8px; font-weight: 600;"
        )
        self._lbl_errors.setVisible(False)
        layout.addWidget(self._lbl_errors)

        layout.addStretch(1)

        # ── Remote mode toggle ─────────────────────────────────────────── #
        self._btn_remote = self._make_remote_toggle_btn()

        self._lbl_remote_addr = QLabel("")
        self._lbl_remote_addr.setObjectName("RemoteAddressLabel")
        self._lbl_remote_addr.setStyleSheet(
            "color: #22C55E; font-family: monospace; font-size: 11px;"
        )
        self._lbl_remote_addr.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._lbl_remote_addr.setVisible(False)

        self._btn_copy_ip = QPushButton("📋")
        self._btn_copy_ip.setObjectName("CopyIpButton")
        self._btn_copy_ip.setFixedSize(22, 22)
        self._btn_copy_ip.setToolTip("Copiar IP:Porta")
        self._btn_copy_ip.setStyleSheet(
            "QPushButton { background-color: transparent; border: none;"
            "  border-radius: 3px; font-size: 12px; color: #71717A; }"
            "QPushButton:hover { background-color: #3F3F46; }"
        )
        self._btn_copy_ip.setVisible(False)

        self._lbl_connection_badge = QLabel("● Conectado")
        self._lbl_connection_badge.setObjectName("RemoteConnectionBadge")
        self._lbl_connection_badge.setStyleSheet(
            "color: #22C55E; font-size: 11px;"
        )
        self._lbl_connection_badge.setVisible(False)

        layout.addWidget(self._btn_remote)
        layout.addWidget(self._lbl_remote_addr)
        layout.addWidget(self._btn_copy_ip)
        layout.addWidget(self._lbl_connection_badge)

        # ── DataTest toggle ───────────────────────────────────────────── #
        self._btn_datatest = QPushButton("DataTest")
        self._btn_datatest.setFixedSize(68, 32)
        self._btn_datatest.setCheckable(True)
        self._btn_datatest.setToolTip("Exibir data-testid em todos os componentes")
        self._btn_datatest.setStyleSheet(
            "QPushButton { background-color: transparent; color: #A1A1AA;"
            "  border: 1px solid #52525B; border-radius: 6px;"
            "  font-size: 11px; font-weight: 600; padding: 0 6px; }"
            "QPushButton:hover { color: #FAFAFA; background-color: #3F3F46;"
            "  border-color: #71717A; }"
            "QPushButton:checked { background-color: #DC2626; color: #FAFAFA;"
            "  border-color: #DC2626; font-weight: 700; }"
        )
        self._btn_datatest.setCursor(Qt.CursorShape.PointingHandCursor)
        self._btn_datatest.clicked.connect(
            lambda checked: self._signal_bus.datatest_toggled.emit(checked)
        )
        layout.addWidget(self._btn_datatest)

        # ── Right controls ────────────────────────────────────────────── #
        self._btn_prefs = self._make_icon_btn("\u2699\uFE0F", "Preferências")
        layout.addWidget(self._btn_prefs)

    def _setup_git_overlay(self) -> None:
        """Configure overlay label for git info (bottom-right corner)."""
        self._lbl_git_info = QLabel("", self)
        self._lbl_git_info.setStyleSheet(
            "color: #71717A; font-size: 10px; background: transparent;"
            "font-family: 'JetBrains Mono', monospace;"
        )
        self._lbl_git_info.hide()

    def _make_remote_toggle_btn(self) -> QPushButton:
        btn = QPushButton("◉")  # U+25C9 Fisheye — BMP, no emoji font needed
        btn.setObjectName("RemoteToggleButton")
        btn.setFixedSize(36, 32)
        btn.setToolTip("Modo Remoto: ativa servidor WebSocket para controle via Android")
        btn.setCheckable(True)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            "QPushButton { background-color: transparent; border: 1px solid transparent;"
            "  border-radius: 6px; font-size: 18px; color: #D4D4D8; }"
            "QPushButton:hover { background-color: #3F3F46; color: #FAFAFA;"
            "  border-color: #52525B; }"
            "QPushButton:pressed { background-color: #FBBF24; color: #18181B; }"
            "QPushButton:checked { color: #22C55E; font-size: 18px;"
            "  background-color: rgba(34, 197, 94, 0.15);"
            "  border: 1px solid rgba(34, 197, 94, 0.3); }"
        )
        return btn

    def _make_icon_btn(self, icon: str, tooltip: str) -> QPushButton:
        btn = QPushButton(icon)
        btn.setObjectName("IconButton")
        btn.setFixedSize(36, 32)
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            "QPushButton { background-color: transparent; border: 1px solid transparent;"
            "  border-radius: 6px; font-size: 18px; color: #D4D4D8; }"
            "QPushButton:hover { background-color: #3F3F46; color: #FAFAFA;"
            "  border-color: #52525B; }"
            "QPushButton:pressed { background-color: #FBBF24; color: #18181B; }"
            "QPushButton:disabled { color: #52525B; }"
        )
        return btn

    def _make_separator(self) -> QFrame:
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setFixedWidth(1)
        sep.setStyleSheet("background-color: #3F3F46; margin: 8px 4px;")
        return sep

    def resizeEvent(self, event) -> None:
        """Reposition git info label on resize."""
        super().resizeEvent(event)
        if hasattr(self, "_lbl_git_info") and self._lbl_git_info.isVisible():
            lbl = self._lbl_git_info
            lbl.adjustSize()
            x = self.width() - lbl.width() - 8
            y = self.height() - lbl.height() - 2
            lbl.move(max(0, x), max(0, y))

    # ─────────────────────────────────── Instance buttons (Clauded etc.) ── #

    def _on_instance_clicked(self, index: int, name: str) -> None:
        """Type the instance name in the terminal (with Enter) and mark as selected."""
        self._selected_instance = index
        self._apply_instance_styles()
        self._signal_bus.instance_selected.emit(name)
        self._signal_bus.run_command_in_terminal.emit(name)

    def _apply_instance_styles(self) -> None:
        for i, btn in enumerate(self._instance_btns):
            btn.setStyleSheet(
                _INSTANCE_SELECTED if i == self._selected_instance else _INSTANCE_UNSELECTED
            )

    # ─────────────────────────────────── Navigation (Workflow etc.) ──── #

    def _on_nav_clicked(self, index: int) -> None:
        if index == self._active_view:
            return
        self._active_view = index
        self._apply_nav_styles()
        self.view_changed.emit(index)

    def set_active_view(self, index: int) -> None:
        """Switch nav highlight without emitting view_changed (for programmatic switches)."""
        self._active_view = index
        self._apply_nav_styles()

    def _apply_nav_styles(self) -> None:
        for i, btn in enumerate(self._nav_btns):
            btn.setStyleSheet(_NAV_ACTIVE if i == self._active_view else _NAV_INACTIVE)

    # ─────────────────────────────────────────────────────── Signals ─── #

    def _connect_signals(self) -> None:
        bus = self._signal_bus

        self._btn_prefs.clicked.connect(bus.preferences_requested)

        self._btn_remote.clicked.connect(self._on_remote_toggled)
        self._btn_copy_ip.clicked.connect(self._on_copy_ip)
        bus.remote_server_started.connect(self._on_remote_server_started)
        bus.remote_server_stopped.connect(self._on_remote_server_stopped)
        bus.remote_client_connected.connect(self._on_remote_client_connected)
        bus.remote_client_disconnected.connect(self._on_remote_client_disconnected)

        bus.tool_use_started.connect(self._on_tool_use_started)
        bus.tool_use_completed.connect(self._on_tool_use_completed)
        bus.token_update.connect(self._on_token_update)
        bus.metrics_snapshot.connect(self._on_metrics_snapshot)
        bus.git_info_updated.connect(self._on_git_info_updated)

        bus.config_loaded.connect(self._on_config_loaded_signal)
        bus.config_unloaded.connect(self._apply_project_empty)

    # ─────────────────────────────────────────────────────── Slots ───── #

    _COPY_FEEDBACK_MS = 2000

    def _on_remote_toggled(self, checked: bool) -> None:
        from workflow_app.config.app_config import AppConfig
        AppConfig.set("remote_mode_enabled", checked)
        self._signal_bus.remote_mode_toggle_requested.emit(checked)
        if not checked:
            self._lbl_remote_addr.setVisible(False)
            self._btn_copy_ip.setVisible(False)
            self._lbl_connection_badge.setVisible(False)

    def _on_copy_ip(self) -> None:
        addr = self._lbl_remote_addr.text()
        if addr:
            QApplication.clipboard().setText(addr)
            self._btn_copy_ip.setText("✓")
            self._btn_copy_ip.setToolTip("Copiado!")
            QTimer.singleShot(
                self._COPY_FEEDBACK_MS,
                lambda: (
                    self._btn_copy_ip.setText("📋"),
                    self._btn_copy_ip.setToolTip("Copiar IP:Porta"),
                ),
            )

    def _on_remote_server_started(self, address: str) -> None:
        self._btn_remote.setChecked(True)
        self._lbl_remote_addr.setText(address)
        self._lbl_remote_addr.setVisible(True)
        self._btn_copy_ip.setVisible(True)

    def _on_remote_server_stopped(self) -> None:
        self._btn_remote.setChecked(False)
        self._lbl_remote_addr.setText("")
        self._lbl_remote_addr.setVisible(False)
        self._btn_copy_ip.setVisible(False)
        self._lbl_connection_badge.setVisible(False)

    def _on_remote_client_connected(self) -> None:
        self._lbl_connection_badge.setVisible(True)

    def _on_remote_client_disconnected(self) -> None:
        self._lbl_connection_badge.setVisible(False)

    # ──────────────────────────────────────── Project widget slots ─── #

    def _on_proj_select(self) -> None:
        from workflow_app.config.app_state import app_state
        start_dir = str(Path.cwd())
        if app_state.has_config and app_state.config:
            start_dir = str(Path(app_state.config.config_path).parent)
        else:
            candidate = Path(__file__).resolve()
            while candidate != candidate.parent:
                if (candidate / ".claude" / "projects").is_dir():
                    start_dir = str(candidate / ".claude" / "projects")
                    break
                candidate = candidate.parent
        path, _ = QFileDialog.getOpenFileName(
            self, "Selecionar project.json", start_dir,
            "JSON Files (*.json);;All Files (*)",
        )
        if path:
            self.config_change_requested.emit(path)

    def _on_proj_unload(self) -> None:
        self.config_unload_requested.emit()

    def _on_config_loaded_signal(self, _path: str) -> None:
        from workflow_app.config.app_state import app_state
        if app_state.has_config:
            self._apply_project_loaded(app_state.project_name)

    def _apply_project_loaded(self, name: str) -> None:
        self._project_name_lbl.setText(name)
        self._project_pill.show()
        self._project_name_lbl.show()
        self._proj_x.show()
        self._proj_select_btn.hide()

    def _apply_project_empty(self) -> None:
        self._project_pill.hide()
        self._proj_select_btn.show()

    def _on_tool_use_started(self, tool_name: str) -> None:
        self._tool_use_count += 1
        self._tool_use_label.setText(f"Tools: {self._tool_use_count}")
        self._tool_use_label.setVisible(True)

    def _on_tool_use_completed(self, tool_name: str, duration_ms: int) -> None:
        self._tool_use_label.setToolTip(f"Último: {tool_name} ({duration_ms}ms)")

    def _on_token_update(self, tokens_in: int, tokens_out: int, cost_usd: float) -> None:
        def _fmt_k(n: int) -> str:
            return f"{n // 1000}k" if n >= 1000 else str(n)
        text = f"↑{_fmt_k(tokens_in)} ↓{_fmt_k(tokens_out)} ${cost_usd:.2f}"
        self.set_tokens_text(text)

    def _on_metrics_snapshot(self, snapshot: object) -> None:
        """Batch-update token/error widgets from a MetricsSnapshot."""
        errors = getattr(snapshot, "error_commands", 0)
        tokens_in = getattr(snapshot, "tokens_input", 0)
        tokens_out = getattr(snapshot, "tokens_output", 0)
        cost = getattr(snapshot, "cost_estimate_usd", 0.0)

        self.set_errors_badge(errors)
        if tokens_in > 0 or tokens_out > 0:
            self._on_token_update(tokens_in, tokens_out, cost)

    def _on_git_info_updated(self, info_text: str) -> None:
        if info_text:
            self._lbl_git_info.setText(info_text)
            self._lbl_git_info.show()
            self.resizeEvent(None)
        else:
            self._lbl_git_info.hide()

    # ──────────────────────────────────────────────────── Public API ─── #

    def set_tokens_text(self, text: str) -> None:
        self._lbl_tokens.setText(text)
        self._lbl_tokens.setVisible(True)

    def set_errors_badge(self, count: int) -> None:
        if count > 0:
            self._lbl_errors.setText(f"{count} erros")
            self._lbl_errors.setVisible(True)
        else:
            self._lbl_errors.setVisible(False)

    # Backward-compat stubs (called by older code, now no-ops)
    def set_progress_text(self, completed: int, total: int) -> None:
        pass

    def set_elapsed_text(self, hms_str: str) -> None:
        pass

    def set_estimate_text(self, text: str) -> None:
        pass

    def update_tokens(self, tokens: int) -> None:
        if tokens > 0:
            self.set_tokens_text(f"~{tokens / 1000:.1f}k tok")

    def update_errors(self, count: int) -> None:
        self.set_errors_badge(count)
