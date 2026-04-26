"""Per-module detail view for the workflow-app (T-038).

Canonical source: ``detailed.md §9.2`` (DCP-9.2 — SPECIFIC-FLOW resolution
with fallback), ``§9.3`` (DCP-9.3 — click num module carrega SPECIFIC-FLOW
dele), ``§9.4`` (DCP-9.4 — cooperative lock), ``§9.5`` (DCP-9.5 — reader).
TASK-038 frontmatter cites ``§16.2`` which does not exist in detailed.md;
the canonical behavior lives in §9.2/§9.3/§9.5. See EXECUTION-READINESS-T-038
drift D2 for the resolution.

The view is opened from the Kanban (T-036) when the user clicks a module
card. Layout:

    ┌────────────────────────────────────────────────────────────┐
    │ Header: [← Kanban]  module-1-foo  (execution)  #2  🔐 auth │
    ├────────────────────────────────────────────────────────────┤
    │ Tab selector: [Metadados][Artefatos][History][Gates][Pipe] │
    ├────────────────────────────────────────────────────────────┤
    │                                                            │
    │                     ArtifactTabs content                   │
    │                                                            │
    ├────────────────────────────────────────────────────────────┤
    │ Action bar: [Run][Pause][Unblock][Reopen]     [Terminal]   │
    └────────────────────────────────────────────────────────────┘

**NO Promote / NO Rollback**: per DCP state machine (T-006), transicoes
forcadas devem usar ``/delivery:unblock``, ``/delivery:reopen`` ou edicao
auditada de ``delivery.json``. Verificado por teste explicito.

Subprocess execution uses ``QProcess`` for non-blocking I/O. The hint in
TASK-038 mentions ``QThread + Worker`` but ``QProcess`` is the Qt-idiomatic
choice for spawning CLI processes without blocking the UI thread.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Callable, List, Optional

from PySide6.QtCore import QProcess, Qt, Signal
from PySide6.QtWidgets import (
    QButtonGroup,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from workflow_app.models.delivery import (
    Delivery,
    ModuleState,
    ModuleStateLiteral,
    ReworkPhase,
)
from workflow_app.services.delivery_reader import (
    DeliveryFound,
    DeliveryFutureVersion,
    DeliveryInvalid,
    DeliveryMissing,
    DeliveryReader,
)
from workflow_app.signal_bus import signal_bus
from workflow_app.views.kanban import STATE_COLORS, STATE_LABELS
from workflow_app.widgets.action_bar import ActionBar
from workflow_app.widgets.artifact_tabs import (
    ArtifactTabs,
    TAB_LABELS,
    TAB_TESTIDS,
)
from workflow_app.widgets.module_card import MODULE_TYPE_ICONS

logger = logging.getLogger(__name__)

_VIEW_BG = "#0F0F11"
_HEADER_BG = "#18181B"
_HEADER_BORDER = "#27272A"
_TEXT_PRIMARY = "#F4F4F5"
_TEXT_MUTED = "#A1A1AA"
_SELECTOR_BG = "#131316"
_SELECTOR_BTN_BG = "#1F1F22"
_SELECTOR_BTN_ACTIVE_BG = "#2563EB"
_REWORK_PHASES: tuple[str, ...] = (
    "creation",
    "execution",
    "revision",
    "qa",
    "deploy",
)


class ReopenDialog(QDialog):
    """Modal prompting for ``--phase`` (required) and ``--reason`` (optional).

    ``--phase`` values come from the ``ReworkPhase`` literal in
    ``models/delivery.py``. Reason defaults to
    ``"manual reopen via workflow-app"`` when left blank.
    """

    def __init__(self, module_id: str, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._module_id = module_id
        self.setWindowTitle(f"Reabrir {module_id}")
        self.setProperty("testid", "reopen-dialog")
        self.setModal(True)

        layout = QFormLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        intro = QLabel(
            f"Reabrir <b>{module_id}</b> em qual fase?"
        )
        layout.addRow(intro)

        self._phase_combo = QComboBox()
        self._phase_combo.setProperty("testid", "reopen-phase-combo")
        for phase in _REWORK_PHASES:
            self._phase_combo.addItem(phase)
        layout.addRow("Phase:", self._phase_combo)

        self._reason_edit = QLineEdit()
        self._reason_edit.setPlaceholderText("Motivo opcional")
        self._reason_edit.setProperty("testid", "reopen-reason-edit")
        layout.addRow("Reason:", self._reason_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setProperty(
            "testid", "reopen-btn-ok"
        )
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setProperty(
            "testid", "reopen-btn-cancel"
        )
        layout.addRow(buttons)

    def selected_phase(self) -> ReworkPhase:
        return self._phase_combo.currentText()  # type: ignore[return-value]

    def selected_reason(self) -> str:
        text = self._reason_edit.text().strip()
        return text or "manual reopen via workflow-app"


class ModuleDetailView(QWidget):
    """Full per-module detail view with 5 tabs + contextual action bar.

    Signals:
        back_requested(): emitted when the user clicks "← Kanban" in the
            header. The main window swaps the view stack back to the Kanban
            page.

    Public API:
        set_wbs_root(wbs_root): update the wbs_root used by subsequent
            ``show_for`` calls.
        show_for(module_id): (re)load ``delivery.json`` from the cached
            ``wbs_root``, populate all 5 tabs for ``module_id`` and update
            the action bar. Emits a toast on failure and does not switch.
        clear(): reset the view to an empty state.
    """

    back_requested = Signal()

    def __init__(
        self,
        reader: DeliveryReader,
        lock_service: object = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._reader = reader
        self._lock_service = lock_service  # reserved for future lock-aware edits
        self._wbs_root: Optional[Path] = None
        self._current_module_id: Optional[str] = None
        self._current_delivery: Optional[Delivery] = None
        self._tab_buttons: List[QPushButton] = []

        self.setObjectName("ModuleDetailView")
        self.setProperty("testid", "view-module-detail")
        self.setStyleSheet(
            f"QWidget#ModuleDetailView {{ background-color: {_VIEW_BG}; }}"
        )

        self._setup_ui()

    # ─────────────────────────────────────────────────────────── UI ──── #

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        root.addWidget(self._build_header())
        root.addWidget(self._build_tab_selector())

        self._artifact_tabs = ArtifactTabs(parent=self)
        self._artifact_tabs.artifact_clicked.connect(self._on_artifact_clicked)
        root.addWidget(self._artifact_tabs, stretch=1)

        self._action_bar = ActionBar(parent=self)
        self._action_bar.run_requested.connect(self._on_run)
        self._action_bar.pause_requested.connect(self._on_pause)
        self._action_bar.unblock_requested.connect(self._on_unblock)
        self._action_bar.reopen_requested.connect(self._on_reopen)
        self._action_bar.open_terminal_requested.connect(self._on_open_terminal)
        root.addWidget(self._action_bar)

    def _build_header(self) -> QWidget:
        header = QFrame()
        header.setObjectName("DetailHeader")
        header.setFixedHeight(48)
        header.setStyleSheet(
            f"QFrame#DetailHeader {{"
            f"  background-color: {_HEADER_BG};"
            f"  border-bottom: 1px solid {_HEADER_BORDER};"
            f"}}"
        )

        layout = QHBoxLayout(header)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(12)

        self._back_btn = QPushButton("← Kanban")
        self._back_btn.setProperty("testid", "detail-btn-back")
        self._back_btn.setFixedHeight(28)
        self._back_btn.setMinimumWidth(96)
        self._back_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {_SELECTOR_BTN_BG}; color: {_TEXT_PRIMARY};"
            f"  border: 1px solid #3F3F46; border-radius: 4px;"
            f"  padding: 4px 10px; font-size: 11px; font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background-color: #27272A; }}"
        )
        self._back_btn.clicked.connect(self.back_requested)
        layout.addWidget(self._back_btn)

        self._title_label = QLabel("Nenhum modulo")
        self._title_label.setStyleSheet(
            f"color: {_TEXT_PRIMARY}; font-size: 14px; font-weight: 700;"
            f" background: transparent; border: none;"
        )
        self._title_label.setProperty("testid", "detail-title")
        layout.addWidget(self._title_label)

        self._state_badge = QLabel("")
        self._state_badge.setStyleSheet(
            f"color: #FFFFFF; background-color: #3F3F46;"
            f" padding: 3px 10px; border-radius: 10px;"
            f" font-size: 11px; font-weight: 700;"
        )
        self._state_badge.setProperty("testid", "detail-state-badge")
        self._state_badge.hide()
        layout.addWidget(self._state_badge)

        self._blocked_prev_label = QLabel("")
        self._blocked_prev_label.setStyleSheet(
            f"color: {_TEXT_MUTED}; font-size: 11px;"
            f" background: transparent; border: none;"
        )
        self._blocked_prev_label.setProperty("testid", "detail-blocked-prev")
        self._blocked_prev_label.hide()
        layout.addWidget(self._blocked_prev_label)

        self._attempt_label = QLabel("")
        self._attempt_label.setStyleSheet(
            f"color: {_TEXT_MUTED}; font-size: 11px;"
            f" background: transparent; border: none;"
        )
        self._attempt_label.setProperty("testid", "detail-attempt")
        layout.addWidget(self._attempt_label)

        layout.addStretch(1)

        self._module_type_label = QLabel("")
        self._module_type_label.setStyleSheet(
            f"color: {_TEXT_MUTED}; font-size: 11px;"
            f" background: transparent; border: none;"
        )
        self._module_type_label.setProperty("testid", "detail-module-type")
        layout.addWidget(self._module_type_label)

        return header

    def _build_tab_selector(self) -> QWidget:
        selector = QFrame()
        selector.setObjectName("DetailTabSelector")
        selector.setFixedHeight(36)
        selector.setStyleSheet(
            f"QFrame#DetailTabSelector {{"
            f"  background-color: {_SELECTOR_BG};"
            f"  border-bottom: 1px solid {_HEADER_BORDER};"
            f"}}"
        )

        layout = QHBoxLayout(selector)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(4)

        self._tab_group = QButtonGroup(self)
        self._tab_group.setExclusive(True)

        for index, (label, testid) in enumerate(zip(TAB_LABELS, TAB_TESTIDS)):
            btn = QPushButton(label)
            btn.setCheckable(True)
            btn.setProperty("testid", f"detail-selector-{testid}")
            btn.setFixedHeight(26)
            btn.setMinimumWidth(94)
            btn.setStyleSheet(
                f"QPushButton {{"
                f"  background-color: {_SELECTOR_BTN_BG};"
                f"  color: {_TEXT_PRIMARY};"
                f"  border: 1px solid #27272A; border-radius: 4px;"
                f"  padding: 3px 10px; font-size: 11px; font-weight: 600;"
                f"}}"
                f"QPushButton:hover {{ background-color: #27272A; }}"
                f"QPushButton:checked {{"
                f"  background-color: {_SELECTOR_BTN_ACTIVE_BG};"
                f"  border-color: {_SELECTOR_BTN_ACTIVE_BG};"
                f"}}"
            )
            btn.clicked.connect(
                lambda _checked=False, i=index: self._on_tab_selected(i)
            )
            self._tab_group.addButton(btn, index)
            self._tab_buttons.append(btn)
            layout.addWidget(btn)

        layout.addStretch(1)

        self._tab_buttons[0].setChecked(True)
        return selector

    # ──────────────────────────────────────────────────────────── API ──── #

    def set_wbs_root(self, wbs_root: Optional[Path]) -> None:
        """Bind the view to a new ``wbs_root`` (or ``None`` on unload)."""
        self._wbs_root = Path(wbs_root) if wbs_root else None
        if self._wbs_root is None:
            self.clear()

    def show_for(self, module_id: str) -> None:
        """Load ``delivery.json`` from the cached ``wbs_root`` and render
        ``module_id``.

        Emits a ``toast_requested`` error and leaves the view unchanged if
        the module cannot be resolved (missing wbs_root, invalid delivery,
        unknown module).
        """
        if self._wbs_root is None:
            self._emit_toast(
                "Nenhum projeto carregado — abra um projeto primeiro.",
                "error",
            )
            return

        self._reader.invalidate_cache()
        result = self._reader.load(self._wbs_root)
        if isinstance(result, DeliveryMissing):
            self._emit_toast(
                f"delivery.json nao encontrado em {result.path}", "error"
            )
            return
        if isinstance(result, DeliveryInvalid):
            self._emit_toast(
                f"delivery.json invalido: {result.error}", "error"
            )
            return
        if isinstance(result, DeliveryFutureVersion):
            self._emit_toast(result.message, "error")
            return

        assert isinstance(result, DeliveryFound)
        delivery = result.delivery
        module_state = delivery.modules.get(module_id)
        if module_state is None:
            self._emit_toast(
                f"Modulo {module_id!r} nao encontrado em delivery.json",
                "error",
            )
            return

        self._current_delivery = delivery
        self._current_module_id = module_id
        self._update_header(module_id, module_state)

        project_root = result.path.parent.parent  # wbs_root → project_root
        self._artifact_tabs.load(
            delivery=delivery,
            module_state=module_state,
            module_id=module_id,
            reader=self._reader,
            wbs_root=self._wbs_root,
            project_root=project_root,
        )
        self._action_bar.update_for_state(module_id, module_state.state)

        # Reset to first tab whenever a new module opens.
        self._tab_buttons[0].setChecked(True)
        self._artifact_tabs.setCurrentIndex(0)

    def clear(self) -> None:
        """Reset the view to an empty state (title, tabs, action bar)."""
        self._current_module_id = None
        self._current_delivery = None
        self._title_label.setText("Nenhum modulo")
        self._state_badge.hide()
        self._blocked_prev_label.hide()
        self._attempt_label.setText("")
        self._module_type_label.setText("")
        self._artifact_tabs.clear()
        self._action_bar.clear()

    # ───────────────────────────────────────────── Header internals ──── #

    def _update_header(
        self,
        module_id: str,
        module_state: ModuleState,
    ) -> None:
        self._title_label.setText(module_id)

        state = module_state.state
        label = STATE_LABELS.get(state, state)
        color = STATE_COLORS.get(state, "#3F3F46")
        self._state_badge.setText(label)
        self._state_badge.setStyleSheet(
            f"color: #FFFFFF; background-color: {color};"
            f" padding: 3px 10px; border-radius: 10px;"
            f" font-size: 11px; font-weight: 700;"
        )
        self._state_badge.show()

        if module_state.blocked_prev_state:
            self._blocked_prev_label.setText(
                f"(previously {module_state.blocked_prev_state})"
            )
            self._blocked_prev_label.show()
        else:
            self._blocked_prev_label.hide()

        self._attempt_label.setText(f"attempt #{module_state.attempt}")

        icon = MODULE_TYPE_ICONS.get(module_state.module_type, "\u25A0")
        self._module_type_label.setText(f"{icon}  {module_state.module_type}")

    # ──────────────────────────────────────── Subprocess helpers ──── #

    def _run_claude_cli(
        self,
        args: List[str],
        *,
        success_toast: Optional[str] = None,
        on_success: Optional[Callable[[QProcess], None]] = None,
    ) -> QProcess:
        """Run ``claude <args>`` via ``QProcess`` without blocking the UI."""
        proc = QProcess(self)
        proc.setProgram("claude")
        proc.setArguments(args)

        def _finished(exit_code: int, _status: QProcess.ExitStatus) -> None:
            stderr = bytes(proc.readAllStandardError()).decode("utf-8", "replace")
            stdout = bytes(proc.readAllStandardOutput()).decode("utf-8", "replace")
            if exit_code == 0:
                logger.info("claude %s -> ok", " ".join(args))
                if success_toast:
                    self._emit_toast(success_toast, "success")
                if on_success is not None:
                    on_success(proc)
            else:
                logger.warning(
                    "claude %s -> exit=%s stderr=%s",
                    " ".join(args),
                    exit_code,
                    stderr,
                )
                summary = stderr.strip() or stdout.strip() or "falha desconhecida"
                self._emit_toast(f"Falha: {summary[:200]}", "error")

        proc.finished.connect(_finished)
        proc.errorOccurred.connect(
            lambda err: self._emit_toast(
                f"Erro ao executar claude CLI: {err}", "error"
            )
        )
        proc.start()
        return proc

    def _emit_toast(self, message: str, level: str) -> None:
        try:
            signal_bus.toast_requested.emit(message, level)
        except Exception:  # pragma: no cover - signal_bus always available
            logger.exception("toast emit failed: %s", message)

    # ──────────────────────────────────────────────────── Slots ──── #

    def _on_tab_selected(self, index: int) -> None:
        self._artifact_tabs.setCurrentIndex(index)

    def _on_artifact_clicked(self, payload: str) -> None:
        # Try to open the path via the OS. Fall back to a toast when the path
        # does not exist or cannot be opened.
        try:
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
        except ImportError:  # pragma: no cover
            self._emit_toast(f"Abrir: {payload}", "info")
            return
        url = QUrl.fromLocalFile(payload)
        if QDesktopServices.openUrl(url):
            return
        self._emit_toast(f"Nao foi possivel abrir: {payload}", "warning")

    def _on_run(self, module_id: str) -> None:
        state = self._action_bar.current_state
        if state == "pending":
            self._emit_toast(
                f"Disparando /build-module-pipeline para {module_id}...",
                "info",
            )
            self._run_claude_cli(
                args=["/build-module-pipeline", module_id],
                success_toast=f"Pipeline criado para {module_id}",
            )
            return
        self._emit_toast(
            f"Retomando pipeline de {module_id} — veja a aba Comandos.",
            "info",
        )
        try:
            signal_bus.pipeline_resumed.emit()
        except Exception:  # pragma: no cover
            logger.exception("pipeline_resumed emit failed")

    def _on_pause(self, module_id: str) -> None:
        self._emit_toast(
            f"Pausando pipeline de {module_id} apos o step atual...",
            "info",
        )
        try:
            signal_bus.pipeline_paused.emit()
        except Exception:  # pragma: no cover
            logger.exception("pipeline_paused emit failed")

    def _on_unblock(self, module_id: str) -> None:
        reply = QMessageBox.question(
            self,
            "Unblock",
            (
                f"Restaurar blocked_prev_state de {module_id}?\n\n"
                f"Executa: /delivery:unblock {module_id}"
            ),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._run_claude_cli(
            args=["/delivery:unblock", module_id],
            success_toast=f"{module_id} desbloqueado",
        )

    def _on_reopen(self, module_id: str) -> None:
        dialog = ReopenDialog(module_id=module_id, parent=self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        phase = dialog.selected_phase()
        reason = dialog.selected_reason()
        self._run_claude_cli(
            args=[
                "/delivery:reopen",
                module_id,
                "--phase",
                phase,
                "--reason",
                reason,
            ],
            success_toast=f"{module_id} reaberto em {phase}",
        )

    def _on_open_terminal(self, module_id: str) -> None:
        workspace = self._resolve_workspace_path(module_id)
        if workspace is None:
            self._emit_toast(
                "workspace_root nao disponivel para este modulo.",
                "warning",
            )
            return
        if not self._spawn_terminal(workspace):
            self._emit_toast(
                f"Nao foi possivel abrir terminal em {workspace}",
                "error",
            )

    def _resolve_workspace_path(self, module_id: str) -> Optional[Path]:
        if self._current_delivery is None or self._wbs_root is None:
            return None
        workspace = Path(self._current_delivery.project.workspace_root)
        if not workspace.is_absolute():
            workspace = self._wbs_root.parent / workspace
        if not workspace.exists():
            logger.warning(
                "terminal: workspace_root %s does not exist for %s",
                workspace,
                module_id,
            )
            return None
        return workspace

    def _spawn_terminal(self, cwd: Path) -> bool:
        # Linux-first fallback chain. Darwin/Windows left as best effort.
        candidates = [
            "x-terminal-emulator",
            "gnome-terminal",
            "konsole",
            "xfce4-terminal",
            "xterm",
        ]
        for binary in candidates:
            if shutil.which(binary) is None:
                continue
            proc = QProcess(self)
            proc.setProgram(binary)
            if binary == "gnome-terminal":
                proc.setArguments(["--working-directory", str(cwd)])
            elif binary in {"konsole", "xfce4-terminal"}:
                proc.setArguments(["--workdir", str(cwd)])
            else:
                proc.setWorkingDirectory(str(cwd))
            if proc.startDetached():
                return True
        # Darwin fallback
        if shutil.which("open") is not None and os.uname().sysname == "Darwin":
            proc = QProcess(self)
            proc.setProgram("open")
            proc.setArguments(["-a", "Terminal", str(cwd)])
            if proc.startDetached():
                return True
        return False

    # ──────────────────────────────────────────────── Introspection ──── #

    @property
    def artifact_tabs(self) -> ArtifactTabs:
        return self._artifact_tabs

    @property
    def action_bar(self) -> ActionBar:
        return self._action_bar

    @property
    def current_module_id(self) -> Optional[str]:
        return self._current_module_id

    @property
    def tab_buttons(self) -> List[QPushButton]:
        return list(self._tab_buttons)


__all__ = ["ModuleDetailView", "ReopenDialog"]
