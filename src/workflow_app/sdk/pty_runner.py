"""
PtyRunner — Subprocess runner using a real PTY (pseudo-terminal).

Why PTY instead of QProcess pipes:
  The claude CLI is a Node.js app. When stdout is a pipe (not a TTY),
  Node.js buffers output until the process ends. With a PTY, it sees a
  real terminal and streams every line immediately — which is what we want.

Design:
  - os.openpty() creates master/slave fd pair
  - subprocess.Popen gets slave as stdin/stdout/stderr
  - QSocketNotifier watches master fd on the main thread (no asyncio, no QThread)
  - QTimer polls for process exit every 100 ms
  - Emits output_received(str) for each chunk, command_completed(str, bool) at end
"""

from __future__ import annotations

import fcntl
import logging
import os
import pathlib
import struct
import subprocess
import termios

from PySide6.QtCore import QObject, QSocketNotifier, QTimer, Signal

logger = logging.getLogger(__name__)

# ─── Helpers (shared with process_runner) ────────────────────────────────── #

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
    try:
        from importlib.util import find_spec  # noqa: PLC0415

        spec = find_spec("claude_agent_sdk")
        if spec and spec.origin:
            bundled = pathlib.Path(spec.origin).parent / "_bundled" / "claude"
            if bundled.exists():
                return str(bundled)
    except Exception:  # noqa: BLE001
        pass
    return "claude"


def _find_systemforge_root() -> str | None:
    candidate = pathlib.Path(__file__).resolve().parent
    while candidate != candidate.parent:
        if (
            (candidate / ".claude" / "commands").is_dir()
            and (candidate / "ai-forge").is_dir()
            and (candidate / "CLAUDE.md").is_file()
        ):
            return str(candidate)
        candidate = candidate.parent
    return None


# ─── PtyRunner ───────────────────────────────────────────────────────────── #


class PtyRunner(QObject):
    """Runs a claude CLI command via a real PTY — output streams immediately.

    Drop-in replacement for ProcessRunner with the key difference that
    the child process sees a TTY, so Node.js doesn't buffer stdout.
    """

    output_received = Signal(str)       # chunk of raw terminal output
    command_completed = Signal(str, bool)  # (command_name, success)
    error_occurred = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._master_fd: int | None = None
        self._proc: subprocess.Popen | None = None
        self._command_name: str = ""
        self._notifier: QSocketNotifier | None = None

        self._poll_timer = QTimer(self)
        self._poll_timer.setInterval(100)
        self._poll_timer.timeout.connect(self._check_exit)

        self._binary: str = _find_claude_binary()
        self._systemforge_root: str | None = _find_systemforge_root()

    # ── Public API ────────────────────────────────────────────────────── #

    def start(
        self,
        command: str,
        model: str = "sonnet",
        permission_mode: str = "autoAccept",
        workspace_dir: str | None = None,
        config_path: str | None = None,
    ) -> None:
        """Launch claude with a PTY so output is not buffered."""
        self._command_name = command if command.startswith("/") else f"/{command}"

        cwd = workspace_dir or self._systemforge_root
        cli_permission = _PERMISSION_MODE_MAP.get(permission_mode, "acceptEdits")
        cli_model = _MODEL_MAP.get(model.lower(), model)

        # Build environment: remove CLAUDECODE, set TERM so claude sees a terminal
        env = os.environ.copy()
        env.pop("CLAUDECODE", None)
        env["TERM"] = "xterm-256color"
        env["COLUMNS"] = "220"
        env["LINES"] = "50"

        args = [self._binary, self._command_name]
        if config_path:
            args.append(config_path)
        args += ["--permission-mode", cli_permission, "--model", cli_model]

        # Create PTY pair
        master_fd, slave_fd = os.openpty()
        self._master_fd = master_fd

        # Set terminal size on the slave so programs behave correctly
        winsize = struct.pack("HHHH", 50, 220, 0, 0)  # rows, cols, x, y
        try:
            fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)
        except OSError:
            pass

        logger.info(
            "[PtyRunner] Starting: %s %s (cwd=%s)",
            self._binary,
            " ".join(args[1:]),
            cwd,
        )

        try:
            self._proc = subprocess.Popen(
                args,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd=cwd,
                env=env,
                close_fds=True,
                start_new_session=True,  # new session so slave becomes controlling tty
            )
        except Exception as exc:  # noqa: BLE001
            os.close(slave_fd)
            os.close(master_fd)
            self._master_fd = None
            msg = f"Falha ao iniciar claude: {exc}"
            logger.error("[PtyRunner] %s", msg)
            self.error_occurred.emit(msg)
            self.command_completed.emit(self._command_name, False)
            return

        # Close slave in the parent (child has its own copy)
        os.close(slave_fd)

        # Make master non-blocking so reads don't stall the main thread
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        # Watch master fd for data (runs on main thread via event loop)
        self._notifier = QSocketNotifier(
            master_fd, QSocketNotifier.Type.Read, self
        )
        self._notifier.activated.connect(self._read_output)

        # Poll for process exit
        self._poll_timer.start()

    def send_user_input(self, text: str) -> None:
        """Write text + newline to the running process PTY."""
        if self._master_fd is not None:
            try:
                os.write(self._master_fd, (text + "\n").encode("utf-8"))
                logger.debug("[PtyRunner] Sent user input: %r", text)
            except OSError as exc:
                logger.warning("[PtyRunner] send_user_input failed: %s", exc)

    def send_raw(self, data: bytes) -> None:
        """Write raw bytes to the PTY (for key forwarding)."""
        if self._master_fd is not None:
            try:
                os.write(self._master_fd, data)
            except OSError as exc:
                logger.warning("[PtyRunner] send_raw failed: %s", exc)

    def terminate(self) -> None:
        """Kill the running process."""
        if self._proc and self._proc.poll() is None:
            logger.info("[PtyRunner] Terminating %s", self._command_name)
            self._proc.terminate()
        self._teardown()

    @property
    def command_name(self) -> str:
        return self._command_name

    # ── Private ───────────────────────────────────────────────────────── #

    def _read_output(self) -> None:
        """Called by QSocketNotifier when data is available on master fd."""
        if self._master_fd is None:
            return
        try:
            data = os.read(self._master_fd, 4096)
            text = data.decode("utf-8", errors="replace")
            if text:
                self.output_received.emit(text)
        except OSError:
            # EIO when slave closes (process exited), EAGAIN when no data
            pass

    def _check_exit(self) -> None:
        """QTimer callback: detect when the subprocess exits."""
        if self._proc is None:
            return
        rc = self._proc.poll()
        if rc is None:
            return  # still running

        self._poll_timer.stop()

        # Drain any remaining buffered output
        if self._master_fd is not None:
            try:
                while True:
                    data = os.read(self._master_fd, 4096)
                    if not data:
                        break
                    text = data.decode("utf-8", errors="replace")
                    self.output_received.emit(text)
            except OSError:
                pass

        success = rc == 0
        logger.info(
            "[PtyRunner] Exited: %s rc=%d success=%s",
            self._command_name,
            rc,
            success,
        )
        self._teardown()
        self.command_completed.emit(self._command_name, success)

    def _teardown(self) -> None:
        if self._notifier is not None:
            self._notifier.setEnabled(False)
            self._notifier = None
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None
