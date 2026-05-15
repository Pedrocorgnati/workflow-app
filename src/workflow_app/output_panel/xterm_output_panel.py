from pathlib import Path

from PySide6.QtCore import QObject, QUrl, Signal, Slot
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QVBoxLayout, QWidget

from .persistent_shell import PersistentShell

ASSETS_DIR = Path(__file__).resolve().parents[3] / "assets" / "xterm"


class _PtyBridge(QObject):
    output_received = Signal(str)

    def __init__(self, shell, parent=None):
        super().__init__(parent)
        self._shell = shell

    @Slot(str)
    def write_to_pty(self, data: str) -> None:
        if self._shell is not None:
            self._shell.send_raw(data.encode("utf-8"))

    @Slot(int, int)
    def resize_pty(self, cols: int, rows: int) -> None:
        if self._shell is not None:
            self._shell.resize(cols, rows)


class XtermOutputPanel(QWidget):
    def __init__(self, parent=None, workspace_mode: bool = False):
        super().__init__(parent)
        self._workspace_mode = workspace_mode
        self._shell = PersistentShell(parent=self)
        self._view = QWebEngineView(self)
        self._channel = QWebChannel(self)
        self._bridge = _PtyBridge(shell=self._shell, parent=self)
        self._shell.output_received.connect(self._bridge.output_received)
        self._channel.registerObject("pyShell", self._bridge)
        self._view.page().setWebChannel(self._channel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._view)
        self._view.load(QUrl.fromLocalFile(str(ASSETS_DIR / "index.html")))
        self._shell_started = False

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        if not self._shell_started and self._shell is not None:
            self._shell.start()
            self._shell_started = True

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
