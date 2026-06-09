"""Canonical executable-task enumeration for the workflow-app tree.

SINGLE source of truth =
``.claude/commands/_lib/specific_flow/templating.enumerate_module_tasks`` — the
SAME function the offline generator (`generator._list_tasks`) uses. This module
reaches it via the sanctioned cross-tree lazy `sys.path` import (mirrors
`queue_derivation._load_evaluate_condition`). On import failure it falls back to
a LOCAL implementation of the IDENTICAL canonical rule, so the DCP queue
derivation and `/auto-flow` expansion never silently regress to the old
companion-inclusive `glob("TASK-*.md")` (loop 06-08 root cause).

A parity test (`tests/test_task_enum_parity.py`) asserts the local fallback
matches the canonical function on a comprehensive fixture set — any drift is a
CI failure (single-engine discipline, dcp-cmd-list-build.md §19.2).

WHY THIS EXISTS (the bug it fixes): the matrix consumer used to synthesize task
names as ``TASK-{k}.md`` for ``k in range(1, loop_multiplier+1)``. Real task
files start at ``TASK-0.md``, have gaps, use decimal indices (``TASK-0.5.md``),
and the count over-counted companion artifacts — so the synthesized names
pointed at non-existent files (``"task N doesn't exist"``) AND silently dropped
real tasks. Task identity must come from the filesystem (delivery.json does not
enumerate tasks), never from a baked count.
"""

from __future__ import annotations

import logging
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# Canonical executable DCP module task: TASK-<int|decimal>.md with NO alpha/
# hyphen suffix. Kept byte-identical to templating._EXECUTABLE_TASK_RE; the
# parity test guards against drift.
_EXECUTABLE_TASK_RE = re.compile(r"^TASK-(\d+(?:\.\d+)?)\.md$")

_canonical_fn: "Optional[Any]" = None
_canonical_loaded = False


def _load_canonical() -> "Optional[Any]":
    """Lazily import templating.enumerate_module_tasks; cache the result/None."""
    global _canonical_fn, _canonical_loaded
    if _canonical_loaded:
        return _canonical_fn
    _canonical_loaded = True
    try:
        repo_root = Path(__file__).resolve().parents[5]
        lib_dir = repo_root / ".claude" / "commands" / "_lib"
        if str(lib_dir) not in sys.path:
            sys.path.insert(0, str(lib_dir))
        from specific_flow.templating import (  # noqa: E402
            enumerate_module_tasks as _fn,
        )
        _canonical_fn = _fn
    except Exception as exc:  # pragma: no cover - import guard
        logger.warning(
            "[dcp-queue] enumerate_module_tasks canonico indisponivel (%s); "
            "usando fallback local identico.", exc
        )
        _canonical_fn = None
    return _canonical_fn


def _local_enumerate(module_dir: Path) -> list[str]:
    """Identical-rule fallback used only if the canonical import fails."""
    d = Path(module_dir)
    if not d.is_dir():
        return []
    matched: list[tuple[Decimal, str]] = []
    for p in d.glob("TASK-*.md"):
        m = _EXECUTABLE_TASK_RE.match(p.name)
        if m is None:
            continue
        try:
            key = Decimal(m.group(1))
        except InvalidOperation:  # pragma: no cover - regex guarantees numeric
            continue
        matched.append((key, p.name))
    matched.sort(key=lambda t: (t[0], t[1]))
    return [name for _, name in matched]


def enumerate_module_tasks(module_dir: Path) -> list[str]:
    """Ordered basenames of executable DCP task specs in `module_dir`.

    Numeric-ordered (``TASK-2.md`` before ``TASK-10.md``), companion artifacts
    excluded. Returns ``[]`` when the directory is absent or holds no executable
    task spec.
    """
    fn = _load_canonical()
    if fn is not None:
        try:
            return list(fn(module_dir))
        except Exception as exc:  # pragma: no cover - never crash the queue
            logger.warning(
                "[dcp-queue] enumerate_module_tasks canonico falhou (%s); "
                "fallback local.", exc
            )
    return _local_enumerate(module_dir)


__all__ = ["enumerate_module_tasks"]
