"""
ExtrasOrchestrator — Integração de TokenTracker, GitInfoReader e NotificationService
(module-15/TASK-4).

Design de plugin: se qualquer dos extras não estiver disponível (None),
as chamadas correspondentes são no-ops silenciosas.
"""

from __future__ import annotations

import logging

from PySide6.QtCore import QObject, QThread, Signal

from workflow_app.core.git_info_reader import GitInfoReader
from workflow_app.core.notification_service import NotificationService
from workflow_app.core.token_tracker import TokenTracker
from workflow_app.domain import ModelType, PipelineStatus
from workflow_app.signal_bus import SignalBus

logger = logging.getLogger(__name__)


class _GitWorker(QThread):
    """Worker para chamar GitInfoReader sem bloquear a UI."""

    result_ready = Signal(str)  # texto formatado para MetricsBar

    def __init__(
        self,
        reader: GitInfoReader,
        workspace_root: str,
    ) -> None:
        super().__init__()
        self._reader = reader
        self._workspace_root = workspace_root

    def run(self) -> None:
        info = self._reader.get_info(self._workspace_root)
        if info is not None:
            text = GitInfoReader.format_for_display(info)
            self.result_ready.emit(text)


class ExtrasOrchestrator(QObject):
    """Orquestra a integração de TokenTracker, GitInfoReader e NotificationService.

    Design de plugin: se qualquer dos extras não estiver disponível (None),
    as chamadas correspondentes são no-ops silenciosas.
    """

    def __init__(
        self,
        signal_bus: SignalBus,
        *,
        token_tracker: TokenTracker | None = None,
        git_reader: GitInfoReader | None = None,
        notification_service: NotificationService | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._bus = signal_bus
        self._tokens = token_tracker
        self._git = git_reader
        self._notifs = notification_service
        self._git_workers: list[_GitWorker] = []
        self._workspace_root: str = ""

        self._connect_signals()

    def set_workspace_root(self, path: str) -> None:
        """Define o workspace root para leitura de git info."""
        self._workspace_root = path

    # ------------------------------------------------------------------
    # API pública (chamada pelo PipelineManager)
    # ------------------------------------------------------------------

    def on_command_completed(
        self,
        pipeline_id: int,
        command_id: int,
        model: str,
        tokens_in: int = 0,
        tokens_out: int = 0,
    ) -> None:
        """Chamado após cada comando concluído.

        Registra tokens e dispara leitura de git info em background.
        """
        # 1. Tokens
        if self._tokens is not None and (tokens_in > 0 or tokens_out > 0):
            try:
                model_type = ModelType(model)
            except ValueError:
                model_type = ModelType.SONNET

            self._tokens.record(command_id, tokens_in, tokens_out, model_type)
            total_in, total_out, total_cost = self._tokens.get_session_total(pipeline_id)
            self._bus.token_update.emit(total_in, total_out, total_cost)

        # 2. Git info (em background)
        if self._git is not None and self._workspace_root:
            worker = _GitWorker(self._git, self._workspace_root)
            worker.result_ready.connect(self._bus.git_info_updated.emit)
            self._git_workers.append(worker)
            worker.finished.connect(lambda: self._cleanup_worker(worker))
            worker.start()

    def on_pipeline_done(
        self,
        project: str,
        duration: str,
        errors: int,
    ) -> None:
        """Chamado quando pipeline é concluído."""
        if self._notifs is not None:
            self._notifs.notify_pipeline_done(project, duration, errors)
            self._notifs.show_tray_icon(executing=False)

    def on_command_error(self, command: str, error: str) -> None:
        """Chamado quando um comando falha."""
        if self._notifs is not None:
            self._notifs.notify_command_error(command, error)

    def on_pipeline_paused(self, command: str) -> None:
        """Chamado quando o pipeline pausa para interação."""
        if self._notifs is not None:
            self._notifs.notify_pipeline_paused(command)

    # ------------------------------------------------------------------
    # Conexão com SignalBus
    # ------------------------------------------------------------------

    def _connect_signals(self) -> None:
        """Conecta signals do SignalBus ao orchestrator."""
        self._bus.pipeline_status_changed.connect(self._on_pipeline_status)

    def _on_pipeline_status(self, pipeline_id: int, status_str: str) -> None:
        try:
            status = PipelineStatus(status_str)
        except ValueError:
            return

        if status == PipelineStatus.EXECUTANDO and self._notifs is not None:
            self._notifs.show_tray_icon(executing=True)
        elif status in (PipelineStatus.CONCLUIDO, PipelineStatus.CANCELADO):
            if self._notifs is not None:
                self._notifs.show_tray_icon(executing=False)

    def _cleanup_worker(self, worker: _GitWorker) -> None:
        """Remove worker concluído da lista (previne memory leak)."""
        try:
            self._git_workers.remove(worker)
        except ValueError:
            pass
