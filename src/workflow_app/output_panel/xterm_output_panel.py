import os
import shutil
from pathlib import Path

from PySide6.QtCore import QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget

from .output_panel import _find_systemforge_root
from .persistent_shell import PersistentShell
from workflow_app.signal_bus import signal_bus

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
                )
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

    def _on_shell_output(self, _data: bytes) -> None:
        signal_bus.terminal_activity.emit("workspace_xterm")
        self._idle_timer.start()

    def _on_idle_timeout(self) -> None:
        signal_bus.terminal_session_finished.emit(self._channel_name)
        signal_bus.terminal_force_idle.emit(self._channel_name)
