"""
ExecutionDetailPanel — Painel de detalhe de uma execução (module-14/TASK-3+4).

Exibe metadados do pipeline selecionado (data, duração, status) e lista de
CommandExecution com status por comando. Inclui botão de exportação markdown.
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from workflow_app.domain import CommandStatus
from workflow_app.history.history_manager import HistoryManager


class ExecutionDetailPanel(QWidget):
    """Painel de detalhes de uma execução de pipeline."""

    def __init__(
        self, history_manager: HistoryManager, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self._mgr = history_manager
        self._current_exec_id: int | None = None
        self._setup_ui()

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        self._header_label = QLabel("Selecione uma execução")
        self._header_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._header_label.setWordWrap(True)
        layout.addWidget(self._header_label)

        self._commands_list = QListWidget()
        layout.addWidget(self._commands_list)

        btn_export = QPushButton("Exportar Markdown")
        btn_export.clicked.connect(self._export_markdown)
        layout.addWidget(btn_export)

    # ─── Public ─────────────────────────────────────────────────────── #

    def load_execution(self, pipeline_exec_id: int) -> None:
        """Carrega e exibe os detalhes da execução selecionada."""
        self._current_exec_id = pipeline_exec_id
        try:
            pe = self._mgr.get_execution_detail(pipeline_exec_id)
        except Exception as exc:
            self._header_label.setText(f"Erro ao carregar execução: {exc}")
            self._commands_list.clear()
            return

        if pe is None:
            self._header_label.setText("Execução não encontrada")
            self._commands_list.clear()
            return

        created = (
            pe.created_at.strftime("%Y-%m-%d %H:%M") if pe.created_at else "—"
        )
        self._header_label.setText(
            f"ID {pe.id} · {created} · Status: {pe.status.upper()}"
        )

        self._commands_list.clear()
        commands = sorted(
            getattr(pe, "commands", []), key=lambda c: c.position
        )
        for cmd in commands:
            label = f"{cmd.position + 1}. {cmd.command_name} — {cmd.status}"
            if cmd.model:
                label += f" [{cmd.model}]"
            if getattr(cmd, "elapsed_seconds", None):
                label += f" {cmd.elapsed_seconds}s"

            item = QListWidgetItem(label)
            if cmd.status == CommandStatus.ERRO.value:
                item.setForeground(Qt.GlobalColor.red)
            elif cmd.status == CommandStatus.CONCLUIDO.value:
                item.setForeground(Qt.GlobalColor.green)

            self._commands_list.addItem(item)

    # ─── Internal ───────────────────────────────────────────────────── #

    def _export_markdown(self) -> None:
        if self._current_exec_id is None:
            return
        md = self._mgr.export_execution_markdown(self._current_exec_id)
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Salvar Resumo",
            f"execução-{self._current_exec_id}.md",
            "Markdown (*.md)",
        )
        if path:
            from pathlib import Path

            Path(path).write_text(md, encoding="utf-8")
