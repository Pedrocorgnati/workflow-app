"""End-to-end test reproducing the full B-dcp pipeline using the
`task-manager-desktop` reproducer copied into a tmp dir.

Loop 05-14-dcp-build-pipeline-implant Task 14.

Flow:
  1. Copy `output/wbs/task-manager-desktop/` into a tmp dir and rewrite
     `delivery.json` so every project path is reparented to the tmp dir
     (no absolute paths leak from the developer workstation).
  2. Build a PipelineConfig pointing at the copy.
  3. Reset `module-0-foundations.state` to `pending` and remove the absolute
     `last_specific_flow` pointer so the handler chooses the fresh-pipeline
     path (no destructive modal).
  4. Trigger `_on_dcp_build_pipeline_clicked` on a real CommandQueueWidget;
     assert the first emission has 6 items (5 slash + 1 local-action) and
     that the slash slot has the expected shape.
  5. Simulate the mock executor by writing a placeholder `SPECIFIC-FLOW.json`
     at the canonical level-1 cascade path (`{wbs}/modules/{cm_id}/
     SPECIFIC-FLOW.json`) — this is what the real `/build-module-pipeline`
     would produce after the first slash item "completes".
  6. Invoke the local-action handler at queue position 6; assert a second
     `pipeline_ready` emission appears carrying the commands from the
     placeholder flow (the queue is "substituted" by the flow contents).

This test does NOT exercise PipelineManager dispatch — that path is covered
by `test_local_action_dispatch.py`. The mock executor here is implicit
(handler-level), matching the spec's "simulate sucesso dos 5 slash-commands
criando SPECIFIC-FLOW.json placeholder no path canonico".
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any, List

import pytest

from workflow_app.config.config_parser import PipelineConfig
from workflow_app.domain import CommandSpec, InteractionType, ModelName
from workflow_app.services.delivery_reader import (
    DELIVERY_FILENAME,
    SPECIFIC_FLOW_FILENAME,
)


# Path on disk where the reproducer lives. The test is skipped if it is not
# checked into the workstation (e.g. CI without the output/ tree).
REPRODUCER_SRC = (
    Path(__file__).resolve().parents[3] / "output" / "wbs" / "task-manager-desktop"
)
REPRODUCER_AVAILABLE = (REPRODUCER_SRC / DELIVERY_FILENAME).exists()


@pytest.fixture()
def reproducer(tmp_path: Path) -> Path:
    """Copy the task-manager-desktop reproducer into tmp_path and rewrite
    delivery.json so absolute paths point at the copy."""
    if not REPRODUCER_AVAILABLE:
        pytest.skip(f"task-manager-desktop reproducer not present at {REPRODUCER_SRC}")

    dst = tmp_path / "task-manager-desktop"
    shutil.copytree(REPRODUCER_SRC, dst)

    delivery_path = dst / DELIVERY_FILENAME
    raw = json.loads(delivery_path.read_text(encoding="utf-8"))

    # Reparent project paths so the reader doesn't escape tmp_path.
    raw["project"]["brief_root"] = str(dst / "brief")
    raw["project"]["docs_root"] = str(dst / "docs")
    raw["project"]["wbs_root"] = str(dst)
    raw["project"]["workspace_root"] = str(dst / "workspace")

    # Fix skeleton block to match the current Delivery schema (the reproducer
    # captured an older shape that drops sha256/doc_path/code_path).
    raw["skeleton"] = {
        "version": raw.get("skeleton", {}).get("version", "skeleton-v2"),
        "sha256": "a" * 64,
        "doc_path": "output/_SHARED-SKELETON.md",
        "code_path": "output/shared/contracts",
        "last_updated": "2026-05-14T08:00:00Z",
        "bumped_by": "modules:create-structure",
    }
    raw.setdefault(
        "locks",
        {
            "holder": None,
            "acquired_at": None,
            "expires_at": None,
            "ttl_seconds": 120,
        },
    )
    meta = raw.setdefault(
        "metadata",
        {
            "schema_sha256": "schema-v1",
            "created_at": "2026-05-14T15:00:00Z",
            "created_by": "/delivery:init",
            "last_modified_by": "build-module-pipeline",
        },
    )
    # The on-disk reproducer often stores schema_sha256=None (legacy snapshot);
    # the current schema rejects null. Force a string value when missing/null.
    if not isinstance(meta.get("schema_sha256"), str):
        meta["schema_sha256"] = "schema-v1"
    if not isinstance(meta.get("created_at"), str):
        meta["created_at"] = "2026-05-14T15:00:00Z"
    if not isinstance(meta.get("created_by"), str):
        meta["created_by"] = "/delivery:init"
    if not isinstance(meta.get("last_modified_by"), str):
        meta["last_modified_by"] = "build-module-pipeline"

    # Normalise every module's module_type — the reproducer uses literals
    # ('feature') that aren't part of the ModuleType enum.
    valid_types = {
        "foundations",
        "landing-page",
        "dashboard",
        "crud",
        "auth",
        "integration",
        "payment",
        "notification",
        "backoffice",
        "infra-only",
        "api-only",
        "report",
    }
    for mid, mod in raw["modules"].items():
        if mod.get("module_type") not in valid_types:
            mod["module_type"] = "crud"

    # Force fresh-pipeline path (state=pending + clear absolute pointer) so
    # the destructive modal isn't triggered. The on-disk reproducer often
    # advances as the real project moves forward (current_module=module-2-...
    # once foundations is done); the test specifically exercises module-0,
    # so we pin it explicitly rather than inheriting whatever the snapshot has.
    cm_id = "module-0-foundations"
    raw["current_module"] = cm_id
    mod = raw["modules"][cm_id]
    mod["state"] = "pending"
    mod["state_detail"] = "pending"
    mod["history"] = []
    mod["attempt"] = 0
    mod["blocked"] = False
    mod["blocked_reason"] = None
    mod["blocked_prev_state"] = None
    mod["flags"]["needs_rework"] = False
    mod["rework_iterations"] = 0
    # v2 drops last_specific_flow / last_specific_flow_sha256 (DCP-COMMAND-MATRIX
    # rollout, ModuleArtifacts extra="forbid"). Strip from every module artifacts
    # block in case the on-disk reproducer still carries them (legacy snapshot).
    for _mod in raw["modules"].values():
        _arts = _mod.get("artifacts")
        if isinstance(_arts, dict):
            _arts.pop("last_specific_flow", None)
            _arts.pop("last_specific_flow_sha256", None)
    mod["artifacts"]["directive_injector_run_at"] = None
    mod["dependencies"] = []

    delivery_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    # Also wipe any existing module-0 SPECIFIC-FLOW.json so the placeholder
    # write later is the only one observed by the cascade.
    flow_path = dst / "modules" / cm_id / SPECIFIC_FLOW_FILENAME
    if flow_path.exists():
        flow_path.unlink()

    return dst


def _make_config(tmp_path: Path, wbs_root: Path) -> PipelineConfig:
    return PipelineConfig(
        config_path=str(tmp_path / ".claude" / "project.json"),
        project_name="task-manager-desktop",
        brief_root=str(wbs_root / "brief"),
        docs_root=str(wbs_root / "docs"),
        wbs_root=str(wbs_root),
        workspace_root=str(wbs_root / "workspace"),
    )


def test_e2e_dcp_build_pipeline_six_items_then_load_substitutes_queue(
    qapp, monkeypatch, tmp_path: Path, reproducer: Path
) -> None:
    """E2E — click → 6 items emitted → mock executor drops placeholder
    SPECIFIC-FLOW.json → local-action at position 6 emits second
    pipeline_ready with the flow's commands."""
    from workflow_app import dcp as dcp_pkg
    from workflow_app.command_queue.command_queue_widget import (
        CommandQueueWidget,
        DcpBuildContext,
    )
    from workflow_app.config.app_state import app_state
    from workflow_app.signal_bus import signal_bus

    cfg = _make_config(tmp_path, reproducer)
    app_state.set_config(cfg)
    monkeypatch.setattr(dcp_pkg, "READER_AVAILABLE", True)

    emissions: List[List[Any]] = []

    def listener(specs: List[Any]) -> None:
        emissions.append(specs)

    signal_bus.pipeline_ready.connect(listener)

    try:
        widget = CommandQueueWidget()
        try:
            # ── Step 1: click triggers the 6-item pipeline ──────────────────
            widget._on_dcp_build_pipeline_clicked()

            assert len(emissions) == 1, "first click should emit exactly one pipeline"
            first_specs = emissions[0]
            # `_inject_clears` (WORKFLOW-APP-RULES GROUP_MAP) expands the 6
            # canonical B-dcp specs with /clear + /model + /effort directive
            # triplets. Filter them to recover the 6 logical commands.
            first_real_specs = [
                s for s in first_specs
                if not (
                    s.name == "/clear"
                    or s.name.startswith("/model ")
                    or s.name.startswith("/effort ")
                )
            ]
            assert len(first_real_specs) == 6, (
                f"first emission must have 6 logical items, got "
                f"{len(first_real_specs)} (raw={len(first_specs)})"
            )

            # Slot 1: build-module-pipeline (module 0; fresh path = no --regenerate)
            assert first_real_specs[0].name.startswith("/build-module-pipeline ")
            assert "--module 0" in first_real_specs[0].name
            assert "--regenerate" not in first_real_specs[0].name

            # Slot 6: local-action with the load action id
            assert first_real_specs[5].kind == "local-action"
            assert first_real_specs[5].local_action_id == "dcp-load-specific-flow"

            # Widget must have armed the load context.
            assert isinstance(widget._pending_dcp_load_ctx, DcpBuildContext)
            assert widget._pending_dcp_load_ctx.cm_id == "module-0-foundations"

            # ── Step 2: mock executor "completes" the 5 slash commands by
            # writing the placeholder SPECIFIC-FLOW.json at the canonical
            # level-1 path. This is what `/build-module-pipeline` would
            # produce in a real session. ──────────────────────────────────
            flow_path = (
                reproducer
                / "modules"
                / "module-0-foundations"
                / SPECIFIC_FLOW_FILENAME
            )
            flow_payload = {
                "version": 1,
                "project": "task-manager-desktop",
                "module_id": "module-0-foundations",
                "commands": [
                    {
                        "name": "/front-end-build",
                        "model": "sonnet",
                        "effort": "high",
                        "phase": "B.2",
                        "interaction": "auto",
                    },
                    {
                        "name": "/back-end-build",
                        "model": "sonnet",
                        "effort": "high",
                        "phase": "B.2",
                        "interaction": "auto",
                    },
                ],
            }
            # The cascade resolves level-0 (per-module canonical wbs path)
            # before any other level. v2 schema dropped artifacts.last_specific_flow
            # (ModuleArtifacts extra="forbid"), so we rely on level-0 alone:
            # writing the flow at modules/{id}/SPECIFIC-FLOW.json is sufficient.
            flow_path.parent.mkdir(parents=True, exist_ok=True)
            flow_path.write_text(json.dumps(flow_payload, indent=2), encoding="utf-8")

            # ── Step 3: invoke the local-action at queue position 6 ─────────
            local_spec = first_real_specs[5]
            assert isinstance(local_spec, CommandSpec)
            ok = widget._handle_dcp_load_specific_flow(local_spec)
            assert ok is True, "local-action must return True on happy path"

            # Pending context is cleared after success.
            assert widget._pending_dcp_load_ctx is None

            # A second pipeline_ready was emitted carrying the flow's commands.
            assert len(emissions) == 2, (
                f"expected 2 emissions (6-item pipeline + flow load), "
                f"got {len(emissions)}"
            )
            second_specs = emissions[1]
            slash_names = [s.name for s in second_specs if s.kind == "slash"]
            assert "/front-end-build" in slash_names
            assert "/back-end-build" in slash_names
        finally:
            widget.deleteLater()
    finally:
        try:
            signal_bus.pipeline_ready.disconnect(listener)
        except (RuntimeError, TypeError):
            pass
        app_state.clear_config()


def test_e2e_dcp_build_button_tooltip_reflects_new_contract(qapp) -> None:
    """The new tooltip on `queue-btn-dcp-build` must mention the pipeline
    contract (enfileira, SPECIFIC-FLOW, modal de confirmacao) instead of the
    legacy 'Cola /build-module-pipeline no terminal' wording.

    Reproducer-independent: only needs widget construction. The button lives
    under `widget.header_widget` (reparented to MainWindow at runtime), so we
    search children of `header_widget` here rather than the widget itself.
    """
    from PySide6.QtWidgets import QPushButton

    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget

    widget = CommandQueueWidget()
    try:
        target = None
        for btn in widget.header_widget.findChildren(QPushButton):
            if btn.property("testid") == "queue-btn-dcp-build":
                target = btn
                break
        assert target is not None, "queue-btn-dcp-build not found under header_widget"

        tooltip = target.toolTip()
        # New contract phrases (from Task 13 cutover).
        assert "Enfileira pipeline" in tooltip
        assert "SPECIFIC-FLOW" in tooltip
        assert "Modal de confirmacao" in tooltip
        # Legacy wording must be gone.
        assert "Cola /build-module-pipeline no terminal" not in tooltip
    finally:
        widget.deleteLater()
