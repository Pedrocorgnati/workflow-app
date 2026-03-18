"""
Tests for SDKAdapter auth checks (module-08/TASK-2/ST004).

Covers:
  - check_sdk_available() returns True/False based on find_spec
  - check_auth() returns True/False based on claude CLI exit code
  - ensure_sdk_ready() raises correct errors
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from workflow_app.errors import SDKNotAuthenticatedError, SDKNotAvailableError
from workflow_app.sdk.sdk_adapter import SDKAdapter


class TestCheckSdkAvailable:
    def test_returns_true_when_sdk_installed(self):
        adapter = SDKAdapter()
        with patch(
            "workflow_app.sdk.sdk_adapter.find_spec", return_value=MagicMock()
        ):
            assert adapter.check_sdk_available() is True

    def test_returns_false_when_sdk_not_installed(self):
        adapter = SDKAdapter()
        with patch("workflow_app.sdk.sdk_adapter.find_spec", return_value=None):
            assert adapter.check_sdk_available() is False


class TestCheckAuth:
    def test_returns_true_when_claude_available(self):
        adapter = SDKAdapter()
        mock_result = MagicMock()
        mock_result.returncode = 0
        with patch("subprocess.run", return_value=mock_result):
            assert adapter.check_auth() is True

    def test_returns_false_when_auth_check_fails(self):
        adapter = SDKAdapter()
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert adapter.check_auth() is False

    def test_returns_false_on_nonzero_exit(self):
        adapter = SDKAdapter()
        mock_result = MagicMock()
        mock_result.returncode = 1
        with patch("subprocess.run", return_value=mock_result):
            assert adapter.check_auth() is False

    def test_returns_false_on_timeout(self):
        """GAP-003: TimeoutExpired should return False."""
        import subprocess

        adapter = SDKAdapter()
        with patch(
            "subprocess.run",
            side_effect=subprocess.TimeoutExpired(cmd="claude", timeout=5),
        ):
            assert adapter.check_auth() is False

    def test_returns_false_on_os_error(self):
        """GAP-003: OSError should return False."""
        adapter = SDKAdapter()
        with patch("subprocess.run", side_effect=OSError("Permission denied")):
            assert adapter.check_auth() is False


class TestEnsureSdkReady:
    def test_raises_sdk_not_available_when_missing(self):
        adapter = SDKAdapter()
        with patch.object(adapter, "check_sdk_available", return_value=False):
            with pytest.raises(SDKNotAvailableError, match="pip install"):
                adapter.ensure_sdk_ready()

    def test_raises_sdk_not_authenticated_when_not_authed(self):
        adapter = SDKAdapter()
        with patch.object(adapter, "check_sdk_available", return_value=True):
            with patch.object(adapter, "check_auth", return_value=False):
                with pytest.raises(SDKNotAuthenticatedError, match="claude auth login"):
                    adapter.ensure_sdk_ready()

    def test_does_not_raise_when_everything_ok(self):
        adapter = SDKAdapter()
        with patch.object(adapter, "check_sdk_available", return_value=True):
            with patch.object(adapter, "check_auth", return_value=True):
                adapter.ensure_sdk_ready()  # no exception
