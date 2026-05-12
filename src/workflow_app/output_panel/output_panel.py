"""
OutputPanel — Embedded terminal with PersistentShell + pyte rendering.

Architecture:
  - PersistentShell: always-on bash/zsh PTY session
      * Key events → shell stdin when no pipeline running
      * User can type "claude /cmd" directly, or use the sidebar
  - PtyRunner (via PipelineManager): spawns claude commands
      * While running: key events → claude PTY stdin instead
      * pyte renders TUI output (spinners, menus, cursor moves)
  - QTimer at 20fps: flushes pyte → TerminalCanvas (QPainter grid)
  - TerminalCanvas: pixel-perfect character grid, zero gaps between rows

Input:
  - Typing directly in the terminal forwards to PTY
  - Ctrl+Shift+V pastes clipboard content to PTY (with bracketed paste support)
  - Right-click → Colar also pastes
  - Interactive pipeline responses work the same way (keys routed to runner)
"""

from __future__ import annotations

import pathlib
from typing import Any

import pyte
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QScrollBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from workflow_app.output_panel.enhanced_screen import EnhancedScreen
from workflow_app.output_panel.persistent_shell import PersistentShell
from workflow_app.output_panel.terminal_canvas import Cell, TerminalCanvas
from workflow_app.signal_bus import signal_bus


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


_TERMINAL_COLS = 80
_TERMINAL_ROWS = 24

DEFAULT_MAX_LINES = 10_000

# Bracketed paste mode bit (DEC 2004)
_BRACKETED_PASTE_MODE = 2004 << 5


class OutputPanel(QWidget):
    """Terminal panel: persistent shell + optional pipeline runner overlay."""

    def __init__(self, parent: QWidget | None = None, workspace_mode: bool = False) -> None:
        super().__init__(parent)
        self._workspace_mode = workspace_mode
        self._channel = "workspace" if workspace_mode else "interactive"
        self.setObjectName("WorkspacePanel" if workspace_mode else "OutputPanel")
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.setStyleSheet("background-color: #18181B;")

        self._max_lines = DEFAULT_MAX_LINES
        self._pipeline_runner: object | None = None  # active PtyRunner, if any
        self._runner_active: bool = False
        self._cols: int = _TERMINAL_COLS
        self._rows: int = _TERMINAL_ROWS

        # ── pyte virtual terminal (EnhancedScreen with alt-screen support) ── #
        self._screen = EnhancedScreen(
            self._cols, self._rows, history=5000
        )
        self._stream = pyte.ByteStream(self._screen)
        self._history_cursor = 0
        self._has_pending_render = False

        self._render_timer = QTimer(self)
        self._render_timer.setInterval(50)  # 20 fps
        self._render_timer.timeout.connect(self._flush_pyte)

        # ── Heuristic 2s idle timer (interactive channel only) ─ #
        # Detects "PTY went silent for 2s" → fires terminal_force_idle.
        # Used by Claude (interactive) which goes genuinely silent post-
        # command. NOT used by workspace — see `_on_chunk` gate.
        self._idle_timer = QTimer(self)
        self._idle_timer.setSingleShot(True)
        self._idle_timer.setInterval(2_000)
        self._idle_timer.timeout.connect(
            lambda: signal_bus.terminal_force_idle.emit(self._channel)
        )

        # ── Resize debounce timer ──────────────────────────────────────── #
        self._resize_timer = QTimer(self)
        self._resize_timer.setSingleShot(True)
        self._resize_timer.setInterval(150)  # 150ms debounce
        self._resize_timer.timeout.connect(self._apply_pending_resize)
        self._pending_cols: int = self._cols
        self._pending_rows: int = self._rows

        # ── Persistent shell ──────────────────────────────────────────── #
        # Shell is created here but NOT started until showEvent fires with
        # real widget geometry. Starting early with fallback cols/rows makes
        # Claude Code (and any TUI) render its banner at the wrong width,
        # which then wraps/duplicates lines forever.
        self._shell: PersistentShell | None = None
        self._shell = PersistentShell(
            cols=self._cols, rows=self._rows, cwd=_find_systemforge_root()
        )
        self._shell.output_received.connect(self._on_chunk)
        self._shell_started: bool = False

        self._setup_ui()
        self._connect_signals()

    # ─────────────────────────────────────────────────────────── UI ──── #

    def _setup_ui(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._terminal = TerminalCanvas()
        self._terminal.setProperty("testid",
            "terminal-workspace-output" if self._workspace_mode else "terminal-interactive-output")
        self._terminal.raw_key_pressed.connect(self._on_raw_key)
        layout.addWidget(self._terminal, stretch=1)

        # Vertical scrollbar
        self._scrollbar = QScrollBar(Qt.Orientation.Vertical)
        self._scrollbar.setStyleSheet(
            "QScrollBar:vertical { background: #0D1117; width: 10px; }"
            "QScrollBar::handle:vertical { background: #3F3F46; min-height: 20px; border-radius: 4px; }"
            "QScrollBar::handle:vertical:hover { background: #52525B; }"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
            "QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: #0D1117; }"
        )
        self._terminal.set_scrollbar(self._scrollbar)
        layout.addWidget(self._scrollbar)

        QTimer.singleShot(0, self._schedule_resize)

    def showEvent(self, event) -> None:  # noqa: N802
        """Start the persistent shell only after real geometry is known.

        On the first show, force the layout to settle, recompute cols/rows
        from actual pixel size, apply that size synchronously to pyte + PTY,
        and only then spawn the shell. This avoids the Claude Code / TUI
        "banner rendered at 220 cols, visible area is 130 cols" breakage.
        """
        super().showEvent(event)
        if self._shell_started or self._shell is None:
            return

        layout = self.layout()
        if layout is not None:
            layout.activate()

        cols, rows = self._terminal.recompute_grid()
        if cols > 0 and rows > 0:
            self._cols = cols
            self._rows = rows
            try:
                self._screen.resize(lines=rows, columns=cols)
            except Exception:  # noqa: BLE001
                self._screen = EnhancedScreen(cols, rows, history=5000)
                self._stream = pyte.ByteStream(self._screen)
                self._history_cursor = 0
                self._has_pending_render = False
            self._shell.resize(cols, rows)
        self._shell.start()
        self._shell_started = True

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._schedule_resize()

    def _schedule_resize(self) -> None:
        """Debounce terminal geometry recalculation."""
        cols, rows = self._terminal.recompute_grid()
        if cols != self._cols or rows != self._rows:
            self._pending_cols = cols
            self._pending_rows = rows
            self._resize_timer.start()  # restart 150ms debounce

    def _apply_pending_resize(self) -> None:
        """Apply the pending resize after debounce period."""
        cols = self._pending_cols
        rows = self._pending_rows
        if cols == self._cols and rows == self._rows:
            return
        self._cols = cols
        self._rows = rows

        # Resize pyte screen (preserves buffer where possible)
        try:
            self._screen.resize(lines=rows, columns=cols)
        except Exception:  # noqa: BLE001
            self._screen = EnhancedScreen(cols, rows, history=5000)
            self._stream = pyte.ByteStream(self._screen)
            self._history_cursor = 0
            self._has_pending_render = False

        # Resize shell PTY and active pipeline runner
        if self._shell is not None:
            self._shell.resize(cols, rows)
        if self._pipeline_runner is not None:
            resize = getattr(self._pipeline_runner, "resize", None)
            if callable(resize):
                resize(cols, rows)

    # ─────────────────────────────────────────────────────── Signals ─── #

    def _connect_signals(self) -> None:
        signal_bus.terminal_output_chunk_received.connect(self._on_terminal_output_chunk)
        signal_bus.terminal_session_started.connect(self._on_terminal_session_started)
        signal_bus.terminal_session_finished.connect(self._on_terminal_session_finished)
        signal_bus.terminal_worker_changed.connect(self._on_terminal_worker_changed)
        if not self._workspace_mode:
            signal_bus.output_cleared.connect(self.clear)
            signal_bus.pipeline_started.connect(self._on_pipeline_started)
            signal_bus.pipeline_completed.connect(self._on_pipeline_completed)
            signal_bus.pipeline_cancelled.connect(self._on_pipeline_completed)
            signal_bus.output_chunk_received.connect(self._on_pipeline_chunk)
            signal_bus.current_worker_changed.connect(self.set_current_worker)
            signal_bus.command_status_changed.connect(self._on_command_status_changed)
            signal_bus.pipeline_error_occurred.connect(self._on_pipeline_error)
            signal_bus.run_command_in_terminal.connect(self._run_shell_command)
            signal_bus.paste_text_in_terminal.connect(self._on_paste_text)
            signal_bus.submit_enter_to_terminal.connect(self._send_enter_to_shell)
        else:
            signal_bus.run_command_in_workspace_terminal.connect(self._run_shell_command)
            signal_bus.paste_text_in_workspace_terminal.connect(self._on_paste_text)
            signal_bus.submit_enter_to_workspace_terminal.connect(self._send_enter_to_shell)
            signal_bus.kimi_blue_arrow_dispatched.connect(self._run_kimi_blue_arrow)

    # ─────────────────────────────────────────────────────── Key routing ─ #

    def _on_raw_key(self, data: bytes) -> None:
        """Route key to pipeline runner (if active) or persistent shell.

        Wraps clipboard paste in bracketed paste sequences if the shell
        has enabled bracketed paste mode (DEC 2004).
        """
        if self._runner_active and self._pipeline_runner is not None:
            send = getattr(self._pipeline_runner, "send_raw", None)
            if callable(send):
                send(data)
        elif self._shell is not None:
            self._shell.send_raw(data)

    def _on_paste_text(self, text: str) -> None:
        """Route pasted text to the active PTY session or the shell.

        Wraps in bracketed paste sequences (ESC[200~ ... ESC[201~) when the
        terminal has enabled DEC 2004 bracketed paste mode.
        """
        if not text:
            return
        data = text.encode("utf-8", errors="replace")

        # Wrap in bracketed paste if mode is active
        if _BRACKETED_PASTE_MODE in self._screen.mode:
            data = b"\x1b[200~" + data + b"\x1b[201~"

        if self._runner_active and self._pipeline_runner is not None:
            send = getattr(self._pipeline_runner, "send_raw", None)
            if callable(send):
                send(data)
                return
        if self._shell is not None:
            self._shell.send_raw(data)

    def _run_shell_command(self, command: str) -> None:
        """Send a command to the persistent shell, when available.

        Wraps the payload in bracketed paste markers (ESC[200~…ESC[201~) when
        DEC 2004 is active, then always schedules the submitting Enter (\r) as
        a separate write. Ink-based CLIs (Claude Code) buffer the paste block
        and swallow a trailing \r that arrives in the same chunk, so the queue
        run trigger would type the command but never submit it. A delayed
        singleShot guarantees the Enter lands as a standalone keypress in both
        BP and non-BP modes.
        """
        if self._shell is None:
            return
        data = command.encode("utf-8", errors="replace")
        if _BRACKETED_PASTE_MODE in self._screen.mode:
            data = b"\x1b[200~" + data + b"\x1b[201~"
        self._shell.send_raw(data)
        QTimer.singleShot(80, self._send_enter_to_shell)

    def _send_enter_to_shell(self) -> None:
        """Send a bare \r to the persistent shell if it is still alive."""
        if self._shell is not None:
            self._shell.send_raw(b"\r")

    def _run_kimi_blue_arrow(self, prompt: str, delay_ms: int) -> None:
        """Blue-arrow Kimi dispatch — paste + delayed Enter.

        Kimi's Rich/textual prompt sometimes swallows Enter when it arrives
        too early (Ink CLIs buffer the paste block and an Enter on the same
        tick gets eaten before the /skill: line is fully composed). The
        delay is supplied by the caller — typically 1000ms, or 3000ms when
        the dispatch is subsequent to /clear (Kimi takes longer to render
        the prompt right after a clear because the TUI repaints fully).
        """
        if self._shell is None:
            return
        data = prompt.encode("utf-8", errors="replace")
        if _BRACKETED_PASTE_MODE in self._screen.mode:
            data = b"\x1b[200~" + data + b"\x1b[201~"
        self._shell.send_raw(data)
        QTimer.singleShot(delay_ms, self, self._send_enter_to_shell)

    def _on_terminal_output_chunk(self, channel: str, chunk: str) -> None:
        """Render a PTY chunk for the bound terminal channel."""
        if channel == self._channel:
            self._on_chunk(chunk)

    def _on_terminal_session_started(self, channel: str) -> None:
        """Attach this panel to an externally managed PTY session."""
        if channel != self._channel:
            return
        self._runner_active = True
        self._idle_timer.stop()
        # Disconnect shell output to prevent mixing with runner output
        if self._shell is not None:
            try:
                self._shell.output_received.disconnect(self._on_chunk)
            except RuntimeError:
                pass  # already disconnected
        self._reset_pyte()

    def _on_terminal_session_finished(self, channel: str) -> None:
        """Detach this panel from an externally managed PTY session."""
        if channel != self._channel:
            return
        self._render_timer.stop()
        if self._has_pending_render:
            self._flush_pyte()
        self._runner_active = False
        self._pipeline_runner = None
        self._reset_pyte()
        # Reconnect shell output after runner session ends
        if self._shell is not None:
            try:
                self._shell.output_received.connect(self._on_chunk)
            except RuntimeError:
                pass  # already connected

    def _on_terminal_worker_changed(self, channel: str, worker: object) -> None:
        """Update the PTY target for keyboard routing on this panel."""
        if channel == self._channel:
            self.set_current_worker(worker)

    # ─────────────────────────────────── pyte → TerminalCanvas rendering ─ #

    def _pyte_row_to_cells(self, row_dict: dict[int, Any]) -> list[Cell]:
        """Convert a pyte buffer row to a list of Cell objects."""
        if not row_dict:
            return [Cell.empty() for _ in range(self._cols)]
        max_col = max(row_dict.keys()) if row_dict else 0
        cells: list[Cell] = []
        col = 0
        while col <= max(max_col, self._cols - 1):
            ch = row_dict.get(col)
            if ch is not None:
                cell = Cell.from_pyte(ch)
                cells.append(cell)
                if cell.wide:
                    cells.append(None)  # type: ignore[arg-type]  # placeholder for wide char
                    col += 2
                else:
                    col += 1
            else:
                cells.append(Cell.empty())
                col += 1
        # Pad to cols
        while len(cells) < self._cols:
            cells.append(Cell.empty())
        return cells[:self._cols]

    def _on_chunk(self, chunk: str) -> None:
        """Feed a chunk (from shell or pipeline) to pyte and schedule render.

        Heuristic 2s idle timer is armed ONLY for the interactive channel
        (Claude Code). Claude's UI emits a "Bash..." indicator while a
        bash tool is running (so intra-execution sleeps don't cause false
        idle), and goes genuinely silent when the command finishes — so
        the 2s timer + 3s soft fire correctly when there's nothing
        emitting notify file for the interactive channel.

        Workspace (Kimi) does NOT use this heuristic: Kimi's input prompt
        emits subtle PTY bytes indefinitely (cursor, ANSI repaints), so a
        silence-based heuristic never fires AND collides with notify
        hardening. Workspace relies on the explicit 5s post-notify timer.
        """
        try:
            self._stream.feed(chunk.encode("utf-8", errors="replace"))
        except Exception:  # noqa: BLE001
            return
        self._has_pending_render = True
        if not self._render_timer.isActive():
            self._render_timer.start()
        if not self._runner_active and self._channel == "interactive":
            self._idle_timer.start()
        signal_bus.terminal_activity.emit(self._channel)

    def _on_pipeline_chunk(self, chunk: str) -> None:
        """Chunk from the pipeline runner (separate signal from shell)."""
        self._on_chunk(chunk)

    def _flush_pyte(self) -> None:
        if not self._has_pending_render:
            return
        self._has_pending_render = False

        # ── 1. Append history lines that scrolled off ──────────────────── #
        history_top = list(self._screen.history.top)
        new_count = len(history_top) - self._history_cursor
        if new_count > 0:
            new_lines: list[list[Cell]] = []
            for line_dict in history_top[self._history_cursor:]:
                new_lines.append(self._pyte_row_to_cells(dict(line_dict)))
            self._terminal.append_scrollback(new_lines)
            self._history_cursor = len(history_top)

        # ── 2. Build visible buffer as Cell grid ───────────────────────── #
        term_cursor_row = self._screen.cursor.y
        term_cursor_col = self._screen.cursor.x

        visible_lines: list[list[Cell]] = []
        for row_idx in range(self._screen.lines):
            row = self._screen.buffer.get(row_idx) or {}
            visible_lines.append(self._pyte_row_to_cells(dict(row)))

        self._terminal.set_visible_lines(
            visible_lines,
            cursor_row=term_cursor_row,
            cursor_col=term_cursor_col,
        )
        self._terminal.scroll_to_bottom()

    # ─────────────────────────────────────────────────── Pipeline events ─ #

    def _on_pipeline_started(self) -> None:
        self._runner_active = True
        self._idle_timer.stop()
        if self._shell is not None:
            try:
                self._shell.output_received.disconnect(self._on_chunk)
            except RuntimeError:
                pass
        self._reset_pyte()
        self._terminal.setFocus()

    def _on_pipeline_error(self, _exec_id: int, message: str) -> None:
        pass  # errors visible in the terminal output itself

    def _on_pipeline_completed(self) -> None:
        self._render_timer.stop()
        if self._has_pending_render:
            self._flush_pyte()
        self._runner_active = False
        self._pipeline_runner = None
        self._reset_pyte()
        if self._shell is not None:
            try:
                self._shell.output_received.connect(self._on_chunk)
            except RuntimeError:
                pass
        self._terminal.setFocus()

    def _on_command_status_changed(self, _cmd_exec_id: int, status: str) -> None:
        pass  # status visible in command queue sidebar

    def _reset_pyte(self) -> None:
        """Reset pyte state (keeps terminal canvas content intact)."""
        self._screen = EnhancedScreen(
            self._cols, self._rows, history=5000
        )
        self._stream = pyte.ByteStream(self._screen)
        self._history_cursor = 0
        self._has_pending_render = False
        self._render_timer.stop()

    # ─────────────────────────────────────────────────────── Public API ─ #

    def append_output(self, text: str) -> None:
        """Feed text through pyte for proper rendering."""
        self._on_chunk(text)

    def clear(self) -> None:
        """Clear the terminal display and reset pyte."""
        self._terminal.clear_all()
        self._reset_pyte()

    def set_max_lines(self, max_lines: int) -> None:
        self._max_lines = max_lines

    def set_interactive_mode(self, active: bool) -> None:
        pass  # no-op: input handled directly via terminal keyboard

    def set_current_worker(self, worker: object) -> None:
        self._pipeline_runner = worker
        resize = getattr(worker, "resize", None)
        if callable(resize):
            resize(self._cols, self._rows)

    def closeEvent(self, event) -> None:  # noqa: N802
        self._render_timer.stop()
        self._resize_timer.stop()
        if self._shell is not None:
            self._shell.terminate()
        super().closeEvent(event)
