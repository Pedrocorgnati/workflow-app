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
    5.  For `per_task` entries in `A-creation` / `B3-execute`, expand
        `loop_multiplier[phase]` times against TASK-{k}.md placeholders.
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
from workflow_app.models.dcp_command_matrix import (
    CommandIndexEntry,
    CommandRef,
    DcpCommandMatrix,
    ModuleEntry,
)
from workflow_app.templates.quick_templates import _inject_clears

logger = logging.getLogger(__name__)


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
    """First non-done module key sorted by module number, or None."""
    candidates = [
        mid for mid, mod in delivery.modules.items()
        if getattr(mod, "state", None) != "done"
    ]
    return sorted(candidates, key=_sort_module_key)[0] if candidates else None


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
    }
    rendered = template
    for key, value in substitutions.items():
        rendered = rendered.replace(key, value)
    return re.sub(r"\s+", " ", rendered).strip()


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

    queue: list[CommandSpec] = []
    position = 0

    def emit(entry: CommandIndexEntry, *, task: Optional[str] = None) -> None:
        # D-02: consumer reads `entry.name` only (the producer flip W2 emits it
        # with placeholders preserved); the audit-only field is the audit
        # projection and MUST NOT be referenced here (enforced at type level by
        # CommandIndexRuntimeEntry, which omits it).
        nonlocal position
        rendered = _render(
            entry.name,
            task=task,
            stack=stack,
            module_id=cm_id,
            wbs_root=wbs_root,
            commit_variant=commit_variant,
            config_path=config_path,
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

    # A-creation: dedicated PRE pass that consumes loop_multiplier["A-creation"]
    # for per_task entries before falling into PHASE_ORDER (source.md L457-460).
    creation_bucket = matrix.phase_buckets.get("A-creation", [])
    creation_iters = max(1, int(multiplier.get("A-creation", 1)))
    for idx in creation_bucket:
        if filter_bits[idx] == 0:
            continue
        entry = matrix.command_index[idx]
        if entry.per_task:
            for k in range(1, creation_iters + 1):
                emit(entry, task=f"TASK-{k}.md")
        else:
            emit(entry)

    # B-tdd .. F2-stack-check
    for phase in PHASE_ORDER:
        bucket = matrix.phase_buckets.get(phase, [])
        iters = max(1, int(multiplier.get(phase, 1))) if phase in PER_TASK_PHASES else 1
        for idx in bucket:
            if filter_bits[idx] == 0:
                continue
            entry = matrix.command_index[idx]
            if phase in PER_TASK_PHASES and entry.per_task:
                for k in range(1, iters + 1):
                    emit(entry, task=f"TASK-{k}.md")
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

    emit_fold(matrix.fold_in_rules.H_commit, "H-commit")
    emit_fold(matrix.fold_in_rules.I_human_signoff, "I-human-signoff")
    if is_last:
        emit_fold(matrix.fold_in_rules.G_deploy, "G-deploy")
        emit_fold(matrix.fold_in_rules.I_human_mkt, "I-human-mkt")

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
    "_next_non_done_module_id",
    "_last_module_id",
    "load_matrix",
    "derive_queue_from_matrix",
    "build_load_queue_trail_entry",
]
