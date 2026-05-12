"""Daily Loop integration for workflow-app.

Reads `_LOOP-CONFIG.json` (loaded via metrics-project-pill) plus the bucketed
`PROGRESS.md` and expands them into a CommandSpec queue with one entry per
pending item, deduplicating consecutive `/model` and `/effort` headers.

Pairs with the `/daily-loop` pipeline (`.claude/commands/daily-loop.md`).
"""

from workflow_app.daily_loop.loader import (
    DailyLoopConfigError,
    ReviewBlockedSentinel,
    build_daily_loop_specs,
    parse_progress_items,
    read_review_blocked_sentinel,
    resolve_loop_path,
)

__all__ = [
    "DailyLoopConfigError",
    "ReviewBlockedSentinel",
    "build_daily_loop_specs",
    "parse_progress_items",
    "read_review_blocked_sentinel",
    "resolve_loop_path",
]
