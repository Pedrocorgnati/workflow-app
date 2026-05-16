"""Pure handler that decides which `/build-module-pipeline ...` variant to
paste in the interactive terminal when the user clicks `[DCP: Specific-Flow]`.

No Qt dependency, no I/O beyond what `DeliveryReader` already performs, no
mutation of `delivery.json` (invariants I-01 / I-10 preserved). The widget
click callback wraps the returned `SpecificFlowAction` in a QMessageBox or a
`signal_bus.run_command_in_terminal.emit(...)` call — separation of concerns
keeps the handler unit-testable without PySide6.

Decision table (per TASK-050 §Subtasks + detailed.md §6.3):

    config is None / no has_config     → QMessageBox "Carregue um projeto..."
    DeliveryMissing                    → QMessageBox "delivery.json ausente..."
    DeliveryInvalid                    → QMessageBox with error summary
    DeliveryFutureVersion              → QMessageBox with upgrade hint
    current_module is None             → QMessageBox "Nenhum modulo ativo..."
    all modules.state == "done"        → QMessageBox "Nenhum modulo ativo..."
    current_module.state == "done"     → QMessageBox "Nenhum modulo ativo..."
    module not in modules dict         → QMessageBox "current_module nao existe..."
    module.state == "pending"          → paste canonical pipeline command
                                         (build_paste_command_only, no flags)
    artifacts.last_specific_flow set   → paste canonical command with
                                         ``--regenerate`` (re-emit SPECIFIC-FLOW
                                         without re-transitioning state)
    otherwise                          → QMessageBox "modulo {id} em estado {state}..."

The two "done" branches collapse into the same "Nenhum modulo ativo..."
message per TASK-050 §107 ("current_module é None OR todos os modulos estao
done → MessageBox 'Nenhum modulo ativo...'"). This is stricter than looking
at `current_module` alone because delivery.json can point to a finished
module while the pipeline is between runs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from workflow_app.config.config_parser import PipelineConfig

# T-035 reader is an optional dependency at module-load time: when the service
# is missing the app must still start with `[DCP: Specific-Flow]` disabled
# (TASK-050 lines 51, 112-119). Guarding the import keeps this module loadable
# even if the reader is absent — `resolve()` is only reached when the widget
# gating confirmed `dcp.READER_AVAILABLE is True`, so the rebinding below is
# safe in production.
try:
    from workflow_app.services.delivery_reader import (
        DeliveryFound,
        DeliveryFutureVersion,
        DeliveryInvalid,
        DeliveryMissing,
        DeliveryReader,
    )
except ImportError:  # pragma: no cover — exercised indirectly via dcp/__init__.py
    DeliveryFound = None  # type: ignore[assignment,misc]
    DeliveryFutureVersion = None  # type: ignore[assignment,misc]
    DeliveryInvalid = None  # type: ignore[assignment,misc]
    DeliveryMissing = None  # type: ignore[assignment,misc]
    DeliveryReader = None  # type: ignore[assignment,misc]

if TYPE_CHECKING:  # pragma: no cover
    from workflow_app.services.delivery_reader import (
        DeliveryReader as _DeliveryReaderType,
    )


@dataclass(frozen=True)
class SpecificFlowAction:
    """Outcome of resolving a click on the `[DCP: Specific-Flow]` button.

    Attributes:
        command: `/build-module-pipeline ...` text to paste in the terminal,
            or `None` when the widget must show a QMessageBox instead.
        reason: Human-readable explanation. Used either as the QMessageBox
            body (when `command is None`) or as a log string / toast hint
            (when the widget pastes `command`).
    """

    command: Optional[str]
    reason: str


import re as _re


def _sort_module_key(module_id: str) -> tuple:
    m = _re.match(r"^module-(\d+)([a-z]?)-", module_id)
    return (int(m.group(1)), m.group(2)) if m else (9999, module_id)


def _next_non_done_module_id(delivery: "Delivery") -> "Optional[str]":  # type: ignore[name-defined]
    """Return the first non-done module key ordered by module number, or None.

    Called when `current_module` points to a `done` module so the button can
    auto-advance to the next pending module instead of blocking the user.
    """
    candidates = [mid for mid, mod in delivery.modules.items() if mod.state != "done"]
    return sorted(candidates, key=_sort_module_key)[0] if candidates else None


def _module_number(module_id: str) -> str:
    """Extract the numeric (+ optional letter) part from a module id.

    Examples:
        'module-1-setup'        → '1'
        'module-6a-aba3-engine' → '6a'
    """
    m = _re.match(r"^module-(\d+[a-z]?)-", module_id)
    return m.group(1) if m else module_id


def _relative_config_path(config_path: str) -> str:
    """Return config_path relative to the repo root (walk-up to CLAUDE.md).

    Falls back to the absolute path if the repo root cannot be found.
    """
    p = Path(config_path)
    for parent in p.parents:
        if (parent / "CLAUDE.md").exists():
            try:
                return str(p.relative_to(parent))
            except ValueError:
                break
    return config_path


def build_paste_command_only(
    config: "Optional[PipelineConfig]" = None,
    current_module: "Optional[str]" = None,
    *,
    regenerate: bool = False,
) -> str:
    """Return the literal text the `[DCP: Build Module Pipeline]` button pastes.

    When *config* and *current_module* are supplied the command is enriched
    with ``--module {N}`` and the config path so the user can paste it
    directly without editing:

        /build-module-pipeline --module 1 .claude/projects/zap-typist.json

    When *regenerate* is True (module already past pending — re-emit
    SPECIFIC-FLOW.json without re-transitioning state), ``--regenerate`` is
    inserted before ``--module``:

        /build-module-pipeline --regenerate --module 1 .claude/projects/zap-typist.json

    When only *config* is supplied (current_module unavailable), the command
    still includes the config path so build-module-pipeline can resolve the
    current module from delivery.json itself:

        /build-module-pipeline .claude/projects/zap-typist.json

    Falls back to the bare ``/build-module-pipeline`` only when config is
    also absent (stateless, backwards-compatible).
    """
    if config is None:
        return "/build-module-pipeline"
    rel_path = _relative_config_path(config.config_path)
    flags = " --regenerate" if regenerate else ""
    if current_module is None:
        return f"/build-module-pipeline{flags} {rel_path}"
    module_num = _module_number(current_module)
    return f"/build-module-pipeline{flags} --module {module_num} {rel_path}"


def _resolve_wbs_root(config: PipelineConfig) -> Path:
    """Return the absolute `wbs_root` for a given PipelineConfig.

    `config.wbs_root` may be absolute or relative to `config.project_dir`.
    This mirrors the same resolution rule used by the T-035 reader, so the
    handler and the reader agree on the path they use to look up delivery.json.
    """
    wbs = Path(config.wbs_root)
    if wbs.is_absolute():
        return wbs
    return config.project_dir / wbs


def resolve(
    config: Optional[PipelineConfig],
    reader: Optional[DeliveryReader] = None,
) -> SpecificFlowAction:
    """Decide which command (if any) the `[DCP: Specific-Flow]` button pastes.

    Args:
        config: Currently loaded `PipelineConfig`, or `None` when no project
            is loaded in `app_state`.
        reader: Optional pre-instantiated `DeliveryReader` (for tests that
            want to share a cache). A fresh one is created if `None`.

    Returns:
        A `SpecificFlowAction` whose `command` is the paste text (or `None`
        when the widget should surface `reason` via `QMessageBox.information`).
    """
    if config is None:
        return SpecificFlowAction(
            None,
            "Carregue um projeto (pill superior) antes de gerar pipeline DCP.",
        )

    if reader is None:
        reader = DeliveryReader()

    wbs_root = _resolve_wbs_root(config)
    result = reader.load(wbs_root)

    if isinstance(result, DeliveryMissing):
        return SpecificFlowAction(
            None,
            "delivery.json ausente — rode /delivery:init antes de gerar pipeline DCP.",
        )
    if isinstance(result, DeliveryInvalid):
        return SpecificFlowAction(
            None,
            f"delivery.json invalido: {result.error}. Rode /delivery:validate.",
        )
    if isinstance(result, DeliveryFutureVersion):
        return SpecificFlowAction(None, result.message)

    assert isinstance(result, DeliveryFound)
    delivery = result.delivery

    no_active_module_msg = (
        "Nenhum modulo ativo. Use [DCP: Build Module Pipeline] primeiro"
    )

    cm_id = delivery.current_module
    if not cm_id:
        return SpecificFlowAction(None, no_active_module_msg)

    if delivery.modules and all(
        m.state == "done" for m in delivery.modules.values()
    ):
        return SpecificFlowAction(None, no_active_module_msg)

    module = delivery.modules.get(cm_id)
    if module is None:
        return SpecificFlowAction(
            None,
            f"current_module={cm_id!r} nao existe em modules. Rode /delivery:validate.",
        )

    if module.state == "done":
        next_id = _next_non_done_module_id(delivery)
        if next_id is None:
            return SpecificFlowAction(None, no_active_module_msg)
        cm_id = next_id
        module = delivery.modules[cm_id]

    if module.state == "pending":
        return SpecificFlowAction(
            build_paste_command_only(config=config, current_module=cm_id),
            "novo pipeline",
        )

    if module.artifacts.last_specific_flow:
        return SpecificFlowAction(
            build_paste_command_only(
                config=config, current_module=cm_id, regenerate=True
            ),
            "regenerar SPECIFIC-FLOW existente",
        )

    return SpecificFlowAction(
        None,
        f"modulo {cm_id} em estado {module.state!r} — use o botao DCP correspondente a essa fase",
    )


# Re-exports from queue_derivation so callers that have historically imported
# the matrix-helpers from this module keep working after task-027 / st-05
# split. `_next_non_done_module_id` already lives here for delivery-driven
# auto-advance; `_last_module_id` operates on the matrix and is sourced from
# the queue derivation module.
try:
    from workflow_app.dcp.queue_derivation import (  # noqa: E402
        _last_module_id,
    )
except ImportError:  # pragma: no cover — defensive (Pydantic/model dep missing)
    _last_module_id = None  # type: ignore[assignment]


__all__ = [
    "SpecificFlowAction",
    "build_paste_command_only",
    "resolve",
    "_next_non_done_module_id",
    "_last_module_id",
]
