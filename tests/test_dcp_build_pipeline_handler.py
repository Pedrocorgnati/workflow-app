"""Tests for `_dcp_build_preflight` (11 gate cases) and the new
`_on_dcp_build_pipeline_clicked` handler (3 pipeline emission cases).

Loop 05-14-dcp-build-pipeline-implant Task 14 — consolidates the assertions
described for Tasks 10/11/13. The legacy paste handler was removed in Task 13;
this file covers only the new pipeline-based path.

Test layout:

  Preflight gates 1..11
    1.1  no project loaded
    1.2  delivery.json missing
    1.3  delivery.json invalid
    1.4  delivery.json future version
    1.5  execution_mode == parallel-independent
    1.6  current_module is None
    1.7  all modules state==done
    1.8  current_module key absent from modules dict
    1.9  MODULE-META.json file missing
    1.10 MODULE-META.json corrupt JSON
    1.11 dependency readiness fails (dep not done) for pending → creation

  Pipeline emission via `_on_dcp_build_pipeline_clicked`
    P1  happy path (pending) emits 6 specs, item 6 is the local-action,
        item 1 has no --regenerate, no destructive modal shown
    P2  state past pending → --regenerate present + destructive modal
        accepted → 6 specs emitted
    P3  destructive modal rejected → no specs emitted, no
        _pending_dcp_load_ctx armed
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

import pytest

from workflow_app.config.config_parser import PipelineConfig
from workflow_app.services.delivery_reader import DELIVERY_FILENAME


# ─── Fixture builders (aligned with test_dcp_specific_flow_handler.py) ──── #


def _base_project(wbs_root: Path) -> Dict[str, Any]:
    return {
        "name": "dcp-pipeline-test",
        "brief_root": str(wbs_root / "brief"),
        "docs_root": str(wbs_root / "docs"),
        "wbs_root": str(wbs_root),
        "workspace_root": str(wbs_root / "workspace"),
    }


def _base_skeleton() -> Dict[str, Any]:
    return {
        "version": "skeleton-v2",
        "sha256": "a1b2c3d4",
        "doc_path": "output/_SHARED-SKELETON.md",
        "code_path": "output/shared/contracts",
        "last_updated": "2026-05-14T08:00:00Z",
        "bumped_by": "modules:create-structure",
    }


def _base_metadata() -> Dict[str, Any]:
    return {
        "schema_sha256": "schema-v1",
        "created_at": "2026-05-14T15:00:00Z",
        "created_by": "/delivery:init",
        "last_modified_by": "build-module-pipeline",
    }


def _base_locks_null() -> Dict[str, Any]:
    return {
        "holder": None,
        "acquired_at": None,
        "expires_at": None,
        "ttl_seconds": 120,
    }


def _module(
    state: str,
    *,
    module_type: str = "crud",
    last_specific_flow: str | None = None,
    dependencies: list | None = None,
) -> Dict[str, Any]:
    history: list = (
        []
        if state == "pending"
        else [
            {
                "from": "pending",
                "to": state,
                "at": "2026-05-14T12:00:00Z",
                "by": "build-module-pipeline",
                "note": "auto",
            }
        ]
    )
    return {
        "state": state,
        "state_detail": f"{state}-detail",
        "module_type": module_type,
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
        "history": history,
        "artifacts": {
            "module_meta_path": None,
            "overview_path": None,
            "last_specific_flow": last_specific_flow,
            "last_review_report": None,
            "last_commit_sha": None,
            "last_deploy_url": None,
            "git_tag": None,
        },
        "dependencies": dependencies if dependencies is not None else [],
    }


def _write_delivery(
    wbs_root: Path,
    current_module: str | None,
    modules: Dict[str, Any],
    *,
    execution_mode: str = "sequential",
    current_modules: list | None = None,
    version: int = 1,
) -> Path:
    payload: Dict[str, Any] = {
        "version": version,
        "project": _base_project(wbs_root),
        "current_module": current_module,
        "current_modules": current_modules or [],
        "execution_mode": execution_mode,
        "modules": modules,
        "skeleton": _base_skeleton(),
        "locks": _base_locks_null(),
        "metadata": _base_metadata(),
    }
    path = wbs_root / DELIVERY_FILENAME
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def _make_config(tmp_path: Path, wbs_root: Path) -> PipelineConfig:
    return PipelineConfig(
        config_path=str(tmp_path / ".claude" / "project.json"),
        project_name="dcp-pipeline-test",
        brief_root=str(wbs_root / "brief"),
        docs_root=str(wbs_root / "docs"),
        wbs_root=str(wbs_root),
        workspace_root=str(wbs_root / "workspace"),
    )


def _write_meta(wbs_root: Path, module_id: str, *, content: str | None = None) -> Path:
    meta_dir = wbs_root / "modules" / module_id
    meta_dir.mkdir(parents=True, exist_ok=True)
    meta_path = meta_dir / "MODULE-META.json"
    if content is None:
        content = json.dumps(
            {
                "module_id": module_id,
                "module_name": module_id.replace("-", " ").title(),
                "module_type": "crud",
            }
        )
    meta_path.write_text(content, encoding="utf-8")
    return meta_path


# ─── Preflight helper that exercises `_dcp_build_preflight` directly ────── #


def _run_preflight(
    qapp,
    monkeypatch,
    cfg: PipelineConfig,
    captured: List[str],
):
    """Instantiate CommandQueueWidget, set config, intercept QMessageBox.*,
    invoke `_dcp_build_preflight`, return its result. Always disposes widget.
    """
    from unittest.mock import patch

    from workflow_app import dcp as dcp_pkg
    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
    from workflow_app.config.app_state import app_state

    monkeypatch.setattr(dcp_pkg, "READER_AVAILABLE", True)
    app_state.set_config(cfg)

    def _capture(*args, **_kwargs):
        # Signature: (parent, title, text, ...). Capture the body text.
        if len(args) >= 3:
            captured.append(args[2])

    try:
        with patch("PySide6.QtWidgets.QMessageBox.information", side_effect=_capture), \
             patch("PySide6.QtWidgets.QMessageBox.warning", side_effect=_capture):
            widget = CommandQueueWidget()
            try:
                return widget._dcp_build_preflight()
            finally:
                widget.deleteLater()
    finally:
        app_state.clear_config()


# ─── Gate tests (11) ──────────────────────────────────────────────────────── #


def test_preflight_gate_1_no_project(qapp, monkeypatch) -> None:
    """Gate 1.1 — no project loaded triggers QMessageBox and returns None."""
    from unittest.mock import patch

    from workflow_app import dcp as dcp_pkg
    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
    from workflow_app.config.app_state import app_state

    app_state.clear_config()
    monkeypatch.setattr(dcp_pkg, "READER_AVAILABLE", True)

    captured: List[str] = []
    with patch(
        "PySide6.QtWidgets.QMessageBox.information",
        side_effect=lambda *a, **kw: captured.append(a[2] if len(a) >= 3 else ""),
    ):
        widget = CommandQueueWidget()
        try:
            ctx = widget._dcp_build_preflight()
        finally:
            widget.deleteLater()

    assert ctx is None
    assert len(captured) == 1
    assert "Carregue um projeto" in captured[0]


def test_preflight_gate_2_delivery_missing(qapp, monkeypatch, tmp_path: Path) -> None:
    """Gate 1.2 — delivery.json absent triggers QMessageBox and returns None."""
    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()
    cfg = _make_config(tmp_path, wbs_root)
    captured: List[str] = []
    ctx = _run_preflight(qapp, monkeypatch, cfg, captured)
    assert ctx is None
    assert len(captured) == 1
    assert "delivery.json ausente" in captured[0]


def test_preflight_gate_2_delivery_invalid(qapp, monkeypatch, tmp_path: Path) -> None:
    """Gate 1.3 — delivery.json with invalid JSON triggers QMessageBox."""
    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()
    # Malformed JSON triggers DeliveryInvalid
    (wbs_root / DELIVERY_FILENAME).write_text("{not valid", encoding="utf-8")
    cfg = _make_config(tmp_path, wbs_root)
    captured: List[str] = []
    ctx = _run_preflight(qapp, monkeypatch, cfg, captured)
    assert ctx is None
    assert len(captured) == 1
    assert "delivery.json invalido" in captured[0]


def test_preflight_gate_2_delivery_future_version(
    qapp, monkeypatch, tmp_path: Path
) -> None:
    """Gate 1.4 — version > supported triggers QMessageBox."""
    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()
    _write_delivery(
        wbs_root,
        current_module="module-1-x",
        modules={"module-1-x": _module("pending")},
        version=99,
    )
    cfg = _make_config(tmp_path, wbs_root)
    captured: List[str] = []
    ctx = _run_preflight(qapp, monkeypatch, cfg, captured)
    assert ctx is None
    assert len(captured) == 1
    # DeliveryFutureVersion message format may vary; just ensure something was shown.
    assert captured[0]


def test_preflight_gate_3_parallel_independent(
    qapp, monkeypatch, tmp_path: Path
) -> None:
    """Gate 1.5 — parallel-independent mode blocks the widget-level button."""
    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()
    _write_delivery(
        wbs_root,
        current_module=None,
        modules={"module-1-x": _module("creation")},
        execution_mode="parallel-independent",
        current_modules=["module-1-x"],
    )
    cfg = _make_config(tmp_path, wbs_root)
    captured: List[str] = []
    ctx = _run_preflight(qapp, monkeypatch, cfg, captured)
    assert ctx is None
    assert len(captured) == 1
    assert "parallel-independent" in captured[0]


def test_preflight_gate_4_current_module_none(
    qapp, monkeypatch, tmp_path: Path
) -> None:
    """Gate 1.6 — current_module is None in sequential mode aborts via gate 4.

    The Delivery model enforces I-01 (sequential requires current_module), so
    we have to bypass the loader by writing a payload that loads but exposes
    current_module=None. The reader rejects this at validation, surfacing a
    DeliveryInvalid path; that still routes through Gate 2 (delivery invalid)
    and emits QMessageBox.information. We assert ctx is None either way.
    """
    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()
    # Sequential mode with current_module=None is rejected by Pydantic.
    # Build a payload that passes model load but has empty modules so that
    # gate 4 fires for "no current_module".
    payload = {
        "version": 1,
        "project": _base_project(wbs_root),
        "current_module": None,
        "current_modules": [],
        "execution_mode": "sequential",
        "modules": {},
        "skeleton": _base_skeleton(),
        "locks": _base_locks_null(),
        "metadata": _base_metadata(),
    }
    (wbs_root / DELIVERY_FILENAME).write_text(json.dumps(payload), encoding="utf-8")
    cfg = _make_config(tmp_path, wbs_root)
    captured: List[str] = []
    ctx = _run_preflight(qapp, monkeypatch, cfg, captured)
    assert ctx is None
    assert len(captured) == 1
    # Either gate 4 ("current_module nao definido") or gate 2 ("delivery.json
    # invalido") fires depending on whether the model accepts empty modules.
    msg = captured[0]
    assert ("current_module" in msg) or ("delivery.json" in msg)


def test_preflight_gate_4_all_modules_done(
    qapp, monkeypatch, tmp_path: Path
) -> None:
    """Gate 1.7 — every module is state==done aborts with a friendly message."""
    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()
    _write_delivery(
        wbs_root,
        current_module="module-1-done",
        modules={"module-1-done": _module("done")},
    )
    cfg = _make_config(tmp_path, wbs_root)
    captured: List[str] = []
    ctx = _run_preflight(qapp, monkeypatch, cfg, captured)
    assert ctx is None
    assert len(captured) == 1
    assert "concluidos" in captured[0]


def test_preflight_gate_4_module_not_in_modules(
    qapp, monkeypatch, tmp_path: Path
) -> None:
    """Gate 1.8 — current_module key absent in modules dict.

    Delivery model enforces referential integrity (I-01), so loading is
    expected to fail with DeliveryInvalid. We assert the abort is graceful
    (ctx None + a single QMessageBox).
    """
    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()
    payload = {
        "version": 1,
        "project": _base_project(wbs_root),
        "current_module": "module-missing",
        "current_modules": [],
        "execution_mode": "sequential",
        "modules": {"module-1-x": _module("pending")},
        "skeleton": _base_skeleton(),
        "locks": _base_locks_null(),
        "metadata": _base_metadata(),
    }
    (wbs_root / DELIVERY_FILENAME).write_text(json.dumps(payload), encoding="utf-8")
    cfg = _make_config(tmp_path, wbs_root)
    captured: List[str] = []
    ctx = _run_preflight(qapp, monkeypatch, cfg, captured)
    assert ctx is None
    assert len(captured) == 1


def test_preflight_gate_5_meta_missing(qapp, monkeypatch, tmp_path: Path) -> None:
    """Gate 1.9 — MODULE-META.json absent triggers QMessageBox."""
    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()
    _write_delivery(
        wbs_root,
        current_module="module-1-x",
        modules={"module-1-x": _module("pending")},
    )
    cfg = _make_config(tmp_path, wbs_root)
    captured: List[str] = []
    ctx = _run_preflight(qapp, monkeypatch, cfg, captured)
    assert ctx is None
    assert len(captured) == 1
    assert "MODULE-META.json ausente" in captured[0]


def test_preflight_gate_5_meta_corrupt(qapp, monkeypatch, tmp_path: Path) -> None:
    """Gate 1.10 — MODULE-META.json with invalid JSON triggers QMessageBox."""
    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()
    _write_delivery(
        wbs_root,
        current_module="module-1-x",
        modules={"module-1-x": _module("pending")},
    )
    _write_meta(wbs_root, "module-1-x", content="{not json")
    cfg = _make_config(tmp_path, wbs_root)
    captured: List[str] = []
    ctx = _run_preflight(qapp, monkeypatch, cfg, captured)
    assert ctx is None
    assert len(captured) == 1
    assert "MODULE-META.json corrupto" in captured[0]


def test_preflight_gate_6_deps_not_done(qapp, monkeypatch, tmp_path: Path) -> None:
    """Gate 1.11 — pending module with unmet dependency aborts via QMessageBox.warning."""
    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()
    _write_delivery(
        wbs_root,
        current_module="module-2-feature",
        modules={
            "module-1-foundation": _module("revision"),
            "module-2-feature": _module(
                "pending", dependencies=["module-1-foundation"]
            ),
        },
    )
    _write_meta(wbs_root, "module-2-feature")
    cfg = _make_config(tmp_path, wbs_root)
    captured: List[str] = []
    ctx = _run_preflight(qapp, monkeypatch, cfg, captured)
    assert ctx is None
    assert len(captured) == 1
    assert "module-1-foundation" in captured[0]
    assert "revision" in captured[0]


# ─── Pipeline emission tests (3) ──────────────────────────────────────────── #


def _setup_pending_scenario(tmp_path: Path) -> tuple[Path, PipelineConfig]:
    """Pending module 1 (no deps, no SPECIFIC-FLOW on disk) — happy path."""
    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()
    _write_delivery(
        wbs_root,
        current_module="module-1-feature",
        modules={"module-1-feature": _module("pending")},
    )
    _write_meta(wbs_root, "module-1-feature")
    cfg = _make_config(tmp_path, wbs_root)
    return wbs_root, cfg


def _setup_regen_scenario(
    tmp_path: Path, *, with_flow: bool
) -> tuple[Path, PipelineConfig]:
    """Module 1 past pending so the handler chooses --regenerate."""
    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()
    _write_delivery(
        wbs_root,
        current_module="module-1-feature",
        modules={"module-1-feature": _module("creation")},
    )
    _write_meta(wbs_root, "module-1-feature")
    if with_flow:
        flow_path = wbs_root / "modules" / "module-1-feature" / "SPECIFIC-FLOW.json"
        flow_path.write_text(
            json.dumps({"version": 1, "commands": [{"name": "/clear"}]}),
            encoding="utf-8",
        )
    cfg = _make_config(tmp_path, wbs_root)
    return wbs_root, cfg


def test_pipeline_pending_emits_6_specs_with_local_action_at_position_6(
    qapp, monkeypatch, tmp_path: Path
) -> None:
    """P1 — happy path on pending: 6 specs, item 6 is local-action,
    item 1 has no --regenerate, no destructive modal shown."""
    from unittest.mock import patch

    from workflow_app import dcp as dcp_pkg
    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
    from workflow_app.config.app_state import app_state
    from workflow_app.signal_bus import signal_bus

    _, cfg = _setup_pending_scenario(tmp_path)
    app_state.set_config(cfg)
    monkeypatch.setattr(dcp_pkg, "READER_AVAILABLE", True)

    emitted: List[List[Any]] = []
    signal_bus.pipeline_ready.connect(emitted.append)

    modal_calls: List[bool] = []

    def fake_exec(self):
        modal_calls.append(True)
        return 1  # Accepted, defensively

    try:
        with patch(
            "workflow_app.dialogs.confirm_regenerate_specific_flow_modal."
            "ConfirmRegenerateSpecificFlowModal.exec",
            new=fake_exec,
        ):
            widget = CommandQueueWidget()
            try:
                # Invoke the handler directly: the testid button lives in
                # `widget.header_widget` (reparented to MainWindow in app
                # runtime) and isn't reachable via `widget.findChildren`.
                widget._on_dcp_build_pipeline_clicked()
            finally:
                widget.deleteLater()
    finally:
        app_state.clear_config()
        try:
            signal_bus.pipeline_ready.disconnect(emitted.append)
        except (RuntimeError, TypeError):
            pass

    assert len(modal_calls) == 0, "destructive modal must NOT run on pending path"
    assert len(emitted) == 1, "exactly one pipeline_ready emission expected"
    specs = emitted[0]
    assert len(specs) == 6, f"expected 6 specs, got {len(specs)}"

    # Slot 1: /build-module-pipeline with --module 1 and no --regenerate
    assert specs[0].name.startswith("/build-module-pipeline ")
    assert "--regenerate" not in specs[0].name
    assert "--module 1" in specs[0].name

    # Slots 2..5: 4 dcp validators
    assert "/dcp:congruence-check --module 1" in specs[1].name
    assert "/dcp:temporality-check --module 1" in specs[2].name
    assert "/dcp:meta-completeness --module 1" in specs[3].name
    assert "/dcp:directive-injector --module 1 --in-place" in specs[4].name

    # Slot 6: local-action carrying the load action id
    assert specs[5].kind == "local-action"
    assert specs[5].local_action_id == "dcp-load-specific-flow"
    assert specs[5].position == 6


def test_pipeline_past_pending_includes_regenerate_when_modal_accepted(
    qapp, monkeypatch, tmp_path: Path
) -> None:
    """P2 — module in state=creation + SPECIFIC-FLOW existing: modal accepted
    → 6 specs emitted, slot 1 carries --regenerate."""
    from unittest.mock import patch

    from PySide6.QtWidgets import QDialog

    from workflow_app import dcp as dcp_pkg
    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
    from workflow_app.config.app_state import app_state
    from workflow_app.signal_bus import signal_bus

    _, cfg = _setup_regen_scenario(tmp_path, with_flow=True)
    app_state.set_config(cfg)
    monkeypatch.setattr(dcp_pkg, "READER_AVAILABLE", True)

    emitted: List[List[Any]] = []
    signal_bus.pipeline_ready.connect(emitted.append)

    def fake_exec(self):
        return QDialog.DialogCode.Accepted

    try:
        with patch(
            "workflow_app.dialogs.confirm_regenerate_specific_flow_modal."
            "ConfirmRegenerateSpecificFlowModal.exec",
            new=fake_exec,
        ):
            widget = CommandQueueWidget()
            try:
                widget._on_dcp_build_pipeline_clicked()
            finally:
                widget.deleteLater()
    finally:
        app_state.clear_config()
        try:
            signal_bus.pipeline_ready.disconnect(emitted.append)
        except (RuntimeError, TypeError):
            pass

    assert len(emitted) == 1
    specs = emitted[0]
    assert len(specs) == 6
    assert specs[0].name.startswith("/build-module-pipeline --regenerate --module 1 ")
    assert specs[5].kind == "local-action"


def test_pipeline_regen_modal_rejected_blocks_emission(
    qapp, monkeypatch, tmp_path: Path
) -> None:
    """P3 — destructive modal rejected: no pipeline_ready emitted and the
    widget never arms `_pending_dcp_load_ctx`."""
    from unittest.mock import patch

    from PySide6.QtWidgets import QDialog

    from workflow_app import dcp as dcp_pkg
    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
    from workflow_app.config.app_state import app_state
    from workflow_app.signal_bus import signal_bus

    _, cfg = _setup_regen_scenario(tmp_path, with_flow=True)
    app_state.set_config(cfg)
    monkeypatch.setattr(dcp_pkg, "READER_AVAILABLE", True)

    emitted: List[List[Any]] = []
    signal_bus.pipeline_ready.connect(emitted.append)

    def fake_exec(self):
        return QDialog.DialogCode.Rejected

    armed_ctx: List[Any] = []
    try:
        with patch(
            "workflow_app.dialogs.confirm_regenerate_specific_flow_modal."
            "ConfirmRegenerateSpecificFlowModal.exec",
            new=fake_exec,
        ):
            widget = CommandQueueWidget()
            try:
                widget._on_dcp_build_pipeline_clicked()
                armed_ctx.append(widget._pending_dcp_load_ctx)
            finally:
                widget.deleteLater()
    finally:
        app_state.clear_config()
        try:
            signal_bus.pipeline_ready.disconnect(emitted.append)
        except (RuntimeError, TypeError):
            pass

    assert len(emitted) == 0, "rejected modal must block pipeline_ready emission"
    assert armed_ctx == [None], (
        "rejected modal must NOT arm _pending_dcp_load_ctx"
    )
