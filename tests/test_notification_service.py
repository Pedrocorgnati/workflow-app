"""Tests for NotificationService (module-15/TASK-2)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from workflow_app.core.notification_service import NotificationService


def test_notification_service_degrades_silently_when_tray_not_available(qapp):
    """NotificationService não deve levantar exceção sem bandeja do sistema."""
    with patch(
        "workflow_app.core.notification_service.QSystemTrayIcon.isSystemTrayAvailable",
        return_value=False,
    ):
        service = NotificationService()
        result = service.setup()

    assert result is False
    assert service.is_available is False

    # Chamadas subsequentes devem ser no-ops silenciosas
    service.notify_pipeline_done("proj", "01:30", errors=0)
    service.notify_command_error("/cmd", "algum erro")
    service.notify_pipeline_paused("/cmd")


def test_notify_pipeline_done_calls_show_message(qapp):
    """Com bandeja disponível, showMessage deve ser chamado."""
    with patch(
        "workflow_app.core.notification_service.QSystemTrayIcon.isSystemTrayAvailable",
        return_value=True,
    ):
        service = NotificationService()
        mock_tray = MagicMock()
        service._tray = mock_tray
        service._available = True

        service.notify_pipeline_done("meu-projeto", "02:30", errors=0)

        mock_tray.showMessage.assert_called_once()
        call_args = mock_tray.showMessage.call_args
        assert "Pipeline Concluído" in call_args[0][0]
        assert "meu-projeto" in call_args[0][1]


def test_notify_command_error_truncates_long_message(qapp):
    with patch(
        "workflow_app.core.notification_service.QSystemTrayIcon.isSystemTrayAvailable",
        return_value=True,
    ):
        service = NotificationService()
        mock_tray = MagicMock()
        service._tray = mock_tray
        service._available = True

        long_error = "x" * 200
        service.notify_command_error("/cmd", long_error)

        call_args = mock_tray.showMessage.call_args[0][1]
        assert len(call_args) <= len("/cmd\n") + 103  # 100 + "..."


def test_notify_pipeline_done_with_errors_uses_warning_icon(qapp):
    with patch(
        "workflow_app.core.notification_service.QSystemTrayIcon.isSystemTrayAvailable",
        return_value=True,
    ):
        service = NotificationService()
        mock_tray = MagicMock()
        service._tray = mock_tray
        service._available = True

        service.notify_pipeline_done("proj", "01:00", errors=2)

        call_args = mock_tray.showMessage.call_args[0]
        assert "Erros" in call_args[0] or "erro" in call_args[1]


def test_notify_pipeline_paused_calls_show_message(qapp):
    service = NotificationService()
    mock_tray = MagicMock()
    service._tray = mock_tray
    service._available = True

    service.notify_pipeline_paused("/my-cmd")

    mock_tray.showMessage.assert_called_once()
    call_args = mock_tray.showMessage.call_args[0]
    assert "Pipeline Pausado" in call_args[0]
    assert "/my-cmd" in call_args[1]


def test_show_tray_icon_sets_tooltip(qapp):
    service = NotificationService()
    mock_tray = MagicMock()
    mock_tray.isVisible.return_value = False
    service._tray = mock_tray
    service._available = True

    service.show_tray_icon(executing=True)

    mock_tray.setToolTip.assert_called_with("SystemForge Desktop — Executando")
    mock_tray.show.assert_called_once()


def test_hide_tray_icon(qapp):
    """hide_tray_icon() deve chamar hide() no tray."""
    service = NotificationService()
    mock_tray = MagicMock()
    service._tray = mock_tray

    service.hide_tray_icon()

    mock_tray.hide.assert_called_once()
