"""Runtime paths shared by source, wheel and PyInstaller executions."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def workflow_app_assets_dir() -> Path:
    """Return the directory containing Workflow App UI assets.

    Source checkouts keep ``assets`` at the project root. Installed wheels and
    PyInstaller builds place the same directory below the ``workflow_app``
    package, so frozen paths must be checked before checkout fallbacks.
    """
    override = os.environ.get("WORKFLOW_APP_ASSETS_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()

    package_dir = Path(__file__).resolve().parent
    candidates: list[Path] = []

    if getattr(sys, "frozen", False):
        bundle_dir = getattr(sys, "_MEIPASS", None)
        if bundle_dir:
            candidates.append(Path(bundle_dir) / "workflow_app" / "assets")

    candidates.extend(
        (
            package_dir / "assets",
            package_dir.parents[1] / "assets",
            Path(sys.executable).resolve().parent / "assets",
            Path(sys.executable).resolve().parent.parent / "assets",
            Path.cwd().resolve() / "assets",
        )
    )

    for candidate in candidates:
        if candidate.is_dir():
            return candidate

    return package_dir / "assets"


__all__ = ["workflow_app_assets_dir"]
