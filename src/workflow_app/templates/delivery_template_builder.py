"""
Delivery Template Builder — Dynamic template generation based on BUDGET.md milestones.

Scans the docs_root/BUDGET.md file for milestone entries and generates
the delivery pipeline with per-milestone auto-flow commands.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from workflow_app.domain import CommandSpec, InteractionType, ModelName

logger = logging.getLogger(__name__)

_O = ModelName.OPUS
_S = ModelName.SONNET
_A = InteractionType.AUTO


def _spec(name: str, model: ModelName, pos: int) -> CommandSpec:
    return CommandSpec(
        name=name,
        model=model,
        interaction_type=_A,
        position=pos,
    )


def _discover_milestones(docs_root: str, project_dir: str) -> list[int]:
    """Discover milestone numbers from BUDGET.md.

    Scans for patterns like "Milestone 1", "milestone-1", "## Milestone 1",
    "### Milestone 2" etc. in the BUDGET.md file.

    Returns sorted list of milestone numbers.
    """
    budget_path = Path(project_dir) / docs_root / "BUDGET.md"
    if not budget_path.is_file():
        # Try alternative paths
        for alt in ("project/BUDGET.md", "BUDGET.md"):
            alt_path = Path(project_dir) / docs_root / alt
            if alt_path.is_file():
                budget_path = alt_path
                break
        else:
            logger.warning("BUDGET.md not found in %s", docs_root)
            return []

    try:
        content = budget_path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.error("Failed to read BUDGET.md: %s", exc)
        return []

    # Match milestone references: "Milestone N", "milestone-N", "MILESTONE N"
    pattern = re.compile(r"milestone[\s\-_]*(\d+)", re.IGNORECASE)
    numbers = sorted(set(int(m.group(1)) for m in pattern.finditer(content)))

    if not numbers:
        logger.warning("No milestones found in BUDGET.md at %s", budget_path)

    return numbers


def build_delivery_template(docs_root: str, project_dir: str) -> list[CommandSpec]:
    """Build the delivery pipeline template dynamically.

    Scans BUDGET.md for milestones and generates:
    - /model choice at the start
    - Per milestone: /clear + /auto-flow delivery milestone-{n} json

    Args:
        docs_root: relative path to docs root (e.g. "output/docs/my-project")
        project_dir: absolute path to project directory

    Returns:
        list[CommandSpec] with all commands, positions renumbered 1..N
    """
    milestones = _discover_milestones(docs_root, project_dir)
    if not milestones:
        logger.error("No milestones found in BUDGET.md under %s", docs_root)
        return []

    specs: list[CommandSpec] = []

    # Per-milestone delivery commands
    for n in milestones:
        specs.append(_spec("/clear", _S, 0))
        specs.append(_spec(f"/auto-flow delivery milestone-{n}", _O, 0))

    # Renumber positions 1..N
    for i, spec in enumerate(specs, start=1):
        spec.position = i

    logger.info(
        "Delivery template built: %d commands for %d milestones",
        len(specs), len(milestones),
    )
    return specs
