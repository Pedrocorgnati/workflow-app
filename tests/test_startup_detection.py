"""Tests for AppState and MainWindow startup detection (module-03/TASK-2)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from workflow_app.config.app_state import AppState, app_state
from workflow_app.config.config_parser import PipelineConfig


def _safe_disconnect(signal, slot) -> None:
    try:
        signal.disconnect(slot)
    except (RuntimeError, TypeError):
        pass


@pytest.fixture(autouse=True)
def reset_app_state():
    """Limpa o app_state antes e depois de cada teste."""
    app_state.clear_config()
    yield
    app_state.clear_config()
    for widget in QApplication.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QApplication.processEvents()


def _make_pipeline_config(tmp_path: Path, name: str = "test-app") -> PipelineConfig:
    return PipelineConfig(
        config_path=str(tmp_path / ".claude" / "project.json"),
        project_name=name,
        brief_root="b",
        docs_root="d",
        wbs_root="w",
        workspace_root="ws",
    )


class TestAppState:
    def test_initial_state(self):
        state = AppState()
        assert state.config is None
        assert not state.has_config
        assert state.project_name == ""

    def test_set_config(self, tmp_path):
        cfg = _make_pipeline_config(tmp_path)
        state = AppState()
        state.set_config(cfg)
        assert state.has_config
        assert state.project_name == "test-app"
        assert state.config is cfg

    def test_clear_config(self, tmp_path):
        cfg = _make_pipeline_config(tmp_path)
        state = AppState()
        state.set_config(cfg)
        state.clear_config()
        assert not state.has_config
        assert state.project_name == ""
        assert state.config is None

    def test_singleton_shared_state(self, tmp_path):
        """O singleton app_state é partilhado."""
        cfg = _make_pipeline_config(tmp_path)
        app_state.set_config(cfg)
        # Importar de novo deve retornar a mesma instância
        from workflow_app.config.app_state import app_state as app_state2
        assert app_state2.has_config
        assert app_state2.project_name == "test-app"


class TestMainWindowStartup:
    def test_startup_never_autoloads_config(self, qapp):
        """Multi-instance safety: o startup NUNCA auto-carrega um projeto.

        Mesmo com um lastConfigPath valido persistido em QSettings, abrir uma
        nova MainWindow deve resultar em app_state sem config (pill sem selecao,
        queue-command-list vazio). A escolha de contexto e sempre manual.
        """
        # Persistir um lastConfigPath valido ANTES de instanciar a janela.
        from PySide6.QtCore import QSettings

        from workflow_app.main_window import MainWindow
        settings = QSettings("SystemForge", "WorkflowApp")
        settings.setValue(MainWindow._SETTINGS_LAST_CONFIG, __file__)  # path existe

        try:
            window = MainWindow()
            assert not app_state.has_config
            assert window.windowTitle() == "SystemForge Desktop — Sem Projeto"
        finally:
            settings.remove(MainWindow._SETTINGS_LAST_CONFIG)

    def test_update_title_with_project(self, qapp):
        """MainWindow._update_title exibe título correto com projeto."""
        from workflow_app.main_window import MainWindow
        window = MainWindow()

        window._update_title("meu-app")
        assert window.windowTitle() == "meu-app — SystemForge Desktop"

    def test_update_title_without_project(self, qapp):
        from workflow_app.main_window import MainWindow
        window = MainWindow()

        window._update_title(None)
        assert window.windowTitle() == "SystemForge Desktop — Sem Projeto"

    def test_load_config_emits_signal(self, qapp, tmp_path):
        """_load_config emite signal_bus.config_loaded com o path correto."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        cfg_path = claude_dir / "project.json"
        cfg_path.write_text(json.dumps({
            "name": "test-project",
            "basic_flow": {
                "brief_root": "b", "docs_root": "d",
                "wbs_root": "w", "workspace_root": "ws",
            }
        }), encoding="utf-8")

        from workflow_app.main_window import MainWindow
        from workflow_app.signal_bus import signal_bus

        window = MainWindow()

        received_paths = []
        slot = received_paths.append
        signal_bus.config_loaded.connect(slot)

        try:
            window._load_config(str(cfg_path))
            assert received_paths == [str(cfg_path.resolve())]
        finally:
            _safe_disconnect(signal_bus.config_loaded, slot)

    def test_load_config_updates_app_state(self, qapp, tmp_path):
        """_load_config atualiza o AppState global."""
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        cfg_path = claude_dir / "project.json"
        cfg_path.write_text(json.dumps({
            "name": "my-project",
            "basic_flow": {
                "brief_root": "b", "docs_root": "d",
                "wbs_root": "w", "workspace_root": "ws",
            }
        }), encoding="utf-8")

        from workflow_app.main_window import MainWindow
        window = MainWindow()

        window._load_config(str(cfg_path))
        assert app_state.has_config
        assert app_state.project_name == "my-project"

    def test_load_config_invalid_shows_toast(self, qapp):
        """_load_config com path inválido exibe toast de erro e não altera estado."""
        from workflow_app.main_window import MainWindow
        window = MainWindow()

        # Startup nunca auto-carrega (multi-instance safety), mas mantemos o
        # clear defensivo caso um teste anterior tenha deixado estado residual.
        app_state.clear_config()

        from workflow_app.signal_bus import signal_bus
        toasts = []
        slot = lambda m, t: toasts.append((m, t))
        signal_bus.toast_requested.connect(slot)
        try:
            window._load_config("/nao/existe/project.json")
            assert not app_state.has_config
            assert any("Falha" in m for m, t in toasts)
        finally:
            _safe_disconnect(signal_bus.toast_requested, slot)

    def test_unload_config(self, qapp, tmp_path):
        """_unload_config limpa o AppState e emite config_unloaded."""
        cfg = _make_pipeline_config(tmp_path, "loaded-app")

        from workflow_app.main_window import MainWindow
        window = MainWindow()

        # Carregar manualmente apos o startup (que nunca auto-carrega).
        app_state.set_config(cfg)

        from workflow_app.signal_bus import signal_bus
        unloaded = []
        slot = lambda: unloaded.append(True)
        signal_bus.config_unloaded.connect(slot)

        try:
            window._unload_config()
            assert not app_state.has_config
            assert unloaded == [True]
            assert window.windowTitle() == "SystemForge Desktop — Sem Projeto"
        finally:
            _safe_disconnect(signal_bus.config_unloaded, slot)
