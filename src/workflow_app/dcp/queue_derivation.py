"""In-memory queue derivation from DCP-COMMAND-MATRIX.json (task-027 / st-05).

This module implements the canonical algorithm (source.md st-05 L442-515) that
replaces the legacy "read SPECIFIC-FLOW.json from disk" path in the workflow-app
widget. The widget invokes `derive_queue_from_matrix(...)` at queue position 6
of the B-dcp pipeline (item `dcp:load-specific-flow` / handler
`_handle_dcp_load_specific_flow`).

Algorithm summary (steps 1-17 of source.md):

    1.  Load + Pydantic-validate `DCP-COMMAND-MATRIX.json`.
    2.  Resolve `cm_id` (hint or first non-done module from delivery.json).
    3.  Detect whether `cm_id` is the last module in `execution_order`.
    4.  Iterate `PHASE_ORDER`; for each phase iterate
        `matrix.phase_buckets[phase]`; skip indices whose `filter` bit is 0.
    5.  For `per_task` entries in `A-creation` / `B3-execute`, expand against
        the REAL executable task specs on disk (canonical `enumerate_module_tasks`
        over `{wbs_root}/modules/{cm_id}`) — one command per real `TASK-*.md`,
        numeric-ordered, companion artifacts excluded. `loop_multiplier[phase]`
        is now a cross-check (WARN on drift, Zero Silencio) plus a fallback to
        synthesizing `TASK-{k}.md` ONLY when `wbs_root` is None (legacy/
        programmatic callers + tests). When `wbs_root` IS provided but the
        module dir does not resolve, derivation raises ValueError (fail-loud,
        loop 06-09): synthesizing from a possibly-stale multiplier there
        fabricates phantom tasks ("task N nao existe") and masks the real
        problem (cm_id <-> dirname drift / wrong wbs_root resolution).
    6.  Append fold_in_rules:
            H-commit          ALWAYS
            I-human-signoff   ALWAYS
            G-deploy          only when is_last
            I-human-mkt       only when is_last
    7.  Drop commands whose rendered name is in
        `matrix.modules[cm_id].overrides_skipped`.
    8.  Return List[CommandSpec] for `signal_bus.pipeline_ready.emit(...)`.

The two helpers `_next_non_done_module_id` and `_last_module_id` are also
re-exported from `workflow_app.dcp.specific_flow_handler` so callers that
already import from there keep working.

Edge cases (lista vazia, nunca null - source.md L466-470):

    - Single-module project: is_last = True -> all fold_in_rules apply.
    - No-deploy: fold_in_rules["G-deploy"] = [] -> no-op silencioso.
    - No-mkt: fold_in_rules["I-human-mkt"] = [] -> idem.
    - Single-module + no-deploy + no-mkt: queue final sem G nem I-mkt.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

from pydantic import ValidationError

from workflow_app.domain import (
    CommandSpec,
    EffortLevel,
    InteractionType,
    ModelName,
)
from workflow_app.dcp.task_enum import enumerate_module_tasks
from workflow_app.models.dcp_command_matrix import (
    CommandIndexEntry,
    CommandRef,
    DcpCommandMatrix,
    ModuleEntry,
)
from workflow_app.templates.quick_templates import _inject_clears

logger = logging.getLogger(__name__)


# Canonical placeholder token (matches {project_json}, {module_n}, ...) used to
# detect a render that drifted from the placeholder vocabulary. Prose braces are
# not used in any canonical template, so this never matches legitimate output.
_UNRESOLVED_PLACEHOLDER_RE = re.compile(r"\{[a-z_][a-z0-9_]*\}")

# A bare slash-token without args/placeholders (with `:` namespaces). Mirrors
# command_queue_widget._BARE_SLASH_NAME_RE and _dcp_canonical.BARE_SLASH_NAME_RE.
_BARE_SLASH_NAME_RE = re.compile(r"^/[a-z][a-z0-9-]*(:[a-z0-9-]+)*$")


# ─── canonical condition engine (defense-in-depth) ──────────────────────── #
#
# The per-module filter bits are the materialized cache of the canonical
# condition verdict (computed by the producer, build_module_pipeline +
# specific_flow.matrix_filter). As a SAFETY NET against a stale/incorrect
# matrix, the consumer re-evaluates `entry.condition` at emit-time when given
# the module's MODULE-META + project.json. This can only ADD drops (a bit==0
# entry is skipped before this runs), never restore — so it can never leak a
# command whose condition is False, even if the cached bit is wrongly 1.
#
# Cross-package: profiles.py lives under .claude/commands/_lib (not on the
# workflow-app path). We add it defensively and import lazily; on ANY failure
# we log a WARN and fall back to filter-only behavior so the queue NEVER fails
# to load (Zero Silencio: the WARN surfaces the degraded mode).

_evaluate_condition_cached: "Optional[Any]" = None
_evaluate_condition_loaded = False


def _load_evaluate_condition() -> "Optional[Any]":
    """Lazily import profiles.evaluate_condition; cache the result (or None)."""
    global _evaluate_condition_cached, _evaluate_condition_loaded
    if _evaluate_condition_loaded:
        return _evaluate_condition_cached
    _evaluate_condition_loaded = True
    try:
        repo_root = Path(__file__).resolve().parents[5]
        lib_dir = repo_root / ".claude" / "commands" / "_lib"
        import sys as _sys
        if str(lib_dir) not in _sys.path:
            _sys.path.insert(0, str(lib_dir))
        from specific_flow.profiles import evaluate_condition  # noqa: E402
        _evaluate_condition_cached = evaluate_condition
    except Exception as exc:  # pragma: no cover - import guard
        logger.warning(
            "[dcp-queue] condition engine indisponivel (%s); defense-in-depth "
            "desligada, usando filter_bits apenas.", exc
        )
        _evaluate_condition_cached = None
    return _evaluate_condition_cached


def _condition_holds(
    condition: Optional[str],
    meta: Optional[dict],
    project: Optional[dict],
) -> bool:
    """True if the entry should be emitted per its condition.

    Returns True (emit) when context is absent (meta/project None) or the engine
    is unavailable — i.e. the consumer trusts the producer's filter bits unless
    it can prove the condition is False. Returns False ONLY when context is
    present, the engine loads, and the condition evaluates False.

    CONTRACT: ``meta`` MUST be ENRICHED with the delivery runtime snapshot
    (generator._enrich_meta_with_delivery_state) before being passed in. Passing
    RAW MODULE-META would let runtime-state predicates (module.state.*,
    review.*, tdd.gate_ready) default-false and FALSE-DROP a command the
    producer legitimately kept. The widget enriches before calling
    (command_queue_widget._load_condition_context); other callers must do the
    same or pass meta=None to disable this safety net.
    """
    if condition is None or meta is None or project is None:
        return True
    fn = _load_evaluate_condition()
    if fn is None:
        return True
    try:
        return bool(fn(condition, meta, project))
    except Exception as exc:  # pragma: no cover - never crash the queue
        logger.warning(
            "[dcp-queue] evaluate_condition('%s') falhou (%s); mantendo comando.",
            condition, exc,
        )
        return True


# ─── canonical-bare command set (single source of truth) ────────────────── #
#
# Some FULL_PROFILE commands are CANONICALLY bare by design: their template
# carries NO placeholder (e.g. /create-task-layout, /data-test-id, every
# /nextjs:* review). A bare rendering of these is CORRECT. Commands whose
# template DOES carry a placeholder (e.g. /create-task {task}) are NOT in this
# set, so a bare rendering of THEM is the loop 05-27 regression. This is the
# exact distinction the canonical validator uses (validate-dcp-matrix-canonical
# only flags BARE_NON_EXECUTABLE_NAME when the canonical template has "{"), so
# the consumer guard and the validator never disagree.

_canonical_bare_names_cached: "Optional[frozenset[str]]" = None
_canonical_bare_names_loaded = False


def canonical_bare_command_names() -> "Optional[frozenset[str]]":
    """Slash command names that are canonically bare (no placeholder required).

    Single source of truth = ``specific_flow.profiles.FULL_PROFILE`` (the same
    source the validator consumes). Returns the frozenset, or ``None`` when
    profiles cannot be imported so the caller can fall back to its own static
    snapshot — never a silent fail-open.
    """
    global _canonical_bare_names_cached, _canonical_bare_names_loaded
    if _canonical_bare_names_loaded:
        return _canonical_bare_names_cached
    _canonical_bare_names_loaded = True
    try:
        repo_root = Path(__file__).resolve().parents[5]
        lib_dir = repo_root / ".claude" / "commands" / "_lib"
        import sys as _sys
        if str(lib_dir) not in _sys.path:
            _sys.path.insert(0, str(lib_dir))
        from specific_flow import profiles  # noqa: E402
        steps = profiles.get_profile(profiles.PROFILE_FULL)
        _canonical_bare_names_cached = frozenset(
            st.template.strip()
            for st in steps
            if st.template.startswith("/") and "{" not in st.template
        )
    except Exception as exc:  # pragma: no cover - import guard
        logger.warning(
            "[dcp-queue] canonical-bare set indisponivel (%s); consumidor usara "
            "snapshot estatico de fallback.", exc
        )
        _canonical_bare_names_cached = None
    return _canonical_bare_names_cached


# Canonical phase order applied by the widget when deriving the queue
# (source.md st-05 L450-456). A-creation is iterated BEFORE this list as a
# dedicated sub-loop driven by `loop_multiplier["A-creation"]`. Phases
# G-deploy / H-commit / I-human-* are appended by the fold_in_rules step
# (NEVER iterated as phase_buckets entries by the widget).
PHASE_ORDER: tuple[str, ...] = (
    "B-tdd",
    "B-build",
    "B-dcp",
    "B3-execute",
    "C-linkage",
    "D-f8-micro",
    "D5-review",
    "E-qa-micro",
    "F-stack-plan",
    "F2-stack-check",
)

# Phases whose per_task entries consume loop_multiplier[phase] iterations.
# A-creation is iterated standalone (PRE pass before PHASE_ORDER); B3-execute
# is iterated inline when its bucket is reached.
PER_TASK_PHASES: frozenset[str] = frozenset({"A-creation", "B3-execute"})


_STACK_REVIEW_CMD: dict[str, str] = {
    "nextjs": "/nextjs:next-review",
    "typescript": "/typescript:ts-review",
    "python": "/python:py-review",
    "android": "/android:android-review",
    "reactnative": "/reactnative:rn-review",
}


# ─── helpers reused by widget + specific_flow_handler ───────────────────── #


_MODULE_KEY_RE = re.compile(r"^module-(\d+)([a-z]?)-")


def _sort_module_key(module_id: str) -> tuple:
    """Stable sort key tolerant of `module-6a-x` style suffixes."""
    m = _MODULE_KEY_RE.match(module_id)
    return (int(m.group(1)), m.group(2)) if m else (9999, module_id)


def _next_non_done_module_id(delivery: Any) -> Optional[str]:
    """Next module to work on when current_module is done/stranded, ordered by
    module number. DEPENDENCY-GATED (mirrors dcp_closer._next_eligible_module /
    the specific_flow_handler twin): a `pending` module whose in-set deps are
    not all `done` is skipped (cannot start yet); a mid-flight (non-pending,
    non-done) module is returned so a stranded pointer resumes it. External deps
    (not in the module set) are treated as satisfied, matching topo.py.
    """
    states = {
        mid: getattr(mod, "state", None) for mid, mod in delivery.modules.items()
    }
    for mid in sorted(delivery.modules.keys(), key=_sort_module_key):
        state = states[mid]
        if state == "done":
            continue
        if state == "pending":
            deps = getattr(delivery.modules[mid], "dependencies", None) or []
            if not all(states.get(d) == "done" for d in deps if d in states):
                continue
        return mid
    return None


def _last_module_id(matrix: DcpCommandMatrix) -> Optional[str]:
    """Return the last module_id in canonical order, or None when modules empty.

    Uses `matrix.execution_order[-1]` when non-empty (canonical source per
    source.md L488). Falls back to `sorted(matrix.modules.keys())[-1]` with a
    warning about fragility against `module-6a` style suffixes (the regex-based
    `_sort_module_key` is used to make the fallback stable).
    """
    if matrix.execution_order:
        return matrix.execution_order[-1]
    if not matrix.modules:
        return None
    logger.warning(
        "[dcp-queue] matrix.execution_order vazio; usando sorted(modules.keys())[-1] "
        "como fallback (fragil com sufixos module-6a)."
    )
    return sorted(matrix.modules.keys(), key=_sort_module_key)[-1]


def enumerate_modules_on_disk(wbs_root: Optional[Path]) -> list[str]:
    """List module dirnames under ``wbs_root/modules/``, filtered and ordered.

    Single source of truth for "which modules exist" when the caller needs the
    real filesystem state rather than ``delivery.json``/matrix bookkeeping
    (e.g. the workflow-app "Build+Exec de todos os modules" queue button).
    Mirrors the real-files-over-baked-count discipline already used by
    ``task_enum.enumerate_module_tasks`` for TASK-*.md.

    Rules:
        - Only entries matching ``^module-\\d+[a-z]?-`` are considered (same
          pattern as ``_sort_module_key``); everything else (``_shared``,
          ``.DS_Store``, stray files) is skipped with a debug log, never a
          crash (Zero Silencio: the skip is logged, not swallowed silently).
        - Non-directories are skipped.
        - Symlinks are followed only when they resolve to a path INSIDE
          ``wbs_root`` (path-safety / R5 from source.md "Riscos previsiveis").
          A symlink resolving outside `wbs_root`, or a broken symlink, is
          skipped with a WARN.
        - Result is sorted via ``_sort_module_key`` (numeric, `module-6a`
          suffix-tolerant).

    Returns:
        ``[]`` when ``wbs_root`` is ``None`` or ``wbs_root/modules/`` does not
        exist (never raises for the "no modules yet" case).
    """
    if wbs_root is None:
        return []
    modules_dir = Path(wbs_root) / "modules"
    if not modules_dir.is_dir():
        return []

    try:
        wbs_root_resolved = Path(wbs_root).resolve()
    except OSError:  # pragma: no cover - defensive, unresolvable wbs_root
        wbs_root_resolved = Path(wbs_root)

    found: list[str] = []
    for entry in modules_dir.iterdir():
        name = entry.name
        if not _MODULE_KEY_RE.match(name):
            logger.debug(
                "[dcp-queue] enumerate_modules_on_disk: ignorando entrada fora "
                "do padrao module-N[letra]-slug: %s", name,
            )
            continue

        if entry.is_symlink():
            try:
                resolved = entry.resolve(strict=True)
            except OSError:
                logger.warning(
                    "[dcp-queue] enumerate_modules_on_disk: symlink quebrado "
                    "ignorado: %s", name,
                )
                continue
            try:
                resolved.relative_to(wbs_root_resolved)
            except ValueError:
                logger.warning(
                    "[dcp-queue] enumerate_modules_on_disk: symlink %s aponta "
                    "para fora do wbs_root (%s); ignorado (path-safety R5).",
                    name, resolved,
                )
                continue
            if not resolved.is_dir():
                logger.debug(
                    "[dcp-queue] enumerate_modules_on_disk: symlink %s nao "
                    "resolve para diretorio; ignorado.", name,
                )
                continue
        elif not entry.is_dir():
            logger.debug(
                "[dcp-queue] enumerate_modules_on_disk: entrada nao-diretorio "
                "ignorada: %s", name,
            )
            continue

        found.append(name)

    found.sort(key=_sort_module_key)
    return found


# ─── template rendering (mirror of _lib/specific_flow/templating.py) ────── #
#
# The widget cannot import from `.claude/commands/_lib/...` directly (not on
# the workflow-app Python path). To avoid coupling the two trees we inline a
# minimal renderer with the same placeholder semantics. Any drift between the
# two renderers is a BUG; the offline generator path (templating.py) remains
# the canonical reference for placeholder names.


def _module_number(module_id: str) -> str:
    m = re.search(r"module-(\d+[a-z]?)-", module_id or "")
    return m.group(1) if m else "N"


def _module_path(module_id: str, wbs_root: Optional[Path]) -> str:
    if wbs_root:
        return f"{wbs_root}/modules/{module_id}"
    return f"modules/{module_id}"


def _resolve_task_substitution(task: Optional[str], module_path: str) -> str:
    if not task:
        return ""
    if "/" in task or task.startswith("/"):
        return task
    return f"{module_path}/{task}"


def _relative_project_json(config_path: Optional[str]) -> str:
    """Render `config_path` relative to the repo root (walk-up to CLAUDE.md).

    Mirrors `templating._relative_project_json` so the FASE H rendering on the
    workflow-app side matches the offline generator path.
    """
    if not config_path:
        return ""
    p = Path(config_path)
    for parent in p.parents:
        if (parent / "CLAUDE.md").exists():
            try:
                return str(p.relative_to(parent))
            except ValueError:
                break
    return str(p)


def _render(
    template: str,
    *,
    task: Optional[str],
    stack: Optional[str],
    module_id: str,
    wbs_root: Optional[Path],
    commit_variant: str = "simple",
    config_path: Optional[str] = None,
) -> str:
    """Render a CommandIndexEntry.name template into the final command line."""
    if stack and "/{stack}:{stack}-review" in template:
        review_cmd = _STACK_REVIEW_CMD.get(stack)
        if review_cmd is None:
            raise ValueError(
                f"stack '{stack}' nao tem review command mapeado em _STACK_REVIEW_CMD"
            )
        template = template.replace("/{stack}:{stack}-review", review_cmd)

    module_path = _module_path(module_id, wbs_root)
    module_n = _module_number(module_id)

    # FASE H {github_check_flag} + {commit_target} — mirrored from templating.py.
    # See profiles.py H-commit StepSpec for the rule rationale.
    project_json_rel = _relative_project_json(config_path)
    if commit_variant == "simple" and module_n in {"0", "1"}:
        github_check_flag = " --github-check"
    else:
        github_check_flag = ""
    commit_target = project_json_rel if project_json_rel else f"--module {module_n}"

    substitutions = {
        "{task}": _resolve_task_substitution(task, module_path),
        "{stack}": stack or "",
        "{module_id}": module_id,
        "{module_n}": module_n,
        "{module_path}": module_path,
        "{commit_variant}": commit_variant,
        "{github_check_flag}": github_check_flag,
        "{commit_target}": commit_target,
        # Mirror templating.py:174 — {project_json} renders to the repo-relative
        # project config path (NO `--module` fallback). Used by the /goal:review
        # I-human entry. Omitting it let a literal `{project_json}` leak into the
        # derived command (renderer drift vs the canonical offline generator).
        "{project_json}": project_json_rel,
    }
    rendered = template
    for key, value in substitutions.items():
        rendered = rendered.replace(key, value)
    rendered = re.sub(r"\s+", " ", rendered).strip()
    # Drift guard (Zero Silencio): every canonical placeholder MUST be
    # substituted above. A leftover `{token}` means this renderer drifted from
    # the canonical placeholder vocabulary (_dcp_canonical.PLACEHOLDER_PATTERNS /
    # templating.py) — fail loud instead of emitting an unrunnable command that
    # carries a literal placeholder.
    leftover = _UNRESOLVED_PLACEHOLDER_RE.search(rendered)
    if leftover:
        raise ValueError(
            f"placeholder nao resolvido {leftover.group(0)!r} apos render do "
            f"template {template!r} (renderer drift vs templating.py)"
        )
    return rendered


# ─── model/effort/interaction mapping ───────────────────────────────────── #


_MODEL_MAP: dict[str, ModelName] = {
    "opus": ModelName.OPUS,
    "sonnet": ModelName.SONNET,
}

_EFFORT_MAP: dict[str, EffortLevel] = {
    "low": EffortLevel.LOW,
    "medium": EffortLevel.STANDARD,
    "high": EffortLevel.HIGH,
    "max": EffortLevel.MAX,
}

_INTERACTION_MAP: dict[str, InteractionType] = {
    # Matrix model's `InteractionLiteral` is "interactive" | "headless"
    # (models/dcp_command_matrix.py:66). The widget's `InteractionType` enum
    # is "auto" | "inter". Headless = runs without prompting -> AUTO.
    "headless": InteractionType.AUTO,
    "auto": InteractionType.AUTO,
    "manual": InteractionType.INTERACTIVE,
    "interactive": InteractionType.INTERACTIVE,
    "inter": InteractionType.INTERACTIVE,
}


def _to_command_spec(
    rendered_name: str,
    *,
    model: str,
    effort: str,
    interaction: str,
    phase: str,
    position: int,
    config_path: str = "",
) -> CommandSpec:
    return CommandSpec(
        name=rendered_name,
        model=_MODEL_MAP.get(model, ModelName.SONNET),
        effort=_EFFORT_MAP.get(effort, EffortLevel.STANDARD),
        interaction_type=_INTERACTION_MAP.get(interaction, InteractionType.AUTO),
        phase=phase,
        position=position,
        config_path=config_path,
    )


# ─── load + derive ──────────────────────────────────────────────────────── #


def load_matrix(dcp_root: Path) -> DcpCommandMatrix:
    """Read DCP-COMMAND-MATRIX.json under `dcp_root` and validate via Pydantic.

    Raises:
        FileNotFoundError when the file is absent.
        ValidationError when the file violates the Pydantic schema.
        ValueError when JSON cannot be parsed.
    """
    matrix_path = dcp_root / "DCP-COMMAND-MATRIX.json"
    if not matrix_path.exists():
        raise FileNotFoundError(f"DCP-COMMAND-MATRIX.json ausente em {matrix_path}")
    try:
        data = json.loads(matrix_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"DCP-COMMAND-MATRIX.json invalido em {matrix_path}: {exc}") from exc
    return DcpCommandMatrix.model_validate(data)


def derive_queue_from_matrix(
    matrix: DcpCommandMatrix,
    cm_id: str,
    *,
    wbs_root: Optional[Path] = None,
    config_path: str = "",
    commit_variant: str = "simple",
    stack: Optional[str] = None,
    include_directives: bool = False,
    meta: Optional[dict] = None,
    project: Optional[dict] = None,
) -> list[CommandSpec]:
    """Build the queue for `cm_id` per source.md st-05 algorithm 9-17.

    Args:
        matrix: validated `DcpCommandMatrix`.
        cm_id: target module id (must exist in `matrix.modules`).
        wbs_root: absolute path to `wbs_root` used to render `{module_path}`.
        config_path: project config path forwarded to each `CommandSpec`.
        commit_variant: value substituted for `{commit_variant}` placeholder.
        stack: optional stack short name for `{stack}` substitution / review
            command swap. When the matrix carries multi-stack reviews the
            caller is expected to expand them per stack separately.
        include_directives: when True, inject render-ready `/clear`, `/model`
            and `/effort` rows as first-class `CommandSpec` entries. Keep
            False for programmatic consumers that need the real-command list.

    Returns:
        Ordered list of `CommandSpec` ready for `signal_bus.pipeline_ready.emit`.

    Raises:
        KeyError when `cm_id` is not in `matrix.modules`.
        IndexError when a phase_buckets index is out of range (guarded by the
            model validator but re-raised defensively).
        ValueError on stack mismatch in review templates.
    """
    if cm_id not in matrix.modules:
        raise KeyError(f"cm_id {cm_id!r} ausente em matrix.modules")

    module: ModuleEntry = matrix.modules[cm_id]
    filter_bits = module.filter
    multiplier = module.loop_multiplier
    overrides_skipped = set(module.overrides_skipped or [])
    n = len(matrix.command_index)
    if len(filter_bits) != n:
        raise ValueError(
            f"matrix.modules[{cm_id!r}].filter tem {len(filter_bits)} bits, "
            f"esperado {n} (==len(command_index))"
        )

    is_last = (cm_id == _last_module_id(matrix))

    # Real task identity comes from the FILESYSTEM (single source of truth —
    # delivery.json does not enumerate tasks). Synthesizing `TASK-{k}.md` from
    # loop_multiplier breaks on TASK-0 starts, gaps, decimal indices, and
    # companion-file over-count (loop 06-08). When a wbs_root is available,
    # enumerate the real executable specs and iterate those; loop_multiplier
    # degrades to a drift cross-check. The synthetic fallback fires ONLY when
    # wbs_root is None (legacy callers/tests).
    real_tasks: Optional[list[str]] = None
    if wbs_root is not None:
        module_dir = Path(wbs_root) / "modules" / cm_id
        if not module_dir.is_dir():
            # Fail-loud (Zero Silencio + Zero Assumido, loop 06-09): wbs_root
            # foi fornecido mas o diretorio do modulo nao resolve. Sintetizar
            # `TASK-{k}.md` a partir do loop_multiplier (possivelmente stale)
            # aqui FABRICA tasks fantasma ("task N nao existe nos modules") e
            # esconde o problema real — drift cm_id <-> nome do diretorio,
            # wbs_root resolvido errado, ou estrutura do modulo ausente. O
            # widget captura esta excecao, emite toast e cai para o caminho
            # transicional SPECIFIC-FLOW.json (validado contra o disco no
            # load), entao a degradacao e visivel e sem fantasmas.
            raise ValueError(
                f"diretorio do modulo nao encontrado: {module_dir} "
                f"(wbs_root={wbs_root}, cm_id={cm_id!r}). Sem os arquivos "
                "TASK-*.md reais nao da para expandir comandos per_task sem "
                "fabricar tasks fantasma. Verifique o wbs_root do projeto e o "
                "nome do diretorio do modulo; regenere via "
                "[DCP: Build Module Pipeline]."
            )
        real_tasks = enumerate_module_tasks(module_dir)
        # Cross-check the baked loop_multiplier against reality (Zero
        # Silencio): a mismatch means the matrix is stale — emit a WARN but
        # trust the real files (covering every task is the safe failure
        # mode; missing a task is the dangerous one). No truthiness guard on
        # `_baked`: a baked 0 with real tasks present (0 -> N) IS drift worth
        # surfacing; foundations-pure (0 == 0) produces no warning naturally.
        for _ph in ("A-creation", "B3-execute"):
            _baked = int(multiplier.get(_ph, 0) or 0)
            if _baked != len(real_tasks):
                logger.warning(
                    "[dcp-queue] modulo %s: loop_multiplier[%s]=%d difere de "
                    "%d TASK-*.md reais; usando os arquivos reais. Rode "
                    "/dcp:matrix-mark-loops para re-sincronizar a matrix.",
                    cm_id, _ph, _baked, len(real_tasks),
                )

    def _per_task_iter(phase: str) -> list[str]:
        """Tasks to expand a per_task entry against, for `phase`.

        Real executable filenames when available (may be empty -> zero per-task
        commands, the correct result for a foundations-pure / companion-only
        module); otherwise the legacy `TASK-{k}.md` count-synthesis driven by
        loop_multiplier (wbs_root None only — dir missing now raises upstream).
        """
        if real_tasks is not None:
            return list(real_tasks)
        iters = max(1, int(multiplier.get(phase, 1)))
        return [f"TASK-{k}.md" for k in range(1, iters + 1)]

    queue: list[CommandSpec] = []
    position = 0

    def emit(entry: CommandIndexEntry, *, task: Optional[str] = None) -> None:
        # D-02: consumer reads `entry.name` only (the producer flip W2 emits it
        # with placeholders preserved); the audit-only field is the audit
        # projection and MUST NOT be referenced here (enforced at type level by
        # CommandIndexRuntimeEntry, which omits it).
        nonlocal position
        # Defense-in-depth: drop when the canonical condition resolves False,
        # even if the cached filter bit is (wrongly) 1. No-op when meta/project
        # absent or engine unavailable (trusts producer filter bits).
        if not _condition_holds(getattr(entry, "condition", None), meta, project):
            logger.debug("[dcp-queue] skip condition-false: %s", entry.name)
            return
        rendered = _render(
            entry.name,
            task=task,
            stack=stack,
            module_id=cm_id,
            wbs_root=wbs_root,
            commit_variant=commit_variant,
            config_path=config_path,
        )
        # Regression guard (loop 05-27): a template that REQUIRES a placeholder
        # ("{" in entry.name) must never collapse to a bare slash token — that
        # means the args were lost. Canonically bare entries (no "{" in name) are
        # exempt: a bare render is correct for them.
        if "{" in (entry.name or "") and _BARE_SLASH_NAME_RE.match(rendered):
            raise ValueError(
                f"template com placeholder {entry.name!r} renderizou bare "
                f"{rendered!r} (args perdidos) no modulo {cm_id}"
            )
        # overrides_skipped works on the rendered command name (source.md L463).
        if rendered in overrides_skipped:
            logger.debug("[dcp-queue] skip overrides_skipped: %s", rendered)
            return
        position += 1
        queue.append(_to_command_spec(
            rendered,
            model=entry.model,
            effort=entry.effort,
            interaction=entry.interaction,
            phase=entry.phase,
            position=position,
            config_path=config_path,
        ))

    # A-creation: dedicated PRE pass that expands per_task entries against the
    # real executable task specs before falling into PHASE_ORDER (source.md
    # L457-460). See `_per_task_iter` for the real-files-vs-synthesis contract.
    creation_bucket = matrix.phase_buckets.get("A-creation", [])
    for idx in creation_bucket:
        if filter_bits[idx] == 0:
            continue
        entry = matrix.command_index[idx]
        if entry.per_task:
            for task in _per_task_iter("A-creation"):
                emit(entry, task=task)
        else:
            emit(entry)

    # B-tdd .. F2-stack-check
    for phase in PHASE_ORDER:
        bucket = matrix.phase_buckets.get(phase, [])
        for idx in bucket:
            if filter_bits[idx] == 0:
                continue
            entry = matrix.command_index[idx]
            if phase in PER_TASK_PHASES and entry.per_task:
                for task in _per_task_iter(phase):
                    emit(entry, task=task)
            else:
                emit(entry)

    # fold_in_rules: H-commit + I-human-signoff ALWAYS; G-deploy + I-human-mkt
    # only on the last module.
    def emit_fold(rules: Iterable[CommandRef], phase_label: str) -> None:
        # D-02: same contract as `emit` for fold-in CommandRefs — read `ref.name`
        # only; the audit-only field (carried by CommandIndexAuditEntry for
        # validator/telemetry parity, TASK-002) is NEVER referenced here
        # (executor contract per TASK-016 / I-NN).
        nonlocal position
        for ref in rules:
            # Defense-in-depth for fold-in refs (CommandRef carries condition).
            if not _condition_holds(getattr(ref, "condition", None), meta, project):
                logger.debug("[dcp-queue] skip fold condition-false: %s", ref.name)
                continue
            rendered = _render(
                ref.name,
                task=None,
                stack=stack,
                module_id=cm_id,
                wbs_root=wbs_root,
                commit_variant=commit_variant,
                config_path=config_path,
            )
            if rendered in overrides_skipped:
                continue
            position += 1
            queue.append(_to_command_spec(
                rendered,
                model=ref.model or "opus",
                effort=ref.effort or "high",
                interaction=ref.interaction or "auto",
                phase=phase_label,
                position=position,
                config_path=config_path,
            ))

    # Opção C (fix 2026-05-30): quando fold_in_rules NÃO FOI INICIALIZADO (todas
    # as 4 listas vazias), auto-derivar de command_index por prefixo de fase.
    # Isso garante que matrix-init sem fold_in_rules populado não trave o
    # pipeline. O mecanismo fold_in_rules (sempre vs only-last) é preservado.
    #
    # IMPORTANTE: o fallback só dispara quando fold_in_rules está completamente
    # uninitializado (todas as 4 arrays vazias). Quando alguma phase está
    # intencionalmente vazia (ex: projeto sem mkt_flow → I_human_mkt=[]), o
    # estado é respeitado sem derivação automática.
    _fold = matrix.fold_in_rules
    _fold_uninitialized = (
        not _fold.H_commit
        and not _fold.I_human_signoff
        and not _fold.G_deploy
        and not _fold.I_human_mkt
    )

    if _fold_uninitialized:
        logger.warning(
            "[dcp-queue] fold_in_rules completamente vazio em matrix — derivando H/I/G "
            "de command_index por prefixo de fase (fix 2026-05-30). "
            "Popule fold_in_rules via /dcp:matrix-init para eliminar este aviso."
        )
        from workflow_app.models.dcp_command_matrix import CommandRef as _CmdRef

        def _derive_fold(phase_prefix: str) -> "list[CommandRef]":
            return [
                _CmdRef(
                    name=entry.name,
                    phase=entry.phase,  # type: ignore[arg-type]
                    model=entry.model or None,
                    effort=entry.effort or None,
                    interaction=entry.interaction or None,
                    condition=entry.condition or None,
                    mandatory=getattr(entry, "mandatory", False),
                    source_ref=getattr(entry, "source_ref", None),
                )
                for entry in matrix.command_index
                if getattr(entry, "phase", "").startswith(phase_prefix)
            ]

        h_commit_rules: "list[CommandRef]" = _derive_fold("H-commit")
        i_signoff_rules: "list[CommandRef]" = _derive_fold("I-human-signoff")
        g_deploy_rules: "list[CommandRef]" = _derive_fold("G-deploy")
        i_mkt_rules: "list[CommandRef]" = _derive_fold("I-human-mkt")
    else:
        h_commit_rules = list(_fold.H_commit)
        i_signoff_rules = list(_fold.I_human_signoff)
        g_deploy_rules = list(_fold.G_deploy)
        i_mkt_rules = list(_fold.I_human_mkt)

    # Ordem canônica: validação humana → commit (apaga a luz) → sign-off/handoff (fecha a porta).
    # Split de I-human-signoff no primeiro /delivery:sign-off:
    #   pre_signoff  = npm-run, goal, skeleton, sync (validação antes de commitar)
    #   h_commit     = commit                        (apaga a luz — tudo ok, commita)
    #   post_signoff = sign-off, handoff             (fecha a porta)
    split_idx = next(
        (i for i, r in enumerate(i_signoff_rules) if "/delivery:sign-off" in r.name),
        len(i_signoff_rules),
    )
    pre_signoff = i_signoff_rules[:split_idx]
    post_signoff = i_signoff_rules[split_idx:]

    emit_fold(pre_signoff, "I-human-signoff")
    emit_fold(h_commit_rules, "H-commit")
    emit_fold(post_signoff, "I-human-signoff")
    if is_last:
        emit_fold(g_deploy_rules, "G-deploy")
        emit_fold(i_mkt_rules, "I-human-mkt")

    return _inject_clears(queue) if include_directives else queue


def build_load_queue_trail_entry(
    cm_id: str,
    queue_size: int,
    is_last: bool,
    *,
    run_id: Optional[str] = None,
) -> dict[str, Any]:
    """Construct the canonical trail dict for the `load-queue` action.

    Returned as a plain dict so callers can pass it through
    `TrailEntry.model_validate(...)` or append to the matrix module's `trail`
    list before persisting via the standard trail writer.

    The shape matches the generic-action variant of TrailEntry (source.md
    L451-453 and models/dcp_command_matrix.py:122-167): `ts`, `gate`, `run_id`,
    `action`. `cm_id`, `queue_size`, `is_last` ride in `reason` since the
    Pydantic model forbids extra keys.
    """
    return {
        "ts": datetime.now(tz=timezone.utc).isoformat(),
        "gate": "load-queue",
        "run_id": run_id or f"load-queue-{cm_id}",
        "action": "load-queue",
        "reason": f"cm_id={cm_id} count={queue_size} is_last={is_last}",
    }


__all__ = [
    "PHASE_ORDER",
    "PER_TASK_PHASES",
    "canonical_bare_command_names",
    "_next_non_done_module_id",
    "_last_module_id",
    "enumerate_modules_on_disk",
    "load_matrix",
    "derive_queue_from_matrix",
    "build_load_queue_trail_entry",
]
