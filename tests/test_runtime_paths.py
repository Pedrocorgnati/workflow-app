from __future__ import annotations

import sys
from pathlib import Path

from workflow_app.runtime_paths import workflow_app_assets_dir


def test_assets_dir_uses_explicit_override(tmp_path, monkeypatch):
    assets = tmp_path / "custom-assets"
    monkeypatch.setenv("WORKFLOW_APP_ASSETS_DIR", str(assets))

    assert workflow_app_assets_dir() == assets.resolve()


def test_assets_dir_uses_pyinstaller_bundle(tmp_path, monkeypatch):
    assets = tmp_path / "workflow_app" / "assets"
    assets.mkdir(parents=True)
    monkeypatch.delenv("WORKFLOW_APP_ASSETS_DIR", raising=False)
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)

    assert workflow_app_assets_dir() == assets


def test_assets_dir_resolves_source_checkout(monkeypatch):
    monkeypatch.delenv("WORKFLOW_APP_ASSETS_DIR", raising=False)
    monkeypatch.delattr(sys, "frozen", raising=False)
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)

    assets = workflow_app_assets_dir()

    assert assets == Path(__file__).resolve().parents[1] / "assets"
    assert (assets / "xterm" / "index.html").is_file()
