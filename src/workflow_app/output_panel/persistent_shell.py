"""
PersistentShell — A permanent bash/zsh PTY session embedded in the app.

Always running. Key events from TerminalWidget go here when no pipeline
runner is active. When a pipeline runner is active, keys go to it instead.
The shell is what the user sees as "the terminal".
"""

from __future__ import annotations

import codecs
import fcntl
import logging
import os
import struct
import subprocess
import termios

from PySide6.QtCore import QObject, QSocketNotifier, Signal

logger = logging.getLogger(__name__)

_SHELL = os.environ.get("SHELL", "/bin/bash")


class PersistentShell(QObject):
    """Wraps a long-lived bash/zsh PTY session."""

    output_received = Signal(str)  # raw PTY output chunk

    def __init__(self, cols: int = 220, rows: int = 50, cwd: str | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cols = cols
        self._rows = rows
        self._cwd = cwd
        self._master_fd: int | None = None
        self._proc: subprocess.Popen | None = None
        self._notifier: QSocketNotifier | None = None
        self._utf8_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def start(self) -> None:
        """Spawn the shell process."""
        # Reset incremental decoder on each (re)start
        self._utf8_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        master_fd, slave_fd = os.openpty()
        self._master_fd = master_fd

        # Set terminal size
        winsize = struct.pack("HHHH", self._rows, self._cols, 0, 0)
        try:
            fcntl.ioctl(slave_fd, termios.TIOCSWINSZ, winsize)
        except OSError:
            pass

        env = os.environ.copy()
        env["TERM"] = "xterm-256color"
        env["COLORTERM"] = "truecolor"
        env["COLUMNS"] = str(self._cols)
        env["LINES"] = str(self._rows)
        # Remove CLAUDECODE so sub-claude CLIs work inside the shell
        env.pop("CLAUDECODE", None)

        try:
            self._proc = subprocess.Popen(
                [_SHELL, "--login", "-i"],
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                cwd=self._cwd,
                env=env,
                close_fds=True,
                start_new_session=True,
            )
        except Exception as exc:  # noqa: BLE001
            os.close(slave_fd)
            os.close(master_fd)
            self._master_fd = None
            logger.error("[PersistentShell] Failed to spawn shell: %s", exc)
            return

        os.close(slave_fd)

        # Non-blocking reads
        flags = fcntl.fcntl(master_fd, fcntl.F_GETFL)
        fcntl.fcntl(master_fd, fcntl.F_SETFL, flags | os.O_NONBLOCK)

        self._notifier = QSocketNotifier(master_fd, QSocketNotifier.Type.Read, self)
        self._notifier.activated.connect(self._read_output)

        logger.info("[PersistentShell] Started %s (pid=%d)", _SHELL, self._proc.pid)

    def send_raw(self, data: bytes) -> None:
        """Write raw bytes to the shell PTY (key forwarding)."""
        if self._master_fd is not None:
            try:
                os.write(self._master_fd, data)
            except OSError as exc:
                logger.warning("[PersistentShell] send_raw failed: %s", exc)

    def send_text(self, text: str) -> None:
        """Write text (no newline) to the shell PTY."""
        self.send_raw(text.encode("utf-8", errors="replace"))

    def run_command(self, command: str) -> None:
        """Type a command + Enter into the shell."""
        self.send_raw((command + "\r").encode("utf-8"))

    def resize(self, cols: int, rows: int) -> None:
        """Resize the PTY."""
        self._cols = cols
        self._rows = rows
        if self._master_fd is None:
            return
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        try:
            fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, winsize)
        except OSError:
            pass

    def terminate(self) -> None:
        if self._notifier:
            self._notifier.setEnabled(False)
            self._notifier = None
        if self._proc and self._proc.poll() is None:
            self._proc.terminate()
        if self._master_fd is not None:
            try:
                os.close(self._master_fd)
            except OSError:
                pass
            self._master_fd = None

    # ── Private ───────────────────────────────────────────────────────── #

    def _read_output(self) -> None:
        if self._master_fd is None:
            return
        try:
            data = os.read(self._master_fd, 65536)
            # Use incremental decoder to handle multi-byte UTF-8 sequences
            # that may be split across multiple os.read() calls (e.g. accented chars).
            text = self._utf8_decoder.decode(data)
            if text:
                self.output_received.emit(text)
        except OSError:
            pass
