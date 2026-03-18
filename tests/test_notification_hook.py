"""
Tests for _NotificationHook (module-08/TASK-4/ST004).

Covers:
  - Parses thinking/tool_use/response notification types
  - Parses dict notifications
  - Returns unknown for unrecognized type
  - Does not propagate exceptions (informational hook)
  - Emits agent_status_updated on valid notification
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from workflow_app.sdk.sdk_adapter import _NotificationHook


class TestNotificationHookParsing:
    def test_parses_thinking_notification(self):
        hook = _NotificationHook()
        notif = MagicMock()
        notif.type = "thinking"
        result = hook._parse_notification(notif)
        assert result == "thinking"

    def test_parses_tool_use_with_name(self):
        hook = _NotificationHook()
        notif = MagicMock()
        notif.type = "tool_use"
        notif.tool_name = "Bash"
        result = hook._parse_notification(notif)
        assert result == "tool_use: Bash"

    def test_parses_response_notification(self):
        hook = _NotificationHook()
        notif = MagicMock()
        notif.type = "response"
        result = hook._parse_notification(notif)
        assert result == "response"

    def test_parses_dict_notification(self):
        hook = _NotificationHook()
        notif = {"type": "tool_use", "tool_name": "Read"}
        result = hook._parse_notification(notif)
        assert result == "tool_use: Read"

    def test_tool_use_without_name_returns_desconhecida(self):
        """GAP-005: tool_use without tool_name or name falls back to 'desconhecida'."""
        hook = _NotificationHook()
        notif = MagicMock(spec=[])
        notif.type = "tool_use"
        result = hook._parse_notification(notif)
        assert result == "tool_use: desconhecida"

    def test_unknown_type_returns_unknown(self):
        hook = _NotificationHook()
        notif = MagicMock()
        notif.type = None
        result = hook._parse_notification(notif)
        assert "unknown" in result.lower()


class TestNotificationHookDoesNotPropagate:
    def test_exception_in_parse_does_not_raise(self):
        hook = _NotificationHook()

        # MagicMock with side_effect raises when called as function,
        # but getattr(obj, "type") on a MagicMock returns another MagicMock.
        # To simulate a broken notification, use a class that raises on getattr.
        class BreakingNotif:
            @property
            def type(self):
                raise RuntimeError("SDK error")

        with patch("workflow_app.sdk.sdk_adapter.signal_bus"):
            # Must not raise
            hook(notification=BreakingNotif())

    def test_emits_signal_on_valid_notification(self):
        hook = _NotificationHook()
        notif = MagicMock()
        notif.type = "thinking"

        with patch(
            "workflow_app.sdk.sdk_adapter.signal_bus"
        ) as mock_bus:
            hook(notification=notif)

        mock_bus.agent_status_updated.emit.assert_called_once_with("thinking")
