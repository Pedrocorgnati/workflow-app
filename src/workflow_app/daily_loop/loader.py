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

import os
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
    queue (`queue-btn-daily-loop`). When present, the user is shown a
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


def _resolve_item_commands(
    daily_loop: dict[str, Any], item_id: str
) -> list[str] | None:
    """Resolve canonical per-item commands declared in `buckets[*].items[*]`.

    Schema aceito em `buckets[*].items[*]`:
      - str  -> legacy; sempre retorna None (caller cai no wrapper).
      - dict -> {"id": "001", "commands": ["/cmd:update --foo", ...]}
        * commands ausente -> retorna [] (fallback explicito).
        * commands == []   -> retorna [] (fallback explicito).
        * commands populada -> retorna list[str] preservada (literal).

    Raises:
        DailyLoopConfigError: se `commands` existe e nao e list, ou se algum
        elemento normalizado for /daily-loop:do (token proibido — o caller
        legacy ja injeta esse wrapper; itens canonicos devem carregar o
        comando-alvo real, nao o wrapper).
    """
    for bucket in daily_loop.get("buckets", []) or []:
        if not isinstance(bucket, dict):
            continue
        for entry in bucket.get("items", []) or []:
            if isinstance(entry, str):
                if entry.strip() == item_id:
                    return None
                continue
            if not isinstance(entry, dict):
                continue
            if str(entry.get("id", "")).strip() != item_id:
                continue
            if "commands" not in entry:
                return []
            cmds = entry.get("commands")
            if cmds is None:
                return []
            if not isinstance(cmds, list):
                raise DailyLoopConfigError(
                    f"item {item_id}: 'commands' deve ser list[str]; "
                    f"recebido {type(cmds).__name__}"
                )
            normalized = [str(c).strip() for c in cmds if str(c).strip()]
            for cmd in normalized:
                if cmd.split(" ", 1)[0] == "/daily-loop:do":
                    raise DailyLoopConfigError(
                        f"item {item_id}: 'commands' nao pode conter "
                        f"/daily-loop:do (token wrapper reservado ao fallback)"
                    )
            return normalized
    return None


def _resolve_item_expanded_commands(
    daily_loop: dict[str, Any], item_id: str
) -> list[str] | None:
    """Resolve `expanded_commands` for cmd-single items from `items_index`.

    Returns the expanded_commands list when ALL conditions hold:
      - items_index[item_id] exists and is a dict
      - items_index[item_id].cmd_complexity == "single"
      - items_index[item_id].expanded_commands is a non-empty list[str]
      - items_index[item_id].commands is empty/missing (per cmd-single contract
        in /loop:check-tasks-and-cmd PASSO 4)

    Returns None otherwise (caller falls back to do_command wrapper).

    Fix arquitetural 2026-05-17 (PIPELINE-PITFALLS Pitfall 7 bug upstream):
    cmd_complexity=single items por contrato gravam commands=[] e populam
    expanded_commands. Sem este resolver, build_daily_loop_specs caia no
    do_command fallback e perdia 16 items silently (caso canonico:
    05-15-05-15-study-flow-upgrade).
    """
    items_index = daily_loop.get("items_index")
    if not isinstance(items_index, dict):
        return None
    entry = items_index.get(item_id)
    if not isinstance(entry, dict):
        return None
    if str(entry.get("cmd_complexity", "")).strip() != "single":
        return None
    cmds = entry.get("commands") or []
    if isinstance(cmds, list) and len([c for c in cmds if str(c).strip()]) > 0:
        return None
    expanded = entry.get("expanded_commands")
    if not isinstance(expanded, list):
        return None
    normalized = [str(c).strip() for c in expanded if str(c).strip()]
    if not normalized:
        return None
    for cmd in normalized:
        if cmd.split(" ", 1)[0] == "/daily-loop:do":
            raise DailyLoopConfigError(
                f"item {item_id}: 'expanded_commands' nao pode conter "
                f"/daily-loop:do (token wrapper reservado ao fallback)"
            )
    return normalized


def _rewrite_bare_relative_md_tokens(
    cmds: list[str],
    loop_root: Path,
    workspace_root: Path,
    item_id: str,
) -> list[str]:
    """Defense-in-depth: rewrite bare-relative .md tokens to workspace-relative.

    Catches the catastrophic bug where /loop:integration emitted item.target
    cru (relative to loop_root) into items[*].commands instead of prefixing
    with relpath(loop_root, workspace_root). The workflow-app queue runs
    commands with cwd == workspace_root; a bare-relative token (`tasks/items/
    task-NNN-*.md`) resolves to a non-existent path and breaks the queue
    silently.

    Strategy per token T ending in `.md`:
      1. T absolute -> keep.
      2. T resolves from workspace_root -> keep.
      3. T resolves from loop_root (bare-relative bug) -> rewrite to
         `relpath(loop_root, workspace_root) + "/" + T` and emit WARN.
      4. Otherwise -> keep (W4b in /loop:workflow-app reports as blocker).

    Fixed in 2026-05-15 after diagnosing the 3 broken _LOOP-CONFIG.json
    files in blacksmith/loop-archives/ (loop-rocksmash-flow,
    study-flow-upgrade, dual-script-finalize-decisoes).
    """
    import sys
    try:
        rel_loop = os.path.relpath(loop_root, workspace_root)
    except ValueError:
        return cmds

    out: list[str] = []
    for cmd in cmds:
        tokens = cmd.split()
        new_tokens: list[str] = []
        rewritten = False
        for tok in tokens:
            if not tok.endswith(".md") or tok.startswith("/") or tok.startswith(rel_loop):
                new_tokens.append(tok)
                continue
            ws_path = workspace_root / tok
            if ws_path.exists():
                new_tokens.append(tok)
                continue
            loop_path = loop_root / tok
            if loop_path.exists():
                fixed = f"{rel_loop}/{tok}"
                print(
                    f"[loader] WARN: item {item_id}: bare-relative path rewritten "
                    f"({tok} -> {fixed}). Run /loop:integration to persist.",
                    file=sys.stderr,
                )
                new_tokens.append(fixed)
                rewritten = True
            else:
                new_tokens.append(tok)
        out.append(" ".join(new_tokens) if rewritten else cmd)
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


def _raise_if_ambiguous(daily_loop: dict[str, Any], item_id: str) -> None:
    """Block expansion when an item is still labelled ``task_type=ambiguous``.

    Items left as ``ambiguous`` after ``/loop:mark-type`` exigem decisao humana
    (escolher entre ``task`` ou ``cmd``) antes de qualquer importacao para a
    fila do workflow-app. Sem o bloqueio explicito, o loader caia silenciosamente
    no wrapper ``/daily-loop:do`` ou despachava ``commands`` materializadas como
    se a classificacao estivesse pronta — ver `_HARDENING-REPORT.md` §3.6.

    Retro-compat preservada:
      - ``daily_loop.task_types`` ausente -> noop.
      - ``task_types`` presente mas sem entry para ``item_id`` -> noop.
      - ``task_types[item_id]`` != ``"ambiguous"`` -> noop.

    Quando dispara, a mensagem informa exatamente o que corrigir (path do
    arquivo, iid e razao registrada em ``items_index[item_id].blocked_reason``).
    """
    task_types = daily_loop.get("task_types")
    if not isinstance(task_types, dict):
        return
    if task_types.get(item_id) != "ambiguous":
        return
    items_index = daily_loop.get("items_index")
    if isinstance(items_index, dict) and isinstance(items_index.get(item_id), dict):
        blocked_reason = items_index[item_id].get(
            "blocked_reason", "sem motivo registrado"
        )
    else:
        blocked_reason = "sem motivo registrado"
    raise DailyLoopConfigError(
        f"item {item_id} esta marcado task_type=ambiguous. "
        f"Resolver manualmente (escolher cmd ou task) em _LOOP-CONFIG.json antes de importar. "
        f"Razao: {blocked_reason}"
    )


def _warn_silent_fallback_if_items_index_populated(
    daily_loop: dict[str, Any], item_id: str, do_command: str
) -> None:
    """Emit a stderr WARN when the loader takes the legacy fallback wrapper
    despite `daily_loop.items_index[iid].commands` being populated.

    The silent fallback trap (see _HARDENING-REPORT.md §3.5) happens when
    `/loop:integration` materialized the per-item commands into
    `items_index`, but `buckets[*].items[*]` was written as a bare string.
    The loader cannot use the materialized commands in that shape, so it
    emits the legacy `/daily-loop:do --slug X --item NNN` wrapper — silently
    discarding the canonical commands. This warn names the bug and points
    at the fix, without raising (retro-compat preserved).
    """
    items_index = daily_loop.get("items_index")
    if not isinstance(items_index, dict):
        return
    entry = items_index.get(item_id)
    if not isinstance(entry, dict):
        return
    cmds = entry.get("commands")
    if not isinstance(cmds, list) or not cmds:
        return

    import sys

    print(
        f"[daily-loop] WARN: item {item_id} caiu no fallback {do_command}, "
        f"mas items_index tem {len(cmds)} commands materializadas. "
        f"Provavel bug: daily_loop.buckets[*].items[*] esta como string. "
        f"Rodar /loop:integration novamente OU promover manualmente para "
        f'dict {{"id":"{item_id}","commands":[...]}}.',
        file=sys.stderr,
    )


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
    workspace_root_path = Path(
        str(raw_config.get("basic_flow", {}).get("workspace_root", "")).strip()
        or loop_root_path
    )
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

        _raise_if_ambiguous(daily_loop, item.item_id)
        canonical_cmds = _resolve_item_commands(daily_loop, item.item_id)
        if canonical_cmds:
            canonical_cmds = _rewrite_bare_relative_md_tokens(
                canonical_cmds,
                loop_root_path,
                workspace_root_path,
                item.item_id,
            )
        if not canonical_cmds:
            # Path 2 (2026-05-17 fix Pitfall 7): cmd_complexity=single items
            # tem commands=[] por contrato e expanded_commands populado.
            expanded_cmds = _resolve_item_expanded_commands(
                daily_loop, item.item_id
            )
            if expanded_cmds:
                canonical_cmds = _rewrite_bare_relative_md_tokens(
                    expanded_cmds,
                    loop_root_path,
                    workspace_root_path,
                    item.item_id,
                )
        if canonical_cmds:
            # Precedencia canonica: items[k].commands OU items_index[k].
            # expanded_commands (cmd-single) populado -> emitir cada entrada
            # literal como CommandSpec proprio (sem wrapper /slug/--item).
            for cmd_str in canonical_cmds:
                specs.append(
                    CommandSpec(
                        name=cmd_str,
                        model=model,
                        interaction_type=InteractionType.AUTO,
                        config_path="",
                        position=0,
                        effort=effort,
                        phase="daily-loop",
                    )
                )
        else:
            # Fallback wrapper (retro-compat /daily-loop): items legacy como
            # string pura OU dict sem `commands` populada caem aqui.
            _warn_silent_fallback_if_items_index_populated(
                daily_loop, item.item_id, do_command
            )
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


# ---------------------------------------------------------------------------
# /loop pipeline (queue-btn-loop) — backtick-aware variant
# ---------------------------------------------------------------------------
#
# The /loop pipeline (created 2026-05-12, family of /loop --task|--cmd|--cmd-single|--both)
# emits PROGRESS.md rows where the `Target` column may contain literal
# `|` characters inside backtick-wrapped inline code (e.g. mode flags like
# `--simple|--deep|--heavy`). The legacy `_ITEM_ROW` regex stops at the
# first `|` regardless of backtick context, making `--deep` look like a
# bucket id and triggering `DailyLoopConfigError: item 001 referencia
# bucket inexistente: '--deep'`.
#
# The functions below are deliberate clones of `parse_progress_items` and
# `build_daily_loop_specs` with a single change: column splitting respects
# backtick-bounded segments. The legacy daily-loop entrypoints are kept
# untouched so existing archives keep working byte-for-byte.


def _split_md_row_backtick_aware(line: str) -> list[str]:
    """Split a markdown table row by `|`, ignoring pipes inside backticks.

    Returns the cells between pipes (without the leading/trailing empty
    cells caused by the row's own `| ... |` framing). Caller must strip
    each cell.
    """
    cells: list[str] = []
    current: list[str] = []
    in_backtick = False
    for ch in line:
        if ch == "`":
            in_backtick = not in_backtick
            current.append(ch)
        elif ch == "|" and not in_backtick:
            cells.append("".join(current))
            current = []
        else:
            current.append(ch)
    cells.append("".join(current))
    return cells


_LOOP_ID_RE = re.compile(r"^[A-Za-z0-9_-]+$")
_LOOP_MARK_RE = re.compile(r"^\[(?P<mark>[ x!])\]$")
_LOOP_BUCKET_RE = re.compile(r"^[A-Za-z0-9_.:-]+$")


def parse_progress_items_loop(progress_md_text: str) -> list[ProgressItem]:
    """Backtick-aware variant of `parse_progress_items` for the /loop pipeline.

    Accepts the same PROGRESS.md schema as daily-loop (columns: ID, Status,
    Target, Bucket [, ...]) but the Target cell may contain literal `|`
    inside backtick-wrapped inline code without breaking the parser.

    A line is treated as an item row iff:
      - it starts with `|`,
      - splits into >=5 cells (counting leading/trailing empties),
      - cell[1] matches the ID regex,
      - cell[2] matches `[x]`, `[ ]`, or `[!]`,
      - cell[4] matches the bucket regex.

    Header rows, separators, and free-form prose are silently skipped.
    """
    items: list[ProgressItem] = []
    for line in progress_md_text.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        cells = _split_md_row_backtick_aware(line)
        # `| a | b | c |` splits into ['', ' a ', ' b ', ' c ', ''] = 5 cells
        if len(cells) < 5:
            continue
        id_raw = cells[1].strip()
        mark_raw = cells[2].strip()
        target_raw = cells[3].strip()
        bucket_raw = cells[4].strip()

        if not _LOOP_ID_RE.match(id_raw):
            continue
        mark_m = _LOOP_MARK_RE.match(mark_raw)
        if mark_m is None:
            continue
        if not _LOOP_BUCKET_RE.match(bucket_raw):
            continue

        mark = mark_m.group("mark")
        if mark == "x":
            status = "done"
        elif mark == "!":
            status = "failed"
        else:
            status = "pending"
        items.append(
            ProgressItem(
                item_id=id_raw,
                status=status,
                target=target_raw,
                bucket_id=bucket_raw,
            )
        )
    return items


def build_loop_specs(
    raw_config: dict[str, Any],
    loop_root: Path | str,
) -> list[CommandSpec]:
    """Expand a `/loop`-flavoured `_LOOP-CONFIG.json` + PROGRESS.md into a queue.

    Behaviour mirrors `build_daily_loop_specs` exactly, except PROGRESS.md is
    parsed by `parse_progress_items_loop` (backtick-aware). Use this entrypoint
    for the new `/loop` family (`queue-btn-loop`); keep
    `build_daily_loop_specs` for legacy `queue-btn-daily-loop`.

    Args:
        raw_config: parsed `_LOOP-CONFIG.json` (root dict; same V3 + kind:
            daily-loop schema as the legacy daily-loop pipeline).
        loop_root:  resolved filesystem path of
            `blacksmith/loop-archives/{slug}/`.

    Returns:
        list[CommandSpec] ready for `signal_bus.pipeline_ready.emit(...)`.
        Empty list if no pending items.

    Raises:
        DailyLoopConfigError: missing `daily_loop` block, missing
        PROGRESS.md, invalid bucket_id reference, or unknown model/effort
        value.
    """
    daily_loop = raw_config.get("daily_loop")
    if not isinstance(daily_loop, dict):
        raise DailyLoopConfigError(
            "_LOOP-CONFIG.json sem bloco 'daily_loop' — gere via /loop ou /daily-loop:enumerate"
        )

    slug = str(daily_loop.get("slug", "")).strip()
    if not slug:
        raise DailyLoopConfigError("daily_loop.slug ausente")

    bucket_index = _resolve_bucket_index(daily_loop)

    loop_root_path = Path(loop_root)
    workspace_root_path = Path(
        str(raw_config.get("basic_flow", {}).get("workspace_root", "")).strip()
        or loop_root_path
    )
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
            "  acao: rode /loop ou /daily-loop:enumerate para regerar OU corrija "
            "progress_path no JSON (filename-only relativo a loop_root, ou path absoluto)."
        )

    items = parse_progress_items_loop(progress_path.read_text(encoding="utf-8"))
    pending = [it for it in items if it.status == "pending"]

    if not pending:
        return []

    do_command = str(daily_loop.get("do_command", "/daily-loop:do")).strip() or "/daily-loop:do"
    review_done_command = str(
        daily_loop.get("review_done_command", "/daily-loop:review-done")
    ).strip() or "/daily-loop:review-done"
    clear_between_items = bool(daily_loop.get("clear_between_items", False))
    _REVIEW_DONE_MODEL: ModelName = ModelName.OPUS
    _REVIEW_DONE_EFFORT: EffortLevel = EffortLevel.STANDARD

    specs: list[CommandSpec] = []

    specs.append(
        CommandSpec(
            name="/clear",
            model=ModelName.SONNET,
            interaction_type=InteractionType.AUTO,
            config_path="",
            position=0,
        )
    )

    current_model: ModelName | None = None
    current_effort: EffortLevel | None = None

    for idx, item in enumerate(pending):
        if clear_between_items and idx > 0:
            specs.append(
                CommandSpec(
                    name="/clear",
                    model=ModelName.SONNET,
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

        _raise_if_ambiguous(daily_loop, item.item_id)
        canonical_cmds = _resolve_item_commands(daily_loop, item.item_id)
        if canonical_cmds:
            canonical_cmds = _rewrite_bare_relative_md_tokens(
                canonical_cmds,
                loop_root_path,
                workspace_root_path,
                item.item_id,
            )
        if not canonical_cmds:
            # Path 2 (2026-05-17 fix Pitfall 7): cmd_complexity=single items
            # tem commands=[] por contrato e expanded_commands populado.
            expanded_cmds = _resolve_item_expanded_commands(
                daily_loop, item.item_id
            )
            if expanded_cmds:
                canonical_cmds = _rewrite_bare_relative_md_tokens(
                    expanded_cmds,
                    loop_root_path,
                    workspace_root_path,
                    item.item_id,
                )
        if canonical_cmds:
            # Precedencia canonica /loop --task|--cmd|--cmd-single|--both:
            # items[k].commands OU items_index[k].expanded_commands (cmd-single)
            # populada -> emitir cada entrada literal como CommandSpec.
            for cmd_str in canonical_cmds:
                specs.append(
                    CommandSpec(
                        name=cmd_str,
                        model=model,
                        interaction_type=InteractionType.AUTO,
                        config_path="",
                        position=0,
                        effort=effort,
                        phase="loop",
                    )
                )
        else:
            # Fallback wrapper para items legacy ou sem commands materializada.
            _warn_silent_fallback_if_items_index_populated(
                daily_loop, item.item_id, do_command
            )
            specs.append(
                CommandSpec(
                    name=f"{do_command} --slug {slug} --item {item.item_id}",
                    model=model,
                    interaction_type=InteractionType.AUTO,
                    config_path="",
                    position=0,
                    effort=effort,
                    phase="loop",
                )
            )

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
                phase="loop",
            )
        )

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
            phase="loop",
        )
    )

    for i, spec in enumerate(specs, start=1):
        spec.position = i

    return specs
