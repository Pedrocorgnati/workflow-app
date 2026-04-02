"""
Pipeline research utilities for benchmark/scorecard/ledger workflows.

This module is intentionally lightweight and deterministic so it can be reused
by command runners, dry-run checks, and offline tooling.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import json


@dataclass(slots=True)
class Scorecard:
    run_id: str
    project_class: str
    quality_functional: float
    adherence_semantic: float
    stability: float
    efficiency: float
    simplicity: float

    def srs(self) -> float:
        """SystemForge Research Score (0..1 expected)."""
        return (
            0.35 * self.quality_functional
            + 0.25 * self.adherence_semantic
            + 0.20 * self.stability
            + 0.10 * self.efficiency
            + 0.10 * self.simplicity
        )


def ensure_research_dir(docs_root: str | Path) -> Path:
    root = Path(docs_root) / "_pipeline-research"
    root.mkdir(parents=True, exist_ok=True)
    return root


def write_scorecard(docs_root: str | Path, scorecard: Scorecard, regressions: list[str] | None = None) -> Path:
    """Persist scorecard in a stable JSON format."""
    regressions = regressions or []
    out_dir = ensure_research_dir(docs_root)
    payload = {
        "version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "run_id": scorecard.run_id,
        "project_class": scorecard.project_class,
        "metrics": {
            "quality_functional": scorecard.quality_functional,
            "adherence_semantic": scorecard.adherence_semantic,
            "stability": scorecard.stability,
            "efficiency": scorecard.efficiency,
            "simplicity": scorecard.simplicity,
            "srs": scorecard.srs(),
        },
        "regressions": regressions,
    }
    target = out_dir / "PIPELINE-SCORECARD.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return target


def append_ledger_row(
    docs_root: str | Path,
    run_id: str,
    command_name: str,
    variant_id: str,
    project_class: str,
    srs_before: float,
    srs_after: float,
    status: str,
    note: str = "",
) -> Path:
    """Append a TSV row to PIPELINE-RUNS.tsv creating header if missing."""
    out_dir = ensure_research_dir(docs_root)
    target = out_dir / "PIPELINE-RUNS.tsv"
    header = (
        "run_id\tcommand_name\tvariant_id\tproject_class\t"
        "srs_before\tsrs_after\tdelta\tstatus\tnote\n"
    )
    if not target.exists():
        target.write_text(header, encoding="utf-8")

    delta = srs_after - srs_before
    row = (
        f"{run_id}\t{command_name}\t{variant_id}\t{project_class}\t"
        f"{srs_before:.6f}\t{srs_after:.6f}\t{delta:.6f}\t{status}\t{note}\n"
    )
    with target.open("a", encoding="utf-8") as fh:
        fh.write(row)
    return target
