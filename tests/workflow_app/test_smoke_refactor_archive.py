"""T4 smoke - end-to-end validation that the runtime emits canonical specs.

This test loads the predecessor archive `refactor-loop-study-canonical-pattern`
(which surfaced the spec/runtime drift Codex MCP flagged on 2026-05-12), and
exercises `build_daily_loop_specs` to confirm the loader emits each canonical
`/cmd:*`, `/loop:iteraction:*`, `/cmd:update`, `/cmd:review`, `/execute-task`
or `/study:*` literally from `items[k].commands` instead of the legacy wrapper
`/daily-loop:do --slug X --item N`.

The predecessor archive stores items as bare ID strings in `buckets[*].items`
(pre-V3 shape) and keeps per-item command lists in `metadata.classification`.
The smoke performs an in-memory V3 migration (string item -> {"id", "commands"})
using the classification block as the source of truth, then feeds the migrated
config through the loader. The on-disk archive is untouched - this is a runtime
contract test, not an archive migration.
"""

from __future__ import annotations

import copy
import json
import re
import shutil
from pathlib import Path

import pytest

from workflow_app.daily_loop import build_daily_loop_specs


PREDECESSOR_ARCHIVE = (
    Path(__file__).resolve().parents[3]
    / "blacksmith"
    / "loop-archives"
    / "refactor-loop-study-canonical-pattern"
)
# Walk up to repo root then dive in - the test file lives at
# ai-forge/workflow-app/tests/workflow_app/, so parents[3] = repo root.
REPO_ROOT = Path(__file__).resolve().parents[4]
ARCHIVE_PATH = (
    REPO_ROOT
    / "blacksmith"
    / "loop-archives"
    / "refactor-loop-study-canonical-pattern"
)

BOUNDARY_PREFIXES = ("/clear", "/model ", "/effort ")
FORBIDDEN_WRAPPER = re.compile(
    r"^/daily-loop:do --slug refactor-loop-study-canonical-pattern --item "
)
CANONICAL_PREFIXES = (
    "/cmd:",
    "/execute-task",
    "/study:",
    "/loop:iteraction:",
    "/create-task",
)


def _migrate_items_to_v3(cfg: dict) -> tuple[dict, set[str]]:
    """Return (deep-copy of cfg with buckets[*].items[*] in V3 dict shape,
    set of item ids that ended up with non-empty commands).

    Source of per-item commands: `metadata.classification[k]` (matched by `id`).
    Boundary markers (/clear, /model X, /effort Y) are stripped because the
    loader emits them itself via dedup on bucket transitions. Items whose
    classification carries zero real commands legitimately fall through to
    the wrapper lane and are excluded from the canonical smoke fixture so the
    assertions can be tight (every retained item MUST emit canonical specs).
    """
    migrated = copy.deepcopy(cfg)
    classification = {
        entry["id"]: entry["commands"]
        for entry in migrated.get("metadata", {}).get("classification", [])
    }
    canonical_ids: set[str] = set()
    for bucket in migrated["daily_loop"]["buckets"]:
        new_items = []
        for raw in bucket["items"]:
            if isinstance(raw, str):
                item_id = raw
                cmds = [
                    c
                    for c in classification.get(item_id, [])
                    if not c.startswith(BOUNDARY_PREFIXES)
                ]
                if not cmds:
                    continue
                new_items.append({"id": item_id, "commands": cmds})
                canonical_ids.add(item_id)
            else:
                new_items.append(raw)
                if isinstance(raw, dict) and raw.get("commands"):
                    canonical_ids.add(str(raw.get("id")))
        bucket["items"] = new_items
    return migrated, canonical_ids


def _prune_progress(progress_text: str, keep_ids: set[str]) -> str:
    """Drop PROGRESS rows whose item id is not in keep_ids."""
    kept: list[str] = []
    row_re = re.compile(r"^\|\s*([0-9A-Za-z_-]+)\s*\|\s*\[")
    for line in progress_text.splitlines():
        m = row_re.match(line)
        if m and m.group(1) not in keep_ids:
            continue
        kept.append(line)
    return "\n".join(kept) + "\n"


def _flip_progress_to_pending(progress_text: str) -> str:
    """Replace every `[x]` status cell with `[ ]` (pending) so the loader
    expands the full queue. Idempotent on already-pending rows."""
    return re.sub(r"\| \[x\] \|", "| [ ] |", progress_text)


@pytest.fixture
def migrated_archive(tmp_path: Path) -> tuple[dict, Path]:
    """Copy the predecessor archive into a tmp loop_root, flip PROGRESS to
    pending, and return (migrated config dict, tmp loop_root path)."""
    if not ARCHIVE_PATH.exists():
        pytest.skip(f"predecessor archive not found at {ARCHIVE_PATH}")

    dst = tmp_path / "refactor-loop-study-canonical-pattern"
    shutil.copytree(ARCHIVE_PATH, dst)

    with (dst / "_LOOP-CONFIG.json").open(encoding="utf-8") as fh:
        cfg = json.load(fh)

    migrated, canonical_ids = _migrate_items_to_v3(cfg)

    progress = dst / "PROGRESS.md"
    flipped = _flip_progress_to_pending(progress.read_text(encoding="utf-8"))
    progress.write_text(
        _prune_progress(flipped, canonical_ids),
        encoding="utf-8",
    )

    return migrated, dst


def test_smoke_emits_canonical_commands_from_predecessor(migrated_archive):
    """Loader must emit at least one canonical /cmd:*, /execute-task, /study:*
    or /loop:iteraction:* spec name when items[].commands is materialised."""
    migrated, loop_root = migrated_archive
    specs = build_daily_loop_specs(migrated, loop_root)
    names = [s.name for s in specs]

    canonical_hits = [n for n in names if n.startswith(CANONICAL_PREFIXES)]
    assert canonical_hits, (
        "expected >= 1 canonical command emitted, got none. "
        f"All names: {names[:30]}"
    )

    # Stronger check: confirm at least one /cmd: AND one /loop:iteraction:
    # since the predecessor archive mixes both families.
    assert any(n.startswith("/cmd:") for n in names), (
        "expected at least one /cmd:* spec"
    )
    assert any(n.startswith("/loop:iteraction:") for n in names), (
        "expected at least one /loop:iteraction:* spec"
    )


def test_smoke_zero_legacy_wrapper_emissions(migrated_archive):
    """When items[].commands is populated, the legacy
    `/daily-loop:do --slug X --item N` wrapper must NOT appear."""
    migrated, loop_root = migrated_archive
    specs = build_daily_loop_specs(migrated, loop_root)
    names = [s.name for s in specs]

    forbidden = [n for n in names if FORBIDDEN_WRAPPER.match(n)]
    assert not forbidden, (
        "loader emitted the legacy wrapper despite items[].commands being "
        f"populated. Offending specs: {forbidden}"
    )


def test_smoke_review_done_lane_unchanged(migrated_archive):
    """`/daily-loop:review-done --slug X --item N` is per-item adversarial
    audit and MUST still be emitted once per pending item (the precedence
    contract only covers the :do lane, not :review-done)."""
    migrated, loop_root = migrated_archive
    specs = build_daily_loop_specs(migrated, loop_root)
    names = [s.name for s in specs]

    review_done = [n for n in names if n.startswith("/daily-loop:review-done")]
    pending_count = sum(
        1 for b in migrated["daily_loop"]["buckets"] for _ in b["items"]
    )
    assert len(review_done) == pending_count, (
        f"expected {pending_count} /daily-loop:review-done entries (one per "
        f"item), got {len(review_done)}"
    )
