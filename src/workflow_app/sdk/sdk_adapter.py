"""
SDKAdapter — Abstraction layer over claude-agent-sdk (module-08).

Covers:
  TASK-1: Core streaming adapter (run_command, cancel, hooks)
  TASK-2: Auth checks (check_sdk_available, check_auth, ensure_sdk_ready)
  TASK-3: _StopHook — emits sdk_command_stopped on agent termination
  TASK-4: _NotificationHook — emits agent_status_updated on status changes

Risco CRITICO: The exact API of claude-agent-sdk must be verified on PyPI.
This implementation assumes query() with include_partial_messages=True.
If the API differs, adapt while keeping SDKAdapter's public interface intact.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from collections.abc import AsyncIterator
from importlib.util import find_spec

from workflow_app.domain import ModelType
from workflow_app.errors import (
    SDKExecutionError,
    SDKNotAuthenticatedError,
    SDKNotAvailableError,
)
from workflow_app.signal_bus import signal_bus

logger = logging.getLogger(__name__)

# ─── Constants ───────────────────────────────────────────────────────────── #

# Mapping ModelType → SDK model string
_MODEL_STRINGS: dict[ModelType, str] = {
    ModelType.HAIKU: "claude-haiku-4-5",
    ModelType.SONNET: "claude-sonnet-4-6",
    ModelType.OPUS: "claude-opus-4-6",
}

# Supported permission modes (internal names used throughout the app)
PERMISSION_ACCEPT_EDITS = "acceptEdits"
PERMISSION_AUTO_ACCEPT = "autoAccept"
PERMISSION_MANUAL = "manual"

# Translate internal permission mode names to valid CLI values
# CLI valid choices: acceptEdits, bypassPermissions, default, dontAsk, plan, auto
_PERMISSION_MODE_MAP: dict[str, str] = {
    "acceptEdits": "acceptEdits",
    "autoAccept": "bypassPermissions",
    "manual": "default",
    # pass-through for any already-valid CLI value
    "bypassPermissions": "bypassPermissions",
    "default": "default",
    "dontAsk": "dontAsk",
    "plan": "plan",
    "auto": "auto",
}

# Notification types from claude-agent-sdk
_NOTIFICATION_TOOL_USE = "tool_use"
_NOTIFICATION_THINKING = "thinking"
_NOTIFICATION_RESPONSE = "response"
_NOTIFICATION_UNKNOWN = "unknown"


# ─── Hooks ───────────────────────────────────────────────────────────────── #


class _StopHook:
    """
    Programmatic hook for the Stop event from claude-agent-sdk.

    Called by the SDK when the agent terminates voluntarily.
    Emits sdk_command_stopped via SignalBus singleton.

    NOTE: The exact hook interface depends on the SDK version.
    Possible interfaces:
      - client.add_hook("stop", callback)
      - client.on_stop = callback
    """

    def __init__(self, command_name: str, start_time: float) -> None:
        self._command_name = command_name
        self._start_time = start_time

    def __call__(self, exit_code: int = 0, **kwargs) -> None:
        """Called by the SDK on agent termination."""
        duration = time.monotonic() - self._start_time

        if exit_code == 0:
            logger.info(
                "[StopHook] Command '%s' completed normally in %.2fs",
                self._command_name,
                duration,
            )
        else:
            logger.error(
                "[StopHook] Command '%s' terminated with error (code %d) in %.2fs",
                self._command_name,
                exit_code,
                duration,
            )

        signal_bus.sdk_command_stopped.emit(self._command_name, exit_code)


class _NotificationHook:
    """
    Programmatic hook for the Notification event from claude-agent-sdk.

    Called by the SDK with agent status during execution (tool_use, thinking,
    response). Purely informational — does not interrupt or alter the flow.

    NOTE: Exact notification format depends on the SDK version.
    Tries multiple attributes for robustness.
    """

    def __call__(self, notification, **kwargs) -> None:
        """
        Processes SDK notification and emits agent_status_updated via SignalBus.

        Args:
            notification: Notification object from SDK (format uncertain).
        """
        try:
            status = self._parse_notification(notification)
            signal_bus.agent_status_updated.emit(status)
            logger.debug("[NotificationHook] Status: %s", status)
        except Exception as exc:
            # Never propagate exception from informational hook
            logger.warning(
                "[NotificationHook] Failed to process notification: %s", exc
            )

    @staticmethod
    def _parse_notification(notification) -> str:
        """
        Extracts status string from SDK notification.

        Tries multiple attributes/formats for robustness.

        Returns:
            Status string for UI display.
        """
        # Try direct "type" attribute
        notif_type = getattr(notification, "type", None)

        if notif_type == _NOTIFICATION_TOOL_USE:
            tool_name = (
                getattr(notification, "tool_name", None)
                or getattr(notification, "name", None)
                or "desconhecida"
            )
            return f"tool_use: {tool_name}"

        if notif_type == _NOTIFICATION_THINKING:
            return "thinking"

        if notif_type == _NOTIFICATION_RESPONSE:
            return "response"

        # Fallback: try as dict
        if isinstance(notification, dict):
            notif_type = notification.get("type", _NOTIFICATION_UNKNOWN)
            if notif_type == _NOTIFICATION_TOOL_USE:
                tool = notification.get("tool_name", "desconhecida")
                return f"tool_use: {tool}"
            return notif_type

        # Last resort fallback
        return str(notif_type) if notif_type else _NOTIFICATION_UNKNOWN


# ─── SDKAdapter ──────────────────────────────────────────────────────────── #


class SDKAdapter:
    """
    Wraps claude-agent-sdk (PyPI) for use in Workflow App.

    Clean interface for SDKWorker (module-09). Should not be instantiated
    directly in the UI — use via SDKWorker (QThread).

    Risco: claude-agent-sdk API must be validated on PyPI before
    implementation. This class assumes query() interface with
    include_partial_messages=True.
    """

    def __init__(self) -> None:
        self._is_running: bool = False
        self._current_command: str | None = None
        self._cancel_event: asyncio.Event = asyncio.Event()
        self._sdk_client = None  # lazily initialized in _get_client()
        self._pending_permission: asyncio.Future | None = None
        self._pending_user_input: asyncio.Future | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    # ── Public properties ─────────────────────────────────────────────── #

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def current_command(self) -> str | None:
        return self._current_command

    # ── Auth checks (TASK-2) ─────────────────────────────────────────── #

    def check_sdk_available(self) -> bool:
        """
        Checks if claude-agent-sdk can be imported.

        Uses importlib.util.find_spec to avoid polluting sys.modules.

        Returns:
            True if the package is available, False otherwise.
        """
        return find_spec("claude_agent_sdk") is not None

    def check_auth(self) -> bool:
        """
        Checks if Claude CLI is authenticated.

        Strategy: runs `claude --version` via subprocess.
        If it returns code 0, the CLI is installed and presumably authenticated.

        NOTE: claude-agent-sdk may have its own auth check method.
        Check documentation and use if available.

        Returns:
            True if authenticated, False otherwise.
        """
        try:
            result = subprocess.run(
                ["claude", "--version"],
                capture_output=True,
                timeout=5,
                check=False,
            )
            return result.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False

    def ensure_sdk_ready(self) -> None:
        """
        Calls check_sdk_available() and check_auth() in sequence.
        Raises error if any check fails.

        Should be called at startup before opening the main window.

        Raises:
            SDKNotAvailableError: SDK not installed.
            SDKNotAuthenticatedError: Claude not authenticated.
        """
        if not self.check_sdk_available():
            raise SDKNotAvailableError(
                "claude-agent-sdk não encontrado. Instale com: pip install claude-agent-sdk"
            )
        if not self.check_auth():
            raise SDKNotAuthenticatedError(
                "Claude não autenticado. Execute: claude auth login"
            )

    # ── Main API (TASK-1) ─────────────────────────────────────────────── #

    async def run_command(
        self,
        command: str,
        model: ModelType,
        permission_mode: str = PERMISSION_ACCEPT_EDITS,
        workspace_dir: str | None = None,
    ) -> AsyncIterator[str]:
        """
        Executes a slash command via claude-agent-sdk and streams chunks.

        Args:
            command: Command name without slash (e.g. "prd-create") or with slash.
            model: ModelType (HAIKU/SONNET/OPUS).
            permission_mode: "acceptEdits" | "autoAccept" | "manual".
            workspace_dir: Working directory for Claude (docs_root or workspace_root).

        Yields:
            str: Each text chunk received from the SDK.

        Raises:
            SDKExecutionError: If the SDK raises an exception during execution.
        """
        cmd_str = command if command.startswith("/") else f"/{command}"
        model_str = _MODEL_STRINGS.get(model, "claude-sonnet-4-5")

        self._is_running = True
        self._current_command = cmd_str
        self._cancel_event.clear()
        self._pending_permission = None
        self._loop = asyncio.get_running_loop()
        start_time = time.monotonic()

        logger.info(
            "[SDKAdapter] Starting command=%s model=%s permission=%s ts=%s",
            cmd_str,
            model_str,
            permission_mode,
            time.strftime("%Y-%m-%dT%H:%M:%S"),
        )

        try:
            async for chunk in self._stream_query(
                command=cmd_str,
                model_str=model_str,
                permission_mode=permission_mode,
                workspace_dir=workspace_dir,
            ):
                if self._cancel_event.is_set():
                    logger.info("[SDKAdapter] Execution cancelled: %s", cmd_str)
                    break
                yield chunk

        except Exception as exc:
            duration = time.monotonic() - start_time
            logger.error(
                "[SDKAdapter] Error in %s after %.2fs: %s", cmd_str, duration, exc
            )
            raise SDKExecutionError(
                f"Erro ao executar {cmd_str}: {exc}"
            ) from exc
        finally:
            duration = time.monotonic() - start_time
            logger.info(
                "[SDKAdapter] End: command=%s duration=%.2fs", cmd_str, duration
            )
            self._is_running = False
            self._current_command = None

    def cancel_current(self) -> None:
        """
        Signals cancellation of the ongoing execution.
        The iterator checks the event and stops on the next yield.
        Also rejects any pending permission future to prevent deadlock.
        """
        if self._is_running:
            logger.info(
                "[SDKAdapter] cancel_current() called for: %s", self._current_command
            )
            self._cancel_event.set()
            # Reject pending permission to avoid deadlock
            fut = self._pending_permission
            if fut is not None and not fut.done():
                if self._loop is not None and self._loop.is_running():
                    self._loop.call_soon_threadsafe(fut.set_result, False)
                else:
                    try:
                        fut.set_result(False)
                    except Exception:
                        pass
            # Also cancel any pending user input future
            fut2 = self._pending_user_input
            if fut2 is not None and not fut2.done():
                if self._loop is not None and self._loop.is_running():
                    self._loop.call_soon_threadsafe(fut2.cancel)
                else:
                    try:
                        fut2.cancel()
                    except Exception:
                        pass

    def respond_to_permission(self, granted: bool) -> None:
        """
        Resolves the pending permission future.
        Called from the UI/main thread after user approves or rejects.

        Args:
            granted: True to allow the SDK action, False to reject.
        """
        fut = self._pending_permission
        if fut is not None and not fut.done():
            if self._loop is not None and self._loop.is_running():
                self._loop.call_soon_threadsafe(fut.set_result, granted)
            else:
                try:
                    fut.set_result(granted)
                except Exception:
                    pass

    def send_user_input(self, text: str) -> None:
        """
        Sends user input to a pending AskUserQuestion call.
        Called from the UI/main thread when the user submits text in the input field.

        Args:
            text: User's answer to Claude's question.
        """
        fut = self._pending_user_input
        if fut is not None and not fut.done():
            if self._loop is not None and self._loop.is_running():
                self._loop.call_soon_threadsafe(fut.set_result, text)
            else:
                try:
                    fut.set_result(text)
                except Exception:
                    pass

    # ── Internal helpers ─────────────────────────────────────────────── #

    async def _stream_query(
        self,
        command: str,
        model_str: str,
        permission_mode: str,
        workspace_dir: str | None,
    ) -> AsyncIterator[str]:
        """
        Executa o comando via claude_agent_sdk.query() e faz streaming de chunks.

        cwd deve apontar para a raiz da systemForge (onde está .claude/commands/)
        para que o Claude CLI encontre os slash commands ao processar o prompt.
        """
        from claude_agent_sdk import (  # noqa: PLC0415
            AssistantMessage,
            ClaudeAgentOptions,
            HookMatcher,
            PermissionResultAllow,
            PermissionResultDeny,
            ResultMessage,
            TextBlock,
            query,
        )
        from claude_agent_sdk.types import StreamEvent  # noqa: PLC0415

        start_time = time.monotonic()

        # ── can_use_tool: intercepts AskUserQuestion for interactive commands ─ #

        async def _can_use_tool(
            tool_name: str, input_data: dict, context
        ) -> PermissionResultAllow | PermissionResultDeny:
            if tool_name == "AskUserQuestion":
                question = input_data.get("question", "?")
                options_list = input_data.get("options", [])
                q_text = f"\n❓ {question}"
                if options_list:
                    def _opt_label(o) -> str:
                        if isinstance(o, dict):
                            return o.get("label") or o.get("value") or str(o)
                        return str(o)
                    q_text += "\n" + "\n".join(f"  • {_opt_label(o)}" for o in options_list)
                q_text += "\n"
                signal_bus.output_chunk_received.emit(q_text)
                signal_bus.interactive_input_requested.emit()
                loop = asyncio.get_running_loop()
                self._pending_user_input = loop.create_future()
                try:
                    answer = await self._pending_user_input
                    return PermissionResultAllow(
                        updated_input={**input_data, "answer": answer}
                    )
                finally:
                    self._pending_user_input = None
            # Allow all other tools by default
            return PermissionResultAllow()

        # ── Prompt as AsyncIterable (required for can_use_tool) ─────────── #

        async def _command_iter():
            yield {
                "type": "user",
                "session_id": "",
                "message": {"role": "user", "content": command},
                "parent_tool_use_id": None,
            }

        cli_permission_mode = _PERMISSION_MODE_MAP.get(permission_mode, "acceptEdits")

        # Resolve the working directory: prefer workspace_dir, otherwise find the
        # SystemForge root (the directory that contains .claude/commands/) by
        # traversing up from this file.  This ensures the CLI can locate slash
        # commands regardless of how the app is launched.
        effective_cwd: str | None = workspace_dir or None
        if not effective_cwd:
            import pathlib
            candidate = pathlib.Path(__file__).resolve().parent
            while candidate != candidate.parent:
                if (
                    (candidate / ".claude" / "commands").is_dir()
                    and (candidate / "CLAUDE.md").is_file()
                ):
                    effective_cwd = str(candidate)
                    break
                candidate = candidate.parent

        # ── PostToolUse hook: REQUIRED to keep stdin open ─────────────────── #
        #
        # query.py `wait_for_result_and_end_input()` only keeps stdin open if
        # `self.sdk_mcp_servers OR self.hooks` is truthy.  Without hooks, stdin
        # closes immediately after writing the user message, breaking the
        # can_use_tool round-trip (CLI sends control_request but stdin is gone).
        #
        # The hook MUST return {"continue_": True} — the SDK converts it to
        # {"continue": true} via _convert_hook_output_for_cli.  Returning {}
        # results in {"continue": false}, causing the CLI to stop early.

        async def _post_tool_hook(
            input_data: dict, tool_use_id: str, context: dict
        ) -> dict:
            return {"continue_": True}

        hooks = {
            "PostToolUse": [HookMatcher(matcher=".*", hooks=[_post_tool_hook])],
        }

        def _stderr_callback(line: str) -> None:
            logger.warning("[SDKAdapter] CLI stderr: %s", line)

        options = ClaudeAgentOptions(
            cwd=effective_cwd,
            model=model_str,
            permission_mode=cli_permission_mode,
            include_partial_messages=True,
            can_use_tool=_can_use_tool,
            hooks=hooks,
            # Load project-level settings so the CLI can find .claude/commands/ and CLAUDE.md.
            setting_sources=["project"],
            # Use preset (not None) so subprocess_cli.py does NOT pass --system-prompt ""
            # which would wipe CLAUDE.md loaded by setting_sources.
            # With type="preset" and no "append" key, no --system-prompt flag is emitted.
            system_prompt={"type": "preset", "preset": "claude_code"},
            stderr=_stderr_callback,
        )

        # Track if we received any streaming text to avoid duplicating from ResultMessage
        _got_text = False

        try:
            async for message in query(prompt=_command_iter(), options=options):
                if self._cancel_event.is_set():
                    break

                if isinstance(message, StreamEvent):
                    # Real-time text delta from the API stream
                    event = message.event
                    if event.get("type") == "content_block_delta":
                        delta = event.get("delta", {})
                        if delta.get("type") == "text_delta":
                            text = delta.get("text", "")
                            if text:
                                _got_text = True
                                yield text

                elif isinstance(message, AssistantMessage):
                    # Final consolidated assistant message — skip if already streamed
                    if not _got_text:
                        for block in message.content:
                            if isinstance(block, TextBlock) and block.text:
                                _got_text = True
                                yield block.text

                elif isinstance(message, ResultMessage):
                    duration = time.monotonic() - start_time
                    logger.info(
                        "[SDKAdapter] ResultMessage: stop_reason=%s duration=%.2fs",
                        message.stop_reason,
                        duration,
                    )
                    # Yield result summary if we got no streaming text
                    if message.result and not _got_text:
                        yield message.result
                    signal_bus.sdk_command_stopped.emit(command, 0)

        except Exception as exc:
            signal_bus.sdk_command_stopped.emit(command, 1)
            raise exc
