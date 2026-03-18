"""Tests for PreferencesDialog (module-13/TASK-4)."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from workflow_app.config.app_config import AppConfig
from workflow_app.metrics_bar.preferences_dialog import (
    _DEFAULT_BUFFER_LIMIT,
    _DEFAULT_PERMISSION_MODE,
    _DEFAULT_TIMEOUT_SECONDS,
    PreferencesDialog,
)


@pytest.fixture(autouse=True)
def reset_config(tmp_path):
    """Isolate each test by redirecting AppConfig to a temp file."""
    original_path = AppConfig._CONFIG_PATH
    AppConfig._CONFIG_PATH = tmp_path / "config.json"
    AppConfig.reset()
    yield
    AppConfig._CONFIG_PATH = original_path
    AppConfig.reset()


@pytest.fixture()
def dlg(qapp):
    """Dialog instance with no db_manager (uses file-based AppConfig)."""
    return PreferencesDialog()


# ── Basic structure ──────────────────────────────────────────────────────── #


def test_dialog_opens_with_defaults(dlg):
    assert dlg._spin_buffer.value() == _DEFAULT_BUFFER_LIMIT
    assert dlg._spin_timeout.value() == _DEFAULT_TIMEOUT_SECONDS


def test_two_tabs_exist(dlg):
    assert dlg._tabs.count() == 2
    assert dlg._tabs.tabText(0) == "Geral"
    assert dlg._tabs.tabText(1) == "Execução"


def test_permission_combo_has_three_options(dlg):
    assert dlg._combo_permission.count() == 3


def test_default_permission_mode_selected(dlg):
    current_data = dlg._combo_permission.currentData()
    assert current_data == _DEFAULT_PERMISSION_MODE


# ── Restore defaults ─────────────────────────────────────────────────────── #


def test_restore_defaults_resets_values(dlg):
    dlg._spin_buffer.setValue(25_000)
    dlg._spin_timeout.setValue(600)

    with patch(
        "PySide6.QtWidgets.QMessageBox.question",
        return_value=0x00004000,  # QMessageBox.StandardButton.Yes
    ):
        dlg._restore_defaults()

    assert dlg._spin_buffer.value() == _DEFAULT_BUFFER_LIMIT
    assert dlg._spin_timeout.value() == _DEFAULT_TIMEOUT_SECONDS


def test_restore_defaults_cancelled_keeps_values(dlg):
    dlg._spin_buffer.setValue(25_000)

    with patch(
        "PySide6.QtWidgets.QMessageBox.question",
        return_value=0x00010000,  # QMessageBox.StandardButton.No
    ):
        dlg._restore_defaults()

    assert dlg._spin_buffer.value() == 25_000


# ── get_settings ─────────────────────────────────────────────────────────── #


def test_get_settings_returns_current_values(dlg):
    dlg._spin_buffer.setValue(20_000)
    dlg._spin_timeout.setValue(120)
    settings = dlg.get_settings()
    assert settings["buffer_limit"] == 20_000
    assert settings["timeout_seconds"] == 120


# ── db_manager compatibility ─────────────────────────────────────────────── #


def test_dialog_accepts_db_manager_arg(qapp):
    """PreferencesDialog(db_manager=...) should not raise."""
    mock_db = MagicMock()
    dlg = PreferencesDialog(mock_db)
    assert dlg._spin_buffer.value() == _DEFAULT_BUFFER_LIMIT


# ────────────────────────────────── _save (GAP-008) ─── #


class TestPreferencesDialogSave:
    """_save persists values via AppConfig and accepts dialog (GAP-008 fix)."""

    def test_save_calls_appconfig_set_for_buffer(self, dlg):
        dlg._spin_buffer.setValue(25_000)
        with patch.object(dlg, "accept"), \
             patch("workflow_app.metrics_bar.preferences_dialog.AppConfig") as MockCfg:
            dlg._save()
        MockCfg.set.assert_any_call("buffer_limit", 25_000)

    def test_save_calls_appconfig_set_for_timeout(self, dlg):
        dlg._spin_timeout.setValue(600)
        with patch.object(dlg, "accept"), \
             patch("workflow_app.metrics_bar.preferences_dialog.AppConfig") as MockCfg:
            dlg._save()
        MockCfg.set.assert_any_call("timeout_seconds", 600)

    def test_save_calls_appconfig_set_for_permission(self, dlg):
        dlg._combo_permission.setCurrentIndex(1)
        with patch.object(dlg, "accept"), \
             patch("workflow_app.metrics_bar.preferences_dialog.AppConfig") as MockCfg:
            dlg._save()
        MockCfg.set.assert_any_call("default_permission_mode", "autoAccept")

    def test_save_calls_accept(self, dlg):
        with patch.object(dlg, "accept") as mock_accept, \
             patch("workflow_app.metrics_bar.preferences_dialog.AppConfig"):
            dlg._save()
        mock_accept.assert_called_once()
