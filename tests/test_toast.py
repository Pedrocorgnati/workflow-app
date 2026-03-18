"""Tests for ToastNotification widget (module-02/TASK-6)."""

from __future__ import annotations

from workflow_app.widgets.notification_banner import (
    NotificationBanner,
    ToastManager,
    ToastNotification,
)


class TestToastNotification:
    def test_instantiates(self, qapp):
        toast = ToastNotification()
        assert toast is not None

    def test_show_toast_info(self, qapp):
        toast = ToastNotification()
        # Should not raise
        toast.show_toast("Hello", "info")

    def test_show_toast_success(self, qapp):
        toast = ToastNotification()
        toast.show_toast("Done!", "success")

    def test_show_toast_error(self, qapp):
        toast = ToastNotification()
        toast.show_toast("Failed", "error")

    def test_show_toast_warning(self, qapp):
        toast = ToastNotification()
        toast.show_toast("Warning", "warning")

    def test_show_toast_unknown_type(self, qapp):
        """Unknown type should not raise (graceful fallback)."""
        toast = ToastNotification()
        toast.show_toast("Hmm", "unknown_type")

    def test_is_qwidget(self, qapp):
        from PySide6.QtWidgets import QWidget
        toast = ToastNotification()
        assert isinstance(toast, QWidget)


class TestNotificationBanner:
    def test_instantiates(self, qapp):
        banner = NotificationBanner()
        assert banner is not None

    def test_show_error(self, qapp):
        banner = NotificationBanner()
        banner.show_error("Something went wrong")
        assert banner.isVisible()

    def test_show_info(self, qapp):
        banner = NotificationBanner()
        banner.show_info("FYI")
        assert banner.isVisible()

    def test_show_success(self, qapp):
        banner = NotificationBanner()
        banner.show_success("All good")
        assert banner.isVisible()

    def test_hide(self, qapp):
        banner = NotificationBanner()
        banner.show_error("err")
        banner.hide()
        assert not banner.isVisible()

    def test_is_qwidget(self, qapp):
        from PySide6.QtWidgets import QWidget
        banner = NotificationBanner()
        assert isinstance(banner, QWidget)


class TestToastManager:
    def test_instantiates(self, qapp):
        from PySide6.QtWidgets import QWidget
        parent = QWidget()
        parent.resize(800, 600)
        manager = ToastManager(parent)
        assert manager._toast is not None

    def test_signal_bus_triggers_toast(self, qapp):
        from PySide6.QtWidgets import QWidget

        from workflow_app.signal_bus import signal_bus

        parent = QWidget()
        parent.resize(800, 600)
        manager = ToastManager(parent)
        signal_bus.toast_requested.emit("Test via bus!", "info")
        assert manager._toast._message.text() == "Test via bus!"

    def test_show_message_alias(self, qapp):
        toast = ToastNotification()
        toast.show_message("Hello", "success")
        assert toast._message.text() == "Hello"
