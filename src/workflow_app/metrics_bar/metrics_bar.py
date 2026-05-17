"""
MetricsBar — 80px top toolbar for project, instance selection, navigation and metrics.

Layout:
  Row 1 (top):    [project pill / Selecionar] │ (metrics) │ (stretch)

Git info: overlay label, bottom-right corner, updated via git_info_updated signal.

Specs:
  Height: 80px fixed (single row)
  Background: #27272A
  Border-bottom: none
"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import (
    QDateTime,
    QFileSystemWatcher,
    QMimeData,
    QSettings,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QDrag, QFont
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

_SCHEDULE_STATE_FILE = Path.home() / ".workflow-app" / "schedule-autocast.json"

# ─── Instance buttons drag&drop (output-toolbar-center-top) ───────────────── #
#
# Os botoes do `instance-group` (clauded/kimid/clauded2/kimid2) sao reordenaveis
# via drag&drop. A ordem persiste em QSettings("SystemForge", "WorkflowApp")
# sob `_INSTANCE_ORDER_SETTINGS_KEY` e e restaurada na proxima abertura do app.
_CANONICAL_INSTANCE_NAMES = ["clauded", "kimid", "clauded2", "kimid2"]
_INSTANCE_ORDER_SETTINGS_KEY = "MetricsBar/instanceOrder"
_INSTANCE_DRAG_MIME = "application/x-workflow-instance-button"
_INSTANCE_DRAG_THRESHOLD = 6


class _DraggableInstanceButton(QPushButton):
    """QPushButton arrastavel dentro de _InstanceDropZone.

    Inicia QDrag depois que o cursor se move alem de _INSTANCE_DRAG_THRESHOLD
    pixels com o botao esquerdo pressionado. O clique normal continua funcionando
    quando nao ha movimento significativo (QDrag.exec() intercepta o release
    quando o drag inicia, impedindo o `clicked` espurio).
    """

    def __init__(self, name: str, parent: QWidget | None = None) -> None:
        super().__init__(name, parent)
        self._instance_name = name
        self._drag_start = None

    def mousePressEvent(self, event):  # noqa: N802 (Qt API)
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position().toPoint()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):  # noqa: N802 (Qt API)
        if not (event.buttons() & Qt.MouseButton.LeftButton) or self._drag_start is None:
            super().mouseMoveEvent(event)
            return
        delta = (event.position().toPoint() - self._drag_start).manhattanLength()
        if delta < _INSTANCE_DRAG_THRESHOLD:
            super().mouseMoveEvent(event)
            return
        self._drag_start = None
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(_INSTANCE_DRAG_MIME, self._instance_name.encode("utf-8"))
        drag.setMimeData(mime)
        pixmap = self.grab()
        drag.setPixmap(pixmap)
        drag.setHotSpot(event.position().toPoint())
        self.setCursor(Qt.CursorShape.ClosedHandCursor)
        try:
            drag.exec(Qt.DropAction.MoveAction)
        finally:
            self.unsetCursor()

    def mouseReleaseEvent(self, event):  # noqa: N802 (Qt API)
        self._drag_start = None
        self.unsetCursor()
        super().mouseReleaseEvent(event)


class _InstanceDropZone(QWidget):
    """Container que aceita drops de _DraggableInstanceButton e dispara callback."""

    def __init__(self, on_drop, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._on_drop = on_drop
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):  # noqa: N802 (Qt API)
        if event.mimeData().hasFormat(_INSTANCE_DRAG_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):  # noqa: N802 (Qt API)
        if event.mimeData().hasFormat(_INSTANCE_DRAG_MIME):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):  # noqa: N802 (Qt API)
        if not event.mimeData().hasFormat(_INSTANCE_DRAG_MIME):
            event.ignore()
            return
        raw = bytes(event.mimeData().data(_INSTANCE_DRAG_MIME))
        name = raw.decode("utf-8", errors="replace")
        drop_x = event.position().toPoint().x()
        self._on_drop(name, drop_x)
        event.acceptProposedAction()


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

_AUTOCAST_OFF = (
    "QPushButton {"
    "  background-color: #2563EB;"
    "  color: #FAFAFA;"
    "  border: none;"
    "  border-radius: 4px;"
    "  padding: 0 12px;"
    "  font-size: 11px;"
    "  font-weight: 700;"
    "}"
    "QPushButton:hover { background-color: #1D4ED8; }"
    "QPushButton:disabled { background-color: #1E3A8A; color: #93C5FD; }"
)
_AUTOCAST_ON = (
    "QPushButton {"
    "  background-color: #DC2626;"
    "  color: #FAFAFA;"
    "  border: none;"
    "  border-radius: 4px;"
    "  padding: 0 12px;"
    "  font-size: 11px;"
    "  font-weight: 700;"
    "}"
    "QPushButton:hover { background-color: #B91C1C; }"
)

_SCHEDULE_IDLE = (
    "QPushButton {"
    "  background-color: #2563EB;"
    "  color: #FAFAFA;"
    "  border: none;"
    "  border-radius: 4px;"
    "  padding: 0 12px;"
    "  font-size: 11px;"
    "  font-weight: 700;"
    "}"
    "QPushButton:hover { background-color: #1D4ED8; }"
)
_SCHEDULE_RUNNING = (
    "QPushButton {"
    "  background-color: #F0B90B;"
    "  color: #18181B;"
    "  border: none;"
    "  border-radius: 4px;"
    "  padding: 0 12px;"
    "  font-size: 11px;"
    "  font-weight: 700;"
    "}"
    "QPushButton:hover { background-color: #D9A509; }"
)
_SCHEDULE_FIRED = (
    "QPushButton {"
    "  background-color: #22C55E;"
    "  color: #FAFAFA;"
    "  border: none;"
    "  border-radius: 4px;"
    "  padding: 0 12px;"
    "  font-size: 11px;"
    "  font-weight: 700;"
    "}"
)


def _read_schedule_state() -> dict | None:
    try:
        if not _SCHEDULE_STATE_FILE.exists():
            return None
        return json.loads(_SCHEDULE_STATE_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_schedule_state(end_at_iso: str) -> None:
    try:
        _SCHEDULE_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _SCHEDULE_STATE_FILE.write_text(
            json.dumps({"end_at": end_at_iso}), encoding="utf-8"
        )
    except OSError:
        pass


def _clear_schedule_state() -> None:
    try:
        _SCHEDULE_STATE_FILE.unlink(missing_ok=True)
    except OSError:
        pass


class TerminalStatusDot(QWidget):
    """Circular indicator for terminal activity state.

    Green  (#22C55E) — terminal silent for 2+ seconds (idle at prompt).
    Yellow (#F59E0B) — PTY output flowing (command executing).

    Responsive (2026-05-17): size is the "preferred" diameter used as sizeHint
    so the parent layout can shrink/grow the dot. resizeEvent recomputes the
    border-radius from the current min(width, height) so the dot stays a
    perfect circle at any size.
    """

    busy_changed = Signal(str, bool)  # channel, is_busy — fired on every transition

    _SIZE = 28
    _MIN_SIZE = 16
    _IDLE_COLOR = "#22C55E"
    _BUSY_COLOR = "#F59E0B"

    def __init__(
        self,
        channel: str,
        label: str,
        parent: "QWidget | None" = None,
        *,
        size: int = _SIZE,
    ) -> None:
        super().__init__(parent)
        self._channel = channel
        self._label = label
        self._busy = False
        self._size = int(size)
        self.setProperty("testid", f"listener-{channel}")
        # Responsive sizing: parent layout drives actual width/height; widget
        # keeps preferred `size` via sizeHint while accepting shrink to _MIN_SIZE.
        self.setMinimumSize(self._MIN_SIZE, self._MIN_SIZE)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._apply_style()
        self.setToolTip(f"{label}: parado")

    def sizeHint(self) -> QSize:
        return QSize(self._size, self._size)

    def minimumSizeHint(self) -> QSize:
        return QSize(self._MIN_SIZE, self._MIN_SIZE)

    def _current_diameter(self) -> int:
        return max(self._MIN_SIZE, min(self.width(), self.height()))

    def _apply_style(self) -> None:
        color = self._BUSY_COLOR if self._busy else self._IDLE_COLOR
        radius = self._current_diameter() // 2
        border = "border: 2px solid #FFFFFF;" if color == self._IDLE_COLOR else ""
        self.setStyleSheet(
            f"QWidget {{ background-color: {color}; border-radius: {radius}px; {border} }}"
        )

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        self._apply_style()

    @property
    def is_busy(self) -> bool:
        return self._busy

    @property
    def channel(self) -> str:
        return self._channel

    def set_busy(self, busy: bool) -> None:
        if busy == self._busy:
            return
        self._busy = busy
        self._apply_style()
        self.setToolTip(f"{self._label}: {'executando' if busy else 'parado'}")
        self.busy_changed.emit(self._channel, busy)


class MetricsBar(QWidget):
    """48px project selector, instance selection, and navigation toolbar."""

    view_changed = Signal(int)              # 0=Workflow, 1=Comandos, 2=Kanban
    config_change_requested = Signal(str)   # path of selected .json
    config_unload_requested = Signal()      # user clicked ✕ on project pill

    def __init__(self, signal_bus=None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("MetricsBar")
        self.setFixedHeight(38)
        self.setStyleSheet(
            "QWidget#MetricsBar { background-color: #27272A; }"
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
        self._autocast_phase: str = "off"  # off | awaiting-busy | running
        self._awaiting_user_input: bool = False

        # MARKER_SCHEDULE_AUTOCAST_STATE - schedule-autocast countdown state
        self._schedule_end_at: QDateTime | None = None
        self._schedule_timer = QTimer(self)
        self._schedule_timer.setInterval(1000)
        self._schedule_timer.timeout.connect(self._on_schedule_tick)

        # Restore schedule-autocast state from disk
        state = _read_schedule_state()
        if state and isinstance(state.get("end_at"), str):
            restored = QDateTime.fromString(state["end_at"], Qt.DateFormat.ISODate)
            if restored.isValid() and QDateTime.currentDateTime().secsTo(restored) > 0:
                self._schedule_end_at = restored
                self._schedule_timer.start()
                QTimer.singleShot(0, self._update_schedule_visual)
            else:
                _clear_schedule_state()

        self._setup_ui()
        self._setup_activity_timers()
        self._setup_git_overlay()
        self._connect_signals()

        # Remote mode removido 2026-05-12 — botao e estado persistido foram
        # eliminados; o RemoteServer (se ainda instanciado) permanece dormente.

        # Reflect current project state (if a project was loaded before MetricsBar init)
        from workflow_app.config.app_state import app_state
        if app_state.has_config:
            self._apply_project_loaded(app_state.project_name)
        else:
            self._apply_project_empty()

    # ─────────────────────────────────────────────────────────── UI ──── #

    def _setup_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        top_row = QWidget()
        top_row.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        top_row.setStyleSheet("background: transparent;")
        layout = QHBoxLayout(top_row)
        layout.setContentsMargins(8, 5, 8, 5)
        layout.setSpacing(4)
        outer.addWidget(top_row)

        # ── Project pill / select button ──────────────────────────────── #
        self._project_pill = QWidget()
        self._project_pill.setObjectName("ProjectPill")
        self._project_pill.setProperty("testid", "metrics-project-pill")
        self._project_pill.setFixedHeight(28)
        self._project_pill.setStyleSheet(
            "QWidget#ProjectPill { background: transparent; border: 1px solid #22C55E; border-radius: 5px; }"
            " QWidget#ProjectPill QLabel { border: none; }"
            " QWidget#ProjectPill QPushButton { border: none; }"
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
        self._proj_x.setObjectName("ProjCloseBtn")
        self._proj_x.setFixedSize(20, 20)
        self._proj_x.setToolTip("Desvincular projeto")
        self._proj_x.setCursor(Qt.CursorShape.PointingHandCursor)
        self._proj_x.setStyleSheet(
            "QPushButton#ProjCloseBtn { background: transparent; border: none;"
            "  color: #EF4444; font-size: 14px; font-weight: 700;"
            "  min-width: 20px; min-height: 20px; padding: 0; margin: 0; }"
            "QPushButton#ProjCloseBtn:hover { color: #FCA5A5; background: rgba(239, 68, 68, 0.15); border-radius: 3px; }"
        )
        self._proj_x.clicked.connect(self._on_proj_unload)
        _pl.addWidget(self._proj_x)

        # ── Feature name input (beside the pill) ─────────────────────── #
        self._feature_name_input = QLineEdit()
        self._feature_name_input.setProperty("testid", "metrics-feature-name")
        self._feature_name_input.setPlaceholderText("feature")
        self._feature_name_input.setFixedHeight(28)
        self._feature_name_input.setStyleSheet(
            "QLineEdit { background: transparent; color: #A78BFA; border: 1px solid #6D28D9;"
            "  border-radius: 5px; font-size: 11px; font-weight: 600; padding: 0 8px; }"
            "QLineEdit:focus { border-color: #A78BFA; }"
        )
        self._feature_name_input.setReadOnly(True)
        self._feature_name_input.hide()

        _SELECT_BTN_STYLE = (
            "QPushButton { background: transparent; color: #FBBF24; border: 1px solid #FBBF24;"
            "  border-radius: 5px; font-size: 11px; font-weight: 600; padding: 0 12px; }"
            "QPushButton:hover { background: rgba(251, 191, 36, 0.12); }"
        )

        self._proj_select_btn = QPushButton("Projeto")
        self._proj_select_btn.setProperty("testid", "metrics-btn-proj-select")
        self._proj_select_btn.setToolTip("Abrir project.json (parte de .claude/projects/)")
        self._proj_select_btn.setFixedHeight(28)
        self._proj_select_btn.setStyleSheet(_SELECT_BTN_STYLE)
        self._proj_select_btn.clicked.connect(self._on_proj_select)

        self._loop_select_btn = QPushButton("Loop")
        self._loop_select_btn.setProperty("testid", "metrics-btn-loop-select")
        self._loop_select_btn.setToolTip("Abrir _LOOP-CONFIG.json (parte de blacksmith/)")
        self._loop_select_btn.setFixedHeight(28)
        self._loop_select_btn.setStyleSheet(_SELECT_BTN_STYLE)
        self._loop_select_btn.clicked.connect(self._on_loop_select)

        self._proj_open_btn = QPushButton("Abrir")
        self._proj_open_btn.setProperty("testid", "metrics-btn-proj-open")
        self._proj_open_btn.setToolTip("Abrir pasta do projeto no explorador de arquivos")
        self._proj_open_btn.setFixedHeight(28)
        self._proj_open_btn.setStyleSheet(_SELECT_BTN_STYLE)
        self._proj_open_btn.clicked.connect(self._on_proj_open)

        # ── Instance toggle buttons (clauded group) ───────────────────── #
        # Task 4 (loop 05-13-workflow-app-layout-2):
        #   4a: adicionado `kimid2` apos `clauded2` (mirror clauded2 — interactive terminal).
        #   4d: removido `codex` (eliminado do layout + handler orfao).
        # 2026-05-14: botoes sao reordenaveis via drag&drop (output-toolbar-center-top).
        # Ordem persiste em QSettings/_INSTANCE_ORDER_SETTINGS_KEY e e restaurada aqui.
        self._instance_order_settings = QSettings("SystemForge", "WorkflowApp")
        instance_order = self._load_instance_order()
        self._instance_btns: list[_DraggableInstanceButton] = []
        self._instance_group = _InstanceDropZone(self._on_instance_button_dropped)
        self._instance_group.setProperty("testid", "instance-group")
        self._instance_group.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self._instance_group.setStyleSheet("background: transparent;")
        _ig_layout = QHBoxLayout(self._instance_group)
        _ig_layout.setContentsMargins(0, 0, 0, 0)
        _ig_layout.setSpacing(4)

        for name in instance_order:
            btn = _DraggableInstanceButton(name, parent=self._instance_group)
            btn.setFixedHeight(28)
            btn.setToolTip(
                f"{name} — clique para selecionar. Arraste para reordenar."
            )
            # Lambda usa self._instance_btns.index(b) para obter o indice ATUAL
            # do botao no momento do clique (apos qualquer reorderacao).
            btn.clicked.connect(
                lambda _checked=False, b=btn, n=name: self._on_instance_clicked(
                    self._instance_btns.index(b), n
                )
            )
            self._instance_btns.append(btn)
            _ig_layout.addWidget(btn)

        self._apply_instance_styles()
        # _instance_group NOT added here — reparented to output-toolbar-center by MainWindow.

        layout.addWidget(self._project_pill)
        layout.addWidget(self._feature_name_input)
        layout.addWidget(self._proj_select_btn)
        layout.addWidget(self._loop_select_btn)

        # ── Navigation buttons (Workflow | Comandos) ────────────────── #
        # Criados aqui mas posicionados mais a direita (no slot antes
        # ocupado pelo botao de Modo Remoto, removido em 2026-05-12).
        font_nav = QFont("Inter", 10)
        font_nav.setWeight(QFont.Weight.Medium)

        self._btn_workflow = QPushButton("Workflow")
        self._btn_workflow.setProperty("testid", "nav-btn-workflow")
        self._btn_workflow.setFixedHeight(28)
        self._btn_workflow.setFont(font_nav)
        self._btn_workflow.setMinimumWidth(80)
        self._btn_workflow.clicked.connect(lambda: self._on_nav_clicked(0))

        self._btn_comandos = QPushButton("Comandos")
        self._btn_comandos.setProperty("testid", "nav-btn-comandos")
        self._btn_comandos.setFixedHeight(28)
        self._btn_comandos.setFont(font_nav)
        self._btn_comandos.setMinimumWidth(80)
        self._btn_comandos.clicked.connect(lambda: self._on_nav_clicked(1))

        self._nav_btns = [
            self._btn_workflow,
            self._btn_comandos,
        ]
        self._apply_nav_styles()

        # ── Header actions slot (4th div) ─────────────────────────────── #
        # Populated by MainWindow with the JSON/WS/mcp-* quick-action
        # buttons (moved from output-toolbar 2026-05-12). Empty placeholder
        # if MainWindow doesn't fill it.
        self._header_actions = QWidget()
        self._header_actions.setObjectName("HeaderActions")
        self._header_actions_layout = QHBoxLayout(self._header_actions)
        self._header_actions_layout.setContentsMargins(0, 0, 0, 0)
        self._header_actions_layout.setSpacing(6)
        layout.addWidget(self._header_actions)

        # ── Listeners + ring frame (own div, NOT added to metrics_bar layout) ──
        # Migration 2026-05-12 (Iter 12): listeners-frame foi movido para uma
        # nova barra horizontal acima do toggle_bar no output_container do
        # main_window. As instancias seguem owned por MetricsBar para preservar
        # state machine (idle timers, dot busy tracking, ring updates). O
        # main_window reparente _listeners_frame ao montar sua barra.
        self._listeners_frame = QFrame()
        self._listeners_frame.setObjectName("ListenersFrame")
        self._listeners_frame.setProperty("testid", "listeners-frame")
        self._listeners_frame.setMinimumHeight(108)
        # Task 9 (loop 05-13-workflow-app-layout-2): border interna removida
        # para eliminar duplicacao com a border externa do OutputToolbar
        # (output-toolbar-col1-top), que envelopa este frame apos a migracao
        # Iter 12. O frame permanece como container de layout (margens 12/8
        # e spacing 16) hospedando dots, queue-progress-ring, queue-count-col.
        self._listeners_frame.setStyleSheet(
            "QFrame#ListenersFrame { background-color: transparent; }"
        )
        # Listeners-frame agora expande horizontalmente; os dots compartilham
        # o espaco igualmente via stretch=1 (Task 4 do refactor power-bi).
        self._listeners_frame.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred,
        )
        lf = QHBoxLayout(self._listeners_frame)
        lf.setContentsMargins(12, 8, 12, 8)
        lf.setSpacing(16)

        self._dot_interactive = TerminalStatusDot(
            "interactive", "Claude CLI", self._listeners_frame, size=88,
        )
        self._dot_workspace = TerminalStatusDot(
            "workspace", "Kimi CLI", self._listeners_frame, size=88,
        )
        lf.addWidget(self._dot_interactive, 1)
        lf.addWidget(self._dot_workspace, 1)

        # queue-progress-ring agora vive como IRMAO do listeners-frame dentro
        # do power-bi-section (montado em main_window._build_output_toolbar).
        # Permanece owned por MetricsBar para preservar signal pipelines, mas
        # sem parent ate ser reparenteado pelo PowerBiSection.
        from workflow_app.widgets.queue_progress_ring import QueueProgressRing
        self._queue_progress_ring = QueueProgressRing(None, diameter=88)

        # Contador textual "executados/faltantes" — migrado em 2026-05-17 do
        # centro do queue-progress-ring para a row queue-last-command (vive
        # como filho reparenteado pelo CommandQueueWidget). Aqui o label segue
        # owned por MetricsBar pra preservar o pipeline de signal
        # (`metrics_updated` -> `_on_metrics_updated_for_ring` -> setText).
        self._lbl_queue_count = QLabel("0/0")
        self._lbl_queue_count.setObjectName("QueueCountLabel")
        self._lbl_queue_count.setProperty("testid", "queue-count-label")
        self._lbl_queue_count.setToolTip("Comandos executados / total")
        self._lbl_queue_count.setAlignment(Qt.AlignmentFlag.AlignCenter)

        # queue-count-toggles-row continua existindo (terminal-layout-toggle +
        # terminal-workspace-collapse populados via MainWindow), mas agora vive
        # em output-toolbar-queue-toggles (reparenteado por MainWindow). Mantemos
        # o widget como orfao aqui ate que MainWindow._build_queue_toggles_column
        # o reparenteie.
        self._queue_count_toggles_row = QWidget()
        self._queue_count_toggles_row.setProperty(
            "testid", "queue-count-toggles-row"
        )
        self._queue_count_toggles_layout = QVBoxLayout(
            self._queue_count_toggles_row
        )
        self._queue_count_toggles_layout.setContentsMargins(0, 0, 0, 0)
        self._queue_count_toggles_layout.setSpacing(6)

        # Migration 2026-05-12 (TASK-1 AC-1.4): autocast e schedule-autocast
        # buttons foram movidos para o play_bar do CommandQueueWidget. As
        # instancias permanecem aqui (hidden, NoParent layout) para preservar
        # a state machine existente — toggle/click sao driveados via signal_bus
        # (`autocast_toggle_requested`, `schedule_autocast_requested`).
        self._btn_schedule_autocast = QPushButton("agendar")
        self._btn_schedule_autocast.setProperty("testid", "schedule-autocast-btn-legacy")
        self._btn_schedule_autocast.setVisible(False)
        self._btn_schedule_autocast.clicked.connect(self._on_schedule_clicked)

        self._btn_autocast = QPushButton("autocast")
        self._btn_autocast.setProperty("testid", "autocast-btn-legacy")
        self._btn_autocast.setCheckable(True)
        self._btn_autocast.setVisible(False)
        self._btn_autocast.toggled.connect(self._on_autocast_toggled)

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

        # ── Nav group (Workflow | Comandos) ────────────────────────────── #
        # Botões mantidos no layout (lógica/sinais preservados) mas ocultos —
        # a tela ativa é sempre Workflow (índice 0).
        layout.addWidget(self._btn_workflow)
        layout.addWidget(self._btn_comandos)
        self._btn_workflow.hide()
        self._btn_comandos.hide()

        # ── DataTest toggle ───────────────────────────────────────────── #
        self._btn_datatest = QPushButton("DataTest")
        self._btn_datatest.setFixedSize(68, 32)
        self._btn_datatest.setCheckable(True)
        self._btn_datatest.setToolTip("Exibir data-testid em todos os componentes")
        self._btn_datatest.setStyleSheet(
            "QPushButton { background-color: transparent; color: #4ADE80;"
            "  border: 1px solid #16A34A; border-radius: 6px;"
            "  font-size: 11px; font-weight: 600; padding: 0 6px; }"
            "QPushButton:hover { color: #FAFAFA; background-color: #166534;"
            "  border-color: #22C55E; }"
            "QPushButton:checked { background-color: #16A34A; color: #FAFAFA;"
            "  border-color: #16A34A; font-weight: 700; }"
        )
        self._btn_datatest.setCursor(Qt.CursorShape.PointingHandCursor)
        # Task 3 (loop 05-13-workflow-app-layout-2): wiring agora pertence ao MainWindow
        # (botao integrado a 4a coluna `output-toolbar-test-mode` com toggle radio-like
        # exclusivo via QButtonGroup, emitindo `datatest_mode_changed`). O .clicked->emit
        # antigo foi removido para evitar duplicidade de sinal.
        # NOT added to metrics_bar layout — reparented to `output-toolbar-test-mode`
        # column by MainWindow (first row of the new 4th sibling).


    # Path where the notify script writes its signal.
    _NOTIFY_FILE = Path.home() / ".workflow-app" / "terminal-notify.json"

    def _setup_activity_timers(self) -> None:
        """Idle detection — two coexisting paths.

        AUTHORITATIVE (primary, used by skill notify files):
          When a skill script writes ~/.workflow-app/terminal-notify-{channel}.json,
          QFileSystemWatcher fires _on_notify_file_changed → the dot goes green
          IMMEDIATELY and a per-channel lock ignores subsequent PTY repaint
          chunks (Rich/textual cursor blink, status line). Lock releases when
          the app dispatches the next command, when an external session starts,
          or after a 30s safety-net TTL.

        HEURISTIC (legacy, for runner-backed PTY sessions):
          terminal_session_finished → _on_force_idle starts a 2s one-shot timer.
          PTY output during that window resets the timer. After 2s of silence
          the dot turns green. Used only when no notify file is involved.

        Two fences guard the authoritative path:
          - epoch fence: rejects notifies whose iat <= last command dispatch
          - session fence: ignores notifies while runner-backed session is active
        """
        # Hardening window — 3s of true PTY silence after notify file
        # before the dot turns green. Resets on every chunk while active.
        # Single timer, no hardcap: the contract is "if there's activity,
        # the dot does NOT turn green". A CLI with infinite animation
        # (genuine continuous output) keeps the dot yellow indefinitely
        # — that is the correct behaviour, not a bug.
        self._idle_timer_interactive = QTimer(self)
        self._idle_timer_interactive.setSingleShot(True)
        self._idle_timer_interactive.setInterval(3_000)
        self._idle_timer_interactive.timeout.connect(
            lambda: self._on_idle_confirmed("interactive")
        )

        self._idle_timer_workspace = QTimer(self)
        self._idle_timer_workspace.setSingleShot(True)
        self._idle_timer_workspace.setInterval(3_000)
        self._idle_timer_workspace.timeout.connect(
            lambda: self._on_idle_confirmed("workspace")
        )

        # One notify file per channel — eliminates cross-channel race conditions.
        # Files are created here so QFileSystemWatcher can watch them from the start.
        notify_dir = self._NOTIFY_FILE.parent
        notify_dir.mkdir(parents=True, exist_ok=True)
        self._notify_files: dict[str, Path] = {
            "interactive": notify_dir / "terminal-notify-interactive.json",
            "workspace":   notify_dir / "terminal-notify-workspace.json",
        }
        for p in self._notify_files.values():
            if not p.exists():
                p.write_text("{}")
        self._notify_watcher = QFileSystemWatcher(
            [str(p) for p in self._notify_files.values()], self
        )
        self._notify_watcher.fileChanged.connect(self._on_notify_file_changed)
        # Also watch the parent directory: if a notify file is deleted at
        # runtime (e.g. user `rm` to debug), QFileSystemWatcher drops the
        # file path forever. The directory watcher catches the delete and
        # we re-create + re-add. Without this, a deleted notify file
        # leaves the channel permanently disconnected from notify events.
        self._notify_watcher.addPath(str(notify_dir))
        self._notify_watcher.directoryChanged.connect(
            self._on_notify_directory_changed
        )
        # Clean stale notify files from previous sessions on startup.
        self._clean_stale_notify_files()

        # Authoritative idle lock — green-by-default semantics.
        #
        # The dot represents "is a command currently being executed via the
        # app on this channel?". At rest, the lock is True so ambient PTY
        # chunks (Kimi cursor blink, Rich repaints from a mouse click on the
        # terminal area, status line refreshes) are ignored and the dot
        # stays green. The lock is only released when the app actively
        # dispatches a command (`run_command_in_*_terminal`) or when an
        # external PTY session starts. After the command finishes (notify
        # file → hardening → silence) the lock returns to True and the dot
        # is green again until the next dispatch.
        self._idle_locked: dict[str, bool] = {"interactive": True, "workspace": True}
        # NOTE: the legacy 30s TTL safety net was removed — it conflicted
        # with green-by-default semantics by periodically opening a window
        # in which a stray click could flip the dot yellow. The lock now
        # persists until an actual dispatch event releases it.
        self._idle_lock_ttl: dict[str, QTimer] = {}

        # Command epoch fence: monotonic wall-clock of the latest command
        # dispatched per channel. A notify whose `iat` is older than the
        # current epoch is rejected — prevents a delayed notify from command A
        # re-locking the dot while command B is already running. Initialized
        # to 0 so notifies before the first command are still accepted.
        self._command_epoch: dict[str, float] = {"interactive": 0.0, "workspace": 0.0}

        # External-session fence: True between terminal_session_started and
        # terminal_session_finished. While active, authoritative notifies are
        # ignored — runner-driven sessions own the dot via the legacy
        # heuristic path (terminal_session_finished -> _on_force_idle).
        self._session_active: dict[str, bool] = {"interactive": False, "workspace": False}

        # Hardcap timers are created on-demand by `_arm_hardening` when
        # called with `hardcap_ms`. Skills (notify file path) call without
        # hardcap → no entry created, strict "activity ⇒ yellow" preserved.
        # Helpers (/clear, /model, etc) call with hardcap_ms=5000 → entry
        # created and started; even Kimi's invisible CPR/cursor chunks
        # cannot keep the dot yellow past the cap.
        self._hardcap_timer: dict[str, QTimer] = {}

    def _setup_git_overlay(self) -> None:
        """Configure overlay label for git info (bottom-right corner)."""
        self._lbl_git_info = QLabel("", self)
        self._lbl_git_info.setStyleSheet(
            "color: #71717A; font-size: 10px; background: transparent;"
            "font-family: 'JetBrains Mono', monospace;"
        )
        self._lbl_git_info.hide()

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
        if name == "kimid":
            self._signal_bus.run_command_in_workspace_terminal.emit(name)
        else:
            self._signal_bus.run_command_in_terminal.emit(name)

    def _apply_instance_styles(self) -> None:
        for i, btn in enumerate(self._instance_btns):
            btn.setStyleSheet(
                _INSTANCE_SELECTED if i == self._selected_instance else _INSTANCE_UNSELECTED
            )

    # ─── Drag & drop reordering (output-toolbar-center-top) ──────────── #

    def _load_instance_order(self) -> list[str]:
        """Le a ordem persistida e a reconcilia com o set canonico.

        Mantem apenas nomes canonicos preservando a ordem do usuario; nomes
        canonicos ausentes na persistencia (ex: depois de um upgrade que
        adicionou um botao novo) sao anexados ao final.
        """
        canonical = list(_CANONICAL_INSTANCE_NAMES)
        raw = self._instance_order_settings.value(_INSTANCE_ORDER_SETTINGS_KEY, None)
        persisted: list[str] = []
        if isinstance(raw, str) and raw:
            try:
                decoded = json.loads(raw)
                if isinstance(decoded, list):
                    persisted = [str(x) for x in decoded]
            except json.JSONDecodeError:
                persisted = []
        elif isinstance(raw, list):
            persisted = [str(x) for x in raw]

        result = [n for n in persisted if n in canonical]
        for n in canonical:
            if n not in result:
                result.append(n)
        return result

    def _save_instance_order(self) -> None:
        order = [b._instance_name for b in self._instance_btns]
        self._instance_order_settings.setValue(
            _INSTANCE_ORDER_SETTINGS_KEY, json.dumps(order)
        )

    def _on_instance_button_dropped(self, name: str, drop_x: int) -> None:
        """Reordena botoes no layout em resposta a um drop e persiste a ordem.

        `drop_x` e a coordenada x do drop no sistema de coordenadas do
        _instance_group. Posicao de insercao e calculada relativa aos centros
        horizontais dos botoes vizinhos.
        """
        src_idx = next(
            (i for i, b in enumerate(self._instance_btns) if b._instance_name == name),
            None,
        )
        if src_idx is None:
            return

        visual_target = len(self._instance_btns)
        for i, btn in enumerate(self._instance_btns):
            center = btn.x() + btn.width() // 2
            if drop_x < center:
                visual_target = i
                break

        target_idx = visual_target - 1 if src_idx < visual_target else visual_target
        if target_idx == src_idx:
            return

        selected_name: str | None = None
        if 0 <= self._selected_instance < len(self._instance_btns):
            selected_name = self._instance_btns[self._selected_instance]._instance_name

        layout = self._instance_group.layout()
        btn = self._instance_btns.pop(src_idx)
        layout.removeWidget(btn)
        self._instance_btns.insert(target_idx, btn)
        layout.insertWidget(target_idx, btn)

        if selected_name is not None:
            for i, b in enumerate(self._instance_btns):
                if b._instance_name == selected_name:
                    self._selected_instance = i
                    break

        self._apply_instance_styles()
        self._save_instance_order()

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

    # ─────────────────────────────────── Autocast (toggle + loop) ────── #
    #
    # State machine:
    #   OFF                 → button blue "autocast", no triggers fired.
    #   awaiting-busy       → just fired a step; if neither dot turns yellow within
    #                         _AUTOCAST_ARM_MS, queue is empty → switch back to OFF.
    #   running             → at least one dot turned yellow; when BOTH dots are
    #                         green again, fire next step and re-arm.
    #
    # The dot busy transitions are emitted by TerminalStatusDot.set_busy(), which
    # is the single source of truth for color changes.

    _AUTOCAST_ARM_MS = 1500      # window after a click in which busy must appear
    _AUTOCAST_DEBOUNCE_MS = 1000 # delay before re-firing on both-green (per spec)

    def _on_metrics_updated_for_ring(self, done: int, total: int) -> None:
        """Atualiza queue-progress-ring e o label de contagem associado."""
        try:
            d, t = int(done), int(total)
            if hasattr(self, "_queue_progress_ring"):
                self._queue_progress_ring.set_progress(d, t)
            if hasattr(self, "_lbl_queue_count"):
                self._lbl_queue_count.setText(f"{d}/{t}")
        except Exception:  # noqa: BLE001 - UI nao deve quebrar
            pass

    def _on_autocast_proxy_toggle(self, checked: bool) -> None:
        """Receive autocast toggle from play_bar (signal_bus) and forward to
        the existing toggle handler. Mirrors the legacy button state for
        backwards compatibility (some tests still inspect `_btn_autocast`).
        """
        if self._btn_autocast.isChecked() != bool(checked):
            self._btn_autocast.setChecked(bool(checked))
        else:
            self._on_autocast_toggled(bool(checked))

    def _on_autocast_toggled(self, checked: bool) -> None:
        # Notify play_bar button to stay in sync (e.g., auto-stop via arm timeout).
        self._signal_bus.autocast_state_changed.emit(bool(checked))
        if checked:
            self._autocast_phase = "awaiting-busy"
            self._btn_autocast.setText("parar")
            self._btn_autocast.setStyleSheet(_AUTOCAST_ON)
            self._ensure_autocast_timers()
            self._fire_autocast_step()
        else:
            self._autocast_phase = "off"
            self._btn_autocast.setText("autocast")
            self._btn_autocast.setStyleSheet(_AUTOCAST_OFF)
            if hasattr(self, "_autocast_arm_timer"):
                self._autocast_arm_timer.stop()
            if hasattr(self, "_autocast_fire_timer"):
                self._autocast_fire_timer.stop()

    def _ensure_autocast_timers(self) -> None:
        if not hasattr(self, "_autocast_arm_timer"):
            self._autocast_arm_timer = QTimer(self)
            self._autocast_arm_timer.setSingleShot(True)
            self._autocast_arm_timer.setInterval(self._AUTOCAST_ARM_MS)
            self._autocast_arm_timer.timeout.connect(self._on_autocast_arm_timeout)
        if not hasattr(self, "_autocast_fire_timer"):
            self._autocast_fire_timer = QTimer(self)
            self._autocast_fire_timer.setSingleShot(True)
            self._autocast_fire_timer.setInterval(self._AUTOCAST_DEBOUNCE_MS)
            self._autocast_fire_timer.timeout.connect(self._fire_autocast_step)

    def _fire_autocast_step(self) -> None:
        """Request CommandQueueWidget to click `queue-btn-play-next` and arm the window."""
        if not self._btn_autocast.isChecked():
            return
        if self._awaiting_user_input:
            return
        self._autocast_phase = "awaiting-busy"
        self._signal_bus.autocast_step_requested.emit()
        self._autocast_arm_timer.start()

    def _on_autocast_arm_timeout(self) -> None:
        """No dot turned yellow within the arm window → queue is empty, stop autocast."""
        if not self._btn_autocast.isChecked():
            return
        if self._autocast_phase != "awaiting-busy":
            return
        # Toggle the button OFF programmatically; toggled signal handles UI reset.
        self._btn_autocast.setChecked(False)

    def _on_interactive_input_requested(self) -> None:
        """AskUserQuestion is active — pause the autocast loop until the user replies."""
        self._awaiting_user_input = True

    def _on_user_input_submitted(self, _text: str) -> None:
        """User answered AskUserQuestion — release the autocast loop."""
        self._awaiting_user_input = False

    def _on_pipeline_completed_reset_input_guard(self) -> None:
        """Safety reset: clear the guard if the pipeline completes/cancels while active."""
        self._awaiting_user_input = False

    def _on_dot_busy_changed(self, _channel: str, busy: bool) -> None:
        if not self._btn_autocast.isChecked():
            return
        if busy:
            # Confirmed a command actually started — leave the awaiting window.
            if self._autocast_phase == "awaiting-busy":
                self._autocast_phase = "running"
                self._autocast_arm_timer.stop()
            return
        # Dot went green. Only proceed once BOTH are idle and we are in 'running'.
        if self._autocast_phase != "running":
            return
        if self._dot_interactive.is_busy or self._dot_workspace.is_busy:
            return
        # Debounce a touch so paired green-transitions arriving in the same tick
        # don't double-fire and so any late PTY chunk has a chance to flip yellow.
        # Guard: AskUserQuestion is pending — dots go green while CLI awaits human
        # input, which is semantically the opposite of "command completed".
        if self._awaiting_user_input:
            return
        self._autocast_fire_timer.start()

    # ─────────────────────────────────────────────────────── Signals ─── #

    def _connect_signals(self) -> None:
        bus = self._signal_bus

        # Terminal status dots — dual-mode: output-silence (10 s) + script notify
        bus.terminal_activity.connect(self._on_terminal_activity)
        bus.terminal_force_idle.connect(self._on_force_idle)
        bus.terminal_session_started.connect(self._on_terminal_session_started)
        bus.terminal_session_finished.connect(self._on_terminal_session_finished)

        # Autocast — listen to dot busy transitions to drive the loop state machine
        self._dot_interactive.busy_changed.connect(self._on_dot_busy_changed)
        self._dot_workspace.busy_changed.connect(self._on_dot_busy_changed)

        # Autocast/schedule buttons moved to play_bar (TASK-1 AC-1.4): receive
        # toggle/click via signal_bus and proxy to the existing state machine.
        bus.autocast_toggle_requested.connect(self._on_autocast_proxy_toggle)
        bus.schedule_autocast_requested.connect(self._on_schedule_clicked)

        # Autocast guard: pause the loop while AskUserQuestion awaits human input.
        bus.interactive_input_requested.connect(self._on_interactive_input_requested)
        bus.user_input_submitted.connect(self._on_user_input_submitted)
        bus.pipeline_completed.connect(self._on_pipeline_completed_reset_input_guard)
        bus.pipeline_cancelled.connect(self._on_pipeline_completed_reset_input_guard)

        # queue-progress-ring: tracking discreto via metrics_updated(done, total).
        bus.metrics_updated.connect(self._on_metrics_updated_for_ring)

        # Release authoritative idle lock when the app sends a new command,
        # so the dot can turn yellow again on real activity. Bound methods
        # (not lambdas) so the singleton bus does not retain stale closures
        # over self after MetricsBar destruction.
        bus.run_command_in_terminal.connect(self._on_command_dispatched_interactive)
        bus.run_command_in_workspace_terminal.connect(self._on_command_dispatched_workspace)
        # Blue-arrow Kimi dispatch uses a different signal (paste + 500ms +
        # Enter), but it IS still a command dispatch from the dot's POV —
        # without listening here the workspace epoch never advances and
        # any helper auto-idle scheduled before it would fire mid-command.
        bus.kimi_blue_arrow_dispatched.connect(self._on_command_dispatched_workspace)

        # Modo Remoto removido 2026-05-12 — sem connections para
        # remote_server_started/stopped/client_connected/disconnected.

        bus.tool_use_started.connect(self._on_tool_use_started)
        bus.tool_use_completed.connect(self._on_tool_use_completed)
        bus.token_update.connect(self._on_token_update)
        bus.metrics_snapshot.connect(self._on_metrics_snapshot)
        bus.git_info_updated.connect(self._on_git_info_updated)

        bus.config_loaded.connect(self._on_config_loaded_signal)
        bus.config_unloaded.connect(self._apply_project_empty)

    # ─────────────────────────────────────────────────────── Slots ───── #

    _COPY_FEEDBACK_MS = 2000

    # Handlers de Modo Remoto removidos em 2026-05-12 (botao eliminado).

    # ──────────────────────────────────────── Project widget slots ─── #

    def _resolve_walk_up(self, *segments: str) -> str | None:
        """Resolve `segments` ancorado na raiz do repositorio (marcador `.git`).

        Bugfix 2026-05-15: a versao anterior fazia walk-up retornando o
        PRIMEIRO ancestral com a pasta — quebrava quando havia uma pasta
        homonima intermediaria (ex: `ai-forge/workflow-app/blacksmith/`
        vazio, criado por engano, era retornado em vez do canonico
        `{repo_root}/blacksmith/`). Agora sobe ate achar `.git` (dir OU
        arquivo, para cobrir worktrees) e ancora ali.

        Returns o path absoluto se {repo_root}/{segments} existir, senao None.
        Usado para seed do file picker (.claude/projects para Projeto,
        blacksmith para Loop).
        """
        # `.git` sozinho nao serve como ancora: workflow-app e submodulo (tem
        # `.git` proprio dentro de systemForge), e `~/.git` tambem existe (home
        # dotfiles do usuario). Marcador unico do systemForge root: a pasta
        # `ai-forge/workflow-app/` so existe ali. Procuramos por ele.
        cur = Path(__file__).resolve().parent
        repo_root: Path | None = None
        while cur != cur.parent:
            if (cur / "ai-forge" / "workflow-app").is_dir():
                repo_root = cur
                break
            cur = cur.parent
        if repo_root is None:
            return None
        target = repo_root.joinpath(*segments)
        return str(target) if target.is_dir() else None

    def _open_config_picker(self, title: str, fallback_segments: tuple[str, ...]) -> None:
        """Shared picker for Projeto/Loop buttons.

        Opens a getOpenFileName dialog starting at the dir of the currently
        loaded config (when present); otherwise walks up to find the
        `fallback_segments` directory; otherwise uses cwd. Performs loop-
        schema validation by JSON content (not filename suffix) so that
        `_LOOP-CONFIG.json` and other non `-loop.json` names still get
        checked. Emits `config_change_requested(path)` on success.
        """
        from workflow_app.config.app_state import app_state
        start_dir = str(Path.cwd())
        if app_state.has_config and app_state.config:
            start_dir = str(Path(app_state.config.config_path).parent)
        else:
            resolved = self._resolve_walk_up(*fallback_segments)
            if resolved:
                start_dir = resolved
        path, _ = QFileDialog.getOpenFileName(
            self, title, start_dir,
            "JSON Files (*.json);;All Files (*)",
        )
        if not path:
            return
        p = Path(path)
        # Validacao por conteudo (nao por sufixo do filename): qualquer JSON
        # que pareca loop config (`-loop.json`, `_LOOP-CONFIG.json`, ou
        # totalmente arbitrario) e validado quando carrega campos canonicos
        # de loop OU declara `kind: daily-loop` + bloco `daily_loop`.
        try:
            raw_probe = json.loads(p.read_text(encoding="utf-8"))
        except Exception as exc:
            self._signal_bus.toast_requested.emit(
                f"Erro ao ler {p.name}: {exc}", "error"
            )
            return
        if isinstance(raw_probe, dict):
            has_loop_fields = (
                "iteration_template" in raw_probe
                and "items" in raw_probe
                and "finalization" in raw_probe
            )
            is_daily_loop_kind = (
                raw_probe.get("kind") == "daily-loop"
                and "daily_loop" in raw_probe
            )
            if has_loop_fields or is_daily_loop_kind:
                required = ["schema_version", "name"]
                if has_loop_fields:
                    required.extend(["iteration_template", "items", "finalization"])
                if is_daily_loop_kind:
                    required.append("daily_loop")
                # `mode` exigido em cmd/both (legacy `-cmd-loop.json` /
                # `-both-loop.json` por nome) e sempre que o proprio JSON
                # declarar `mode` (validamos o valor abaixo).
                if (
                    p.name.endswith("-cmd-loop.json")
                    or p.name.endswith("-both-loop.json")
                ):
                    required.append("mode")
                missing = [f for f in required if f not in raw_probe]
                if missing:
                    self._signal_bus.toast_requested.emit(
                        f"Schema invalido em {p.name}: campos ausentes "
                        f"{', '.join(missing)}. Verifique se o JSON segue o "
                        "LOOP_CANONICAL_TEMPLATE.",
                        "error",
                    )
                    return
                if "mode" in raw_probe and raw_probe["mode"] not in ("task", "cmd", "both"):
                    self._signal_bus.toast_requested.emit(
                        f"Schema invalido em {p.name}: modo "
                        f"'{raw_probe.get('mode')}' nao reconhecido. "
                        "Valores validos: task, cmd, both.",
                        "error",
                    )
                    return
        self.config_change_requested.emit(path)

    def _on_proj_select(self) -> None:
        self._open_config_picker(
            "Selecionar project.json", (".claude", "projects"),
        )

    def _on_loop_select(self) -> None:
        self._open_config_picker(
            "Selecionar _LOOP-CONFIG.json", ("blacksmith",),
        )

    def _on_proj_unload(self) -> None:
        self.config_unload_requested.emit()

    def _on_proj_open(self) -> None:
        """Seleciona pasta de projeto, carrega-o e abre no file manager.

        Fluxo:
        1. Abre QFileDialog.getExistingDirectory para selecionar a pasta raiz.
        2. Procura project.json em .claude/project.json ou .claude/projects/*.json.
        3. Emite config_change_requested para carregar o projeto (o MainWindow
           chama _load_config -> _restore_queue_from_storage automaticamente).
        4. Abre a pasta no file manager do SO via QDesktopServices.
        5. Toast explicito em todos os caminhos (Zero Silencio).
        """
        from pathlib import Path

        from PySide6.QtCore import QUrl
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtWidgets import QFileDialog

        start_dir = str(Path.cwd())
        folder = QFileDialog.getExistingDirectory(
            self, "Abrir pasta do projeto", start_dir
        )
        if not folder:
            return

        folder_path = Path(folder)

        # Procura project.json canonico
        candidates: list[Path] = [folder_path / ".claude" / "project.json"]
        projects_dir = folder_path / ".claude" / "projects"
        if projects_dir.exists():
            candidates.extend(sorted(projects_dir.glob("*.json")))
        config_path = None
        for c in candidates:
            if c.exists():
                config_path = str(c)
                break

        if not config_path:
            self._signal_bus.toast_requested.emit(
                "Nenhum project.json encontrado nesta pasta. "
                "Verifique se o diretorio contem .claude/project.json ou .claude/projects/*.json",
                "error",
            )
            return

        # Carrega projeto (MainWindow tratara o resto: queue-command-list, etc)
        self.config_change_requested.emit(config_path)

        # Abre pasta no file manager do SO
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder_path)))
        self._signal_bus.toast_requested.emit(
            f"Projeto carregado e pasta aberta: {folder_path.name}", "success"
        )

    def _on_config_loaded_signal(self, _path: str) -> None:
        from workflow_app.config.app_state import app_state
        if app_state.has_config:
            raw = app_state.config.raw if app_state.config else {}
            # Discriminar tipo de JSON pelo schema. `kind` e `loop_mode` sao
            # eixos ortogonais — extraimos `mode` sempre que o JSON tiver
            # campos canonicos de loop OU declarar `mode` no root, mesmo
            # quando `kind == "daily-loop"` (os dois convivem em archives
            # gerados por /loop+/daily-loop a partir de 2026-05).
            kind = "unknown"
            loop_mode: str | None = None
            has_loop_fields = False
            is_daily_loop_kind = False
            if isinstance(raw, dict):
                has_loop_fields = (
                    "iteration_template" in raw
                    and "items" in raw
                    and "finalization" in raw
                )
                is_daily_loop_kind = (
                    raw.get("kind") == "daily-loop" and "daily_loop" in raw
                )
                if is_daily_loop_kind:
                    kind = "daily-loop"
                elif has_loop_fields:
                    kind = "loop-json"
                # mode extraido independente do branch
                if has_loop_fields or is_daily_loop_kind:
                    candidate = raw.get("mode")
                    if candidate in ("task", "cmd", "both"):
                        loop_mode = candidate
                    elif has_loop_fields:
                        loop_mode = "task"  # default historico
            app_state.set_loop_mode(loop_mode)
            commercial = raw.get("commercial_name", "") or app_state.project_name
            feature = raw.get("feature_name", "")
            self._apply_project_loaded(commercial, feature)
            # Toast acionavel quando o JSON e um loop config — aponta o
            # botao certo da queue-strip e mostra contagem de pendencias
            # lida de PROGRESS.md (fallback: total declarado).
            if kind in ("daily-loop", "loop-json"):
                self._emit_loop_loaded_toast(raw, kind)

    def _emit_loop_loaded_toast(self, raw: dict, kind: str) -> None:
        """Toast pos-load para loop config: contagem de pendentes + CTA do botao certo."""
        from workflow_app.config.app_state import app_state
        loop_root: Path | None = None
        if app_state.has_config and app_state.config:
            loop_root = Path(app_state.config.config_path).parent
        # Contagem de pendentes: tenta PROGRESS.md (verdade) -> fallback
        # `daily_loop.total_items` -> fallback `len(items)`.
        pending: int | None = None
        if loop_root is not None:
            progress_path = loop_root / "PROGRESS.md"
            if progress_path.is_file():
                try:
                    from workflow_app.daily_loop.loader import (
                        parse_progress_items_loop,
                    )
                    items = parse_progress_items_loop(
                        progress_path.read_text(encoding="utf-8")
                    )
                    pending = sum(1 for it in items if it.status == "pending")
                except Exception:
                    pending = None
        if pending is None:
            total_items = raw.get("daily_loop", {}).get("total_items")
            if isinstance(total_items, int):
                pending = total_items
            else:
                pending = len(raw.get("items", []) or [])
        # CTA: daily-loop legacy aponta queue-btn-daily-loop; loop-json
        # (mode task/cmd/both) aponta queue-btn-loop. JSONs que carregam
        # AMBOS os shapes (kind=daily-loop + iteration_template) sao
        # despachaveis pelos dois botoes — preferimos queue-btn-loop
        # (familia /loop nova) quando `mode` esta presente no root.
        has_loop_fields = (
            "iteration_template" in raw and "items" in raw and "finalization" in raw
        )
        if has_loop_fields and raw.get("mode") in ("task", "cmd", "both"):
            cta_btn = "queue-btn-loop"
            cta_label = "Loop"
        elif kind == "daily-loop":
            cta_btn = "queue-btn-daily-loop"
            cta_label = "Daily loop"
        else:
            cta_btn = "queue-btn-loop"
            cta_label = "Loop"
        slug = (
            raw.get("daily_loop", {}).get("slug")
            or raw.get("name")
            or "loop"
        )
        toast_type = "info" if pending else "warning"
        msg = (
            f"{cta_label} carregado ({slug}): {pending} pendente(s). "
            f"Clique `{cta_btn}` na barra de queue para enfileirar."
        )
        if pending == 0:
            msg = (
                f"{cta_label} carregado ({slug}): nenhum item pendente em "
                "PROGRESS.md. Loop ja concluido — rode review/clear conforme "
                "o fluxo."
            )
        self._signal_bus.toast_requested.emit(msg, toast_type)

    def _apply_project_loaded(self, name: str, feature_name: str = "") -> None:
        self._project_name_lbl.setText(name)
        self._project_pill.show()
        self._project_name_lbl.show()
        self._proj_x.show()
        self._proj_select_btn.hide()
        self._loop_select_btn.hide()
        self._proj_open_btn.hide()
        if feature_name:
            self._feature_name_input.setText(feature_name)
            self._feature_name_input.show()
        else:
            self._feature_name_input.setText("")
            self._feature_name_input.hide()

    def _apply_project_empty(self) -> None:
        self._project_pill.hide()
        self._feature_name_input.setText("")
        self._feature_name_input.hide()
        self._proj_select_btn.show()
        self._loop_select_btn.show()
        self._proj_open_btn.show()

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

    # ── Terminal status dot slots ─────────────────────────────────────── #

    def _clean_stale_notify_files(self) -> None:
        """Truncate notify files with expired timestamps on startup."""
        import time as _time
        for p in self._notify_files.values():
            try:
                data = json.loads(p.read_text())
                exp = data.get("exp", 0)
                if exp and _time.time() > exp:
                    p.write_text("{}")
            except Exception:
                pass

    def _on_notify_directory_changed(self, _path: str) -> None:
        """Re-create + re-watch any notify file that was deleted at runtime.

        QFileSystemWatcher drops a watched file path on delete and never
        re-arms it on its own. Without this recovery the channel stays
        disconnected from notify events for the rest of the app session.
        """
        for ch, p in self._notify_files.items():
            if not p.exists():
                try:
                    p.write_text("{}")
                except OSError:
                    continue
            if str(p) not in self._notify_watcher.files():
                self._notify_watcher.addPath(str(p))

    def _on_notify_file_changed(self, path: str) -> None:
        """QFileSystemWatcher callback — skill script wrote the notify file."""
        import time as _time
        try:
            data = json.loads(Path(path).read_text())
            channel = data.get("channel", "")
            exp = data.get("exp", 0)
            iat = data.get("iat", 0)
            # Reject stale notifications (app was not running when script fired).
            if exp and _time.time() > exp:
                return
            # Defense in depth: reject if JSON channel contradicts the filename.
            # Prevents cross-channel contamination from manual edits or external writes.
            expected = next(
                (c for c, p in self._notify_files.items() if str(p) == path), None
            )
            if expected is not None and channel != expected:
                return
            if data.get("state") == "idle" and channel in ("interactive", "workspace"):
                # Epoch fence: drop notifies that do not strictly post-date
                # the latest command dispatched on this channel. Without
                # this, a delayed notify from command A could re-lock the dot
                # while command B is actively running. `<=` (not `<`) closes
                # the same-tick equality boundary.
                if iat and iat <= self._command_epoch.get(channel, 0.0):
                    return
                # Session fence: while a runner-backed session is active,
                # the dot is owned by terminal_session_started/finished.
                # An authoritative notify here would silently mask runner
                # output until the next command.
                if self._session_active.get(channel):
                    return
                # Workspace (Kimi) bypasses hardening entirely — Kimi's TUI
                # emits continuous subtle PTY chunks at the input prompt
                # which would reset any soft timer forever. Instead, wait
                # a fixed 5s after notify then go straight to green.
                # Interactive (Claude Code) keeps the strict hardening
                # contract: 3s soft, no hardcap. Claude genuinely goes
                # silent at its prompt so soft fires reliably on its own.
                if channel == "workspace":
                    self._arm_workspace_post_notify_timeout()
                else:
                    self._arm_hardening(channel)
        except Exception:
            pass
        # Some Linux inotify backends remove the watch after IN_CLOSE_WRITE; re-add it.
        if path not in self._notify_watcher.files():
            self._notify_watcher.addPath(path)

    def _on_force_idle(self, channel: str) -> None:
        """OutputPanel detected 2s of PTY silence on this channel.

        Used ONLY for `interactive` (Claude) — the workspace OutputPanel
        does not arm its idle timer (see output_panel.py `_on_chunk`).
        For interactive, this is the silence-based path that lets Claude
        go green even when a skill doesn't write a notify file for it.

        Defensive: if this somehow fires for workspace (e.g. future code
        change or session_finished path), no-op to preserve workspace's
        explicit 5s post-notify contract.
        """
        if channel != "interactive":
            return
        if self._idle_locked.get(channel):
            return
        self._arm_hardening(channel)

    def _on_idle_confirmed(self, channel: str) -> None:
        """Soft hardening timer fired — true silence reached after notify.

        Promote the channel to authoritative idle: green + lock. Subsequent
        chunks (post-stream cursor animations, mouse-click repaints) will
        be ignored.
        """
        self._enter_authoritative_idle(channel)

    def _arm_hardening(self, channel: str, hardcap_ms: int | None = None) -> None:
        """Enter the hardening phase. Dot stays YELLOW until soft timer
        expires (3s of true silence) OR optional hardcap fires.

        Two callers, two contracts:
          - `_on_notify_file_changed` calls without hardcap → strict
            "if there's activity, NOT green" contract. Skills that emit
            forever stay yellow forever (correct).
          - `_helper_auto_idle` calls with hardcap_ms=5000 → helpers
            (/clear, /model, etc) eventually flip green even if Kimi's
            TUI emits invisible CPR/cursor chunks indefinitely.

        Hardcap timers are created on-demand and cached in
        `self._hardcap_timer[channel]`.
        """
        if self._idle_locked.get(channel):
            return
        idle = self._idle_timer_for(channel)
        if idle:
            idle.start()  # 3s soft window, resets on activity
        if hardcap_ms is not None:
            cap = self._hardcap_timer.get(channel)
            if cap is None:
                cap = QTimer(self)
                cap.setSingleShot(True)
                cap.timeout.connect(
                    lambda _ch=channel: self._on_hardcap_expired(_ch)
                )
                self._hardcap_timer[channel] = cap
            cap.setInterval(hardcap_ms)
            cap.start()  # absolute ceiling, never resets on activity

    def _on_hardcap_expired(self, channel: str) -> None:
        """Hard cap reached — force authoritative idle even if chunks
        are still flowing (typical for Kimi's animated prompt)."""
        self._enter_authoritative_idle(channel)

    def _arm_workspace_post_notify_timeout(self) -> None:
        """Workspace-only: schedule plain 5s timer to green after notify.

        Bypasses the chunk-watching hardening path (which would never
        complete because Kimi's input prompt emits subtle PTY bytes
        forever). Cancellable: any new dispatch on workspace calls
        `_release_idle_lock` which stops this timer too.
        """
        if self._idle_locked.get("workspace"):
            return
        # Reuse the workspace hardcap slot as the post-notify timer —
        # _release_idle_lock already stops it on next dispatch. Different
        # interval but same lifecycle semantics.
        cap = self._hardcap_timer.get("workspace")
        if cap is None:
            cap = QTimer(self)
            cap.setSingleShot(True)
            cap.timeout.connect(
                lambda: self._on_hardcap_expired("workspace")
            )
            self._hardcap_timer["workspace"] = cap
        cap.setInterval(self._WORKSPACE_POST_NOTIFY_MS)
        cap.start()

    def _enter_authoritative_idle(self, channel: str) -> None:
        """Promote channel to green + locked. PTY repaint chunks (cursor
        blink, Rich status bar, mouse-click repaints, etc.) are ignored
        until the app sends the next command or an external session starts.
        """
        idle = self._idle_timer_for(channel)
        if idle:
            idle.stop()
        cap = self._hardcap_timer.get(channel)
        if cap:
            cap.stop()
        self._idle_locked[channel] = True
        dot = self._dot_for(channel)
        if dot:
            dot.set_busy(False)

    def _release_idle_lock(self, channel: str) -> None:
        """Release the authoritative idle lock for a channel.

        Also cancels any in-flight hardening (idle/hardcap timers) so a new
        command does not get prematurely promoted by a stale notify.
        """
        self._idle_locked[channel] = False
        idle = self._idle_timer_for(channel)
        if idle:
            idle.stop()
        cap = self._hardcap_timer.get(channel)
        if cap:
            cap.stop()

    def _bump_command_epoch(self, channel: str) -> None:
        """Advance the per-channel epoch fence to wall-clock now.

        Subsequent notifies whose payload `iat` is `<=` this epoch are
        rejected by `_on_notify_file_changed`. Solves the A/B race where a
        delayed notify from command A would otherwise re-lock the dot while
        command B is already running.

        Defenses:
          - Clamps to never-decrease, so a backward NTP step cannot reset
            the fence below an older notify's iat.
          - Uses `<=` comparison on the reader side, so two events at the
            same tick (epoch == iat) reject the notify rather than accept it.
        """
        import time as _time
        self._command_epoch[channel] = max(
            self._command_epoch.get(channel, 0.0), _time.time()
        )

    def _on_command_dispatched_interactive(self, cmd: str) -> None:
        """Bound slot — a new interactive command was dispatched. Bump
        epoch, release lock, force dot yellow as immediate UI feedback,
        and (for helpers) schedule the deferred hardening arm.

        Forcing yellow on dispatch matters for commands the CLI processes
        silently (e.g. Kimi's `/clear` emits no PTY output). Without this,
        the dot would stay green and the user would have no visual
        confirmation that the command was actually dispatched.
        """
        self._bump_command_epoch("interactive")
        self._release_idle_lock("interactive")
        self._dot_interactive.set_busy(True)
        self._maybe_schedule_helper_auto_idle("interactive", cmd)

    def _on_command_dispatched_workspace(self, cmd: str) -> None:
        """Bound slot — a new workspace command was dispatched."""
        self._bump_command_epoch("workspace")
        self._release_idle_lock("workspace")
        self._dot_workspace.set_busy(True)
        self._maybe_schedule_helper_auto_idle("workspace", cmd)

    # Queue helpers — no notify file, just mutate CLI session state or
    # change the bash environment. All these get a deferred hardening
    # arm so the dot eventually goes green after their brief output.
    _HELPER_COMMANDS: tuple[str, ...] = (
        "/model", "/effort", "/clear",            # slash-helpers
        "cd",                                      # bash directory change
        "clauded", "kimid", "clauded2", "kimid2",  # CLI launches
    )
    _HELPER_AUTO_IDLE_MS: int = 1_000
    # Extra delay added to /clear on the workspace channel: Kimi's TUI
    # repaint after a clear takes longer than a regular helper, so the
    # dot must stay yellow longer before hardening arms.
    _CLEAR_WORKSPACE_EXTRA_MS: int = 1_000

    def _maybe_schedule_helper_auto_idle(self, channel: str, cmd: str) -> None:
        """Schedule auto-green for queue helpers that don't notify on completion.

        These commands are processed by the CLI in well under a second, but
        they don't write a notify file because they're queue-side helpers
        (model switch, effort change, context clear) rather than skills.
        Without this hook the dot would stay yellow forever after the helper.

        Epoch-guarded: if a newer command is dispatched on the same channel
        before the timer fires, the auto-idle is dropped — prevents a stale
        helper schedule from flipping a real command's dot green prematurely.

        Uses the `QTimer.singleShot(msec, context, slot)` overload with `self`
        as context so the timer is auto-cancelled if MetricsBar is destroyed
        before it fires (avoids "C++ object already deleted" in tests).
        """
        if not self._is_helper_command(cmd):
            return
        scheduled_epoch = self._command_epoch.get(channel, 0.0)
        head = cmd.strip().split(None, 1)[0].lower() if cmd.strip() else ""
        delay_ms = self._HELPER_AUTO_IDLE_MS
        # /clear on workspace gets +1s extra because Kimi's TUI repaint
        # after a clear is slower — the dot must stay yellow longer to
        # cover the repaint window before hardening arms.
        if channel == "workspace" and head == "/clear":
            delay_ms += self._CLEAR_WORKSPACE_EXTRA_MS
        QTimer.singleShot(
            delay_ms,
            self,
            lambda: self._helper_auto_idle(channel, scheduled_epoch),
        )

    def _is_helper_command(self, cmd: str) -> bool:
        """Match a queue helper by the leading slash-token (case-insensitive)."""
        if not cmd or not cmd.strip():
            return False
        head = cmd.strip().split(None, 1)[0].lower()
        return head in self._HELPER_COMMANDS

    # Hardcap window — only used by HELPERS (no notify file) on either
    # channel. Skills on interactive use no cap (Claude truly idles).
    # Skills on workspace use `_arm_workspace_post_notify_timeout`
    # instead (5s fixed timer, no chunk-watching).
    _HELPER_HARDCAP_MS: int = 5_000
    # Workspace post-notify timeout: fixed delay between notify file
    # arrival and green. Bypasses chunk-watching since Kimi's input
    # prompt emits subtle PTY bytes that would reset any soft timer.
    _WORKSPACE_POST_NOTIFY_MS: int = 5_000

    def _helper_auto_idle(self, channel: str, scheduled_epoch: float) -> None:
        """Arm hardening on behalf of a helper command (no notify file).

        Helpers (/clear /model /effort, also `cd` and `kimid`) don't write
        notify files because they're not skills — they just mutate CLI
        session state. Auto-idle waits 1s/2s post-dispatch then arms
        hardening WITH a 5s hardcap. The hardcap guarantees the dot turns
        green even if Kimi's TUI keeps emitting invisible cursor/CPR
        chunks (Codex/Kimi /skill:double-mcp consensus: option B).

        Race protection: helper at t=0, real command at t=0.5 → at t=1 the
        helper's auto-idle would otherwise hand control over to a stale
        hardening. Comparing epochs cancels the late auto-idle.
        """
        if self._command_epoch.get(channel, 0.0) > scheduled_epoch:
            return
        self._arm_hardening(channel, hardcap_ms=self._HELPER_HARDCAP_MS)

    def _on_terminal_activity(self, channel: str) -> None:
        """Any PTY output chunk — turn dot yellow.

        If the soft idle timer is active (notify already fired and we are in
        the hardening window), reset it so post-notify streaming output keeps
        the dot yellow until 2s of true silence. The hard cap timer is NOT
        reset here — it is the absolute ceiling that guarantees we eventually
        leave the hardening phase even if chunks never stop (Kimi animations).
        """
        if self._idle_locked.get(channel):
            return
        dot = self._dot_for(channel)
        timer = self._idle_timer_for(channel)
        if dot:
            dot.set_busy(True)
        if timer and timer.isActive():
            timer.start()  # reset 2s countdown while summary is still printing

    def _on_terminal_session_started(self, channel: str) -> None:
        """External PTY session started — ensure dot is yellow, stop idle timer."""
        self._session_active[channel] = True
        self._release_idle_lock(channel)
        dot = self._dot_for(channel)
        timer = self._idle_timer_for(channel)
        if timer:
            timer.stop()
        if dot:
            dot.set_busy(True)

    def _on_terminal_session_finished(self, channel: str) -> None:
        """External PTY session finished — clear the session fence so
        notify-driven hardening can engage on the next legitimate notify.
        """
        self._session_active[channel] = False

    def _dot_for(self, channel: str) -> "TerminalStatusDot | None":
        if channel == "interactive":
            return self._dot_interactive
        if channel == "workspace":
            return self._dot_workspace
        return None

    def _idle_timer_for(self, channel: str) -> "QTimer | None":
        if channel == "interactive":
            return self._idle_timer_interactive
        if channel == "workspace":
            return self._idle_timer_workspace
        return None

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

    # MARKER_SCHEDULE_AUTOCAST_HELPERS - helpers do schedule-autocast
    @staticmethod
    def _format_schedule_remaining(total_seconds: int) -> str:
        total_seconds = max(0, int(total_seconds))
        h, rem = divmod(total_seconds, 3600)
        m, s = divmod(rem, 60)
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def _on_schedule_clicked(self) -> None:
        if self._schedule_end_at is None:
            from workflow_app.metrics_bar.schedule_autocast_dialog import (
                ScheduleAutocastDialog,
            )
            dialog = ScheduleAutocastDialog(self)
            if dialog.exec() != ScheduleAutocastDialog.DialogCode.Accepted:
                return
            seconds = dialog.total_seconds()
            if seconds <= 0:
                return
            self._schedule_end_at = QDateTime.currentDateTime().addSecs(seconds)
            _write_schedule_state(self._schedule_end_at.toString(Qt.DateFormat.ISODate))
            self._schedule_timer.start()
            self._update_schedule_visual()
            return

        # Cancelamento
        self._schedule_timer.stop()
        self._schedule_end_at = None
        _clear_schedule_state()
        self._reset_schedule_visual_to_idle()

    def _on_schedule_tick(self) -> None:
        if self._schedule_end_at is None:
            self._schedule_timer.stop()
            return
        remaining = QDateTime.currentDateTime().secsTo(self._schedule_end_at)
        if remaining <= 0:
            self._schedule_timer.stop()
            self._fire_schedule_autocast()
            return
        self._update_schedule_visual()

    def _update_schedule_visual(self) -> None:
        if self._schedule_end_at is None:
            return
        remaining = max(0, QDateTime.currentDateTime().secsTo(self._schedule_end_at))
        label = self._format_schedule_remaining(remaining)
        tooltip = f"Clique para cancelar - dispara em {label}"
        self._btn_schedule_autocast.setText(label)
        self._btn_schedule_autocast.setStyleSheet(_SCHEDULE_RUNNING)
        self._btn_schedule_autocast.setToolTip(tooltip)
        self._signal_bus.schedule_autocast_visual_changed.emit(
            label, _SCHEDULE_RUNNING, tooltip
        )

    def _fire_schedule_autocast(self) -> None:
        _clear_schedule_state()
        # Ja ligado: ignorar silenciosamente, sem clicar, sem toast, sem tooltip.
        if self._btn_autocast.isChecked():
            self._schedule_end_at = None
            self._reset_schedule_visual_to_idle()
            return

        self._schedule_end_at = None
        self._btn_schedule_autocast.setText("disparado")
        self._btn_schedule_autocast.setStyleSheet(_SCHEDULE_FIRED)
        self._btn_schedule_autocast.setToolTip("Autocast disparado")
        self._signal_bus.schedule_autocast_visual_changed.emit(
            "disparado", _SCHEDULE_FIRED, "Autocast disparado"
        )
        QTimer.singleShot(2000, self._reset_schedule_visual_to_idle)
        self._btn_autocast.click()

    def _reset_schedule_visual_to_idle(self) -> None:
        self._btn_schedule_autocast.setText("agendar")
        self._btn_schedule_autocast.setStyleSheet(_SCHEDULE_IDLE)
        self._btn_schedule_autocast.setToolTip(
            "Agendar disparo automatico do autocast"
        )
        self._signal_bus.schedule_autocast_visual_changed.emit(
            "agendar", _SCHEDULE_IDLE, "Agendar disparo automatico do autocast"
        )
