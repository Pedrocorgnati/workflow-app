"""Tests for ConfigBar widget (module-03/TASK-3)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from PySide6.QtWidgets import QApplication

from workflow_app.config.app_state import app_state
from workflow_app.config.config_bar import ConfigBar
from workflow_app.config.config_parser import PipelineConfig
from workflow_app.signal_bus import signal_bus


def _make_config(tmp_path: Path, name: str = "test-app") -> PipelineConfig:
    return PipelineConfig(
        config_path=str(tmp_path / ".claude" / "project.json"),
        project_name=name,
        brief_root="b",
        docs_root="d",
        wbs_root="w",
        workspace_root="ws",
    )


@pytest.fixture(autouse=True)
def reset_state():
    """Limpa o app_state antes e depois de cada teste."""
    app_state.clear_config()
    yield
    app_state.clear_config()
    for widget in QApplication.topLevelWidgets():
        if isinstance(widget, ConfigBar):
            widget.close()
            widget.deleteLater()
    QApplication.processEvents()


class TestConfigBarEmptyState:
    def test_initial_empty_state(self, qapp):
        bar = ConfigBar()
        assert bar._name_label.text() == "Sem projeto"
        assert bar._close_btn.isHidden()
        assert not bar._select_btn.isHidden()

    def test_empty_state_tooltip_is_empty(self, qapp):
        bar = ConfigBar()
        assert bar._name_label.toolTip() == ""


class TestConfigBarLoadedState:
    def test_shows_project_name_when_config_set(self, qapp, tmp_path):
        cfg = _make_config(tmp_path)
        app_state.set_config(cfg)
        bar = ConfigBar()
        assert bar._name_label.text() == "test-app"
        assert not bar._close_btn.isHidden()
        assert bar._select_btn.isHidden()

    def test_updates_on_config_loaded_signal(self, qapp, tmp_path):
        bar = ConfigBar()
        cfg = _make_config(tmp_path, "signal-app")
        app_state.set_config(cfg)
        signal_bus.config_loaded.emit(cfg.config_path)
        assert bar._name_label.text() == "signal-app"

    def test_clears_on_config_unloaded_signal(self, qapp, tmp_path):
        cfg = _make_config(tmp_path)
        app_state.set_config(cfg)
        bar = ConfigBar()
        assert bar._name_label.text() == "test-app"

        app_state.clear_config()
        signal_bus.config_unloaded.emit()
        assert bar._name_label.text() == "Sem projeto"
        assert bar._close_btn.isHidden()
        assert not bar._select_btn.isHidden()


class TestConfigBarActions:
    def test_select_emits_config_change_requested(self, qapp, tmp_path):
        bar = ConfigBar()
        emitted = []
        bar.config_change_requested.connect(emitted.append)

        fake_path = str(tmp_path / "project.json")
        with patch(
            "workflow_app.config.config_bar.QFileDialog.getOpenFileName",
            return_value=(fake_path, ""),
        ):
            bar._on_select_clicked()

        assert emitted == [fake_path]

    def test_cancel_dialog_no_signal(self, qapp):
        bar = ConfigBar()
        emitted = []
        bar.config_change_requested.connect(emitted.append)

        with patch(
            "workflow_app.config.config_bar.QFileDialog.getOpenFileName",
            return_value=("", ""),
        ):
            bar._on_select_clicked()

        assert emitted == []

    def test_unload_button_emits_signal(self, qapp, tmp_path):
        cfg = _make_config(tmp_path)
        app_state.set_config(cfg)
        bar = ConfigBar()
        emitted = []
        bar.config_unload_requested.connect(lambda: emitted.append(True))
        bar._on_unload_clicked()
        assert emitted == [True]


class TestConfigBarTooltip:
    def test_tooltip_shows_relative_path(self, qapp, tmp_path, monkeypatch):
        """Tooltip exibe path relativo ao cwd."""
        monkeypatch.chdir(tmp_path)
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        cfg_path = claude_dir / "project.json"
        cfg_path.touch()

        cfg = PipelineConfig(
            config_path=str(cfg_path),
            project_name="rel-test",
            brief_root="b", docs_root="d",
            wbs_root="w", workspace_root="ws",
        )
        app_state.set_config(cfg)
        bar = ConfigBar()

        tooltip = bar._name_label.toolTip()
        assert ".claude" in tooltip
        assert "project.json" in tooltip

    def test_tooltip_absolute_when_outside_cwd(self, qapp, tmp_path):
        """Quando o config está fora do cwd, usa path absoluto."""
        cfg = PipelineConfig(
            config_path="/absolute/path/to/project.json",
            project_name="abs-test",
            brief_root="b", docs_root="d",
            wbs_root="w", workspace_root="ws",
        )
        app_state.set_config(cfg)
        bar = ConfigBar()

        tooltip = bar._name_label.toolTip()
        assert "project.json" in tooltip


class TestConfigBarCurrentConfig:
    def test_current_config_property(self, qapp, tmp_path):
        cfg = _make_config(tmp_path)
        app_state.set_config(cfg)
        bar = ConfigBar()
        assert bar.current_config is cfg

    def test_current_config_none_when_empty(self, qapp):
        bar = ConfigBar()
        assert bar.current_config is None
