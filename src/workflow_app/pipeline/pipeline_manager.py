"""
PipelineManager — Orchestrates command execution (module-11/TASK-2).

TODO: Implement backend — module-11 (auto-flow execute)
"""

from __future__ import annotations

from typing import Callable

from workflow_app.domain import CommandSpec, PipelineStatus


class PipelineManager:
    """
    Manages sequential execution of a CommandSpec queue.

    Responsibilities:
    - Start, pause, resume, cancel pipeline execution
    - Delegate each command to SDKWorker
    - Update command states via CommandStateMachine
    - Emit progress signals via SignalBus

    TODO: Implement backend — module-11 (auto-flow execute)
    """

    def __init__(self) -> None:
        # TODO: Implement backend — module-11
        self._status = PipelineStatus.NAO_INICIADO
        self._commands: list[CommandSpec] = []

    def load_pipeline(self, commands: list[CommandSpec]) -> None:
        """Load a pipeline from a list of CommandSpec objects."""
        # TODO: Implement backend — module-11/TASK-2
        self._commands = commands

    def start(self, workspace: str) -> None:
        """Start executing the pipeline."""
        # TODO: Implement backend — module-11/TASK-2
        raise NotImplementedError("module-11/TASK-2 not yet implemented — run /auto-flow execute")

    def pause(self) -> None:
        """Pause the running pipeline."""
        # TODO: Implement backend — module-11/TASK-3
        raise NotImplementedError("module-11/TASK-3 not yet implemented — run /auto-flow execute")

    def resume(self) -> None:
        """Resume a paused pipeline."""
        # TODO: Implement backend — module-11/TASK-3
        raise NotImplementedError("module-11/TASK-3 not yet implemented — run /auto-flow execute")

    def cancel(self) -> None:
        """Cancel the running pipeline."""
        # TODO: Implement backend — module-11/TASK-3
        raise NotImplementedError("module-11/TASK-3 not yet implemented — run /auto-flow execute")

    @property
    def status(self) -> PipelineStatus:
        return self._status

    @property
    def commands(self) -> list[CommandSpec]:
        return list(self._commands)
