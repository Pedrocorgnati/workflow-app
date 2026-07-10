"""Unit tests for ``workflow_app.dcp.queue_derivation.enumerate_modules_on_disk``.

Covers the acceptance criteria of loop 07-09-modules-build-execute-btn task-002:
- numeric ordering (module-2 before module-10),
- ignoring `_shared` / `.DS_Store` / stray files,
- `[]` when `modules/` is absent,
- path-safety (R5): a symlink pointing outside `wbs_root` is rejected.
"""

from __future__ import annotations

from pathlib import Path

from workflow_app.dcp.queue_derivation import enumerate_modules_on_disk


def _make_module_dir(modules_dir: Path, name: str) -> Path:
    d = modules_dir / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def test_enumerate_modules_on_disk_orders_numerically(tmp_path: Path) -> None:
    wbs_root = tmp_path / "wbs"
    modules_dir = wbs_root / "modules"
    for name in ("module-10-foo", "module-2-bar", "module-1-baz"):
        _make_module_dir(modules_dir, name)

    result = enumerate_modules_on_disk(wbs_root)

    assert result == ["module-1-baz", "module-2-bar", "module-10-foo"]


def test_enumerate_modules_on_disk_tolerates_alpha_suffix(tmp_path: Path) -> None:
    wbs_root = tmp_path / "wbs"
    modules_dir = wbs_root / "modules"
    for name in ("module-6-foo", "module-6a-bar", "module-7-baz"):
        _make_module_dir(modules_dir, name)

    result = enumerate_modules_on_disk(wbs_root)

    assert result == ["module-6-foo", "module-6a-bar", "module-7-baz"]


def test_enumerate_modules_on_disk_ignores_non_matching_entries(tmp_path: Path) -> None:
    wbs_root = tmp_path / "wbs"
    modules_dir = wbs_root / "modules"
    _make_module_dir(modules_dir, "module-1-foo")
    _make_module_dir(modules_dir, "_shared")
    (modules_dir).mkdir(parents=True, exist_ok=True)
    (modules_dir / ".DS_Store").write_text("junk")
    (modules_dir / "README.md").write_text("junk")
    (modules_dir / "not-a-module-dir").mkdir()

    result = enumerate_modules_on_disk(wbs_root)

    assert result == ["module-1-foo"]


def test_enumerate_modules_on_disk_returns_empty_when_modules_dir_absent(
    tmp_path: Path,
) -> None:
    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir(parents=True, exist_ok=True)

    assert enumerate_modules_on_disk(wbs_root) == []


def test_enumerate_modules_on_disk_returns_empty_when_wbs_root_is_none() -> None:
    assert enumerate_modules_on_disk(None) == []


def test_enumerate_modules_on_disk_rejects_symlink_outside_wbs_root(
    tmp_path: Path,
) -> None:
    wbs_root = tmp_path / "wbs"
    modules_dir = wbs_root / "modules"
    _make_module_dir(modules_dir, "module-1-foo")

    outside_dir = tmp_path / "outside" / "module-2-evil"
    outside_dir.mkdir(parents=True, exist_ok=True)

    symlink_path = modules_dir / "module-2-evil"
    symlink_path.symlink_to(outside_dir, target_is_directory=True)

    result = enumerate_modules_on_disk(wbs_root)

    assert result == ["module-1-foo"]


def test_enumerate_modules_on_disk_accepts_symlink_inside_wbs_root(
    tmp_path: Path,
) -> None:
    wbs_root = tmp_path / "wbs"
    modules_dir = wbs_root / "modules"
    real_dir = wbs_root / "real-module-storage" / "module-3-linked"
    real_dir.mkdir(parents=True, exist_ok=True)
    modules_dir.mkdir(parents=True, exist_ok=True)

    symlink_path = modules_dir / "module-3-linked"
    symlink_path.symlink_to(real_dir, target_is_directory=True)

    result = enumerate_modules_on_disk(wbs_root)

    assert result == ["module-3-linked"]


def test_enumerate_modules_on_disk_ignores_broken_symlink(tmp_path: Path) -> None:
    wbs_root = tmp_path / "wbs"
    modules_dir = wbs_root / "modules"
    modules_dir.mkdir(parents=True, exist_ok=True)
    _make_module_dir(modules_dir, "module-1-foo")

    broken_symlink = modules_dir / "module-9-broken"
    broken_symlink.symlink_to(tmp_path / "does-not-exist", target_is_directory=True)

    result = enumerate_modules_on_disk(wbs_root)

    assert result == ["module-1-foo"]
