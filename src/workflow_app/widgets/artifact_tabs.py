"""Artifact tabs widget for the per-module detail view (T-038).

Canonical source: ``detailed.md §9.2`` (DCP-9.2 — SPECIFIC-FLOW resolution
cascade), ``§9.3`` (DCP-9.3 — click-to-load), ``§9.5`` (DCP-9.5 — reader
details). Implements the 5 tabs required by TASK-038:

    Metadados | Artefatos | History | Gates | Pipeline

The widget is a ``QStackedWidget`` (hint per TASK-038: "Usar QStackedWidget
para tabs") so the owning ``ModuleDetailView`` can drive page switching from
an external tab selector button row.

**Metadados** is deliberately read-only (see EXECUTION-READINESS-T-038.md
drift D4): TASK-038 mentions "editor quando permitido" without defining the
permission rule, so the editor is deferred to a future task. A banner makes
this explicit in the UI.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPlainTextEdit,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from workflow_app.models.delivery import (
    Delivery,
    ModuleArtifacts,
    ModuleState,
)
from workflow_app.services.delivery_reader import DeliveryReader
from workflow_app.widgets.history_timeline import HistoryTimeline

logger = logging.getLogger(__name__)

TAB_METADADOS = 0
TAB_ARTEFATOS = 1
TAB_HISTORY = 2
TAB_GATES = 3
TAB_PIPELINE = 4

TAB_LABELS: tuple[str, ...] = (
    "Metadados",
    "Artefatos",
    "History",
    "Gates",
    "Pipeline",
)

TAB_TESTIDS: tuple[str, ...] = (
    "tab-metadados",
    "tab-artefatos",
    "tab-history",
    "tab-gates",
    "tab-pipeline",
)

_TEXT_PRIMARY = "#F4F4F5"
_TEXT_MUTED = "#A1A1AA"
_PAGE_BG = "#0F0F11"
_BANNER_BG = "#1F2937"
_BANNER_TEXT = "#E5E7EB"


class ArtifactTabs(QStackedWidget):
    """Five stacked pages rendering a module's artifacts.

    Usage::

        tabs = ArtifactTabs()
        tabs.load(delivery, module_state, module_id, reader, wbs_root)
        tabs.setCurrentIndex(ArtifactTabs.TAB_HISTORY)

    Signals:
        artifact_clicked(str): emitted when the user double-clicks an entry
            in the Artefatos list. Payload is the resolved absolute path as
            a string. The owner is responsible for opening it.
    """

    artifact_clicked = Signal(str)

    # Re-exported so callers can use ArtifactTabs.TAB_GATES etc.
    TAB_METADADOS = TAB_METADADOS
    TAB_ARTEFATOS = TAB_ARTEFATOS
    TAB_HISTORY = TAB_HISTORY
    TAB_GATES = TAB_GATES
    TAB_PIPELINE = TAB_PIPELINE

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("ArtifactTabs")
        self.setProperty("testid", "artifact-tabs")
        self.setStyleSheet(
            f"QStackedWidget#ArtifactTabs {{ background-color: {_PAGE_BG}; }}"
        )

        self._build_metadados_page()
        self._build_artefatos_page()
        self._build_history_page()
        self._build_gates_page()
        self._build_pipeline_page()

    # ─────────────────────────────────────────────────────────── UI ──── #

    def _build_metadados_page(self) -> None:
        page = QWidget()
        page.setProperty("testid", TAB_TESTIDS[TAB_METADADOS])
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._metadados_banner = QLabel(
            "Editor read-only — edicao manual de MODULE-META.json sera "
            "habilitada em task futura."
        )
        self._metadados_banner.setStyleSheet(
            f"background-color: {_BANNER_BG}; color: {_BANNER_TEXT};"
            f" font-size: 11px; padding: 6px 10px;"
            f" border-bottom: 1px solid #374151;"
        )
        self._metadados_banner.setProperty("testid", "metadata-banner")
        layout.addWidget(self._metadados_banner)

        self._metadados_editor = QPlainTextEdit()
        self._metadados_editor.setReadOnly(True)
        self._metadados_editor.setProperty("testid", "metadata-editor")
        mono = QFont("JetBrains Mono")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(10)
        self._metadados_editor.setFont(mono)
        self._metadados_editor.setStyleSheet(
            f"QPlainTextEdit {{"
            f"  background-color: {_PAGE_BG}; color: {_TEXT_PRIMARY};"
            f"  border: none; padding: 8px;"
            f"}}"
        )
        layout.addWidget(self._metadados_editor, stretch=1)

        self.insertWidget(TAB_METADADOS, page)

    def _build_artefatos_page(self) -> None:
        page = QWidget()
        page.setProperty("testid", TAB_TESTIDS[TAB_ARTEFATOS])
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        hint = QLabel(
            "Clique duplo em um item para abrir o arquivo no visualizador do sistema."
        )
        hint.setStyleSheet(
            f"color: {_TEXT_MUTED}; font-size: 11px; background: transparent;"
        )
        layout.addWidget(hint)

        self._artifacts_list = QListWidget()
        self._artifacts_list.setProperty("testid", "artifacts-list")
        self._artifacts_list.setStyleSheet(
            f"QListWidget {{"
            f"  background-color: {_PAGE_BG}; color: {_TEXT_PRIMARY};"
            f"  border: 1px solid #27272A; font-size: 11px;"
            f"}}"
            f"QListWidget::item {{ padding: 6px 8px; }}"
            f"QListWidget::item:hover {{ background-color: #27272A; }}"
        )
        self._artifacts_list.itemDoubleClicked.connect(
            self._on_artifact_double_clicked
        )
        layout.addWidget(self._artifacts_list, stretch=1)

        self.insertWidget(TAB_ARTEFATOS, page)

    def _build_history_page(self) -> None:
        page = QWidget()
        page.setProperty("testid", TAB_TESTIDS[TAB_HISTORY])
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._history_timeline = HistoryTimeline(parent=page)
        layout.addWidget(self._history_timeline, stretch=1)

        self.insertWidget(TAB_HISTORY, page)

    def _build_gates_page(self) -> None:
        page = QWidget()
        page.setProperty("testid", TAB_TESTIDS[TAB_GATES])
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._gates_table = QTableWidget()
        self._gates_table.setProperty("testid", "gates-table")
        self._gates_table.setColumnCount(3)
        self._gates_table.setHorizontalHeaderLabels(["Gate", "Status", "Detalhe"])
        self._gates_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch
        )
        self._gates_table.verticalHeader().setVisible(False)
        self._gates_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._gates_table.setStyleSheet(
            f"QTableWidget {{"
            f"  background-color: {_PAGE_BG}; color: {_TEXT_PRIMARY};"
            f"  border: 1px solid #27272A; font-size: 11px;"
            f"}}"
        )
        layout.addWidget(self._gates_table, stretch=1)

        self._gates_placeholder = QLabel(
            "Nenhum SPECIFIC-FLOW.json encontrado para este modulo."
        )
        self._gates_placeholder.setProperty("testid", "gates-placeholder")
        self._gates_placeholder.setStyleSheet(
            f"color: {_TEXT_MUTED}; font-size: 12px; padding: 20px;"
        )
        self._gates_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._gates_placeholder.hide()
        layout.addWidget(self._gates_placeholder)

        self.insertWidget(TAB_GATES, page)

    def _build_pipeline_page(self) -> None:
        page = QWidget()
        page.setProperty("testid", TAB_TESTIDS[TAB_PIPELINE])
        layout = QVBoxLayout(page)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        self._pipeline_table = QTableWidget()
        self._pipeline_table.setProperty("testid", "pipeline-table")
        self._pipeline_table.setColumnCount(5)
        self._pipeline_table.setHorizontalHeaderLabels(
            ["#", "Phase", "Command", "Effort", "Estado"]
        )
        hh = self._pipeline_table.horizontalHeader()
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hh.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self._pipeline_table.verticalHeader().setVisible(False)
        self._pipeline_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._pipeline_table.setStyleSheet(
            f"QTableWidget {{"
            f"  background-color: {_PAGE_BG}; color: {_TEXT_PRIMARY};"
            f"  border: 1px solid #27272A; font-size: 11px;"
            f"}}"
        )
        layout.addWidget(self._pipeline_table, stretch=1)

        self._pipeline_placeholder = QLabel(
            "Nenhum SPECIFIC-FLOW.json encontrado para este modulo."
        )
        self._pipeline_placeholder.setProperty("testid", "pipeline-placeholder")
        self._pipeline_placeholder.setStyleSheet(
            f"color: {_TEXT_MUTED}; font-size: 12px; padding: 20px;"
        )
        self._pipeline_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pipeline_placeholder.hide()
        layout.addWidget(self._pipeline_placeholder)

        self.insertWidget(TAB_PIPELINE, page)

    # ────────────────────────────────────────────────────────── API ──── #

    def load(
        self,
        delivery: Delivery,
        module_state: ModuleState,
        module_id: str,
        reader: DeliveryReader,
        wbs_root: Path,
        project_root: Optional[Path] = None,
    ) -> None:
        """Populate all 5 pages for ``module_id``.

        ``project_root`` defaults to the parent of ``wbs_root`` — enough for
        the common layout where ``delivery.project.wbs_root`` is relative.
        """
        wbs_root = Path(wbs_root)
        project_root = Path(project_root) if project_root else wbs_root.parent

        self._load_metadados(module_state.artifacts, wbs_root)
        self._load_artefatos(module_state.artifacts, wbs_root)
        self._load_history(module_state)
        flow_path = reader.resolve_specific_flow(
            delivery,
            module_id=module_id,
            project_root=project_root,
        )
        self._load_gates(flow_path)
        self._load_pipeline(flow_path)

    def clear(self) -> None:
        """Reset all 5 pages to an empty state."""
        self._metadados_editor.clear()
        self._artifacts_list.clear()
        self._history_timeline.clear()
        self._gates_table.setRowCount(0)
        self._gates_placeholder.hide()
        self._gates_table.show()
        self._pipeline_table.setRowCount(0)
        self._pipeline_placeholder.hide()
        self._pipeline_table.show()

    # ────────────────────────────────────────────────── Loaders ──── #

    def _load_metadados(
        self,
        artifacts: ModuleArtifacts,
        wbs_root: Path,
    ) -> None:
        path_str = artifacts.module_meta_path
        if not path_str:
            self._metadados_editor.setPlainText(
                "# Nenhum MODULE-META.json declarado em artifacts.module_meta_path"
            )
            return
        path = Path(path_str)
        if not path.is_absolute():
            path = wbs_root / path
        if not path.exists():
            self._metadados_editor.setPlainText(
                f"# MODULE-META.json nao encontrado: {path}"
            )
            return
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self._metadados_editor.setPlainText(
                f"# Erro lendo MODULE-META.json: {exc}"
            )
            return
        pretty = json.dumps(data, indent=2, ensure_ascii=False)
        self._metadados_editor.setPlainText(pretty)

    def _load_artefatos(
        self,
        artifacts: ModuleArtifacts,
        wbs_root: Path,
    ) -> None:
        labels_and_values: list[tuple[str, Optional[str]]] = [
            ("MODULE-META", artifacts.module_meta_path),
            ("OVERVIEW", artifacts.overview_path),
            ("SPECIFIC-FLOW (last)", artifacts.last_specific_flow),
            ("Review Report", artifacts.last_review_report),
            ("Commit SHA", artifacts.last_commit_sha),
            ("Deploy URL", artifacts.last_deploy_url),
            ("Git tag", artifacts.git_tag),
        ]

        for label, value in labels_and_values:
            if not value:
                continue
            display = f"{label}  —  {value}"
            item = QListWidgetItem(display)
            resolved = self._resolve_artifact_path(value, wbs_root)
            item.setData(Qt.ItemDataRole.UserRole, str(resolved) if resolved else value)
            # commit sha / deploy url / git tag are scalar values, not paths.
            item.setToolTip(str(resolved) if resolved else value)
            self._artifacts_list.addItem(item)

    @staticmethod
    def _resolve_artifact_path(
        value: str,
        wbs_root: Path,
    ) -> Optional[Path]:
        if not value:
            return None
        if value.startswith(("http://", "https://")):
            return None
        if value.startswith(("sha:", "tag:")):
            return None
        candidate = Path(value)
        if not candidate.is_absolute():
            candidate = wbs_root / candidate
        return candidate

    def _load_history(self, module_state: ModuleState) -> None:
        self._history_timeline.set_history(list(module_state.history))

    def _load_gates(self, flow_path: Optional[Path]) -> None:
        self._gates_table.setRowCount(0)
        if flow_path is None or not flow_path.exists():
            self._gates_table.hide()
            self._gates_placeholder.show()
            return
        try:
            data = json.loads(flow_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Gates: cannot read %s: %s", flow_path, exc)
            self._gates_table.hide()
            self._gates_placeholder.setText(
                f"Erro lendo SPECIFIC-FLOW.json: {exc}"
            )
            self._gates_placeholder.show()
            return

        gates = self._extract_gates(data)
        if not gates:
            self._gates_table.hide()
            self._gates_placeholder.setText(
                "SPECIFIC-FLOW.json nao declara gates."
            )
            self._gates_placeholder.show()
            return

        self._gates_placeholder.hide()
        self._gates_table.show()
        self._gates_table.setRowCount(len(gates))
        for row, gate in enumerate(gates):
            self._gates_table.setItem(
                row, 0, QTableWidgetItem(str(gate.get("name", gate.get("id", f"gate-{row}"))))
            )
            self._gates_table.setItem(
                row, 1, QTableWidgetItem(str(gate.get("status", "unknown")))
            )
            self._gates_table.setItem(
                row, 2, QTableWidgetItem(str(gate.get("detail", gate.get("description", ""))))
            )

    def _load_pipeline(self, flow_path: Optional[Path]) -> None:
        self._pipeline_table.setRowCount(0)
        if flow_path is None or not flow_path.exists():
            self._pipeline_table.hide()
            self._pipeline_placeholder.show()
            return
        try:
            data = json.loads(flow_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Pipeline: cannot read %s: %s", flow_path, exc)
            self._pipeline_table.hide()
            self._pipeline_placeholder.setText(
                f"Erro lendo SPECIFIC-FLOW.json: {exc}"
            )
            self._pipeline_placeholder.show()
            return

        steps = self._extract_steps(data)
        if not steps:
            self._pipeline_table.hide()
            self._pipeline_placeholder.setText(
                "SPECIFIC-FLOW.json nao declara steps."
            )
            self._pipeline_placeholder.show()
            return

        self._pipeline_placeholder.hide()
        self._pipeline_table.show()
        self._pipeline_table.setRowCount(len(steps))
        for row, step in enumerate(steps):
            self._pipeline_table.setItem(row, 0, QTableWidgetItem(str(row + 1)))
            self._pipeline_table.setItem(
                row, 1, QTableWidgetItem(str(step.get("phase", "")))
            )
            self._pipeline_table.setItem(
                row, 2, QTableWidgetItem(str(step.get("command", step.get("name", ""))))
            )
            self._pipeline_table.setItem(
                row, 3, QTableWidgetItem(str(step.get("effort", "")))
            )
            self._pipeline_table.setItem(
                row, 4, QTableWidgetItem(str(step.get("state", step.get("status", ""))))
            )

    @staticmethod
    def _extract_gates(flow: dict) -> List[dict]:
        if not isinstance(flow, dict):
            return []
        gates = flow.get("gates")
        if isinstance(gates, list):
            return [g for g in gates if isinstance(g, dict)]
        return []

    @staticmethod
    def _extract_steps(flow: dict) -> List[dict]:
        if not isinstance(flow, dict):
            return []
        steps = flow.get("steps") or flow.get("pipeline") or flow.get("commands")
        if isinstance(steps, list):
            return [s for s in steps if isinstance(s, dict)]
        return []

    # ─────────────────────────────────────────────────────── Slots ──── #

    def _on_artifact_double_clicked(self, item: QListWidgetItem) -> None:
        payload = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(payload, str) and payload:
            self.artifact_clicked.emit(payload)


__all__ = ["ArtifactTabs", "TAB_LABELS", "TAB_TESTIDS"]
