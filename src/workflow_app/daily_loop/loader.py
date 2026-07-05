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
from collections.abc import Iterator
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
    bucket_id: str        # "T-sonnet-medium" (low rejeitado)


_MODEL_MAP: dict[str, ModelName] = {
    "opus": ModelName.OPUS,
    "sonnet": ModelName.SONNET,
}

_EFFORT_MAP: dict[str, EffortLevel] = {
    "low": EffortLevel.LOW,
    "medium": EffortLevel.STANDARD,
    "standard": EffortLevel.STANDARD,
    "high": EffortLevel.HIGH,
    "max": EffortLevel.MAX,
}

_WORKSPACE_DRIFT_ALLOW_PROJECT_OVERRIDE = "allow_project_override"

# Match a PROGRESS.md item row, e.g.
#   | 001 | [ ] | path/to/file.md | T-sonnet-medium | - |
_ITEM_ROW = re.compile(
    r"^\s*\|\s*"
    r"(?P<id>[A-Za-z0-9_-]+)\s*\|\s*"
    r"\[(?P<mark>[ x!])\]\s*\|\s*"
    r"(?P<target>[^|]+?)\s*\|\s*"
    r"(?P<bucket>[A-Za-z0-9_.:-]+)\s*\|"
)


def diagnose_workspace_doubled_path(
    value: Any,
    loop_root: Path,
) -> str | None:
    """Detect the workspace-doubled-path anti-pattern (CONTRACT v1.1 secao 2.2).

    Symptom: a `daily_loop.*` path field carries a workspace-relative value
    (e.g. ``"blacksmith/loop-archives/{slug}/PROGRESS.md"``) while ``loop_root``
    already terminates in ``.../blacksmith/loop-archives/{slug}``. The resolver
    then joins them, producing a doubled path that never exists on disk
    (``.../{slug}/blacksmith/loop-archives/{slug}/PROGRESS.md``).

    Returns:
        Suggested loop_root-relative replacement (e.g. ``"PROGRESS.md"``) when
        the pattern is detected, ``None`` otherwise.

    Notes:
        - Detection key: the basename of ``loop_root`` (the slug) appears as a
          path component inside the candidate value. Slugs are kebab-case and
          typically unique, so collision risk is low.
        - Absolute values are never reported (they bypass the resolver and are
          governed by their own contract).
    """
    if not isinstance(value, str) or not value.strip():
        return None
    p = Path(value.strip())
    if p.is_absolute():
        return None
    slug = loop_root.name
    parts = p.parts
    if slug not in parts:
        return None
    last_idx = len(parts) - 1 - tuple(reversed(parts)).index(slug)
    tail = parts[last_idx + 1:]
    if not tail:
        return None
    return str(Path(*tail))


def assert_loop_root_relative_path(
    value: Any,
    loop_root: Path,
    *,
    label: str,
) -> None:
    """Enforce CONTRACT v1.1 secao 2.2 (Path field convention) on a single field.

    Raises ``DailyLoopConfigError`` when the value is workspace-relative
    (i.e. it embeds the loop_root slug as a path prefix). Intended for
    write-time guards in producers and for review-time validators. Resolver
    code path (``resolve_loop_path``) does NOT call this — the resolver
    remains tolerant; only ``diagnose_*`` is invoked there to enrich error
    messages when resolution fails. This keeps the runtime contract stable
    and the strict gate explicit.
    """
    suggestion = diagnose_workspace_doubled_path(value, loop_root)
    if suggestion is not None:
        raise DailyLoopConfigError(
            f"daily_loop.{label} viola CONTRACT v1.1 secao 2.2 "
            f"(workspace-relative detectado): value={value!r} embute o slug "
            f"{loop_root.name!r} que ja faz parte de loop_root.\n"
            f"  fix: trocar para {suggestion!r} (filename-only relativo a loop_root) "
            "ou path absoluto.\n"
            "  ref: ai-forge/workflow-app/src/workflow_app/daily_loop/CONTRACT.md secao 2.2."
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


def _canonical_path(path: Path) -> Path:
    return path.expanduser().resolve(strict=False)


def _workspace_drift_policy(raw_config: dict[str, Any]) -> str:
    daily_loop = raw_config.get("daily_loop")
    metadata = raw_config.get("metadata")
    candidates: list[Any] = [
        raw_config.get("workspace_drift_policy"),
        metadata.get("workspace_drift_policy") if isinstance(metadata, dict) else None,
        daily_loop.get("workspace_drift_policy") if isinstance(daily_loop, dict) else None,
    ]
    for candidate in candidates:
        value = str(candidate or "").strip()
        if value:
            return value
    return "block"


def resolve_effective_workspace_root(
    raw_config: dict[str, Any],
    loop_root: Path | str,
    *,
    project_workspace_root: Path | str | None = None,
) -> Path:
    """Resolve the workspace used to rewrite loop command tokens.

    Default policy is fail-closed: when the loop declares a workspace root that
    differs from the active project workspace, do not silently switch bases.
    Producers may opt in with `workspace_drift_policy: allow_project_override`.
    Without an active project, preserve legacy behavior: loop workspace when
    declared, otherwise loop_root.
    """
    loop_root_path = _canonical_path(Path(loop_root))
    loop_workspace_raw = ""
    basic_flow = raw_config.get("basic_flow")
    if isinstance(basic_flow, dict):
        loop_workspace_raw = str(basic_flow.get("workspace_root", "") or "").strip()
    loop_workspace = (
        _canonical_path(Path(loop_workspace_raw))
        if loop_workspace_raw
        else loop_root_path
    )

    if project_workspace_root is None or not str(project_workspace_root).strip():
        return loop_workspace

    project_workspace = _canonical_path(Path(project_workspace_root))
    if loop_workspace == project_workspace:
        return loop_workspace

    policy = _workspace_drift_policy(raw_config)
    if policy == _WORKSPACE_DRIFT_ALLOW_PROJECT_OVERRIDE:
        return project_workspace

    raise DailyLoopConfigError(
        "workspace_root divergente entre loop e project; sobrescrita silenciosa "
        "bloqueada.\n"
        f"  loop.basic_flow.workspace_root: {loop_workspace}\n"
        f"  project.workspace_root:         {project_workspace}\n"
        "  politica default: bloquear.\n"
        "  para permitir override explicito, declare "
        "workspace_drift_policy: allow_project_override no _LOOP-CONFIG.json."
    )


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
# falhas silenciadas. low produziu regressoes no historico — coercao
# silenciosa para o piso impede o /daily-loop:plan (ou config legado) de
# passar valores fracos ao terminal.
_DAILY_LOOP_FLOOR_MODEL: ModelName = ModelName.SONNET
_DAILY_LOOP_FLOOR_EFFORT: EffortLevel = EffortLevel.STANDARD
_FORBIDDEN_MODELS: frozenset[ModelName] = frozenset()
_FORBIDDEN_EFFORTS: frozenset[EffortLevel] = frozenset({EffortLevel.LOW})


def _coerce_floor(
    model: ModelName, effort: EffortLevel, label: str
) -> tuple[ModelName, EffortLevel]:
    """Apply the daily-loop model/effort floor to an already-resolved pair.

    Floor coercion — reject forbidden combos rather than silently accept.
    Configs legados (gerados antes da regra v1.2 do plan/enumerate) sao
    promovidos sem perguntar; mensagem visivel via stderr para auditoria.

    `label` identifica a origem do par (bucket id ou item id) na telemetria.
    """
    if model in _FORBIDDEN_MODELS:
        model = _DAILY_LOOP_FLOOR_MODEL
    if effort in _FORBIDDEN_EFFORTS:
        import sys

        print(
            f"[daily-loop] WARN: {label} effort={effort.value!r} "
            f"violates floor (low banned) -> coerced to {_DAILY_LOOP_FLOOR_EFFORT.value}",
            file=sys.stderr,
        )
        effort = _DAILY_LOOP_FLOOR_EFFORT
    return model, effort


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
    return _coerce_floor(model, effort, f"bucket {b.get('id')!r}")


def _resolve_item_model_effort(
    daily_loop: dict[str, Any], item_id: str
) -> tuple[ModelName | None, EffortLevel | None]:
    """Resolve per-item model/effort from the canonical sources.

    Fonte primaria V3: ``items_index[item_id].{model,effort}``.
    Fallback V2: entrada dict correspondente em ``buckets[*].items[*]``.

    Convencao de heranca por run (compressao da FASE /loop:individual-analysis
    PASSO 3): um item sem sizing explicito grava ``model: null``/``effort: null``
    e herda o run ativo. Aqui isso vira ``None`` — o caller (`build_loop_specs`)
    aplica a heranca, NUNCA caindo no default do bucket para itens nulos quando
    existe um run anchor. Itens com sizing explicito vencem o bucket.

    Returns:
        ``(model | None, effort | None)`` com enums mapeados. ``None`` significa
        "herdar o run ativo" (campo ausente ou explicitamente null).

    Raises:
        DailyLoopConfigError: valor presente porem nao mapeavel
        (ex: ``model: "gpt"`` ou ``effort: "ultra"``).
    """

    def _map(raw_model: Any, raw_effort: Any, src: str) -> tuple[
        ModelName | None, EffortLevel | None
    ]:
        model: ModelName | None = None
        effort: EffortLevel | None = None
        if raw_model is not None:
            model = _MODEL_MAP.get(str(raw_model).lower())
            if model is None:
                raise DailyLoopConfigError(
                    f"item {item_id} ({src}) model invalido: {raw_model!r}"
                )
        if raw_effort is not None:
            effort = _EFFORT_MAP.get(str(raw_effort).lower())
            if effort is None:
                raise DailyLoopConfigError(
                    f"item {item_id} ({src}) effort invalido: {raw_effort!r}"
                )
        return model, effort

    items_index = daily_loop.get("items_index")
    if isinstance(items_index, dict):
        entry = items_index.get(item_id)
        if isinstance(entry, dict) and ("model" in entry or "effort" in entry):
            return _map(entry.get("model"), entry.get("effort"), "items_index")

    # Fallback V2: buckets[*].items[*] dict entries.
    for bucket in daily_loop.get("buckets", []) or []:
        if not isinstance(bucket, dict):
            continue
        for entry in bucket.get("items", []) or []:
            if not isinstance(entry, dict):
                continue
            if str(entry.get("id", "")).strip() != item_id:
                continue
            if "model" in entry or "effort" in entry:
                return _map(entry.get("model"), entry.get("effort"), "buckets.items")
            return None, None
    return None, None


def _resolve_run_default_model_effort(
    daily_loop: dict[str, Any],
) -> tuple[ModelName | None, EffortLevel | None]:
    """Seed sizing for the run-anchor inheritance chain.

    Varre `items_index` (ou `buckets[*].items[*]`) em ordem de id e devolve o
    PRIMEIRO par com `model` E `effort` explicitos. Esse par e o "run anchor":
    itens nulos que aparecem ANTES dele (ex: bookend `preparo`) tambem herdam
    esse sizing, em vez de cair no default do bucket — evitando que um item
    no-op rode no modelo caro de um bucket desatualizado (incidente
    05-25-rede-micro-sites: bucket T-opus-high vs anchor sonnet/standard).

    Returns ``(None, None)`` quando nenhum item carrega sizing explicito
    (config legado all-null) — ai o caller usa o bucket como seed.
    """
    item_ids: list[str] = []
    items_index = daily_loop.get("items_index")
    if isinstance(items_index, dict):
        item_ids = sorted(str(k) for k in items_index)
    else:
        seen: set[str] = set()
        for bucket in daily_loop.get("buckets", []) or []:
            if not isinstance(bucket, dict):
                continue
            for entry in bucket.get("items", []) or []:
                iid = (
                    str(entry.get("id", "")).strip()
                    if isinstance(entry, dict)
                    else str(entry).strip()
                )
                if iid and iid not in seen:
                    seen.add(iid)
                    item_ids.append(iid)
    for iid in item_ids:
        model, effort = _resolve_item_model_effort(daily_loop, iid)
        if model is not None and effort is not None:
            return model, effort
    return None, None


def _resolve_effective_sizing(
    daily_loop: dict[str, Any],
    item_id: str,
    bucket: dict[str, Any],
    active_model: ModelName | None,
    active_effort: EffortLevel | None,
) -> tuple[ModelName, EffortLevel, ModelName, EffortLevel]:
    """Resolve o (model, effort) efetivo de um item e avanca o run anchor.

    Precedencia (fix do bug de propagacao de bucket — incidente
    05-25-rede-micro-sites onde o bucket T-opus-high vencia o sizing per-item
    sonnet/standard calculado pela FASE /loop:individual-analysis):

      1. sizing explicito per-item (items_index / buckets.items) VENCE o bucket;
      2. sizing null herda o run ativo (`active_*`);
      3. sem run ativo (item antes do primeiro anchor, config legado) -> bucket.

    Floor coercion (low banido) e aplicada por ultimo. Devolve tambem o novo
    par `active_*` (atualizado quando o item carrega sizing explicito), para o
    caller propagar a heranca ao proximo item.
    """
    bucket_model, bucket_effort = _bucket_to_model_effort(bucket)
    pi_model, pi_effort = _resolve_item_model_effort(daily_loop, item_id)

    if pi_model is not None:
        active_model = pi_model
    model = active_model if active_model is not None else bucket_model

    if pi_effort is not None:
        active_effort = pi_effort
    effort = active_effort if active_effort is not None else bucket_effort

    model, effort = _coerce_floor(model, effort, f"item {item_id!r}")
    return model, effort, active_model, active_effort


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


# Canonical per-iteration command tokens for rocksmash mode (B6 2026-05-19).
# The loader validates that, when raw_config["mode"] == "rocksmash", each
# iteration item's `commands` list contains exactly these four tokens (in
# this order), with any /clear|/model|/effort directives stripped before the
# comparison. Producers (/loop:create-structure, /loop:integration) must
# write this exact 4-tuple per item; auto-upgrade of legacy 2-tuple loops
# (do + review-done only) is covered by /legacy:* + B12 backfill.
_ROCKSMASH_CANONICAL_TOKENS: tuple[str, ...] = (
    "/loop-rocksmash:do",
    "/loop-rocksmash:review-done",
    "/loop-rocksmash:compare",
    "/loop-rocksmash:integrate",
)


def is_rocksmash_mode(raw_config: dict[str, Any]) -> bool:
    """Return True when raw_config declares the canonical rocksmash mode.

    The discriminator lives at top-level ``mode`` in ``_LOOP-CONFIG.json`` and
    is set by ``/loop --rocksmash`` (or by ``/legacy:detect`` when promoting a
    legacy rocksmash loop). All other values (``"normal"``, ``"task"``,
    ``"cmd"``, ``"cmd-single"``, ``"both"``, ``"mkt_assets"``, missing) imply
    non-rocksmash.

    Missing or non-string ``mode`` defaults to non-rocksmash silently
    (retro-compat for V3 loops produced before 2026-05-19, per B6 contract).
    """
    mode = raw_config.get("mode")
    if not isinstance(mode, str):
        return False
    return mode.strip().lower() == "rocksmash"


def _strip_directives(cmds: list[str]) -> list[str]:
    """Remove /clear, /model X, /effort Y directives from a command list."""
    out: list[str] = []
    for c in cmds:
        c = str(c).strip()
        if not c:
            continue
        head = c.split(" ", 1)[0]
        if head in ("/clear", "/model", "/effort"):
            continue
        out.append(c)
    return out


def assert_rocksmash_iteration_shape(
    raw_config: dict[str, Any],
) -> None:
    """Enforce the canonical 4-command per-iteration shape for rocksmash loops.

    Behavior:
      - Noop unless ``is_rocksmash_mode(raw_config)`` returns True.
      - For every item with ``kind == "iteration"`` (or missing kind, treated
        as iteration), strip /clear/model/effort directives and assert the
        remaining tokens are exactly the 4 canonical tokens (matched by their
        first whitespace-separated word, so per-iteration ``--task <path>``
        suffixes are accepted).
      - Items with ``kind in {"preparo", "finalizacao"}`` are skipped.
      - Empty ``commands`` is tolerated only when the loop is pre-integration
        (``metadata.integration_completed_at`` absent); after integration the
        empty list is rejected with a descriptive ``DailyLoopConfigError``.

    Raises:
        DailyLoopConfigError: on any divergence, with the offending item id,
        the observed token sequence and the expected 4-tuple.
    """
    if not is_rocksmash_mode(raw_config):
        return

    daily_loop = raw_config.get("daily_loop")
    if not isinstance(daily_loop, dict):
        return

    metadata = raw_config.get("metadata") or {}
    integration_done = bool(
        isinstance(metadata, dict) and metadata.get("integration_completed_at")
    )

    expected = list(_ROCKSMASH_CANONICAL_TOKENS)
    for bucket in daily_loop.get("buckets", []) or []:
        if not isinstance(bucket, dict):
            continue
        for item in bucket.get("items", []) or []:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind", "iteration")).strip().lower()
            if kind in ("preparo", "finalizacao"):
                continue
            iid = str(item.get("id", "?"))
            cmds = item.get("commands")
            if not isinstance(cmds, list):
                raise DailyLoopConfigError(
                    f"rocksmash item {iid}: 'commands' deve ser list[str] "
                    f"com 4 tokens canonicos (do/review-done/compare/integrate); "
                    f"recebido {type(cmds).__name__}"
                )
            stripped = _strip_directives(cmds)
            if not stripped and not integration_done:
                # Pre-integration placeholder is tolerated.
                continue
            heads = [c.split(" ", 1)[0] for c in stripped]
            if heads != expected:
                raise DailyLoopConfigError(
                    f"rocksmash item {iid}: shape de iteration_template invalido. "
                    f"Esperado 4 tokens canonicos {expected}; "
                    f"recebido {heads}. "
                    f"Re-rodar /loop:integration ou aplicar /legacy:detect."
                )


# Canonical lane namespace for the `/mkt-assets` family (mkt-assets pipeline,
# 2026-06-18). The `/mkt-assets` loop is a twin of `/loop` (preparo ->
# iteration_template -> finalizacao) that reuses this loader/engine, the same
# way `/kimi-loop` does. It distinguishes itself with the top-level
# discriminator ``mode == "mkt_assets"`` and per-iteration commands in the
# ``/mkt-assets:*`` namespace. Unlike rocksmash, mkt_assets keeps the variable
# /loop iteration shape (create-task / review-created-task / execute-task /
# review-executed-task), so there is NO fixed token-count gate — only a
# tolerant lane-containment check (see ``assert_mkt_assets_iteration_shape``)
# that catches the execution_risk "botao aparece mas comando cai no handler
# errado / falha silenciosa".
_MKT_ASSETS_MODE = "mkt_assets"
_MKT_ASSETS_NAMESPACE = "/mkt-assets:"


def is_mkt_assets_mode(raw_config: dict[str, Any]) -> bool:
    """Return True when raw_config declares the canonical mkt-assets lane mode.

    The discriminator lives at top-level ``mode`` in ``_LOOP-CONFIG.json`` and
    is set by ``/mkt-assets`` (preparation pipeline) when materializing the
    family's loop config. All other values (``"normal"``, ``"task"``,
    ``"cmd"``, ``"cmd-single"``, ``"both"``, ``"rocksmash"``, missing) imply
    non-mkt-assets.

    Missing or non-string ``mode`` defaults to non-mkt-assets silently
    (retro-compat for every loop produced before 2026-06-18). The match is
    case-insensitive and tolerant of surrounding whitespace.
    """
    mode = raw_config.get("mode")
    if not isinstance(mode, str):
        return False
    return mode.strip().lower() == _MKT_ASSETS_MODE


def assert_mkt_assets_iteration_shape(
    raw_config: dict[str, Any],
) -> None:
    """Enforce lane containment for mkt-assets loops (discovery gate).

    Behavior:
      - Noop unless ``is_mkt_assets_mode(raw_config)`` returns True.
      - For every item with ``kind == "iteration"`` (or missing kind, treated
        as iteration), strip /clear/model/effort directives and assert every
        remaining per-iteration token belongs to the ``/mkt-assets:`` namespace
        (matched by its first whitespace-separated word). This is what prevents
        a mkt-assets button from dispatching a command that "falls into the
        wrong handler" or fails silently.
      - Items with ``kind in {"preparo", "finalizacao"}`` are skipped: those
        slots legitimately carry cross-lane housekeeping (e.g.
        ``/loop:iteraction:review-executed-loop``).
      - Empty ``commands`` is tolerated only when the loop is pre-integration
        (``metadata.integration_completed_at`` absent); after integration the
        empty list is rejected with a descriptive ``DailyLoopConfigError``.

    Unlike ``assert_rocksmash_iteration_shape`` there is NO fixed token count:
    mkt_assets keeps the variable /loop iteration shape.

    Raises:
        DailyLoopConfigError: on any divergence, with the offending item id and
        the out-of-namespace token sequence.
    """
    if not is_mkt_assets_mode(raw_config):
        return

    daily_loop = raw_config.get("daily_loop")
    if not isinstance(daily_loop, dict):
        return

    metadata = raw_config.get("metadata") or {}
    integration_done = bool(
        isinstance(metadata, dict) and metadata.get("integration_completed_at")
    )

    for bucket in daily_loop.get("buckets", []) or []:
        if not isinstance(bucket, dict):
            continue
        for item in bucket.get("items", []) or []:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind", "iteration")).strip().lower()
            if kind in ("preparo", "finalizacao"):
                continue
            iid = str(item.get("id", "?"))
            cmds = item.get("commands")
            if not isinstance(cmds, list):
                raise DailyLoopConfigError(
                    f"mkt_assets item {iid}: 'commands' deve ser list[str] "
                    f"com tokens no namespace {_MKT_ASSETS_NAMESPACE!r}; "
                    f"recebido {type(cmds).__name__}"
                )
            stripped = _strip_directives(cmds)
            if not stripped and not integration_done:
                # Pre-integration placeholder is tolerated.
                continue
            if not stripped and integration_done:
                raise DailyLoopConfigError(
                    f"mkt_assets item {iid}: 'commands' vazio apos integracao. "
                    f"Re-rodar /loop:integration para materializar os tokens "
                    f"{_MKT_ASSETS_NAMESPACE}*."
                )
            heads = [c.split(" ", 1)[0] for c in stripped]
            out_of_lane = [h for h in heads if not h.startswith(_MKT_ASSETS_NAMESPACE)]
            if out_of_lane:
                raise DailyLoopConfigError(
                    f"mkt_assets item {iid}: tokens fora da lane "
                    f"{_MKT_ASSETS_NAMESPACE}*: {out_of_lane}. "
                    f"Iteration items da lane mkt-assets so podem despachar "
                    f"comandos {_MKT_ASSETS_NAMESPACE}* (Zero Fluxos Incompletos)."
                )


_KIMI_PAIR_COMMANDS = ("/cmd:kimi-pair-analyse", "/cmd:kimi-pair-execute")


def _iter_all_command_strings(
    daily_loop: dict[str, Any],
) -> Iterator[tuple[str, str]]:
    """Yield (location_label, command_string) over every command source.

    Covers ``buckets[*].items[*].commands``, ``items_index[*].commands``,
    ``items_index[*].expanded_commands`` and a recursive walk of
    ``iteration_template``. Used by ``_assert_no_orphan_kimi_pair`` to scan
    for contraband ``/cmd:kimi-pair-*`` tokens wherever they may hide.
    """
    for bucket in daily_loop.get("buckets", []) or []:
        if not isinstance(bucket, dict):
            continue
        bid = str(bucket.get("bucket_id", bucket.get("id", "?")))
        for item in bucket.get("items", []) or []:
            if not isinstance(item, dict):
                continue
            iid = str(item.get("id", "?"))
            for cmd in item.get("commands", []) or []:
                if isinstance(cmd, str):
                    yield (f"buckets[{bid}].items[{iid}].commands", cmd)

    items_index = daily_loop.get("items_index")
    if isinstance(items_index, dict):
        for iid, entry in items_index.items():
            if not isinstance(entry, dict):
                continue
            for cmd in entry.get("commands", []) or []:
                if isinstance(cmd, str):
                    yield (f"items_index[{iid}].commands", cmd)
            for cmd in entry.get("expanded_commands", []) or []:
                if isinstance(cmd, str):
                    yield (f"items_index[{iid}].expanded_commands", cmd)

    def _walk(node: Any, label: str) -> Iterator[tuple[str, str]]:
        if isinstance(node, str):
            yield (label, node)
        elif isinstance(node, list):
            for idx, child in enumerate(node):
                yield from _walk(child, f"{label}[{idx}]")
        elif isinstance(node, dict):
            for key, child in node.items():
                yield from _walk(child, f"{label}.{key}")

    yield from _walk(daily_loop.get("iteration_template"), "iteration_template")


def _assert_no_orphan_kimi_pair(raw_config: dict[str, Any]) -> None:
    """Reject ``/cmd:kimi-pair-*`` tokens that have no business in this loop.

    Last line of defense for legacy archives that the ``/loop:review`` C15 and
    ``/loop:workflow-app`` W10 spec gates never re-validated. Two guards:

      1. ``mode == "task"``: ANY ``/cmd:kimi-pair-analyse`` or
         ``/cmd:kimi-pair-execute`` token is a hard error. The Kimi pair adapts
         SLASH-COMMANDS and only exists in ``--cmd``/``--both`` loops, always
         chained right after ``/cmd:create|update|review``.
      2. ANY mode: a ``/cmd:kimi-pair-*`` token carrying a ``--task`` argument
         is a hard error. The ``--task`` form is the contamination smell; only
         the ``--approved`` form is valid inside a loop.

    Raises:
        DailyLoopConfigError: on the first offending token found (Zero Silencio).
    """
    daily_loop = raw_config.get("daily_loop")
    if not isinstance(daily_loop, dict):
        return

    mode = raw_config.get("mode")
    if not isinstance(mode, str):
        metadata = raw_config.get("metadata")
        if isinstance(metadata, dict):
            mode = metadata.get("mode")
    mode = mode.strip().lower() if isinstance(mode, str) else ""

    for label, cmd in _iter_all_command_strings(daily_loop):
        head = cmd.split(" ", 1)[0].strip()
        if head not in _KIMI_PAIR_COMMANDS:
            continue
        if mode == "task":
            raise DailyLoopConfigError(
                f"par Kimi contaminando loop modo --task em {label}: "
                f"'{cmd}'. O wrapper /cmd:kimi-pair-* adapta SLASH-COMMANDS "
                f"e so existe em loops --cmd/--both, sempre encadeado apos "
                f"/cmd:create, /cmd:update ou /cmd:review. "
                f"Re-rodar /loop:integration."
            )
        if "--task" in cmd.split():
            raise DailyLoopConfigError(
                f"par Kimi na forma --task em {label}: '{cmd}'. "
                f"Apenas a forma /cmd:kimi-pair-* --approved e valida dentro "
                f"de um loop; a forma --task <path> indica contaminacao."
            )


def build_daily_loop_specs(
    raw_config: dict[str, Any],
    loop_root: Path | str,
    *,
    project_workspace_root: Path | str | None = None,
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

    # mkt-assets lane (2026-06-18): recognize the discriminator here too so the
    # legacy daily-loop entrypoint enforces lane containment instead of falling
    # through to the silent "normal" default. Noop for other modes.
    if is_mkt_assets_mode(raw_config):
        assert_mkt_assets_iteration_shape(raw_config)

    # Reject /cmd:kimi-pair-* tokens orphaned in a --task loop or carrying the
    # --task contamination form (runtime guard, mirrors /loop:review C15 and
    # /loop:workflow-app W10 for legacy archives those gates never touched).
    _assert_no_orphan_kimi_pair(raw_config)

    slug = str(daily_loop.get("slug", "")).strip()
    if not slug:
        raise DailyLoopConfigError("daily_loop.slug ausente")

    bucket_index = _resolve_bucket_index(daily_loop)

    loop_root_path = Path(loop_root)
    workspace_root_path = resolve_effective_workspace_root(
        raw_config,
        loop_root_path,
        project_workspace_root=project_workspace_root,
    )
    progress_path = resolve_loop_path(
        daily_loop.get("progress_path"),
        loop_root_path,
        label="progress_path",
        default="PROGRESS.md",
    )

    if not progress_path.exists():
        raw_value = daily_loop.get("progress_path")
        fix_hint = diagnose_workspace_doubled_path(raw_value, loop_root_path)
        fix_line = (
            f"  ANTI-PATTERN DETECTADO (CONTRACT v1.1 secao 2.2): progress_path "
            f"parece workspace-relative. Trocar para {fix_hint!r} (filename-only "
            "relativo a loop_root) ou path absoluto.\n"
            if fix_hint
            else ""
        )
        raise DailyLoopConfigError(
            "PROGRESS.md nao encontrado.\n"
            f"  declarado em _LOOP-CONFIG.json:  progress_path = {raw_value!r}\n"
            f"  loop_root resolvido:              {loop_root_path}\n"
            f"  caminho final calculado:          {progress_path}\n"
            + fix_line
            + "  acao: rode /daily-loop:enumerate para regerar OU corrija progress_path "
            "no JSON (filename-only relativo a loop_root, ou path absoluto)."
        )

    items = parse_progress_items(progress_path.read_text(encoding="utf-8"))
    pending = [it for it in items if it.status == "pending"]

    if not pending:
        return []

    do_command = str(daily_loop.get("do_command", "/daily-loop:do")).strip() or "/daily-loop:do"
    # Per-item adversarial audit injected after each :do. Defaults to
    # /daily-loop:review-done (opus/standard) and runs /mcp:dual Level 3
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
    # Run-anchor inheritance (ver _resolve_effective_sizing): seed = primeiro par
    # explicito do loop, NAO o bucket. Independente da emissao; nao resetado por
    # /clear (esse reset zera apenas a re-emissao de /model e /effort).
    active_model, active_effort = _resolve_run_default_model_effort(daily_loop)

    for idx, item in enumerate(pending):
        # Opt-in: drop a /clear between items (after the prior :review-done,
        # before this :do). Skipped before the first item — position 0 already
        # holds a /clear. NAO resetar current_model/current_effort: /clear reseta
        # apenas o CONTEXTO da conversa, nunca /model nem /effort no CLI
        # (workflow-app-command-lists.md secao 1). Resetar forcaria re-emissao
        # redundante de directives identicas a cada item, violando a politica
        # anti-redundancia (secao 3.1). O dedup natural por bucket continua valendo.
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

        bucket = bucket_index.get(item.bucket_id)
        if bucket is None:
            raise DailyLoopConfigError(
                f"item {item.item_id} referencia bucket inexistente: {item.bucket_id!r}"
            )
        model, effort, active_model, active_effort = _resolve_effective_sizing(
            daily_loop, item.item_id, bucket, active_model, active_effort
        )

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
    *,
    project_workspace_root: Path | str | None = None,
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

    # B6 (2026-05-19): when raw_config declares mode=='rocksmash', enforce the
    # canonical 4-command per-iteration shape. Noop for other modes.
    if is_rocksmash_mode(raw_config):
        assert_rocksmash_iteration_shape(raw_config)

    # mkt-assets lane (2026-06-18): when raw_config declares mode=='mkt_assets',
    # enforce lane containment of per-iteration commands (discovery gate). Noop
    # for other modes. Keeps the variable /loop iteration shape — no fixed count.
    if is_mkt_assets_mode(raw_config):
        assert_mkt_assets_iteration_shape(raw_config)

    # Reject /cmd:kimi-pair-* tokens orphaned in a --task loop or carrying the
    # --task contamination form (runtime guard, mirrors /loop:review C15 and
    # /loop:workflow-app W10 for legacy archives those gates never touched).
    _assert_no_orphan_kimi_pair(raw_config)

    slug = str(daily_loop.get("slug", "")).strip()
    if not slug:
        raise DailyLoopConfigError("daily_loop.slug ausente")

    bucket_index = _resolve_bucket_index(daily_loop)

    loop_root_path = Path(loop_root)
    workspace_root_path = resolve_effective_workspace_root(
        raw_config,
        loop_root_path,
        project_workspace_root=project_workspace_root,
    )
    progress_path = resolve_loop_path(
        daily_loop.get("progress_path"),
        loop_root_path,
        label="progress_path",
        default="PROGRESS.md",
    )

    if not progress_path.exists():
        raw_value = daily_loop.get("progress_path")
        fix_hint = diagnose_workspace_doubled_path(raw_value, loop_root_path)
        fix_line = (
            f"  ANTI-PATTERN DETECTADO (CONTRACT v1.1 secao 2.2): progress_path "
            f"parece workspace-relative. Trocar para {fix_hint!r} (filename-only "
            "relativo a loop_root) ou path absoluto.\n"
            if fix_hint
            else ""
        )
        raise DailyLoopConfigError(
            "PROGRESS.md nao encontrado.\n"
            f"  declarado em _LOOP-CONFIG.json:  progress_path = {raw_value!r}\n"
            f"  loop_root resolvido:              {loop_root_path}\n"
            f"  caminho final calculado:          {progress_path}\n"
            + fix_line
            + "  acao: rode /loop ou /daily-loop:enumerate para regerar OU corrija "
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
    # Run-anchor inheritance (ver _resolve_effective_sizing): seed = primeiro par
    # explicito do loop, NAO o bucket. Independente da emissao; nao resetado por
    # /clear (esse reset zera apenas a re-emissao de /model e /effort).
    active_model, active_effort = _resolve_run_default_model_effort(daily_loop)

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
            # NAO resetar current_model/current_effort aqui. /clear reseta apenas
            # o CONTEXTO da conversa, nunca /model nem /effort no CLI
            # (workflow-app-command-lists.md secao 1, tabela de persistencia).
            # Resetar forcaria re-emissao redundante de /model e /effort identicos
            # a cada item, violando a politica anti-redundancia (secao 3.1).

        bucket = bucket_index.get(item.bucket_id)
        if bucket is None:
            raise DailyLoopConfigError(
                f"item {item.item_id} referencia bucket inexistente: {item.bucket_id!r}"
            )
        model, effort, active_model, active_effort = _resolve_effective_sizing(
            daily_loop, item.item_id, bucket, active_model, active_effort
        )

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
            # review_done_command NAO e injetado aqui: canonical_cmds ja carrega
            # seu proprio reviewer per-item (/loop:iteraction:review-executed-task,
            # /cmd:review, etc.). Injetar causaria cross-lane contamination
            # (/daily-loop:review-done revisando output de /loop:iteraction:execute-task).
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
            # Fallback path only: inject review_done_command.
            # canonical_cmds path omits this — reviewer e embedded nos commands.
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
