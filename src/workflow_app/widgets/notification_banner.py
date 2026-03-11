"""
NotificationBanner — Inline error/info banner for dialogs.
ToastNotification — Floating corner toast for main window.
"""

from __future__ import annotations

from PySide6.QtCore import QPropertyAnimation, QRect, Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget


class NotificationBanner(QWidget):
    """Inline notification bar shown inside dialogs (e.g. interview errors)."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("NotificationBanner")
        self.setVisible(False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        self._icon = QLabel()
        self._icon.setFixedWidth(16)
        layout.addWidget(self._icon)

        self._message = QLabel()
        self._message.setWordWrap(True)
        layout.addWidget(self._message, stretch=1)

        self._close_btn = QPushButton("✕")
        self._close_btn.setObjectName("IconButton")
        self._close_btn.setFixedSize(20, 20)
        self._close_btn.clicked.connect(self.hide)
        layout.addWidget(self._close_btn)

    def show_error(self, message: str) -> None:
        self._icon.setText("✕")
        self._message.setText(message)
        self.setProperty("type", "error")
        self.setStyleSheet(
            "background-color: #27272A; border-left: 3px solid #FB7185;"
            " border-radius: 4px; padding: 4px;"
        )
        self._message.setStyleSheet("color: #FAFAFA;")
        self.setVisible(True)

    def show_info(self, message: str) -> None:
        self._icon.setText("ℹ")
        self._message.setText(message)
        self.setProperty("type", "info")
        self.setStyleSheet(
            "background-color: #27272A; border-left: 3px solid #38BDF8;"
            " border-radius: 4px; padding: 4px;"
        )
        self._message.setStyleSheet("color: #FAFAFA;")
        self.setVisible(True)

    def show_success(self, message: str) -> None:
        self._icon.setText("✓")
        self._message.setText(message)
        self.setProperty("type", "success")
        self.setStyleSheet(
            "background-color: #27272A; border-left: 3px solid #34D399;"
            " border-radius: 4px; padding: 4px;"
        )
        self._message.setStyleSheet("color: #FAFAFA;")
        self.setVisible(True)


class ToastNotification(QWidget):
    """Floating bottom-right toast notification. Auto-dismisses after 3s."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ToastNotification")
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.ToolTip)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setVisible(False)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)

        self._icon = QLabel()
        layout.addWidget(self._icon)

        self._message = QLabel()
        self._message.setStyleSheet("color: #FAFAFA; font-size: 13px;")
        layout.addWidget(self._message)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

    def show_toast(self, message: str, msg_type: str = "info", duration_ms: int = 3000) -> None:
        colors = {
            "success": ("#16A34A", "✓"),
            "error":   ("#DC2626", "✕"),
            "warning": ("#D97706", "⚠"),
            "info":    ("#2563EB", "ℹ"),
        }
        bg, icon = colors.get(msg_type, colors["info"])
        self._icon.setText(icon)
        self._message.setText(message)
        self.setStyleSheet(
            f"background-color: {bg}; border-radius: 6px; padding: 4px 8px;"
        )
        self.adjustSize()

        if self.parent():
            parent_rect = self.parent().rect()
            x = parent_rect.width() - self.width() - 16
            y = parent_rect.height() - self.height() - 16
            self.move(x, y)

        self.setVisible(True)
        self.raise_()
        self._timer.start(duration_ms)
