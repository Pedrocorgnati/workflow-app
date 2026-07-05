"""Daily Loop integration for workflow-app.

Reads `_LOOP-CONFIG.json` (loaded via metrics-project-pill) plus the bucketed
`PROGRESS.md` and expands them into a CommandSpec queue with one entry per
pending item, deduplicating consecutive `/model` and `/effort` headers.

Pairs with the `/daily-loop` pipeline (`.claude/commands/daily-loop.md`).
"""

from workflow_app.daily_loop.loader import (
    DailyLoopConfigError,
    ReviewBlockedSentinel,
    assert_loop_root_relative_path,
    assert_mkt_assets_iteration_shape,
    assert_rocksmash_iteration_shape,
    build_daily_loop_specs,
    build_loop_specs,
    diagnose_workspace_doubled_path,
    is_mkt_assets_mode,
    is_rocksmash_mode,
    parse_progress_items,
    parse_progress_items_loop,
    read_review_blocked_sentinel,
    resolve_effective_workspace_root,
    resolve_loop_path,
)

__all__ = [
    "DailyLoopConfigError",
    "ReviewBlockedSentinel",
    "assert_loop_root_relative_path",
    "assert_mkt_assets_iteration_shape",
    "assert_rocksmash_iteration_shape",
    "build_daily_loop_specs",
    "build_loop_specs",
    "diagnose_workspace_doubled_path",
    "is_mkt_assets_mode",
    "is_rocksmash_mode",
    "parse_progress_items",
    "parse_progress_items_loop",
    "read_review_blocked_sentinel",
    "resolve_effective_workspace_root",
    "resolve_loop_path",
]
