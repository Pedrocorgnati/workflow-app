"""Lock the widget's static canonically-bare snapshot against profiles drift.

`CommandQueueWidget._CANONICAL_BARE_FALLBACK` is the fail-safe the bare-name
guard uses when `specific_flow.profiles.FULL_PROFILE` cannot be imported. It MUST
equal the live set derived from profiles, otherwise the degraded-environment
guard would admit a command that lost its placeholder (false negative) or flag a
legitimately-bare command (false positive — the tecum-app abort class).

When this test fails, regenerate the snapshot in command_queue_widget.py from:

    python3 - <<'PY'
    import sys; sys.path.insert(0, '.claude/commands/_lib')
    from specific_flow import profiles
    steps = profiles.get_profile(profiles.PROFILE_FULL)
    for n in sorted({s.template.strip() for s in steps
                     if s.template.startswith('/') and '{' not in s.template}):
        print(n)
    PY
"""
from __future__ import annotations

import pytest

from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
from workflow_app.dcp.queue_derivation import canonical_bare_command_names


def test_static_fallback_matches_live_profiles_set() -> None:
    live = canonical_bare_command_names()
    if live is None:
        pytest.skip("profiles.FULL_PROFILE not importable in this environment")
    static = CommandQueueWidget._CANONICAL_BARE_FALLBACK
    missing = live - static
    extra = static - live
    assert not missing and not extra, (
        "canonical-bare snapshot drift — "
        f"missing from static fallback: {sorted(missing)}; "
        f"extra in static fallback: {sorted(extra)}"
    )


def test_placeholder_commands_absent_from_fallback() -> None:
    """Commands whose canonical template requires args must NOT be in the
    fallback (else a placeholder-loss regression would be silently admitted)."""
    static = CommandQueueWidget._CANONICAL_BARE_FALLBACK
    for name in (
        "/create-task", "/execute-task", "/review-created-task",
        "/create-overview", "/update-task-user-stories", "/tdd:test-plan",
    ):
        assert name not in static, f"{name} requires a placeholder; must not be bare-OK"
