"""Expander for the ``queue-btn-rocksmash`` button.

Reads a ``_LOOP-CONFIG.json`` (kind == ``daily-loop``) and produces the
canonical ``/loop-rocksmash:*`` queue:

    /loop-rocksmash:prepare {abs/path/_LOOP-CONFIG.json}
    [ /loop-rocksmash:do {abs/path/tasks/items/task-NNN-*.md}
      /loop-rocksmash:review-done {abs/path/tasks/items/task-NNN-*.md} ]   x N
    /loop-rocksmash:rename {abs/path/_LOOP-CONFIG.json}

Iteration items are sourced from ``daily_loop.items_index`` (preferred when
present) or, as a fallback, from ``daily_loop.buckets[*].items[*]``. Items
with ``kind`` in {``preparo``, ``finalizacao``} are skipped — only
``iteration`` items (or items without an explicit kind, treated as
iteration) produce ``:do`` + ``:review-done`` pairs.

``/clear``, ``/model`` and ``/effort`` directives are auto-injected at
bucket boundaries, mirroring ``build_loop_specs``. The fixed framing
commands (``:prepare``, ``:rename``) use ``opus`` + ``standard`` to match
``T-opus-standard``, the canonical preparo/finalizacao bucket.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from workflow_app.daily_loop.loader import (
    DailyLoopConfigError,
    _bucket_to_model_effort,
    _resolve_bucket_index,
)
from workflow_app.domain import (
    CommandSpec,
    EffortLevel,
    InteractionType,
    ModelName,
)

_FRAMING_MODEL: ModelName = ModelName.OPUS
_FRAMING_EFFORT: EffortLevel = EffortLevel.STANDARD


def _iter_items(daily_loop: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    """Return [(item_id, item_dict), ...] sorted by item_id ascending.

    Reads from ``daily_loop.buckets[*].items[*]`` as the authoritative source
    per CONTRACT.md (``items_index`` is audit-only metadata; runtime reads
    from buckets). When a bucket item lacks ``kind``, ``task_path``, or
    ``target``, falls back to ``items_index[id]`` for that single field
    (legacy V3 configs pre-2026-05-17 stored these only in items_index).
    """
    items_index = daily_loop.get("items_index") or {}
    if not isinstance(items_index, dict):
        items_index = {}

    flat: list[tuple[str, dict[str, Any]]] = []
    for bucket in daily_loop.get("buckets", []) or []:
        if not isinstance(bucket, dict):
            continue
        bucket_id = str(bucket.get("id", ""))
        for item in bucket.get("items") or []:
            if not isinstance(item, dict):
                continue
            iid = str(item.get("id", ""))
            if not iid:
                continue
            enriched = dict(item)
            enriched.setdefault("bucket", bucket_id)
            # Backfill per-item metadata from items_index when absent in
            # bucket (retro-compat: pre-2026-05-17 producers only wrote
            # kind/task_path/target to items_index). New producers MUST
            # write both per the canonical shape in CONTRACT.md section 2.
            idx_entry = items_index.get(iid)
            if isinstance(idx_entry, dict):
                for fallback_field in ("kind", "task_path", "target"):
                    if not enriched.get(fallback_field) and idx_entry.get(fallback_field):
                        enriched[fallback_field] = idx_entry[fallback_field]
                # task_file (items_index naming) -> task_path (bucket naming)
                if not enriched.get("task_path") and not enriched.get("target") and idx_entry.get("task_file"):
                    enriched["task_path"] = idx_entry["task_file"]
            flat.append((iid, enriched))
    return sorted(flat, key=lambda kv: kv[0])


def _resolve_task_path(
    item: dict[str, Any], loop_root: Path
) -> Path | None:
    """Resolve absolute task path from an item dict.

    Looks at ``task_path`` (preferred when present) then ``target``;
    relative paths are anchored at ``loop_root``.
    """
    raw = item.get("task_path") or item.get("target")
    if not raw:
        return None
    p = Path(str(raw))
    if not p.is_absolute():
        p = loop_root / p
    return p


def build_loop_rocksmash_specs(
    raw_config: dict[str, Any],
    loop_root: Path | str,
) -> list[CommandSpec]:
    """Build the canonical /loop-rocksmash:* queue from a daily-loop config.

    Args:
        raw_config: parsed ``_LOOP-CONFIG.json`` root dict (must have
            ``kind == "daily-loop"`` and a ``daily_loop`` block).
        loop_root: directory containing the ``_LOOP-CONFIG.json``.

    Returns:
        list[CommandSpec] starting with ``/clear`` + framing prepare,
        followed by per-iteration pairs, ending with framing rename.

    Raises:
        DailyLoopConfigError: missing ``daily_loop`` block, no iteration
            items, or a bucket referenced by an item is unknown.
    """
    daily_loop = raw_config.get("daily_loop")
    if not isinstance(daily_loop, dict):
        raise DailyLoopConfigError(
            "_LOOP-CONFIG.json sem bloco 'daily_loop' — "
            "rode /loop ou /daily-loop:enumerate para regerar."
        )

    loop_root_path = Path(loop_root)
    config_path = loop_root_path / "_LOOP-CONFIG.json"

    bucket_index = _resolve_bucket_index(daily_loop)

    all_items = _iter_items(daily_loop)
    iteration_items = [
        (iid, it)
        for iid, it in all_items
        if str(it.get("kind", "iteration")) == "iteration"
        and not it.get("archived")
        and it.get("rocksmash_executable", True)
    ]
    if not iteration_items:
        raise DailyLoopConfigError(
            "Nenhum item com kind=iteration encontrado. "
            "rocksmash exige pelo menos 1 par :do/:review-done. "
            "Verifique tambem se algum item esta com rocksmash_executable=false "
            "(gate RP-EXEC-01 do /loop-rocksmash:prepare)."
        )

    specs: list[CommandSpec] = []

    # Leading /clear to scrub context before the framing prepare.
    specs.append(
        CommandSpec(
            name="/clear",
            model=ModelName.SONNET,
            interaction_type=InteractionType.AUTO,
            config_path="",
            position=0,
        )
    )

    # Framing model+effort for prepare/rename.
    specs.append(
        CommandSpec(
            name=f"/model {_FRAMING_MODEL.value.lower()}",
            model=_FRAMING_MODEL,
            interaction_type=InteractionType.AUTO,
            config_path="",
            position=0,
        )
    )
    specs.append(
        CommandSpec(
            name=f"/effort {_FRAMING_EFFORT.value.lower()}",
            model=_FRAMING_MODEL,
            interaction_type=InteractionType.AUTO,
            config_path="",
            position=0,
        )
    )
    current_model: ModelName = _FRAMING_MODEL
    current_effort: EffortLevel = _FRAMING_EFFORT

    specs.append(
        CommandSpec(
            name=f"/loop-rocksmash:prepare {config_path}",
            model=_FRAMING_MODEL,
            interaction_type=InteractionType.AUTO,
            config_path="",
            position=0,
            effort=_FRAMING_EFFORT,
            phase="loop-rocksmash",
        )
    )

    for iid, item in iteration_items:
        task_path = _resolve_task_path(item, loop_root_path)
        if task_path is None:
            raise DailyLoopConfigError(
                f"item {iid} sem task_path/target — corrija o JSON antes de usar rocksmash."
            )

        bucket_id = str(item.get("bucket", ""))
        bucket = bucket_index.get(bucket_id)
        if bucket is None:
            raise DailyLoopConfigError(
                f"item {iid} referencia bucket inexistente: {bucket_id!r}"
            )
        model, effort = _bucket_to_model_effort(bucket)

        # /clear between items + model/effort drift directives.
        specs.append(
            CommandSpec(
                name="/clear",
                model=ModelName.SONNET,
                interaction_type=InteractionType.AUTO,
                config_path="",
                position=0,
            )
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

        specs.append(
            CommandSpec(
                name=f"/loop-rocksmash:do {task_path}",
                model=model,
                interaction_type=InteractionType.AUTO,
                config_path="",
                position=0,
                effort=effort,
                phase="loop-rocksmash",
            )
        )
        specs.append(
            CommandSpec(
                name=f"/loop-rocksmash:review-done {task_path}",
                model=model,
                interaction_type=InteractionType.AUTO,
                config_path="",
                position=0,
                effort=effort,
                phase="loop-rocksmash",
            )
        )

    # Framing rename — switch back to framing model/effort if drifted.
    specs.append(
        CommandSpec(
            name="/clear",
            model=ModelName.SONNET,
            interaction_type=InteractionType.AUTO,
            config_path="",
            position=0,
        )
    )
    if current_model != _FRAMING_MODEL:
        specs.append(
            CommandSpec(
                name=f"/model {_FRAMING_MODEL.value.lower()}",
                model=_FRAMING_MODEL,
                interaction_type=InteractionType.AUTO,
                config_path="",
                position=0,
            )
        )
    if current_effort != _FRAMING_EFFORT:
        specs.append(
            CommandSpec(
                name=f"/effort {_FRAMING_EFFORT.value.lower()}",
                model=_FRAMING_MODEL,
                interaction_type=InteractionType.AUTO,
                config_path="",
                position=0,
            )
        )
    specs.append(
        CommandSpec(
            name=f"/loop-rocksmash:rename {config_path}",
            model=_FRAMING_MODEL,
            interaction_type=InteractionType.AUTO,
            config_path="",
            position=0,
            effort=_FRAMING_EFFORT,
            phase="loop-rocksmash",
        )
    )

    return specs
