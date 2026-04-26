"""Tests for ``workflow_app.services.lock_service.LockService`` (T-037).

Ten cases (C1..C10) cover the surface promised by the FASE A plan:

* C1  — happy path try_acquire emits ``Acquired`` and writes delivery.json
* C2  — second acquire on the same file returns ``Busy``
* C3  — expired lock is reclaimed
* C4  — ``release_and_stop`` is idempotent
* C5  — heartbeat extends ``expires_at``
* C6  — heartbeat loss emits ``lock_lost`` and clears state
* C7  — ``read_current_holder`` returns ``None`` / holder string
* C8  — ``release_and_stop`` is safe when never acquired
* C9  — close flow: release_and_stop writes ``locks=null``
* C10 — ``KanbanView._populate`` auto-drives the lock badge

The tests talk to the CANONICAL ``DeliveryLock`` loaded through
``workflow_app.delivery`` (T-005 lock_bridge.py), so any invariant
violation (I-04/I-05) would surface here without needing a separate
integration suite.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict

import pytest
from PySide6.QtTest import QTest

from workflow_app.delivery import DeliveryLock
from workflow_app.services.delivery_reader import DELIVERY_FILENAME, DeliveryReader
from workflow_app.services.lock_service import (
    Acquired,
    Busy,
    LockFail,
    LockService,
)
from workflow_app.views.kanban import KanbanView

pytestmark = pytest.mark.usefixtures("qapp")


# ─── Helpers / Fixtures ──────────────────────────────────────────────────── #


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _base_project(wbs_root: Path) -> Dict[str, Any]:
    return {
        "name": "lock-service-test",
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
        "last_updated": "2026-04-12T08:00:00Z",
        "bumped_by": "modules:create-structure",
    }


def _base_metadata() -> Dict[str, Any]:
    return {
        "schema_sha256": "schema-v1-hex",
        "created_at": "2026-04-11T15:00:00Z",
        "created_by": "/delivery:init",
        "last_modified_by": "test",
    }


def _null_locks() -> Dict[str, Any]:
    return {
        "holder": None,
        "acquired_at": None,
        "expires_at": None,
        "ttl_seconds": 120,
    }


def _single_module_payload(wbs_root: Path) -> Dict[str, Any]:
    """Minimal schema-valid delivery.json for KanbanView.load (C10)."""
    module = {
        "state": "execution",
        "state_detail": "execution-detail",
        "module_type": "dashboard",
        "attempt": 1,
        "started_at": "2026-04-12T09:00:00Z",
        "last_transition": "2026-04-12T09:00:00Z",
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
                "to": "execution",
                "at": "2026-04-12T09:00:00Z",
                "by": "build-module-pipeline",
                "note": "auto",
            }
        ],
        "artifacts": {
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
    return {
        "version": 1,
        "project": _base_project(wbs_root),
        "current_module": "module-1-dashboard",
        "execution_mode": "sequential",
        "modules": {"module-1-dashboard": module},
        "skeleton": _base_skeleton(),
        "locks": _null_locks(),
        "metadata": _base_metadata(),
    }


def _minimal_locks_doc(locks: Dict[str, Any]) -> Dict[str, Any]:
    """Just enough JSON for DeliveryLock (which only touches ``locks``)."""
    return {"version": 1, "modules": {}, "locks": locks}


def _write(path: Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


@pytest.fixture
def empty_wbs(tmp_path: Path) -> Path:
    """wbs_root with a delivery.json whose ``locks`` block is all-null."""
    wbs = tmp_path / "wbs"
    wbs.mkdir()
    _write(wbs / DELIVERY_FILENAME, _minimal_locks_doc(_null_locks()))
    return wbs


@pytest.fixture
def expired_wbs(tmp_path: Path) -> Path:
    """wbs_root with a delivery.json whose lock expired in the past."""
    wbs = tmp_path / "wbs"
    wbs.mkdir()
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    older = past - timedelta(minutes=2)
    _write(
        wbs / DELIVERY_FILENAME,
        _minimal_locks_doc(
            {
                "holder": "ghost@1",
                "acquired_at": _iso(older),
                "expires_at": _iso(past),
                "ttl_seconds": 120,
            }
        ),
    )
    return wbs


@pytest.fixture
def kanban_wbs(tmp_path: Path) -> Path:
    """wbs_root with a schema-valid delivery.json suitable for KanbanView."""
    wbs = tmp_path / "wbs"
    wbs.mkdir()
    _write(wbs / DELIVERY_FILENAME, _single_module_payload(wbs))
    return wbs


# ─── C1 — happy path ─────────────────────────────────────────────────────── #


def test_c1_try_acquire_happy_path(empty_wbs: Path) -> None:
    service = LockService()
    acquired_signals: list[str] = []
    service.lock_acquired.connect(acquired_signals.append)

    result = service.try_acquire(empty_wbs, purpose="workflow-app.edit")

    try:
        assert isinstance(result, Acquired)
        assert result.holder.startswith("workflow-app.edit@")
        assert result.acquired_at.endswith("Z")
        assert result.expires_at.endswith("Z")
        assert service.is_held() is True
        assert acquired_signals == ["workflow-app.edit"]

        # delivery.json must reflect the new holder (not null).
        disk = json.loads((empty_wbs / DELIVERY_FILENAME).read_text())
        assert disk["locks"]["holder"] == result.holder
        assert disk["locks"]["expires_at"] == result.expires_at
    finally:
        service.release_and_stop()


# ─── C2 — busy (second acquire in same process) ──────────────────────────── #


def test_c2_try_acquire_busy(empty_wbs: Path) -> None:
    first = LockService()
    second = LockService()

    first_result = first.try_acquire(empty_wbs, purpose="workflow-app.edit")
    assert isinstance(first_result, Acquired)

    try:
        # Use wait=0 so we don't stall the test for the full poll budget.
        second_result = second.try_acquire(
            empty_wbs, purpose="workflow-app.other", wait=0
        )
        assert isinstance(second_result, Busy)
        assert second_result.holder == first_result.holder
        assert second_result.expires_at == first_result.expires_at
        assert second.is_held() is False
    finally:
        second.release_and_stop()
        first.release_and_stop()


# ─── C3 — expired lock reclaim ───────────────────────────────────────────── #


def test_c3_try_acquire_expired_reclaim(
    expired_wbs: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    service = LockService()
    try:
        result = service.try_acquire(expired_wbs, purpose="workflow-app.edit")
        assert isinstance(result, Acquired)
        assert result.holder.startswith("workflow-app.edit@")

        # DeliveryLock prints a stderr warning on reclaim (T-005 contract).
        captured = capsys.readouterr()
        assert "reclamando" in captured.err
    finally:
        service.release_and_stop()


# ─── C4 — release idempotent ─────────────────────────────────────────────── #


def test_c4_release_and_stop_is_idempotent(empty_wbs: Path) -> None:
    service = LockService()
    released_signals: list[int] = []
    service.lock_released.connect(lambda: released_signals.append(1))

    acquired = service.try_acquire(empty_wbs, purpose="workflow-app.edit")
    assert isinstance(acquired, Acquired)

    service.release_and_stop()
    service.release_and_stop()  # second call must not raise or re-emit
    service.release_and_stop()  # and a third for good measure

    assert service.is_held() is False
    assert service._heartbeat_timer.isActive() is False  # noqa: SLF001
    # Only ONE release signal fired (idempotent).
    assert released_signals == [1]


# ─── C5 — heartbeat extends expires_at ───────────────────────────────────── #


def test_c5_heartbeat_extends_expires_at(empty_wbs: Path) -> None:
    service = LockService()
    result = service.try_acquire(empty_wbs, purpose="workflow-app.edit")
    assert isinstance(result, Acquired)

    try:
        initial_expires = result.expires_at
        # Timestamps are second-resolution (ISO-Z, no microseconds), so a
        # 1s wait can flake on clock boundaries. 1600ms gives us a full
        # second of safety while still keeping the test under 2s.
        QTest.qWait(1600)

        service._on_heartbeat_tick()  # noqa: SLF001

        disk = json.loads((empty_wbs / DELIVERY_FILENAME).read_text())
        new_expires = disk["locks"]["expires_at"]
        assert new_expires > initial_expires
        assert service.is_held() is True
    finally:
        service.release_and_stop()


# ─── C6 — heartbeat loss emits lock_lost ─────────────────────────────────── #


def test_c6_heartbeat_loss_emits_lock_lost(empty_wbs: Path) -> None:
    service = LockService()
    lost_reasons: list[str] = []
    service.lock_lost.connect(lost_reasons.append)

    result = service.try_acquire(empty_wbs, purpose="workflow-app.edit")
    assert isinstance(result, Acquired)

    # Simulate another process stealing the lock: overwrite the holder
    # field via the SAME atomic helper production uses (os.replace), so
    # the test exercises the real loss path without flaking on a partial
    # read mid-rename (Codex R6).
    path = empty_wbs / DELIVERY_FILENAME
    doc = json.loads(path.read_text())
    future = datetime.now(timezone.utc) + timedelta(minutes=5)
    doc["locks"] = {
        "holder": "intruder@999",
        "acquired_at": _iso(datetime.now(timezone.utc)),
        "expires_at": _iso(future),
        "ttl_seconds": 120,
    }
    import sys
    atomic_mod = sys.modules["_delivery_lib_bridge.atomic_write"]
    atomic_mod.atomic_write_json(path, doc)

    service._on_heartbeat_tick()  # noqa: SLF001

    assert service.is_held() is False
    assert service._heartbeat_timer.isActive() is False  # noqa: SLF001
    assert len(lost_reasons) == 1
    assert "holder" in lost_reasons[0] or "heartbeat" in lost_reasons[0]

    # release_and_stop must still be safe after an externally-lost lock.
    service.release_and_stop()


# ─── C7 — read_current_holder ────────────────────────────────────────────── #


def test_c7_read_current_holder(empty_wbs: Path) -> None:
    service = LockService()

    # No holder → None.
    assert service.read_current_holder(empty_wbs) is None

    result = service.try_acquire(empty_wbs, purpose="workflow-app.edit")
    assert isinstance(result, Acquired)
    try:
        holder = service.read_current_holder(empty_wbs)
        assert isinstance(holder, str)
        assert holder.startswith("workflow-app.edit@")
    finally:
        service.release_and_stop()

    # After release → None again.
    assert service.read_current_holder(empty_wbs) is None

    # Pointing to a directory with no delivery.json must not raise.
    assert service.read_current_holder(empty_wbs.parent / "missing") is None


# ─── C8 — release safe when never acquired ───────────────────────────────── #


def test_c8_release_safe_when_never_acquired() -> None:
    service = LockService()
    # No acquire() was ever called — closeEvent must still be safe.
    service.release_and_stop()
    service.release_and_stop()
    assert service.is_held() is False


# ─── C9 — close flow integration ─────────────────────────────────────────── #


def test_c9_close_flow_writes_null_locks(empty_wbs: Path) -> None:
    service = LockService()
    result = service.try_acquire(empty_wbs, purpose="workflow-app.edit")
    assert isinstance(result, Acquired)

    service.release_and_stop()

    disk = json.loads((empty_wbs / DELIVERY_FILENAME).read_text())
    assert disk["locks"]["holder"] is None
    assert disk["locks"]["acquired_at"] is None
    assert disk["locks"]["expires_at"] is None
    # I-04 invariant: ttl_seconds is preserved (only the triple is nulled).
    assert disk["locks"]["ttl_seconds"] == 120


# ─── C10 — KanbanView auto-drives lock badge ─────────────────────────────── #


def test_c10_kanban_auto_drives_lock_badge(kanban_wbs: Path) -> None:
    # Step 1: load with no holder — badge must be hidden.
    reader = DeliveryReader()
    view = KanbanView(reader=reader)
    view.load(kanban_wbs)
    view.show()
    QTest.qWait(20)
    assert view._lock_badge.isHidden() is True  # noqa: SLF001

    # Step 2: mutate delivery.json to set a holder and refresh.
    path = kanban_wbs / DELIVERY_FILENAME
    doc = json.loads(path.read_text())
    future = datetime.now(timezone.utc) + timedelta(minutes=5)
    doc["locks"] = {
        "holder": "cli@123",
        "acquired_at": _iso(datetime.now(timezone.utc)),
        "expires_at": _iso(future),
        "ttl_seconds": 120,
    }
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")

    view.refresh()
    QTest.qWait(20)
    assert view._lock_badge.isHidden() is False  # noqa: SLF001
    assert view._lock_badge.text() == "LOCKED by cli@123"  # noqa: SLF001

    # Step 3: clear the holder again and refresh — badge must hide.
    doc["locks"] = _null_locks()
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    view.refresh()
    QTest.qWait(20)
    assert view._lock_badge.isHidden() is True  # noqa: SLF001
    assert view._lock_badge.text() == ""  # noqa: SLF001
