"""Pure helpers to expand a daily-loop _LOOP-CONFIG.json + PROGRESS.md into specs.

Public surface:
    - build_daily_loop_specs(raw_config, loop_root) -> list[CommandSpec]
    - parse_progress_items(progress_md_text) -> list[ProgressItem]
    - resolve_loop_path(value, loop_root, label) -> Path
    - DailyLoopConfigError

Path contract (v1.1 — strict, no heuristics):
    All path fields inside `daily_loop` (progress_path, tasks_dir, log_path)
    follow ONE rule:

      * Absolute path -> used as-is.
      * Relative path -> resolved as `loop_root / value`. Always.

    The previous version applied a "is it just a filename?" heuristic that
    silently used `loop_root.parent / value` for multi-segment relative paths,
    producing path duplication when a generator wrote the full
    `blacksmith/loop-archives/{slug}/PROGRESS.md` form. That heuristic is removed.

    `/daily-loop:enumerate` (v1.1+) writes filename-only relatives or absolutes.
    Legacy configs with multi-segment relatives now resolve under loop_root.

Design:
    - The handler in command_queue_widget reads _LOOP-CONFIG.json via the
      project pill (basic_flow paths point inside blacksmith/loop-archives/{slug}/),
      and dispatches here for spec generation.
    - We deduplicate consecutive `/model X` and `/effort Y` headers — only
      emit a row when the value changes from the previous spec.
    - One `/clear` is emitted at position 0 to reset context for the loop.
    - Failed items ([!]) are NOT re-queued — only `[ ]` (pending) are picked up.
    - Optional `daily_loop.clear_between_items: true` injects a `/clear` between
      consecutive items (after each `:review-done`, before the next `:do`). The
      `/clear` is omitted before the first item (already at position 0) and
      before the final `:review` (already emits its own). When enabled, the
      next item's `/model` and `/effort` are force-re-emitted (current state is
      reset to None) so the queue does not depend on the harness preserving
      those flags across `/clear`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from workflow_app.domain import (
    CommandSpec,
    EffortLevel,
    InteractionType,
    ModelName,
)


class DailyLoopConfigError(ValueError):
    """Raised when _LOOP-CONFIG.json or PROGRESS.md is malformed."""


@dataclass(frozen=True)
class ReviewBlockedSentinel:
    """Marker file dropped by /daily-loop:review-created when the FASE 4 audit
    exhausts its 3-round self-healing loop with blockers remaining.

    The workflow-app reads `{loop_root}/.review-blocked` before expanding the
    queue (`queue-btn-execute-daily-loop`). When present, the user is shown a
    confirmation modal summarising the blockers and must explicitly accept to
    proceed.

    A sentinel without a parseable summary is still treated as "present" — UX
    must surface that the audit was reproved even if details are missing.
    """

    path: Path
    raw: str
    summary: str         # short blurb for the modal title
    blocker_count: int   # extracted from the sentinel body when possible


def read_review_blocked_sentinel(loop_root: Path | str) -> ReviewBlockedSentinel | None:
    """Return the `.review-blocked` sentinel if present in loop_root, else None.

    Pure helper — no Qt, no UI. Designed for unit-testing the sentinel contract
    independently of the workflow-app dialog code.

    Sentinel layout (written by /daily-loop:review-created FASE 6):
        # Daily Loop — Review BLOQUEADO
        Slug: {slug}
        Data: {ISO 8601}
        Rodadas exauridas: 3/3
        Blockers remanescentes: {N}
        ...

    The function is tolerant: a malformed sentinel still returns a
    ReviewBlockedSentinel (with summary="" and blocker_count=0). Absence of the
    file (the common case) returns None — that path is hot.
    """
    sentinel_path = Path(loop_root) / ".review-blocked"
    if not sentinel_path.is_file():
        return None
    try:
        raw = sentinel_path.read_text(encoding="utf-8")
    except OSError:
        return ReviewBlockedSentinel(
            path=sentinel_path, raw="", summary="", blocker_count=0
        )

    summary = ""
    blocker_count = 0
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("Blockers remanescentes:"):
            tail = stripped.split(":", 1)[1].strip()
            try:
                blocker_count = int(tail)
            except ValueError:
                blocker_count = 0
        elif stripped.startswith("Slug:") and not summary:
            summary = stripped
    return ReviewBlockedSentinel(
        path=sentinel_path, raw=raw, summary=summary, blocker_count=blocker_count
    )


@dataclass(frozen=True)
class ProgressItem:
    """One item line from PROGRESS.md — what /daily-loop:do consumes."""

    item_id: str          # "001"
    status: str           # "pending" | "done" | "failed"
    target: str           # path or identifier
    bucket_id: str        # "T-sonnet-medium" (haiku/low rejeitados — ver _bucket_to_model_effort)


_MODEL_MAP: dict[str, ModelName] = {
    "opus": ModelName.OPUS,
    "sonnet": ModelName.SONNET,
    "haiku": ModelName.HAIKU,
}

_EFFORT_MAP: dict[str, EffortLevel] = {
    "low": EffortLevel.LOW,
    "medium": EffortLevel.STANDARD,
    "standard": EffortLevel.STANDARD,
    "high": EffortLevel.HIGH,
    "max": EffortLevel.MAX,
}

# Match a PROGRESS.md item row, e.g.
#   | 001 | [ ] | path/to/file.md | T-sonnet-medium | - |
_ITEM_ROW = re.compile(
    r"^\s*\|\s*"
    r"(?P<id>[A-Za-z0-9_-]+)\s*\|\s*"
    r"\[(?P<mark>[ x!])\]\s*\|\s*"
    r"(?P<target>[^|]+?)\s*\|\s*"
    r"(?P<bucket>[A-Za-z0-9_.:-]+)\s*\|"
)


def resolve_loop_path(
    value: Any,
    loop_root: Path,
    *,
    label: str,
    default: str | None = None,
) -> Path:
    """Resolve a path field from _LOOP-CONFIG.json under the strict v1.1 contract.

    Rules:
      - value absent or empty -> use `default` joined to loop_root (or raise if no default).
      - value is absolute Path string -> used as-is.
      - value is relative Path string -> resolved as `loop_root / value`. No
        heuristic. Multi-segment relatives are NOT redirected to loop_root.parent.

    Args:
        value: raw value from the config (may be any type — coerced safely).
        loop_root: absolute Path of the loop root (dir containing _LOOP-CONFIG.json).
        label: field name for error messages (e.g. "progress_path").
        default: fallback relative path if value is missing/empty.

    Raises:
        DailyLoopConfigError: when value is missing AND no default provided, or
        when value is a non-string non-empty type that cannot be coerced.
    """
    if value is None or (isinstance(value, str) and not value.strip()):
        if default is None:
            raise DailyLoopConfigError(
                f"daily_loop.{label} ausente e sem default — corrija o _LOOP-CONFIG.json"
            )
        candidate = default
    elif isinstance(value, str):
        candidate = value.strip()
    else:
        raise DailyLoopConfigError(
            f"daily_loop.{label} deve ser string (recebeu {type(value).__name__}: {value!r})"
        )
    p = Path(candidate)
    if p.is_absolute():
        return p
    return (loop_root / p).resolve()


def parse_progress_items(progress_md_text: str) -> list[ProgressItem]:
    """Extract item rows from a PROGRESS.md.

    Tolerates extra columns (e.g. `Updated`) — only the first 4 are required.
    Skips any non-matching lines (header rows, separators, free-form notes).
    """
    items: list[ProgressItem] = []
    for line in progress_md_text.splitlines():
        m = _ITEM_ROW.match(line)
        if not m:
            continue
        mark = m.group("mark")
        if mark == "x":
            status = "done"
        elif mark == "!":
            status = "failed"
        else:
            status = "pending"
        items.append(
            ProgressItem(
                item_id=m.group("id"),
                status=status,
                target=m.group("target").strip(),
                bucket_id=m.group("bucket").strip(),
            )
        )
    return items


def _resolve_bucket_index(daily_loop: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Build {bucket_id: bucket_dict} for fast lookup."""
    buckets = daily_loop.get("buckets") or []
    if not isinstance(buckets, list) or not buckets:
        raise DailyLoopConfigError("daily_loop.buckets ausente ou vazio")
    out: dict[str, dict[str, Any]] = {}
    for b in buckets:
        if not isinstance(b, dict):
            continue
        bid = str(b.get("id", "")).strip()
        if not bid:
            continue
        out[bid] = b
    if not out:
        raise DailyLoopConfigError("nenhum bucket valido em daily_loop.buckets")
    return out


# /daily-loop:do tem piso obrigatorio de modelo/effort. Persona forte protege
# contra: PROGRESS.md corrompido, criterio de aceite aprovado erroneamente,
# falhas silenciadas. haiku/low produziu regressoes no historico — coercoes
# silenciosas para o piso impedem o /daily-loop:plan (ou config legado) de
# passar valores fracos ao terminal.
_DAILY_LOOP_FLOOR_MODEL: ModelName = ModelName.SONNET
_DAILY_LOOP_FLOOR_EFFORT: EffortLevel = EffortLevel.STANDARD
_FORBIDDEN_MODELS: frozenset[ModelName] = frozenset({ModelName.HAIKU})
_FORBIDDEN_EFFORTS: frozenset[EffortLevel] = frozenset({EffortLevel.LOW})


def _bucket_to_model_effort(b: dict[str, Any]) -> tuple[ModelName, EffortLevel]:
    model_key = str(b.get("model", "sonnet")).lower()
    effort_key = str(b.get("effort", "medium")).lower()
    model = _MODEL_MAP.get(model_key)
    effort = _EFFORT_MAP.get(effort_key)
    if model is None:
        raise DailyLoopConfigError(
            f"bucket {b.get('id')!r} model invalido: {model_key!r}"
        )
    if effort is None:
        raise DailyLoopConfigError(
            f"bucket {b.get('id')!r} effort invalido: {effort_key!r}"
        )
    # Floor coercion — reject forbidden combos rather than silently accept.
    # Configs legados (gerados antes da regra v1.2 do plan/enumerate) sao
    # promovidos sem perguntar; mensagem visivel via stderr para auditoria.
    if model in _FORBIDDEN_MODELS:
        import sys
        print(
            f"[daily-loop] WARN: bucket {b.get('id')!r} model={model_key!r} "
            f"violates floor (haiku banned) -> coerced to {_DAILY_LOOP_FLOOR_MODEL.value}",
            file=sys.stderr,
        )
        model = _DAILY_LOOP_FLOOR_MODEL
    if effort in _FORBIDDEN_EFFORTS:
        import sys
        print(
            f"[daily-loop] WARN: bucket {b.get('id')!r} effort={effort_key!r} "
            f"violates floor (low banned) -> coerced to {_DAILY_LOOP_FLOOR_EFFORT.value}",
            file=sys.stderr,
        )
        effort = _DAILY_LOOP_FLOOR_EFFORT
    return model, effort


def build_daily_loop_specs(
    raw_config: dict[str, Any],
    loop_root: Path | str,
) -> list[CommandSpec]:
    """Expand the daily_loop block + PROGRESS.md into a CommandSpec queue.

    Args:
        raw_config: parsed _LOOP-CONFIG.json (root dict).
        loop_root:  resolved filesystem path of blacksmith/loop-archives/{slug}/.

    Returns:
        list[CommandSpec] ready for `signal_bus.pipeline_ready.emit(...)`.
        Empty list if no pending items.

    Raises:
        DailyLoopConfigError: missing `daily_loop` block, missing PROGRESS.md,
        invalid bucket_id reference, or unknown model/effort value.
    """
    daily_loop = raw_config.get("daily_loop")
    if not isinstance(daily_loop, dict):
        raise DailyLoopConfigError(
            "_LOOP-CONFIG.json sem bloco 'daily_loop' — gere via /daily-loop:enumerate"
        )

    slug = str(daily_loop.get("slug", "")).strip()
    if not slug:
        raise DailyLoopConfigError("daily_loop.slug ausente")

    bucket_index = _resolve_bucket_index(daily_loop)

    loop_root_path = Path(loop_root)
    progress_path = resolve_loop_path(
        daily_loop.get("progress_path"),
        loop_root_path,
        label="progress_path",
        default="PROGRESS.md",
    )

    if not progress_path.exists():
        raise DailyLoopConfigError(
            "PROGRESS.md nao encontrado.\n"
            f"  declarado em _LOOP-CONFIG.json:  progress_path = {daily_loop.get('progress_path')!r}\n"
            f"  loop_root resolvido:              {loop_root_path}\n"
            f"  caminho final calculado:          {progress_path}\n"
            "  acao: rode /daily-loop:enumerate para regerar OU corrija progress_path "
            "no JSON (filename-only relativo a loop_root, ou path absoluto)."
        )

    items = parse_progress_items(progress_path.read_text(encoding="utf-8"))
    pending = [it for it in items if it.status == "pending"]

    if not pending:
        return []

    do_command = str(daily_loop.get("do_command", "/daily-loop:do")).strip() or "/daily-loop:do"
    # Per-item adversarial audit injected after each :do. Defaults to
    # /daily-loop:review-done (opus/standard) and runs /skill:double-mcp Level 3
    # CROSS_ADVERSARIAL — see .claude/commands/daily-loop/review-done.md.
    review_done_command = str(
        daily_loop.get("review_done_command", "/daily-loop:review-done")
    ).strip() or "/daily-loop:review-done"
    # Default false preserves the historical contract for legacy configs (single
    # /clear at position 0). New configs always emit "clear_between_items": true
    # via enumerate.md template, so the default only matters for old archives.
    clear_between_items = bool(daily_loop.get("clear_between_items", False))
    # Floor canonico do review-done. Mantido aqui (nao no JSON) para impedir que
    # configs legados degradem o per-item audit para sonnet/medium.
    _REVIEW_DONE_MODEL: ModelName = ModelName.OPUS
    _REVIEW_DONE_EFFORT: EffortLevel = EffortLevel.STANDARD

    specs: list[CommandSpec] = []

    # Position 0: /clear once at the top — context reset before the run.
    # Subsequent /clear is NOT injected per item by default (loop iterations
    # share state only via PROGRESS.md on disk, not via conversation memory of
    # prior items). To opt into a /clear between items (legitimate for long
    # rollouts where each item is independent and accumulated context degrades
    # the model — e.g. KIMI-BOOST KB-01..KB-12), set
    # `daily_loop.clear_between_items: true` in _LOOP-CONFIG.json. The
    # injection happens AFTER each :review-done and BEFORE the next item — never
    # between :do and :review-done (the audit needs the fresh :do context).
    specs.append(
        CommandSpec(
            name="/clear",
            model=ModelName.SONNET,  # placeholder — /clear ignores model
            interaction_type=InteractionType.AUTO,
            config_path="",
            position=0,
        )
    )

    current_model: ModelName | None = None
    current_effort: EffortLevel | None = None

    for idx, item in enumerate(pending):
        # Opt-in: drop a /clear between items (after the prior :review-done,
        # before this :do). Skipped before the first item — position 0 already
        # holds a /clear. After a /clear we cannot rely on the harness keeping
        # /model and /effort state, so reset the dedup trackers to force the
        # next pair of headers to re-emit. Only the bucket headers are forced;
        # the review-done /model opus + /effort standard headers will dedup
        # naturally based on whether the new bucket already matches them.
        if clear_between_items and idx > 0:
            specs.append(
                CommandSpec(
                    name="/clear",
                    model=ModelName.SONNET,  # placeholder — /clear ignores model
                    interaction_type=InteractionType.AUTO,
                    config_path="",
                    position=0,
                )
            )
            current_model = None
            current_effort = None

        bucket = bucket_index.get(item.bucket_id)
        if bucket is None:
            raise DailyLoopConfigError(
                f"item {item.item_id} referencia bucket inexistente: {item.bucket_id!r}"
            )
        model, effort = _bucket_to_model_effort(bucket)

        if model != current_model:
            specs.append(
                CommandSpec(
                    name=f"/model {model.value.lower()}",
                    model=model,
                    interaction_type=InteractionType.AUTO,
                    config_path="",
                    position=0,
                )
            )
            current_model = model

        if effort != current_effort:
            specs.append(
                CommandSpec(
                    name=f"/effort {effort.value.lower()}",
                    model=model,
                    interaction_type=InteractionType.AUTO,
                    config_path="",
                    position=0,
                )
            )
            current_effort = effort

        specs.append(
            CommandSpec(
                name=f"{do_command} --slug {slug} --item {item.item_id}",
                model=model,
                interaction_type=InteractionType.AUTO,
                config_path="",  # do command resolves loop_root via slug
                position=0,
                effort=effort,
                phase="daily-loop",
            )
        )

        # Per-item adversarial audit. Roda IMEDIATAMENTE apos o :do — espelha
        # /review-executed-task. Forca opus/standard via emissao explicita
        # (dedup so emite quando muda). NAO injeta /clear: queremos contexto
        # do :do recente ainda quente para a auditoria.
        if _REVIEW_DONE_MODEL != current_model:
            specs.append(
                CommandSpec(
                    name=f"/model {_REVIEW_DONE_MODEL.value.lower()}",
                    model=_REVIEW_DONE_MODEL,
                    interaction_type=InteractionType.AUTO,
                    config_path="",
                    position=0,
                )
            )
            current_model = _REVIEW_DONE_MODEL
        if _REVIEW_DONE_EFFORT != current_effort:
            specs.append(
                CommandSpec(
                    name=f"/effort {_REVIEW_DONE_EFFORT.value.lower()}",
                    model=_REVIEW_DONE_MODEL,
                    interaction_type=InteractionType.AUTO,
                    config_path="",
                    position=0,
                )
            )
            current_effort = _REVIEW_DONE_EFFORT

        specs.append(
            CommandSpec(
                name=f"{review_done_command} --slug {slug} --item {item.item_id}",
                model=_REVIEW_DONE_MODEL,
                interaction_type=InteractionType.AUTO,
                config_path="",
                position=0,
                effort=_REVIEW_DONE_EFFORT,
                phase="daily-loop",
            )
        )

    # Review final — espelha o padrão do /daily (FASE 5 do daily.md). Roda depois
    # de todos os pares (do, review-done) pendentes. Sempre Opus/HIGH (frontmatter
    # de review.md). Se o user clicar Execute novamente com mais pending, o
    # review é re-anexado: /daily-loop:review é idempotente (apenas re-lê
    # PROGRESS.md + gera _LOOP-REVIEW.md). /model e /effort dedupam contra o
    # último spec emitido — como review-done já deixa o estado em opus/standard,
    # tipicamente só /effort high precisa ser re-emitido aqui (fila enxuta).
    review_command = str(
        daily_loop.get("review_command", "/daily-loop:review")
    ).strip() or "/daily-loop:review"

    specs.append(
        CommandSpec(
            name="/clear",
            model=ModelName.SONNET,
            interaction_type=InteractionType.AUTO,
            config_path="",
            position=0,
        )
    )
    if current_model != ModelName.OPUS:
        specs.append(
            CommandSpec(
                name="/model opus",
                model=ModelName.OPUS,
                interaction_type=InteractionType.AUTO,
                config_path="",
                position=0,
            )
        )
        current_model = ModelName.OPUS
    if current_effort != EffortLevel.HIGH:
        specs.append(
            CommandSpec(
                name="/effort high",
                model=ModelName.OPUS,
                interaction_type=InteractionType.AUTO,
                config_path="",
                position=0,
            )
        )
        current_effort = EffortLevel.HIGH
    specs.append(
        CommandSpec(
            name=f"{review_command} --slug {slug}",
            model=ModelName.OPUS,
            interaction_type=InteractionType.AUTO,
            config_path="",
            position=0,
            effort=EffortLevel.HIGH,
            phase="daily-loop",
        )
    )

    for i, spec in enumerate(specs, start=1):
        spec.position = i

    return specs
