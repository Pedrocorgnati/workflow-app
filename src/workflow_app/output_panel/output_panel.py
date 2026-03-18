"""
OutputPanel — Embedded terminal with PersistentShell + pyte rendering.

Architecture:
  - PersistentShell: always-on bash/zsh PTY session
      * Key events → shell stdin when no pipeline running
      * User can type "claude /cmd" directly, or use the sidebar
  - PtyRunner (via PipelineManager): spawns claude commands
      * While running: key events → claude PTY stdin instead
      * pyte renders TUI output (spinners, menus, cursor moves)
  - QTimer at 20fps: flushes pyte → QTextEdit (with ANSI colors)

Input:
  - Typing directly in the terminal forwards to PTY
  - Ctrl+Shift+V pastes clipboard content to PTY
  - Right-click → Colar also pastes
  - Interactive pipeline responses work the same way (keys routed to runner)
"""

from __future__ import annotations

import itertools
import pathlib
from typing import Any

import pyte
from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QKeyEvent, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QMenu,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from workflow_app.output_panel.persistent_shell import PersistentShell
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


_TERMINAL_COLS = 220
_TERMINAL_ROWS = 50

DEFAULT_MAX_LINES = 10_000

# VT100 escape sequences for named keys
_KEY_MAP: dict[Qt.Key, bytes] = {
    Qt.Key.Key_Up:        b"\x1b[A",
    Qt.Key.Key_Down:      b"\x1b[B",
    Qt.Key.Key_Right:     b"\x1b[C",
    Qt.Key.Key_Left:      b"\x1b[D",
    Qt.Key.Key_Home:      b"\x1b[H",
    Qt.Key.Key_End:       b"\x1b[F",
    Qt.Key.Key_PageUp:    b"\x1b[5~",
    Qt.Key.Key_PageDown:  b"\x1b[6~",
    Qt.Key.Key_Delete:    b"\x1b[3~",
    Qt.Key.Key_Insert:    b"\x1b[2~",
    Qt.Key.Key_F1:        b"\x1bOP",
    Qt.Key.Key_F2:        b"\x1bOQ",
    Qt.Key.Key_F3:        b"\x1bOR",
    Qt.Key.Key_F4:        b"\x1bOS",
    Qt.Key.Key_Return:    b"\r",
    Qt.Key.Key_Enter:     b"\r",
    Qt.Key.Key_Backspace: b"\x7f",
    Qt.Key.Key_Tab:       b"\t",
    Qt.Key.Key_Escape:    b"\x1b",
}

# ── ANSI color palette ──────────────────────────────────────────────────── #
# VS Code–style 16-color palette (looks good on dark backgrounds)
_ANSI_16_COLORS: dict[str, QColor] = {
    "black":         QColor("#1E1E1E"),
    "red":           QColor("#CD3131"),
    "green":         QColor("#0DBC79"),
    "yellow":        QColor("#E5E510"),
    "blue":          QColor("#2472C8"),
    "magenta":       QColor("#BC3FBC"),
    "cyan":          QColor("#11A8CD"),
    "white":         QColor("#E5E5E5"),
    "brightblack":   QColor("#666666"),
    "brightred":     QColor("#F14C4C"),
    "brightgreen":   QColor("#23D18B"),
    "brightyellow":  QColor("#F5F543"),
    "brightblue":    QColor("#3B8EEA"),
    "brightmagenta": QColor("#D670D6"),
    "brightcyan":    QColor("#29B8DB"),
    "brightwhite":   QColor("#FFFFFF"),
}

# Ordered list for 256-color index 0–15
_ANSI_16_BY_INDEX: list[QColor] = list(_ANSI_16_COLORS.values())

# 256-color cube lookup table (indices 0–5 → 0, 95, 135, 175, 215, 255)
_CUBE_LUT = (0, 95, 135, 175, 215, 255)

_DEFAULT_FG_COLOR = QColor("#E6EDF3")   # terminal text
_DEFAULT_BG_COLOR = QColor("#0D1117")   # terminal background

# Style key used for plain/default chars (no ANSI attributes)
_DEFAULT_STYLE_KEY: tuple = ("default", "default", False, False, False, False, False)

# Tolerance in pixels to consider the scroll position "at the bottom"
_SCROLL_MARGIN = 20

# Cursor block: amber background, dark foreground
_CURSOR_BG_COLOR = QColor("#FBBF24")
_CURSOR_FG_COLOR = QColor("#18181B")
_CURSOR_STYLE_KEY: tuple = ("__cursor__", "__cursor__", False, False, False, False, False)


def _pyte_color_to_qcolor(raw: Any) -> QColor | None:
    """Convert a pyte color value to QColor.

    pyte color formats:
      str  — named ANSI color ("red", "brightblue", …) or "default"
      int  — 256-color index 0–255
      tuple — (r, g, b) truecolor
    Returns None for "default" / unknown (caller uses terminal default color).
    """
    if raw is None or raw == "default":
        return None
    if isinstance(raw, str):
        return _ANSI_16_COLORS.get(raw)
    if isinstance(raw, int):
        if raw < 16:
            return _ANSI_16_BY_INDEX[raw]
        if raw < 232:
            # 6×6×6 color cube: index 16–231
            idx = raw - 16
            r, g, b = idx // 36, (idx // 6) % 6, idx % 6
            return QColor(_CUBE_LUT[r], _CUBE_LUT[g], _CUBE_LUT[b])
        # Grayscale ramp: index 232–255
        v = 8 + (raw - 232) * 10
        return QColor(v, v, v)
    if isinstance(raw, tuple) and len(raw) == 3:
        return QColor(int(raw[0]), int(raw[1]), int(raw[2]))
    return None


class TerminalWidget(QTextEdit):
    """Read-only rich-text display that captures and forwards key events to a PTY."""

    from PySide6.QtCore import Signal
    raw_key_pressed = Signal(bytes)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TerminalOutput")
        self.setReadOnly(True)
        font = QFont("JetBrains Mono", 12)
        font.setStyleHint(QFont.StyleHint.Monospace)
        if not font.exactMatch():
            font = QFont("Consolas", 12)
        if not font.exactMatch():
            font = QFont("Courier New", 12)
        self.setFont(font)
        self.setStyleSheet(
            "QTextEdit#TerminalOutput {"
            "  background-color: #0D1117;"
            "  color: #E6EDF3;"
            "  border: none;"
            "  selection-background-color: #264F78;"
            "}"
        )
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setTabChangesFocus(False)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def event(self, event: QEvent) -> bool:  # noqa: N802
        """Override: intercepts Tab before Qt processes the focus chain."""
        if event.type() == QEvent.Type.KeyPress:
            key_event: QKeyEvent = event  # type: ignore[assignment]
            key = Qt.Key(key_event.key())
            if key == Qt.Key.Key_Tab and not (key_event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                # Tab without Shift: send to PTY, do not propagate to Qt focus chain
                self.keyPressEvent(key_event)
                return True
        return super().event(event)

    def inputMethodEvent(self, event) -> None:  # noqa: N802
        """Handle composed/accented characters from input methods (dead keys, iBus, etc.)."""
        commit = event.commitString()
        if commit:
            self.raw_key_pressed.emit(commit.encode("utf-8", errors="replace"))

    def keyPressEvent(self, event: QKeyEvent) -> None:  # noqa: N802
        key = Qt.Key(event.key())
        modifiers = event.modifiers()
        ctrl = Qt.KeyboardModifier.ControlModifier
        shift = Qt.KeyboardModifier.ShiftModifier

        # Ctrl+Shift+V → paste clipboard to PTY (Linux terminal convention)
        if modifiers == (ctrl | shift) and key == Qt.Key.Key_V:
            self._paste_clipboard()
            event.accept()
            return

        # Ctrl+Shift+C → copy selected text
        if modifiers == (ctrl | shift) and key == Qt.Key.Key_C:
            self.copy()
            event.accept()
            return

        # Ctrl+letter → control character (Ctrl+C = 3, Ctrl+D = 4, etc.)
        if modifiers & ctrl and not (modifiers & shift):
            ctrl_char = event.key() - Qt.Key.Key_A.value + 1
            if 1 <= ctrl_char <= 26:
                self.raw_key_pressed.emit(bytes([ctrl_char]))
                event.accept()
                return

        # Named keys with VT100 sequences
        if key in _KEY_MAP:
            self.raw_key_pressed.emit(_KEY_MAP[key])
            event.accept()
            return

        # Printable characters
        text = event.text()
        if text:
            self.raw_key_pressed.emit(text.encode("utf-8", errors="replace"))
            event.accept()
            return

        # Fallback: scrolling, selection, etc.
        super().keyPressEvent(event)

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        menu = QMenu(self)
        menu.setStyleSheet(
            "QMenu { background-color: #27272A; border: 1px solid #3F3F46;"
            "  color: #FAFAFA; padding: 4px; }"
            "QMenu::item { padding: 6px 16px; border-radius: 4px; }"
            "QMenu::item:selected { background-color: #3F3F46; }"
            "QMenu::separator { background-color: #3F3F46; height: 1px; }"
        )
        copy_action = menu.addAction("Copiar")
        copy_action.setEnabled(self.textCursor().hasSelection())
        menu.addSeparator()
        paste_action = menu.addAction("Colar  Ctrl+Shift+V")
        paste_action.setEnabled(bool(QApplication.clipboard().text()))

        action = menu.exec(event.globalPos())
        if action == copy_action:
            self.copy()
        elif action == paste_action:
            self._paste_clipboard()

    def _paste_clipboard(self) -> None:
        """Send clipboard text to the PTY."""
        text = QApplication.clipboard().text()
        if text:
            self.raw_key_pressed.emit(text.encode("utf-8", errors="replace"))


class OutputPanel(QWidget):
    """Terminal panel: persistent shell + optional pipeline runner overlay."""

    def __init__(self, parent: QWidget | None = None, autocast_mode: bool = False) -> None:
        super().__init__(parent)
        self._autocast_mode = autocast_mode
        self.setObjectName("AutocastPanel" if autocast_mode else "OutputPanel")
        self.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.setStyleSheet("background-color: #18181B;")

        self._max_lines = DEFAULT_MAX_LINES
        self._pipeline_runner: object | None = None  # active PtyRunner, if any
        self._live_view_start_block: int = -1
        self._runner_active: bool = False

        # Cache QTextCharFormat instances keyed by style tuple to avoid
        # re-allocation on every flush (important at 20 fps).
        self._fmt_cache: dict[tuple, QTextCharFormat] = {}

        # ── pyte virtual terminal ─────────────────────────────────────── #
        self._screen = pyte.HistoryScreen(
            _TERMINAL_COLS, _TERMINAL_ROWS, history=5000
        )
        self._stream = pyte.ByteStream(self._screen)
        self._history_cursor = 0
        self._has_pending_render = False

        self._render_timer = QTimer(self)
        self._render_timer.setInterval(50)  # 20 fps
        self._render_timer.timeout.connect(self._flush_pyte)

        # ── Persistent shell ──────────────────────────────────────────── #
        self._shell = PersistentShell(
            cols=_TERMINAL_COLS, rows=_TERMINAL_ROWS, cwd=_find_systemforge_root()
        )
        self._shell.output_received.connect(self._on_chunk)

        self._setup_ui()
        self._connect_signals()

        # Start the shell
        self._shell.start()

    # ─────────────────────────────────────────────────────────── UI ──── #

    def _setup_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        self._terminal = TerminalWidget()
        self._terminal.document().setMaximumBlockCount(self._max_lines)
        self._terminal.raw_key_pressed.connect(self._on_raw_key)
        layout.addWidget(self._terminal, stretch=1)

    # ─────────────────────────────────────────────────────── Signals ─── #

    def _connect_signals(self) -> None:
        if self._autocast_mode:
            # Autocast terminal: receives autocast commands and output
            signal_bus.output_appended.connect(self.append_output)
            signal_bus.run_autocast_in_terminal.connect(self._shell.run_command)
        else:
            # Interactive terminal: receives interactive commands + keyboard input
            signal_bus.output_cleared.connect(self.clear)
            signal_bus.pipeline_started.connect(self._on_pipeline_started)
            signal_bus.pipeline_completed.connect(self._on_pipeline_completed)
            signal_bus.pipeline_cancelled.connect(self._on_pipeline_completed)
            signal_bus.output_chunk_received.connect(self._on_pipeline_chunk)
            signal_bus.current_worker_changed.connect(self.set_current_worker)
            signal_bus.command_status_changed.connect(self._on_command_status_changed)
            signal_bus.pipeline_error_occurred.connect(self._on_pipeline_error)
            signal_bus.run_command_in_terminal.connect(self._shell.run_command)
            signal_bus.paste_text_in_terminal.connect(self._shell.send_text)

    # ─────────────────────────────────────────────────────── Key routing ─ #

    def _on_raw_key(self, data: bytes) -> None:
        """Route key to pipeline runner (if active) or persistent shell."""
        if self._runner_active and self._pipeline_runner is not None:
            send = getattr(self._pipeline_runner, "send_raw", None)
            if callable(send):
                send(data)
        else:
            self._shell.send_raw(data)

    # ──────────────────────────────────────── pyte color rendering helpers ─ #

    def _format_for(self, key: tuple) -> QTextCharFormat:
        """Return a cached QTextCharFormat for a pyte style key tuple.

        key = (fg, bg, bold, italics, underscore, strikethrough, reverse)
        Special key _CURSOR_STYLE_KEY renders the blinking cursor block.
        """
        fmt = self._fmt_cache.get(key)
        if fmt is not None:
            return fmt

        if key is _CURSOR_STYLE_KEY or key == _CURSOR_STYLE_KEY:
            fmt = QTextCharFormat()
            fmt.setBackground(_CURSOR_BG_COLOR)
            fmt.setForeground(_CURSOR_FG_COLOR)
            self._fmt_cache[key] = fmt
            return fmt

        fg_raw, bg_raw, bold, italic, underline, strike, reverse = key

        fmt = QTextCharFormat()

        if reverse:
            # Swap foreground/background; fall back to terminal defaults.
            new_fg = _pyte_color_to_qcolor(bg_raw) if bg_raw not in ("default", None) else _DEFAULT_BG_COLOR
            new_bg = _pyte_color_to_qcolor(fg_raw) if fg_raw not in ("default", None) else _DEFAULT_FG_COLOR
            fmt.setForeground(new_fg)
            fmt.setBackground(new_bg)
        else:
            fg_color = _pyte_color_to_qcolor(fg_raw)
            if fg_color is not None:
                fmt.setForeground(fg_color)
            bg_color = _pyte_color_to_qcolor(bg_raw)
            if bg_color is not None:
                fmt.setBackground(bg_color)

        if bold:
            fmt.setFontWeight(QFont.Weight.Bold)
        if italic:
            fmt.setFontItalic(True)
        if underline:
            fmt.setFontUnderline(True)
        if strike:
            fmt.setFontStrikeOut(True)

        self._fmt_cache[key] = fmt
        return fmt

    def _insert_line_runs(
        self, cursor: QTextCursor, line_dict: dict[int, Any], cursor_col: int = -1
    ) -> None:
        """Insert one pyte line as styled runs into the document.

        Groups consecutive chars with the same style key so we make
        one insertText() call per run instead of one per character.
        If cursor_col >= 0, the character at that column is rendered with
        the block-cursor highlight (amber background).
        """
        max_col = max(line_dict.keys()) if line_dict else -1
        if cursor_col >= 0:
            max_col = max(max_col, cursor_col)

        if max_col < 0:
            return

        # Build (style_key, char_data) sequence up to the last relevant column
        items: list[tuple[tuple, str]] = []
        for col in range(max_col + 1):
            ch = line_dict.get(col)
            char_data = (ch.data if ch else " ") or " "
            if col == cursor_col:
                items.append((_CURSOR_STYLE_KEY, char_data))
            elif ch is None:
                items.append((_DEFAULT_STYLE_KEY, char_data))
            else:
                key = (ch.fg, ch.bg, ch.bold, ch.italics,
                       ch.underscore, ch.strikethrough, ch.reverse)
                items.append((key, char_data))

        # Strip trailing whitespace-with-default-style (saves space in document)
        # Cursor characters are never stripped.
        while items and items[-1][1].strip() == "" and items[-1][0] == _DEFAULT_STYLE_KEY:
            items.pop()

        if not items:
            return

        # Insert grouped runs
        for style_key, group in itertools.groupby(items, key=lambda x: x[0]):
            text = "".join(ch for _, ch in group)
            if text:
                cursor.insertText(text, self._format_for(style_key))

    def _collect_visible_buffer_lines(self, min_rows: int = 0) -> list[dict[int, Any]]:
        """Return non-empty visible rows from the pyte buffer as {col: Char} dicts.

        Trims trailing empty rows so the live view doesn't grow on every flush,
        but always includes at least min_rows rows (used to preserve cursor row).
        Uses .get() on the defaultdict to avoid creating entries for empty rows.
        """
        rows: list[dict[int, Any]] = []
        last_nonempty = -1

        for row_idx in range(self._screen.lines):
            # .get() avoids defaultdict __missing__ side-effects
            row = self._screen.buffer.get(row_idx) or {}
            row_dict = dict(row)
            if any(ch.data.strip() for ch in row_dict.values()):
                last_nonempty = row_idx
            rows.append(row_dict)

        limit = max(last_nonempty, min_rows)
        return rows[:limit + 1]

    # ─────────────────────────────────────────────────── pyte rendering ─ #

    def _on_chunk(self, chunk: str) -> None:
        """Feed a chunk (from shell or pipeline) to pyte and schedule render."""
        try:
            self._stream.feed(chunk.encode("utf-8", errors="replace"))
        except Exception:  # noqa: BLE001
            self._append_to_terminal(chunk)
            return
        self._has_pending_render = True
        if not self._render_timer.isActive():
            self._render_timer.start()

    def _on_pipeline_chunk(self, chunk: str) -> None:
        """Chunk from the pipeline runner (separate signal from shell)."""
        self._on_chunk(chunk)

    def _flush_pyte(self) -> None:
        if not self._has_pending_render:
            return
        self._has_pending_render = False

        # ── 1. Append history lines that scrolled off (with colors) ──── #
        history_top = list(self._screen.history.top)
        new_count = len(history_top) - self._history_cursor
        if new_count > 0:
            cursor = self._terminal.textCursor()
            cursor.movePosition(QTextCursor.MoveOperation.End)
            for line_dict in history_top[self._history_cursor:]:
                self._insert_line_runs(cursor, dict(line_dict))
                cursor.insertText("\n")
            self._history_cursor = len(history_top)
            self._terminal.setTextCursor(cursor)

        # ── 2. Replace live view with current visible buffer (with colors) ─ #
        term_cursor_row = self._screen.cursor.y
        term_cursor_col = self._screen.cursor.x
        visible_lines = self._collect_visible_buffer_lines(min_rows=term_cursor_row)
        self._replace_live_view(visible_lines, term_cursor_row=term_cursor_row, term_cursor_col=term_cursor_col)

    def _replace_live_view(
        self,
        lines: list[dict[int, Any]],
        term_cursor_row: int = -1,
        term_cursor_col: int = -1,
    ) -> None:
        """Replace the live-view section with freshly rendered colored lines.

        term_cursor_row/col: pyte cursor position — that character is rendered
        with an amber block highlight so the user can see where they are typing.
        """
        cursor = self._terminal.textCursor()
        doc = self._terminal.document()
        block_count = doc.blockCount()

        if 0 <= self._live_view_start_block < block_count:
            start_block = doc.findBlockByNumber(self._live_view_start_block)
            cursor.setPosition(start_block.position())
            cursor.movePosition(
                QTextCursor.MoveOperation.End, QTextCursor.MoveMode.KeepAnchor
            )
            cursor.removeSelectedText()
        else:
            cursor.movePosition(QTextCursor.MoveOperation.End)

        self._live_view_start_block = doc.blockCount() - 1

        for i, line_dict in enumerate(lines):
            if i > 0:
                cursor.insertText("\n")
            col = term_cursor_col if i == term_cursor_row else -1
            self._insert_line_runs(cursor, line_dict, cursor_col=col)

        self._terminal.setTextCursor(cursor)
        sb = self._terminal.verticalScrollBar()
        if sb.value() >= sb.maximum() - _SCROLL_MARGIN:
            self._terminal.moveCursor(QTextCursor.MoveOperation.End)
            sb.setValue(sb.maximum())

    # ─────────────────────────────────────────────────── Pipeline events ─ #

    def _on_pipeline_started(self) -> None:
        self._runner_active = True
        self._reset_pyte()
        self._append_to_terminal("\n● Pipeline iniciado\n")
        self._terminal.setFocus()

    def _on_pipeline_error(self, _exec_id: int, message: str) -> None:
        self._append_to_terminal(f"\n✕ Erro: {message}\n")

    def _on_pipeline_completed(self) -> None:
        self._render_timer.stop()
        if self._has_pending_render:
            self._flush_pyte()
        self._runner_active = False
        self._pipeline_runner = None
        self._reset_pyte()
        self._terminal.setFocus()

    def _on_command_status_changed(self, _cmd_exec_id: int, status: str) -> None:
        if status == "concluido":
            self._append_to_terminal("\n✓ Concluído\n")
        elif status == "erro":
            self._append_to_terminal("\n✕ Erro\n")

    def _reset_pyte(self) -> None:
        """Reset pyte state (keeps terminal text intact)."""
        self._screen = pyte.HistoryScreen(
            _TERMINAL_COLS, _TERMINAL_ROWS, history=5000
        )
        self._stream = pyte.ByteStream(self._screen)
        self._history_cursor = 0
        self._has_pending_render = False
        self._live_view_start_block = -1
        self._fmt_cache.clear()
        self._render_timer.stop()
        sb = self._terminal.verticalScrollBar()
        sb.setValue(sb.maximum())

    # ─────────────────────────────────────────────────────── Public API ─ #

    def append_output(self, text: str) -> None:
        self._append_to_terminal(text)

    def clear(self) -> None:
        """Clear the terminal display and reset pyte."""
        self._terminal.clear()
        self._reset_pyte()

    def set_max_lines(self, max_lines: int) -> None:
        self._max_lines = max_lines
        self._terminal.document().setMaximumBlockCount(max_lines)

    def set_interactive_mode(self, active: bool) -> None:
        pass  # no-op: input handled directly via terminal keyboard

    def set_current_worker(self, worker: object) -> None:
        self._pipeline_runner = worker

    def _append_to_terminal(self, text: str) -> None:
        """Insert plain system text (pipeline status messages) at the end."""
        self._live_view_start_block = -1
        cursor = self._terminal.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        # Default QTextCharFormat inherits the widget's base color (E6EDF3)
        cursor.insertText(text, QTextCharFormat())
        self._terminal.setTextCursor(cursor)
        self._terminal.moveCursor(QTextCursor.MoveOperation.End)
        sb = self._terminal.verticalScrollBar()
        sb.setValue(sb.maximum())

    def closeEvent(self, event) -> None:  # noqa: N802
        self._shell.terminate()
        super().closeEvent(event)
