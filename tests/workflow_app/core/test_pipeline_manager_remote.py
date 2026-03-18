"""Unit tests for PipelineManager.send_interactive_response (remote module).

Tests the actual implementation: the method routes responses by response_type,
delegates to SDKAdapter for permissions, and returns bool.
First-response-wins is enforced by SignalBridge upstream (not tested here).
"""

from unittest.mock import MagicMock

import pytest


@pytest.fixture
def pm():
    """Minimal PipelineManager instance with mocked DI."""
    from workflow_app.pipeline.pipeline_manager import PipelineManager

    mock_bus = MagicMock()
    mock_bus.user_input_submitted = MagicMock()
    mock_bus.user_input_submitted.emit = MagicMock()

    mock_sdk = MagicMock()
    mock_sdk.respond_to_permission = MagicMock()

    manager = PipelineManager.__new__(PipelineManager)
    manager._signal_bus = mock_bus
    manager._sdk_adapter = mock_sdk
    manager._force_interactive_next_complete = False
    return manager


def test_text_input_routes_to_user_input_submitted(pm):
    result = pm.send_interactive_response(
        request_id="abc", value="my answer", response_type="text_input"
    )
    assert result is True
    pm._signal_bus.user_input_submitted.emit.assert_called_once_with("my answer")


def test_permission_approve_routes_to_sdk(pm):
    result = pm.send_interactive_response(
        request_id="abc", value="approve", response_type="permission"
    )
    assert result is True
    pm._sdk_adapter.respond_to_permission.assert_called_once_with(True)


def test_permission_deny_routes_to_sdk(pm):
    result = pm.send_interactive_response(
        request_id="abc", value="deny", response_type="permission"
    )
    assert result is True
    pm._sdk_adapter.respond_to_permission.assert_called_once_with(False)


def test_unknown_response_type_returns_false(pm):
    result = pm.send_interactive_response(
        request_id="abc", value="something", response_type="INVALID"
    )
    assert result is False
    pm._signal_bus.user_input_submitted.emit.assert_not_called()
    pm._sdk_adapter.respond_to_permission.assert_not_called()


def test_permission_without_sdk_adapter_returns_false(pm):
    pm._sdk_adapter = None
    result = pm.send_interactive_response(
        request_id="abc", value="approve", response_type="permission"
    )
    assert result is False


def test_appconfig_remote_mode_enabled_default():
    """AppConfig must have remote_mode_enabled defaulting to False."""
    from workflow_app.config.app_config import AppConfig

    AppConfig.reset()
    value = AppConfig.get("remote_mode_enabled")
    assert value is False


def test_signal_bus_has_remote_signals():
    """SignalBus must expose the remote-mode signals used by workflow-mobile."""
    from workflow_app.signal_bus import signal_bus

    assert hasattr(signal_bus, "remote_mode_toggle_requested")
    assert hasattr(signal_bus, "remote_server_started")
    assert hasattr(signal_bus, "remote_server_stopped")
    assert hasattr(signal_bus, "remote_client_connected")
    assert hasattr(signal_bus, "remote_client_disconnected")
