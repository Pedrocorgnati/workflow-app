"""Integration tests: RemoteServer → signal_bus.toast_requested (module-5 audit)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from workflow_app.remote.remote_server import RemoteServer


@pytest.fixture
def mock_bus():
    bus = MagicMock()
    return bus


@pytest.fixture
def server(qapp, mock_bus):
    return RemoteServer(mock_bus)


class TestRemoteServerToastFeedback:
    """Verify that RemoteServer.start() emits correct toasts via signal_bus."""

    def test_start_without_tailscale_emits_error_toast(self, server, mock_bus):
        """When Tailscale is not detected, an error toast must be emitted."""
        fake_result = MagicMock(success=False, error="not found")
        with patch(
            "workflow_app.remote.remote_server.TailscaleDetector"
        ) as MockDetector:
            MockDetector.return_value.detect.return_value = fake_result
            result = server.start()

        assert result is False
        # Find the toast_requested call with "error" level
        toast_calls = mock_bus.toast_requested.emit.call_args_list
        assert any(
            "Tailscale" in str(call) and "error" in str(call)
            for call in toast_calls
        ), f"Expected Tailscale error toast, got: {toast_calls}"

    def test_start_success_emits_success_toast(self, server, mock_bus):
        """When server starts successfully, a success toast with address must be emitted."""
        fake_result = MagicMock(success=True, ip="100.64.1.2")

        with (
            patch(
                "workflow_app.remote.remote_server.TailscaleDetector"
            ) as MockDetector,
            patch(
                "workflow_app.remote.remote_server.QWebSocketServer"
            ) as MockServer,
        ):
            MockDetector.return_value.detect.return_value = fake_result
            mock_ws = MockServer.return_value
            mock_ws.listen.return_value = True
            result = server.start()

        assert result is True
        toast_calls = mock_bus.toast_requested.emit.call_args_list
        assert any(
            "100.64.1.2" in str(call) and "success" in str(call)
            for call in toast_calls
        ), f"Expected success toast with address, got: {toast_calls}"

    def test_start_all_ports_busy_emits_error_toast(self, server, mock_bus):
        """When all ports are busy, an error toast about ports must be emitted."""
        fake_result = MagicMock(success=True, ip="100.64.1.2")

        with (
            patch(
                "workflow_app.remote.remote_server.TailscaleDetector"
            ) as MockDetector,
            patch(
                "workflow_app.remote.remote_server.QWebSocketServer"
            ) as MockServer,
        ):
            MockDetector.return_value.detect.return_value = fake_result
            mock_ws = MockServer.return_value
            mock_ws.listen.return_value = False  # All ports fail
            mock_ws.deleteLater = MagicMock()
            result = server.start()

        assert result is False
        toast_calls = mock_bus.toast_requested.emit.call_args_list
        assert any(
            "ocupadas" in str(call) and "error" in str(call)
            for call in toast_calls
        ), f"Expected ports-busy error toast, got: {toast_calls}"

    def test_port_fallback_emits_info_toasts(self, server, mock_bus):
        """When ports are tried and fail, info toasts should be emitted per port."""
        fake_result = MagicMock(success=True, ip="100.64.1.2")

        with (
            patch(
                "workflow_app.remote.remote_server.TailscaleDetector"
            ) as MockDetector,
            patch(
                "workflow_app.remote.remote_server.QWebSocketServer"
            ) as MockServer,
        ):
            MockDetector.return_value.detect.return_value = fake_result
            mock_ws = MockServer.return_value
            # First 2 ports fail, 3rd succeeds
            mock_ws.listen.side_effect = [False, False, True]
            result = server.start()

        assert result is True
        toast_calls = mock_bus.toast_requested.emit.call_args_list
        info_toasts = [
            call for call in toast_calls
            if "em uso" in str(call) and "info" in str(call)
        ]
        assert len(info_toasts) == 2, f"Expected 2 port-in-use info toasts, got {len(info_toasts)}: {info_toasts}"
