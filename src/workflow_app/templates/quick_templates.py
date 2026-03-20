"""
Quick template definitions for header buttons.

Defines static command sequences for all non-dynamic header buttons.
The WBS button is dynamic and handled by wbs_template_builder.py.
"""

from __future__ import annotations

from workflow_app.domain import CommandSpec, InteractionType, ModelName

# ─── Short aliases ──────────────────────────────────────────────────────────── #

_O = ModelName.OPUS
_S = ModelName.SONNET
_H = ModelName.HAIKU
_I = InteractionType.INTERACTIVE
_A = InteractionType.AUTO


def _spec(
    name: str,
    model: ModelName,
    interaction: InteractionType,
    pos: int,
    optional: bool = False,
) -> CommandSpec:
    return CommandSpec(
        name=name,
        model=model,
        interaction_type=interaction,
        position=pos,
        is_optional=optional,
    )


def _same_context_group(prev_name: str, curr_name: str) -> bool:
    """True if two commands belong to the same pipeline group (no /clear between them).

    Groups are sub-pipelines where each step feeds into the next and benefits
    from shared conversation context:
      - /qa:prep → /qa:trace → /qa:report
      - /backend:scan → /backend:audit → /backend:test-check → /backend:report
      - /frontend:scan → /frontend:audit → /frontend:assets-check → /frontend:report
      - /deep-research-1 → /deep-research-2
      - /c4-diagram-create → /mermaid-diagram-create

    NOT grouped: stack review commands (/nextjs:*, /python:*, etc.) — they are
    independent checks that don't need each other's context.
    """
    _PIPELINE_PREFIXES = ("/qa:", "/backend:", "/frontend:")
    for prefix in _PIPELINE_PREFIXES:
        if prev_name.startswith(prefix) and curr_name.startswith(prefix):
            return True
    if prev_name.startswith("/deep-research") and curr_name.startswith("/deep-research"):
        return True
    if "diagram-create" in prev_name and "diagram-create" in curr_name:
        return True
    return False


def _inject_clears(specs: list[CommandSpec]) -> list[CommandSpec]:
    """Insert /clear before AUTO commands, respecting context groups.

    Rules:
      - First command: never gets /clear before it.
      - INTERACTIVE commands: never get /clear before them (they build context
        through dialogue and need the conversation history).
      - AUTO commands in the same context group as the previous command:
        no /clear inserted (they share a sub-pipeline).
      - Other AUTO commands: /clear inserted before them.
      - /clear uses the NEXT command's model (avoids unnecessary /model haiku).

    Applied to: Brief, Modules, Deploy, Mkt, Business, QA, Micro-Architecture.
    NOT applied to: Daily (context flows through the full session by design).
    """
    result: list[CommandSpec] = []
    pos = 1
    prev_name = ""
    for i, spec in enumerate(specs):
        if i > 0 and spec.interaction_type == _A and not _same_context_group(prev_name, spec.name):
            result.append(CommandSpec(
                name="/clear",
                interaction_type=_A,
                position=pos,
            ))
            pos += 1
        result.append(CommandSpec(
            name=spec.name,
            model=spec.model,
            interaction_type=spec.interaction_type,
            position=pos,
            is_optional=spec.is_optional,
        ))
        pos += 1
        prev_name = spec.name
    return result


# ─── JSON: apenas /project-json ─────────────────────────────────────────────── #

TEMPLATE_JSON: list[CommandSpec] = [
    _spec("/project-json", _S, _I, 1),
]

# ─── Brief: Novo Projeto (from z-templates/start.md [new]) ──────────────────── #

TEMPLATE_BRIEF_NEW: list[CommandSpec] = _inject_clears([
    _spec("/first-brief-create",        _O, _I,  1),
    _spec("/intake:analyze",            _S, _A,  2),
    _spec("/intake:enhance",            _O, _I,  3),
    _spec("/tech-feasibility",          _O, _I,  4),
    _spec("/break-intake",              _S, _A,  5),
    _spec("/prd-create",                _O, _I,  6),
    _spec("/user-stories-create",       _S, _I,  7),
    _spec("/hld-create",                _O, _I,  8),
    _spec("/lld-create",                _O, _I,  9),
    _spec("/api-contract-create",       _O, _A, 10),
    _spec("/threat-model-create",       _O, _A, 11),
    _spec("/privacy-assessment-create", _S, _I, 12),
    _spec("/error-catalog-create",      _S, _A, 13),
    _spec("/notification-spec-create",  _S, _I, 14),
    _spec("/analytics-spec-create",     _S, _I, 15),
    _spec("/i18n-spec-create",          _S, _I, 16),
    _spec("/deep-research-1",           _O, _A, 17),
    _spec("/deep-research-2",           _O, _A, 18),
    _spec("/adr-create",                _O, _I, 19),
    _spec("/fdd-create",                _O, _I, 20),
    _spec("/c4-diagram-create",         _H, _A, 21),
    _spec("/mermaid-diagram-create",    _H, _A, 22),
    _spec("/design-create",             _O, _I, 23),
    _spec("/review-prd-flow",           _O, _I, 24),
    _spec("/auto-flow rocks",           _O, _A, 25),
    _spec("/create-scaffolds",          _O, _I, 26),
    _spec("/create-blueprints",         _O, _I, 27),
    _spec("/create-guardrails",         _O, _I, 28),
    _spec("/create-integrations",       _O, _I, 29),
])

# ─── Brief: Feature (from z-templates/start.md [feature]) ───────────────────── #

TEMPLATE_BRIEF_FEATURE: list[CommandSpec] = _inject_clears([
    _spec("/feature-brief-create",      _O, _I,  1),
    _spec("/intake:analyze",            _S, _A,  2),
    _spec("/intake:enhance",            _O, _I,  3),
    _spec("/tech-feasibility",          _O, _I,  4),
    _spec("/break-intake",              _S, _A,  5),
    _spec("/prd-create",                _O, _I,  6),
    _spec("/user-stories-create",       _S, _I,  7),
    _spec("/lld-create",                _O, _I,  8),
    _spec("/error-catalog-create",      _S, _A,  9),
    _spec("/notification-spec-create",  _S, _I, 10),
    _spec("/adr-create",                _O, _I, 11),
    _spec("/fdd-create",                _O, _I, 12),
    _spec("/c4-diagram-create",         _H, _A, 13),
    _spec("/mermaid-diagram-create",    _H, _A, 14),
    _spec("/design-create",             _O, _I, 15),
    _spec("/review-prd-flow",           _O, _I, 16),
    _spec("/auto-flow rocks",           _O, _A, 17),
    _spec("/create-scaffolds",          _O, _I, 18),
    _spec("/create-blueprints",         _O, _I, 19),
    _spec("/create-guardrails",         _O, _I, 20),
    _spec("/create-integrations",       _O, _I, 21),
])

# ─── Modules (from z-templates/modules.md) ───────────────────────────────────── #

TEMPLATE_MODULES: list[CommandSpec] = _inject_clears([
    _spec("/modules:create-core",       _O, _I, 1),
    _spec("/modules:create-blueprints", _S, _A, 2),
    _spec("/modules:create-variants",   _O, _I, 3),
    _spec("/modules:create-structure",  _S, _A, 4),
    _spec("/modules:create-coverage",   _S, _A, 5),
    _spec("/modules:create-overview",   _S, _A, 6),
    _spec("/modules:review-created",    _O, _I, 7),
    _spec("/rollout-strategy-create",   _S, _I, 8),
])

# ─── Deploy (from z-templates/deploy.md) ─────────────────────────────────────── #

TEMPLATE_DEPLOY: list[CommandSpec] = _inject_clears([
    _spec("/ci-cd-create",          _S, _I,  1),
    _spec("/supabase-sql-editor",   _S, _A,  2),
    _spec("/infra-create",          _S, _I,  3),
    _spec("/pre-deploy-testing",    _S, _I,  4),
    _spec("/slo-create",            _S, _I,  5),
    _spec("/staging-validate",      _S, _A,  6),
    _spec("/monitoring-setup",      _S, _I,  7),
    _spec("/post-deploy-verify",    _S, _A,  8),
    _spec("/changelog-create",      _H, _A,  9),
    _spec("/deploy-flow",           _S, _A, 10),
])

# ─── Daily (from z-templates/daily.md) ────────────────────────────────────────── #
# NOTE: NO /clear injected — daily commands flow context between steps by design.

TEMPLATE_DAILY: list[CommandSpec] = [
    _spec("/daily:scan",     _S, _A, 1),
    _spec("/daily:plan",     _S, _A, 2),
    _spec("/daily:do",       _S, _A, 3),
    _spec("/daily:validate", _S, _A, 4),
    _spec("/daily:review",   _S, _A, 5),
]

# ─── Marketing (from z-templates/mkt.md) ──────────────────────────────────────── #

TEMPLATE_MKT: list[CommandSpec] = _inject_clears([
    _spec("/docs-create",           _S, _A, 1),
    _spec("/mkt:portfolio-add",     _H, _A, 2),
    _spec("/mkt:linkedin-mkt",      _H, _A, 3),
    _spec("/mkt:instagram-mkt",     _H, _A, 4),
    _spec("/mkt:portfolio-publish", _H, _A, 5),
    _spec("/handoff-create",        _H, _A, 6),
])

# ─── Business (from z-templates/business.md) ──────────────────────────────────── #

TEMPLATE_BUSINESS: list[CommandSpec] = _inject_clears([
    _spec("/business:product-brief-create",  _O, _A, 1),
    _spec("/business:sow-create",            _O, _I, 2),
    _spec("/business:create-budget",         _S, _I, 3),
    _spec("/business:simple-budget",         _S, _I, 4),
    _spec("/business:generate-pdf-docs",     _H, _A, 5),
    _spec("/business:generate-json-project", _H, _A, 6),
])

# ─── QA Templates per stack (from z-templates/qa.md) ──────────────────────────── #

_QA_BASE: list[tuple[str, ModelName, InteractionType]] = [
    ("/qa:prep",              _S, _A),
    ("/qa:trace",             _O, _A),
    ("/qa:report",            _S, _A),
    ("/validate-billing",     _O, _A),
    ("/backend:scan",         _S, _A),
    ("/backend:audit",        _O, _A),
    ("/backend:test-check",   _S, _A),
    ("/backend:report",       _O, _A),
    ("/validate-front-end",   _O, _A),
    ("/frontend:scan",        _S, _A),
    ("/frontend:audit",        _O, _A),
    ("/frontend:mobile-check", _S, _A),
    ("/frontend:assets-check", _S, _A),
    ("/frontend:report",      _O, _A),
    ("/qa-remediate",         _S, _A),
    ("/load-test-create",     _S, _A),
    ("/tech-debt-audit",      _S, _A),
    ("/dependency-audit",     _S, _A),
    ("/secrets-scan",         _H, _A),
    ("/compliance-check",     _S, _A),
    ("/mutation-test-create",  _H, _A),
    ("/review-language",      _H, _A),
    ("/validate-stack",       _H, _A),
]

_QA_NEXTJS: list[tuple[str, ModelName, InteractionType]] = [
    ("/nextjs:seo",                _H, _A),
    ("/nextjs:error-handling",     _S, _A),
    ("/nextjs:server-actions",     _S, _A),
    ("/nextjs:architecture",       _S, _A),
    ("/nextjs:accessibility",      _S, _A),
    ("/nextjs:anti-loop",          _S, _A),
    ("/nextjs:hardcodes",          _S, _A),
    ("/nextjs:performance",        _S, _A),
    ("/nextjs:styling",            _S, _A),
    ("/nextjs:anti-hacking-review", _S, _A),
    ("/nextjs:typescript",         _S, _A),
    ("/nextjs:forms",              _S, _A),
    ("/nextjs:boundaries",         _S, _A),
    ("/nextjs:data-fetching",      _S, _A),
    ("/nextjs:scalability",        _S, _A),
    ("/nextjs:security",           _S, _A),
    ("/nextjs:nextjs-components",  _S, _A),
    ("/nextjs:configuration",      _S, _A),
    ("/final-review",              _S, _A),
]

_QA_TYPESCRIPT: list[tuple[str, ModelName, InteractionType]] = [
    ("/typescript:seo",            _H, _A),
    ("/typescript:error-handling",  _S, _A),
    ("/typescript:architecture",    _S, _A),
    ("/typescript:accessibility",   _S, _A),
    ("/typescript:hardcodes",       _S, _A),
    ("/typescript:dom-components",  _S, _A),
    ("/typescript:performance",     _S, _A),
    ("/typescript:styling",         _S, _A),
    ("/typescript:typescript",      _S, _A),
    ("/typescript:forms",           _S, _A),
    ("/typescript:data-fetching",   _S, _A),
    ("/typescript:scalability",     _S, _A),
    ("/typescript:security",        _S, _A),
    ("/typescript:configuration",   _S, _A),
    ("/final-review",              _S, _A),
]

_QA_PYTHON: list[tuple[str, ModelName, InteractionType]] = [
    ("/python:ci-cd",          _S, _A),
    ("/python:error-handling",  _S, _A),
    ("/python:architecture",    _S, _A),
    ("/python:hardcodes",       _S, _A),
    ("/python:dependencies",    _S, _A),
    ("/python:performance",     _S, _A),
    ("/python:web-framework",   _S, _A),
    ("/python:packaging",       _S, _A),
    ("/python:api",             _S, _A),
    ("/python:typing",          _S, _A),
    ("/python:data-handling",   _S, _A),
    ("/python:testing",         _S, _A),
    ("/python:async",           _S, _A),
    ("/python:scalability",     _S, _A),
    ("/python:security",        _S, _A),
    ("/python:configuration",   _S, _A),
    ("/final-review",          _S, _A),
]

_QA_ANDROID: list[tuple[str, ModelName, InteractionType]] = [
    ("/android:lifecycle",      _S, _A),
    ("/android:data-layer",     _S, _A),
    ("/android:architecture",   _S, _A),
    ("/android:accessibility",  _S, _A),
    ("/android:compose",        _S, _A),
    ("/android:hardcodes",      _S, _A),
    ("/android:di",             _S, _A),
    ("/android:kotlin",         _S, _A),
    ("/android:performance",    _S, _A),
    ("/android:navigation",     _S, _A),
    ("/android:resources",      _S, _A),
    ("/android:scalability",    _S, _A),
    ("/android:security",       _S, _A),
    ("/android:configuration",  _S, _A),
    ("/android:testing",        _S, _A),
    ("/final-review",          _S, _A),
]

_QA_REACT_NATIVE: list[tuple[str, ModelName, InteractionType]] = [
    ("/reactnative:configuration",   _S, _A),
    ("/reactnative:typescript",      _S, _A),
    ("/reactnative:architecture",    _S, _A),
    ("/reactnative:state-management", _S, _A),
    ("/reactnative:data-fetching",   _S, _A),
    ("/reactnative:error-handling",  _S, _A),
    ("/reactnative:security",        _S, _A),
    ("/reactnative:navigation",      _S, _A),
    ("/reactnative:styling",         _S, _A),
    ("/reactnative:accessibility",   _S, _A),
    ("/reactnative:performance",     _S, _A),
    ("/reactnative:testing",         _S, _A),
    ("/reactnative:hardcodes",       _S, _A),
    ("/reactnative:scalability",     _S, _A),
    ("/reactnative:ci-cd",           _S, _A),
    ("/final-review",               _S, _A),
]


def _build_qa_template(stack_cmds: list[tuple[str, ModelName, InteractionType]]) -> list[CommandSpec]:
    """Build a QA template by combining base QA commands with stack-specific ones."""
    base_specs = [_spec(name, model, interaction, i + 1) for i, (name, model, interaction) in enumerate(_QA_BASE + stack_cmds)]
    return _inject_clears(base_specs)


TEMPLATE_QA_NEXTJS: list[CommandSpec] = _build_qa_template(_QA_NEXTJS)
TEMPLATE_QA_TYPESCRIPT: list[CommandSpec] = _build_qa_template(_QA_TYPESCRIPT)
TEMPLATE_QA_PYTHON: list[CommandSpec] = _build_qa_template(_QA_PYTHON)
TEMPLATE_QA_ANDROID: list[CommandSpec] = _build_qa_template(_QA_ANDROID)
TEMPLATE_QA_REACT_NATIVE: list[CommandSpec] = _build_qa_template(_QA_REACT_NATIVE)

# ─── Micro-Architecture (F4b) ────────────────────────────────────────────────── #
# Full flow: feature brief (sem break-intake) → micro-arch WBS → review

TEMPLATE_MICRO_ARCHITECTURE: list[CommandSpec] = _inject_clears([
    _spec("/feature-brief-create",               _O, _I, 1),
    _spec("/intake:analyze",                     _S, _A, 2),
    _spec("/intake:enhance",                     _O, _I, 3),
    _spec("/micro-architecture",                 _S, _I, 4),
    _spec("/review-created-micro-architecture",  _O, _A, 5),
    _spec("/auto-flow execute",                  _S, _A, 6),
    _spec("/review-executed-micro-architecture", _O, _A, 7),
])

# ─── Autocast Test (F4b/Daily — validação do ciclo de autocast) ─────────────── #

TEMPLATE_AUTOCAST_TEST: list[CommandSpec] = _inject_clears([
    _spec("/test-autoflow-auto",        _S, _A, 1),
    _spec("/test-autoflow-auto",        _S, _A, 2),
    _spec("/test-autoflow-interactive", _S, _I, 3),
    _spec("/test-autoflow-interactive", _S, _I, 4),
    _spec("/test-autoflow-auto",        _S, _A, 5),
    _spec("/test-autoflow-interactive", _S, _I, 6),
    _spec("/test-autoflow-auto",        _S, _A, 7),
    _spec("/test-autoflow-auto",        _S, _A, 8),
])

# ─── Auto-Improove Loop (Auxiliar tab) ──────────────────────────────────────── #
# Designed for /loop button — cycles continuously until stopped.

TEMPLATE_AUTO_IMPROOVE_LOOP: list[CommandSpec] = [
    _spec("/model Opus",          _O, _A,  1),
    _spec("/clear",               _O, _A,  2),
    _spec("/auto-improove:cmd",   _O, _A,  3),
    _spec("/clear",               _O, _A,  4),
    _spec("/auto-improove:cmd",   _O, _A,  5),
    _spec("/clear",               _O, _A,  6),
    _spec("/auto-improove:cmd",   _O, _A,  7),
    _spec("/clear",               _O, _A,  8),
    _spec("/auto-improove:cmd",   _O, _A,  9),
    _spec("/clear",               _O, _A, 10),
    _spec("/auto-improove:cmd",   _O, _A, 11),
]

# ─── Map for QA stack picker dialog ──────────────────────────────────────────── #

QA_STACK_TEMPLATES: dict[str, list[CommandSpec]] = {
    "Next.js": TEMPLATE_QA_NEXTJS,
    "TypeScript": TEMPLATE_QA_TYPESCRIPT,
    "Python": TEMPLATE_QA_PYTHON,
    "Android": TEMPLATE_QA_ANDROID,
    "React Native": TEMPLATE_QA_REACT_NATIVE,
}
