"""Action bar widget for the per-module detail view (T-038).

Canonical source: ``detailed.md §9.3`` (DCP-9.3) + TASK-038 §"action bar
contextual por estado". Provides five context-sensitive buttons:

    [Run Pipeline] [Pause] [Unblock] [Reopen] [Abrir em Terminal]

**No Promote / No Rollback** — per DCP state machine (T-006), transicoes
forcadas devem usar ``/delivery:unblock``, ``/delivery:reopen`` ou edicao
auditada de ``delivery.json``. ``Promote`` e ``Rollback`` NAO existem no DCP
e a ausencia destes botoes e verificada por teste explicito em
``tests/test_module_detail_view.py``.

The widget is stateless regarding the module source; the owning
``ModuleDetailView`` calls ``update_for_state(module_id, state)`` whenever a
new module is opened. The bar re-emits click intents through dedicated
``Signal(str)`` channels so the view can wire them to ``QProcess`` helpers.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QPushButton, QWidget

from workflow_app.models.delivery import ACTIVE_STATES, ModuleStateLiteral

_BAR_BG = "#18181B"
_BAR_BORDER = "#27272A"
_BTN_BG = "#1F1F22"
_BTN_BG_HOVER = "#2A2A2E"
_BTN_BORDER = "#3F3F46"
_BTN_TEXT = "#F4F4F5"
_BTN_DISABLED_BG = "#131316"
_BTN_DISABLED_TEXT = "#52525B"
_PRIMARY_ACCENT = "#2563EB"


class ActionBar(QFrame):
    """Five context-sensitive action buttons.

    Signals:
        run_requested(str): emitted on "Run Pipeline" click, carries module_id.
        pause_requested(str): emitted on "Pause" click.
        unblock_requested(str): emitted on "Unblock" click.
        reopen_requested(str): emitted on "Reopen" click (view opens a dialog).
        open_terminal_requested(str): emitted on "Abrir em Terminal" click.

    Public API:
        update_for_state(module_id, state): enable/disable buttons per DCP
            state machine. Stores ``module_id`` so later clicks can re-emit
            it without the caller having to pass it in again.
        clear(): reset to an empty, fully disabled state.
    """

    run_requested = Signal(str)
    pause_requested = Signal(str)
    unblock_requested = Signal(str)
    reopen_requested = Signal(str)
    open_terminal_requested = Signal(str)

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._module_id: Optional[str] = None
        self._module_state: Optional[ModuleStateLiteral] = None

        self.setObjectName("ActionBar")
        self.setProperty("testid", "action-bar")
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setStyleSheet(
            f"QFrame#ActionBar {{"
            f"  background-color: {_BAR_BG};"
            f"  border-top: 1px solid {_BAR_BORDER};"
            f"}}"
        )
        self._setup_ui()
        self._disable_all()

    # ─────────────────────────────────────────────────────────── UI ──── #

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        self._btn_run = self._make_button(
            label="Run Pipeline",
            testid="action-btn-run",
            primary=True,
        )
        self._btn_run.clicked.connect(self._on_run_clicked)
        layout.addWidget(self._btn_run)

        self._btn_pause = self._make_button(
            label="Pause",
            testid="action-btn-pause",
            primary=False,
        )
        self._btn_pause.clicked.connect(self._on_pause_clicked)
        layout.addWidget(self._btn_pause)

        self._btn_unblock = self._make_button(
            label="Unblock",
            testid="action-btn-unblock",
            primary=False,
        )
        self._btn_unblock.clicked.connect(self._on_unblock_clicked)
        layout.addWidget(self._btn_unblock)

        self._btn_reopen = self._make_button(
            label="Reopen",
            testid="action-btn-reopen",
            primary=False,
        )
        self._btn_reopen.clicked.connect(self._on_reopen_clicked)
        layout.addWidget(self._btn_reopen)

        layout.addStretch(1)

        self._btn_terminal = self._make_button(
            label="Abrir em Terminal",
            testid="action-btn-terminal",
            primary=False,
        )
        self._btn_terminal.clicked.connect(self._on_terminal_clicked)
        layout.addWidget(self._btn_terminal)

    def _make_button(
        self,
        *,
        label: str,
        testid: str,
        primary: bool,
    ) -> QPushButton:
        btn = QPushButton(label)
        btn.setProperty("testid", testid)
        btn.setFixedHeight(32)
        btn.setMinimumWidth(110)
        btn.setCursor(btn.cursor())  # default pointer -- style sheet sets the rest
        accent = _PRIMARY_ACCENT if primary else _BTN_BORDER
        btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: {_BTN_BG};"
            f"  color: {_BTN_TEXT};"
            f"  border: 1px solid {accent};"
            f"  border-radius: 4px;"
            f"  padding: 4px 12px;"
            f"  font-size: 11px;"
            f"  font-weight: 600;"
            f"}}"
            f"QPushButton:hover {{ background-color: {_BTN_BG_HOVER}; }}"
            f"QPushButton:disabled {{"
            f"  background-color: {_BTN_DISABLED_BG};"
            f"  color: {_BTN_DISABLED_TEXT};"
            f"  border-color: {_BTN_DISABLED_BG};"
            f"}}"
        )
        return btn

    # ────────────────────────────────────────────────────────── API ──── #

    def update_for_state(
        self,
        module_id: str,
        state: ModuleStateLiteral,
    ) -> None:
        """Rebind the bar to ``module_id`` and enable buttons per ``state``.

        DCP state-to-affordance rules (literal, per TASK-038):

          pending                     -> Run only
          creation|execution|
          revision|qa|deploy (active) -> Run (resume) + Pause + Terminal
          done                        -> Reopen + Terminal
          blocked                     -> Unblock + Terminal
          rework                      -> Run + Terminal
        """
        self._module_id = module_id
        self._module_state = state
        self._disable_all()

        if state == "pending":
            self._btn_run.setEnabled(True)
            self._btn_run.setToolTip("Executar /build-module-pipeline")
            return

        if state in ACTIVE_STATES:
            self._btn_run.setEnabled(True)
            self._btn_run.setToolTip(
                "Retomar consumo da fila (nao recria pipeline)"
            )
            self._btn_pause.setEnabled(True)
            self._btn_pause.setToolTip(
                "Pausa apos o step atual terminar"
            )
            self._btn_terminal.setEnabled(True)
            self._btn_terminal.setToolTip(
                "Abrir terminal em {workspace_root}"
            )
            return

        if state == "done":
            self._btn_reopen.setEnabled(True)
            self._btn_reopen.setToolTip(
                "Reabrir modulo em uma fase (/delivery:reopen)"
            )
            self._btn_terminal.setEnabled(True)
            self._btn_terminal.setToolTip(
                "Abrir terminal em {workspace_root}"
            )
            return

        if state == "blocked":
            self._btn_unblock.setEnabled(True)
            self._btn_unblock.setToolTip(
                "Restaurar blocked_prev_state (/delivery:unblock)"
            )
            self._btn_terminal.setEnabled(True)
            self._btn_terminal.setToolTip(
                "Abrir terminal em {workspace_root}"
            )
            return

        if state == "rework":
            self._btn_run.setEnabled(True)
            self._btn_run.setToolTip(
                "Retomar consumo da fila (rework target)"
            )
            self._btn_terminal.setEnabled(True)
            self._btn_terminal.setToolTip(
                "Abrir terminal em {workspace_root}"
            )
            return

    def clear(self) -> None:
        """Reset the bar to an empty, fully disabled state."""
        self._module_id = None
        self._module_state = None
        self._disable_all()

    @property
    def current_module_id(self) -> Optional[str]:
        return self._module_id

    @property
    def current_state(self) -> Optional[ModuleStateLiteral]:
        return self._module_state

    # ───────────────────────────────────────────────────── Internals ──── #

    def _disable_all(self) -> None:
        for btn, reason in (
            (self._btn_run, "Sem modulo ativo"),
            (self._btn_pause, "Sem modulo ativo"),
            (self._btn_unblock, "Apenas em modulos blocked"),
            (self._btn_reopen, "Apenas em modulos done"),
            (self._btn_terminal, "Sem modulo ativo"),
        ):
            btn.setEnabled(False)
            btn.setToolTip(reason)

    # ─────────────────────────────────────────────────────── Slots ──── #

    def _on_run_clicked(self) -> None:
        if self._module_id is not None:
            self.run_requested.emit(self._module_id)

    def _on_pause_clicked(self) -> None:
        if self._module_id is not None:
            self.pause_requested.emit(self._module_id)

    def _on_unblock_clicked(self) -> None:
        if self._module_id is not None:
            self.unblock_requested.emit(self._module_id)

    def _on_reopen_clicked(self) -> None:
        if self._module_id is not None:
            self.reopen_requested.emit(self._module_id)

    def _on_terminal_clicked(self) -> None:
        if self._module_id is not None:
            self.open_terminal_requested.emit(self._module_id)


__all__ = ["ActionBar"]
