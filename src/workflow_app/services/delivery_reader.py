"""Read `delivery.json` v1 as the primary state source for the workflow-app.

Aligned with DCP-9.2 / DCP-9.3 / DCP-5.2. This module is **read-only** — it
does not acquire the cooperative lock (T-005), since reads do not race with
writes under the DCP short-lock protocol (§5.2.10: "comandos CLI devem
segurar o lock somente durante a escrita"). T-037 will add lock-aware
behavior for mutating flows.

Load result is an explicit ADT so callers can pattern-match without try/except.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from pydantic import ValidationError

from workflow_app.models.delivery import (
    Delivery,
    DeliveryInvariantWarning,
)

logger = logging.getLogger(__name__)

DELIVERY_FILENAME = "delivery.json"
SPECIFIC_FLOW_FILENAME = "SPECIFIC-FLOW.json"
DEFAULT_CUSTOM_WORKFLOW_SUBDIR = "workflow-app"


# ─── Load result ADT ─────────────────────────────────────────────────────── #


@dataclass(frozen=True)
class DeliveryFound:
    delivery: Delivery
    warnings: List[DeliveryInvariantWarning]
    path: Path
    mtime: float


@dataclass(frozen=True)
class DeliveryMissing:
    path: Path
    message: str = "delivery.json nao encontrado"


@dataclass(frozen=True)
class DeliveryInvalid:
    path: Path
    error: str  # human-readable summary
    details: Optional[str] = None  # full pydantic error JSON


@dataclass(frozen=True)
class DeliveryFutureVersion:
    path: Path
    version: Any
    message: str


DeliveryLoadResult = Union[
    DeliveryFound, DeliveryMissing, DeliveryInvalid, DeliveryFutureVersion
]


# ─── Reader ──────────────────────────────────────────────────────────────── #


class DeliveryReader:
    """Cached reader for `delivery.json`.

    Usage::

        reader = DeliveryReader()
        result = reader.load(wbs_root)
        if isinstance(result, DeliveryFound):
            for warn in result.warnings:
                ui.show_invariant_warning(warn)
            flow_path = reader.resolve_specific_flow(
                result.delivery,
                module_id="module-0-foundations",
                project_root=Path("."),
            )
    """

    def __init__(self) -> None:
        # Cache keyed by (delivery_path, module_id, delivery_mtime).
        self._flow_cache: Dict[tuple, Optional[Path]] = {}

    # -- loading -----------------------------------------------------------

    def load(self, wbs_root: Path | str) -> DeliveryLoadResult:
        """Load `delivery.json` from `{wbs_root}/delivery.json`."""
        wbs_root = Path(wbs_root)
        path = wbs_root / DELIVERY_FILENAME

        if not path.exists():
            return DeliveryMissing(path=path)

        try:
            content = path.read_text(encoding="utf-8")
        except OSError as exc:
            return DeliveryInvalid(
                path=path,
                error=f"io error reading delivery.json: {exc}",
            )

        # Pre-peek version so we can emit a friendly error for v>1 without
        # dragging pydantic's opaque Literal error up to the UI layer.
        try:
            raw = json.loads(content)
        except json.JSONDecodeError as exc:
            return DeliveryInvalid(
                path=path,
                error=f"invalid JSON: {exc.msg} (line {exc.lineno}, col {exc.colno})",
            )

        raw_version = raw.get("version") if isinstance(raw, dict) else None
        if isinstance(raw_version, int) and raw_version > 1:
            return DeliveryFutureVersion(
                path=path,
                version=raw_version,
                message=(
                    f"Workflow-app precisa de update para delivery.json version={raw_version}"
                ),
            )

        try:
            delivery = Delivery.model_validate(raw)
        except ValidationError as exc:
            return DeliveryInvalid(
                path=path,
                error=f"schema validation failed ({exc.error_count()} errors)",
                details=exc.json(),
            )

        try:
            mtime = path.stat().st_mtime
        except OSError:
            mtime = 0.0

        return DeliveryFound(
            delivery=delivery,
            warnings=delivery.get_invariant_warnings(),
            path=path,
            mtime=mtime,
        )

    # -- specific-flow resolution -----------------------------------------

    def resolve_specific_flow(
        self,
        delivery: Delivery,
        module_id: str,
        project_root: Path | str,
        *,
        custom_workflow_root: Optional[str] = None,
        delivery_mtime: float = 0.0,
    ) -> Optional[Path]:
        """Resolve which `SPECIFIC-FLOW.json` to load for a module.

        Cascade (DCP-9.2):
          1. `delivery.modules[id].artifacts.last_specific_flow` (path relative
             to `wbs_root`). If exists on disk, return it.
          2. `{custom_workflow_root or wbs_root/workflow-app}/SPECIFIC-FLOW.json`.
          3. `quick_templates` stub — **not implemented in T-035**. Returns
             `None`; T-050 will wire an adapter to `workflow_app.templates.quick_templates`.

        Cache key: `(delivery.project.wbs_root, module_id, delivery_mtime)`.
        The cache is invalidated when the caller re-loads `delivery.json` and
        passes the new mtime.
        """
        project_root = Path(project_root)

        cache_key = (delivery.project.wbs_root, module_id, delivery_mtime)
        if cache_key in self._flow_cache:
            return self._flow_cache[cache_key]

        path = resolve_specific_flow(
            delivery,
            module_id,
            project_root,
            custom_workflow_root=custom_workflow_root,
        )
        self._flow_cache[cache_key] = path
        return path

    def invalidate_cache(self) -> None:
        self._flow_cache.clear()


# ─── Functional helpers (callable without an instance) ──────────────────── #


def resolve_specific_flow(
    delivery: Delivery,
    module_id: str,
    project_root: Path | str,
    *,
    custom_workflow_root: Optional[str] = None,
) -> Optional[Path]:
    """Pure function version of `DeliveryReader.resolve_specific_flow` (no cache).

    See `DeliveryReader.resolve_specific_flow` for the cascade description.
    """
    project_root = Path(project_root)
    module = delivery.modules.get(module_id)
    if module is None:
        logger.debug("resolve_specific_flow: module %s not in delivery", module_id)
        return None

    wbs = Path(delivery.project.wbs_root)
    wbs_abs = wbs if wbs.is_absolute() else (project_root / wbs)

    # Level 1: artifacts.last_specific_flow (relative to wbs_root).
    last = module.artifacts.last_specific_flow
    if last:
        candidate = Path(last)
        if not candidate.is_absolute():
            candidate = wbs_abs / candidate
        if candidate.exists():
            return candidate
        logger.debug(
            "resolve_specific_flow: level-1 miss for %s (last_specific_flow=%s)",
            module_id,
            candidate,
        )

    # Level 2: {custom_workflow_root}/SPECIFIC-FLOW.json.
    cwr = custom_workflow_root or str(
        wbs_abs / DEFAULT_CUSTOM_WORKFLOW_SUBDIR
    )
    cwr_path = Path(cwr)
    if not cwr_path.is_absolute():
        cwr_path = project_root / cwr_path
    candidate = cwr_path / SPECIFIC_FLOW_FILENAME
    if candidate.exists():
        return candidate
    logger.debug(
        "resolve_specific_flow: level-2 miss for %s (candidate=%s)",
        module_id,
        candidate,
    )

    # Level 3: quick_templates fallback — not implemented in T-035.
    # T-050 will wire this to `workflow_app.templates.quick_templates`.
    logger.debug(
        "resolve_specific_flow: level-3 (quick_templates) not implemented; "
        "returning None for %s",
        module_id,
    )
    return None


def read_module_meta(
    delivery: Delivery,
    module_id: str,
    project_root: Path | str,
) -> Optional[Dict[str, Any]]:
    """Best-effort read of `MODULE-META.json` for a module.

    Returns the parsed dict or `None` if `artifacts.module_meta_path` is null,
    the file does not exist, or the JSON is invalid. The shape of the dict
    is not validated here — T-050 may substitute this by a pydantic model
    for T-008 once that schema is imported into the workflow-app.
    """
    project_root = Path(project_root)
    module = delivery.modules.get(module_id)
    if module is None or not module.artifacts.module_meta_path:
        return None

    wbs = Path(delivery.project.wbs_root)
    wbs_abs = wbs if wbs.is_absolute() else (project_root / wbs)

    meta_path = Path(module.artifacts.module_meta_path)
    if not meta_path.is_absolute():
        # module_meta_path is stored relative to workspace root in some specs;
        # we try wbs-relative first, then project-root-relative.
        for base in (wbs_abs, project_root):
            candidate = base / meta_path
            if candidate.exists():
                meta_path = candidate
                break
        else:
            return None

    try:
        return json.loads(meta_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("read_module_meta: failed to read %s: %s", meta_path, exc)
        return None


__all__ = [
    "DEFAULT_CUSTOM_WORKFLOW_SUBDIR",
    "DELIVERY_FILENAME",
    "DeliveryFound",
    "DeliveryFutureVersion",
    "DeliveryInvalid",
    "DeliveryLoadResult",
    "DeliveryMissing",
    "DeliveryReader",
    "SPECIFIC_FLOW_FILENAME",
    "read_module_meta",
    "resolve_specific_flow",
]
