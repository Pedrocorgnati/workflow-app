"""ECU Audit específico para rock-3 (MetricsBar, History, Extras) (module-16/TASK-3).

Verifica as 4 regras de ECU para os componentes do rock-3:
1. Zero Orfãos: botões da MetricsBar têm tooltips e handlers
2. Zero Silêncio: MetricsBar responde visualmente a mudanças de estado
3. Zero Estados Indefinidos: History tem empty state definido
4. Zero Fluxos Incompletos: NotificationService não crasha sem bandeja
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch


def _make_metrics_bar_bus():
    """Cria mock de bus com todos os signals que MetricsBar usa."""
    bus = MagicMock()
    for attr in [
        "pipeline_ready", "pipeline_started", "pipeline_paused",
        "pipeline_resumed", "pipeline_completed", "pipeline_cancelled",
        "metrics_updated", "metrics_snapshot", "tool_use_started",
        "tool_use_completed", "token_update", "git_info_updated",
        "new_pipeline_requested", "history_panel_toggled", "preferences_requested",
    ]:
        mock_sig = MagicMock()
        mock_sig.connect = MagicMock()
        mock_sig.emit = MagicMock()
        setattr(bus, attr, mock_sig)
    return bus


def test_ecu_metrics_bar_all_buttons_have_tooltips(qapp):
    """ECU Rule 1: MetricsBar — botões de ação têm tooltip definido."""
    from workflow_app.metrics_bar.metrics_bar import MetricsBar

    bus = _make_metrics_bar_bus()
    bar = MetricsBar(bus)

    for btn_name in ["_btn_remote", "_btn_copy_ip", "_btn_prefs"]:
        btn = getattr(bar, btn_name)
        assert btn.toolTip() != "", f"ECU FAIL: {btn_name} sem tooltip"


def test_ecu_metrics_bar_status_feedback(qapp):
    """ECU Rule 2: MetricsBar produz feedback visual com métricas de token."""
    from workflow_app.metrics_bar.metrics_bar import MetricsBar

    bus = _make_metrics_bar_bus()
    bar = MetricsBar(bus)

    # Antes de token_update: label de tokens está oculta
    assert bar._lbl_tokens.isHidden()

    # Simular token_update → exibe label
    bar._on_token_update(5000, 2000, 0.05)
    assert not bar._lbl_tokens.isHidden(), "ECU FAIL: _lbl_tokens deve exibir após token_update"
    assert "↑5k" in bar._lbl_tokens.text(), "ECU FAIL: token count não exibido"


def test_ecu_history_empty_state(qapp):
    """ECU Rule 3: ExecutionHistoryWidget tem empty state definido."""
    from workflow_app.history.history_manager import HistoryManager
    from workflow_app.widgets.execution_history_widget import ExecutionHistoryWidget

    session_factory = MagicMock()
    mock_session = MagicMock()
    mock_session.query.return_value.filter.return_value.count.return_value = 0
    mock_session.query.return_value.filter.return_value.order_by.return_value.offset.return_value.limit.return_value.all.return_value = []
    mock_session.__enter__ = lambda s: mock_session
    mock_session.__exit__ = MagicMock(return_value=False)
    session_factory.return_value = mock_session

    mgr = HistoryManager(session_factory)
    widget = ExecutionHistoryWidget(mgr)

    # Deve exibir empty state text, não tela em branco
    assert widget._list.count() == 1  # "Nenhuma execução encontrada"
    assert "Nenhum" in widget._list.item(0).text()


def test_ecu_notification_service_no_crash(qapp):
    """ECU Rule 4: NotificationService não crasha em ambiente sem bandeja."""
    from workflow_app.core.notification_service import NotificationService

    with patch(
        "workflow_app.core.notification_service.QSystemTrayIcon.isSystemTrayAvailable",
        return_value=False,
    ):
        svc = NotificationService()
        ok = svc.setup()

    assert ok is False
    # Chamadas no-op não devem levantar exceção
    svc.notify_pipeline_done("proj", "01:00", errors=0)
    svc.notify_command_error("/cmd", "erro")
