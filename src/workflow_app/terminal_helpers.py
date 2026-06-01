"""Canonical helper-command vocabulary for the embedded terminals.

Single source of truth for "queue helper" classification, previously
duplicated in three modules (metrics_bar, output_panel, xterm_output_panel)
with "keep in sync" comments — a drift hazard flagged in adversarial review:
a divergence here turns into either a spurious EARLY_EXIT (helper armed the
early-exit watcher) or a permanently-yellow dot (helper not auto-greened).

Helpers are commands that mutate CLI/session state or the bash environment
but DO NOT write a notify file on completion:
  - slash-helpers: /model, /effort, /clear (Claude Code session directives)
  - bash: cd (directory change)
  - CLI launches: clauded, kimid, clauded2, kimid2, codex, codex-high

Consequences of being a helper (enforced by the consumers, not here):
  - the early-exit watcher is NOT armed for them — they finish fast by design
    and would false-trigger EARLY_EXIT (<2048 bytes, <8s). See
    ai-forge/rules/workflow-app-listeners.md §3.3.
  - the listener dot is auto-greened by a timer instead of a notify file.

This module is pure (no Qt, no I/O) so it can be unit-tested without
instantiating widgets.
"""
from __future__ import annotations

# Canonical, ordered for readability. Membership test is order-independent.
HELPER_COMMANDS: tuple[str, ...] = (
    "/model", "/effort", "/clear",            # slash-helpers
    "cd",                                      # bash directory change
    "clauded", "kimid", "clauded2", "kimid2", "codex", "codex-high",  # CLI launches
)


def is_helper_command(cmd: str | None) -> bool:
    """True if `cmd` is a queue helper, matched by leading token.

    Case-insensitive; tolerates leading/trailing whitespace and arguments
    (`/model opus`, `  /MODEL opus`, `cd foo` all match). Empty/whitespace
    is not a helper.
    """
    if not cmd or not cmd.strip():
        return False
    head = cmd.strip().split(None, 1)[0].lower()
    return head in HELPER_COMMANDS
