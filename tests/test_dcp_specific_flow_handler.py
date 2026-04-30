"""Tests for T-050 DCP: Specific-Flow handler + button gating.

Covers:
- `workflow_app.dcp.specific_flow_handler.resolve()` pure logic across the
  six branches documented in the module docstring.
- `workflow_app.dcp.specific_flow_handler.build_paste_command_only()` literal.
- CommandQueueWidget init-time gating when `READER_AVAILABLE` is false.

Spec: `scheduled-updates/refactor-workflow-sytemforge/TASK-050-workflow-app-dcp-cleanup.md`
lines 89, 107-119 (literal messages, disabled-at-init requirement).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict

import pytest

from workflow_app.config.config_parser import PipelineConfig
from workflow_app.dcp.specific_flow_handler import (
    SpecificFlowAction,
    build_paste_command_only,
    resolve,
)
from workflow_app.services.delivery_reader import DELIVERY_FILENAME, DeliveryReader


# ─── Fixture builders (minimal, aligned with test_delivery_reader.py) ─────── #


def _base_project(wbs_root: Path) -> Dict[str, Any]:
    return {
        "name": "t050-test",
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
        "last_updated": "2026-04-12T08:00:00Z",
        "bumped_by": "modules:create-structure",
    }


def _base_metadata() -> Dict[str, Any]:
    return {
        "schema_sha256": "schema-v1",
        "created_at": "2026-04-11T15:00:00Z",
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
) -> Dict[str, Any]:
    history: list = (
        []
        if state == "pending"
        else [
            {
                "from": "pending",
                "to": state,
                "at": "2026-04-12T12:00:00Z",
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
        "started_at": "2026-04-12T12:00:00Z",
        "last_transition": "2026-04-12T12:00:00Z",
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
        "dependencies": [],
    }


def _write_delivery(wbs_root: Path, current_module: str | None, modules: Dict[str, Any]) -> Path:
    payload: Dict[str, Any] = {
        "version": 1,
        "project": _base_project(wbs_root),
        "current_module": current_module,
        "execution_mode": "sequential",
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
        project_name="t050-test",
        brief_root=str(wbs_root / "brief"),
        docs_root=str(wbs_root / "docs"),
        wbs_root=str(wbs_root),
        workspace_root=str(wbs_root / "workspace"),
    )


# ─── Pure handler tests ──────────────────────────────────────────────────── #


def test_build_paste_command_only_literal() -> None:
    assert build_paste_command_only() == "/build-module-pipeline"


def test_resolve_no_project_returns_spec_literal_message() -> None:
    action = resolve(None)
    assert isinstance(action, SpecificFlowAction)
    assert action.command is None
    assert action.reason == (
        "Carregue um projeto (pill superior) antes de gerar pipeline DCP."
    )


def test_resolve_delivery_missing() -> None:
    tmp = Path.cwd()  # any dir without delivery.json at cwd/_nonexistent_wbs/
    with pytest.MonkeyPatch.context() as mp:
        mp.chdir(tmp)
        cfg = PipelineConfig(
            config_path=str(tmp / ".claude" / "project.json"),
            project_name="missing",
            brief_root="b",
            docs_root="d",
            wbs_root="_nonexistent_wbs_t050",
            workspace_root="ws",
        )
        action = resolve(cfg, reader=DeliveryReader())
    assert action.command is None
    assert "delivery.json ausente" in action.reason


def test_resolve_module_pending_paste_build_module_pipeline(tmp_path: Path) -> None:
    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()
    _write_delivery(
        wbs_root,
        current_module="module-1-dashboard",
        modules={
            "module-1-dashboard": _module("pending", module_type="dashboard"),
        },
    )
    cfg = _make_config(tmp_path, wbs_root)

    action = resolve(cfg, reader=DeliveryReader())

    assert action.command == "/build-module-pipeline module-1-dashboard"
    assert action.reason == "novo pipeline"


def test_resolve_module_with_last_specific_flow_rehydrate(tmp_path: Path) -> None:
    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()
    _write_delivery(
        wbs_root,
        current_module="module-1-dashboard",
        modules={
            "module-1-dashboard": _module(
                "creation",
                module_type="dashboard",
                last_specific_flow="workflow-app/SPECIFIC-FLOW.json",
            ),
        },
    )
    cfg = _make_config(tmp_path, wbs_root)

    action = resolve(cfg, reader=DeliveryReader())

    assert action.command == "/build-module-pipeline --rehydrate module-1-dashboard"
    assert action.reason == "reidratar pipeline existente"


def test_resolve_current_module_in_done_state_returns_no_active_module(
    tmp_path: Path,
) -> None:
    """Spec §107: 'current_module is None OR all modules done' → same message."""
    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()
    _write_delivery(
        wbs_root,
        current_module="module-1-dashboard",
        modules={
            "module-1-dashboard": _module("done", module_type="dashboard"),
        },
    )
    cfg = _make_config(tmp_path, wbs_root)

    action = resolve(cfg, reader=DeliveryReader())

    assert action.command is None
    assert action.reason == (
        "Nenhum modulo ativo. Use [DCP: Build Module Pipeline] primeiro"
    )


def test_resolve_all_modules_done_returns_no_active_module(tmp_path: Path) -> None:
    """Spec §107: when every module is done, treat as 'no active module'."""
    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()
    _write_delivery(
        wbs_root,
        current_module="module-2-crud",
        modules={
            "module-1-dashboard": _module("done", module_type="dashboard"),
            "module-2-crud": _module("done", module_type="crud"),
        },
    )
    cfg = _make_config(tmp_path, wbs_root)

    action = resolve(cfg, reader=DeliveryReader())

    assert action.command is None
    assert action.reason == (
        "Nenhum modulo ativo. Use [DCP: Build Module Pipeline] primeiro"
    )


def test_resolve_delivery_invalid(tmp_path: Path) -> None:
    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()
    (wbs_root / DELIVERY_FILENAME).write_text("{not valid json", encoding="utf-8")
    cfg = _make_config(tmp_path, wbs_root)

    action = resolve(cfg, reader=DeliveryReader())

    assert action.command is None
    assert "delivery.json invalido" in action.reason
    assert "/delivery:validate" in action.reason


def test_resolve_delivery_future_version(tmp_path: Path) -> None:
    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()
    payload: Dict[str, Any] = {
        "version": 999,
        "project": _base_project(wbs_root),
        "current_module": None,
        "execution_mode": "sequential",
        "modules": {},
        "skeleton": _base_skeleton(),
        "locks": _base_locks_null(),
        "metadata": _base_metadata(),
    }
    (wbs_root / DELIVERY_FILENAME).write_text(json.dumps(payload), encoding="utf-8")
    cfg = _make_config(tmp_path, wbs_root)

    action = resolve(cfg, reader=DeliveryReader())

    assert action.command is None
    assert action.reason  # non-empty message from DeliveryFutureVersion


def test_resolve_no_current_module(tmp_path: Path) -> None:
    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()
    _write_delivery(
        wbs_root,
        current_module=None,
        modules={
            "module-0-foundations": _module("done", module_type="foundations"),
        },
    )
    cfg = _make_config(tmp_path, wbs_root)

    action = resolve(cfg, reader=DeliveryReader())

    assert action.command is None
    assert action.reason == (
        "Nenhum modulo ativo. Use [DCP: Build Module Pipeline] primeiro"
    )


# ─── Qt widget gating test ────────────────────────────────────────────────── #


def test_dcp_specific_flow_button_disabled_when_reader_missing(
    qapp, monkeypatch
) -> None:
    """When `workflow_app.dcp.READER_AVAILABLE` is False, the button must be
    disabled at widget init time with the spec-mandated tooltip."""
    from PySide6.QtWidgets import QPushButton

    from workflow_app import dcp as dcp_pkg
    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget

    monkeypatch.setattr(dcp_pkg, "READER_AVAILABLE", False)

    widget = CommandQueueWidget()
    try:
        target = None
        for btn in widget.findChildren(QPushButton):
            if btn.property("testid") == "queue-btn-dcp-specific-flow":
                target = btn
                break
        assert target is not None, "queue-btn-dcp-specific-flow not found"
        assert target.isEnabled() is False
        assert target.toolTip() == "Requer T-035 (reader)"
    finally:
        widget.deleteLater()


def test_modules_creation_button_enabled(qapp) -> None:
    """`[Modules (Creation)]` must be enabled at widget init time — it covers
    fase A do canonical loop (creates WBS structure + MODULE-META + delivery.json),
    a hard pre-requisite of `/build-module-pipeline`."""
    from PySide6.QtWidgets import QPushButton

    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget

    widget = CommandQueueWidget()
    try:
        target = None
        for btn in widget.findChildren(QPushButton):
            if btn.property("testid") == "queue-btn-modules":
                target = btn
                break
        assert target is not None, "queue-btn-modules not found"
        assert target.isEnabled() is True
        assert "Fase A" in target.toolTip()
    finally:
        widget.deleteLater()
