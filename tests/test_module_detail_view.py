"""Tests for the per-module detail view (T-038).

Covers AC1..AC7 from TASK-038:

- AC1: clicking a module card opens the detail view (integration with T-036)
- AC2: 5 tabs rendered (Metadados, Artefatos, History, Gates, Pipeline)
- AC3: Action bar contextual per DCP state
- AC4: **NO** Promote / **NO** Rollback buttons (explicit assertion)
- AC5: Reopen dialog exposes ``ReworkPhase`` literals + optional reason
- AC6: Unblock path triggers confirmation before ``/delivery:unblock``
- AC7: History tab renders the module ``history`` as a vertical timeline
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest

from workflow_app.services.delivery_reader import DELIVERY_FILENAME, DeliveryReader
from workflow_app.views.module_detail import ModuleDetailView, ReopenDialog, _REWORK_PHASES
from workflow_app.widgets.action_bar import ActionBar
from workflow_app.widgets.artifact_tabs import ArtifactTabs, TAB_TESTIDS
from workflow_app.widgets.history_timeline import HistoryTimeline

pytestmark = pytest.mark.usefixtures("qapp")


# ─── Builders ───────────────────────────────────────────────────────────── #


def _iso(ts: str = "2026-04-12T09:00:00Z") -> str:
    return ts


def _base_project(wbs_root: Path) -> Dict[str, Any]:
    return {
        "name": "detail-test",
        "brief_root": str(wbs_root / "brief"),
        "docs_root": str(wbs_root / "docs"),
        "wbs_root": str(wbs_root),
        "workspace_root": str(wbs_root / "workspace"),
    }


def _base_skeleton() -> Dict[str, Any]:
    return {
        "version": "skeleton-v2",
        "sha256": "a1b2c3",
        "doc_path": "output/wbs/detail/_SHARED-SKELETON.md",
        "code_path": "output/workspace/detail/shared/contracts",
        "last_updated": _iso("2026-04-12T08:00:00Z"),
        "bumped_by": "modules:create-structure",
    }


def _base_metadata() -> Dict[str, Any]:
    return {
        "schema_sha256": "schema-hex",
        "created_at": _iso("2026-04-11T15:00:00Z"),
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
    attempt: int = 1,
    module_type: str = "crud",
    history: list | None = None,
    blocked: bool = False,
    blocked_reason: str | None = None,
    blocked_prev_state: str | None = None,
    artifacts: dict | None = None,
    owner: str | None = "pipeline",
) -> Dict[str, Any]:
    if history is None:
        if state == "pending":
            history = []
        else:
            history = [
                {
                    "from": "pending",
                    "to": state,
                    "at": "2026-04-12T10:00:00Z",
                    "by": "build-module-pipeline",
                    "note": "auto",
                }
            ]
    return {
        "state": state,
        "state_detail": f"{state}-detail",
        "module_type": module_type,
        "attempt": attempt,
        "started_at": "2026-04-12T10:00:00Z",
        "last_transition": "2026-04-12T10:00:00Z",
        "blocked": blocked,
        "blocked_reason": blocked_reason,
        "blocked_prev_state": blocked_prev_state,
        "owner": owner,
        "flags": {
            "needs_rework": state == "rework",
            "skeleton_outdated": False,
            "rework_target": (
                {"phase": "execution", "module": "module-4-rework"}
                if state == "rework"
                else {"phase": None, "module": None}
            ),
        },
        "skeleton_version": "skeleton-v2",
        "rework_iterations": 0,
        "max_rework_iterations": 2,
        "history": history,
        "artifacts": artifacts or {
            "module_meta_path": None,
            "overview_path": None,
            "last_specific_flow": None,
            "last_review_report": None,
            "last_commit_sha": None,
            "last_deploy_url": None,
            "git_tag": None,
        },
        "dependencies": [],
    }


def _write_delivery(wbs_root: Path, modules: Dict[str, Dict[str, Any]]) -> Path:
    payload = {
        "version": 1,
        "project": _base_project(wbs_root),
        "current_module": next(iter(modules.keys())),
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


# ─── Fixtures ───────────────────────────────────────────────────────────── #


@pytest.fixture
def wbs_with_modules(tmp_path: Path) -> Path:
    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()
    (wbs_root.parent / "workspace").mkdir(exist_ok=True)
    _write_delivery(
        wbs_root,
        {
            "module-0-foundations": _module(
                "done",
                module_type="foundations",
                history=[
                    {
                        "from": "pending",
                        "to": "creation",
                        "at": "2026-04-12T09:00:00Z",
                        "by": "build-module-pipeline",
                        "note": "start",
                    },
                    {
                        "from": "creation",
                        "to": "execution",
                        "at": "2026-04-12T09:30:00Z",
                        "by": "update-task-user-stories",
                        "note": "",
                    },
                    {
                        "from": "execution",
                        "to": "done",
                        "at": "2026-04-12T10:00:00Z",
                        "by": "delivery:sign-off",
                        "note": "ok",
                    },
                ],
            ),
            "module-1-crud": _module("pending", attempt=0),
            "module-2-exec": _module("execution"),
            "module-3-blocked": _module(
                "blocked",
                blocked=True,
                blocked_reason="dep failure",
                blocked_prev_state="execution",
            ),
            "module-4-rework": _module("rework"),
        },
    )
    return wbs_root


@pytest.fixture
def view(wbs_with_modules: Path) -> ModuleDetailView:
    reader = DeliveryReader()
    v = ModuleDetailView(reader=reader)
    v.set_wbs_root(wbs_with_modules)
    return v


# ─── Helpers ────────────────────────────────────────────────────────────── #


def _children_testids(widget, *, prefix: str = "") -> list[str]:
    ids: list[str] = []
    for child in widget.findChildren(object):
        tid = child.property("testid")
        if isinstance(tid, str) and (not prefix or tid.startswith(prefix)):
            ids.append(tid)
    return ids


# ─── Structural tests ───────────────────────────────────────────────────── #


def test_view_exposes_five_tab_buttons(view: ModuleDetailView) -> None:
    assert len(view.tab_buttons) == 5
    expected = [f"detail-selector-{tid}" for tid in TAB_TESTIDS]
    actual = [btn.property("testid") for btn in view.tab_buttons]
    assert actual == expected


def test_artifact_tabs_has_five_pages(view: ModuleDetailView) -> None:
    assert view.artifact_tabs.count() == 5
    # Each page exposes its testid.
    page_ids = [
        view.artifact_tabs.widget(i).property("testid") for i in range(5)
    ]
    assert page_ids == list(TAB_TESTIDS)


def test_no_promote_no_rollback_buttons(view: ModuleDetailView) -> None:
    """AC critico: DCP state machine nao permite Promote/Rollback.

    Qualquer botao action-btn-promote ou action-btn-rollback seria uma
    violacao do contrato documentado em T-006.
    """
    all_testids = _children_testids(view)
    assert "action-btn-promote" not in all_testids
    assert "action-btn-rollback" not in all_testids
    # Positive check: the five legal buttons must exist.
    for expected in (
        "action-btn-run",
        "action-btn-pause",
        "action-btn-unblock",
        "action-btn-reopen",
        "action-btn-terminal",
    ):
        assert expected in all_testids, f"missing {expected}"


def test_metadata_editor_is_read_only(view: ModuleDetailView) -> None:
    editor = view.artifact_tabs._metadados_editor
    assert editor.isReadOnly() is True
    # Banner explicitly warns the user.
    banner = view.findChild(object, name=None)  # just sanity check
    assert view.artifact_tabs._metadados_banner.text().startswith("Editor read-only")


# ─── show_for / state transitions ──────────────────────────────────────── #


def test_show_for_pending_enables_only_run(view: ModuleDetailView) -> None:
    view.show_for("module-1-crud")
    bar: ActionBar = view.action_bar
    assert bar._btn_run.isEnabled() is True
    assert bar._btn_pause.isEnabled() is False
    assert bar._btn_unblock.isEnabled() is False
    assert bar._btn_reopen.isEnabled() is False
    assert bar._btn_terminal.isEnabled() is False


def test_show_for_execution_enables_run_pause_terminal(view: ModuleDetailView) -> None:
    view.show_for("module-2-exec")
    bar: ActionBar = view.action_bar
    assert bar._btn_run.isEnabled() is True
    assert bar._btn_pause.isEnabled() is True
    assert bar._btn_terminal.isEnabled() is True
    assert bar._btn_unblock.isEnabled() is False
    assert bar._btn_reopen.isEnabled() is False


def test_show_for_done_enables_reopen_and_terminal(view: ModuleDetailView) -> None:
    view.show_for("module-0-foundations")
    bar: ActionBar = view.action_bar
    assert bar._btn_reopen.isEnabled() is True
    assert bar._btn_terminal.isEnabled() is True
    assert bar._btn_run.isEnabled() is False
    assert bar._btn_pause.isEnabled() is False
    assert bar._btn_unblock.isEnabled() is False


def test_show_for_blocked_enables_unblock_and_terminal(view: ModuleDetailView) -> None:
    view.show_for("module-3-blocked")
    bar: ActionBar = view.action_bar
    assert bar._btn_unblock.isEnabled() is True
    assert bar._btn_terminal.isEnabled() is True
    assert bar._btn_run.isEnabled() is False
    assert bar._btn_pause.isEnabled() is False
    assert bar._btn_reopen.isEnabled() is False


def test_show_for_rework_enables_run_and_terminal(view: ModuleDetailView) -> None:
    view.show_for("module-4-rework")
    bar: ActionBar = view.action_bar
    assert bar._btn_run.isEnabled() is True
    assert bar._btn_terminal.isEnabled() is True
    assert bar._btn_pause.isEnabled() is False


def test_show_for_blocked_shows_previous_state_in_header(
    view: ModuleDetailView,
) -> None:
    view.show_for("module-3-blocked")
    assert view._blocked_prev_label.isHidden() is False
    assert "execution" in view._blocked_prev_label.text()


def test_show_for_unknown_module_emits_toast(view: ModuleDetailView) -> None:
    from workflow_app.signal_bus import signal_bus

    received: list[tuple[str, str]] = []
    signal_bus.toast_requested.connect(
        lambda msg, lvl: received.append((msg, lvl))
    )
    try:
        view.show_for("module-does-not-exist")
    finally:
        signal_bus.toast_requested.disconnect()
    assert any("nao encontrado" in msg for msg, _ in received)


def test_show_for_sets_title_and_state_badge(view: ModuleDetailView) -> None:
    view.show_for("module-2-exec")
    assert view._title_label.text() == "module-2-exec"
    assert view._state_badge.isHidden() is False
    assert view._state_badge.text().lower().startswith("exec")


# ─── History tab ───────────────────────────────────────────────────────── #


def test_history_tab_renders_timeline_items(view: ModuleDetailView) -> None:
    view.show_for("module-0-foundations")
    timeline: HistoryTimeline = view.artifact_tabs._history_timeline
    assert len(timeline.items) == 3


def test_history_tab_empty_for_pending_module(view: ModuleDetailView) -> None:
    view.show_for("module-1-crud")
    timeline: HistoryTimeline = view.artifact_tabs._history_timeline
    assert len(timeline.items) == 0
    assert timeline._empty_label.isHidden() is False


# ─── Gates/Pipeline tabs ───────────────────────────────────────────────── #


def test_gates_placeholder_when_no_specific_flow(view: ModuleDetailView) -> None:
    view.show_for("module-2-exec")
    tabs = view.artifact_tabs
    assert tabs._gates_placeholder.isHidden() is False
    assert tabs._gates_table.isHidden() is True
    assert tabs._pipeline_placeholder.isHidden() is False
    assert tabs._pipeline_table.isHidden() is True


def test_gates_and_pipeline_populated_from_specific_flow(
    tmp_path: Path,
) -> None:
    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()
    flow_rel = "workflow-app/SPECIFIC-FLOW.json"
    project_root = wbs_root.parent
    flow_path = project_root / flow_rel
    flow_path.parent.mkdir(parents=True, exist_ok=True)
    flow_path.write_text(
        json.dumps(
            {
                "gates": [
                    {"name": "gate-1", "status": "pass", "detail": "ok"},
                    {"name": "gate-2", "status": "fail", "detail": "tests red"},
                ],
                "steps": [
                    {
                        "phase": "B",
                        "command": "/front-end-build",
                        "effort": "high",
                        "state": "done",
                    },
                    {
                        "phase": "E",
                        "command": "/qa:prep",
                        "effort": "low",
                        "state": "pending",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    _write_delivery(
        wbs_root,
        {
            "module-1-crud": _module(
                "execution",
                artifacts={
                    "module_meta_path": None,
                    "overview_path": None,
                    "last_specific_flow": str(flow_path),
                    "last_review_report": None,
                    "last_commit_sha": None,
                    "last_deploy_url": None,
                    "git_tag": None,
                },
            ),
        },
    )
    reader = DeliveryReader()
    v = ModuleDetailView(reader=reader)
    v.set_wbs_root(wbs_root)
    v.show_for("module-1-crud")

    tabs = v.artifact_tabs
    assert tabs._gates_table.rowCount() == 2
    assert tabs._gates_table.item(0, 0).text() == "gate-1"
    assert tabs._gates_table.item(1, 1).text() == "fail"
    assert tabs._pipeline_table.rowCount() == 2
    assert tabs._pipeline_table.item(0, 2).text() == "/front-end-build"


# ─── ReopenDialog ──────────────────────────────────────────────────────── #


def test_reopen_dialog_lists_all_rework_phases() -> None:
    dialog = ReopenDialog(module_id="module-1-crud")
    assert dialog._phase_combo.count() == len(_REWORK_PHASES)
    values = [dialog._phase_combo.itemText(i) for i in range(dialog._phase_combo.count())]
    assert values == list(_REWORK_PHASES)


def test_reopen_dialog_default_reason_when_blank() -> None:
    dialog = ReopenDialog(module_id="module-1-crud")
    assert dialog.selected_reason() == "manual reopen via workflow-app"
    dialog._reason_edit.setText(" trailing ")
    assert dialog.selected_reason() == "trailing"


# ─── Unblock confirmation path ────────────────────────────────────────── #


def test_unblock_click_prompts_confirmation(view: ModuleDetailView) -> None:
    view.show_for("module-3-blocked")
    with patch(
        "workflow_app.views.module_detail.QMessageBox.question"
    ) as mocked_q, patch.object(view, "_run_claude_cli") as mocked_run:
        # Simulate the user clicking "No" — no CLI invocation should happen.
        from PySide6.QtWidgets import QMessageBox

        mocked_q.return_value = QMessageBox.StandardButton.No
        view._on_unblock("module-3-blocked")
        assert mocked_q.called
        assert mocked_run.call_count == 0

        # Then "Yes" — CLI is dispatched with the right args.
        mocked_q.return_value = QMessageBox.StandardButton.Yes
        view._on_unblock("module-3-blocked")
        assert mocked_run.call_count == 1
        call = mocked_run.call_args
        assert call.kwargs["args"] == ["/delivery:unblock", "module-3-blocked"]


# ─── Back button ──────────────────────────────────────────────────────── #


def test_back_button_emits_back_requested(view: ModuleDetailView) -> None:
    received: list[bool] = []
    view.back_requested.connect(lambda: received.append(True))
    view._back_btn.click()
    assert received == [True]


# ─── clear / unload ───────────────────────────────────────────────────── #


def test_clear_resets_view(view: ModuleDetailView) -> None:
    view.show_for("module-2-exec")
    assert view.current_module_id == "module-2-exec"
    view.clear()
    assert view.current_module_id is None
    assert view._title_label.text() == "Nenhum modulo"
    assert view._state_badge.isHidden() is True
    bar: ActionBar = view.action_bar
    assert bar._btn_run.isEnabled() is False
    assert bar._btn_pause.isEnabled() is False


def test_show_for_without_wbs_root_emits_error_toast(tmp_path: Path) -> None:
    from workflow_app.signal_bus import signal_bus

    reader = DeliveryReader()
    v = ModuleDetailView(reader=reader)
    # No set_wbs_root() call.
    received: list[tuple[str, str]] = []
    signal_bus.toast_requested.connect(
        lambda msg, lvl: received.append((msg, lvl))
    )
    try:
        v.show_for("module-1-crud")
    finally:
        signal_bus.toast_requested.disconnect()
    assert any(lvl == "error" for _, lvl in received)


# ─── Regression: Kanban → Detail click flow ───────────────────────────── #


def test_kanban_click_drives_detail_show_for(wbs_with_modules: Path) -> None:
    """Smoke test: the signal emitted by KanbanView wires to show_for."""
    from workflow_app.views.kanban import KanbanView

    reader = DeliveryReader()
    kanban = KanbanView(reader=reader)
    kanban.load(wbs_with_modules)

    detail = ModuleDetailView(reader=reader)
    detail.set_wbs_root(wbs_with_modules)
    kanban.module_clicked.connect(detail.show_for)

    kanban.module_clicked.emit("module-2-exec")
    assert detail.current_module_id == "module-2-exec"
