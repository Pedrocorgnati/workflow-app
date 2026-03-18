"""
PipelineManager — Central orchestrator for pipeline execution.

Covers:
  TASK-2: PipelineManager with start/pause/resume/cancel/advance/retry/skip
  TASK-3: Guards (can_edit_queue, can_reorder, can_start_next) + full logging

Design:
  - One instance per execution session (not a singleton).
  - Delegates all state transitions to CommandStateMachine.
  - Persists each change via SQLAlchemy sessionmaker (thread-safe).
  - Emits signals via SignalBus — never accesses Qt widgets directly.
  - Keeps references to SDKWorker instances in self._workers (prevents GC).

Module: module-11/TASK-2 + TASK-3
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from workflow_app.domain import CommandStatus, InteractionType, PipelineStatus
from workflow_app.pipeline.command_state_machine import CommandStateMachine
from workflow_app.sdk.pty_runner import PtyRunner as ProcessRunner

if TYPE_CHECKING:
    from sqlalchemy.orm import sessionmaker

    from workflow_app.domain import CommandSpec
    from workflow_app.sdk.sdk_adapter import SDKAdapter
    from workflow_app.signal_bus import SignalBus
    from workflow_app.system_progress_writer import SystemProgressWriter

logger = logging.getLogger(__name__)


class PipelineManager:
    """Orchestrates sequential execution of a CommandSpec queue.

    Responsibilities:
    - Create/update PipelineExecution and CommandExecution records in the DB
    - Instantiate and start SDKWorker per command
    - Delegate transitions to CommandStateMachine
    - Emit signals via SignalBus
    - Support pause, cancel, retry, skip, advance, check_resume
    """

    def __init__(
        self,
        *,
        signal_bus: SignalBus,
        sdk_adapter: SDKAdapter,
        session_factory: sessionmaker,
        system_progress_writer: SystemProgressWriter | None = None,
        workspace_dir: str = "",
        wbs_root: str = "",
    ) -> None:
        self._signal_bus = signal_bus
        self._sdk_adapter = sdk_adapter
        self._session_factory = session_factory
        self._progress_writer = system_progress_writer
        self._workspace_dir = workspace_dir
        self._wbs_root = wbs_root

        # In-memory pipeline state
        self._queue: list[CommandSpec] = []
        self._current_index: int = 0
        self._pipeline_exec_id: int | None = None
        self._paused: bool = False
        self._permission_mode: str = "acceptEdits"

        # State machines: command_exec_id → CommandStateMachine
        self._state_machines: dict[int, CommandStateMachine] = {}

        # Optional ExtrasOrchestrator (token tracking, git info, notifications)
        self._extras: object | None = None

        # Active runners (anti-GC references)
        self._workers: list[ProcessRunner] = []
        # Currently running ProcessRunner (for cancel)
        self._current_runner: ProcessRunner | None = None

        # Mapping from position index → command_exec_id (set during _launch_current)
        self._position_to_exec_id: dict[int, int] = {}

        # command_exec_id of the currently running command
        self._current_command_exec_id: int | None = None

        # Set to True when AskUserQuestion is intercepted during execution;
        # forces manual advance even for NON_INTERACTIVE commands.
        self._force_interactive_next_complete: bool = False

    # ── Public API ────────────────────────────────────────────────────── #

    def set_extras_orchestrator(self, extras: object) -> None:
        """Inject the ExtrasOrchestrator (optional, for token/git/notification support)."""
        self._extras = extras

    def set_queue(self, commands: list[CommandSpec]) -> None:
        """Set the command queue before calling start()."""
        self._queue = list(commands)
        self._current_index = 0

    def start(self, permission_mode: str | None = None) -> None:
        """Create PipelineExecution in DB and start the first command."""
        if not self._queue:
            logger.warning("PipelineManager.start() called with empty queue")
            return
        if permission_mode is None:
            from workflow_app.config.app_config import AppConfig
            permission_mode = AppConfig.get("default_permission_mode", "acceptEdits")
        self._permission_mode = permission_mode
        self._paused = False
        self._pipeline_exec_id = self._create_pipeline_execution()
        self._signal_bus.pipeline_status_changed.emit(
            self._pipeline_exec_id, PipelineStatus.EXECUTANDO.value
        )
        self._signal_bus.pipeline_started.emit()
        self._signal_bus.interactive_advance_triggered.connect(self.interactive_advance)
        self._signal_bus.interactive_input_requested.connect(self._on_interaction_detected)
        self._launch_current()

    def pause(self) -> None:
        """Pause after the current command completes."""
        self._paused = True
        if self._pipeline_exec_id:
            self._log_pipeline_event("paused")
            self._signal_bus.pipeline_status_changed.emit(
                self._pipeline_exec_id, PipelineStatus.PAUSADO.value
            )
            self._signal_bus.pipeline_paused.emit()

    def resume(self) -> None:
        """Resume after pause."""
        self._paused = False
        if self._pipeline_exec_id:
            self._log_pipeline_event("resumed")
            self._signal_bus.pipeline_status_changed.emit(
                self._pipeline_exec_id, PipelineStatus.EXECUTANDO.value
            )
            self._signal_bus.pipeline_resumed.emit()
        self._launch_current()

    def cancel(self) -> None:
        """Cancel pipeline: stop current runner and mark as CANCELADO."""
        if self._current_runner is not None:
            self._current_runner.terminate()
        if self._pipeline_exec_id:
            self._log_pipeline_event("cancelled")
            self._update_pipeline_status(PipelineStatus.CANCELADO)
            self._signal_bus.pipeline_status_changed.emit(
                self._pipeline_exec_id, PipelineStatus.CANCELADO.value
            )
            self._signal_bus.pipeline_cancelled.emit()

    def advance(self) -> None:
        """Advance to the next command in the queue.

        Called manually (interactive mode) or automatically (autocast).
        """
        self._current_index += 1
        if self._current_index >= len(self._queue):
            self._on_pipeline_completed()
            return
        if not self._paused:
            self._launch_current()

    def interactive_advance(self) -> None:
        """Advance triggered by user clicking 'Próximo' in interactive mode.

        No-op unless the current command is in an AGUARDANDO_INTERACAO state
        (i.e. interactive_advance_ready was emitted and no advance has occurred).
        Guard: only proceed if there is a completed interactive command waiting.
        """
        if self._current_command_exec_id is None:
            logger.debug("interactive_advance: no current command — noop")
            return
        sm = self._state_machines.get(self._current_command_exec_id)
        if sm is None:
            logger.debug("interactive_advance: no state machine — noop")
            return
        if sm.current_command_status != CommandStatus.CONCLUIDO:
            logger.debug(
                "interactive_advance: status=%s, not CONCLUIDO — noop",
                sm.current_command_status,
            )
            return
        logger.info("interactive_advance: advancing from interactive command")
        self.advance()

    def _on_interaction_detected(self) -> None:
        """Called when AskUserQuestion is intercepted in the SDK.

        Forces the pipeline to wait for manual advance after the current
        command completes, regardless of the command's interaction_type.
        """
        self._force_interactive_next_complete = True
        logger.debug("Interaction detected — queue will pause after current command")

    def send_interactive_response(
        self, request_id: str, value: str, response_type: str
    ) -> bool:
        """Route an interactive response received from the Android remote app.

        Called by SignalBridge after first-response-wins validation.

        Args:
            request_id:    UUID of the interaction (for logging only; idempotency
                           is enforced by SignalBridge before this call).
            value:         User's text answer or "approve" / "deny".
            response_type: "text_input" or "permission".

        Returns:
            True if the response was routed, False if there was nothing to route.
        """
        if response_type == "text_input":
            logger.info(
                "PipelineManager: routing text_input response (request_id=%s) from mobile",
                request_id,
            )
            self._signal_bus.user_input_submitted.emit(value)
            return True

        if response_type == "permission":
            approved = value == "approve"
            if self._sdk_adapter is not None and hasattr(self._sdk_adapter, "respond_to_permission"):
                logger.info(
                    "PipelineManager: routing permission response=%s (request_id=%s) from mobile",
                    value,
                    request_id,
                )
                self._sdk_adapter.respond_to_permission(approved)
                return True
            logger.warning(
                "PipelineManager: permission response received but no SDKAdapter "
                "(request_id=%s)",
                request_id,
            )
            return False

        logger.warning(
            "PipelineManager: unknown response_type=%s (request_id=%s)",
            response_type,
            request_id,
        )
        return False

    def retry_current(self) -> None:
        """Transition ERRO → EXECUTANDO and relaunch the worker."""
        if self._current_command_exec_id is None:
            return
        sm = self._state_machines.get(self._current_command_exec_id)
        if sm and sm.current_command_status == CommandStatus.ERRO:
            self._log_execution_event(self._current_command_exec_id, "retry")
            sm.retry()
            self._launch_worker_for(
                self._queue[self._current_index],
                self._current_command_exec_id,
            )

    def skip_current(self) -> None:
        """Transition PENDENTE → PULADO and advance."""
        if self._current_command_exec_id is None:
            return
        sm = self._state_machines.get(self._current_command_exec_id)
        if sm and sm.current_command_status == CommandStatus.PENDENTE:
            self._log_execution_event(self._current_command_exec_id, "skipped")
            sm.skip()
            self.advance()

    def check_resume(self) -> int | None:
        """Check for interrupted PipelineExecution.

        Returns:
            pipeline_exec_id if found, None otherwise.
        """
        from workflow_app.db.models import PipelineExecution

        with self._session_factory() as session:
            interrupted = (
                session.query(PipelineExecution)
                .filter(
                    PipelineExecution.status.notin_(
                        [PipelineStatus.CONCLUIDO.value, PipelineStatus.CANCELADO.value]
                    )
                )
                .order_by(PipelineExecution.created_at.desc())
                .first()
            )
            return interrupted.id if interrupted else None

    def expand_with_modules(self, new_commands: list[CommandSpec]) -> None:
        """Insert new commands after the current position (INT-035)."""
        insert_pos = self._current_index + 1
        self._queue[insert_pos:insert_pos] = new_commands
        logger.info(
            "Queue expanded with %d commands starting at position %d",
            len(new_commands),
            insert_pos,
        )

    # ── Guards ────────────────────────────────────────────────────────── #

    def can_edit_queue(self, position: int) -> bool:
        """Return True if the item at position can be edited.

        An item cannot be edited if it is in state EXECUTANDO.
        Out-of-range positions are considered editable (new items).
        """
        if position < 0 or position >= len(self._queue):
            return True
        exec_id = self._get_exec_id_for_position(position)
        if exec_id is None:
            return True
        sm = self._state_machines.get(exec_id)
        if sm is None:
            return True
        return sm.current_command_status != CommandStatus.EXECUTANDO

    def can_reorder(self, position: int) -> bool:
        """Return True if the item at position can be reordered.

        Only allows reordering if the item is in PENDENTE.
        """
        if position < 0 or position >= len(self._queue):
            return False
        exec_id = self._get_exec_id_for_position(position)
        if exec_id is None:
            return True  # Not yet started = implicitly PENDENTE
        sm = self._state_machines.get(exec_id)
        if sm is None:
            return True
        return sm.current_command_status == CommandStatus.PENDENTE

    def can_start_next(self, position: int) -> bool:
        """Return True if the next item at position can be started.

        The predecessor must be in CONCLUIDO or PULADO.
        """
        if position == 0:
            return True
        prev_exec_id = self._get_exec_id_for_position(position - 1)
        if prev_exec_id is None:
            return False
        sm = self._state_machines.get(prev_exec_id)
        if sm is None:
            return False
        return sm.current_command_status in (
            CommandStatus.CONCLUIDO,
            CommandStatus.PULADO,
        )

    def reorder_command(self, from_spec_pos: int, to_indicator_pos: int) -> bool:
        """Move a command within the queue before execution starts.

        Args:
            from_spec_pos: 1-based spec position of the item to move.
            to_indicator_pos: 0-based target index in the queue layout.

        Returns True on success, False if the guard blocks the move.
        """
        from_idx = from_spec_pos - 1  # 1-based → 0-based
        if not self.can_reorder(from_idx):
            logger.warning("reorder_command blocked: position %d cannot be reordered", from_idx)
            return False
        queue_len = len(self._queue)
        if from_idx < 0 or from_idx >= queue_len:
            return False
        to_idx = max(0, min(to_indicator_pos, queue_len))
        if from_idx == to_idx:
            return False
        item = self._queue.pop(from_idx)
        insert_idx = to_idx if to_idx < from_idx else to_idx - 1
        self._queue.insert(insert_idx, item)
        # Re-number positions (1-based)
        for i, spec in enumerate(self._queue):
            spec.position = i + 1
        logger.info("reorder_command: moved position %d → index %d", from_spec_pos, insert_idx + 1)
        return True

    # ── Internal: worker launching ────────────────────────────────────── #

    def _launch_current(self) -> None:
        """Create CommandExecution in DB and start SDKWorker for current index."""
        spec = self._queue[self._current_index]
        command_exec_id = self._create_command_execution(spec)
        self._current_command_exec_id = command_exec_id
        self._position_to_exec_id[self._current_index] = command_exec_id

        sm = CommandStateMachine(
            command_exec_id=command_exec_id,
            signal_bus=self._signal_bus,
            persist_callback=self._persist_command_status,
        )
        self._state_machines[command_exec_id] = sm
        self._log_execution_event(command_exec_id, "started")
        sm.start()  # PENDENTE → EXECUTANDO

        self._launch_worker_for(spec, command_exec_id)

    def _launch_worker_for(self, spec: CommandSpec, command_exec_id: int) -> None:
        """Instantiate and start ProcessRunner. Maintain reference in self._workers."""
        runner = ProcessRunner()
        self._current_runner = runner

        model_str = (
            spec.model.value.lower()
            if hasattr(spec.model, "value")
            else str(spec.model).lower()
        )

        runner.output_received.connect(self._signal_bus.output_chunk_received)
        runner.command_completed.connect(
            lambda name, ok, _id=command_exec_id: self._on_command_completed(_id, ok)
        )
        runner.error_occurred.connect(
            lambda msg, _id=command_exec_id: self._on_worker_error(_id, msg)
        )
        # Connect user input from UI → runner stdin
        self._signal_bus.user_input_submitted.connect(runner.send_user_input)
        # Cleanup when done
        runner.command_completed.connect(lambda _n, _ok: self._cleanup_runner(runner))

        self._workers.append(runner)
        self._signal_bus.current_worker_changed.emit(runner)

        # Show "$ claude /command [config]" in terminal so the user sees what's running
        cmd_display = spec.name if spec.name.startswith("/") else f"/{spec.name}"
        config_suffix = f" {spec.config_path}" if spec.config_path else ""
        self._signal_bus.output_chunk_received.emit(
            f"\n\x1b[32m$\x1b[0m claude {cmd_display}{config_suffix}\n"
        )

        runner.start(
            command=spec.name,
            model=model_str,
            permission_mode=self._permission_mode,
            workspace_dir=self._workspace_dir or None,
            config_path=spec.config_path or None,
        )

    def _cleanup_runner(self, runner: ProcessRunner) -> None:
        """Remove runner reference when finished."""
        try:
            self._workers.remove(runner)
        except ValueError:
            pass
        # Disconnect user_input to avoid leaking connections
        try:
            self._signal_bus.user_input_submitted.disconnect(runner.send_user_input)
        except RuntimeError:
            pass
        if self._current_runner is runner:
            self._current_runner = None

    # ── Internal: worker callbacks ────────────────────────────────────── #

    def _on_command_completed(self, command_exec_id: int, success: bool) -> None:
        """Called by SDKWorker when it finishes (success or handled failure)."""
        sm = self._state_machines.get(command_exec_id)
        if sm is None:
            return

        if success:
            sm.result_ok()
            self._log_execution_event(command_exec_id, "completed")
            self._signal_bus.output_chunk_received.emit("\n\x1b[32m$\x1b[0m ")  # bash prompt
            # Notify ExtrasOrchestrator (tokens + git info)
            if self._extras is not None and self._pipeline_exec_id is not None:
                spec = self._queue[self._current_index]
                try:
                    self._extras.on_command_completed(
                        pipeline_id=self._pipeline_exec_id,
                        command_id=command_exec_id,
                        model=spec.model.value if hasattr(spec.model, "value") else str(spec.model),
                    )
                except Exception:  # noqa: BLE001
                    pass
            # Try to mark progress in SYSTEM-PROGRESS.md
            spec = self._queue[self._current_index]
            if self._progress_writer is not None:
                try:
                    self._progress_writer.mark_completed(spec.name.lstrip("/"), "")
                except Exception:  # noqa: BLE001
                    pass
            # RF13: Check if completed command triggers queue expansion
            self._try_expand_queue(spec.name)
            # Autocast: advance automatically unless interactive or question was asked
            is_interactive = spec.interaction_type == InteractionType.INTERACTIVE
            had_question = self._force_interactive_next_complete
            self._force_interactive_next_complete = False  # reset for next command
            if not is_interactive and not had_question:
                next_index = self._current_index + 1
                next_name = self._queue[next_index].name if next_index < len(self._queue) else ""
                self._signal_bus.autocast_advancing.emit(next_name)
                self.advance()
            else:
                # Interactive mode or question was asked: notify UI that manual advance is ready
                self._signal_bus.interactive_advance_ready.emit(command_exec_id)
        else:
            # Error already handled by _on_worker_error; sm.result_fail() called there
            pass

    def _on_worker_error(self, command_exec_id: int, message: str) -> None:
        """Called by SDKWorker when an error occurs."""
        sm = self._state_machines.get(command_exec_id)
        if sm is None:
            return
        if sm.current_command_status == CommandStatus.EXECUTANDO:
            sm.mark_error(message)
        logger.error("Worker error for command %d: %s", command_exec_id, message)
        self._log_execution_event(command_exec_id, f"error: {message}")
        self._signal_bus.pipeline_error_occurred.emit(
            self._pipeline_exec_id or 0, message
        )
        # Notify ExtrasOrchestrator of command error
        if self._extras is not None:
            spec = self._queue[self._current_index] if self._current_index < len(self._queue) else None
            cmd_name = spec.name if spec else "unknown"
            try:
                self._extras.on_command_error(cmd_name, message)
            except Exception:  # noqa: BLE001
                pass

    # ── Internal: RF13 queue expansion ───────────────────────────────── #

    def _try_expand_queue(self, command_name: str) -> None:
        """RF13: Call QueueExpander after each completed command.

        Appends new CommandSpec objects to self._queue if a trigger command
        (e.g. /modules:review-created, /deploy-flow) was just completed.
        Silently skips if wbs_root is not configured or expansion yields nothing.
        """
        if not self._wbs_root:
            return
        try:
            from workflow_app.pipeline.queue_expander import QueueExpander

            expander = QueueExpander(self._wbs_root)
            existing = [s.name for s in self._queue]
            new_specs = expander.check_and_expand(command_name, existing)
            if new_specs:
                for spec in new_specs:
                    spec.position = len(self._queue)
                    self._queue.append(spec)
                self._signal_bus.queue_expanded.emit([s.name for s in new_specs])
                logger.info(
                    "RF13 QueueExpander: %d new command(s) added after '%s'",
                    len(new_specs),
                    command_name,
                )
        except Exception:  # noqa: BLE001
            logger.debug("RF13 QueueExpander: expansion skipped due to error", exc_info=True)

    # ── Internal: pipeline completion ────────────────────────────────── #

    def _on_pipeline_completed(self) -> None:
        """All commands done — update PipelineExecution and emit signal."""
        from workflow_app.db.models import PipelineExecution

        if self._pipeline_exec_id is None:
            return

        with self._session_factory() as session:
            pe = session.get(PipelineExecution, self._pipeline_exec_id)
            if pe is None:
                return
            pe.status = PipelineStatus.CONCLUIDO.value
            pe.completed_at = datetime.now(tz=timezone.utc)
            pe.commands_completed = sum(
                1
                for sm in self._state_machines.values()
                if sm.current_command_status == CommandStatus.CONCLUIDO
            )
            pe.commands_skipped = sum(
                1
                for sm in self._state_machines.values()
                if sm.current_command_status == CommandStatus.PULADO
            )
            session.commit()

        # Disconnect per-pipeline signals to avoid duplicate connections on restart
        try:
            self._signal_bus.interactive_input_requested.disconnect(self._on_interaction_detected)
        except RuntimeError:
            pass

        self._log_pipeline_event("pipeline_completed")
        self._signal_bus.pipeline_status_changed.emit(
            self._pipeline_exec_id, PipelineStatus.CONCLUIDO.value
        )
        self._signal_bus.pipeline_completed.emit()
        self._signal_bus.pipeline_all_completed.emit(self._pipeline_exec_id)

        # Notify ExtrasOrchestrator: persist pipeline cost totals + notify done
        if self._extras is not None and self._pipeline_exec_id is not None:
            try:
                if hasattr(self._extras, '_tokens') and self._extras._tokens is not None:
                    self._extras._tokens.persist_pipeline_totals(self._pipeline_exec_id)
                errors = sum(
                    1 for sm in self._state_machines.values()
                    if sm.current_command_status == CommandStatus.ERRO
                )
                self._extras.on_pipeline_done(
                    self._workspace_dir, "", errors
                )
            except Exception:  # noqa: BLE001
                pass

    # ── Internal: persistence ─────────────────────────────────────────── #

    def _create_pipeline_execution(self) -> int:
        from workflow_app.db.models import PipelineExecution

        with self._session_factory() as session:
            pe = PipelineExecution(
                project_config_path=self._workspace_dir,
                status=PipelineStatus.EXECUTANDO.value,
                permission_mode=self._permission_mode,
                commands_total=len(self._queue),
                started_at=datetime.now(tz=timezone.utc),
            )
            session.add(pe)
            session.commit()
            return pe.id

    def _create_command_execution(self, spec: CommandSpec) -> int:
        from workflow_app.db.models import CommandExecution

        with self._session_factory() as session:
            ce = CommandExecution(
                pipeline_id=self._pipeline_exec_id,
                command_name=spec.name,
                model=spec.model.value.lower(),
                interaction_type=spec.interaction_type.value,
                status=CommandStatus.PENDENTE.value,
                position=self._current_index,
                is_optional=spec.is_optional,
            )
            session.add(ce)
            session.commit()
            return ce.id

    def _persist_command_status(
        self,
        command_exec_id: int,
        status: CommandStatus,
        started_at: datetime | None,
        finished_at: datetime | None,
    ) -> None:
        from workflow_app.db.models import CommandExecution

        with self._session_factory() as session:
            ce = session.get(CommandExecution, command_exec_id)
            if ce is None:
                return
            ce.status = status.value
            if started_at and ce.started_at is None:
                ce.started_at = started_at
            if finished_at:
                ce.completed_at = finished_at
                if ce.started_at:
                    sa = ce.started_at
                    # SQLite returns tz-naive datetimes; normalise before subtraction
                    if finished_at.tzinfo is not None and sa.tzinfo is None:
                        sa = sa.replace(tzinfo=timezone.utc)
                    delta = finished_at - sa
                    ce.elapsed_seconds = int(delta.total_seconds())
            session.commit()

    def _update_pipeline_status(self, status: PipelineStatus) -> None:
        from workflow_app.db.models import PipelineExecution

        if self._pipeline_exec_id is None:
            return
        with self._session_factory() as session:
            pe = session.get(PipelineExecution, self._pipeline_exec_id)
            if pe is None:
                return
            pe.status = status.value
            if status in (PipelineStatus.CONCLUIDO, PipelineStatus.CANCELADO):
                pe.completed_at = datetime.now(tz=timezone.utc)
            session.commit()

    def _log_execution_event(self, command_exec_id: int, event: str) -> None:
        """Log an event associated with a specific CommandExecution."""
        if self._pipeline_exec_id is None:
            return
        from workflow_app.db.models import ExecutionLog

        with self._session_factory() as session:
            log = ExecutionLog(
                pipeline_id=self._pipeline_exec_id,
                command_execution_id=command_exec_id if command_exec_id != 0 else None,
                level="info",
                message=event,
            )
            session.add(log)
            session.commit()

    def _log_pipeline_event(self, event: str) -> None:
        """Log a pipeline-level event (no specific CommandExecution)."""
        self._log_execution_event(0, f"pipeline:{event}")

    # ── Guard helpers ─────────────────────────────────────────────────── #

    def _get_exec_id_for_position(self, position: int) -> int | None:
        """Return the command_exec_id for the given position (if created)."""
        return self._position_to_exec_id.get(position)
