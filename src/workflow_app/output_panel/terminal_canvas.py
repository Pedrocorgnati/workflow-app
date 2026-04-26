"""
TerminalCanvas — QPainter-based character grid for pixel-perfect terminal rendering.

Replaces QTextEdit with a custom QWidget that paints a fixed character grid,
eliminating the line spacing gaps and wrapping issues inherent to rich-text editors.

Architecture:
  - Each cell is exactly (cell_width x cell_height) pixels
  - pyte buffer maps 1:1 to the grid
  - Scrollback stored as flat list of row snapshots
  - Selection tracked in cell coordinates
  - Cursor blinks via QTimer (repaint only the cursor cell)
  - QPixmap double-buffer for flicker-free rendering
"""

from __future__ import annotations

import math
import unicodedata
from typing import Any

from PySide6.QtCore import QEvent, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QColor,
    QFont,
    QFontMetrics,
    QPainter,
    QPaintEvent,
    QPixmap,
    QResizeEvent,
    QWheelEvent,
)
from PySide6.QtWidgets import (
    QApplication,
    QMenu,
    QScrollBar,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)


# ── ANSI color palette (VS Code style) ─────────────────────────────────── #

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
_ANSI_16_BY_INDEX: list[QColor] = list(_ANSI_16_COLORS.values())
_CUBE_LUT = (0, 95, 135, 175, 215, 255)

DEFAULT_FG = QColor("#E6EDF3")
DEFAULT_BG = QColor("#0D1117")
CURSOR_BG = QColor("#FBBF24")
CURSOR_FG = QColor("#18181B")
SELECTION_BG = QColor("#264F78")

# ── Scroll ──────────────────────────────────────────────────────────────── #
SCROLLBACK_MAX = 10_000
SCROLL_LINES_PER_STEP = 3


def _pyte_color_to_qcolor(raw: Any) -> QColor | None:
    """Convert a pyte color value to QColor. Returns None for 'default'.

    pyte stores colors as:
      - 'default'                    → widget default
      - named 16-color: 'red', …     → ANSI palette lookup
      - 256-color & truecolor: 6-char hex 'rrggbb' (no leading '#')
      - int (legacy paths)           → ANSI index / 256-cube
    Without the hex branch, every SGR 38;5;N / 38;2;R;G;B fell through and
    the terminal rendered everything as default white.
    """
    if raw is None or raw == "default":
        return None
    if isinstance(raw, str):
        named = _ANSI_16_COLORS.get(raw)
        if named is not None:
            return named
        if len(raw) == 6:
            try:
                return QColor(
                    int(raw[0:2], 16),
                    int(raw[2:4], 16),
                    int(raw[4:6], 16),
                )
            except ValueError:
                return None
        return None
    if isinstance(raw, int):
        if raw < 16:
            return _ANSI_16_BY_INDEX[raw]
        if raw < 232:
            idx = raw - 16
            r, g, b = idx // 36, (idx // 6) % 6, idx % 6
            return QColor(_CUBE_LUT[r], _CUBE_LUT[g], _CUBE_LUT[b])
        v = 8 + (raw - 232) * 10
        return QColor(v, v, v)
    if isinstance(raw, tuple) and len(raw) == 3:
        return QColor(int(raw[0]), int(raw[1]), int(raw[2]))
    return None


def _char_cell_width(ch: str) -> int:
    """Return 1 for normal chars, 2 for wide (CJK, fullwidth)."""
    if not ch or len(ch) != 1:
        return 1
    eaw = unicodedata.east_asian_width(ch)
    return 2 if eaw in ("W", "F") else 1


# ── Cell data structure ─────────────────────────────────────────────────── #

class Cell:
    """Represents one character cell in the grid."""
    __slots__ = ("char", "fg", "bg", "bold", "italic", "underline", "strikethrough", "reverse", "wide")

    def __init__(
        self,
        char: str = " ",
        fg: QColor | None = None,
        bg: QColor | None = None,
        bold: bool = False,
        italic: bool = False,
        underline: bool = False,
        strikethrough: bool = False,
        reverse: bool = False,
        wide: bool = False,
    ) -> None:
        self.char = char
        self.fg = fg
        self.bg = bg
        self.bold = bold
        self.italic = italic
        self.underline = underline
        self.strikethrough = strikethrough
        self.reverse = reverse
        self.wide = wide

    @staticmethod
    def from_pyte(pyte_char: Any) -> Cell:
        """Create a Cell from a pyte Char object."""
        fg = _pyte_color_to_qcolor(pyte_char.fg)
        bg = _pyte_color_to_qcolor(pyte_char.bg)
        data = pyte_char.data if pyte_char.data else " "
        return Cell(
            char=data,
            fg=fg,
            bg=bg,
            bold=pyte_char.bold,
            italic=pyte_char.italics,
            underline=False,  # disable underline to avoid visual artifacts on spaces
            strikethrough=pyte_char.strikethrough,
            reverse=pyte_char.reverse,
            wide=(_char_cell_width(data) == 2),
        )

    @staticmethod
    def empty() -> Cell:
        return Cell()


# ── TerminalCanvas ──────────────────────────────────────────────────────── #

class TerminalCanvas(QWidget):
    """Character-grid terminal widget using QPainter for pixel-perfect rendering."""

    raw_key_pressed = Signal(bytes)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TerminalCanvas")
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        # Enable input method so dead-key composition (´+a → á, ^+e → ê, ~+a → ã)
        # is routed through inputMethodEvent(). Without this, Brazilian Portuguese
        # accents never compose on Linux/XIM/IBus.
        self.setAttribute(Qt.WidgetAttribute.WA_InputMethodEnabled, True)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # Font setup
        self._font = QFont("JetBrains Mono", 12)
        self._font.setStyleHint(QFont.StyleHint.Monospace)
        self._font.setKerning(False)
        self._font.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
        if not QFontMetrics(self._font).horizontalAdvance("M"):
            self._font = QFont("Consolas", 12)
            self._font.setStyleHint(QFont.StyleHint.Monospace)
            self._font.setKerning(False)
        if not QFontMetrics(self._font).horizontalAdvance("M"):
            self._font = QFont("Courier New", 12)
            self._font.setStyleHint(QFont.StyleHint.Monospace)
            self._font.setKerning(False)

        self._recalc_font_metrics()

        # Grid state
        self._cols: int = 80
        self._rows: int = 24
        self._visible_lines: list[list[Cell]] = []  # current pyte visible buffer
        self._scrollback: list[list[Cell]] = []      # scrolled-off history
        self._scroll_offset: int = 0                  # 0 = bottom (latest)

        # Cursor
        self._cursor_row: int = 0
        self._cursor_col: int = 0
        self._cursor_visible: bool = True
        self._cursor_blink_timer = QTimer(self)
        self._cursor_blink_timer.timeout.connect(self._toggle_cursor_blink)
        self._cursor_blink_timer.start(530)

        # Selection (cell coordinates in absolute document space)
        self._selecting: bool = False
        self._sel_start: tuple[int, int] | None = None  # (row, col) absolute
        self._sel_end: tuple[int, int] | None = None

        # Off-screen pixmap
        self._pixmap = QPixmap(max(1, self.width()), max(1, self.height()))
        self._pixmap.fill(DEFAULT_BG)
        self._dirty = True

        # Scrollbar (external, managed by parent layout)
        self._scrollbar: QScrollBar | None = None

    def set_scrollbar(self, scrollbar: QScrollBar) -> None:
        """Connect an external vertical scrollbar."""
        self._scrollbar = scrollbar
        self._scrollbar.valueChanged.connect(self._on_scrollbar_changed)
        self._update_scrollbar_range()

    # ── Font metrics ────────────────────────────────────────────────────── #

    def _recalc_font_metrics(self) -> None:
        fm = QFontMetrics(self._font)
        self._cell_width = max(1, fm.horizontalAdvance("M"))
        # Use height() = ascent + descent for zero-gap grid
        self._cell_height = max(1, fm.height())
        self._ascent = fm.ascent()
        self._descent = fm.descent()

    def font_cell_size(self) -> tuple[int, int]:
        """Return (cell_width, cell_height) for external geometry calculation."""
        return self._cell_width, self._cell_height

    # ── Grid geometry ───────────────────────────────────────────────────── #

    def grid_size(self) -> tuple[int, int]:
        """Return current (cols, rows) based on widget size."""
        return self._cols, self._rows

    def recompute_grid(self) -> tuple[int, int]:
        """Recalculate cols/rows from widget size. Returns (cols, rows)."""
        w = self.width()
        h = self.height()
        if w <= 0 or h <= 0:
            return self._cols, self._rows
        new_cols = max(20, w // self._cell_width)
        new_rows = max(5, h // self._cell_height)
        changed = new_cols != self._cols or new_rows != self._rows
        self._cols = new_cols
        self._rows = new_rows
        if changed:
            self._dirty = True
        return self._cols, self._rows

    # ── Update content from pyte ────────────────────────────────────────── #

    def set_visible_lines(
        self,
        lines: list[list[Cell]],
        cursor_row: int = -1,
        cursor_col: int = -1,
    ) -> None:
        """Replace the visible buffer with new cell data from pyte."""
        self._visible_lines = lines
        self._cursor_row = cursor_row
        self._cursor_col = cursor_col
        self._cursor_visible = True  # reset blink on new content
        self._dirty = True
        if self._scroll_offset == 0:
            self.update()

    def append_scrollback(self, lines: list[list[Cell]]) -> None:
        """Add lines to the scrollback buffer (history that scrolled off)."""
        self._scrollback.extend(lines)
        # Trim to max
        excess = len(self._scrollback) - SCROLLBACK_MAX
        if excess > 0:
            self._scrollback = self._scrollback[excess:]
        self._update_scrollbar_range()
        self._dirty = True

    def clear_all(self) -> None:
        """Clear scrollback and visible buffer."""
        self._scrollback.clear()
        self._visible_lines.clear()
        self._scroll_offset = 0
        self._sel_start = None
        self._sel_end = None
        self._dirty = True
        self._update_scrollbar_range()
        self.update()

    # ── Scrollbar ───────────────────────────────────────────────────────── #

    def _total_lines(self) -> int:
        return len(self._scrollback) + max(len(self._visible_lines), self._rows)

    def _update_scrollbar_range(self) -> None:
        if self._scrollbar is None:
            return
        total = self._total_lines()
        page = self._rows
        max_val = max(0, total - page)
        self._scrollbar.setRange(0, max_val)
        self._scrollbar.setPageStep(page)
        if self._scroll_offset == 0:
            self._scrollbar.setValue(max_val)

    def _on_scrollbar_changed(self, value: int) -> None:
        total = self._total_lines()
        max_val = max(0, total - self._rows)
        self._scroll_offset = max(0, max_val - value)
        self._dirty = True
        self.update()

    def scroll_to_bottom(self) -> None:
        """Scroll to the latest output."""
        self._scroll_offset = 0
        self._update_scrollbar_range()
        self._dirty = True
        self.update()

    # ── Painting ────────────────────────────────────────────────────────── #

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        if self._dirty:
            self._render_to_pixmap()
            self._dirty = False
        painter = QPainter(self)
        painter.drawPixmap(0, 0, self._pixmap)

    def _render_to_pixmap(self) -> None:
        w = max(1, self.width())
        h = max(1, self.height())
        if self._pixmap.width() != w or self._pixmap.height() != h:
            self._pixmap = QPixmap(w, h)

        painter = QPainter(self._pixmap)
        painter.setFont(self._font)
        painter.fillRect(0, 0, w, h, DEFAULT_BG)

        # Determine which rows to display
        total_scrollback = len(self._scrollback)
        total_visible = len(self._visible_lines)

        # Document rows: scrollback + visible_lines
        # scroll_offset=0 means we see the bottom (latest visible lines)
        doc_total = total_scrollback + total_visible
        # First document row visible on screen
        start_doc_row = max(0, doc_total - self._rows - self._scroll_offset)

        sel_start_abs, sel_end_abs = self._normalized_selection()

        for screen_row in range(self._rows):
            doc_row = start_doc_row + screen_row
            if doc_row < 0:
                continue

            # Get the row data
            cells: list[Cell] = []
            is_live = False
            if doc_row < total_scrollback:
                cells = self._scrollback[doc_row]
            elif doc_row - total_scrollback < total_visible:
                live_idx = doc_row - total_scrollback
                cells = self._visible_lines[live_idx]
                is_live = True
            else:
                continue

            y = screen_row * self._cell_height

            col = 0
            while col < len(cells) and col < self._cols:
                cell = cells[col]
                if cell is None:
                    col += 1
                    continue

                x = col * self._cell_width
                span = 2 if cell.wide else 1
                cell_rect = QRect(x, y, self._cell_width * span, self._cell_height)

                # Determine colors
                fg_color = cell.fg or DEFAULT_FG
                bg_color = cell.bg or None

                if cell.reverse:
                    fg_color, bg_color = (bg_color or DEFAULT_BG), (fg_color or DEFAULT_FG)

                # Check if this is the cursor position
                is_cursor = (
                    is_live
                    and self._scroll_offset == 0
                    and (doc_row - total_scrollback) == self._cursor_row
                    and col == self._cursor_col
                    and self._cursor_visible
                )
                if is_cursor:
                    bg_color = CURSOR_BG
                    fg_color = CURSOR_FG

                # Check selection
                if sel_start_abs is not None and sel_end_abs is not None:
                    abs_pos = doc_row * self._cols + col
                    s_pos = sel_start_abs[0] * self._cols + sel_start_abs[1]
                    e_pos = sel_end_abs[0] * self._cols + sel_end_abs[1]
                    if s_pos <= abs_pos <= e_pos:
                        bg_color = SELECTION_BG
                        fg_color = DEFAULT_FG

                # Paint background
                if bg_color is not None:
                    painter.fillRect(cell_rect, bg_color)

                # Paint text
                if cell.char and cell.char.strip():
                    font = QFont(self._font)
                    if cell.bold:
                        font.setWeight(QFont.Weight.Bold)
                    if cell.italic:
                        font.setItalic(True)
                    painter.setFont(font)
                    painter.setPen(fg_color)
                    text_rect = QRectF(x, y, self._cell_width * span, self._cell_height)
                    painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, cell.char)

                    # Underline
                    if cell.underline:
                        painter.setPen(fg_color)
                        uy = y + self._cell_height - 1
                        painter.drawLine(x, uy, x + self._cell_width * span, uy)

                    # Strikethrough
                    if cell.strikethrough:
                        painter.setPen(fg_color)
                        sy = y + self._cell_height // 2
                        painter.drawLine(x, sy, x + self._cell_width * span, sy)

                    # Reset font if modified
                    if cell.bold or cell.italic:
                        painter.setFont(self._font)

                col += span

        # Draw cursor outline when unfocused
        if not self.hasFocus() and self._scroll_offset == 0:
            cx = self._cursor_col * self._cell_width
            cy = self._cursor_row * self._cell_height
            painter.setPen(CURSOR_BG)
            painter.drawRect(cx, cy, self._cell_width - 1, self._cell_height - 1)

        painter.end()

    def _toggle_cursor_blink(self) -> None:
        self._cursor_visible = not self._cursor_visible
        if self._scroll_offset == 0:
            # Repaint only the cursor cell area
            x = self._cursor_col * self._cell_width
            y = self._cursor_row * self._cell_height
            self._dirty = True
            self.update(x, y, self._cell_width, self._cell_height)

    # ── Selection ───────────────────────────────────────────────────────── #

    def _pixel_to_cell(self, x: int, y: int) -> tuple[int, int]:
        """Convert pixel coords to absolute document (row, col)."""
        screen_row = max(0, min(y // self._cell_height, self._rows - 1))
        col = max(0, min(x // self._cell_width, self._cols - 1))
        total_scrollback = len(self._scrollback)
        total_visible = len(self._visible_lines)
        doc_total = total_scrollback + total_visible
        start_doc_row = max(0, doc_total - self._rows - self._scroll_offset)
        abs_row = start_doc_row + screen_row
        return abs_row, col

    def _normalized_selection(self) -> tuple[tuple[int, int] | None, tuple[int, int] | None]:
        """Return (start, end) with start <= end, or (None, None)."""
        if self._sel_start is None or self._sel_end is None:
            return None, None
        s = self._sel_start
        e = self._sel_end
        if (s[0] * self._cols + s[1]) > (e[0] * self._cols + e[1]):
            s, e = e, s
        return s, e

    def get_selected_text(self) -> str:
        """Return the text within the current selection."""
        sel_s, sel_e = self._normalized_selection()
        if sel_s is None or sel_e is None:
            return ""

        total_scrollback = len(self._scrollback)
        total_visible = len(self._visible_lines)
        result_lines: list[str] = []

        for doc_row in range(sel_s[0], sel_e[0] + 1):
            cells: list[Cell] = []
            if doc_row < total_scrollback:
                cells = self._scrollback[doc_row]
            elif doc_row - total_scrollback < total_visible:
                cells = self._visible_lines[doc_row - total_scrollback]

            start_col = sel_s[1] if doc_row == sel_s[0] else 0
            end_col = sel_e[1] if doc_row == sel_e[0] else (len(cells) - 1 if cells else 0)

            line_chars: list[str] = []
            for c in range(start_col, min(end_col + 1, len(cells))):
                cell = cells[c]
                if cell is not None:
                    line_chars.append(cell.char or " ")
                else:
                    line_chars.append(" ")
            result_lines.append("".join(line_chars).rstrip())

        return "\n".join(result_lines)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position() if hasattr(event, "position") else event.pos()
            self._sel_start = self._pixel_to_cell(int(pos.x()), int(pos.y()))
            self._sel_end = self._sel_start
            self._selecting = True
            self._dirty = True
            self.update()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._selecting:
            pos = event.position() if hasattr(event, "position") else event.pos()
            self._sel_end = self._pixel_to_cell(int(pos.x()), int(pos.y()))
            self._dirty = True
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton:
            self._selecting = False
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        """Select the word under the cursor on double-click."""
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.position() if hasattr(event, "position") else event.pos()
            row, col = self._pixel_to_cell(int(pos.x()), int(pos.y()))
            cells = self._get_doc_row(row)
            if not cells:
                return
            # Expand left
            left = col
            while left > 0 and left < len(cells) and cells[left] and cells[left].char.strip():
                left -= 1
            if left < len(cells) and (not cells[left] or not cells[left].char.strip()):
                left += 1
            # Expand right
            right = col
            while right < len(cells) - 1 and cells[right] and cells[right].char.strip():
                right += 1
            if right < len(cells) and (not cells[right] or not cells[right].char.strip()):
                right -= 1
            self._sel_start = (row, left)
            self._sel_end = (row, right)
            self._selecting = False
            self._dirty = True
            self.update()
        super().mouseDoubleClickEvent(event)

    def _get_doc_row(self, doc_row: int) -> list[Cell]:
        total_scrollback = len(self._scrollback)
        if doc_row < total_scrollback:
            return self._scrollback[doc_row]
        live_idx = doc_row - total_scrollback
        if live_idx < len(self._visible_lines):
            return self._visible_lines[live_idx]
        return []

    # ── Scroll (wheel) ──────────────────────────────────────────────────── #

    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802
        delta = event.angleDelta().y()
        if delta > 0:
            # Scroll up (into history)
            self._scroll_offset = min(
                self._scroll_offset + SCROLL_LINES_PER_STEP,
                max(0, self._total_lines() - self._rows),
            )
        elif delta < 0:
            # Scroll down (toward latest)
            self._scroll_offset = max(0, self._scroll_offset - SCROLL_LINES_PER_STEP)
        self._dirty = True
        self._update_scrollbar_range()
        self.update()
        event.accept()

    # ── Resize ──────────────────────────────────────────────────────────── #

    def resizeEvent(self, event: QResizeEvent) -> None:  # noqa: N802
        super().resizeEvent(event)
        self._dirty = True

    # ── Key input ───────────────────────────────────────────────────────── #

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

    def event(self, event: QEvent) -> bool:  # noqa: N802
        """Intercept Tab before Qt focus chain."""
        if event.type() == QEvent.Type.KeyPress:
            from PySide6.QtGui import QKeyEvent  # noqa: PLC0415
            key_event: QKeyEvent = event  # type: ignore[assignment]
            key = Qt.Key(key_event.key())
            if key == Qt.Key.Key_Tab and not (key_event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                self.keyPressEvent(key_event)
                return True
        return super().event(event)

    def inputMethodEvent(self, event) -> None:  # noqa: N802
        commit = event.commitString()
        if commit:
            self.raw_key_pressed.emit(commit.encode("utf-8", errors="replace"))

    _DEAD_KEYS: frozenset[Qt.Key] = frozenset({
        Qt.Key.Key_Dead_Grave,
        Qt.Key.Key_Dead_Acute,
        Qt.Key.Key_Dead_Circumflex,
        Qt.Key.Key_Dead_Tilde,
        Qt.Key.Key_Dead_Diaeresis,
        Qt.Key.Key_Dead_Cedilla,
    })

    def keyPressEvent(self, event) -> None:  # noqa: N802
        from PySide6.QtGui import QKeyEvent  # noqa: PLC0415
        key = Qt.Key(event.key())
        modifiers = event.modifiers()
        ctrl = Qt.KeyboardModifier.ControlModifier
        shift = Qt.KeyboardModifier.ShiftModifier

        # Reset cursor blink on input
        self._cursor_visible = True
        self._cursor_blink_timer.start(530)

        # Let dead keys pass through Qt's input method so the composed char
        # (e.g. ´+a → á) arrives via inputMethodEvent() instead of here.
        if key in self._DEAD_KEYS:
            event.accept()
            return

        # Ctrl+Shift+V → paste
        if modifiers == (ctrl | shift) and key == Qt.Key.Key_V:
            self._paste_clipboard()
            event.accept()
            return

        # Ctrl+Shift+C → copy
        if modifiers == (ctrl | shift) and key == Qt.Key.Key_C:
            text = self.get_selected_text()
            if text:
                QApplication.clipboard().setText(text)
            event.accept()
            return

        # Ctrl+letter → control character
        if modifiers & ctrl and not (modifiers & shift):
            ctrl_char = event.key() - Qt.Key.Key_A.value + 1
            if 1 <= ctrl_char <= 26:
                self.raw_key_pressed.emit(bytes([ctrl_char]))
                event.accept()
                return

        # Named keys
        if key in self._KEY_MAP:
            self.raw_key_pressed.emit(self._KEY_MAP[key])
            event.accept()
            return

        # Printable
        text = event.text()
        if text:
            self.raw_key_pressed.emit(text.encode("utf-8", errors="replace"))
            event.accept()
            return

        super().keyPressEvent(event)

    # ── Context menu ────────────────────────────────────────────────────── #

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
        sel_text = self.get_selected_text()
        copy_action.setEnabled(bool(sel_text))
        menu.addSeparator()
        paste_action = menu.addAction("Colar  Ctrl+Shift+V")
        paste_action.setEnabled(bool(QApplication.clipboard().text()))

        action = menu.exec(event.globalPos())
        if action == copy_action and sel_text:
            QApplication.clipboard().setText(sel_text)
        elif action == paste_action:
            self._paste_clipboard()

    def _paste_clipboard(self) -> None:
        text = QApplication.clipboard().text()
        if text:
            self.raw_key_pressed.emit(text.encode("utf-8", errors="replace"))

    # ── Compatibility API ───────────────────────────────────────────────── #

    def toPlainText(self) -> str:  # noqa: N802
        """Return all text (scrollback + visible) as plain string.

        Provided for backward compatibility with code that assumed QTextEdit.
        """
        lines: list[str] = []
        for row in self._scrollback:
            chars = []
            for cell in row:
                if cell is not None:
                    chars.append(cell.char or " ")
                else:
                    chars.append(" ")
            lines.append("".join(chars).rstrip())
        for row in self._visible_lines:
            chars = []
            for cell in row:
                if cell is not None:
                    chars.append(cell.char or " ")
                else:
                    chars.append(" ")
            lines.append("".join(chars).rstrip())
        # Strip trailing empty lines
        while lines and not lines[-1]:
            lines.pop()
        return "\n".join(lines)
