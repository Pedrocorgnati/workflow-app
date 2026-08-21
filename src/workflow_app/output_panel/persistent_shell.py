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
import select
import signal
import struct
import subprocess
import sys
import termios
import time
from collections.abc import Iterable, Mapping
from pathlib import Path

from PySide6.QtCore import QObject, QSocketNotifier, Signal

logger = logging.getLogger(__name__)

_SHELL = os.environ.get("SHELL", "/bin/bash")

DEBUG_RAW_PTY = os.environ.get("WORKFLOW_APP_DEBUG_PTY", "") == "1"


def linux_descendant_exec_basenames(root_pid: int) -> frozenset[str]:
    """Basenames of descendant processes of ``root_pid`` (Linux ``/proc``).

    The root pid itself (the PTY shell) is omitted: callers look for the
    CLI hosted *inside* the shell (``grok``, ``codex``, ...). Unreadable
    ``/proc`` entries are skipped. Returns empty on non-Linux or if the
    pid has already exited.
    """
    if root_pid <= 0:
        return frozenset()
    seen: set[int] = set()
    queue = [root_pid]
    names: set[str] = set()
    proc_root = Path("/proc")
    while queue:
        pid = queue.pop()
        if pid in seen:
            continue
        seen.add(pid)
        task_dir = proc_root / str(pid) / "task"
        try:
            tid_dirs = list(task_dir.iterdir())
        except OSError:
            tid_dirs = []
        for tid_dir in tid_dirs:
            try:
                text = (tid_dir / "children").read_text(encoding="utf-8")
            except OSError:
                continue
            for token in text.split():
                try:
                    child = int(token)
                except ValueError:
                    continue
                if child not in seen:
                    queue.append(child)
        if pid == root_pid:
            continue
        try:
            comm = (proc_root / str(pid) / "comm").read_text(encoding="utf-8").strip()
        except OSError:
            comm = ""
        if comm:
            names.add(comm)
        try:
            raw = (proc_root / str(pid) / "cmdline").read_bytes().split(b"\x00")[0]
            exe = Path(raw.decode("utf-8", "replace")).name
        except OSError:
            exe = ""
        if exe:
            names.add(exe)
    return frozenset(names)


def cli_name_in_exec_basenames(cli: str, names: Iterable[str]) -> bool:
    """True when ``cli`` matches a process basename (exact, case-insensitive)."""
    needle = (cli or "").strip().lower()
    if not needle:
        return False
    for raw in names:
        if Path(str(raw)).name.lower() == needle:
            return True
    return False


class PersistentShell(QObject):
    """Wraps a long-lived bash/zsh PTY session."""

    output_received = Signal(str)  # raw PTY output chunk

    def __init__(
        self,
        cols: int = 220,
        rows: int = 50,
        cwd: str | None = None,
        shell: str | None = None,
        extra_env: Mapping[str, str] | None = None,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._cols = cols
        self._rows = rows
        self._cwd = cwd
        # Allow callers to force a specific shell binary (e.g. zsh). When None,
        # fall back to the host's $SHELL (or /bin/bash).
        self._shell = shell or _SHELL
        # Extra env merged into the spawned shell's environ. Used by OutputPanel
        # to inject `WF_CHANNEL_OVERRIDE` per-channel so that any Bash subprocess
        # the embedded CLI (Claude/Kimi) spawns inherits the correct channel
        # without each command/wrapper having to set it manually. See
        # ai-forge/rules/workflow-app-listeners.md §2.4.
        self._extra_env: dict[str, str] = dict(extra_env) if extra_env else {}
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
        # Force a UTF-8 locale so bash readline and TUIs (Claude Code, etc)
        # accept multi-byte input (á é í ã ç …). If the host has a non-UTF-8
        # LANG, accented keystrokes are silently dropped by readline.
        for key in ("LANG", "LC_ALL", "LC_CTYPE"):
            val = env.get(key, "")
            if "UTF-8" not in val and "utf8" not in val.lower():
                env[key] = "C.UTF-8"
        # Remove CLAUDECODE so sub-claude CLIs work inside the shell
        env.pop("CLAUDECODE", None)
        # Caller-supplied overrides (channel binding etc). Applied last so
        # they always win over inherited env, including any stale value from
        # a previous parent process.
        for key, val in self._extra_env.items():
            env[key] = val

        try:
            self._proc = subprocess.Popen(
                [self._shell, "--login", "-i"],
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

        logger.info("[PersistentShell] Started %s (pid=%d)", self._shell, self._proc.pid)

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
        if cols == self._cols and rows == self._rows:
            return
        self._cols, self._rows = cols, rows
        if self._master_fd is None:
            return
        winsize = struct.pack("HHHH", rows, cols, 0, 0)
        fcntl.ioctl(self._master_fd, termios.TIOCSWINSZ, winsize)
        deadline = time.monotonic() + 0.05
        while time.monotonic() < deadline:
            ready, _, _ = select.select([self._master_fd], [], [], 0.005)
            if not ready:
                break
            try:
                chunk = os.read(self._master_fd, 65536)
            except OSError:
                break
            if not chunk:
                break
            text = self._utf8_decoder.decode(chunk)
            if text:
                self.output_received.emit(text)
        if self._proc and self._proc.pid:
            try:
                pgid = os.getpgid(self._proc.pid)
                os.killpg(pgid, signal.SIGWINCH)
            except (ProcessLookupError, PermissionError):
                pass

    def pid(self) -> int | None:
        """PID of the live PTY shell, or None if it is not running."""
        if self._proc is None:
            return None
        if self._proc.poll() is not None:
            return None
        return self._proc.pid

    def descendant_exec_basenames(self) -> frozenset[str]:
        """Basenames of processes running *inside* this PTY session."""
        current = self.pid()
        if current is None:
            return frozenset()
        return linux_descendant_exec_basenames(current)

    def hosts_cli(self, cli: str) -> bool:
        """True when a descendant of this PTY matches the CLI basename."""
        return cli_name_in_exec_basenames(cli, self.descendant_exec_basenames())

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
            if DEBUG_RAW_PTY:
                sys.stderr.write(f"[pty-raw len={len(data)}] {data[:120]!r}\n")
            # Use incremental decoder to handle multi-byte UTF-8 sequences
            # that may be split across multiple os.read() calls (e.g. accented chars).
            text = self._utf8_decoder.decode(data)
            if text:
                self.output_received.emit(text)
        except OSError:
            pass
