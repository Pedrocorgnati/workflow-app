"""
ConfigBar — Barra de status do projeto.

Layout:
  [⬡ icon] [project name]  [spacer]  [Selecionar/✕]

Sinais emitidos:
  config_change_requested(str)  — path do .json selecionado
  config_unload_requested()     — usuário clicou em ✕
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QWidget,
)

# keep backward-compat import
from workflow_app.config.app_state import app_state
from workflow_app.signal_bus import signal_bus

logger = logging.getLogger(__name__)

_BG = "#27272A"
_AMBER = "#FBBF24"
_MUTED = "#71717A"
_DANGER = "#EF4444"

class ConfigBar(QWidget):
    """Barra horizontal de 36px para status do projeto.

    Emite:
        config_change_requested(str)  — path do .json selecionado
        config_unload_requested()     — usuário clicou em ✕
    """

    config_change_requested = Signal(str)
    config_unload_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ConfigBar")
        self.setFixedHeight(48)
        self.setStyleSheet(
            f"background-color: {_BG}; border-bottom: 1px solid #3F3F46;"
        )

        self._setup_ui()
        self._connect_signals()
        self._refresh_state()

    # ────────────────────────────────────────────────────────────── UI ── #

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(8)

        # ── Left: icon + project name ───────────────────────────────── #
        self._hex_icon = QLabel("⬡")
        self._hex_icon.setStyleSheet(f"color: {_MUTED}; font-size: 14px;")
        self._hex_icon.setFixedWidth(20)
        layout.addWidget(self._hex_icon)

        self._name_label = QLabel("Sem projeto")
        self._name_label.setFont(QFont("Inter", 11))
        self._name_label.setStyleSheet(f"color: {_MUTED};")
        self._name_label.setToolTip("")
        layout.addWidget(self._name_label)

        layout.addStretch(1)

        # ── Right: project select / unload ──────────────────────────── #
        self._select_btn = QPushButton("Selecionar Projeto...")
        self._select_btn.setFixedHeight(24)
        self._select_btn.setFont(QFont("Inter", 10))
        self._select_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: transparent;"
            f"  color: {_AMBER};"
            f"  border: 1px solid {_AMBER};"
            f"  border-radius: 4px;"
            f"  padding: 0 8px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  background-color: rgba(251, 191, 36, 0.1);"
            f"}}"
        )
        self._select_btn.clicked.connect(self._on_select_clicked)
        layout.addWidget(self._select_btn)

        self._close_btn = QPushButton("✕")
        self._close_btn.setFixedSize(24, 24)
        self._close_btn.setFont(QFont("Inter", 10))
        self._close_btn.setStyleSheet(
            f"QPushButton {{"
            f"  background-color: transparent;"
            f"  color: {_MUTED};"
            f"  border: none;"
            f"  border-radius: 4px;"
            f"}}"
            f"QPushButton:hover {{"
            f"  color: {_DANGER};"
            f"  background-color: rgba(239, 68, 68, 0.1);"
            f"}}"
        )
        self._close_btn.setToolTip("Desvincular projeto")
        self._close_btn.clicked.connect(self._on_unload_clicked)
        self._close_btn.hide()
        layout.addWidget(self._close_btn)

    def _connect_signals(self) -> None:
        signal_bus.config_loaded.connect(self._on_config_loaded)
        signal_bus.config_unloaded.connect(self._on_config_unloaded)

    # ──────────────────────────────────────────────────── State sync ── #

    def _refresh_state(self) -> None:
        if app_state.has_config:
            self._apply_loaded_state(
                app_state.project_name,
                app_state.config.config_path,  # type: ignore[union-attr]
            )
        else:
            self._apply_empty_state()

    def _apply_loaded_state(self, project_name: str, config_path: str) -> None:
        self._hex_icon.setStyleSheet("color: #22C55E; font-size: 14px;")
        self._name_label.setText(project_name)
        self._name_label.setFont(QFont("Inter", 22))
        self._name_label.setStyleSheet("color: #22C55E; font-weight: 600;")
        try:
            rel = Path(config_path).relative_to(Path.cwd())
            tooltip = str(rel)
        except ValueError:
            tooltip = config_path
        self._name_label.setToolTip(tooltip)
        self._select_btn.hide()
        self._close_btn.show()

    def _apply_empty_state(self) -> None:
        self._hex_icon.setStyleSheet(f"color: {_MUTED}; font-size: 14px;")
        self._name_label.setText("Sem projeto")
        self._name_label.setFont(QFont("Inter", 11))
        self._name_label.setStyleSheet(f"color: {_MUTED};")
        self._name_label.setToolTip("")
        self._select_btn.show()
        self._close_btn.hide()

    # ────────────────────────────────────────────────── Signal slots ── #

    def _on_config_loaded(self, path: str) -> None:
        if app_state.has_config:
            self._apply_loaded_state(app_state.project_name, path)

    def _on_config_unloaded(self) -> None:
        self._apply_empty_state()

    def _on_select_clicked(self) -> None:
        start_dir = str(Path.cwd())
        if app_state.has_config and app_state.config:
            start_dir = str(Path(app_state.config.config_path).parent)
        else:
            candidate = Path(__file__).resolve()
            while candidate != candidate.parent:
                projects_dir = candidate / ".claude" / "projects"
                if projects_dir.is_dir():
                    start_dir = str(projects_dir)
                    break
                candidate = candidate.parent

        path, _ = QFileDialog.getOpenFileName(
            self,
            "Selecionar project.json",
            start_dir,
            "JSON Files (*.json);;All Files (*)",
        )
        if path:
            self.config_change_requested.emit(path)

    def _on_unload_clicked(self) -> None:
        self.config_unload_requested.emit()

    # ─────────────────────────────────────────── Backward compat ──── #

    @property
    def current_config(self):
        return app_state.config
