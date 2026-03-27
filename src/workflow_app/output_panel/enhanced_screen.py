"""
EnhancedScreen — pyte.HistoryScreen subclass with alternate screen buffer support.

pyte 0.8.x does NOT properly save/restore the main buffer when programs enter
alternate screen mode (DEC 1049). This subclass fixes that, which is critical
for programs like claude CLI, vim, less, and htop.
"""

from __future__ import annotations

import copy

import pyte


# DEC Private Mode bit for alternate screen (1049)
_ALT_SCREEN_MODE = 1049 << 5


class EnhancedScreen(pyte.HistoryScreen):
    """HistoryScreen with proper alternate screen buffer save/restore."""

    def __init__(self, columns: int, lines: int, history: int = 5000) -> None:
        super().__init__(columns, lines, history=history)
        self._saved_buffer: dict | None = None
        self._saved_cursor: object | None = None
        self._in_alt_screen: bool = False

    @property
    def in_alt_screen(self) -> bool:
        return self._in_alt_screen

    def set_mode(self, *modes, **kwargs) -> None:  # noqa: ANN002, ANN003
        """Override: intercept DEC 1049 to save the main buffer."""
        needs_alt = _ALT_SCREEN_MODE in modes
        if needs_alt and not self._in_alt_screen:
            # Save the current main buffer and cursor before switching
            self._saved_buffer = copy.deepcopy(dict(self.buffer))
            self._saved_cursor = copy.copy(self.cursor)
            self._in_alt_screen = True
        super().set_mode(*modes, **kwargs)
        if needs_alt and self._in_alt_screen:
            # Clear the screen for the alternate buffer
            self.erase_in_display(2)
            self.cursor_position()

    def reset_mode(self, *modes, **kwargs) -> None:  # noqa: ANN002, ANN003
        """Override: intercept DEC 1049 to restore the main buffer."""
        needs_restore = _ALT_SCREEN_MODE in modes
        super().reset_mode(*modes, **kwargs)
        if needs_restore and self._in_alt_screen:
            self._in_alt_screen = False
            if self._saved_buffer is not None:
                # Restore the saved main buffer
                self.buffer.clear()
                self.buffer.update(self._saved_buffer)
                self._saved_buffer = None
            if self._saved_cursor is not None:
                self.cursor = self._saved_cursor
                self._saved_cursor = None
