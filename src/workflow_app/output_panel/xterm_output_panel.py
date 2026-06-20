import os
import shutil
import time
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget

from workflow_app.app_instance import APP_SESSION_ID
from .output_panel import _FATAL_PATTERNS, _find_systemforge_root
from .persistent_shell import PersistentShell
from workflow_app.signal_bus import signal_bus
from workflow_app.terminal_helpers import HELPER_COMMANDS, is_helper_command

ASSETS_DIR = Path(__file__).resolve().parents[3] / "assets" / "xterm"


def _resolve_zsh() -> str:
    """Locate the zsh binary, falling back to common install paths.

    Returns the first usable zsh path. As a last resort returns the host
    $SHELL so the terminal still spawns even on a machine without zsh.
    """
    found = shutil.which("zsh")
    if found:
        return found
    for candidate in ("/usr/bin/zsh", "/bin/zsh", "/usr/local/bin/zsh"):
        if os.path.exists(candidate):
            return candidate
    return os.environ.get("SHELL", "/bin/bash")


class _PtyBridge(QObject):
    output_received = Signal(str)

    def __init__(self, shell, channel: str, parent=None):
        super().__init__(parent)
        self._shell = shell
        self._channel = channel

    @Slot(str)
    def write_to_pty(self, data: str) -> None:
        """Forward xterm.js front-end input to the PTY.

        Only a genuinely submitted command line (data carrying CR/LF)
        emits `terminal_session_started`. xterm.js routes its automatic
        terminal-report replies (CPR `ESC[..R`, DA `ESC[..c`, DSR
        `ESC[..n`) and partial keystrokes through the same `onData`
        channel as user input — those are protocol handshakes, not
        activity. Treating a CPR reply (emitted by the zsh prompt at
        startup) as a session start released the `workspace_xterm` idle
        lock and pinned the Terminal 3 listener yellow even while T3 sat
        collapsed and idle. The reply is still forwarded to the PTY (the
        shell needs it) but no longer flips the listener.
        """
        if self._shell is None:
            return
        if "\r" in data or "\n" in data:
            signal_bus.terminal_session_started.emit(self._channel)
        self._shell.send_raw(data.encode("utf-8"))

    @Slot(int, int)
    def resize_pty(self, cols: int, rows: int) -> None:
        """Resize the PTY to match the xterm.js viewport.

        A collapsed (0-height) QWebEngineView makes xterm.js' FitAddon
        emit degenerate resize events with non-positive dimensions.
        Forwarding tiny dimensions (for example `1x1`) also corrupts the
        shell layout: prompts wrap one glyph per line and stay visually
        broken until a new valid SIGWINCH arrives. Drop these transient
        events and keep the last stable geometry.
        """
        if self._shell is None:
            return
        # Keep parity with the pyte terminal minimum geometry guards.
        if cols < 20 or rows < 5:
            return
        self._shell.resize(cols, rows)


class XtermOutputPanel(QWidget):
    def __init__(self, parent=None, workspace_mode: bool = False):
        super().__init__(parent)
        self._workspace_mode = workspace_mode
        self._channel_name = "workspace_xterm" if workspace_mode else "interactive_xterm"
        # T3 (workspace xterm): inicia na raiz da systemForge e usa zsh,
        # mantendo paridade com os terminais pyte (T1/T2).
        self._shell = PersistentShell(
            cwd=_find_systemforge_root(),
            shell=_resolve_zsh(),
            extra_env={
                "WF_CHANNEL_OVERRIDE": (
                    "workspace_xterm" if workspace_mode else "interactive"
                ),
                # Per-instance session ID — same isolation contract as
                # OutputPanel. See ai-forge/rules/workflow-app-listeners.md §2.7.
                "WF_APP_SESSION_ID": APP_SESSION_ID,
            },
            parent=self,
        )
        self._view = QWebEngineView(self)
        self._view.setProperty(
            "testid",
            "terminal-workspace-xterm-output"
            if workspace_mode
            else "terminal-interactive-xterm-output",
        )
        self._channel = QWebChannel(self)
        self._bridge = _PtyBridge(shell=self._shell, channel=self._channel_name, parent=self)
        self._shell.output_received.connect(self._bridge.output_received)
        self._shell.output_received.connect(self._on_shell_output)
        self._channel.registerObject("pyShell", self._bridge)
        self._view.page().setWebChannel(self._channel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view)
        self._view.load(QUrl.fromLocalFile(str(ASSETS_DIR / "index.html")))
        self._shell_started = False
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(2_000)
        self._idle_timer.timeout.connect(self._on_idle_timeout)

        # ── Tripwires (parity with OutputPanel T1/T2) ──────────────────── #
        # Before 2026-05-30 T3 had NO failure tripwires: a Codex worker that
        # crashed / exited on error / never reached the `## FASE FINAL` notify
        # block would let the 2s idle timer flip the dot straight to GREEN —
        # a silent-green that made autocast advance as if the command had
        # succeeded (gap confirmed by /mcp:kimi adversarial review). We now
        # mirror OutputPanel: a fatal-pattern scanner (Camada 1) plus an
        # early-exit watcher (Camada 3). Only the workspace_xterm channel (T3,
        # which has a dedicated listener dot) emits terminal_force_failed;
        # interactive_xterm has no dot and stays silent.
        self._dispatch_ts: float | None = None
        self._bytes_since_dispatch: int = 0
        self._last_failure_reason: str | None = None
        signal_bus.run_command_in_workspace_xterm.connect(self._note_dispatch)

    # Calibrated identically to OutputPanel: a real command emits kilobytes
    # over several seconds; a CLI dying on auth/credit emits ~hundreds of
    # bytes in under a second.
    _EARLY_EXIT_BYTES_THRESHOLD = 512
    _EARLY_EXIT_TIME_THRESHOLD_S = 4.0

    # Helpers — no notify file, brief output, must NOT trigger early-exit.
    # Canonical vocabulary lives in workflow_app.terminal_helpers; this is a
    # back-compat alias so existing references keep resolving.
    _HELPER_COMMANDS: tuple[str, ...] = HELPER_COMMANDS

    @staticmethod
    def _is_helper_command(cmd: str) -> bool:
        """Delegates to the canonical predicate (workflow_app.terminal_helpers)."""
        return is_helper_command(cmd)

    def _note_dispatch(self, _cmd: str) -> None:
        """A command was dispatched to T3 (run_command_in_workspace_xterm).

        Opens the early-exit window and resets the fatal dedupe (new dispatch
        ⇒ new error window). Only meaningful for the workspace_xterm panel.
        Helpers are exempt: they finish fast by design and would false-trigger
        EARLY_EXIT (e.g. /clear on Kimi returns to prompt in <1s).
        """
        if self._channel_name != "workspace_xterm":
            return
        if self._is_helper_command(_cmd):
            # Disarm explicitamente (paridade com OutputPanel._run_shell_command):
            # um _dispatch_ts stale de um comando real anterior nao pode
            # false-firar EARLY_EXIT durante o helper. Um bare `return` deixaria
            # a janela armada. Ver workflow-app-listeners.md §3.3.
            self._dispatch_ts = None
            self._bytes_since_dispatch = 0
            return
        self._dispatch_ts = time.monotonic()
        self._bytes_since_dispatch = 0
        self._last_failure_reason = None

    def ensure_shell_started(self) -> None:
        if not self._shell_started and self._shell is not None:
            self._shell.start()
            self._shell_started = True

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self.ensure_shell_started()

    @property
    def _terminal(self):
        return self._view

    def append_output(self, data: bytes) -> None:
        self._bridge.output_received.emit(data.decode("utf-8", errors="replace"))

    def clear(self) -> None:
        self._view.page().runJavaScript("window.term && window.term.clear();")

    def set_max_lines(self, n: int) -> None:
        self._view.page().runJavaScript(
            f"window.term && (window.term.options.scrollback = {int(n)});"
        )

    def set_interactive_mode(self, enabled: bool) -> None:
        pass

    def _on_shell_output(self, data) -> None:
        signal_bus.terminal_activity.emit("workspace_xterm")
        self._idle_timer.start()
        # Camada 3 byte accounting + Camada 1 fatal scan (parity with OutputPanel).
        chunk = data if isinstance(data, str) else (
            data.decode("utf-8", errors="replace")
            if isinstance(data, (bytes, bytearray))
            else str(data)
        )
        if self._dispatch_ts is not None:
            self._bytes_since_dispatch += len(chunk)
        self._scan_chunk_for_fatal(chunk)

    def _scan_chunk_for_fatal(self, chunk: str) -> None:
        """Camada 1: known fatal CLI errors → terminal_force_failed (red).

        Idempotent per reason within a PTY session (dedupe via
        _last_failure_reason). Only emits for the workspace_xterm channel.

        Soft patterns (generic auth/rate/usage words) only count as a crash
        inside the early-crash window — beyond it the same words are benign
        rendered content, not a CLI death (parity with OutputPanel; see
        blacksmith/listeners/debug.md casos 004/010/013).
        """
        if not chunk or self._channel_name != "workspace_xterm":
            return
        in_early_crash_window = (
            self._dispatch_ts is not None
            and self._bytes_since_dispatch < self._EARLY_EXIT_BYTES_THRESHOLD
            and (time.monotonic() - self._dispatch_ts) < self._EARLY_EXIT_TIME_THRESHOLD_S
        )
        for reason, pattern, severity in _FATAL_PATTERNS:
            if severity == "soft" and not in_early_crash_window:
                continue
            if not pattern.search(chunk):
                continue
            if self._last_failure_reason == reason:
                return
            self._last_failure_reason = reason
            signal_bus.terminal_force_failed.emit("workspace_xterm", reason)
            return

    def _on_idle_timeout(self) -> None:
        # Camada 3: early-exit watcher. If a command was dispatched recently,
        # the PTY emitted few bytes in a short window, and no fatal pattern
        # matched, treat the 2s silence as a crash-before-notify → red instead
        # of the unconditional green that caused silent-green on T3.
        if (
            self._channel_name == "workspace_xterm"
            and self._dispatch_ts is not None
            and self._last_failure_reason is None
            and self._bytes_since_dispatch < self._EARLY_EXIT_BYTES_THRESHOLD
            and (time.monotonic() - self._dispatch_ts) < self._EARLY_EXIT_TIME_THRESHOLD_S
        ):
            self._last_failure_reason = "EARLY_EXIT"
            self._dispatch_ts = None
            signal_bus.terminal_force_failed.emit("workspace_xterm", "EARLY_EXIT")
            return
        # Normal path: consume the dispatch window and go green.
        self._dispatch_ts = None
        signal_bus.terminal_session_finished.emit(self._channel_name)
        signal_bus.terminal_force_idle.emit(self._channel_name)
