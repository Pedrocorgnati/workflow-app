"""
ConfigBar — 36px project selector bar shown below MetricsBar.

States:
  - No project: shows hex icon + "Sem projeto" + [Selecionar Projeto...] button
  - Project loaded: shows hex icon + project name (amber, bold) + [✕] close button

On load: emits signal_bus.project_loaded(name)
On clear: emits signal_bus.project_cleared()
"""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

from workflow_app.domain import PermissionMode, ProjectConfig
from workflow_app.signal_bus import signal_bus


class ConfigBar(QWidget):
    """36px project configuration bar."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ConfigBar")
        self.setFixedHeight(36)
        self.setStyleSheet(
            "background-color: #27272A; border-bottom: 1px solid #3F3F46;"
        )

        self._current_config: ProjectConfig | None = None

        self._setup_ui()
        self._connect_signals()

    # ────────────────────────────────────────────────────────────────── #

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(8)

        # Hex icon
        self._hex_icon = QLabel("⬡")
        self._hex_icon.setStyleSheet("color: #71717A; font-size: 14px;")
        layout.addWidget(self._hex_icon)

        # Project name / placeholder
        self._name_label = QLabel("Sem projeto")
        self._name_label.setStyleSheet("color: #71717A; font-size: 13px;")
        layout.addWidget(self._name_label)

        # Project path (tooltip placeholder)
        self._path_label = QLabel()
        self._path_label.setStyleSheet("color: #71717A; font-size: 11px;")
        self._path_label.setVisible(False)
        layout.addWidget(self._path_label)

        layout.addStretch(1)

        # Select button (shown when no project)
        self._select_btn = QPushButton("Selecionar Projeto...")
        self._select_btn.setStyleSheet(
            "QPushButton { background-color: transparent; color: #FBBF24;"
            "  border: 1px solid #FBBF24; border-radius: 4px;"
            "  padding: 3px 10px; font-size: 12px; font-weight: 600; }"
            "QPushButton:hover { background-color: #78350F; }"
        )
        self._select_btn.clicked.connect(self._open_file_dialog)
        layout.addWidget(self._select_btn)

        # Close button (shown when project loaded)
        self._close_btn = QPushButton("✕")
        self._close_btn.setFixedSize(20, 20)
        self._close_btn.setStyleSheet(
            "QPushButton { background-color: transparent; color: #71717A;"
            "  border: none; font-size: 12px; }"
            "QPushButton:hover { color: #FAFAFA; }"
        )
        self._close_btn.clicked.connect(self._clear_project)
        self._close_btn.setVisible(False)
        layout.addWidget(self._close_btn)

    def _connect_signals(self) -> None:
        signal_bus.project_loaded.connect(self._on_project_loaded_external)

    # ────────────────────────────────────────────────────────── Slots ── #

    def _open_file_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar project.json",
            str(Path.home()),
            "JSON Files (*.json)",
        )
        if path:
            self._load_project(Path(path))

    def _load_project(self, path: Path) -> None:
        try:
            config = _parse_project_json(path)
            self._current_config = config
            self._show_project(config)
            signal_bus.project_loaded.emit(config.name)
            signal_bus.toast_requested.emit(
                f"Projeto carregado: {config.name}", "success"
            )
        except Exception as exc:
            signal_bus.toast_requested.emit(
                f"Erro ao carregar projeto: {exc}", "error"
            )

    def _show_project(self, config: ProjectConfig) -> None:
        self._hex_icon.setStyleSheet("color: #FBBF24; font-size: 14px;")
        self._name_label.setText(config.name)
        self._name_label.setStyleSheet(
            "color: #FBBF24; font-size: 13px; font-weight: 700;"
        )
        self._name_label.setToolTip(config.path)
        self._select_btn.setVisible(False)
        self._close_btn.setVisible(True)

        parent_win = self.window()
        if parent_win:
            parent_win.setWindowTitle(f"{config.name} — Workflow App")

    def _clear_project(self) -> None:
        self._current_config = None
        self._hex_icon.setStyleSheet("color: #71717A; font-size: 14px;")
        self._name_label.setText("Sem projeto")
        self._name_label.setStyleSheet("color: #71717A; font-size: 13px;")
        self._name_label.setToolTip("")
        self._select_btn.setVisible(True)
        self._close_btn.setVisible(False)

        parent_win = self.window()
        if parent_win:
            parent_win.setWindowTitle("Workflow App")

        signal_bus.project_cleared.emit()

    def _on_project_loaded_external(self, name: str) -> None:
        """Handle project loaded from outside (e.g. CLI arg)."""
        if not self._current_config:
            self._name_label.setText(name)
            self._name_label.setStyleSheet(
                "color: #FBBF24; font-size: 13px; font-weight: 700;"
            )
            self._select_btn.setVisible(False)
            self._close_btn.setVisible(True)

    @property
    def current_config(self) -> ProjectConfig | None:
        """Return currently loaded project configuration."""
        return self._current_config


# ─────────────────────────────────────────────────────────── Helpers ─── #


def _parse_project_json(path: Path) -> ProjectConfig:
    """Parse a project.json (V1/V2/V3) into a ProjectConfig."""
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    # V3 format (has basic_flow)
    if "basic_flow" in data:
        bf = data["basic_flow"]
        name = data.get("name", path.stem)
        return ProjectConfig(
            path=str(path),
            name=name,
            workspace_root=bf.get("workspace_root", ""),
            docs_root=bf.get("docs_root", ""),
            wbs_root=bf.get("wbs_root", ""),
            brief_root=bf.get("brief_root", ""),
        )

    # V2 / V1 fallback
    name = data.get("name", path.stem)
    return ProjectConfig(
        path=str(path),
        name=name,
        workspace_root=data.get("workspace_root", ""),
        docs_root=data.get("docs_root", ""),
        wbs_root=data.get("wbs_root", ""),
        brief_root=data.get("brief_root", ""),
    )
