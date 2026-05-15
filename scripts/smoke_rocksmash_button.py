"""Smoke test for queue-btn-rocksmash expander.

Loads a _LOOP-CONFIG.json from disk and dumps the resulting queue. Use
this to verify the canonical shape:

    1x /loop-rocksmash:prepare
    N pares /loop-rocksmash:do + /loop-rocksmash:review-done
    1x /loop-rocksmash:rename

Usage::

    python3 ai-forge/workflow-app/scripts/smoke_rocksmash_button.py \
        blacksmith/loop-archives/<slug>/_LOOP-CONFIG.json
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

THIS = Path(__file__).resolve()
SRC = THIS.parents[1] / "src"
sys.path.insert(0, str(SRC))

# Headless Qt — required when CommandSpec/domain pulls in Qt enums.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from workflow_app.command_queue.loop_rocksmash_expander import (  # noqa: E402
    build_loop_rocksmash_specs,
)


def _validate_shape(names: list[str]) -> tuple[bool, str]:
    """Verify 1 prepare + N pairs + 1 rename (ignoring directives)."""
    payload = [
        n
        for n in names
        if not (
            n == "/clear"
            or n.startswith("/model ")
            or n.startswith("/effort ")
        )
    ]
    if len(payload) < 3:
        return False, f"queue tem so {len(payload)} payload specs"
    if not payload[0].startswith("/loop-rocksmash:prepare "):
        return False, f"primeiro payload nao e :prepare: {payload[0]!r}"
    if not payload[-1].startswith("/loop-rocksmash:rename "):
        return False, f"ultimo payload nao e :rename: {payload[-1]!r}"
    middle = payload[1:-1]
    if len(middle) % 2 != 0:
        return False, f"middle nao e par (got {len(middle)})"
    pair_count = len(middle) // 2
    for i in range(pair_count):
        do_cmd = middle[2 * i]
        rd_cmd = middle[2 * i + 1]
        if not do_cmd.startswith("/loop-rocksmash:do "):
            return False, f"pair {i} :do invalido: {do_cmd!r}"
        if not rd_cmd.startswith("/loop-rocksmash:review-done "):
            return False, f"pair {i} :review-done invalido: {rd_cmd!r}"
        m_do = re.search(r"task-(\d+)-", do_cmd)
        m_rd = re.search(r"task-(\d+)-", rd_cmd)
        if not m_do or not m_rd or m_do.group(1) != m_rd.group(1):
            return False, f"pair {i} task id mismatch: do={do_cmd!r} rd={rd_cmd!r}"
    return True, f"OK: 1 prepare + {pair_count} pares + 1 rename"


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: smoke_rocksmash_button.py <_LOOP-CONFIG.json>", file=sys.stderr)
        return 2
    cfg_path = Path(argv[1]).resolve()
    if not cfg_path.is_file():
        print(f"config nao encontrado: {cfg_path}", file=sys.stderr)
        return 2

    raw = json.loads(cfg_path.read_text(encoding="utf-8"))
    loop_root = cfg_path.parent

    specs = build_loop_rocksmash_specs(raw, loop_root)
    names = [s.name for s in specs]

    print(f"# rocksmash queue for {cfg_path}")
    print(f"# total specs: {len(names)}")
    print()
    for i, n in enumerate(names):
        print(f"{i:03d}  {n}")
    print()
    ok, msg = _validate_shape(names)
    print(f"# shape check: {msg}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
