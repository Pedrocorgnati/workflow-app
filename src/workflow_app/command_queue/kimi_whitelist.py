"""
Kimi compatibility — whitelist + Claude→Kimi prompt adapter.

Source of truth: blacksmith/claude-to-kimi/progress.md (37 commands
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

# Commands with %Kimi >= KIMI_THRESHOLD in blacksmith/claude-to-kimi/progress.md.
# Threshold lowered to 54 to accommodate forced whitelisting of
# /blog:deploy (score 54, --force) and /blog:build-programmatic-pages (score 57, --force).
#
# Match is by exact command name (the part before the first space in the
# CommandSpec.name field).
#
# Hardening: tests/test_kimi_whitelist.py parses progress.md at test time and
# fails if any command listed here drops below KIMI_THRESHOLD or disappears
# from the source-of-truth file.
KIMI_THRESHOLD: int = 54
KIMI_PROGRESS_PATH: str = "blacksmith/claude-to-kimi/progress.md"

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
    # Blog pipeline
    "/blog:analytics-review",       # 72
    "/blog:build-internal-links",   # 72
    "/blog:build-metadata",         # 82
    "/blog:build-programmatic-pages",  # 57
    "/blog:cluster-keywords",       # 75
    "/blog:competitor-spy",           # 58
    "/blog:deduplicate-topics",       # 60
    "/blog:deploy",                   # 54
    "/blog:discover-intents",         # 61
    "/blog:discover-intents-part2",   # 61
    "/blog:eeat-inject",              # 60
    "/blog:expand-keywords",          # 58
    "/blog:generate-briefs",          # 54 (bumped to threshold floor; was 28 forced)
    "/blog:hreflang-map",             # 62 (forced via --force)
    "/blog:init-strategy",            # 65
    "/blog:localize-check",           # 70
    "/blog:prioritize-topics",        # 62
    "/blog:quality-gate",             # 54 (bumped to threshold floor; was 52 forced)
    "/blog:refresh-content",          # 54 (bumped to threshold floor; was 30 forced)
    "/blog:review-seo",               # 54 (bumped to threshold floor; was 13 forced)
    "/blog:schedule-batch",           # 54 (bumped to threshold floor; was 51 forced)
    "/blog:stockpile-generate",       # 60
    "/blog:stockpile-invalidate",     # 76
    "/blog:stockpile-promote",        # 54 (bumped to threshold floor; was 50 forced)
    "/blog:stockpile-repair",         # 65
    "/blog:stockpile-review",         # 54 (bumped to threshold floor; was 28 forced)
    "/blog:stockpile-status",         # 100
    "/blog:stockpile-finalize-package",  # 88 (KIMI_PREFERRED — Pass 2.4 deterministico: Read+Write JSON, zero AskUser, zero Codex)
    "/blog:stockpile-validate",       # 90 (KIMI_PREFERRED — wrapper npm + parse stdout, zero AskUser, zero Codex)
    "/blog:stockpile-push",           # 65 (KIMI_OK — git add/commit/push escopado em stockpile/, idempotente, lock+retry, zero AskUser, zero Codex)
    "/blog:write-articles",           # 54 (bumped to threshold floor; was 48 forced)
    # Brief 78% / Blog 72% / build-programmatic-pages 57 (forced) — threshold lowered (79 -> 78 -> 72 -> 57).
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
    # Daily Loop pipeline (queue-btn-daily-loop)
    "/daily-loop:do",               # 86 (apply iteration_template — único do execute)
    # Loop rocksmash pipeline
    "/loop-rocksmash:do",           # 86 (density split deterministic — zero AskUser, templates byte-exatos)
    "/loop-rocksmash:rename",         # 91 (KIMI_PREFERRED — consolidador determinista pos-rocksmash)
    "/loop-rocksmash:compare",      # 85 (KIMI_OK — pareamento JSON + sumario prosa determinista; idempotente por hash)
    # Test-autoflow (deterministic test commands)
    "/test-autoflow-auto",          # 85 (comando de teste determinístico — aguarda 30s e finaliza)
    # Loop housekeeping
    "/loop:clear",                  # 89
    # Meta — cmd hardening
    "/cmd:autocast-hardening",      # 94 (KIMI_PREFERRED)
    "/cmd:autocast-put",            # 91 (KIMI_PREFERRED)
    # DCP — matrix
    "/dcp:matrix-init",             # 86
    "/dcp:matrix-refine",           # 73
    "/dcp:matrix-replicate",        # 92 (KIMI_PREFERRED)
    "/dcp:matrix-mark-loops",       # 95 (KIMI_PREFERRED)
    "/dcp:matrix-filter-modules",   # 72
    # Legacy pipeline
    "/legacy:enqueue-all-modules",  # 73
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
