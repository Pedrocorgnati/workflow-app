"""Tests for ExtrasOrchestrator (module-15/TASK-4)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from workflow_app.core.extras_orchestrator import ExtrasOrchestrator


@pytest.fixture()
def mock_bus():
    bus = MagicMock()
    bus.pipeline_status_changed.connect = MagicMock()
    bus.token_update = MagicMock()
    bus.git_info_updated = MagicMock()
    return bus


def test_token_update_emitted_after_command(mock_bus):
    mock_tracker = MagicMock()
    mock_tracker.get_session_total.return_value = (5000, 2000, 0.045)

    orch = ExtrasOrchestrator(
        mock_bus,
        token_tracker=mock_tracker,
    )
    orch.on_command_completed(
        pipeline_id=1, command_id=10,
        model="sonnet", tokens_in=5000, tokens_out=2000,
    )

    mock_tracker.record.assert_called_once()
    mock_bus.token_update.emit.assert_called_once_with(5000, 2000, 0.045)


def test_no_token_emit_when_zero_tokens(mock_bus):
    mock_tracker = MagicMock()

    orch = ExtrasOrchestrator(mock_bus, token_tracker=mock_tracker)
    orch.on_command_completed(
        pipeline_id=1, command_id=10,
        model="sonnet", tokens_in=0, tokens_out=0,
    )

    mock_tracker.record.assert_not_called()
    mock_bus.token_update.emit.assert_not_called()


def test_pipeline_done_calls_notification(mock_bus):
    mock_notif = MagicMock()

    orch = ExtrasOrchestrator(mock_bus, notification_service=mock_notif)
    orch.on_pipeline_done("meu-projeto", "02:30", errors=0)

    mock_notif.notify_pipeline_done.assert_called_once_with("meu-projeto", "02:30", 0)


def test_works_without_any_extras(mock_bus):
    """Orchestrator sem nenhum extra não deve levantar exceção."""
    orch = ExtrasOrchestrator(mock_bus)
    orch.on_command_completed(1, 10, "sonnet", 100, 50)
    orch.on_pipeline_done("proj", "01:00", 0)
    orch.on_command_error("/cmd", "erro")
    orch.on_pipeline_paused("/cmd")


def test_command_error_calls_notification(mock_bus):
    mock_notif = MagicMock()

    orch = ExtrasOrchestrator(mock_bus, notification_service=mock_notif)
    orch.on_command_error("/prd-create", "falha ao executar")

    mock_notif.notify_command_error.assert_called_once_with("/prd-create", "falha ao executar")


def test_pipeline_paused_calls_notification(mock_bus):
    mock_notif = MagicMock()

    orch = ExtrasOrchestrator(mock_bus, notification_service=mock_notif)
    orch.on_pipeline_paused("/some-cmd")

    mock_notif.notify_pipeline_paused.assert_called_once_with("/some-cmd")


def test_on_pipeline_status_shows_tray_icon_executing(mock_bus):
    mock_notif = MagicMock()

    orch = ExtrasOrchestrator(mock_bus, notification_service=mock_notif)
    orch._on_pipeline_status(1, "executando")

    mock_notif.show_tray_icon.assert_called_once_with(executing=True)


def test_on_pipeline_status_concluido(mock_bus):
    mock_notif = MagicMock()

    orch = ExtrasOrchestrator(mock_bus, notification_service=mock_notif)
    orch._on_pipeline_status(1, "concluido")

    mock_notif.show_tray_icon.assert_called_once_with(executing=False)


def test_on_pipeline_status_invalid_ignored(mock_bus):
    """Status inválido não deve levantar exceção."""
    mock_notif = MagicMock()

    orch = ExtrasOrchestrator(mock_bus, notification_service=mock_notif)
    orch._on_pipeline_status(1, "invalid_status")

    mock_notif.show_tray_icon.assert_not_called()


def test_notification_service_degrades_silently(qapp):
    """Smoke test: NotificationService sem bandeja do sistema."""
    from workflow_app.core.notification_service import NotificationService
    with patch(
        "workflow_app.core.notification_service.QSystemTrayIcon.isSystemTrayAvailable",
        return_value=False,
    ):
        svc = NotificationService()
        ok = svc.setup()
    assert ok is False
    assert svc.is_available is False
    svc.notify_pipeline_done("x", "00:01", 0)  # no-op


def test_set_workspace_root(mock_bus):
    """set_workspace_root define o path para GitInfoReader."""
    orch = ExtrasOrchestrator(mock_bus)
    orch.set_workspace_root("/tmp/my-project")
    assert orch._workspace_root == "/tmp/my-project"


def test_pipeline_done_shows_tray_not_executing(mock_bus):
    """on_pipeline_done deve chamar show_tray_icon(executing=False)."""
    mock_notif = MagicMock()
    orch = ExtrasOrchestrator(mock_bus, notification_service=mock_notif)
    orch.on_pipeline_done("proj", "01:00", errors=0)
    mock_notif.show_tray_icon.assert_called_once_with(executing=False)


def test_token_tracker_calculates_cost():
    """Smoke test: TokenTracker calcula custo corretamente."""
    from workflow_app.core.token_tracker import TokenTracker
    from workflow_app.domain import ModelType

    mock_cmd = MagicMock()
    mock_cmd.tokens_input = 0
    mock_cmd.tokens_output = 0
    mock_cmd.cost_usd = 0.0

    mock_session = MagicMock()
    mock_session.get.return_value = mock_cmd
    mock_session.__enter__ = lambda s: mock_session
    mock_session.__exit__ = MagicMock(return_value=False)

    db = MagicMock()
    db.get_session.return_value = mock_session

    tracker = TokenTracker(db)
    cost = tracker.record(1, 1_000_000, 0, ModelType.SONNET)
    assert cost == pytest.approx(3.0, rel=1e-4)  # 1_000_000 * 3 / 1_000_000 = 3.0
