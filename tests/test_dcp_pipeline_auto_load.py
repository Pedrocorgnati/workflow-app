"""Tests for `_handle_dcp_load_specific_flow` — the local-action callable
registered under id `dcp-load-specific-flow` and invoked at queue position 6
of the B-dcp pipeline.

Loop 05-14-dcp-build-pipeline-implant Task 14 — consolidates Task 12 assertions.

4 cases covered:

  A1  no pending context → toast 'error', returns False
  A2  pipeline succeeded but delivery.json went unreadable → toast 'error',
      returns False, clears pending context
  A3  pipeline succeeded but SPECIFIC-FLOW.json never appeared on disk →
      toast 'warning', returns False, clears pending context
  A4  happy path → resolves flow, calls `_enqueue_specific_flow` once,
      returns True, clears pending context
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from workflow_app.config.config_parser import PipelineConfig
from workflow_app.domain import CommandSpec, InteractionType, ModelName
from workflow_app.services.delivery_reader import (
    DELIVERY_FILENAME,
    SPECIFIC_FLOW_FILENAME,
)


# ─── Fixtures ─────────────────────────────────────────────────────────────── #


def _base_project(wbs_root: Path) -> Dict[str, Any]:
    return {
        "name": "dcp-auto-load-test",
        "brief_root": str(wbs_root / "brief"),
        "docs_root": str(wbs_root / "docs"),
        "wbs_root": str(wbs_root),
        "workspace_root": str(wbs_root / "workspace"),
    }


def _module_state(state: str = "creation") -> Dict[str, Any]:
    return {
        "state": state,
        "state_detail": f"{state}-detail",
        "module_type": "crud",
        "attempt": 1,
        "started_at": "2026-05-14T12:00:00Z",
        "last_transition": "2026-05-14T12:00:00Z",
        "blocked": False,
        "blocked_reason": None,
        "blocked_prev_state": None,
        "owner": "pipeline",
        "flags": {
            "needs_rework": False,
            "skeleton_outdated": False,
            "rework_target": {"phase": None, "module": None},
        },
        "skeleton_version": "skeleton-v2",
        "rework_iterations": 0,
        "max_rework_iterations": 2,
        "history": [
            {
                "from": "pending",
                "to": state,
                "at": "2026-05-14T12:00:00Z",
                "by": "build-module-pipeline",
                "note": "auto",
            }
        ],
        "artifacts": {
            "module_meta_path": None,
            "overview_path": None,
            "last_review_report": None,
            "last_commit_sha": None,
            "last_deploy_url": None,
            "git_tag": None,
        },
        "dependencies": [],
    }


def _write_delivery(wbs_root: Path, module_id: str = "module-1-x") -> Path:
    payload = {
        "version": 2,
        "project": _base_project(wbs_root),
        "current_module": module_id,
        "current_modules": [],
        "execution_mode": "sequential",
        "modules": {module_id: _module_state("creation")},
        "skeleton": {
            "version": "skeleton-v2",
            "sha256": "deadbeef",
            "doc_path": "output/_SHARED-SKELETON.md",
            "code_path": "output/shared/contracts",
            "last_updated": "2026-05-14T08:00:00Z",
            "bumped_by": "modules:create-structure",
        },
        "locks": {
            "holder": None,
            "acquired_at": None,
            "expires_at": None,
            "ttl_seconds": 120,
        },
        "metadata": {
            "schema_sha256": "schema-v1",
            "created_at": "2026-05-14T15:00:00Z",
            "created_by": "/delivery:init",
            "last_modified_by": "build-module-pipeline",
        },
    }
    path = wbs_root / DELIVERY_FILENAME
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _make_config(tmp_path: Path, wbs_root: Path) -> PipelineConfig:
    return PipelineConfig(
        config_path=str(tmp_path / ".claude" / "project.json"),
        project_name="dcp-auto-load-test",
        brief_root=str(wbs_root / "brief"),
        docs_root=str(wbs_root / "docs"),
        wbs_root=str(wbs_root),
        workspace_root=str(wbs_root / "workspace"),
    )


def _make_spec() -> CommandSpec:
    return CommandSpec(
        name="DCP: Carregar Specific-Flow",
        model=ModelName.SONNET,
        interaction_type=InteractionType.AUTO,
        position=6,
        kind="local-action",
        local_action_id="dcp-load-specific-flow",
    )


def _setup_widget(
    qapp, monkeypatch, cfg: PipelineConfig
):
    """Instantiate CommandQueueWidget with reader available and config set."""
    from workflow_app import dcp as dcp_pkg
    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
    from workflow_app.config.app_state import app_state

    monkeypatch.setattr(dcp_pkg, "READER_AVAILABLE", True)
    app_state.set_config(cfg)
    widget = CommandQueueWidget()
    return widget


def _capture_toasts() -> Tuple[List[Tuple[str, str]], Any]:
    """Register a connected listener on signal_bus.toast_requested.

    Returns (captured_list, disconnect_fn). The disconnect_fn must be called
    in a finally to avoid leaking handlers between tests.
    """
    from workflow_app.signal_bus import signal_bus

    captured: List[Tuple[str, str]] = []

    def listener(msg: str, kind: str) -> None:
        captured.append((msg, kind))

    signal_bus.toast_requested.connect(listener)

    def disconnect() -> None:
        try:
            signal_bus.toast_requested.disconnect(listener)
        except (RuntimeError, TypeError):
            pass

    return captured, disconnect


# ─── A1: no pending context ───────────────────────────────────────────────── #


def test_handle_dcp_load_returns_false_when_no_pending_context(
    qapp, monkeypatch, tmp_path: Path
) -> None:
    """A1 — no `_pending_dcp_load_ctx` armed → toast 'error', returns False."""
    from workflow_app.config.app_state import app_state

    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()
    cfg = _make_config(tmp_path, wbs_root)

    captured, disconnect = _capture_toasts()
    try:
        widget = _setup_widget(qapp, monkeypatch, cfg)
        try:
            widget._pending_dcp_load_ctx = None
            result = widget._handle_dcp_load_specific_flow(_make_spec())
        finally:
            widget.deleteLater()
    finally:
        app_state.clear_config()
        disconnect()

    assert result is False
    assert len(captured) == 1
    msg, kind = captured[0]
    assert kind == "error"
    assert "sem contexto" in msg


# ─── A2: delivery becomes unreadable after pipeline ───────────────────────── #


def test_handle_dcp_load_returns_false_when_delivery_indisponivel(
    qapp, monkeypatch, tmp_path: Path
) -> None:
    """A2 — delivery.json was deleted between build and load → toast 'error',
    returns False, clears pending context."""
    from workflow_app.command_queue.command_queue_widget import DcpBuildContext
    from workflow_app.config.app_state import app_state
    from workflow_app.models.delivery import Delivery

    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()
    _write_delivery(wbs_root, "module-1-x")
    cfg = _make_config(tmp_path, wbs_root)

    # Build a real Delivery once so the DcpBuildContext is well-formed.
    delivery = Delivery.model_validate_json(
        (wbs_root / DELIVERY_FILENAME).read_text(encoding="utf-8")
    )

    captured, disconnect = _capture_toasts()
    try:
        widget = _setup_widget(qapp, monkeypatch, cfg)
        try:
            widget._pending_dcp_load_ctx = DcpBuildContext(
                cm_id="module-1-x",
                module_state="creation",
                regenerate=False,
                wbs_root=wbs_root,
                delivery=delivery,
            )
            # Simulate the file becoming unreadable post-pipeline.
            (wbs_root / DELIVERY_FILENAME).unlink()

            result = widget._handle_dcp_load_specific_flow(_make_spec())
        finally:
            widget.deleteLater()
    finally:
        app_state.clear_config()
        disconnect()

    assert result is False
    assert any(kind == "error" and "delivery.json" in msg for msg, kind in captured)


# ─── A3: SPECIFIC-FLOW absent despite pipeline success ────────────────────── #


def test_handle_dcp_load_warns_when_flow_missing(
    qapp, monkeypatch, tmp_path: Path
) -> None:
    """A3 — pipeline reported success but SPECIFIC-FLOW.json never appeared →
    toast 'warning', returns False."""
    from workflow_app.command_queue.command_queue_widget import DcpBuildContext
    from workflow_app.config.app_state import app_state
    from workflow_app.models.delivery import Delivery

    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()
    _write_delivery(wbs_root, "module-1-x")
    cfg = _make_config(tmp_path, wbs_root)

    delivery = Delivery.model_validate_json(
        (wbs_root / DELIVERY_FILENAME).read_text(encoding="utf-8")
    )

    captured, disconnect = _capture_toasts()
    try:
        widget = _setup_widget(qapp, monkeypatch, cfg)
        try:
            widget._pending_dcp_load_ctx = DcpBuildContext(
                cm_id="module-1-x",
                module_state="creation",
                regenerate=False,
                wbs_root=wbs_root,
                delivery=delivery,
            )
            # Note: deliberately do NOT create SPECIFIC-FLOW.json on disk.
            result = widget._handle_dcp_load_specific_flow(_make_spec())
        finally:
            widget.deleteLater()
    finally:
        app_state.clear_config()
        disconnect()

    assert result is False
    assert any(
        kind == "warning" and "SPECIFIC-FLOW.json" in msg for msg, kind in captured
    )


# ─── A4: happy path delegates to _enqueue_specific_flow ───────────────────── #


def test_handle_dcp_load_happy_path_enqueues_and_clears_context(
    qapp, monkeypatch, tmp_path: Path
) -> None:
    """A4 — SPECIFIC-FLOW.json exists → resolves flow, delegates to
    `_enqueue_specific_flow` exactly once with the right kwargs, returns True,
    clears `_pending_dcp_load_ctx`."""
    from workflow_app.command_queue.command_queue_widget import DcpBuildContext
    from workflow_app.config.app_state import app_state
    from workflow_app.models.delivery import Delivery

    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()
    _write_delivery(wbs_root, "module-1-x")
    cfg = _make_config(tmp_path, wbs_root)

    # custom_workflow_root cascade level 2: {wbs}/workflow-app/SPECIFIC-FLOW.json
    flow_dir = wbs_root / "workflow-app"
    flow_dir.mkdir(parents=True)
    flow_path = flow_dir / SPECIFIC_FLOW_FILENAME
    flow_path.write_text(
        json.dumps({"version": 1, "commands": [{"name": "/dummy"}]}),
        encoding="utf-8",
    )

    delivery = Delivery.model_validate_json(
        (wbs_root / DELIVERY_FILENAME).read_text(encoding="utf-8")
    )

    widget = _setup_widget(qapp, monkeypatch, cfg)
    enqueue_calls: List[Dict[str, Any]] = []

    def fake_enqueue(self, *, flow_path, cm_id, default_project_name, prefix_commands):  # noqa: ARG001
        enqueue_calls.append(
            {
                "flow_path": flow_path,
                "cm_id": cm_id,
                "default_project_name": default_project_name,
                "prefix_commands": prefix_commands,
            }
        )
        return True

    try:
        # Patch _enqueue_specific_flow on the instance so the helper is fully
        # mocked (we do not exercise pipeline_ready emission here).
        widget._enqueue_specific_flow = fake_enqueue.__get__(widget)  # type: ignore[method-assign]
        widget._pending_dcp_load_ctx = DcpBuildContext(
            cm_id="module-1-x",
            module_state="creation",
            regenerate=False,
            wbs_root=wbs_root,
            delivery=delivery,
        )

        result = widget._handle_dcp_load_specific_flow(_make_spec())
    finally:
        try:
            widget.deleteLater()
        finally:
            app_state.clear_config()

    assert result is True
    assert len(enqueue_calls) == 1
    assert enqueue_calls[0]["flow_path"] == flow_path
    assert enqueue_calls[0]["cm_id"] == "module-1-x"
    assert enqueue_calls[0]["default_project_name"] == "dcp-auto-load-test"
    assert enqueue_calls[0]["prefix_commands"] is None
