"""
WBS Template Builder — Dynamic template generation based on existing modules.

Scans the wbs_root/modules/ directory for module-* folders and generates
the full WBS execution pipeline (F5→F9) with per-module execute+review pairs.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from workflow_app.domain import CommandSpec, InteractionType, ModelName

logger = logging.getLogger(__name__)

_O = ModelName.OPUS
_S = ModelName.SONNET
_H = ModelName.HAIKU
_A = InteractionType.AUTO


def _spec(name: str, model: ModelName, pos: int) -> CommandSpec:
    return CommandSpec(
        name=name,
        model=model,
        interaction_type=_A,
        position=pos,
    )


def _discover_modules(wbs_root: str, project_dir: str) -> list[str]:
    """Discover module folders under wbs_root/modules/.

    Returns sorted list of module folder paths relative to project_dir.
    E.g. ["output/wbs/proj/modules/module-01-auth", "output/wbs/proj/modules/module-02-db"]
    """
    modules_dir = Path(project_dir) / wbs_root / "modules"
    if not modules_dir.is_dir():
        logger.warning("WBS modules dir not found: %s", modules_dir)
        return []

    def _module_num(d: Path) -> int:
        m = re.search(r"module-(\d+)", d.name)
        return int(m.group(1)) if m else 0

    module_dirs = sorted(
        (d for d in modules_dir.iterdir()
         if d.is_dir() and re.match(r"module-\d+", d.name)),
        key=_module_num,
    )

    return [
        str(Path(wbs_root) / "modules" / d.name)
        for d in module_dirs
    ]


def build_wbs_template(wbs_root: str, project_dir: str) -> list[CommandSpec]:
    """Build the full WBS execution template dynamically.

    Scans wbs_root/modules/ for module folders and generates:
    1. auto-flow create {first} {last} — F5 create range
    2. validate-pipeline + reforge-pipeline
    3. front-end-build, back-end-build, db-migration-create
    4. create-assets, create-mocks, github-linking
    5. Per-module: auto-flow execute + review-executed-module
    6. milestone-checklist-review, reforge:prepare, reforge:fix
    7. F8: env-creation, create-test-user, seed-data-create, docker-create, integration-test-create
    Args:
        wbs_root: relative path to wbs root (e.g. "output/wbs/my-project")
        project_dir: absolute path to project directory

    Returns:
        list[CommandSpec] with all commands, positions renumbered 1..N
    """
    modules = _discover_modules(wbs_root, project_dir)
    if not modules:
        logger.error("No modules found in %s/modules/", wbs_root)
        return []

    specs: list[CommandSpec] = []

    # ── /clear at the start ───────────────────────────────────────────────────
    specs.append(_spec("/clear", _S, 0))

    # ── F5: Create per-module + validate ─────────────────────────────────────
    for module_path in modules:
        specs.append(_spec(f"/auto-flow create {module_path}", _S, 0))
    specs.append(_spec("/validate-pipeline", _S, 0))
    specs.append(_spec("/reforge-pipeline", _O, 0))

    # ── F7: Build phase ──────────────────────────────────────────────────────
    specs.append(_spec("/mobile-first-build", _S, 0))
    specs.append(_spec("/front-end-build", _S, 0))
    specs.append(_spec("/front-end-review", _S, 0))
    specs.append(_spec("/data-test-id", _S, 0))
    specs.append(_spec("/back-end-build", _S, 0))
    specs.append(_spec("/build-verify", _H, 0))
    specs.append(_spec("/db-migration-create", _S, 0))
    specs.append(_spec("/create-assets", _H, 0))
    specs.append(_spec("/create-mocks", _S, 0))
    specs.append(_spec("/github-linking", _H, 0))
    specs.append(_spec("/update-tasks:analyse", _S, 0))
    specs.append(_spec("/update-tasks:execute", _S, 0))

    # ── F7: Per-module execute + review ──────────────────────────────────────
    for module_path in modules:
        specs.append(_spec(f"/auto-flow execute {module_path}", _S, 0))
        specs.append(_spec(f"/review-executed-module {module_path}", _O, 0))

    # ── F7: Post-execution ───────────────────────────────────────────────────
    specs.append(_spec("/milestone-checklist-review", _S, 0))
    specs.append(_spec("/reforge:prepare", _S, 0))
    specs.append(_spec("/reforge:fix", _O, 0))

    # ── F8: Complemento ─────────────────────────────────────────────────────
    specs.append(_spec("/env-creation", _H, 0))
    specs.append(_spec("/create-test-user", _H, 0))
    specs.append(_spec("/seed-data-create", _S, 0))
    specs.append(_spec("/docker-create", _S, 0))
    specs.append(_spec("/integration-test-create", _S, 0))
    specs.append(_spec("/dev-bootstrap-create", _H, 0))
    specs.append(_spec("/infra-smoke-check", _H, 0))

    # ── Renumber positions 1..N ──────────────────────────────────────────────
    for i, spec in enumerate(specs, start=1):
        spec.position = i

    logger.info(
        "WBS template built: %d commands for %d modules",
        len(specs), len(modules),
    )
    return specs
