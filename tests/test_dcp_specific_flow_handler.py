"""Tests for T-050 DCP: Specific-Flow handler + button gating.

Covers:
- `workflow_app.dcp.specific_flow_handler.resolve()` pure logic across the
  six branches documented in the module docstring.
- `workflow_app.dcp.specific_flow_handler.build_paste_command_only()` literal.
- CommandQueueWidget init-time gating when `READER_AVAILABLE` is false.

Spec T-050 (refactor concluido) — comportamento consolidado em
ai-forge/workflow-app/docs/refactor/T-050/README.md.
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
    dependencies: list | None = None,
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
            "last_review_report": None,
            "last_commit_sha": None,
            "last_deploy_url": None,
            "git_tag": None,
        },
        # Test-only sentinel — stripped by _write_delivery before serialisation
        # (v2 ModuleArtifacts has extra="forbid"). When non-None, _write_delivery
        # also drops a placeholder SPECIFIC-FLOW.json at the canonical level-0
        # path so the resolver-based regenerate path fires in the production
        # code (specific_flow_handler.resolve).
        "_test_specific_flow_marker": last_specific_flow,
        "dependencies": dependencies if dependencies is not None else [],
    }


def _write_delivery(wbs_root: Path, current_module: str | None, modules: Dict[str, Any]) -> Path:
    # v2 schema: ModuleArtifacts has extra="forbid"; drop v1-only keys callers
    # may have inherited from older fixture helpers. When the test-only
    # `_test_specific_flow_marker` is non-None, drop a placeholder file at the
    # canonical level-0 path (wbs/modules/{id}/SPECIFIC-FLOW.json) so the
    # resolver-based regenerate path fires in production code.
    for _mid, _mod in modules.items():
        if not isinstance(_mod, dict):
            continue
        _arts = _mod.get("artifacts")
        if isinstance(_arts, dict):
            _arts.pop("last_specific_flow", None)
            _arts.pop("last_specific_flow_sha256", None)
        marker = _mod.pop("_test_specific_flow_marker", None)
        if marker:
            flow_path = wbs_root / "modules" / _mid / "SPECIFIC-FLOW.json"
            flow_path.parent.mkdir(parents=True, exist_ok=True)
            if not flow_path.exists():
                flow_path.write_text(
                    json.dumps({"version": 1, "commands": []}), encoding="utf-8"
                )
    payload: Dict[str, Any] = {
        "version": 2,
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


def test_build_paste_command_only_config_without_module(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path, tmp_path / "wbs")
    cmd = build_paste_command_only(config=cfg)
    assert cmd.startswith("/build-module-pipeline ")
    assert "--module" not in cmd
    assert ".claude" in cmd


def test_build_paste_command_only_config_with_module(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path, tmp_path / "wbs")
    cmd = build_paste_command_only(config=cfg, current_module="module-2-payments")
    assert "--module 2" in cmd
    assert ".claude" in cmd


def test_build_paste_command_only_regenerate(tmp_path: Path) -> None:
    cfg = _make_config(tmp_path, tmp_path / "wbs")
    cmd = build_paste_command_only(
        config=cfg, current_module="module-2-payments", regenerate=True
    )
    assert cmd.startswith("/build-module-pipeline --regenerate --module 2 ")
    assert ".claude" in cmd


def test_build_paste_command_only_letter_suffix_module(tmp_path: Path) -> None:
    """Module ids like 'module-6a-aba3-engine' must extract '6a' alias."""
    cfg = _make_config(tmp_path, tmp_path / "wbs")
    cmd = build_paste_command_only(config=cfg, current_module="module-6a-aba3-engine")
    assert "--module 6a" in cmd


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

    # Canonical CLI contract: --module {N} {config_path} (no --rehydrate, no
    # bare module-id positional). Allow partial match because tmp_path varies.
    assert action.command is not None
    assert action.command.startswith("/build-module-pipeline --module 1 ")
    assert action.command.endswith("project.json")
    assert action.reason == "novo pipeline"


def test_resolve_module_with_last_specific_flow_regenerate(tmp_path: Path) -> None:
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

    # Canonical CLI contract for re-emit: --regenerate --module {N} {config_path}
    # (T-013 implements --regenerate, never --rehydrate).
    assert action.command is not None
    assert action.command.startswith(
        "/build-module-pipeline --regenerate --module 1 "
    )
    assert action.command.endswith("project.json")
    assert action.reason == "regenerar SPECIFIC-FLOW existente"


def test_resolve_current_module_in_done_state_returns_no_active_module(
    tmp_path: Path,
) -> None:
    """Quando current_module esta done e nao ha proximo modulo, retorna no_active_module_msg."""
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


def test_resolve_current_module_done_advances_to_next_pending(tmp_path: Path) -> None:
    """Bug fix: quando current_module esta done mas ha modulo seguinte pending,
    deve retornar comando para o proximo modulo (nao bloquear)."""
    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()
    _write_delivery(
        wbs_root,
        current_module="module-1-dashboard",
        modules={
            "module-1-dashboard": _module("done", module_type="dashboard"),
            "module-2-crud": _module("pending", module_type="crud"),
        },
    )
    cfg = _make_config(tmp_path, wbs_root)

    action = resolve(cfg, reader=DeliveryReader())

    assert action.command is not None
    assert "--module 2" in action.command
    assert action.reason == "novo pipeline"


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
        for btn in widget.header_widget.findChildren(QPushButton):
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
        for btn in widget.header_widget.findChildren(QPushButton):
            if btn.property("testid") == "queue-btn-modules":
                target = btn
                break
        assert target is not None, "queue-btn-modules not found"
        assert target.isEnabled() is True
        assert "Fase A" in target.toolTip()
    finally:
        widget.deleteLater()


# ─── Gate 6: dependency readiness in queue-btn-dcp-build ─────────────────── #


def test_dcp_build_gate6_blocks_when_dep_not_done(
    qapp, monkeypatch, tmp_path: Path
) -> None:
    """Gate 6: `queue-btn-dcp-build` must show QMessageBox.warning (not paste)
    when the pending current_module has unmet dependencies (state != done).

    Reproduces the recurring failure: module-N pending with dep in 'revision'
    → button pasted command → CLI exited 1 → user had to ask for fix.
    """
    from unittest.mock import patch

    from PySide6.QtWidgets import QPushButton

    from workflow_app import dcp as dcp_pkg
    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
    from workflow_app.config.app_state import app_state

    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()

    # module-1-foundation in revision (not done), module-2-feature pending + depends on it
    _write_delivery(
        wbs_root,
        current_module="module-2-feature",
        modules={
            "module-1-foundation": _module("revision"),
            "module-2-feature": _module("pending", dependencies=["module-1-foundation"]),
        },
    )

    # MODULE-META.json for current module
    meta_dir = wbs_root / "modules" / "module-2-feature"
    meta_dir.mkdir(parents=True)
    (meta_dir / "MODULE-META.json").write_text(
        json.dumps({
            "module_id": "module-2-feature",
            "module_name": "Feature",
            "module_type": "crud",
            "dependencies": {"modules": ["module-1-foundation"]},
        }),
        encoding="utf-8",
    )

    cfg = _make_config(tmp_path, wbs_root)
    app_state.set_config(cfg)
    monkeypatch.setattr(dcp_pkg, "READER_AVAILABLE", True)

    pasted: list[str] = []
    from workflow_app.signal_bus import signal_bus
    signal_bus.paste_text_in_terminal.connect(pasted.append)

    warned: list[str] = []
    with patch(
        "PySide6.QtWidgets.QMessageBox.warning",
        side_effect=lambda *a, **kw: warned.append(a[2]),
    ):
        widget = CommandQueueWidget()
        try:
            btn = next(
                (b for b in widget.header_widget.findChildren(QPushButton)
                 if b.property("testid") == "queue-btn-dcp-build"),
                None,
            )
            assert btn is not None, "queue-btn-dcp-build not found"
            btn.click()
        finally:
            widget.deleteLater()
            app_state.clear_config()

    assert len(pasted) == 0, "button must NOT paste when deps are unmet"
    assert len(warned) == 1, "button must show QMessageBox.warning"
    assert "module-1-foundation" in warned[0]
    assert "revision" in warned[0]


def test_dcp_build_gate6_allows_when_all_deps_done(
    qapp, monkeypatch, tmp_path: Path
) -> None:
    """Gate 6 must NOT block when all dependencies are done — happy path."""
    from unittest.mock import patch

    from PySide6.QtWidgets import QPushButton

    from workflow_app import dcp as dcp_pkg
    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
    from workflow_app.config.app_state import app_state

    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()

    _write_delivery(
        wbs_root,
        current_module="module-2-feature",
        modules={
            "module-1-foundation": _module("done"),
            "module-2-feature": _module("pending", dependencies=["module-1-foundation"]),
        },
    )

    meta_dir = wbs_root / "modules" / "module-2-feature"
    meta_dir.mkdir(parents=True)
    (meta_dir / "MODULE-META.json").write_text(
        json.dumps({
            "module_id": "module-2-feature",
            "module_name": "Feature",
            "module_type": "crud",
            "dependencies": {"modules": ["module-1-foundation"]},
        }),
        encoding="utf-8",
    )

    cfg = _make_config(tmp_path, wbs_root)
    app_state.set_config(cfg)
    monkeypatch.setattr(dcp_pkg, "READER_AVAILABLE", True)

    # B-dcp button now enqueues the 6-step pipeline via pipeline_ready
    # instead of pasting a single command in the terminal (DCP-COMMAND-MATRIX
    # rollout). Listen for pipeline_ready, filter to the B-dcp batch.
    emitted: list[list[Any]] = []
    from workflow_app.signal_bus import signal_bus
    signal_bus.pipeline_ready.connect(emitted.append)

    warned: list[str] = []
    with patch(
        "PySide6.QtWidgets.QMessageBox.warning",
        side_effect=lambda *a, **kw: warned.append(a[2]),
    ):
        widget = CommandQueueWidget()
        try:
            btn = next(
                (b for b in widget.header_widget.findChildren(QPushButton)
                 if b.property("testid") == "queue-btn-dcp-build"),
                None,
            )
            assert btn is not None, "queue-btn-dcp-build not found"
            btn.click()
        finally:
            try:
                signal_bus.pipeline_ready.disconnect(emitted.append)
            except (RuntimeError, TypeError):
                pass
            widget.deleteLater()
            app_state.clear_config()

    assert len(warned) == 0, "must not warn when all deps are done"
    handler_batches = [
        batch for batch in emitted
        if batch and any(s.name.startswith("/build-module-pipeline") for s in batch)
    ]
    assert len(handler_batches) == 1, "must enqueue B-dcp pipeline when all deps are done"
    build_spec = next(
        s for s in handler_batches[0]
        if s.name.startswith("/build-module-pipeline")
    )
    assert "--module 2" in build_spec.name


# ─── Onda 1: destructive guard for --regenerate path ────────────────────────── #


def _setup_dcp_build_regen_scenario(
    tmp_path: Path, *, with_specific_flow: bool
) -> tuple[Path, Path]:
    """Helper: scenario where current_module is past pending so the click path
    chooses --regenerate. Optionally writes a SPECIFIC-FLOW.json on disk to
    trigger the destructive confirmation modal.
    """
    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()

    _write_delivery(
        wbs_root,
        current_module="module-1-dashboard",
        modules={
            "module-1-dashboard": _module("creation", module_type="dashboard"),
        },
    )

    meta_dir = wbs_root / "modules" / "module-1-dashboard"
    meta_dir.mkdir(parents=True)
    (meta_dir / "MODULE-META.json").write_text(
        json.dumps({
            "module_id": "module-1-dashboard",
            "module_name": "Dashboard",
            "module_type": "dashboard",
        }),
        encoding="utf-8",
    )

    flow_path = meta_dir / "SPECIFIC-FLOW.json"
    if with_specific_flow:
        flow_path.write_text(
            json.dumps({"version": 1, "commands": [{"name": "/clear"}]}),
            encoding="utf-8",
        )
    return wbs_root, flow_path


def test_dcp_build_regen_with_existing_flow_blocks_paste_when_modal_rejected(
    qapp, monkeypatch, tmp_path: Path
) -> None:
    """Regen path + SPECIFIC-FLOW.json existing → modal must run; reject = no paste."""
    from unittest.mock import patch

    from PySide6.QtWidgets import QDialog, QPushButton

    from workflow_app import dcp as dcp_pkg
    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
    from workflow_app.config.app_state import app_state

    wbs_root, _ = _setup_dcp_build_regen_scenario(tmp_path, with_specific_flow=True)
    cfg = _make_config(tmp_path, wbs_root)
    app_state.set_config(cfg)
    monkeypatch.setattr(dcp_pkg, "READER_AVAILABLE", True)

    pasted: list[str] = []
    from workflow_app.signal_bus import signal_bus
    signal_bus.paste_text_in_terminal.connect(pasted.append)

    modal_calls: list[bool] = []

    def fake_exec(self):
        modal_calls.append(True)
        return QDialog.DialogCode.Rejected

    with patch(
        "workflow_app.dialogs.confirm_regenerate_specific_flow_modal."
        "ConfirmRegenerateSpecificFlowModal.exec",
        new=fake_exec,
    ):
        widget = CommandQueueWidget()
        try:
            btn = next(
                (b for b in widget.header_widget.findChildren(QPushButton)
                 if b.property("testid") == "queue-btn-dcp-build"),
                None,
            )
            assert btn is not None, "queue-btn-dcp-build not found"
            btn.click()
        finally:
            widget.deleteLater()
            app_state.clear_config()

    assert len(modal_calls) == 1, "destructive modal must run on regen path"
    assert len(pasted) == 0, "rejected modal must block paste"


def test_dcp_build_regen_with_existing_flow_pastes_when_modal_accepted(
    qapp, monkeypatch, tmp_path: Path
) -> None:
    """Regen path + SPECIFIC-FLOW.json existing → modal accepted = paste with --regenerate."""
    from unittest.mock import patch

    from PySide6.QtWidgets import QDialog, QPushButton

    from workflow_app import dcp as dcp_pkg
    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
    from workflow_app.config.app_state import app_state

    wbs_root, _ = _setup_dcp_build_regen_scenario(tmp_path, with_specific_flow=True)
    cfg = _make_config(tmp_path, wbs_root)
    app_state.set_config(cfg)
    monkeypatch.setattr(dcp_pkg, "READER_AVAILABLE", True)

    # B-dcp button now enqueues via pipeline_ready instead of pasting.
    emitted: list[list[Any]] = []
    from workflow_app.signal_bus import signal_bus
    signal_bus.pipeline_ready.connect(emitted.append)

    def fake_exec(self):
        return QDialog.DialogCode.Accepted

    with patch(
        "workflow_app.dialogs.confirm_regenerate_specific_flow_modal."
        "ConfirmRegenerateSpecificFlowModal.exec",
        new=fake_exec,
    ):
        widget = CommandQueueWidget()
        try:
            btn = next(
                (b for b in widget.header_widget.findChildren(QPushButton)
                 if b.property("testid") == "queue-btn-dcp-build"),
                None,
            )
            assert btn is not None, "queue-btn-dcp-build not found"
            btn.click()
        finally:
            try:
                signal_bus.pipeline_ready.disconnect(emitted.append)
            except (RuntimeError, TypeError):
                pass
            widget.deleteLater()
            app_state.clear_config()

    handler_batches = [
        batch for batch in emitted
        if batch and any(s.name.startswith("/build-module-pipeline") for s in batch)
    ]
    assert len(handler_batches) == 1, "accepted modal must allow B-dcp pipeline emission"
    build_spec = next(
        s for s in handler_batches[0]
        if s.name.startswith("/build-module-pipeline")
    )
    assert "--regenerate" in build_spec.name
    assert "--module 1" in build_spec.name


def test_dcp_build_regen_without_existing_flow_skips_modal(
    qapp, monkeypatch, tmp_path: Path
) -> None:
    """Regen path BUT no SPECIFIC-FLOW.json on disk → no modal, paste happens."""
    from unittest.mock import patch

    from PySide6.QtWidgets import QPushButton

    from workflow_app import dcp as dcp_pkg
    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
    from workflow_app.config.app_state import app_state

    wbs_root, _ = _setup_dcp_build_regen_scenario(tmp_path, with_specific_flow=False)
    cfg = _make_config(tmp_path, wbs_root)
    app_state.set_config(cfg)
    monkeypatch.setattr(dcp_pkg, "READER_AVAILABLE", True)

    # B-dcp button now enqueues via pipeline_ready instead of pasting.
    emitted: list[list[Any]] = []
    from workflow_app.signal_bus import signal_bus
    signal_bus.pipeline_ready.connect(emitted.append)

    modal_calls: list[bool] = []

    def fake_exec(self):
        modal_calls.append(True)
        return 0

    with patch(
        "workflow_app.dialogs.confirm_regenerate_specific_flow_modal."
        "ConfirmRegenerateSpecificFlowModal.exec",
        new=fake_exec,
    ):
        widget = CommandQueueWidget()
        try:
            btn = next(
                (b for b in widget.header_widget.findChildren(QPushButton)
                 if b.property("testid") == "queue-btn-dcp-build"),
                None,
            )
            assert btn is not None, "queue-btn-dcp-build not found"
            btn.click()
        finally:
            try:
                signal_bus.pipeline_ready.disconnect(emitted.append)
            except (RuntimeError, TypeError):
                pass
            widget.deleteLater()
            app_state.clear_config()

    assert len(modal_calls) == 0, "modal must NOT run when SPECIFIC-FLOW.json missing"
    handler_batches = [
        batch for batch in emitted
        if batch and any(s.name.startswith("/build-module-pipeline") for s in batch)
    ]
    assert len(handler_batches) == 1, "pipeline must emit on regen path with no existing file"
    build_spec = next(
        s for s in handler_batches[0]
        if s.name.startswith("/build-module-pipeline")
    )
    assert "--regenerate" in build_spec.name


# ─── Onda 4: overrides.skipped persistence + filter ────────────────────────── #


def _setup_dcp_specific_flow_scenario(
    tmp_path: Path, *, commands: list[dict], overrides: dict | None = None
) -> tuple[Path, Path]:
    """Build a delivery + SPECIFIC-FLOW pair so the [DCP: Specific-Flow]
    button has something to load."""
    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()
    flow_path = wbs_root / "modules" / "module-1-dashboard" / "SPECIFIC-FLOW.json"
    flow_path.parent.mkdir(parents=True)

    _write_delivery(
        wbs_root,
        current_module="module-1-dashboard",
        modules={
            "module-1-dashboard": _module(
                "creation",
                module_type="dashboard",
                last_specific_flow=str(flow_path),
            ),
        },
    )

    flow = {
        "version": "2.0",
        "project": "t050-test",
        "scope": "module",
        "scope_module": {
            "module_id": "module-1-dashboard",
            "module_name": "Dashboard",
            "module_type": "dashboard",
            "profile": "full",
        },
        "generated_at": "2026-05-10T20:00:00Z",
        "pipeline_range": {},
        "config": {},
        "commands": commands,
    }
    if overrides is not None:
        flow["overrides"] = overrides
    flow_path.write_text(
        json.dumps(flow, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return wbs_root, flow_path


def test_dcp_specific_flow_filters_overrides_skipped(
    qapp, monkeypatch, tmp_path: Path
) -> None:
    """Reader must drop commands whose name appears in overrides.skipped[]."""
    from PySide6.QtWidgets import QPushButton

    from workflow_app import dcp as dcp_pkg
    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
    from workflow_app.config.app_state import app_state

    commands = [
        {"name": "/clear", "model": "sonnet", "effort": "medium", "phase": "FASE_A_CREATION"},
        {"name": "/front-end-build x", "model": "opus", "effort": "high", "phase": "FASE_B_BUILD"},
        {"name": "/back-end-build x", "model": "opus", "effort": "high", "phase": "FASE_B_BUILD"},
    ]
    overrides = {"skipped": ["/front-end-build x"]}
    wbs_root, _ = _setup_dcp_specific_flow_scenario(
        tmp_path, commands=commands, overrides=overrides,
    )
    cfg = _make_config(tmp_path, wbs_root)
    app_state.set_config(cfg)
    monkeypatch.setattr(dcp_pkg, "READER_AVAILABLE", True)

    captured: list[list] = []
    from workflow_app.signal_bus import signal_bus
    signal_bus.pipeline_ready.connect(captured.append)

    widget = CommandQueueWidget()
    try:
        btn = next(
            (b for b in widget.header_widget.findChildren(QPushButton)
             if b.property("testid") == "queue-btn-dcp-specific-flow"),
            None,
        )
        assert btn is not None
        btn.click()
    finally:
        widget.deleteLater()
        app_state.clear_config()

    assert len(captured) == 1, "pipeline_ready must fire once"
    names = [s.name for s in captured[0]]
    assert "/front-end-build x" not in names, "skipped command must be filtered"
    assert "/clear" in names and "/back-end-build x" in names, "non-skipped must remain"


def test_dcp_specific_flow_remove_persists_to_overrides_skipped(
    qapp, monkeypatch, tmp_path: Path
) -> None:
    """Removing a queue item via _on_remove_requested must append to
    overrides.skipped[] of the source SPECIFIC-FLOW.json on disk."""
    from PySide6.QtWidgets import QPushButton

    from workflow_app import dcp as dcp_pkg
    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
    from workflow_app.config.app_state import app_state

    commands = [
        {"name": "/clear", "model": "sonnet", "effort": "medium", "phase": "FASE_A"},
        {"name": "/front-end-build x", "model": "opus", "effort": "high", "phase": "FASE_B"},
    ]
    wbs_root, flow_path = _setup_dcp_specific_flow_scenario(
        tmp_path, commands=commands, overrides=None,
    )
    cfg = _make_config(tmp_path, wbs_root)
    app_state.set_config(cfg)
    monkeypatch.setattr(dcp_pkg, "READER_AVAILABLE", True)

    widget = CommandQueueWidget()
    try:
        btn = next(
            (b for b in widget.header_widget.findChildren(QPushButton)
             if b.property("testid") == "queue-btn-dcp-specific-flow"),
            None,
        )
        assert btn is not None
        btn.click()
        # After click + emit, queue has 2 items at positions 1,2.
        assert len(widget._items) == 2
        assert widget._current_dcp_flow_path == flow_path
        # Remove the /front-end-build x item (position 2)
        widget._on_remove_requested(2)
    finally:
        widget.deleteLater()
        app_state.clear_config()

    data = json.loads(flow_path.read_text(encoding="utf-8"))
    assert "/front-end-build x" in data.get("overrides", {}).get("skipped", []), (
        "remove must persist to overrides.skipped"
    )


def test_dcp_remove_outside_dcp_context_does_not_write_disk(
    qapp, tmp_path: Path
) -> None:
    """When the queue is loaded from a non-DCP source (legacy template),
    _on_remove_requested must NOT touch any SPECIFIC-FLOW.json on disk —
    _current_dcp_flow_path stays None and _persist_dcp_skip is a no-op."""
    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
    from workflow_app.domain import CommandSpec, EffortLevel, InteractionType, ModelName

    widget = CommandQueueWidget()
    try:
        # Load directly via load_pipeline (skips _on_dcp_specific_flow_clicked)
        widget.load_pipeline([
            CommandSpec(
                name="/some-template-cmd",
                model=ModelName.SONNET,
                interaction_type=InteractionType.AUTO,
                position=1,
                effort=EffortLevel.STANDARD,
                phase="legacy",
            ),
        ])
        assert widget._current_dcp_flow_path is None
        widget._on_remove_requested(1)  # should not raise, should not write
        assert widget._current_dcp_flow_path is None
    finally:
        widget.deleteLater()


# ─── Task 12: _on_dcp_build_pipeline_clicked (B-dcp pipeline emission) ────── #


def _setup_dcp_build_pipeline_scenario(
    tmp_path: Path,
    *,
    module_state: str,
    with_specific_flow: bool,
) -> tuple[Path, Path]:
    """Scenario builder for the new B-dcp pipeline handler.

    `module_state="creation"` triggers the --regenerate path (state past
    pending). `module_state="pending"` keeps the bare emission. The
    SPECIFIC-FLOW.json is optional on disk (controls destructive guard).
    """
    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()

    _write_delivery(
        wbs_root,
        current_module="module-1-dashboard",
        modules={
            "module-1-dashboard": _module(module_state, module_type="dashboard"),
        },
    )

    meta_dir = wbs_root / "modules" / "module-1-dashboard"
    meta_dir.mkdir(parents=True)
    (meta_dir / "MODULE-META.json").write_text(
        json.dumps({
            "module_id": "module-1-dashboard",
            "module_name": "Dashboard",
            "module_type": "dashboard",
        }),
        encoding="utf-8",
    )

    flow_path = meta_dir / "SPECIFIC-FLOW.json"
    if with_specific_flow:
        flow_path.write_text(
            json.dumps({"version": 1, "commands": [
                {"name": "/clear"}, {"name": "/dcp:congruence-check"},
            ]}),
            encoding="utf-8",
        )
    return wbs_root, flow_path


def test_pipeline_emits_6_items_with_local_action_at_position_6(
    qapp, monkeypatch, tmp_path: Path
) -> None:
    """Pending module → 6 specs emitted via pipeline_ready, last one
    `kind="local-action"` pointing to `dcp-load-specific-flow`."""
    from workflow_app import dcp as dcp_pkg
    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
    from workflow_app.config.app_state import app_state
    from workflow_app.signal_bus import signal_bus

    wbs_root, _ = _setup_dcp_build_pipeline_scenario(
        tmp_path, module_state="pending", with_specific_flow=False,
    )
    cfg = _make_config(tmp_path, wbs_root)
    app_state.set_config(cfg)
    monkeypatch.setattr(dcp_pkg, "READER_AVAILABLE", True)

    emitted: list[list[CommandSpec]] = []
    signal_bus.pipeline_ready.connect(emitted.append)

    widget = CommandQueueWidget()
    try:
        widget._on_dcp_build_pipeline_clicked()
    finally:
        try:
            signal_bus.pipeline_ready.disconnect(emitted.append)
        except (RuntimeError, TypeError):
            pass
        widget.deleteLater()
        app_state.clear_config()

    # Filter out emissions that come from CommandQueueWidget construction
    # (e.g. listener-test wiring). The handler-emitted batch is the only
    # one containing "/build-module-pipeline" (post-`_inject_clears` the
    # batch starts with /clear directive triplets, not the build command).
    handler_batches = [
        batch for batch in emitted
        if batch and any(s.name.startswith("/build-module-pipeline") for s in batch)
    ]
    assert len(handler_batches) == 1, (
        f"expected exactly 1 B-dcp emission, got {len(handler_batches)} "
        f"(total emissions: {len(emitted)})"
    )
    raw_specs = handler_batches[0]
    # `_inject_clears` expands 6 logical commands with /clear + /model + /effort
    # triplet headers (WORKFLOW-APP-RULES GROUP_MAP). Filter directive headers
    # to recover the 6 logical commands.
    specs = [
        s for s in raw_specs
        if not (
            s.name == "/clear"
            or s.name.startswith("/model ")
            or s.name.startswith("/effort ")
        )
    ]
    assert len(specs) == 6, f"expected 6 logical specs, got {len(specs)} (raw={len(raw_specs)})"

    # Position 1: /build-module-pipeline (no --regenerate on pending)
    assert specs[0].name.startswith("/build-module-pipeline ")
    assert "--regenerate" not in specs[0].name
    assert "--module 1" in specs[0].name

    # Positions 2..5: /dcp:* slash commands
    assert specs[1].name.startswith("/dcp:congruence-check")
    assert specs[2].name.startswith("/dcp:temporality-check")
    assert specs[3].name.startswith("/dcp:meta-completeness")
    assert specs[4].name.startswith("/dcp:directive-injector")

    # Position 6 (last logical slot): local-action — the visible queue marker.
    # The expanded raw position is wherever `_inject_clears` placed it (final),
    # so check identity (kind + id) rather than the literal index 6.
    assert specs[5].kind == "local-action"
    assert specs[5].local_action_id == "dcp-load-specific-flow"

    # Positions are strictly increasing across the raw expanded list.
    raw_positions = [s.position for s in raw_specs]
    assert raw_positions == sorted(raw_positions) and len(set(raw_positions)) == len(raw_positions)


def test_pipeline_includes_regenerate_flag_when_state_past_pending(
    qapp, monkeypatch, tmp_path: Path
) -> None:
    """Module state past `pending` → first spec carries `--regenerate`
    and the destructive-guard modal is skipped when no SPECIFIC-FLOW.json
    exists on disk."""
    from workflow_app import dcp as dcp_pkg
    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
    from workflow_app.config.app_state import app_state
    from workflow_app.signal_bus import signal_bus

    wbs_root, _ = _setup_dcp_build_pipeline_scenario(
        tmp_path, module_state="creation", with_specific_flow=False,
    )
    cfg = _make_config(tmp_path, wbs_root)
    app_state.set_config(cfg)
    monkeypatch.setattr(dcp_pkg, "READER_AVAILABLE", True)

    emitted: list[list[CommandSpec]] = []
    signal_bus.pipeline_ready.connect(emitted.append)

    widget = CommandQueueWidget()
    try:
        widget._on_dcp_build_pipeline_clicked()
    finally:
        try:
            signal_bus.pipeline_ready.disconnect(emitted.append)
        except (RuntimeError, TypeError):
            pass
        widget.deleteLater()
        app_state.clear_config()

    handler_batches = [
        batch for batch in emitted
        if batch and any(s.name.startswith("/build-module-pipeline") for s in batch)
    ]
    assert len(handler_batches) == 1
    raw_specs = handler_batches[0]
    specs = [
        s for s in raw_specs
        if not (
            s.name == "/clear"
            or s.name.startswith("/model ")
            or s.name.startswith("/effort ")
        )
    ]
    assert len(specs) == 6

    # --regenerate inserted before --module on the first spec
    first_name = specs[0].name
    assert first_name.startswith("/build-module-pipeline --regenerate ")
    assert "--module 1" in first_name

    # Position 6 still wired to the local action
    assert specs[5].kind == "local-action"
    assert specs[5].local_action_id == "dcp-load-specific-flow"


def test_destructive_guard_blocks_when_user_cancels_modal(
    qapp, monkeypatch, tmp_path: Path
) -> None:
    """Module past pending + SPECIFIC-FLOW.json exists on disk →
    ConfirmRegenerateSpecificFlowModal runs; rejecting it blocks the
    pipeline_ready emission AND leaves `_pending_dcp_load_ctx` cleared."""
    from unittest.mock import patch

    from PySide6.QtWidgets import QDialog

    from workflow_app import dcp as dcp_pkg
    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
    from workflow_app.config.app_state import app_state
    from workflow_app.signal_bus import signal_bus

    wbs_root, _ = _setup_dcp_build_pipeline_scenario(
        tmp_path, module_state="creation", with_specific_flow=True,
    )
    cfg = _make_config(tmp_path, wbs_root)
    app_state.set_config(cfg)
    monkeypatch.setattr(dcp_pkg, "READER_AVAILABLE", True)

    emitted: list[list[CommandSpec]] = []
    signal_bus.pipeline_ready.connect(emitted.append)

    modal_calls: list[bool] = []

    def fake_exec(self):
        modal_calls.append(True)
        return QDialog.DialogCode.Rejected

    with patch(
        "workflow_app.dialogs.confirm_regenerate_specific_flow_modal."
        "ConfirmRegenerateSpecificFlowModal.exec",
        new=fake_exec,
    ):
        widget = CommandQueueWidget()
        try:
            widget._on_dcp_build_pipeline_clicked()
            handler_batches = [
                batch for batch in emitted
                if batch and batch[0].name.startswith("/build-module-pipeline")
            ]
            assert len(modal_calls) == 1, "destructive modal must run"
            assert handler_batches == [], (
                "rejected modal must block pipeline_ready emission"
            )
            assert widget._pending_dcp_load_ctx is None, (
                "rejected modal must leave _pending_dcp_load_ctx unset"
            )
        finally:
            try:
                signal_bus.pipeline_ready.disconnect(emitted.append)
            except (RuntimeError, TypeError):
                pass
            widget.deleteLater()
            app_state.clear_config()


# ─── Task 13: _handle_dcp_load_specific_flow (local-action at position 6) ── #


def _build_dcp_ctx(wbs_root: Path, cm_id: str, module_state: str, regenerate: bool):
    """Build a DcpBuildContext for direct invocation of the local-action.

    The handler under test reads `ctx.wbs_root` and `ctx.cm_id`; `delivery`
    is forward-referenced and re-loaded internally via DeliveryReader, so we
    pass a placeholder. `module_state` is not consulted by the load step.
    """
    from workflow_app.command_queue.command_queue_widget import DcpBuildContext
    from workflow_app.services.delivery_reader import DeliveryReader

    result = DeliveryReader().load(wbs_root)
    # _build_dcp_ctx is only used after _write_delivery — DeliveryFound expected.
    return DcpBuildContext(
        cm_id=cm_id,
        module_state=module_state,
        regenerate=regenerate,
        wbs_root=wbs_root,
        delivery=result.delivery,  # type: ignore[union-attr]
    )


def _make_local_action_spec():
    """Build the position-6 local-action CommandSpec used at dispatch time."""
    from workflow_app.domain import (
        CommandSpec,
        EffortLevel,
        InteractionType,
        ModelName,
    )

    return CommandSpec(
        name="DCP: Carregar Specific-Flow",
        model=ModelName.HAIKU,
        interaction_type=InteractionType.AUTO,
        position=6,
        effort=EffortLevel.LOW,
        kind="local-action",
        local_action_id="dcp-load-specific-flow",
    )


def test_handle_dcp_load_resolves_flow_and_calls_enqueue(
    qapp, monkeypatch, tmp_path: Path
) -> None:
    """Pending context + SPECIFIC-FLOW.json present → handler calls
    `_enqueue_specific_flow` with the resolved path and propagates its
    return value."""
    from workflow_app.command_queue import command_queue_widget as cqw
    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
    from workflow_app.config.app_state import app_state

    wbs_root, flow_path = _setup_dcp_build_pipeline_scenario(
        tmp_path, module_state="creation", with_specific_flow=True,
    )
    cfg = _make_config(tmp_path, wbs_root)
    app_state.set_config(cfg)

    widget = CommandQueueWidget()
    try:
        widget._pending_dcp_load_ctx = _build_dcp_ctx(
            wbs_root, "module-1-dashboard", "creation", regenerate=True,
        )

        captured: dict = {}

        def fake_enqueue(*, flow_path, cm_id, default_project_name, prefix_commands):
            captured["flow_path"] = flow_path
            captured["cm_id"] = cm_id
            captured["default_project_name"] = default_project_name
            captured["prefix_commands"] = prefix_commands
            return True

        monkeypatch.setattr(widget, "_enqueue_specific_flow", fake_enqueue)
        # Force level-1 cascade hit by stubbing resolver to the fixture path.
        monkeypatch.setattr(
            "workflow_app.services.delivery_reader.resolve_specific_flow",
            lambda *a, **kw: flow_path,
        )

        ok = widget._handle_dcp_load_specific_flow(_make_local_action_spec())

        assert ok is True, "handler must propagate _enqueue_specific_flow return"
        assert captured["flow_path"] == flow_path
        assert captured["cm_id"] == "module-1-dashboard"
        assert captured["default_project_name"] == cfg.project_name
        assert captured["prefix_commands"] is None
    finally:
        widget.deleteLater()
        app_state.clear_config()


def test_handle_dcp_load_warns_when_flow_missing_despite_pipeline_success(
    qapp, monkeypatch, tmp_path: Path
) -> None:
    """Pending context but SPECIFIC-FLOW.json absent on disk → handler
    emits a warning toast, returns False, and does NOT call enqueue."""
    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
    from workflow_app.config.app_state import app_state
    from workflow_app.signal_bus import signal_bus

    wbs_root, _ = _setup_dcp_build_pipeline_scenario(
        tmp_path, module_state="creation", with_specific_flow=False,
    )
    cfg = _make_config(tmp_path, wbs_root)
    app_state.set_config(cfg)

    toasts: list[tuple[str, str]] = []
    signal_bus.toast_requested.connect(lambda msg, lvl: toasts.append((msg, lvl)))

    widget = CommandQueueWidget()
    try:
        widget._pending_dcp_load_ctx = _build_dcp_ctx(
            wbs_root, "module-1-dashboard", "creation", regenerate=True,
        )

        enqueue_calls: list[bool] = []

        def fake_enqueue(**kwargs):
            enqueue_calls.append(True)
            return True

        monkeypatch.setattr(widget, "_enqueue_specific_flow", fake_enqueue)

        ok = widget._handle_dcp_load_specific_flow(_make_local_action_spec())

        assert ok is False
        assert enqueue_calls == [], "enqueue must not run when flow is missing"
        warnings = [
            (m, l) for (m, l) in toasts
            if l == "warning" and "SPECIFIC-FLOW.json nao apareceu" in m
        ]
        assert len(warnings) == 1, (
            f"expected one warning toast about missing flow, got {toasts}"
        )
    finally:
        try:
            signal_bus.toast_requested.disconnect()
        except (RuntimeError, TypeError):
            pass
        widget.deleteLater()
        app_state.clear_config()


def test_handle_dcp_load_clears_pending_context_on_success(
    qapp, monkeypatch, tmp_path: Path
) -> None:
    """Successful dispatch must clear `_pending_dcp_load_ctx` so a
    subsequent click can rearm cleanly."""
    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
    from workflow_app.config.app_state import app_state

    wbs_root, flow_path = _setup_dcp_build_pipeline_scenario(
        tmp_path, module_state="creation", with_specific_flow=True,
    )
    cfg = _make_config(tmp_path, wbs_root)
    app_state.set_config(cfg)

    widget = CommandQueueWidget()
    try:
        widget._pending_dcp_load_ctx = _build_dcp_ctx(
            wbs_root, "module-1-dashboard", "creation", regenerate=True,
        )
        monkeypatch.setattr(widget, "_enqueue_specific_flow", lambda **kw: True)
        monkeypatch.setattr(
            "workflow_app.services.delivery_reader.resolve_specific_flow",
            lambda *a, **kw: flow_path,
        )

        widget._handle_dcp_load_specific_flow(_make_local_action_spec())

        assert widget._pending_dcp_load_ctx is None
    finally:
        widget.deleteLater()
        app_state.clear_config()


def test_handle_dcp_load_clears_pending_context_on_failure(
    qapp, monkeypatch, tmp_path: Path
) -> None:
    """Failure paths (flow absent, delivery indisponivel) must also clear
    `_pending_dcp_load_ctx` so the user can re-click without stale state."""
    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
    from workflow_app.config.app_state import app_state

    wbs_root, _ = _setup_dcp_build_pipeline_scenario(
        tmp_path, module_state="creation", with_specific_flow=False,
    )
    cfg = _make_config(tmp_path, wbs_root)
    app_state.set_config(cfg)

    widget = CommandQueueWidget()
    try:
        widget._pending_dcp_load_ctx = _build_dcp_ctx(
            wbs_root, "module-1-dashboard", "creation", regenerate=True,
        )

        def fail_enqueue(**kw):  # pragma: no cover - should not be reached
            raise AssertionError("enqueue must not be called on failure path")

        monkeypatch.setattr(widget, "_enqueue_specific_flow", fail_enqueue)

        ok = widget._handle_dcp_load_specific_flow(_make_local_action_spec())

        assert ok is False
        assert widget._pending_dcp_load_ctx is None
    finally:
        widget.deleteLater()
        app_state.clear_config()
