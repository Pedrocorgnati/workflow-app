"""
ToastNotifier — Floating toast notifications for the PC remote server feedback.

Displays up to MAX_ACTIVE_TOASTS stacked toasts in the bottom-right corner
of the parent window. Auto-dismisses after a level-dependent duration.

Levels and colours (Warm Charcoal Gold theme):
  info    — bg #292524, border #57534E, 5s
  success — bg #166534, border #15803D, 4s
  warning — bg #92400E, border #D97706, 18s  (triplicado; alias "warn")
  error   — bg #7F1D1D, border #EF4444, 24s  (triplicado)

Para "error", "warning" e "warn": toast inclui botao de copiar a mensagem.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, QSize, Qt, QTimer
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

MAX_ACTIVE_TOASTS = 5
_TOAST_SPACING = 8   # px between stacked toasts
_TOAST_MARGIN = 20   # px from window edge

_LEVEL_STYLE: dict[str, tuple[str, str, int]] = {
    # level -> (bg_hex, border_hex, duration_ms)
    "info":    ("#292524", "#57534E",  5000),
    "success": ("#166534", "#15803D",  4000),
    "warning": ("#92400E", "#D97706", 18000),   # era 6000 — triplicado
    "warn":    ("#92400E", "#D97706", 18000),   # alias de "warning"
    "error":   ("#7F1D1D", "#EF4444", 24000),   # era 8000 — triplicado
}

# Levels que ganham botao de copiar
_COPY_BTN_LEVELS = frozenset({"error", "warning", "warn"})


def _load_copy_icon() -> QIcon | None:
    """Carrega copy.svg tintado em branco do diretorio assets; retorna None se indisponivel."""
    try:
        from PySide6.QtSvg import QSvgRenderer
    except ImportError:
        return None
    svg_path = Path(__file__).resolve().parents[3] / "assets" / "copy.svg"
    if not svg_path.is_file():
        return None
    try:
        raw = svg_path.read_text(encoding="utf-8")
    except OSError:
        return None
    tinted = raw.replace("currentColor", "#FAFAF9")
    renderer = QSvgRenderer(QByteArray(tinted.encode("utf-8")))
    if not renderer.isValid():
        return None
    pixmap = QPixmap(QSize(14, 14))
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    try:
        renderer.render(painter)
    finally:
        painter.end()
    icon = QIcon()
    icon.addPixmap(pixmap)
    return icon


class _Toast(QWidget):
    """Single toast widget — auto-dismisses via QTimer.

    Para levels "error", "warning" e "warn": inclui botao de copiar e
    dura 3x mais que o original. Levels "info" e "success" comportam-se
    como antes (sem botao de copiar).
    """

    def __init__(
        self,
        message: str,
        level: str,
        notifier: ToastNotifier,
        parent: QWidget,
    ) -> None:
        super().__init__(parent)
        self._notifier = notifier
        self._message = message

        bg, border, duration = _LEVEL_STYLE.get(level, _LEVEL_STYLE["info"])
        has_copy = level in _COPY_BTN_LEVELS

        self.setObjectName("_Toast")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setMaximumWidth(400)
        self.setStyleSheet(
            f"QWidget#_Toast {{ background-color: {bg};"
            f" border: 1px solid {border}; border-radius: 6px; }}"
            # Filhos: fundo transparente + sem borda (herdam o container)
            "QLabel { background: transparent; border: none;"
            " color: #FAFAF9; font-size: 12px; }"
        )

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        layout.setSpacing(6)

        msg_label = QLabel(message)
        msg_label.setWordWrap(True)
        msg_label.setMaximumWidth(376)  # 400 - 2*12 padding
        layout.addWidget(msg_label)

        if has_copy:
            btn_row = QWidget()
            btn_row.setStyleSheet("background: transparent; border: none;")
            btn_layout = QHBoxLayout(btn_row)
            btn_layout.setContentsMargins(0, 0, 0, 0)
            btn_layout.setSpacing(0)
            btn_layout.addStretch(1)

            copy_btn = QPushButton()
            copy_btn.setFixedSize(22, 22)
            copy_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            copy_btn.setToolTip("Copiar mensagem de erro")
            copy_btn.setStyleSheet(
                f"QPushButton {{ background-color: transparent; border: 1px solid {border};"
                " border-radius: 3px; color: #FAFAF9; font-size: 12px; padding: 2px; }}"
                "QPushButton:hover { background-color: rgba(255,255,255,0.12); }"
                "QPushButton:pressed { background-color: rgba(255,255,255,0.20); }"
            )
            copy_icon = _load_copy_icon()
            if copy_icon is not None:
                copy_btn.setIcon(copy_icon)
                copy_btn.setIconSize(QSize(12, 12))
            else:
                copy_btn.setText("⧉")  # ⊞ — mesmo fallback do CommandItemWidget
            copy_btn.clicked.connect(self._on_copy)
            btn_layout.addWidget(copy_btn)
            layout.addWidget(btn_row)

        self.adjustSize()
        self.show()

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._dismiss)
        self._timer.start(duration)

    def _on_copy(self) -> None:
        clipboard = QApplication.clipboard()
        if clipboard:
            clipboard.setText(self._message)

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
            level:   One of "info" | "success" | "warning" | "warn" | "error".
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
