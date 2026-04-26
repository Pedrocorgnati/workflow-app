"""Kanban view for the workflow-app (T-036, canonical source: `detailed.md §9.3`).

Renders the delivery pipeline as a 9-column Kanban where each column maps to
one of the DCP module states (`pending`, `creation`, `execution`, `revision`,
`qa`, `deploy`, `done`, `blocked`, `rework`). Colors follow DCP-9.3.

The view is read-only — it consumes the ``DeliveryReader`` API from T-035 and
does not hold the cooperative delivery lock (T-037 will add lock-aware
behavior by calling ``set_lock_holder`` from the main window). A
``QFileSystemWatcher`` + 500ms debounce timer triggers ``refresh`` whenever
``delivery.json`` changes on disk (mitigation for the "Auto-refresh em loop"
risk documented in TASK-036).

Click handling emits ``module_clicked`` with the module id. T-038 will
subscribe to that signal to open a detail view; T-036 ships a toast stub on
the main window side.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional

from PySide6.QtCore import QFileSystemWatcher, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from workflow_app.models.delivery import (
    Delivery,
    ModuleState,
    ModuleStateLiteral,
)
from workflow_app.services.delivery_reader import (
    DeliveryFound,
    DeliveryFutureVersion,
    DeliveryInvalid,
    DeliveryMissing,
    DeliveryReader,
)
from workflow_app.widgets.module_card import ModuleCard
from workflow_app.widgets.state_column import StateColumn

logger = logging.getLogger(__name__)


# ── Canonical state metadata (DCP-9.3) ────────────────────────────────────── #

STATE_ORDER: tuple[ModuleStateLiteral, ...] = (
    "pending",
    "creation",
    "execution",
    "revision",
    "qa",
    "deploy",
    "done",
    "blocked",
    "rework",
)

STATE_COLORS: Dict[ModuleStateLiteral, str] = {
    "pending":   "#6B7280",  # cinza
    "creation":  "#2563EB",  # azul
    "execution": "#FBBF24",  # amarelo
    "revision":  "#F97316",  # laranja
    "qa":        "#7C3AED",  # roxo
    "deploy":    "#84CC16",  # verde claro
    "done":      "#16A34A",  # verde escuro
    "blocked":   "#DC2626",  # vermelho
    "rework":    "#EC4899",  # rosa
}

STATE_LABELS: Dict[ModuleStateLiteral, str] = {
    "pending":   "Pendente",
    "creation":  "Criacao",
    "execution": "Execucao",
    "revision":  "Revisao",
    "qa":        "QA",
    "deploy":    "Deploy",
    "done":      "Pronto",
    "blocked":   "Bloqueado",
    "rework":    "Rework",
}


# ── Styles ────────────────────────────────────────────────────────────────── #

_VIEW_BG = "#18181B"
_HEADER_BG = "#27272A"
_HEADER_TEXT = "#F4F4F5"
_HEADER_MUTED = "#A1A1AA"
_LOCK_BADGE_BG = "#DC2626"
_LOCK_BADGE_TEXT = "#FEE2E2"

_REFRESH_DEBOUNCE_MS = 500


# ── KanbanView ────────────────────────────────────────────────────────────── #


class KanbanView(QWidget):
    """Nine-column Kanban of DCP module states.

    Signals:
        module_clicked(str): emitted with the module id when a card is clicked.

    Public API:
        load(wbs_root): read ``delivery.json`` and populate the columns.
        refresh(): re-read the last-loaded delivery and repopulate.
        clear(): empty all columns and header.
        set_lock_holder(holder): toggle a "LOCKED by {holder}" badge (T-037).
    """

    module_clicked = Signal(str)

    def __init__(
        self,
        reader: DeliveryReader,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self._reader = reader
        self._wbs_root: Optional[Path] = None
        self._delivery_path: Optional[Path] = None
        self._columns: Dict[ModuleStateLiteral, StateColumn] = {}
        self._card_widgets: Dict[str, ModuleCard] = {}

        self.setObjectName("KanbanView")
        self.setProperty("testid", "view-kanban")
        self.setStyleSheet(
            f"QWidget#KanbanView {{ background-color: {_VIEW_BG}; }}"
        )

        # Watcher + debounce timer (per TASK-036 Riscos: debounce 500ms).
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._on_file_changed)
        self._refresh_timer = QTimer(self)
        self._refresh_timer.setSingleShot(True)
        self._refresh_timer.setInterval(_REFRESH_DEBOUNCE_MS)
        self._refresh_timer.timeout.connect(self.refresh)

        self._setup_ui()

    # ─────────────────────────────────────────────────────────── UI ──── #

    def _setup_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header bar ───────────────────────────────────────────────── #
        self._header_bar = QFrame()
        self._header_bar.setObjectName("KanbanHeader")
        self._header_bar.setFixedHeight(40)
        self._header_bar.setStyleSheet(
            f"QFrame#KanbanHeader {{"
            f"  background-color: {_HEADER_BG};"
            f"  border-bottom: 1px solid #3F3F46;"
            f"}}"
        )
        header_layout = QHBoxLayout(self._header_bar)
        header_layout.setContentsMargins(12, 0, 12, 0)
        header_layout.setSpacing(10)

        self._title_label = QLabel("Delivery Kanban")
        self._title_label.setStyleSheet(
            f"color: {_HEADER_TEXT}; font-size: 13px; font-weight: 700;"
            f" background: transparent; border: none;"
        )
        header_layout.addWidget(self._title_label)

        self._status_label = QLabel("Nenhum projeto carregado")
        self._status_label.setStyleSheet(
            f"color: {_HEADER_MUTED}; font-size: 11px;"
            f" background: transparent; border: none;"
        )
        header_layout.addWidget(self._status_label)

        header_layout.addStretch(1)

        # Lock badge (hidden by default; T-037 drives it via set_lock_holder).
        self._lock_badge = QLabel("")
        self._lock_badge.setStyleSheet(
            f"color: {_LOCK_BADGE_TEXT}; background-color: {_LOCK_BADGE_BG};"
            f" font-size: 11px; font-weight: 700; padding: 3px 8px;"
            f" border-radius: 4px;"
        )
        self._lock_badge.setProperty("testid", "kanban-lock-badge")
        self._lock_badge.hide()
        header_layout.addWidget(self._lock_badge)

        root.addWidget(self._header_bar)

        # ── Columns area (horizontal scroll so 9 cols always fit) ───── #
        self._columns_scroll = QScrollArea()
        self._columns_scroll.setObjectName("KanbanColumnsScroll")
        self._columns_scroll.setWidgetResizable(True)
        self._columns_scroll.setStyleSheet(
            f"QScrollArea#KanbanColumnsScroll {{"
            f"  background-color: {_VIEW_BG}; border: none;"
            f"}}"
        )

        columns_container = QWidget()
        columns_container.setStyleSheet(f"background-color: {_VIEW_BG};")
        columns_layout = QHBoxLayout(columns_container)
        columns_layout.setContentsMargins(12, 12, 12, 12)
        columns_layout.setSpacing(10)

        for state in STATE_ORDER:
            column = StateColumn(
                state=state,
                display_label=STATE_LABELS[state],
                color=STATE_COLORS[state],
                parent=columns_container,
            )
            self._columns[state] = column
            columns_layout.addWidget(column)

        columns_layout.addStretch(1)
        self._columns_scroll.setWidget(columns_container)

        root.addWidget(self._columns_scroll, stretch=1)

    # ────────────────────────────────────────────────────────── API ──── #

    def load(self, wbs_root: Path | str) -> None:
        """Load ``delivery.json`` from ``{wbs_root}/delivery.json``.

        Populates the columns and registers the watcher. Safe to call multiple
        times (clears previous state first).
        """
        wbs_root = Path(wbs_root)
        self._wbs_root = wbs_root

        # Invalidate reader cache so subsequent resolve_specific_flow calls
        # do not return stale results (the view itself does not call resolve,
        # but downstream T-038 will and the reader is shared).
        self._reader.invalidate_cache()

        self._clear_columns()
        result = self._reader.load(wbs_root)

        if isinstance(result, DeliveryMissing):
            self._status_label.setText(
                f"delivery.json nao encontrado em {wbs_root}"
            )
            self._delivery_path = result.path
            logger.info("KanbanView.load: delivery missing at %s", result.path)
            return

        if isinstance(result, DeliveryFutureVersion):
            self._status_label.setText(result.message)
            self._delivery_path = result.path
            logger.warning(
                "KanbanView.load: future version at %s: %s",
                result.path,
                result.version,
            )
            return

        if isinstance(result, DeliveryInvalid):
            self._status_label.setText(f"delivery.json invalido: {result.error}")
            self._delivery_path = result.path
            logger.error(
                "KanbanView.load: invalid delivery at %s: %s",
                result.path,
                result.error,
            )
            return

        # DeliveryFound — populate columns.
        assert isinstance(result, DeliveryFound)
        self._delivery_path = result.path
        self._populate(result.delivery)
        self._update_watcher(result.path)

        for warning in result.warnings:
            logger.warning(
                "delivery warning %s on %s: %s",
                warning.code,
                warning.module,
                warning.message,
            )

    def refresh(self) -> None:
        """Re-read the current delivery.json (if any) and repopulate."""
        if self._wbs_root is None:
            return
        self.load(self._wbs_root)

    def clear(self) -> None:
        """Reset the view to an empty state (used on project unload)."""
        self._clear_columns()
        self._status_label.setText("Nenhum projeto carregado")
        self._wbs_root = None
        if self._delivery_path is not None:
            watched = list(self._watcher.files())
            if str(self._delivery_path) in watched:
                self._watcher.removePath(str(self._delivery_path))
            self._delivery_path = None
        # T-037: drop any stale lock badge so it does not persist across
        # project unload → next load.
        self.set_lock_holder(None)

    def set_lock_holder(self, holder: Optional[str]) -> None:
        """Toggle the 'LOCKED by {holder}' badge in the header.

        T-037 will drive this from ``main_window`` when it reads
        ``delivery.locks.holder``. T-036 only exposes the setter so callers
        have a stable hook.
        """
        if holder:
            self._lock_badge.setText(f"LOCKED by {holder}")
            self._lock_badge.show()
        else:
            self._lock_badge.clear()
            self._lock_badge.hide()

    # ──────────────────────────────────────────────── Introspection ──── #

    @property
    def columns(self) -> Dict[ModuleStateLiteral, StateColumn]:
        return self._columns

    def column_card_ids(self, state: ModuleStateLiteral) -> List[str]:
        """Return the ordered list of module ids currently in ``state``."""
        column = self._columns[state]
        return [card.module_id for card in column._cards]  # noqa: SLF001

    # ───────────────────────────────────────────────────── Internals ──── #

    def _populate(self, delivery: Delivery) -> None:
        project_name = delivery.project.name or "project"
        wbs = delivery.project.wbs_root
        self._title_label.setText(f"Delivery Kanban — {project_name}")
        self._status_label.setText(
            f"{len(delivery.modules)} modulos — wbs={wbs}"
        )

        for module_id, module_state in delivery.modules.items():
            self._add_module_card(module_id, module_state)

        # T-037: auto-drive the lock badge from `delivery.locks.holder`.
        # The QFileSystemWatcher already refreshes us on external writes,
        # so this single read keeps the badge in sync with CLI acquires
        # without a separate observer. ``locks`` is populated by pydantic
        # as ``Locks(holder=None, ...)`` by default, so ``delivery.locks``
        # is always truthy — the ``or None`` guards against empty strings.
        holder = delivery.locks.holder if delivery.locks else None
        self.set_lock_holder(holder or None)

    def _add_module_card(
        self,
        module_id: str,
        module_state: ModuleState,
    ) -> None:
        state = module_state.state
        column = self._columns.get(state)
        if column is None:
            logger.warning(
                "KanbanView: unknown state %r on module %s — skipping",
                state,
                module_id,
            )
            return

        card = ModuleCard(
            module_id=module_id,
            module_state=module_state,
            border_color=STATE_COLORS[state],
        )
        card.clicked.connect(self.module_clicked)
        column.add_card(card)
        self._card_widgets[module_id] = card

    def _clear_columns(self) -> None:
        for column in self._columns.values():
            column.clear()
        self._card_widgets.clear()

    def _update_watcher(self, path: Path) -> None:
        """Register ``path`` with the watcher (idempotent)."""
        path_str = str(path)
        watched = list(self._watcher.files())
        if path_str in watched:
            return
        # Some platforms drop the path after an atomic rename; re-adding is
        # cheap and safe.
        self._watcher.addPath(path_str)

    def _on_file_changed(self, _path: str) -> None:
        """Debounced refresh trigger driven by ``QFileSystemWatcher``."""
        # Start or restart the debounce timer.
        self._refresh_timer.start()


__all__ = [
    "STATE_COLORS",
    "STATE_LABELS",
    "STATE_ORDER",
    "KanbanView",
]
