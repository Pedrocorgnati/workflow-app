"""
SDKWorker — QThread with internal asyncio event loop for SDK execution.

Covers:
  TASK-1: SDKWorker class with asyncio bridge (streaming run_command)
  TASK-3: Bidirectional interactive session (_execute_interactive)
  TASK-4: ToolUseHookMixin integration and set_execution_context()

Design:
  - Completely isolates asyncio from Qt's event loop (ADR-002).
  - All communication with the Qt main thread is via Qt signals.
  - NEVER call Qt methods directly inside async coroutines.
    Signal.emit() is thread-safe in Qt6/PySide6 (queued connection).
  - Each SDKWorker instance is single-use (start() called once).
    PipelineManager keeps a reference in self._workers to prevent GC.
"""

from __future__ import annotations

import asyncio

from PySide6.QtCore import QThread, Signal

from workflow_app.domain import CommandSpec, InteractionType, ModelType
from workflow_app.sdk.tool_use_hooks import ToolUseHookMixin

VALID_PERMISSION_MODES = frozenset({"acceptEdits", "autoAccept", "manual"})


class SDKWorker(QThread, ToolUseHookMixin):
    """QThread that creates and manages an internal asyncio event loop.

    Consumes SDKAdapter.run_command() asynchronously and emits output chunks
    via Qt signals to the main thread without blocking the UI.
    """

    # Emitted for each text chunk received from the SDK
    output_received = Signal(str)
    # Emitted on completion: (command_name, success)
    command_completed = Signal(str, bool)
    # Emitted when an exception occurs during execution
    error_occurred = Signal(str)
    # Emitted when the SDK requests interactive input (prompt text)
    interactive_prompt = Signal(str)

    def __init__(
        self,
        command_spec: CommandSpec,
        workspace_dir: str,
        permission_mode: str = "acceptEdits",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self._command_spec = command_spec
        self._workspace_dir = workspace_dir
        if permission_mode not in VALID_PERMISSION_MODES:
            raise ValueError(
                f"permission_mode inválido: {permission_mode!r}. "
                f"Valores aceitos: {sorted(VALID_PERMISSION_MODES)}"
            )
        self._permission_mode = permission_mode
        self._sdk_adapter: object | None = None
            # Queue for user input in interactive sessions.
        # Created before asyncio.run() so it is compatible with the new loop.
        self._user_input_queue: asyncio.Queue[str] = asyncio.Queue()
        # Reference to the running asyncio event loop (set in _execute).
        # Needed for thread-safe queue operations from the Qt main thread.
        self._loop: asyncio.AbstractEventLoop | None = None
        # Tool start times for hook timing (keyed by tool_name)
        self._tool_start_times: dict[str, float | None] = {}

    # ── Public API ────────────────────────────────────────────────────── #

    def set_sdk_adapter(self, adapter: object) -> None:
        """Inject SDKAdapter before starting the worker."""
        self._sdk_adapter = adapter

    def set_execution_context(
        self,
        session_factory,
        pipeline_id: int,
        command_exec_id: int | None,
        signal_bus_instance,
    ) -> None:
        """Inject context needed for ToolUse hooks (optional).

        When not called, hook methods catch AttributeError silently and are no-ops.
        """
        self._session_factory = session_factory
        self._pipeline_id = pipeline_id
        self._command_exec_id = command_exec_id
        self._signal_bus = signal_bus_instance

    def send_user_input(self, text: str) -> None:
        """Called by the Qt thread to send user input to the asyncio loop.

        Uses call_soon_threadsafe() so the queue operation is scheduled safely
        on the asyncio event loop running in this QThread.
        Forwards to both the internal queue (legacy) and the SDK adapter
        (for AskUserQuestion can_use_tool intercept).
        """
        # Forward to SDK adapter first (handles AskUserQuestion via can_use_tool)
        self._sdk_adapter.send_user_input(text)
        # Also feed the queue for _execute_interactive compatibility
        if self._loop is not None and self._loop.is_running():
            self._loop.call_soon_threadsafe(self._user_input_queue.put_nowait, text)
        else:
            self._user_input_queue.put_nowait(text)

    # ── QThread interface ─────────────────────────────────────────────── #

    def run(self) -> None:
        """Thread entry point. Creates and runs a dedicated asyncio event loop.

        Remove CLAUDECODE do ambiente antes de spawnar o SDK para evitar o erro
        "Claude Code cannot be launched inside another Claude Code session".
        A variável é restaurada ao final para não afetar o processo pai.
        """
        import os
        _saved = os.environ.pop("CLAUDECODE", None)
        try:
            asyncio.run(self._execute())
        finally:
            if _saved is not None:
                os.environ["CLAUDECODE"] = _saved

    # ── Asyncio coroutines ────────────────────────────────────────────── #

    async def _execute(self) -> None:
        """Route to streaming or interactive execution based on interaction_type."""
        self._loop = asyncio.get_running_loop()
        command_name = self._command_spec.name
        is_interactive = (
            self._command_spec.interaction_type == InteractionType.INTERACTIVE
        )
        try:
            if is_interactive:
                await self._execute_interactive(command_name)
            else:
                await self._execute_streaming(command_name)
        except asyncio.TimeoutError:
            # Timeout message already emitted by _wait_for_user_input;
            # also emit here so patched versions still produce a message.
            self.error_occurred.emit(
                "Timeout de interação: nenhuma resposta em 300s"
            )
            self.command_completed.emit(command_name, False)
        except BaseException as exc:  # noqa: BLE001
            self.error_occurred.emit(str(exc))
            self.command_completed.emit(command_name, False)
        else:
            self.command_completed.emit(command_name, True)

    async def _execute_streaming(self, command_name: str) -> None:
        """Iterate chunks and emit output_received for each string chunk."""
        model_type = ModelType(self._command_spec.model.value.lower())
        async for chunk in self._sdk_adapter.run_command(
            command=command_name,
            model=model_type,
            workspace_dir=self._workspace_dir,
            permission_mode=self._permission_mode,
        ):
            if isinstance(chunk, str):
                self.output_received.emit(chunk)
            elif hasattr(chunk, "type"):
                await self._handle_tool_event(chunk)

    async def _execute_interactive(self, command_name: str) -> None:
        """Bidirectional: detect interactive prompts and wait for user input."""
        model_type = ModelType(self._command_spec.model.value.lower())
        async for chunk in self._sdk_adapter.run_command(
            command=command_name,
            model=model_type,
            workspace_dir=self._workspace_dir,
            permission_mode=self._permission_mode,
        ):
            if isinstance(chunk, str):
                self.output_received.emit(chunk)
            elif hasattr(chunk, "type") and chunk.type == "interactive_prompt":
                # Notify UI to show input widget
                self.interactive_prompt.emit(getattr(chunk, "text", ""))
                # Suspend until user responds (or timeout)
                user_text = await self._wait_for_user_input()
                # Forward to SDK adapter
                if hasattr(self._sdk_adapter, "send_user_input"):
                    self._sdk_adapter.send_user_input(user_text)
            elif hasattr(chunk, "type"):
                await self._handle_tool_event(chunk)

    async def _wait_for_user_input(self) -> str:
        """Wait up to 300s for user input via the asyncio queue."""
        try:
            text = await asyncio.wait_for(
                self._user_input_queue.get(),
                timeout=300.0,
            )
        except asyncio.TimeoutError:
            self.error_occurred.emit(
                "Timeout de interação: nenhuma resposta em 300s"
            )
            raise
        return text

    async def _handle_tool_event(self, event) -> None:
        """Process tool_use_start/tool_use_end events from the SDK."""
        if not hasattr(event, "type"):
            return
        tool_name = getattr(event, "tool_name", "unknown")
        if event.type == "tool_use_start":
            t = self.on_pre_tool_use(
                tool_name=tool_name,
                input_summary=str(getattr(event, "input", ""))[:200],
            )
            self._tool_start_times[tool_name] = t
        elif event.type == "tool_use_end":
            start = self._tool_start_times.get(tool_name)
            self.on_post_tool_use(
                tool_name=tool_name,
                output_summary=str(getattr(event, "output", ""))[:200],
                start_time=start,
            )
