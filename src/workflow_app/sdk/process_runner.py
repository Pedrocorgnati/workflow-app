"""
ProcessRunner — QProcess-based runner for claude CLI commands.

Replaces the SDKWorker + SDKAdapter + asyncio stack with a direct
QProcess invocation of the bundled claude binary.

Design:
  - No asyncio, no QThread — just QProcess signals on the main thread.
  - readyReadStandardOutput → output_received (streamed in real-time)
  - finished → command_completed
  - write() → stdin for interactive prompts (AskUserQuestion)
"""

from __future__ import annotations

import logging
import pathlib

from PySide6.QtCore import QObject, QProcess, QProcessEnvironment, Signal

logger = logging.getLogger(__name__)

# ─── Helpers ─────────────────────────────────────────────────────────────── #

_PERMISSION_MODE_MAP: dict[str, str] = {
    "acceptEdits": "acceptEdits",
    "autoAccept": "bypassPermissions",
    "manual": "default",
    "bypassPermissions": "bypassPermissions",
    "default": "default",
}

_MODEL_MAP: dict[str, str] = {
    "haiku": "claude-haiku-4-5",
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-6",
}


def _find_claude_binary() -> str:
    """Return path to bundled claude binary, or 'claude' for PATH fallback."""
    try:
        from importlib.util import find_spec  # noqa: PLC0415

        spec = find_spec("claude_agent_sdk")
        if spec and spec.origin:
            bundled = pathlib.Path(spec.origin).parent / "_bundled" / "claude"
            if bundled.exists():
                logger.debug("[ProcessRunner] Using bundled claude: %s", bundled)
                return str(bundled)
    except Exception:  # noqa: BLE001
        pass
    logger.debug("[ProcessRunner] Using 'claude' from PATH")
    return "claude"


def _find_systemforge_root() -> str | None:
    """Walk up from this file to find the directory containing .claude/commands/."""
    candidate = pathlib.Path(__file__).resolve().parent
    while candidate != candidate.parent:
        if (
            (candidate / ".claude" / "commands").is_dir()
            and (candidate / "CLAUDE.md").is_file()
        ):
            return str(candidate)
        candidate = candidate.parent
    return None


# ─── ProcessRunner ───────────────────────────────────────────────────────── #


class ProcessRunner(QObject):
    """Runs a claude CLI command via QProcess, streaming output in real-time.

    Usage::

        runner = ProcessRunner()
        runner.output_received.connect(my_slot)
        runner.command_completed.connect(on_done)
        runner.start("/project-json", model="sonnet", permission_mode="autoAccept")
        # later: runner.send_user_input("my answer")
    """

    # Emitted for each stdout/stderr chunk received
    output_received = Signal(str)
    # Emitted when the process finishes: (command_name, success)
    command_completed = Signal(str, bool)
    # Emitted when QProcess itself fails to start
    error_occurred = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._process = QProcess(self)
        # Merge stderr into stdout so everything appears in the terminal
        self._process.setProcessChannelMode(
            QProcess.ProcessChannelMode.MergedChannels
        )
        self._process.readyReadStandardOutput.connect(self._on_output)
        self._process.finished.connect(self._on_finished)
        self._process.errorOccurred.connect(self._on_process_error)

        self._command_name: str = ""
        self._binary: str = _find_claude_binary()
        self._systemforge_root: str | None = _find_systemforge_root()

    # ── Public API ────────────────────────────────────────────────────── #

    def start(
        self,
        command: str,
        model: str = "sonnet",
        permission_mode: str = "autoAccept",
        workspace_dir: str | None = None,
    ) -> None:
        """Launch claude with the given command.

        Args:
            command: Slash command, e.g. "/project-json" or "project-json".
            model: "haiku" | "sonnet" | "opus" (or full model ID).
            permission_mode: "autoAccept" | "acceptEdits" | "manual".
            workspace_dir: Override CWD (defaults to SystemForge root).
        """
        self._command_name = command if command.startswith("/") else f"/{command}"

        cwd = workspace_dir or self._systemforge_root
        if cwd:
            self._process.setWorkingDirectory(cwd)

        # Remove CLAUDECODE so the child process doesn't refuse to start
        env = QProcessEnvironment.systemEnvironment()
        env.remove("CLAUDECODE")
        self._process.setProcessEnvironment(env)

        cli_permission = _PERMISSION_MODE_MAP.get(permission_mode, "acceptEdits")
        cli_model = _MODEL_MAP.get(model.lower(), model)

        args = [
            self._command_name,
            "--permission-mode", cli_permission,
            "--model", cli_model,
        ]

        logger.info(
            "[ProcessRunner] Starting: %s %s (cwd=%s)",
            self._binary,
            " ".join(args),
            cwd,
        )
        self._process.start(self._binary, args)

    def send_user_input(self, text: str) -> None:
        """Write text + newline to the process stdin (answers interactive prompts)."""
        if self._process.state() == QProcess.ProcessState.Running:
            self._process.write((text + "\n").encode("utf-8"))
            logger.debug("[ProcessRunner] Sent user input: %r", text)

    def terminate(self) -> None:
        """Terminate the running process."""
        if self._process.state() != QProcess.ProcessState.NotRunning:
            logger.info("[ProcessRunner] Terminating %s", self._command_name)
            self._process.terminate()

    @property
    def command_name(self) -> str:
        return self._command_name

    # ── Private slots ─────────────────────────────────────────────────── #

    def _on_output(self) -> None:
        data = bytes(self._process.readAllStandardOutput())
        text = data.decode("utf-8", errors="replace")
        if text:
            self.output_received.emit(text)

    def _on_finished(self, exit_code: int, _exit_status: object) -> None:
        success = exit_code == 0
        logger.info(
            "[ProcessRunner] Finished: %s exit_code=%d success=%s",
            self._command_name,
            exit_code,
            success,
        )
        self.command_completed.emit(self._command_name, success)

    def _on_process_error(self, error: QProcess.ProcessError) -> None:
        msg = self._process.errorString()
        logger.error("[ProcessRunner] QProcess error %s: %s", error, msg)
        self.error_occurred.emit(msg)
        # Also emit command_completed(False) so the pipeline can advance
        self.command_completed.emit(self._command_name, False)
