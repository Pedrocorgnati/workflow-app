"""
CommandStateMachine — Declarative state machine for a single CommandExecution.

Uses python-statemachine v2.3+ API with declarative states/transitions as
class attributes. One instance per active CommandExecution.

States:
    PENDENTE → EXECUTANDO → CONCLUIDO
                           ↓
                         ERRO ←→ EXECUTANDO (retry)
                           ↓
                        PULADO (via skip, directly from PENDENTE)
                           ↓
                       INCERTO (app_closed from EXECUTANDO)

Module: module-11/TASK-1
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from statemachine import State, StateMachine

from workflow_app.domain import CommandStatus

if TYPE_CHECKING:
    from workflow_app.signal_bus import SignalBus


class CommandStateMachine(StateMachine):
    """State machine for a single CommandExecution lifecycle.

    One instance per command in execution. PipelineManager delegates all
    state transitions here.
    """

    # ── Declarative states ────────────────────────────────────────────── #

    pendente = State(CommandStatus.PENDENTE.value, initial=True)
    executando = State(CommandStatus.EXECUTANDO.value)
    concluido = State(CommandStatus.CONCLUIDO.value, final=True)
    erro = State(CommandStatus.ERRO.value)
    pulado = State(CommandStatus.PULADO.value, final=True)
    incerto = State(CommandStatus.INCERTO.value)  # not final — can resume via retry_uncertain

    # ── Declarative transitions ───────────────────────────────────────── #

    start = pendente.to(executando)
    result_ok = executando.to(concluido)
    result_fail = executando.to(erro)
    skip = pendente.to(pulado)
    app_closed = executando.to(incerto)
    retry = erro.to(executando)
    retry_uncertain = incerto.to(executando)

    # ── Constructor ───────────────────────────────────────────────────── #

    def __init__(
        self,
        *,
        command_exec_id: int,
        signal_bus: SignalBus,
        persist_callback: Callable[
            [int, CommandStatus, datetime | None, datetime | None], None
        ],
    ) -> None:
        """
        Args:
            command_exec_id: ID of the CommandExecution in the database.
            signal_bus: Global Qt signal bus.
            persist_callback: Called on each state change to persist.
                Signature: (command_exec_id, new_status, started_at, finished_at)
        """
        super().__init__()
        self._command_exec_id = command_exec_id
        self._signal_bus = signal_bus
        self._persist = persist_callback
        self._started_at: datetime | None = None
        self._finished_at: datetime | None = None

    # ── on_enter_* callbacks (invoked automatically by statemachine) ──── #

    def on_enter_executando(self) -> None:
        """Record start time, persist and emit signal."""
        self._started_at = datetime.now(tz=timezone.utc)
        self._persist(
            self._command_exec_id,
            CommandStatus.EXECUTANDO,
            self._started_at,
            None,
        )
        self._signal_bus.command_status_changed.emit(
            self._command_exec_id, CommandStatus.EXECUTANDO.value
        )

    def on_enter_concluido(self) -> None:
        """Record completion time, persist and emit signal."""
        self._finished_at = datetime.now(tz=timezone.utc)
        self._persist(
            self._command_exec_id,
            CommandStatus.CONCLUIDO,
            self._started_at,
            self._finished_at,
        )
        self._signal_bus.command_status_changed.emit(
            self._command_exec_id, CommandStatus.CONCLUIDO.value
        )

    def on_enter_erro(self) -> None:
        """Persist error state and emit signal."""
        self._finished_at = datetime.now(tz=timezone.utc)
        self._persist(
            self._command_exec_id,
            CommandStatus.ERRO,
            self._started_at,
            self._finished_at,
        )
        self._signal_bus.command_status_changed.emit(
            self._command_exec_id, CommandStatus.ERRO.value
        )

    def on_enter_pulado(self) -> None:
        """Persist PULADO state and emit signal."""
        self._finished_at = datetime.now(tz=timezone.utc)
        self._persist(
            self._command_exec_id,
            CommandStatus.PULADO,
            self._started_at,
            self._finished_at,
        )
        self._signal_bus.command_status_changed.emit(
            self._command_exec_id, CommandStatus.PULADO.value
        )

    def on_enter_incerto(self) -> None:
        """Persist INCERTO silently — app may be closing."""
        self._persist(
            self._command_exec_id,
            CommandStatus.INCERTO,
            self._started_at,
            None,
        )
        # Do NOT emit signal — app may be shutting down

    # ── Helpers ───────────────────────────────────────────────────────── #

    def mark_error(self, error_msg: str) -> None:
        """Store the error message and transition EXECUTANDO → ERRO.

        Preferred over calling result_fail() directly because it captures
        the error message for later inspection.
        """
        self._last_error_message = error_msg
        self.result_fail()

    @property
    def last_error_message(self) -> str | None:
        """Return the last error message set via mark_error(), or None."""
        return getattr(self, "_last_error_message", None)

    @property
    def current_command_status(self) -> CommandStatus:
        """Return the CommandStatus corresponding to the current state."""
        return CommandStatus(self.current_state_value)

    @property
    def duration_seconds(self) -> float | None:
        """Duration in seconds if both started_at and finished_at are set."""
        if self._started_at and self._finished_at:
            return (self._finished_at - self._started_at).total_seconds()
        return None
