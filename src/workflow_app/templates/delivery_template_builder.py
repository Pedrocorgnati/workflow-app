"""
Delivery Template Builder — Dynamic template generation based on MILESTONES.md.

Scans the docs_root/MILESTONES.md file for milestone entries and generates
the delivery pipeline with per-milestone auto-flow commands.

Two indicators available:
- delivery-pre: analyse → identify → create-tasks per milestone (before code)
- delivery-pos: qa-gate → mcp-review → sign-off → pending-actions per milestone (after code)
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from workflow_app.domain import CommandSpec, EffortLevel, InteractionType, ModelName

logger = logging.getLogger(__name__)

_O = ModelName.OPUS
_S = ModelName.SONNET
_A = InteractionType.AUTO


def _spec(
    name: str,
    model: ModelName,
    pos: int,
    effort: EffortLevel = EffortLevel.STANDARD,
) -> CommandSpec:
    return CommandSpec(
        name=name,
        model=model,
        interaction_type=_A,
        position=pos,
        effort=effort,
    )


def _discover_milestones(
    docs_root: str,
    project_dir: str,
    wbs_root: str = "",
) -> list[int]:
    """Discover milestone numbers from MILESTONES (seeded precedence).

    Precedence (matches /intake-review:create-checklist canonical pattern):
      1. {project_dir}/{wbs_root}/modules/MILESTONES.seeded.md (gerado por /intake-review:seed)
      2. {project_dir}/{docs_root}/MILESTONES.md (gerado por /modules:build-milestones)

    Both formats use sequential integer milestone numbers. The seeded format
    (per /intake-review:seed FASE 3.2) is now flat M1..M{total} — no decimals
    and no '+' suffix; sub-granularity that used to live in M{N}.{k} is hoisted
    into its own sequential milestone. Returns deduplicated, sorted integers.
    """
    canonical_path = Path(project_dir) / docs_root / "MILESTONES.md"
    seeded_path: Path | None = None
    if wbs_root:
        seeded_path = Path(project_dir) / wbs_root / "modules" / "MILESTONES.seeded.md"

    source_path: Path | None = None
    if seeded_path and seeded_path.is_file():
        source_path = seeded_path
        logger.info("Usando MILESTONES.seeded.md (gerado por /intake-review:seed): %s", seeded_path)
        # Staleness guard — seeded mais antigo que canonical indica base defasada.
        if canonical_path.is_file():
            try:
                if seeded_path.stat().st_mtime < canonical_path.stat().st_mtime:
                    logger.warning(
                        "MILESTONES.seeded.md eh mais antigo que MILESTONES.md — rode /intake-review:seed novamente se a base mudou"
                    )
            except OSError:
                pass
    elif canonical_path.is_file():
        source_path = canonical_path
        logger.info("Usando MILESTONES.md canonico: %s", canonical_path)
    else:
        logger.warning(
            "Nenhum MILESTONES encontrado (procurado em %s e %s)",
            seeded_path if seeded_path else "(wbs_root ausente)",
            canonical_path,
        )
        return []

    try:
        content = source_path.read_text(encoding="utf-8")
    except Exception as exc:
        logger.error("Failed to read %s: %s", source_path.name, exc)
        return []

    # Primary: canonical MILESTONES.md format — "Milestone N: ..." (integer labels).
    # Anchored to start-of-line to avoid duplicate matches from body references.
    primary = re.compile(r"^Milestone\s+(\d+)\s*:", re.IGNORECASE | re.MULTILINE)
    numbers: set[int] = {int(m.group(1)) for m in primary.finditer(content)}

    # Fallback: seeded sequential format — "### M{N} - ..." with N integer.
    # Per /intake-review:seed FASE 3.2 the seeded file is flat sequential
    # (no decimals, no '+'), so the same integer-only regex applies.
    if not numbers:
        seeded_pattern = re.compile(r"^#{1,4}\s+M(\d+)\b", re.MULTILINE)
        numbers = {int(m.group(1)) for m in seeded_pattern.finditer(content)}
        if numbers:
            logger.info(
                "Milestones parsed via seeded header format (M{N}) — found %d in %s",
                len(numbers), source_path.name,
            )

    if not numbers:
        logger.warning("No milestones found in %s at %s", source_path.name, source_path)
        return []

    return sorted(numbers)


def _renumber(specs: list[CommandSpec]) -> list[CommandSpec]:
    """Renumber positions 1..N."""
    for i, spec in enumerate(specs, start=1):
        spec.position = i
    return specs


def build_delivery_template(
    docs_root: str,
    project_dir: str,
    wbs_root: str = "",
) -> list[CommandSpec]:
    """Build the full delivery pipeline template (legacy — plan mode).

    Kept for backward compatibility. Generates /auto-flow delivery-pre milestone-{n}.
    """
    milestones = _discover_milestones(docs_root, project_dir, wbs_root)
    if not milestones:
        logger.error("No milestones found in MILESTONES.md under %s", docs_root)
        return []

    specs: list[CommandSpec] = []
    for n in milestones:
        specs.append(_spec("/clear", _S, 0))
        specs.append(_spec(f"/auto-flow delivery-pre milestone-{n}", _O, 0))

    logger.info(
        "Delivery template built: %d commands for %d milestones",
        len(specs), len(milestones),
    )
    return _renumber(specs)


def build_delivery_plan_template(
    docs_root: str,
    project_dir: str,
    wbs_root: str = "",
) -> list[CommandSpec]:
    """Build delivery PLAN template (before code exists).

    Per milestone: analyse → identify → create-tasks.
    Uses 'delivery-pre' indicator directly — no mode question needed.
    """
    milestones = _discover_milestones(docs_root, project_dir, wbs_root)
    if not milestones:
        logger.error("No milestones found in MILESTONES.md under %s", docs_root)
        return []

    specs: list[CommandSpec] = []
    for n in milestones:
        specs.append(_spec("/clear", _S, 0))
        specs.append(_spec(f"/auto-flow delivery-pre milestone-{n}", _O, 0))

    logger.info(
        "Delivery PLAN template built: %d commands for %d milestones",
        len(specs), len(milestones),
    )
    return _renumber(specs)


def build_delivery_qa_template(
    docs_root: str,
    project_dir: str,
    wbs_root: str = "",
) -> list[CommandSpec]:
    """Build delivery QA template (after code exists).

    Per milestone: qa-gate → fix (if needed) → mcp-review → sign-off → pending-actions.
    Uses 'delivery-pos' indicator directly — no mode question needed.
    """
    milestones = _discover_milestones(docs_root, project_dir, wbs_root)
    if not milestones:
        logger.error("No milestones found in MILESTONES.md under %s", docs_root)
        return []

    specs: list[CommandSpec] = []
    for n in milestones:
        specs.append(_spec("/clear", _S, 0))
        specs.append(_spec(f"/auto-flow delivery-pos milestone-{n}", _O, 0))

    logger.info(
        "Delivery QA template built: %d commands for %d milestones",
        len(specs), len(milestones),
    )
    return _renumber(specs)
