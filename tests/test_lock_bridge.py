"""Build-mode root resolution for the canonical delivery lock bridge."""

from __future__ import annotations

import sys
from pathlib import Path

from workflow_app.delivery import lock_bridge


def _make_systemforge_root(path: Path) -> Path:
    (path / ".claude" / "commands").mkdir(parents=True)
    (path / "CLAUDE.md").write_text("# test\n", encoding="utf-8")
    return path


def test_frozen_binary_resolves_root_from_real_executable(
    monkeypatch,
    tmp_path: Path,
) -> None:
    root = _make_systemforge_root(tmp_path / "systemForge")
    executable = root / "ai-forge" / "workflow-app" / "dist" / "workflow-app"
    executable.parent.mkdir(parents=True)
    executable.touch()

    extracted_file = tmp_path / "_MEI-test" / "workflow_app" / "delivery" / "lock_bridge.py"
    outside = tmp_path / "outside"
    outside.mkdir()

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(executable))
    monkeypatch.setattr(lock_bridge, "__file__", str(extracted_file))
    monkeypatch.chdir(outside)
    monkeypatch.delenv("SYSTEMFORGE_ROOT", raising=False)

    assert lock_bridge._find_systemforge_root() == root


def test_frozen_binary_resolves_explicit_root(
    monkeypatch,
    tmp_path: Path,
) -> None:
    root = _make_systemforge_root(tmp_path / "explicit-root")
    outside = tmp_path / "outside"
    outside.mkdir()

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(outside / "workflow-app"))
    monkeypatch.setattr(lock_bridge, "__file__", str(outside / "lock_bridge.py"))
    monkeypatch.chdir(outside)
    monkeypatch.setenv("SYSTEMFORGE_ROOT", str(root))

    assert lock_bridge._find_systemforge_root() == root
