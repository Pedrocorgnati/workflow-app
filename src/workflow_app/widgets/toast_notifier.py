"""
ToastNotifier — Floating toast notifications for the PC remote server feedback.

Displays up to MAX_ACTIVE_TOASTS stacked toasts in the bottom-right corner
of the parent window. Auto-dismisses after a level-dependent duration.

Levels and colours (Warm Charcoal Gold theme):
  info    — bg #292524, border #57534E, 5s
  success — bg #166534, border #15803D, 4s
  warning — bg #92400E, border #D97706, 6s
  error   — bg #7F1D1D, border #EF4444, 8s
"""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QLabel, QWidget

MAX_ACTIVE_TOASTS = 5
_TOAST_SPACING = 8   # px between stacked toasts
_TOAST_MARGIN = 20   # px from window edge

_LEVEL_STYLE: dict[str, tuple[str, str, int]] = {
    # level -> (bg_hex, border_hex, duration_ms)
    "info":    ("#292524", "#57534E", 5000),
    "success": ("#166534", "#15803D", 4000),
    "warning": ("#92400E", "#D97706", 6000),
    "error":   ("#7F1D1D", "#EF4444", 8000),
}


class _Toast(QLabel):
    """Single toast widget — auto-dismisses via QTimer."""

    def __init__(
        self,
        message: str,
        level: str,
        notifier: ToastNotifier,
        parent: QWidget,
    ) -> None:
        super().__init__(message, parent)
        self._notifier = notifier

        bg, border, duration = _LEVEL_STYLE.get(level, _LEVEL_STYLE["info"])
        self.setWordWrap(True)
        self.setMaximumWidth(400)
        self.setStyleSheet(
            f"background-color: {bg};"
            f"border: 1px solid {border};"
            "color: #FAFAF9;"
            "border-radius: 6px;"
            "padding: 12px 16px;"
        )
        self.adjustSize()
        self.show()

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._dismiss)
        self._timer.start(duration)

    def _dismiss(self) -> None:
        self._timer.stop()
        self._notifier._remove_toast(self)
        self.deleteLater()


class ToastNotifier:
    """
    Manages floating toast notifications anchored to the bottom-right corner
    of a parent QWidget (typically the MainWindow).

    Usage:
        notifier = ToastNotifier(main_window)
        notifier.show("Servidor ativo em 100.64.0.1:8765", "success")
    """

    def __init__(self, parent: QWidget) -> None:
        self._parent = parent
        self._active: list[_Toast] = []

    # ──────────────────────────────────────────────────── Public API ─── #

    def show(self, message: str, level: str = "info") -> None:
        """
        Display a toast notification.

        Args:
            message: Text to display (supports word-wrap, max 400px wide).
            level:   One of "info" | "success" | "warning" | "error".
        """
        if len(self._active) >= MAX_ACTIVE_TOASTS:
            return  # Silently discard beyond limit

        toast = _Toast(message, level, self, self._parent)
        self._active.append(toast)
        self._reposition()

    # ─────────────────────────────────────────────────── Internal ────── #

    def _remove_toast(self, toast: _Toast) -> None:
        if toast in self._active:
            self._active.remove(toast)
        self._reposition()

    def _reposition(self) -> None:
        """Stack toasts from bottom-right, growing upward."""
        p = self._parent
        x_base = p.width() - _TOAST_MARGIN
        y_base = p.height() - _TOAST_MARGIN

        for toast in reversed(self._active):
            toast.adjustSize()
            w = toast.width()
            h = toast.height()
            x = x_base - w
            y = y_base - h
            toast.move(max(0, x), max(0, y))
            y_base = y - _TOAST_SPACING
