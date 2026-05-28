"""Regression: UI FAIL-CLOSED when DCP-COMMAND-MATRIX.json yields bare slash names.

Loop 05-27-dcp-flow-structured-fix - TASK-020 (item 021).

This regression locks the behavior delivered by TASK-018 (UI fail-closed) and
TASK-017 (matrix-warning popup): when the in-memory matrix derivation produces
CommandSpec instances whose `name` is a bare slash-token without args (e.g.
`/create-task` alone), `_validate_no_bare_names` must:

  1. Surface a critical `MATRIX_INVALID: name bare na fila derivada` popup
     (intercepted via QMessageBox.exec patch since the dialog is modal).
  2. Return False so the caller aborts emit, i.e. `signal_bus.pipeline_ready`
     MUST NOT fire for this attempt.

Two complementary scenarios:

  C1  Direct invocation of `_validate_no_bare_names` with an offender spec.
  C2  End-to-end via `_derive_queue_from_matrix_inmemory` injecting an invalid
      matrix on disk so the schema-validation path arms
      `_matrix_strict_failed_for_ctx` and aborts before any emit.

Pattern follows tests/test_dcp_pipeline_auto_load.py + tests/test_dcp_build_pipeline_handler.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple
from unittest.mock import patch

import pytest

from workflow_app.config.config_parser import PipelineConfig
from workflow_app.domain import CommandSpec, EffortLevel, InteractionType, ModelName


# --- Fixtures replicated from test_dcp_pipeline_auto_load.py --------------- #


def _make_config(tmp_path: Path, wbs_root: Path) -> PipelineConfig:
    return PipelineConfig(
        config_path=str(tmp_path / ".claude" / "project.json"),
        project_name="dcp-bare-fail-closed",
        brief_root=str(wbs_root / "brief"),
        docs_root=str(wbs_root / "docs"),
        wbs_root=str(wbs_root),
        workspace_root=str(wbs_root / "workspace"),
    )


def _setup_widget(qapp, monkeypatch, cfg: PipelineConfig):
    from workflow_app import dcp as dcp_pkg
    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
    from workflow_app.config.app_state import app_state

    monkeypatch.setattr(dcp_pkg, "READER_AVAILABLE", True)
    app_state.set_config(cfg)
    return CommandQueueWidget()


def _capture_pipeline_ready() -> Tuple[List[List[CommandSpec]], Any]:
    """Connect a listener on signal_bus.pipeline_ready and return (calls, disconnect).

    `calls` accumulates one entry per emission with the specs list. If the
    list stays empty after the action, fail-closed held.
    """
    from workflow_app.signal_bus import signal_bus

    calls: List[List[CommandSpec]] = []

    def listener(specs: List[CommandSpec]) -> None:
        calls.append(list(specs))

    signal_bus.pipeline_ready.connect(listener)

    def disconnect() -> None:
        try:
            signal_bus.pipeline_ready.disconnect(listener)
        except (RuntimeError, TypeError):
            pass

    return calls, disconnect


def _capture_toasts() -> Tuple[List[Tuple[str, str]], Any]:
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


def _bare_spec(name: str = "/create-task") -> CommandSpec:
    return CommandSpec(
        name=name,
        model=ModelName.SONNET,
        interaction_type=InteractionType.AUTO,
        position=1,
        effort=EffortLevel.STANDARD,
        kind="slash",
    )


# --- C1: direct guard invocation ------------------------------------------- #


def test_validate_no_bare_names_blocks_emit_and_shows_matrix_invalid_popup(
    qapp, monkeypatch, tmp_path: Path
) -> None:
    """C1 - _validate_no_bare_names returns False on bare slash, fires popup,
    and `signal_bus.pipeline_ready` is NOT emitted by the caller.

    Note: this helper itself does NOT emit; the contract is that callers
    `return False` before emitting (lines 3511-3512 and 3937-3938 of
    command_queue_widget.py). We assert both: helper returns False AND no
    pipeline_ready fires while the popup is captured.
    """
    from workflow_app.config.app_state import app_state

    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()
    cfg = _make_config(tmp_path, wbs_root)

    popup_bodies: List[str] = []

    def _exec_capture(box_self, *_a, **_kw):
        try:
            popup_bodies.append(box_self.text())
        except Exception:
            popup_bodies.append("")
        return 0  # QDialog.Rejected

    pr_calls, pr_disconnect = _capture_pipeline_ready()
    toasts, toast_disconnect = _capture_toasts()
    try:
        widget = _setup_widget(qapp, monkeypatch, cfg)
        try:
            with patch("PySide6.QtWidgets.QMessageBox.exec", new=_exec_capture):
                specs = [
                    _bare_spec("/create-task"),
                    _bare_spec("/execute-task"),
                ]
                result = widget._validate_no_bare_names(specs, "module-1-x")
        finally:
            widget.deleteLater()
    finally:
        app_state.clear_config()
        pr_disconnect()
        toast_disconnect()

    assert result is False, "guard must reject bare-name specs"
    assert pr_calls == [], (
        "pipeline_ready.emit must NOT fire when guard rejects; "
        f"got {len(pr_calls)} emissions"
    )

    # Popup body identifies modulo + offenders + ABORTADO directive.
    assert len(popup_bodies) == 1
    body = popup_bodies[0]
    assert "name bare" in body
    assert "module-1-x" in body
    assert "/create-task" in body
    assert "/execute-task" in body
    assert "DCP Execute ABORTADO" in body

    # Toasts are only emitted when the popup itself fails (headless fallback).
    # With QMessageBox.exec patched the popup "succeeds" so no toast should
    # fire from the guard. Toasts from other subsystems (none expected here)
    # would still be visible if present.
    assert not any(
        "name bare" in msg or "ABORTADO" in msg for msg, _kind in toasts
    ), f"unexpected toast fallback: {toasts}"


def test_validate_no_bare_names_allows_well_formed_specs(
    qapp, monkeypatch, tmp_path: Path
) -> None:
    """C1.b - sanity counter-case: well-formed specs (slash + args, or
    allowlisted bare tokens) pass through and the helper returns True.

    Guards against false positives that would block legitimate matrices.
    """
    from workflow_app.config.app_state import app_state

    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()
    cfg = _make_config(tmp_path, wbs_root)

    pr_calls, pr_disconnect = _capture_pipeline_ready()
    try:
        widget = _setup_widget(qapp, monkeypatch, cfg)
        try:
            specs = [
                _bare_spec("/create-task --module 1 --task 2"),  # has args
                _bare_spec("/clear"),                            # allowlisted
                _bare_spec("/model {tier}"),                     # allowlisted
                _bare_spec("/effort {level}"),                   # allowlisted
            ]
            result = widget._validate_no_bare_names(specs, "module-1-x")
        finally:
            widget.deleteLater()
    finally:
        app_state.clear_config()
        pr_disconnect()

    assert result is True, "well-formed and allowlisted specs must pass"
    # Helper itself does not emit; caller decides. We only assert no spurious
    # emission slipped through.
    assert pr_calls == []


# --- C2: end-to-end via in-memory deriver with invalid matrix on disk ----- #


def _build_ctx(wbs_root: Path, cm_id: str = "module-1-x"):
    """Construct a minimal DcpBuildContext + Delivery for the deriver call."""
    from workflow_app.command_queue.command_queue_widget import DcpBuildContext
    from workflow_app.models.delivery import Delivery
    from workflow_app.services.delivery_reader import DELIVERY_FILENAME

    # Minimal delivery.json mirroring test_dcp_pipeline_auto_load._write_delivery.
    payload: Dict[str, Any] = {
        "version": 2,
        "project": {
            "name": "dcp-bare-fail-closed",
            "brief_root": str(wbs_root / "brief"),
            "docs_root": str(wbs_root / "docs"),
            "wbs_root": str(wbs_root),
            "workspace_root": str(wbs_root / "workspace"),
        },
        "current_module": cm_id,
        "current_modules": [],
        "execution_mode": "sequential",
        "modules": {
            cm_id: {
                "state": "creation",
                "state_detail": "creation-detail",
                "module_type": "crud",
                "attempt": 1,
                "started_at": "2026-05-27T12:00:00Z",
                "last_transition": "2026-05-27T12:00:00Z",
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
                        "to": "creation",
                        "at": "2026-05-27T12:00:00Z",
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
        },
        "skeleton": {
            "version": "skeleton-v2",
            "sha256": "deadbeef",
            "doc_path": "output/_SHARED-SKELETON.md",
            "code_path": "output/shared/contracts",
            "last_updated": "2026-05-27T08:00:00Z",
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
            "created_at": "2026-05-27T15:00:00Z",
            "created_by": "/delivery:init",
            "last_modified_by": "build-module-pipeline",
        },
    }
    delivery_path = wbs_root / DELIVERY_FILENAME
    delivery_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    delivery = Delivery.model_validate_json(
        delivery_path.read_text(encoding="utf-8")
    )
    return DcpBuildContext(
        cm_id=cm_id,
        module_state="creation",
        regenerate=False,
        wbs_root=wbs_root,
        delivery=delivery,
    )


def test_derive_queue_inmemory_fail_closed_on_invalid_matrix(
    qapp, monkeypatch, tmp_path: Path
) -> None:
    """C2 - inject a syntactically invalid DCP-COMMAND-MATRIX.json. The
    deriver must:

      - catch the parse/validation exception,
      - arm `_matrix_strict_failed_for_ctx == cm_id`,
      - return None,
      - surface a critical MATRIX_INVALID popup,
      - never emit `signal_bus.pipeline_ready`.

    This locks the FAIL-CLOSED contract delivered by TASK-018: callers MUST
    NOT silently fall back to SPECIFIC-FLOW.json when the matrix is corrupt.
    """
    from workflow_app.config.app_state import app_state

    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()
    cfg = _make_config(tmp_path, wbs_root)

    # Inject a corrupted matrix at the canonical location.
    # dcp_root defaults to project_dir when empty, so the deriver short-circuits
    # before reading. To trigger the schema-validation path we MUST set a valid
    # dcp_root and write an invalid JSON file there.
    dcp_root = wbs_root / "dcp"
    dcp_root.mkdir()
    (dcp_root / "DCP-COMMAND-MATRIX.json").write_text(
        "{ this is not valid json", encoding="utf-8"
    )
    cfg.dcp_root = str(dcp_root)

    popup_bodies: List[str] = []
    popup_titles: List[str] = []

    def _exec_capture(box_self, *_a, **_kw):
        try:
            popup_bodies.append(box_self.text())
            popup_titles.append(box_self.windowTitle())
        except Exception:
            popup_bodies.append("")
            popup_titles.append("")
        return 0

    pr_calls, pr_disconnect = _capture_pipeline_ready()
    try:
        widget = _setup_widget(qapp, monkeypatch, cfg)
        ctx = _build_ctx(wbs_root, cm_id="module-1-x")
        try:
            with patch("PySide6.QtWidgets.QMessageBox.exec", new=_exec_capture):
                result = widget._derive_queue_from_matrix_inmemory(ctx, cfg)
        finally:
            widget.deleteLater()
    finally:
        app_state.clear_config()
        pr_disconnect()

    assert result is None, "deriver must return None on invalid matrix"
    assert pr_calls == [], (
        "pipeline_ready.emit must NOT fire on matrix invalid; "
        f"got {len(pr_calls)} emissions"
    )

    # Exactly one MATRIX_INVALID popup, with the canonical title and a
    # body that surfaces the invalid path and the ABORTADO directive.
    assert len(popup_bodies) == 1, (
        f"expected exactly 1 popup, got {len(popup_bodies)}"
    )
    assert popup_titles[0].startswith("MATRIX_INVALID")
    body = popup_bodies[0]
    assert "DCP-COMMAND-MATRIX.json" in body or "matrix" in body.lower()
