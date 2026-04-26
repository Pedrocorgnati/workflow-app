"""Tests for the workflow-app Kanban view (T-036).

Covers:
- 9 columns mapped to DCP states in canonical order.
- Modules distributed to the correct column per ``state``.
- Card border color matches the state palette.
- Click emits ``module_clicked`` with the module id.
- ``refresh`` picks up external edits to ``delivery.json``.
- Lock badge shows / hides via ``set_lock_holder``.
- Graceful handling of missing delivery.json.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict, List

import pytest
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest

from workflow_app.models.delivery import ModuleStateLiteral
from workflow_app.services.delivery_reader import (
    DELIVERY_FILENAME,
    DeliveryReader,
)
from workflow_app.views.kanban import (
    STATE_COLORS,
    STATE_LABELS,
    STATE_ORDER,
    KanbanView,
)
from workflow_app.widgets.module_card import MODULE_TYPE_ICONS, ModuleCard
from workflow_app.widgets.state_column import StateColumn

pytestmark = pytest.mark.usefixtures("qapp")


# ─── Builders (lifted from test_delivery_reader for test isolation) ─────── #


def _iso(ts: str = "2026-04-12T09:00:00Z") -> str:
    return ts


def _base_project(wbs_root: Path) -> Dict[str, Any]:
    return {
        "name": "kanban-test",
        "brief_root": str(wbs_root / "brief"),
        "docs_root": str(wbs_root / "docs"),
        "wbs_root": str(wbs_root),
        "workspace_root": str(wbs_root / "workspace"),
    }


def _base_skeleton() -> Dict[str, Any]:
    return {
        "version": "skeleton-v2",
        "sha256": "a1b2c3d4",
        "doc_path": "output/wbs/test/_SHARED-SKELETON.md",
        "code_path": "output/workspace/test/shared/contracts",
        "last_updated": _iso("2026-04-12T08:00:00Z"),
        "bumped_by": "modules:create-structure",
    }


def _base_metadata() -> Dict[str, Any]:
    return {
        "schema_sha256": "schema-v1-hex",
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
    skeleton_version: str = "skeleton-v2",
    module_type: str = "crud",
    dependencies: list | None = None,
    history: list | None = None,
    last_transition: str = "2026-04-12T12:00:00Z",
    needs_rework: bool = False,
    rework_iterations: int = 0,
    blocked: bool = False,
    blocked_reason: str | None = None,
    blocked_prev_state: str | None = None,
    rework_target: dict | None = None,
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
                    "at": last_transition,
                    "by": "build-module-pipeline",
                    "note": "auto",
                }
            ]
    return {
        "state": state,
        "state_detail": f"{state}-detail",
        "module_type": module_type,
        "attempt": attempt,
        "started_at": last_transition,
        "last_transition": last_transition,
        "blocked": blocked,
        "blocked_reason": blocked_reason,
        "blocked_prev_state": blocked_prev_state,
        "owner": owner,
        "flags": {
            "needs_rework": needs_rework,
            "skeleton_outdated": False,
            "rework_target": rework_target or {"phase": None, "module": None},
        },
        "skeleton_version": skeleton_version,
        "rework_iterations": rework_iterations,
        "max_rework_iterations": 2,
        "history": history,
        "artifacts": {
            "module_meta_path": None,
            "overview_path": None,
            "last_specific_flow": None,
            "last_review_report": None,
            "last_commit_sha": None,
            "last_deploy_url": None,
            "git_tag": None,
        },
        "dependencies": dependencies or [],
    }


def _write_delivery(path: Path, payload: Dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


# ─── Fixtures ────────────────────────────────────────────────────────────── #


def _ten_modules_payload(wbs_root: Path) -> Dict[str, Any]:
    """Build a payload with 10 modules spanning all 9 states + a second `done`.

    Layout:
      module-0-foundations (done)
      module-1-crud        (pending)
      module-2-landing     (creation)
      module-3-dashboard   (execution)
      module-4-auth        (revision)
      module-5-integration (qa)
      module-6-payment     (deploy)
      module-7-api         (done)
      module-8-backoffice  (blocked, blocked_prev_state=execution)
      module-9-infra       (rework)
    """
    modules = {
        "module-0-foundations": _module("done", module_type="foundations"),
        "module-1-crud": _module(
            "pending", attempt=0, module_type="crud"
        ),
        "module-2-landing": _module(
            "creation", module_type="landing-page"
        ),
        "module-3-dashboard": _module(
            "execution", module_type="dashboard"
        ),
        "module-4-auth": _module("revision", module_type="auth"),
        "module-5-integration": _module("qa", module_type="integration"),
        "module-6-payment": _module("deploy", module_type="payment"),
        "module-7-api": _module("done", module_type="api-only"),
        "module-8-backoffice": _module(
            "blocked",
            module_type="backoffice",
            blocked=True,
            blocked_reason="dependency failure",
            blocked_prev_state="execution",
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
                    "to": "blocked",
                    "at": "2026-04-12T10:00:00Z",
                    "by": "validation-summary",
                    "note": "dependency failure",
                },
            ],
            owner="human",
        ),
        "module-9-infra": _module(
            "rework",
            module_type="infra-only",
            needs_rework=True,
            rework_iterations=1,
            rework_target={"phase": "execution", "module": "module-9-infra"},
        ),
    }
    return {
        "version": 1,
        "project": _base_project(wbs_root),
        "current_module": "module-3-dashboard",
        "execution_mode": "sequential",
        "modules": modules,
        "skeleton": _base_skeleton(),
        "locks": _base_locks_null(),
        "metadata": _base_metadata(),
    }


@pytest.fixture
def ten_module_delivery(tmp_path: Path) -> Path:
    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()
    payload = _ten_modules_payload(wbs_root)
    _write_delivery(wbs_root / DELIVERY_FILENAME, payload)
    return wbs_root


@pytest.fixture
def empty_wbs(tmp_path: Path) -> Path:
    wbs_root = tmp_path / "empty"
    wbs_root.mkdir()
    return wbs_root


@pytest.fixture
def single_exec_delivery(tmp_path: Path) -> Path:
    wbs_root = tmp_path / "single"
    wbs_root.mkdir()
    payload = {
        "version": 1,
        "project": _base_project(wbs_root),
        "current_module": "module-1-dashboard",
        "execution_mode": "sequential",
        "modules": {
            "module-1-dashboard": _module(
                "execution", module_type="dashboard"
            ),
        },
        "skeleton": _base_skeleton(),
        "locks": _base_locks_null(),
        "metadata": _base_metadata(),
    }
    _write_delivery(wbs_root / DELIVERY_FILENAME, payload)
    return wbs_root


# ─── Helpers ─────────────────────────────────────────────────────────────── #


def _build_view() -> KanbanView:
    reader = DeliveryReader()
    view = KanbanView(reader=reader)
    return view


# ─── Tests ───────────────────────────────────────────────────────────────── #


def test_state_order_has_nine_canonical_entries() -> None:
    assert len(STATE_ORDER) == 9
    assert STATE_ORDER == (
        "pending",
        "creation",
        "execution",
        "revision",
        "qa",
        "deploy",
        "done",
        "blocked",
        "rework",
    )
    assert set(STATE_COLORS.keys()) == set(STATE_ORDER)
    assert set(STATE_LABELS.keys()) == set(STATE_ORDER)


def test_kanban_has_nine_columns() -> None:
    view = _build_view()
    assert len(view.columns) == 9
    assert set(view.columns.keys()) == set(STATE_ORDER)
    for state in STATE_ORDER:
        assert isinstance(view.columns[state], StateColumn)


def test_kanban_distributes_modules_by_state(ten_module_delivery: Path) -> None:
    view = _build_view()
    view.load(ten_module_delivery)

    expected_counts: Dict[ModuleStateLiteral, int] = {
        "pending": 1,
        "creation": 1,
        "execution": 1,
        "revision": 1,
        "qa": 1,
        "deploy": 1,
        "done": 2,  # foundations + api-only
        "blocked": 1,
        "rework": 1,
    }
    for state, expected in expected_counts.items():
        assert view.columns[state].count() == expected, (
            f"state {state!r} expected {expected} cards, "
            f"got {view.columns[state].count()}"
        )

    # Spot-check card ids landed in the right columns.
    assert "module-3-dashboard" in view.column_card_ids("execution")
    assert "module-8-backoffice" in view.column_card_ids("blocked")
    assert "module-9-infra" in view.column_card_ids("rework")
    assert set(view.column_card_ids("done")) == {
        "module-0-foundations",
        "module-7-api",
    }


def test_kanban_card_border_matches_state(ten_module_delivery: Path) -> None:
    view = _build_view()
    view.load(ten_module_delivery)

    exec_column = view.columns["execution"]
    card: ModuleCard = exec_column._cards[0]  # noqa: SLF001
    assert card.border_color == STATE_COLORS["execution"]
    assert STATE_COLORS["execution"] in card.styleSheet()


def test_kanban_click_emits_module_id(single_exec_delivery: Path) -> None:
    view = _build_view()
    view.load(single_exec_delivery)

    received: List[str] = []
    view.module_clicked.connect(received.append)

    exec_column = view.columns["execution"]
    card: ModuleCard = exec_column._cards[0]  # noqa: SLF001
    QTest.mouseClick(card, Qt.MouseButton.LeftButton)

    assert received == ["module-1-dashboard"]


def test_kanban_refresh_picks_up_external_edit(
    single_exec_delivery: Path,
) -> None:
    view = _build_view()
    view.load(single_exec_delivery)
    assert view.columns["execution"].count() == 1
    assert view.columns["qa"].count() == 0

    # Mutate delivery.json: execution → qa.
    delivery_path = single_exec_delivery / DELIVERY_FILENAME
    raw = json.loads(delivery_path.read_text(encoding="utf-8"))
    raw["modules"]["module-1-dashboard"]["state"] = "qa"
    raw["modules"]["module-1-dashboard"]["history"].append(
        {
            "from": "execution",
            "to": "qa",
            "at": "2026-04-12T13:00:00Z",
            "by": "validation-summary",
            "note": "",
        }
    )
    raw["modules"]["module-1-dashboard"]["last_transition"] = (
        "2026-04-12T13:00:00Z"
    )
    delivery_path.write_text(json.dumps(raw, indent=2), encoding="utf-8")

    view.refresh()
    assert view.columns["execution"].count() == 0
    assert view.columns["qa"].count() == 1
    assert "module-1-dashboard" in view.column_card_ids("qa")


def test_kanban_lock_badge_toggles() -> None:
    view = _build_view()
    assert view._lock_badge.isVisible() is False  # noqa: SLF001

    view.set_lock_holder("cli")
    view.show()
    QTest.qWait(20)
    assert view._lock_badge.text() == "LOCKED by cli"  # noqa: SLF001

    view.set_lock_holder(None)
    assert view._lock_badge.text() == ""  # noqa: SLF001
    assert view._lock_badge.isHidden() is True  # noqa: SLF001


def test_kanban_handles_missing_delivery(empty_wbs: Path) -> None:
    view = _build_view()
    view.load(empty_wbs)

    for column in view.columns.values():
        assert column.count() == 0
    assert "nao encontrado" in view._status_label.text()  # noqa: SLF001


def test_kanban_clear_resets_state(single_exec_delivery: Path) -> None:
    view = _build_view()
    view.load(single_exec_delivery)
    assert view.columns["execution"].count() == 1

    view.clear()
    for column in view.columns.values():
        assert column.count() == 0
    assert view._wbs_root is None  # noqa: SLF001
    assert view._status_label.text() == "Nenhum projeto carregado"  # noqa: SLF001


def test_module_card_icons_match_known_types() -> None:
    # Ensure every module_type in the schema has an icon mapped so new types
    # surface as a TypeError in tests before they silently ship.
    expected_types = {
        "foundations",
        "landing-page",
        "dashboard",
        "crud",
        "auth",
        "integration",
        "payment",
        "backoffice",
        "infra-only",
        "api-only",
    }
    assert set(MODULE_TYPE_ICONS.keys()) == expected_types
