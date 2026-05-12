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

# 35 commands with %Kimi >= 79 in scheduled-updates/claude-to-kimi/progress.md.
# Threshold ">= 79%" applied uniformly across:
#   - Sections A..I (canonical loop): 29 commands
#   - Apêndice TEMPLATE_BRIEF_NEW (queue-btn-brief-new): +6 commands
#
# Match is by exact command name (the part before the first space in the
# CommandSpec.name field).
#
# Hardening: tests/test_kimi_whitelist.py parses progress.md at test time and
# fails if any command listed here drops below KIMI_THRESHOLD or disappears
# from the source-of-truth file.
KIMI_THRESHOLD: int = 78
KIMI_PROGRESS_PATH: str = "scheduled-updates/claude-to-kimi/progress.md"

KIMI_COMPATIBLE_COMMANDS: frozenset[str] = frozenset({
    # A-creation
    "/create-task-layout",          # 80
    "/create-overview",             # 84
    # B2-build
    "/mobile-first-build",          # 80
    "/data-test-id",                # 82
    "/assets:create",               # 85
    # B3-execute
    "/review:prep",                 # 79
    # C-linkage
    "/github-linking",              # 84
    "/sync:github",                 # 84
    # D-f8
    "/env-creation",                # 88
    "/create-test-user",            # 84
    "/seed-data-create",            # 79
    "/integration-test-create",     # 80
    "/dev-bootstrap-create",        # 88
    # E-qa
    "/qa:prep",                     # 79
    "/qa:report",                   # 80
    "/backend:scan",                # 80
    "/backend:report",              # 79
    "/frontend:scan",               # 80
    "/frontend:report",             # 79
    "/load-test-create",            # 80
    "/secrets-scan",                # 90 (KIMI_PREFERRED)
    # G-deploy
    "/ci-cd-create",                # 81
    "/supabase-sql-editor",         # 84
    "/infra-create",                # 79
    "/slo-create",                  # 80
    "/monitoring-setup",            # 80
    # I-human
    "/npm-run",                     # 82
    "/next-modules-skeleton-update",  # 89
    "/delivery:sync-progress",      # 86
    # Brief (queue-btn-brief-new) — adicionados via análise do TEMPLATE_BRIEF_NEW
    "/c4-diagram-create",           # 88 (PlantUML deterministic)
    "/mermaid-diagram-create",      # 88 (Mermaid syntax deterministic)
    "/intake:obvious",              # 83 (obvious-pass templated)
    "/error-catalog-create",        # 83 (catálogo templated)
    "/fdd-create",                  # 83 (FDD pattern)
    "/intake:analyze",              # 80 (análise estruturada sem askuser)
    # Brief 78% — adicionados após ajuste manual do threshold (79 -> 78).
    # /break-intake, /prd-create, /user-stories-create, /hld-create foram
    # explicitamente baixados para 75 e ficam KEEP_CLAUDE (decisão do owner).
    "/lld-create",                  # 78 (LLD técnico — incluído pois fora dos 4 manuais)
    "/privacy-assessment-create",   # 78 (LGPD/GDPR domain)
    "/notification-spec-create",    # 78 (UX notification spec)
    "/analytics-spec-create",       # 78 (taxonomia eventos)
    "/i18n-spec-create",            # 78 (i18n strategy)
    "/adr-create",                  # 78 (ADR curto)
    "/optimize:scaffolds",          # 78 (scaffold patterns)
    "/optimize:blueprints",         # 78 (blueprint patterns)
    # Daily Loop pipeline (queue-btn-execute-daily-loop)
    "/daily-loop:do",               # 86 (apply iteration_template — único do execute)
    # Listener Test pipeline (queue-btn-listener-test)
    "/test-autoflow-auto",          # 85 (comando de teste determinístico — aguarda 30s e finaliza)
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


def adapt_to_kimi(command_text: str) -> str:
    """Translate a Claude slash-command line into a Kimi-CLI skill invocation.

    The Kimi CLI auto-discovers skills declared in `.agents/skills/{name}.md`
    when `merge_all_available_skills = true` is set in `~/.kimi/config.toml`
    (default). Each skill file points at the underlying `.claude/commands/...`
    spec and forwards user arguments verbatim. So the adapter just rewrites
    the command head from `/foo:bar` → `/skill:foo:bar` and keeps the args.

    Examples:
        "/qa:prep --module 1 .claude/projects/foo.json"
            → "/skill:qa:prep --module 1 .claude/projects/foo.json"

        "/secrets-scan"
            → "/skill:secrets-scan"

    Pre-flight: if the corresponding skill .md is missing in .agents/skills/,
    Kimi will reply with the literal /skill: invocation as plain text — the
    is_kimi_compatible() whitelist + tests/test_kimi_whitelist.py should
    prevent this from ever shipping (see test_skill_files_exist_for_whitelist).
    """
    if not command_text or not command_text.strip():
        raise ValueError("command_text vazio")

    parts = shlex.split(command_text.strip(), posix=True)
    head = parts[0]
    if not head.startswith("/"):
        raise ValueError(f"comando não começa com '/': {command_text!r}")

    skill_name = head.lstrip("/")
    args = parts[1:]
    if args:
        joined = " ".join(shlex.quote(a) if " " in a else a for a in args)
        return f"/skill:{skill_name} {joined}"
    return f"/skill:{skill_name}"
