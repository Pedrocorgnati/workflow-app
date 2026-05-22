"""
Quick template definitions for header buttons.

Defines static command sequences for all non-dynamic header buttons.
The WBS button is dynamic and handled by wbs_template_builder.py
(including interleaved Codex plugin review steps during execute flow).

CURATED TEMPLATES - INTENTIONAL OMISSIONS
-----------------------------------------
These templates intentionally cover a curated subset of the ~555 SystemForge
slash commands. Each TEMPLATE_* tuple represents one operator-facing flow
(brief, modules, deploy, daily, marketing, business, QA, micro-architecture).
A command being absent from quick_templates.py is NOT a sync gap.

Rules of thumb for what belongs here:
  - Commands that the operator triggers as a sequence from a UI button
  - Commands that need a deterministic order with /clear, /model, /effort
    directives injected between them
  - Commands part of a recurring operational flow (daily, deploy, etc)

Commands that do NOT belong here:
  - One-off utilities (/cache-clear, /reset:*, /sync:*, /memory:*)
  - Subcommands of dynamic subflows already covered by wbs_template_builder.py
    or daily_loop/loop-app templates (modules:*, qa:*, intake-review:*,
    delivery:*, dcp:*, loop:*, daily-loop:*, study:*, etc)
  - Stack-specific review commands (nextjs:*, python:*, android:*, etc) which
    are dispatched by /validate-stack
  - Skill commands (/skill:*) which are invoked from inside other commands
  - Meta tooling (/cmd:*, /auto-improove:*, /optimize:*, /tools:*) operated
    individually
  - Plugin-namespaced commands (vercel:*, codex-plugin:*)

/cmd:readme-upd Fase 6 (sync templates) reports gaps but MUST NOT auto-add
commands from the categories above. Only add when the target template clearly
needs the command (human decision via AskUserQuestion).
"""

from __future__ import annotations

from workflow_app.domain import CommandSpec, EffortLevel, FlagSpec, InteractionType, ModelName

# ─── Short aliases ──────────────────────────────────────────────────────────── #

_O = ModelName.OPUS
_S = ModelName.SONNET
_H = ModelName.SONNET
_I = InteractionType.INTERACTIVE
_A = InteractionType.AUTO

# Commands bumped to EffortLevel.HIGH per TASK-053 §7 (codex thread 019d8577).
# 22 commands — 3 delivery:* entries from the original spec were dropped after
# static verification showed they never appear in any template tuple (drift D1).
_HIGH_EFFORT_COMMANDS: frozenset[str] = frozenset({
    "/deep-research-1",
    "/deep-research-2",
    "/break-intake",
    "/prd-create",
    "/hld-create",
    "/lld-create",
    "/threat-model-create",
    "/modules:create-core",
    "/modules:create-decomposition",
    "/modules:create-structure",
    "/modules:create-coverage",
    "/modules:review-created",
    "/rollout-strategy-create",
    "/modules:build-milestones",
    "/review-executed-micro-architecture",
    "/review-created-micro-architecture",
    "/final-review",
    "/validate-stack",
    "/review-prd-flow",
    "/review-executed-module",
    "/secrets-scan",
    "/compliance-check",
})


def _resolve_effort(name: str, override: EffortLevel | None) -> EffortLevel:
    if override is not None:
        return override
    return EffortLevel.HIGH if name in _HIGH_EFFORT_COMMANDS else EffortLevel.STANDARD


def _spec(
    name: str,
    model: ModelName,
    interaction: InteractionType,
    pos: int,
    optional: bool = False,
    effort: EffortLevel | None = None,
) -> CommandSpec:
    return CommandSpec(
        name=name,
        model=model,
        interaction_type=interaction,
        position=pos,
        is_optional=optional,
        effort=_resolve_effort(name, effort),
    )


def _same_context_group(prev_name: str, curr_name: str) -> bool:
    """True if two commands belong to the same pipeline group (no /clear between them).

    Groups are sub-pipelines where each step feeds into the next and benefits
    from shared conversation context:
      - /qa:prep → /qa:trace → /qa:report
      - /create-task → /review-created-task
      - /execute-task → /review-executed-task
      - /tdd:* chain
      - /backend:scan → /backend:audit → /backend:test-check → /backend:report
      - /frontend:scan → /frontend:audit → /frontend:assets-check → /frontend:report
      - /deep-research-1 → /deep-research-2
      - /c4-diagram-create → /mermaid-diagram-create

    NOT grouped: stack review commands (/nextjs:*, /python:*, etc.) — they are
    independent checks that don't need each other's context.
    """
    _PIPELINE_PREFIXES = ("/qa:", "/backend:", "/frontend:", "/daily:")
    for prefix in _PIPELINE_PREFIXES:
        if prev_name.startswith(prefix) and curr_name.startswith(prefix):
            return True
    prev_head = prev_name.split(maxsplit=1)[0]
    curr_head = curr_name.split(maxsplit=1)[0]
    if (prev_head, curr_head) in {
        ("/create-task", "/review-created-task"),
        ("/execute-task", "/review-executed-task"),
    }:
        return True
    if prev_head.startswith("/tdd:") and curr_head.startswith("/tdd:"):
        return True
    if prev_name.startswith("/deep-research") and curr_name.startswith("/deep-research"):
        return True
    if "diagram-create" in prev_name and "diagram-create" in curr_name:
        return True
    return False


def _repeats(
    cmd: str,
    model: ModelName,
    n: int,
    start_pos: int,
    effort: EffortLevel | None = None,
) -> list[CommandSpec]:
    """Generate n repetitions of (/clear, cmd) starting at start_pos.

    Used exclusively by TEMPLATE_AUTO_IMPROOVE.
    Regenerated by /auto-improove:update-workflow-template — do not edit manually.
    """
    out: list[CommandSpec] = []
    pos = start_pos
    for _ in range(n):
        out.append(CommandSpec(name="/clear", model=model, interaction_type=_A, position=pos))
        pos += 1
        out.append(_spec(cmd, model, _A, pos, effort=effort))
        pos += 1
    return out


def _inject_clears(specs: list[CommandSpec]) -> list[CommandSpec]:
    """Insert /clear + /model + /effort block headers before AUTO commands.

    Follows TEMPLATE_INTAKE_REVIEW canonical pattern (see WORKFLOW-DETAILED §2):
    each block starts with the triplet `/clear`, `/model {X}`, `/effort {Y}` where
    X and Y come from the next real command's resolved model/effort.

    Rules:
      - Leading /clear entries in the input are stripped — this function owns
        block-header emission.
      - An initial header is emitted once, seeded from the first real command.
      - INTERACTIVE commands follow the same state rules as AUTO commands;
        interaction mode does not imply model/effort inheritance is safe.
      - AUTO commands in the same context group as the previous command:
        no header emitted (they share a sub-pipeline).
      - Other AUTO commands: full `/clear` + `/model` + `/effort` block header
        emitted before them.

    Applied to: Brief, Modules, Deploy, Mkt, Business, QA, Micro-Architecture,
    Listener Test, Blog. NOT applied to: Daily (context flows through the full
    session by design) or Intake Review (already hand-authored with triplets).

    Optimization: /model e /effort so sao reemitidos quando o valor MUDA em
    relacao ao header anterior. /clear e sempre emitido (delimita o bloco e
    reseta o contexto de conversa, mas nao reseta model/effort no CLI).
    """
    result: list[CommandSpec] = []
    pos = 1
    last_model: ModelName | None = None
    last_effort: EffortLevel | None = None

    def _emit_header(model: ModelName, effort: EffortLevel) -> None:
        nonlocal pos, last_model, last_effort
        result.append(CommandSpec(name="/clear", model=model, interaction_type=_A, position=pos))
        pos += 1
        if model != last_model:
            result.append(CommandSpec(name=f"/model {model.value.lower()}", model=model, interaction_type=_A, position=pos))
            pos += 1
            last_model = model
        if effort != last_effort:
            result.append(CommandSpec(name=f"/effort {effort.value}", model=model, interaction_type=_A, position=pos))
            pos += 1
            last_effort = effort

    first_real = next((s for s in specs if s.name != "/clear"), None)
    if first_real is not None:
        _emit_header(first_real.model, _resolve_effort(first_real.name, first_real.effort))

    prev_name = ""
    for spec in specs:
        if spec.name == "/clear":
            continue
        effective_effort = _resolve_effort(spec.name, spec.effort)
        needs_header = (
            prev_name != ""
            and not _same_context_group(prev_name, spec.name)
        )
        if needs_header:
            _emit_header(spec.model, effective_effort)
        result.append(CommandSpec(
            name=spec.name,
            model=spec.model,
            interaction_type=spec.interaction_type,
            position=pos,
            is_optional=spec.is_optional,
            estimated_seconds=spec.estimated_seconds,
            phase=spec.phase,
            config_path=spec.config_path,
            effort=effective_effort,
            testid=spec.testid,
            blocked_reason=spec.blocked_reason,
            kimi_eligible=spec.kimi_eligible,
            kind=spec.kind,
            local_action_id=spec.local_action_id,
            flags_boolean=list(spec.flags_boolean),
            flags_with_value=list(spec.flags_with_value),
        ))
        pos += 1
        prev_name = spec.name
    return result


# ─── JSON: apenas /project-json ─────────────────────────────────────────────── #

TEMPLATE_JSON: list[CommandSpec] = [
    _spec("/clear",        _S, _A, 0),
    _spec("/project-json", _S, _I, 1),
]

# ─── Brief: Novo Projeto (from z-templates/start.md [new]) ──────────────────── #

TEMPLATE_BRIEF_NEW: list[CommandSpec] = _inject_clears([
    _spec("/clear",                     _S, _A,  0),
    _spec("/first-brief-create",        _O, _I,  1),
    _spec("/intake:obvious",            _O, _I,  2),
    _spec("/intake:analyze",            _S, _A,  2),
    _spec("/intake:enhance",              _O, _I,  3),
    _spec("/intake:question",             _O, _A,  3),
    _spec("/intake:response",             _O, _I,  3),
    _spec("/intake:front-end",            _O, _I,  4),
    _spec("/tech-feasibility",            _O, _I,  5),
    _spec("/break-intake",                _S, _A,  6),
    _spec("/prd-create",                  _O, _I,  7),
    _spec("/user-stories-create",         _S, _I,  7),
    _spec("/hld-create",                _O, _I,  8),
    _spec("/lld-create",                _O, _I,  9),
    _spec("/core-docs-check",           _S, _A, 10),
    _spec("/api-contract-create",       _S, _A, 11),
    _spec("/threat-model-create",       _O, _A, 11),
    _spec("/privacy-assessment-create", _S, _I, 12),
    _spec("/error-catalog-create",      _S, _A, 13),
    _spec("/notification-spec-create",  _S, _I, 14),
    _spec("/analytics-spec-create",     _S, _I, 15),
    _spec("/i18n-spec-create",          _S, _I, 16),
    _spec("/deep-research-1",           _O, _A, 17),
    _spec("/deep-research-2",           _O, _A, 18),
    _spec("/adr-create",                _S, _I, 19),
    _spec("/fdd-create",                _O, _I, 20),
    _spec("/c4-diagram-create",         _H, _A, 21),
    _spec("/mermaid-diagram-create",    _H, _A, 22),
    _spec("/design-create",             _O, _I, 23),
    _spec("/review-prd-flow",           _O, _I, 24),
    _spec("/auto-flow rocks",           _S, _A, 25),
    _spec("/optimize:analyse-cmd",      _S, _A, 26),
    # {specific-insertion} — runtime hook: workflow-app injeta aqui os comandos
    # specific do projeto ativo (.claude/projects/{slug}.json > specific_commands.active[]).
    # Ver ai-forge/workflow-rules/WORKFLOW-APP-RULES.md §4 e blacksmith/loop-archives/workflow-app-specific-insertion/PROMPT.md.
    _spec("/optimize:cmd-insert",       _O, _I, 27),
    _spec("/optimize:scaffolds",        _O, _I, 28),
    _spec("/optimize:blueprints",       _O, _I, 29),
    _spec("/optimize:guardrails",       _S, _I, 30),
    _spec("/optimize:integrations",     _O, _I, 31),
    _spec("/optimize:review",           _S, _A, 32),
])

# ─── Brief: Feature (from z-templates/start.md [feature]) ───────────────────── #

TEMPLATE_BRIEF_FEATURE: list[CommandSpec] = _inject_clears([
    _spec("/clear",                     _S, _A,  0),
    _spec("/feature-brief-create",      _O, _I,  1),
    _spec("/intake:obvious",            _O, _I,  2),
    _spec("/intake:analyze",            _S, _A,  2),
    _spec("/intake:enhance",              _O, _I,  3),
    _spec("/intake:question",             _O, _A,  3),
    _spec("/intake:response",             _O, _I,  3),
    _spec("/intake:front-end",            _O, _I,  4),
    _spec("/tech-feasibility",            _O, _I,  5),
    _spec("/break-intake",                _S, _A,  6),
    _spec("/prd-create",                  _O, _I,  7),
    _spec("/user-stories-create",         _S, _I,  8),
    _spec("/lld-create",                _O, _I,  9),
    _spec("/error-catalog-create",      _S, _A, 10),
    _spec("/notification-spec-create",  _S, _I, 11),
    _spec("/adr-create",                _S, _I, 12),
    _spec("/fdd-create",                _O, _I, 13),
    _spec("/c4-diagram-create",         _H, _A, 14),
    _spec("/mermaid-diagram-create",    _H, _A, 15),
    _spec("/design-create",             _O, _I, 16),
    _spec("/review-prd-flow",           _O, _I, 17),
    _spec("/auto-flow rocks",           _S, _A, 18),
    _spec("/optimize:analyse-cmd",      _S, _A, 19),
    # {specific-insertion} — runtime hook: workflow-app injeta aqui os comandos
    # specific do projeto ativo (.claude/projects/{slug}.json > specific_commands.active[]).
    # Ver ai-forge/workflow-rules/WORKFLOW-APP-RULES.md §4.
    _spec("/optimize:cmd-insert",       _O, _I, 19),
    _spec("/optimize:scaffolds",        _O, _I, 19),
    _spec("/optimize:blueprints",       _O, _I, 19),
    _spec("/optimize:guardrails",       _S, _I, 20),
    _spec("/optimize:integrations",     _O, _I, 21),
    _spec("/optimize:review",           _S, _A, 22),
])

# ─── Modules (from z-templates/modules.md) ───────────────────────────────────── #

TEMPLATE_MODULES: list[CommandSpec] = _inject_clears([
    _spec("/clear",                     _S, _A, 0),
    _spec("/modules:create-core",       _O, _I, 1),
    _spec("/modules:create-blueprints", _S, _A, 2),
    _spec("/modules:create-decomposition", _O, _I, 3),
    _spec("/modules:create-structure",  _S, _A, 4),
    _spec("/modules:create-coverage",   _S, _A, 5),
    _spec("/modules:user-stories",      _S, _A, 6),
    _spec("/modules:create-overview",   _S, _A, 7),
    _spec("/modules:review-created",    _O, _I, 8),
    _spec("/rollout-strategy-create",        _S, _I, 9),
    _spec("/modules:build-milestones",       _S, _I, 10),
    _spec("/modules:build-shared-skeleton",  _S, _A, 11),
    _spec("/delivery:init",                  _S, _A, 12),
])

# ─── Migration (WordPress legacy → Next.js multi-tenant) ────────────────────── #
# Usado quando o projeto migra N sites WP em hosting Apache (HostGator/UOL/etc)
# para um monorepo Next.js multi-tenant. Sequencia: scrape → mapa de redirects →
# .htaccess por tenant → bootstrap zonas Cloudflare → cutover DNS sequencial.

TEMPLATE_MIGRATION: list[CommandSpec] = _inject_clears([
    _spec("/clear",                          _S, _A, 0),
    _spec("/migration:wp-scrape",            _O, _I, 1),
    _spec("/migration:redirect-map",         _O, _I, 2),
    _spec("/migration:htaccess-gen",         _S, _A, 3),
    _spec("/seo:cloudflare-zone-bootstrap",  _S, _I, 4),
    _spec("/migration:dns-cutover",          _S, _I, 5),
])

# ─── HostGator multi-tenant (build orquestrado + deploy + NAP validation) ──── #
# Sequencia operacional pos-migracao para projetos com N tenants estaticos
# em HostGator compartilhado: build N-output → validacao NAP local SEO →
# commit + rsync deploy multi-dominio.

TEMPLATE_HOSTGATOR: list[CommandSpec] = _inject_clears([
    _spec("/clear",                          _S, _A, 0),
    _spec("/multitenant:build-orchestrate",  _S, _I, 1),
    _spec("/seo:nap-validate",               _O, _A, 2),
    _spec("/commit:hostgator",               _S, _I, 3),
])

# ─── Deploy (from z-templates/deploy.md) ─────────────────────────────────────── #

TEMPLATE_DEPLOY: list[CommandSpec] = _inject_clears([
    _spec("/clear",                 _S, _A,  0),
    _spec("/ci-cd-create",          _S, _I,  1),
    _spec("/supabase-sql-editor",   _S, _A,  2),
    _spec("/infra-create",          _S, _I,  3),
    _spec("/pre-deploy-testing",    _S, _I,  4),
    _spec("/deploy-checklist",      _S, _I,  5),
    _spec("/slo-create",            _S, _I,  6),
    _spec("/staging-validate",      _S, _A,  6),
    _spec("/monitoring-setup",      _S, _I,  7),
    _spec("/post-deploy-verify",    _S, _A,  8),
    _spec("/changelog-create",      _H, _A,  9),
    _spec("/deploy-flow",           _S, _A, 10),
    _spec("/marketing-readiness-check", _S, _A, 11),
])

# ─── Daily (from .claude/commands/daily/) ──────────────────────────────────────
# Pipeline leve: scan -> plan -> do -> validate -> review.
# Sem /clear entre steps (compartilham contexto via _DAILY-*.md).
# Model/effort variam por step — transicoes emitidas sem /clear.
#   scan     sonnet/standard  coleta mecanica, 2-min target
#   plan     opus/high        escopo + intencao + criterios de aceite (L2 adversarial)
#   do       sonnet/high      implementacao constrangida pelo plano
#   validate sonnet/standard  build/lint/test mecanico
#   review   sonnet/standard  sintese de artefatos, commit message
# _inject_clears nao e usada: ela so emite /model e /effort dentro de blocos /clear,
# incompativel com o padrao de contexto compartilhado + model variavel.

TEMPLATE_DAILY: list[CommandSpec] = [
    # header inicial — scan: sonnet/standard (Regra 3.4)
    CommandSpec(name="/clear",           model=_S, interaction_type=_A, position=1),
    CommandSpec(name="/model sonnet",    model=_S, interaction_type=_A, position=2),
    CommandSpec(name="/effort standard", model=_S, interaction_type=_A, position=3),
    _spec("/daily:scan",     _S, _A, 4,  effort=EffortLevel.STANDARD),
    # transicao sonnet/standard → opus/high (plan)
    CommandSpec(name="/model opus",      model=_O, interaction_type=_A, position=5),
    CommandSpec(name="/effort high",     model=_O, interaction_type=_A, position=6),
    _spec("/daily:plan",     _O, _A, 7,  effort=EffortLevel.HIGH),
    # transicao opus/high → sonnet/high (do — so model muda, effort continua high)
    CommandSpec(name="/model sonnet",    model=_S, interaction_type=_A, position=8),
    _spec("/daily:do",       _S, _A, 9,  effort=EffortLevel.HIGH),
    # transicao sonnet/high → sonnet/standard (validate — so effort muda)
    CommandSpec(name="/effort standard", model=_S, interaction_type=_A, position=10),
    _spec("/daily:validate", _S, _A, 11, effort=EffortLevel.STANDARD),
    # sem transicao (review: sonnet/standard = mesmo que validate)
    _spec("/daily:review",   _S, _A, 12, effort=EffortLevel.STANDARD),
]

# ─── Study (from .claude/commands/study.md) ────────────────────────────────────
# Pesquisa estruturada com output dual (user-friendly + tecnico).
# 3 modos: --simple, --deep, --heavy. Gera forged-goods/research/{name}.md.

TEMPLATE_STUDY: list[CommandSpec] = [
    _spec("/study", _O, _I, 0, effort=EffortLevel.HIGH),
]

# ─── Create Daily Loop (preparo no terminal — gera blacksmith/loop-archives/{slug}/) ── #
# Roda /daily-loop como orquestrador unico que internamente encadeia
# scan -> plan -> enumerate. Saida: PROGRESS.md + tasks/T-{model}-{effort}.md +
# _LOOP-CONFIG.json. Depois desse template, o usuario carrega o _LOOP-CONFIG.json
# em metrics-project-pill e clica [Execute daily loop] (queue-btn-daily-loop)
# para expandir os items pendentes na fila.
#
# Frontmatter de /daily-loop declara model: opus, effort: high — repetimos aqui
# para que /clear, /model e /effort sejam injetados no padrao do workflow-app.

TEMPLATE_CREATE_DAILY_LOOP: list[CommandSpec] = [
    _spec("/clear",       _O, _A, 0),
    _spec("/daily-loop",  _O, _A, 1, effort=EffortLevel.HIGH),
]

# ─── Intake Seed (preparacao do INTAKE para /intake-review:seed) ─────────────── #
# Dupla funcao:
#   1. Melhora o INTAKE.md original via /intake:obvious (preenche lacunas obvias
#      a partir do project.json + inferencias de conteudo) — deixa a base limpa.
#   2. Invoca /intake-review:seed — gera INTAKE.seeded.md e MILESTONES.seeded.md
#      com expansao exaustiva (dominios, CRUD, estados UX, auth, edge cases,
#      features consolidadas de docs_root/features/*/INTAKE.md), passando por
#      obvious-pass interno (FASE 2.5) antes de derivar os milestones.
#
# Ambos recebem o project.json apendado automaticamente pelo main_window
# (_on_pipeline_ready) a partir de app_state.config.config_path (metrics-project-pill).
#
# Uso manual — nao integrado ao /auto-flow. Executado sob demanda quando se quer
# preparar uma base maximamente expandida para /intake-review:create-checklist.
#
# Codex wiring: tanto /intake:obvious quanto /intake-review:seed ja invocam
# /skill:mcp-codex internamente (seed: FASE 1.1 Level 2 + FASE 2.5.5 Level 1).
# Nao adicionamos gates externos para evitar redundancia.

TEMPLATE_INTAKE_SEED: list[CommandSpec] = [
    # /model e /effort so sao reinjetados quando o valor MUDA. /clear nao reseta
    # nem modelo nem effort no CLI. Transicoes:
    #   model:  sonnet (bloco 0) -> opus (bloco 1, mantem em 2)
    #   effort: low (bloco 0)   -> medium (bloco 1) -> high (bloco 2)

    # Bloco 0: Reset de feature paths (Sonnet / low) — restaura project.json para paths base
    # — executa /reset:project-json deteccao + preview + confirmacao
    _spec("/clear",              _H, _A, 0),
    _spec("/model sonnet",        _H, _A, 1),
    _spec("/effort low",         _H, _A, 2),
    _spec("/reset:project-json", _H, _A, 3),

    # Bloco 1: obvious-pass do INTAKE original (Opus / medium)
    # — preenche lacunas derivaveis do project.json e inferencias de conteudo
    _spec("/clear",           _O, _A, 4),
    _spec("/model opus",      _O, _A, 5),
    _spec("/effort medium",   _O, _A, 6),
    _spec("/intake:obvious",  _O, _A, 7),

    # Bloco 2: seed (Opus / high) — INTAKE.seeded.md + MILESTONES.seeded.md
    # — consolida features de docs_root/features/*, aplica obvious-pass interno,
    #   deriva milestones expandidos so apos base otimizada
    _spec("/clear",                _O, _A, 8),
    _spec("/effort high",          _O, _A, 9),
    _spec("/intake-review:seed",   _O, _A, 10, effort=EffortLevel.HIGH),
]

# ─── Intake Review (subfluxo F9 QA) ─────────────────────────────────────────── #
# NOTE: No /clear auto-injection — explicit /clear + /model + /effort intercalado
# antes de cada bloco com mudanca de modelo/effort. Segue canonical loop A..I
# style (WORKFLOW-DETAILED.md §2).

TEMPLATE_INTAKE_REVIEW: list[CommandSpec] = [
    # Bloco 1: extracao inicial (Sonnet / standard)
    _spec("/clear",                          _S, _A,  0),
    _spec("/model sonnet",                   _S, _A,  1),
    _spec("/effort medium",                  _S, _A,  2),
    _spec("/intake-review:create-checklist", _S, _A,  3),

    # Bloco 2a: descoberta de gaps — list-improove + compare compartilham contexto
    _spec("/clear",                          _O, _A,  4),
    _spec("/model opus",                     _O, _A,  5),
    _spec("/effort high",                    _O, _A,  6),
    _spec("/intake-review:list-improove",    _O, _A,  7, effort=EffortLevel.HIGH),
    _spec("/intake-review:compare",          _O, _A,  8, effort=EffortLevel.HIGH),

    # Bloco 2b: priorizacao isolada — contexto limpo para create-gaplist (split anti-overload)
    _spec("/clear",                          _O, _A,  9),
    _spec("/model opus",                     _O, _A, 10),
    _spec("/effort high",                    _O, _A, 11),
    _spec("/intake-review:create-gaplist",   _O, _A, 12, effort=EffortLevel.HIGH),

    # Bloco 2.5: Codex adversarial review da gaplist (programatico, skip_prompt)
    _spec(
        "/skill:mcp-codex revisar a gaplist gerada por /intake-review:create-gaplist "
        "(output/wbs/{slug}/intake-review/gaplist.md). Topic_type=decision. Level 2 "
        "primary+secondary (senior-qa-architect + senior-adversarial). Identifique: "
        "(a) gaps do INTAKE que ficaram fora da gaplist, (b) priorizacao P0/P1/P2 "
        "inconsistente, (c) tasks com escopo ambiguo ou criterio de aceite fraco.",
        _S, _A, 13),

    # Bloco 3a.1: execucao P0 blockers — primeira passada (Opus / high)
    _spec("/clear",                             _O, _A, 14),
    _spec("/model opus",                        _O, _A, 15),
    _spec("/effort high",                       _O, _A, 16),
    _spec("/intake-review:execute-gaplist-p0",  _O, _A, 17, effort=EffortLevel.HIGH),

    # Bloco 3a.2: execucao P0 — segunda passada (continua checkpoint)
    _spec("/clear",                             _O, _A, 18),
    _spec("/model opus",                        _O, _A, 19),
    _spec("/effort high",                       _O, _A, 20),
    _spec("/intake-review:execute-gaplist-p0",  _O, _A, 21, effort=EffortLevel.HIGH),

    # Bloco 3b.1: execucao P1 high — primeira passada (Opus / medium)
    _spec("/clear",                             _O, _A, 22),
    _spec("/model opus",                        _O, _A, 23),
    _spec("/effort medium",                     _O, _A, 24),
    _spec("/intake-review:execute-gaplist-p1",  _O, _A, 25),

    # Bloco 3b.2: execucao P1 — segunda passada (continua checkpoint)
    _spec("/clear",                             _O, _A, 26),
    _spec("/model opus",                        _O, _A, 27),
    _spec("/effort medium",                     _O, _A, 28),
    _spec("/intake-review:execute-gaplist-p1",  _O, _A, 29),

    # Bloco 3b.5: gate de build/typecheck — P0+P1 nao podem ter quebrado o repo
    _spec("/build-verify",                      _S, _A, 30, effort=EffortLevel.STANDARD),

    # Bloco 3c: execucao P2+P3 medium/low (Opus / low) — batch pragmatico
    _spec("/clear",                             _O, _A, 31),
    _spec("/model opus",                        _O, _A, 32),
    _spec("/effort low",                        _O, _A, 33),
    _spec("/intake-review:execute-gaplist-p2",  _O, _A, 34, effort=EffortLevel.LOW),

    # Bloco 3.5: Codex adversarial review pos-execucao (programatico)
    _spec(
        "/skill:mcp-codex revisar o estado do workspace apos execucao completa da "
        "gaplist (P0+P1+P2). Topic_type=decision. Level 2 primary+secondary "
        "(senior-qa-architect + senior-adversarial). Identifique: (a) regressoes "
        "introduzidas, (b) INTAKE items ainda nao cobertos no codigo, (c) testes "
        "ou docs desatualizados frente ao codigo novo.",
        _S, _A, 35),

    # Bloco 3.6: validacao de stack completa antes do veredito
    _spec("/validate-stack",                    _O, _A, 36),

    # Bloco 4: veredito final (Opus / high)
    _spec("/clear",                          _O, _A, 37),
    _spec("/model opus",                     _O, _A, 38),
    _spec("/effort high",                    _O, _A, 39),
    _spec("/intake-review:review-executed",  _O, _A, 40, effort=EffortLevel.HIGH),

    # Bloco 4.5: scan de assets/imagens faltantes — append em ASSETS-TO-CREATE.md
    _spec("/assets:create",                  _S, _A, 41, effort=EffortLevel.STANDARD),

    # Bloco 5: housekeeping (Sonnet / low) — limpa historico para nova execucao
    _spec("/clear",                          _H, _A, 42),
    _spec("/model sonnet",                    _H, _A, 43),
    _spec("/effort low",                     _H, _A, 44),
    _spec("/intake-review:clear",            _H, _A, 45, optional=True, effort=EffortLevel.LOW),
]

# ─── Intake MAX Review (versao deep — Opus/MAX + Codex adversarial + gates) ── #
# Clone do TEMPLATE_INTAKE_REVIEW com effort 1-2 graus acima em cada comando
# (excecao do /intake-review:clear final — mantido Sonnet/LOW por instrucao direta).
#
# Ajustes sobre o clone naive (analise Level 2 primary+secondary):
#  - /skill:mcp-codex recebe argumento explicito (skip_prompt implicito via topic),
#    caso contrario entraria em modo interativo e quebraria a fila.
#  - list-improove em HIGH (satura antes do MAX — comando criativo/inferencial).
#
# Anti-overload (splits baseados em tamanho real dos comandos subjacentes):
#  - create-gaplist (394 linhas, maior dos intake-review) isolado em bloco
#    proprio com /clear apos compare — evita competir contexto com o compare
#    (318 linhas) que ja satura em projetos com 30+ models.
#  - execute-gaplist-p0/p1 rodam em DUAS passadas cada com /clear entre elas:
#    o comando tem checkpoint por task, segunda chamada continua de onde parou.
#    Garante que tasks deixadas half-done na primeira sejam concluidas.
#  - /build-verify entre P0+P1 e P2 para garantir que P0+P1 nao quebraram.
#  - /validate-stack antes do veredito para audit completo da stack.
#  - /assets:create apos review-executed para scan final de placeholders de
#    imagem e gerar prompts em forged-goods/assets/ASSETS-TO-CREATE.md (append-only).
#
# Limitacao conhecida: se /intake-review:review-executed emitir REPROVADO, o
# Ciclo 2 (re-run de create-gaplist com gaps residuais) precisa ser disparado
# manualmente re-clicando o botao. Branching condicional nao e expressivel no
# modelo linear de CommandSpec. Para auto-retry use /loop 1 {template}.

TEMPLATE_INTAKE_MAX_REVIEW: list[CommandSpec] = [
    # /model e /effort so sao injetados quando o valor MUDA. /clear nao reseta
    # nem o modelo nem o effort, entao reinjetar entre blocos com mesmo valor
    # e desperdicio. Transicoes:
    #   model:  opus (inicio)               -> sonnet (housekeeping)
    #   effort: high (inicio) -> max (2a)   -> high (3c) -> max (4) -> low (5)

    # Bloco 1: extracao inicial — Opus/HIGH (era Sonnet/medium, +2 graus)
    _spec("/clear",                          _O, _A,  0),
    _spec("/model opus",                     _O, _A,  1),
    _spec("/effort high",                    _O, _A,  2),
    _spec("/intake-review:create-checklist", _O, _A,  3, effort=EffortLevel.HIGH),

    # Bloco 2a: descoberta de gaps — list-improove + compare compartilham contexto
    _spec("/clear",                          _O, _A,  4),
    _spec("/effort max",                     _O, _A,  5),
    _spec("/intake-review:list-improove",    _O, _A,  6, effort=EffortLevel.HIGH),
    _spec("/intake-review:compare",          _O, _A,  7, effort=EffortLevel.MAX),

    # Bloco 2b: priorizacao isolada — contexto limpo para create-gaplist deliberar
    # P0/P1/P2/P3 sem competir com o compare-report ja em memoria (split G-L)
    _spec("/clear",                          _O, _A,  8),
    _spec("/intake-review:create-gaplist",   _O, _A,  9, effort=EffortLevel.MAX),

    # Bloco 2.5: Codex adversarial review da gaplist (programatico, skip_prompt)
    _spec(
        "/skill:mcp-codex revisar a gaplist gerada por /intake-review:create-gaplist "
        "(output/wbs/{slug}/intake-review/gaplist.md). Topic_type=decision. Level 2 "
        "primary+secondary (senior-qa-architect + senior-adversarial). Identifique: "
        "(a) gaps do INTAKE que ficaram fora da gaplist, (b) priorizacao P0/P1/P2 "
        "inconsistente, (c) tasks com escopo ambiguo ou criterio de aceite fraco. "
        "Retorne findings acionaveis antes da execucao.",
        _O, _A, 10, effort=EffortLevel.MAX),

    # Bloco 3a.1: execucao P0 blockers — primeira passada
    _spec("/clear",                             _O, _A, 11),
    _spec("/intake-review:execute-gaplist-p0",  _O, _A, 12, effort=EffortLevel.MAX),

    # Bloco 3a.2: execucao P0 — segunda passada (continua checkpoint, conclui pendentes)
    _spec("/clear",                             _O, _A, 13),
    _spec("/intake-review:execute-gaplist-p0",  _O, _A, 14, effort=EffortLevel.MAX),

    # Bloco 3b.1: execucao P1 high — primeira passada
    _spec("/clear",                             _O, _A, 15),
    _spec("/intake-review:execute-gaplist-p1",  _O, _A, 16, effort=EffortLevel.MAX),

    # Bloco 3b.2: execucao P1 — segunda passada (conclui checkpoints pendentes)
    _spec("/clear",                             _O, _A, 17),
    _spec("/intake-review:execute-gaplist-p1",  _O, _A, 18, effort=EffortLevel.MAX),

    # Bloco 3b.5: gate de build/typecheck — P0+P1 nao podem ter quebrado o repo
    _spec("/build-verify",                      _S, _A, 19, effort=EffortLevel.STANDARD),

    # Bloco 3c: execucao P2+P3 — Opus/HIGH (era Opus/LOW, +2 graus)
    _spec("/clear",                             _O, _A, 20),
    _spec("/effort high",                       _O, _A, 21),
    _spec("/intake-review:execute-gaplist-p2",  _O, _A, 22, effort=EffortLevel.HIGH),

    # Bloco 3.5: Codex adversarial review pos-execucao (programatico)
    _spec(
        "/skill:mcp-codex revisar o estado do workspace apos execucao completa da "
        "gaplist (P0+P1+P2). Topic_type=decision. Level 2 primary+secondary "
        "(senior-qa-architect + senior-adversarial). Identifique: (a) regressoes "
        "introduzidas, (b) INTAKE items ainda nao cobertos no codigo, (c) testes "
        "ou docs desatualizados frente ao codigo novo. Retorne lista de acoes "
        "residuais para o review-executed.",
        _O, _A, 23, effort=EffortLevel.MAX),

    # Bloco 3.6: validacao de stack completa antes do veredito
    _spec("/validate-stack",                    _O, _A, 24, effort=EffortLevel.HIGH),

    # Bloco 4: veredito final — Opus/MAX (era Opus/HIGH, +1 grau)
    _spec("/clear",                          _O, _A, 25),
    _spec("/effort max",                     _O, _A, 26),
    _spec("/intake-review:review-executed",  _O, _A, 27, effort=EffortLevel.MAX),

    # Bloco 4.5: scan de assets/imagens faltantes — append em ASSETS-TO-CREATE.md
    # Comando ja e append-only por design (escaneia @ASSET_PLACEHOLDER, PNG
    # minimos, MP4 vazios; gera prompts gpt-image-1; grava organizado por H1
    # de workspace_root em ordem de chegada). Sonnet/medium e o default.
    _spec("/assets:create",                  _S, _A, 28, effort=EffortLevel.STANDARD),

    # Bloco 5: housekeeping — Sonnet/LOW (mudanca de modelo: opus -> sonnet)
    _spec("/clear",                          _H, _A, 29),
    _spec("/model sonnet",                    _H, _A, 30),
    _spec("/effort low",                     _H, _A, 31),
    _spec("/intake-review:clear",            _H, _A, 32, optional=True, effort=EffortLevel.LOW),
]

# ─── Marketing (from z-templates/mkt.md) ──────────────────────────────────────── #

TEMPLATE_MKT: list[CommandSpec] = _inject_clears([
    _spec("/clear",                 _S, _A, 0),
    _spec("/docs-create",           _S, _A, 1),
    _spec("/mkt:portfolio-add",     _H, _A, 2),
    _spec("/mkt:linkedin-mkt",      _S, _A, 3),
    _spec("/mkt:instagram-mkt",     _H, _A, 4),
    _spec("/mkt:portfolio-publish", _H, _A, 5),
    _spec("/handoff-create",        _S, _A, 6),
])

# ─── Business (from z-templates/business.md) ──────────────────────────────────── #

TEMPLATE_BUSINESS: list[CommandSpec] = _inject_clears([
    _spec("/clear",                          _S, _A, 0),
    _spec("/business:product-brief-create",  _S, _A, 1),
    _spec("/business:sow-create",            _O, _I, 2),
    _spec("/business:create-budget",         _S, _I, 3),
    _spec("/business:simple-budget",         _S, _I, 4),
    _spec("/business:upsell-suggestion",    _O, _I, 5),
    _spec("/business:generate-pdf-docs",     _H, _A, 7),
    _spec("/business:generate-json-project", _H, _A, 7),
])

# ─── QA Templates per stack (from z-templates/qa.md) ──────────────────────────── #

_QA_BASE: list[tuple[str, ModelName, InteractionType]] = [
    ("/intake-review:create-checklist", _S, _A),
    ("/intake-review:list-improove",    _O, _A),
    ("/intake-review:compare",          _O, _A),
    ("/intake-review:create-gaplist",   _O, _A),
    ("/intake-review:execute-gaplist-p0",  _O, _A),
    ("/intake-review:execute-gaplist-p1",  _O, _A),
    ("/intake-review:execute-gaplist-p2",  _O, _A),
    ("/intake-review:review-executed",  _O, _A),
    ("/qa:prep",              _S, _A),
    ("/qa:trace",             _O, _A),
    ("/qa:report",            _S, _A),
    ("/validate-roles",       _O, _A),
    ("/validate-billing",     _O, _A),
    ("/backend:scan",         _S, _A),
    ("/backend:audit",        _O, _A),
    ("/backend:test-check",   _S, _A),
    ("/backend:report",       _S, _A),
    ("/frontend:scan",        _S, _A),
    ("/frontend:audit",        _O, _A),
    ("/frontend:mobile-check", _S, _A),
    ("/frontend:assets-check", _S, _A),
    ("/frontend:report",      _S, _A),
    ("/qa-remediate",         _S, _A),
    ("/qa:summary",           _S, _A),
    ("/load-test-create",     _S, _A),
    ("/tech-debt-audit",      _S, _A),
    ("/dependency-audit",     _S, _A),
    ("/secrets-scan",         _H, _A),
    ("/compliance-check",     _S, _A),
    ("/mutation-test-create",  _H, _A),
    ("/review-language",      _S, _A),
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
    ("/validation-remediate",      _S, _A),
    ("/validation-summary",        _S, _A),
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
    ("/validation-remediate",      _S, _A),
    ("/validation-summary",        _S, _A),
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
    ("/validation-remediate",  _S, _A),
    ("/validation-summary",    _S, _A),
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
    ("/validation-remediate",  _S, _A),
    ("/validation-summary",    _S, _A),
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
    ("/validation-remediate",       _S, _A),
    ("/validation-summary",         _S, _A),
]


def _build_qa_template(stack_cmds: list[tuple[str, ModelName, InteractionType]]) -> list[CommandSpec]:
    """Build a QA template by combining base QA commands with stack-specific ones."""
    base_specs = [_spec(name, model, interaction, i + 1) for i, (name, model, interaction) in enumerate(_QA_BASE + stack_cmds)]
    # _inject_clears already seeds the initial /clear + /model + /effort block header.
    return _inject_clears(base_specs)


TEMPLATE_QA_NEXTJS: list[CommandSpec] = _build_qa_template(_QA_NEXTJS)
TEMPLATE_QA_TYPESCRIPT: list[CommandSpec] = _build_qa_template(_QA_TYPESCRIPT)
TEMPLATE_QA_PYTHON: list[CommandSpec] = _build_qa_template(_QA_PYTHON)
TEMPLATE_QA_ANDROID: list[CommandSpec] = _build_qa_template(_QA_ANDROID)
TEMPLATE_QA_REACT_NATIVE: list[CommandSpec] = _build_qa_template(_QA_REACT_NATIVE)

# ─── Micro-Architecture DCP-lite (F4b) ───────────────────────────────────────── #
# Pipeline /micro:* de 5 comandos que produz PRD + USER-STORIES + ARCHITECTURE +
# _micro-flow-hints + modules consumiveis por queue-btn-dcp-build (DCP completo).
# Substitui o orquestrador legado /micro-architecture + /micro:setup + /micro:plan.
# Referencia: blacksmith/loop/05-13-micro-architecture-refactor.md Parte 2.

TEMPLATE_MICRO_ARCHITECTURE: list[CommandSpec] = _inject_clears([
    _spec("/micro:brief",              _O, _I, 1, effort=EffortLevel.HIGH),
    _spec("/micro:architecture",       _O, _A, 2, effort=EffortLevel.HIGH),
    _spec("/micro:specific-flow-prep", _O, _A, 3, effort=EffortLevel.HIGH),
    _spec("/micro:modularize",         _O, _A, 4, effort=EffortLevel.HIGH),
    _spec("/micro:review",             _O, _A, 5, effort=EffortLevel.HIGH),
])

# ─── Auto-Improove Balanced Flow (Daily tab) ────────────────────────────────── #
# Fluxo balanceado para melhoria contínua do SystemForge.
# Uma iteração = ~10% de progresso em todos os arquivos de progresso.
# Rodar 10× (via Loop) cobre ~97-100% de tudo.
#
# Sem vínculo com projeto — opera sobre os arquivos do próprio SystemForge.
# Excluídos intencionalmente: /auto-improove:clean (quebraria o fluxo),
#                             /auto-improove:update-workflow-template (este gerador).

# << AUTO-GENERATED by /auto-improove:update-workflow-template — DO NOT EDIT MANUALLY >>
# Gerado em: 2026-03-28
# Alvo: X=10 iterações para cobrir ~97-100% de todos os arquivos de progresso.
#
# EXCLUSÕES INTENCIONAIS:
#   /auto-improove:clean             — quebraria o fluxo ao deletar progresso
#   /auto-improove:update-workflow-template — este próprio comando
#   /auto-improove:flow              — FLOW-IMPROOVE.md não existe ainda
#
# Por iteração: cmd×33, cli-bp×33, guardrails×8, blueprints×25, templates×3, fases×2, skills×2, anthropic×4
# Total de entradas: 220   (cada par = /clear + comando)
#
# Para recalcular: /auto-improove:update-workflow-template

TEMPLATE_AUTO_IMPROOVE: list[CommandSpec] = [
    # ── /auto-improove:cmd (33×) ─ pos 0–65
    *_repeats("/auto-improove:cmd",        _O, 33,   0),
    # ── /auto-improove:cli-bp (33×) ─ pos 66–131
    *_repeats("/auto-improove:cli-bp",     _O, 33,  66),
    # ── /auto-improove:guardrails (8×) ─ pos 132–147
    *_repeats("/auto-improove:guardrails", _O,  8, 132),
    # ── /auto-improove:blueprints (25×) ─ pos 148–197
    *_repeats("/auto-improove:blueprints", _O, 25, 148),
    # ── /auto-improove:templates (3×) ─ pos 198–203
    *_repeats("/auto-improove:templates",  _O,  3, 198),
    # ── /auto-improove:fases (2×) ─ pos 204–207
    *_repeats("/auto-improove:fases",      _O,  2, 204),
    # ── /auto-improove:skills (2×) ─ pos 208–211
    *_repeats("/auto-improove:skills",     _O,  2, 208),
    # ── /auto-improove:anthropic (4×) ─ pos 212–219
    *_repeats("/auto-improove:anthropic",  _O,  4, 212),
]
# << END AUTO-GENERATED >>


# ─── Blog SEO (INIT flow from .claude/commands/blog/) ────────────────────────── #
# Full INIT pipeline: strategy → keywords → clusters → articles → deploy.
# /clear between independent steps; /model inserted by _load_quick_template.

TEMPLATE_BLOG: list[CommandSpec] = _inject_clears([
    _spec("/clear",                       _S, _A,  0),
    _spec("/blog:init-strategy",          _O, _A,  1),
    _spec("/blog:competitor-spy",         _O, _A,  2),
    _spec("/blog:discover-intents",       _O, _A,  3),
    _spec("/blog:discover-intents-part2", _O, _A,  4),
    _spec("/blog:expand-keywords",        _S, _A,  5),
    _spec("/blog:cluster-keywords",       _O, _A,  5),
    _spec("/blog:prioritize-topics",      _S, _A,  6),
    _spec("/blog:deduplicate-topics",     _S, _A,  7),
    _spec("/blog:generate-briefs",        _O, _A,  8),
    _spec("/blog:write-articles",         _O, _A,  9),
    _spec("/blog:review-seo",             _S, _A, 10),
    _spec("/blog:eeat-inject",            _S, _A, 11),
    _spec("/blog:localize-check",         _S, _A, 12),
    _spec("/blog:quality-gate",           _S, _A, 13),
    _spec("/blog:build-internal-links",   _S, _A, 14),
    _spec("/blog:build-metadata",         _H, _A, 15),
    _spec("/blog:schedule-batch",         _H, _A, 16),
    _spec("/blog:deploy",                 _S, _A, 17),
    _spec("/blog:hreflang-map",           _H, _A, 18),
])

# ─── Blog Stockpile (gera 1 pacote completo + push; sem promote, sem hreflang) ──────────────── #
# Correcao T002 — blacksmith/05-21-auto-blog/TASKLIST.md, decisao D1/Opcao B
# (DECISION-LOG.md). O template anterior era uma copia DESENROLADA e INCOMPLETA de
# /blog:stockpile-generate: tinha os 17 passos de keywords/briefs/artigos/review/
# quality-gate, mas NAO materializava packages/{uuid}/package.json (faltava o
# equivalente ao Passo 2.4 do gerador) nem rodava validate:stockpile (FASE 3).
# Resultado: o botao produzia diretorios orfaos que o promotor
# (promote-from-stockpile.ts) ignora silenciosamente — o artigo nunca era publicado.
# Consolidado numa unica chamada ao gerador canonico /blog:stockpile-generate, que
# ja inclui o Passo 2.4 (package.json com promotion_state=available, locales_present,
# lifecycle ISO, freshness_policy, scores) e a FASE 3. --max-packages 1 preserva a
# intencao 1:1 atual do botao (escopo por clique = decisao D2/T013). NAO passar
# workspace explicito: stockpile-generate resolve workspace pela mesma regra
# cwd/active-workspace dos demais /blog:* (ressalva R1 do D1). --max-packages 1 sem
# --days-of-stock/--per-day nao dispara a validacao cruzada M==DxP (ressalva R2).
# Promote para content/{locale}/blog/ e hreflang: GitHub Actions cron 13h UTC
# (promote-from-stockpile.yml), NAO desta pipeline local.

TEMPLATE_BLOG_STOCKPILE: list[CommandSpec] = _inject_clears([
    # Gera 1 pacote completo (topicos -> briefs -> artigos -> review -> quality-gate
    # -> package.json -> validate:stockpile). Output: packages/{uuid}/.
    _spec("/blog:stockpile-generate --max-packages 1",           _S, _A,  1),
    # Commit + push idempotente do diretorio stockpile/ para main remoto.
    _spec("/blog:stockpile-push",                                _S, _A,  2),
])


# ─── Boilerplate (from .claude/commands/boilerplate/) ───────────────────────── #
# Pipeline de 9 passos que converte um repo legado num boilerplate Next.js
# vendavel. Diferente dos demais: o argumento posicional NAO e project.json,
# e sim o caminho do repo (scan) ou do staging (8 passos seguintes).
# A injecao por-spec do config_path e feita em
# command_queue_widget.py::_on_boilerplate_clicked, nao em _on_pipeline_ready.
# Todos OPUS + AUTO + HIGH/MAX (alinhado ao frontmatter dos comandos).

TEMPLATE_BOILERPLATE: list[CommandSpec] = _inject_clears([
    _spec("/clear",                     _O, _A, 0),
    _spec("/boilerplate:scan",          _O, _A, 1, effort=EffortLevel.HIGH),
    _spec("/boilerplate:convert-nextjs", _O, _A, 2, effort=EffortLevel.MAX),
    _spec("/boilerplate:cleanup",       _O, _A, 3, effort=EffortLevel.HIGH),
    _spec("/boilerplate:persona",       _O, _A, 4, effort=EffortLevel.HIGH),
    _spec("/boilerplate:mockify",       _O, _A, 5, effort=EffortLevel.HIGH),
    _spec("/boilerplate:persona-assets", _O, _A, 6, effort=EffortLevel.MAX),
    _spec("/boilerplate:enhance-fe",    _O, _A, 7, effort=EffortLevel.HIGH),
    _spec("/boilerplate:gen-sql",       _O, _A, 8, effort=EffortLevel.HIGH),
    _spec("/boilerplate:finalize",      _O, _A, 9, effort=EffortLevel.MAX),
])

# ─── Map for QA stack picker dialog ──────────────────────────────────────────── #

QA_STACK_TEMPLATES: dict[str, list[CommandSpec]] = {
    "Next.js": TEMPLATE_QA_NEXTJS,
    "TypeScript": TEMPLATE_QA_TYPESCRIPT,
    "Python": TEMPLATE_QA_PYTHON,
    "Android": TEMPLATE_QA_ANDROID,
    "React Native": TEMPLATE_QA_REACT_NATIVE,
}


# ─── Command flag specs for modal argument dialog ───────────────────────────── #
# Migrated from raw argument_hint strings to structured FlagSpec definitions.
# Placeholders (<slug>, <path.md>) live ONLY as placeholder text in FlagSpec;
# they are NEVER concatenated to the final command string.

COMMAND_FLAG_SPECS: dict[str, CommandSpec] = {
    "/loop": CommandSpec(
        name="/loop",
        flags_with_value=[
            FlagSpec(name="task", label="Tasklist", placeholder="caminho/para/tasklist.md"),
            FlagSpec(name="cmd", label="Comando", placeholder="caminho/para/comando.md"),
            FlagSpec(name="cmd-single", label="Cmd Single", placeholder="caminho/para/comando.md"),
            FlagSpec(name="both", label="Both", placeholder="caminho/para/tasklist.md"),
            FlagSpec(name="name", label="Nome", placeholder="slug"),
        ],
        flags_boolean=[],
    ),
    "/daily-loop": CommandSpec(
        name="/daily-loop",
        flags_with_value=[
            FlagSpec(name="tasklist", label="Tasklist", placeholder="caminho/para/tasklist.md"),
        ],
        flags_boolean=[],
    ),
    "/daily": CommandSpec(
        name="/daily",
        flags_with_value=[
            FlagSpec(name="tasklist", label="Tasklist", placeholder="caminho/para/tasklist.md"),
        ],
        flags_boolean=[],
    ),
    "/study": CommandSpec(
        name="/study",
        flags_with_value=[
            FlagSpec(name="name", label="Nome", placeholder="slug"),
            FlagSpec(
                name="mode",
                label="Modo",
                placeholder="",
                options=["--simple", "--deep", "--heavy"],
            ),
        ],
        flags_boolean=[],
    ),
}
