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
    module.state == "pending"          → paste "/build-module-pipeline {id}"
    artifacts.last_specific_flow set   → paste "/build-module-pipeline --rehydrate {id}"
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


def build_paste_command_only() -> str:
    """Return the literal text the `[DCP: Build Module Pipeline]` button pastes.

    The button intentionally does NOT try to resolve `current_module` itself —
    `/build-module-pipeline` (T-013) already does that via the project CWD.
    """
    return "/build-module-pipeline"


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
        return SpecificFlowAction(None, no_active_module_msg)

    if module.state == "pending":
        return SpecificFlowAction(
            f"/build-module-pipeline {cm_id}",
            "novo pipeline",
        )

    if module.artifacts.last_specific_flow:
        return SpecificFlowAction(
            f"/build-module-pipeline --rehydrate {cm_id}",
            "reidratar pipeline existente",
        )

    return SpecificFlowAction(
        None,
        f"modulo {cm_id} em estado {module.state!r} — use o botao DCP correspondente a essa fase",
    )


__all__ = [
    "SpecificFlowAction",
    "build_paste_command_only",
    "resolve",
]
