"""Tests for SDKWorker permission_mode + AppConfig (module-11/TASK-4)."""

from __future__ import annotations

import json

import pytest

from workflow_app.config.app_config import AppConfig
from workflow_app.domain import CommandSpec, InteractionType, ModelName

# ── Helpers ───────────────────────────────────────────────────────────────────


def _spec() -> CommandSpec:
    return CommandSpec(name="/test", model=ModelName.SONNET, interaction_type=InteractionType.AUTO)


# ── AppConfig ─────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def reset_config(tmp_path):
    """Isolate each test by redirecting AppConfig to a temp file."""
    original_path = AppConfig._CONFIG_PATH
    AppConfig._CONFIG_PATH = tmp_path / "config.json"
    AppConfig.reset()
    yield
    AppConfig._CONFIG_PATH = original_path
    AppConfig.reset()


def test_app_config_get_returns_built_in_default():
    assert AppConfig.get("default_permission_mode") == "acceptEdits"


def test_app_config_get_with_explicit_default():
    assert AppConfig.get("nonexistent_key", "fallback") == "fallback"


def test_app_config_get_unknown_key_without_default_returns_none():
    assert AppConfig.get("totally_unknown") is None


def test_app_config_set_persists_in_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(AppConfig, "_CONFIG_PATH", tmp_path / ".workflow-app" / "config.json")
    AppConfig.set("default_permission_mode", "manual")
    assert AppConfig.get("default_permission_mode") == "manual"


def test_app_config_set_writes_to_disk(tmp_path, monkeypatch):
    config_path = tmp_path / ".workflow-app" / "config.json"
    monkeypatch.setattr(AppConfig, "_CONFIG_PATH", config_path)
    AppConfig.set("default_permission_mode", "autoAccept")
    data = json.loads(config_path.read_text())
    assert data["default_permission_mode"] == "autoAccept"


def test_app_config_reload_from_disk_after_reset(tmp_path, monkeypatch):
    config_path = tmp_path / ".workflow-app" / "config.json"
    monkeypatch.setattr(AppConfig, "_CONFIG_PATH", config_path)
    AppConfig.set("default_permission_mode", "manual")
    AppConfig.reset()
    # After reset, next get() re-reads from disk
    assert AppConfig.get("default_permission_mode") == "manual"


def test_app_config_handles_corrupt_json(tmp_path, monkeypatch):
    config_dir = tmp_path / ".workflow-app"
    config_dir.mkdir(parents=True)
    config_path = config_dir / "config.json"
    config_path.write_text("NOT VALID JSON")
    monkeypatch.setattr(AppConfig, "_CONFIG_PATH", config_path)
    # Must fall back to defaults without raising
    assert AppConfig.get("default_permission_mode") == "acceptEdits"


def test_app_config_missing_file_returns_default(tmp_path, monkeypatch):
    monkeypatch.setattr(
        AppConfig, "_CONFIG_PATH", tmp_path / "nonexistent" / "config.json"
    )
    assert AppConfig.get("default_permission_mode") == "acceptEdits"


# ── SDKWorker permission_mode ─────────────────────────────────────────────────


def test_sdk_worker_default_permission_mode(qapp):
    from workflow_app.sdk.sdk_worker import SDKWorker

    worker = SDKWorker(command_spec=_spec(), workspace_dir="/tmp")
    assert worker._permission_mode == "acceptEdits"


def test_sdk_worker_accepts_accept_edits(qapp):
    from workflow_app.sdk.sdk_worker import SDKWorker

    worker = SDKWorker(command_spec=_spec(), workspace_dir="/tmp", permission_mode="acceptEdits")
    assert worker._permission_mode == "acceptEdits"


def test_sdk_worker_accepts_auto_accept(qapp):
    from workflow_app.sdk.sdk_worker import SDKWorker

    worker = SDKWorker(command_spec=_spec(), workspace_dir="/tmp", permission_mode="autoAccept")
    assert worker._permission_mode == "autoAccept"


def test_sdk_worker_accepts_manual(qapp):
    from workflow_app.sdk.sdk_worker import SDKWorker

    worker = SDKWorker(command_spec=_spec(), workspace_dir="/tmp", permission_mode="manual")
    assert worker._permission_mode == "manual"


def test_sdk_worker_rejects_invalid_permission_mode(qapp):
    from workflow_app.sdk.sdk_worker import SDKWorker

    with pytest.raises(ValueError, match="permission_mode inválido"):
        SDKWorker(command_spec=_spec(), workspace_dir="/tmp", permission_mode="invalid")


def test_sdk_worker_rejects_empty_string(qapp):
    from workflow_app.sdk.sdk_worker import SDKWorker

    with pytest.raises(ValueError):
        SDKWorker(command_spec=_spec(), workspace_dir="/tmp", permission_mode="")


def test_sdk_worker_rejects_none_permission_mode(qapp):
    from workflow_app.sdk.sdk_worker import SDKWorker

    with pytest.raises((ValueError, TypeError)):
        SDKWorker(command_spec=_spec(), workspace_dir="/tmp", permission_mode=None)
