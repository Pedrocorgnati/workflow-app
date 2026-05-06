"""
Kimi compatibility — whitelist + Claude→Kimi prompt adapter.

Source of truth: scheduled-updates/claude-to-kimi/progress.md (37 commands
classified as KIMI_OK or KIMI_PREFERRED). Commands listed here are eligible
for execution in the Kimi CLI running on the workspace terminal, instead of
the Claude Code interactive terminal.

Adapter rationale: Kimi does not know SystemForge slash-commands, but the
prompt template lives at .claude/commands/{slug}.md and is readable from the
repo. The minimal safe transformation is to point Kimi at that file and pass
the original arguments verbatim.
"""

from __future__ import annotations

import shlex

# 37 commands classified as KIMI_OK or KIMI_PREFERRED in
# scheduled-updates/claude-to-kimi/progress.md (sections A..I).
# Match is by exact command name (the part before the first space in the
# CommandSpec.name field).
KIMI_COMPATIBLE_COMMANDS: frozenset[str] = frozenset({
    # A-creation
    "/create-task",
    "/create-task-layout",
    "/create-overview",
    # B2-build
    "/mobile-first-build",
    "/front-end-obvious",
    "/data-test-id",
    "/db-migration-create",
    "/assets:create",
    # B3-execute
    "/review:prep",
    # C-linkage
    "/github-linking",
    "/sync:github",
    "/sync:mcp",
    # D-f8
    "/env-creation",
    "/create-test-user",
    "/seed-data-create",
    "/integration-test-create",
    "/dev-bootstrap-create",
    "/infra-smoke-check",
    # E-qa
    "/qa:prep",
    "/qa:report",
    "/backend:scan",
    "/backend:report",
    "/frontend:scan",
    "/frontend:mobile-check",
    "/frontend:assets-check",
    "/frontend:report",
    "/load-test-create",
    "/dependency-audit",
    "/secrets-scan",
    # G-deploy
    "/ci-cd-create",
    "/supabase-sql-editor",
    "/infra-create",
    "/slo-create",
    "/monitoring-setup",
    # I-human
    "/npm-run",
    "/next-modules-skeleton-update",
    "/delivery:sync-progress",
})


def is_kimi_compatible(command_name: str) -> bool:
    """Return True if this slash-command is in the Kimi-compatible whitelist.

    Match is on the first whitespace-delimited token (the slash-command head).
    Anything after — flags, config paths — is ignored for matching.
    """
    if not command_name or not command_name.strip():
        return False
    head = command_name.strip().split(None, 1)[0]
    return head in KIMI_COMPATIBLE_COMMANDS


def _slug_to_path(head: str) -> str:
    """Convert '/qa:prep' → '.claude/commands/qa/prep.md'."""
    slug = head.lstrip("/")
    slug = slug.replace(":", "/")
    return f".claude/commands/{slug}.md"


def adapt_to_kimi(command_text: str) -> str:
    """Translate a Claude slash-command line into a Kimi-CLI free-text prompt.

    Examples:
        "/qa:prep --module 1 .claude/projects/foo.json"
            → "Lê .claude/commands/qa/prep.md e executa esse fluxo "
              "com argumentos: --module 1 .claude/projects/foo.json"

        "/secrets-scan"
            → "Lê .claude/commands/secrets-scan.md e executa esse fluxo"
    """
    if not command_text or not command_text.strip():
        raise ValueError("command_text vazio")

    parts = shlex.split(command_text.strip(), posix=True)
    head = parts[0]
    if not head.startswith("/"):
        raise ValueError(f"comando não começa com '/': {command_text!r}")

    path = _slug_to_path(head)
    args = parts[1:]
    if args:
        joined = " ".join(shlex.quote(a) if " " in a else a for a in args)
        return f"Lê {path} e executa esse fluxo com argumentos: {joined}"
    return f"Lê {path} e executa esse fluxo"
