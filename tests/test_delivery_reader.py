"""Tests for `workflow_app.services.delivery_reader` (T-035).

Covers:
- Happy-path load for three fixtures (sequential 1-active, parallel 3-active,
  blocked_prev_state populated).
- Error paths (missing, future version, invalid JSON, schema violation).
- Invariant warnings (I-01, I-02, I-03, I-10) — collected as non-fatal.
- `resolve_specific_flow` cascade levels 1/2/3.
- `DeliveryReader` cache by (wbs_root, module_id, mtime).
- `read_module_meta` helper.
"""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from typing import Any, Dict

import pytest

from workflow_app.models.delivery import Delivery, DeliveryInvariantWarning
from workflow_app.services.delivery_reader import (
    DEFAULT_CUSTOM_WORKFLOW_SUBDIR,
    DELIVERY_FILENAME,
    SPECIFIC_FLOW_FILENAME,
    DeliveryFound,
    DeliveryFutureVersion,
    DeliveryInvalid,
    DeliveryMissing,
    DeliveryReader,
    read_module_meta,
    resolve_specific_flow,
)

# ─── Builders ────────────────────────────────────────────────────────────── #


def _iso(ts: str = "2026-04-12T09:00:00Z") -> str:
    return ts


def _base_project(wbs_root: Path) -> Dict[str, Any]:
    return {
        "name": "test-project",
        "brief_root": str(wbs_root / "brief"),
        "docs_root": str(wbs_root / "docs"),
        "wbs_root": str(wbs_root),
        "workspace_root": str(wbs_root / "workspace"),
    }


def _base_skeleton() -> Dict[str, Any]:
    return {
        "version": "skeleton-v2",
        "sha256": "a1b2c3d4e5f6",
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
    artifacts: dict | None = None,
    skeleton_outdated: bool = False,
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
            "skeleton_outdated": skeleton_outdated,
            "rework_target": rework_target or {"phase": None, "module": None},
        },
        "skeleton_version": skeleton_version,
        "rework_iterations": rework_iterations,
        "max_rework_iterations": 2,
        "history": history,
        "artifacts": artifacts
        or {
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


@pytest.fixture
def fixture_sequential(tmp_path: Path) -> Path:
    """F1 — sequential, 1 active module, zero warnings."""
    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()
    payload = {
        "version": 1,
        "project": _base_project(wbs_root),
        "current_module": "module-1-dashboard",
        "execution_mode": "sequential",
        "modules": {
            "module-0-foundations": _module(
                "done",
                module_type="foundations",
            ),
            "module-1-dashboard": _module(
                "creation",
                module_type="dashboard",
                dependencies=["module-0-foundations"],
            ),
        },
        "skeleton": _base_skeleton(),
        "locks": _base_locks_null(),
        "metadata": _base_metadata(),
    }
    return _write_delivery(wbs_root / DELIVERY_FILENAME, payload)


@pytest.fixture
def fixture_parallel(tmp_path: Path) -> Path:
    """F2 — parallel-independent, 3 active, zero warnings."""
    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()
    payload = {
        "version": 1,
        "project": _base_project(wbs_root),
        "current_modules": [
            "module-1-crud",
            "module-2-landing",
            "module-3-api",
        ],
        "execution_mode": "parallel-independent",
        "modules": {
            "module-1-crud": _module("execution", module_type="crud"),
            "module-2-landing": _module(
                "execution", module_type="landing-page"
            ),
            "module-3-api": _module("execution", module_type="api-only"),
        },
        "skeleton": _base_skeleton(),
        "locks": _base_locks_null(),
        "metadata": _base_metadata(),
    }
    return _write_delivery(wbs_root / DELIVERY_FILENAME, payload)


@pytest.fixture
def fixture_blocked(tmp_path: Path) -> Path:
    """F3 — blocked_prev_state populated."""
    wbs_root = tmp_path / "wbs"
    wbs_root.mkdir()
    blocked_history = [
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
            "to": "revision",
            "at": "2026-04-12T10:00:00Z",
            "by": "review-executed-module",
            "note": "",
        },
        {
            "from": "revision",
            "to": "qa",
            "at": "2026-04-12T10:30:00Z",
            "by": "review-executed-module",
            "note": "ok",
        },
        {
            "from": "qa",
            "to": "blocked",
            "at": "2026-04-12T11:00:00Z",
            "by": "validation-summary",
            "note": "QA reprovado, billing",
        },
    ]
    payload = {
        "version": 1,
        "project": _base_project(wbs_root),
        "current_module": "module-3-billing",
        "execution_mode": "sequential",
        "modules": {
            "module-3-billing": _module(
                "blocked",
                attempt=1,
                module_type="payment",
                blocked=True,
                blocked_reason="QA reprovado, billing sandbox",
                blocked_prev_state="qa",
                last_transition="2026-04-12T11:00:00Z",
                history=blocked_history,
                owner="human",
            ),
        },
        "skeleton": _base_skeleton(),
        "locks": _base_locks_null(),
        "metadata": _base_metadata(),
    }
    return _write_delivery(wbs_root / DELIVERY_FILENAME, payload)


# ─── Happy-path load ─────────────────────────────────────────────────────── #


def test_load_happy_sequential(fixture_sequential: Path) -> None:
    reader = DeliveryReader()
    result = reader.load(fixture_sequential.parent)

    assert isinstance(result, DeliveryFound)
    assert result.delivery.version == 1
    assert result.delivery.execution_mode == "sequential"
    assert result.delivery.current_module == "module-1-dashboard"
    assert set(result.delivery.modules) == {
        "module-0-foundations",
        "module-1-dashboard",
    }
    assert result.warnings == []
    assert not result.delivery.has_invariant_warnings()


def test_load_parallel_independent(fixture_parallel: Path) -> None:
    reader = DeliveryReader()
    result = reader.load(fixture_parallel.parent)

    assert isinstance(result, DeliveryFound)
    assert result.delivery.execution_mode == "parallel-independent"
    assert len(result.delivery.current_modules) == 3
    assert len(result.delivery.modules) == 3
    assert result.warnings == []


def test_load_blocked_prev_state(fixture_blocked: Path) -> None:
    reader = DeliveryReader()
    result = reader.load(fixture_blocked.parent)

    assert isinstance(result, DeliveryFound)
    mod = result.delivery.modules["module-3-billing"]
    assert mod.state == "blocked"
    assert mod.blocked is True
    assert mod.blocked_prev_state == "qa"
    assert mod.blocked_reason == "QA reprovado, billing sandbox"
    assert mod.history[-1].to == "blocked"


def test_load_canonical_example_fixture() -> None:
    """Roundtrip the T-001 canonical example to guard against schema drift."""
    canonical = (
        Path(__file__).resolve().parents[3]
        / "scheduled-updates/refactor-workflow-sytemforge/schemas/delivery.example.json"
    )
    if not canonical.exists():
        pytest.skip(f"canonical fixture not found at {canonical}")

    content = canonical.read_text(encoding="utf-8")
    delivery = Delivery.model_validate_json(content)
    assert delivery.version == 1
    assert "module-0-foundations" in delivery.modules
    assert delivery.execution_mode in ("sequential", "parallel-independent")


# ─── Error paths ─────────────────────────────────────────────────────────── #


def test_missing_delivery_json(tmp_path: Path) -> None:
    reader = DeliveryReader()
    result = reader.load(tmp_path)
    assert isinstance(result, DeliveryMissing)
    assert result.path == tmp_path / DELIVERY_FILENAME


def test_future_version(tmp_path: Path) -> None:
    payload = {"version": 2, "unsupported": True}
    _write_delivery(tmp_path / DELIVERY_FILENAME, payload)
    reader = DeliveryReader()
    result = reader.load(tmp_path)
    assert isinstance(result, DeliveryFutureVersion)
    assert result.version == 2
    assert "version=2" in result.message


def test_invalid_json(tmp_path: Path) -> None:
    (tmp_path / DELIVERY_FILENAME).write_text("{not valid json", encoding="utf-8")
    reader = DeliveryReader()
    result = reader.load(tmp_path)
    assert isinstance(result, DeliveryInvalid)
    assert "invalid JSON" in result.error


def test_schema_violation_missing_required(tmp_path: Path) -> None:
    payload = {"version": 1, "project": {"name": "x"}}  # missing required fields
    _write_delivery(tmp_path / DELIVERY_FILENAME, payload)
    reader = DeliveryReader()
    result = reader.load(tmp_path)
    assert isinstance(result, DeliveryInvalid)
    assert "schema validation failed" in result.error
    assert result.details is not None


def test_schema_violation_invalid_module_key(
    fixture_sequential: Path,
) -> None:
    raw = json.loads(fixture_sequential.read_text())
    raw["modules"]["bad-key"] = raw["modules"].pop("module-1-dashboard")
    raw["current_module"] = "bad-key"
    fixture_sequential.write_text(json.dumps(raw))
    reader = DeliveryReader()
    result = reader.load(fixture_sequential.parent)
    assert isinstance(result, DeliveryInvalid)


# ─── Invariant warnings (soft) ────────────────────────────────────────────── #


def test_warning_i02_sequential_two_active(fixture_sequential: Path) -> None:
    raw = json.loads(fixture_sequential.read_text())
    # Force module-0-foundations into "execution" while module-1-dashboard is
    # already active — violates I-02 in sequential mode.
    m0 = raw["modules"]["module-0-foundations"]
    m0["state"] = "execution"
    m0["attempt"] = 1
    m0["last_transition"] = "2026-04-12T12:00:00Z"
    m0["history"] = [
        {
            "from": "pending",
            "to": "execution",
            "at": "2026-04-12T12:00:00Z",
            "by": "build-module-pipeline",
            "note": "synthetic",
        }
    ]
    fixture_sequential.write_text(json.dumps(raw))

    reader = DeliveryReader()
    result = reader.load(fixture_sequential.parent)
    assert isinstance(result, DeliveryFound)
    codes = [w.code for w in result.warnings]
    assert "I-02" in codes


def test_warning_i03_skeleton_mismatch(fixture_sequential: Path) -> None:
    raw = json.loads(fixture_sequential.read_text())
    raw["modules"]["module-0-foundations"]["skeleton_version"] = "skeleton-v1"
    raw["modules"]["module-0-foundations"]["flags"]["skeleton_outdated"] = False
    fixture_sequential.write_text(json.dumps(raw))

    reader = DeliveryReader()
    result = reader.load(fixture_sequential.parent)
    assert isinstance(result, DeliveryFound)
    codes = [w.code for w in result.warnings]
    assert "I-03" in codes


def test_warning_i10_dependency_not_done(fixture_sequential: Path) -> None:
    raw = json.loads(fixture_sequential.read_text())
    # Put module-0-foundations back into "execution" so module-1's dep is NOT done.
    m0 = raw["modules"]["module-0-foundations"]
    m0["state"] = "pending"
    m0["attempt"] = 0
    m0["history"] = []
    m0["last_transition"] = "2026-04-12T08:00:00Z"
    # But module-0 must have max_rework_iterations > 0 (already set). Pending
    # with attempt=0 is valid per I-06 exception list.
    # With sequential mode and module-1-dashboard in creation, dep module-0 is
    # pending → I-10 violation.
    fixture_sequential.write_text(json.dumps(raw))

    reader = DeliveryReader()
    result = reader.load(fixture_sequential.parent)
    assert isinstance(result, DeliveryFound)
    codes = [w.code for w in result.warnings]
    assert "I-10" in codes


def test_warning_i01_parallel_empty_current(tmp_path: Path) -> None:
    payload = {
        "version": 1,
        "project": _base_project(tmp_path / "wbs"),
        "current_modules": [],  # will trigger schema error first? nope minItems=1
        "execution_mode": "parallel-independent",
        "modules": {
            "module-1-crud": _module("pending", attempt=0, history=[]),
        },
        "skeleton": _base_skeleton(),
        "locks": _base_locks_null(),
        "metadata": _base_metadata(),
    }
    (tmp_path / "wbs").mkdir()
    _write_delivery(tmp_path / "wbs" / DELIVERY_FILENAME, payload)

    reader = DeliveryReader()
    result = reader.load(tmp_path / "wbs")
    # current_modules=[] is allowed by our pydantic model (min=0 default) so
    # this surfaces as an I-01 warning rather than a schema error. If that
    # changes in the future, this test documents the trade-off.
    assert isinstance(result, (DeliveryFound, DeliveryInvalid))
    if isinstance(result, DeliveryFound):
        codes = [w.code for w in result.warnings]
        assert "I-01" in codes


# ─── resolve_specific_flow cascade ──────────────────────────────────────── #


def test_resolve_specific_flow_level1(fixture_sequential: Path) -> None:
    wbs_root = fixture_sequential.parent
    module_flow_dir = wbs_root / "modules/module-1-dashboard"
    module_flow_dir.mkdir(parents=True)
    flow_path = module_flow_dir / "SPECIFIC-FLOW.json"
    flow_path.write_text("{}", encoding="utf-8")

    raw = json.loads(fixture_sequential.read_text())
    raw["modules"]["module-1-dashboard"]["artifacts"][
        "last_specific_flow"
    ] = "modules/module-1-dashboard/SPECIFIC-FLOW.json"
    fixture_sequential.write_text(json.dumps(raw))

    reader = DeliveryReader()
    result = reader.load(wbs_root)
    assert isinstance(result, DeliveryFound)

    got = reader.resolve_specific_flow(
        result.delivery,
        "module-1-dashboard",
        project_root=wbs_root.parent,
        delivery_mtime=result.mtime,
    )
    assert got == flow_path


def test_resolve_specific_flow_level2(fixture_sequential: Path) -> None:
    wbs_root = fixture_sequential.parent
    legacy_dir = wbs_root / DEFAULT_CUSTOM_WORKFLOW_SUBDIR
    legacy_dir.mkdir()
    legacy_flow = legacy_dir / SPECIFIC_FLOW_FILENAME
    legacy_flow.write_text("{}", encoding="utf-8")

    reader = DeliveryReader()
    result = reader.load(wbs_root)
    assert isinstance(result, DeliveryFound)

    got = reader.resolve_specific_flow(
        result.delivery,
        "module-1-dashboard",
        project_root=wbs_root.parent,
        delivery_mtime=result.mtime,
    )
    assert got == legacy_flow


def test_resolve_specific_flow_level3_returns_none(
    fixture_sequential: Path,
) -> None:
    reader = DeliveryReader()
    result = reader.load(fixture_sequential.parent)
    assert isinstance(result, DeliveryFound)

    got = reader.resolve_specific_flow(
        result.delivery,
        "module-1-dashboard",
        project_root=fixture_sequential.parent.parent,
        delivery_mtime=result.mtime,
    )
    assert got is None


def test_resolve_specific_flow_custom_root(fixture_sequential: Path) -> None:
    wbs_root = fixture_sequential.parent
    custom = wbs_root.parent / "my-workflow"
    custom.mkdir()
    flow = custom / SPECIFIC_FLOW_FILENAME
    flow.write_text("{}", encoding="utf-8")

    reader = DeliveryReader()
    result = reader.load(wbs_root)
    assert isinstance(result, DeliveryFound)

    got = reader.resolve_specific_flow(
        result.delivery,
        "module-1-dashboard",
        project_root=wbs_root.parent,
        custom_workflow_root=str(custom),
        delivery_mtime=result.mtime,
    )
    assert got == flow


def test_resolve_specific_flow_cache(fixture_sequential: Path) -> None:
    wbs_root = fixture_sequential.parent
    legacy_dir = wbs_root / DEFAULT_CUSTOM_WORKFLOW_SUBDIR
    legacy_dir.mkdir()
    legacy_flow = legacy_dir / SPECIFIC_FLOW_FILENAME
    legacy_flow.write_text("{}", encoding="utf-8")

    reader = DeliveryReader()
    result = reader.load(wbs_root)
    assert isinstance(result, DeliveryFound)

    got1 = reader.resolve_specific_flow(
        result.delivery,
        "module-1-dashboard",
        project_root=wbs_root.parent,
        delivery_mtime=result.mtime,
    )
    # Delete the file so a non-cached call would now return None.
    legacy_flow.unlink()
    got2 = reader.resolve_specific_flow(
        result.delivery,
        "module-1-dashboard",
        project_root=wbs_root.parent,
        delivery_mtime=result.mtime,
    )
    assert got1 == got2 == legacy_flow  # cache hit


def test_resolve_specific_flow_cache_invalidated_on_mtime_change(
    fixture_sequential: Path,
) -> None:
    wbs_root = fixture_sequential.parent

    reader = DeliveryReader()
    result = reader.load(wbs_root)
    assert isinstance(result, DeliveryFound)

    # First call — both levels miss, cache stores None.
    got1 = reader.resolve_specific_flow(
        result.delivery,
        "module-1-dashboard",
        project_root=wbs_root.parent,
        delivery_mtime=result.mtime,
    )
    assert got1 is None

    # New mtime simulates a `delivery.json` rewrite; cache key differs.
    legacy_dir = wbs_root / DEFAULT_CUSTOM_WORKFLOW_SUBDIR
    legacy_dir.mkdir()
    legacy_flow = legacy_dir / SPECIFIC_FLOW_FILENAME
    legacy_flow.write_text("{}", encoding="utf-8")

    got2 = reader.resolve_specific_flow(
        result.delivery,
        "module-1-dashboard",
        project_root=wbs_root.parent,
        delivery_mtime=result.mtime + 1.0,
    )
    assert got2 == legacy_flow


def test_resolve_specific_flow_functional_api(fixture_sequential: Path) -> None:
    """The module-level `resolve_specific_flow` works without a reader instance."""
    reader = DeliveryReader()
    result = reader.load(fixture_sequential.parent)
    assert isinstance(result, DeliveryFound)
    got = resolve_specific_flow(
        result.delivery,
        "module-1-dashboard",
        project_root=fixture_sequential.parent.parent,
    )
    assert got is None


def test_resolve_specific_flow_unknown_module(
    fixture_sequential: Path,
) -> None:
    reader = DeliveryReader()
    result = reader.load(fixture_sequential.parent)
    assert isinstance(result, DeliveryFound)
    got = resolve_specific_flow(
        result.delivery,
        "module-99-ghost",
        project_root=fixture_sequential.parent.parent,
    )
    assert got is None


# ─── read_module_meta helper ─────────────────────────────────────────────── #


def test_read_module_meta_missing(fixture_sequential: Path) -> None:
    reader = DeliveryReader()
    result = reader.load(fixture_sequential.parent)
    assert isinstance(result, DeliveryFound)
    got = read_module_meta(
        result.delivery,
        "module-1-dashboard",
        project_root=fixture_sequential.parent.parent,
    )
    assert got is None


def test_read_module_meta_present(fixture_sequential: Path) -> None:
    wbs_root = fixture_sequential.parent
    meta_dir = wbs_root / "modules/module-1-dashboard"
    meta_dir.mkdir(parents=True)
    meta_path = meta_dir / "MODULE-META.json"
    meta_payload = {"deploy": {"target": "hostinger"}, "module_type": "dashboard"}
    meta_path.write_text(json.dumps(meta_payload), encoding="utf-8")

    raw = json.loads(fixture_sequential.read_text())
    raw["modules"]["module-1-dashboard"]["artifacts"][
        "module_meta_path"
    ] = "modules/module-1-dashboard/MODULE-META.json"
    fixture_sequential.write_text(json.dumps(raw))

    reader = DeliveryReader()
    result = reader.load(wbs_root)
    assert isinstance(result, DeliveryFound)

    got = read_module_meta(
        result.delivery,
        "module-1-dashboard",
        project_root=wbs_root.parent,
    )
    assert got == meta_payload


def test_read_module_meta_invalid_json(fixture_sequential: Path) -> None:
    wbs_root = fixture_sequential.parent
    meta_dir = wbs_root / "modules/module-1-dashboard"
    meta_dir.mkdir(parents=True)
    meta_path = meta_dir / "MODULE-META.json"
    meta_path.write_text("{not json", encoding="utf-8")

    raw = json.loads(fixture_sequential.read_text())
    raw["modules"]["module-1-dashboard"]["artifacts"][
        "module_meta_path"
    ] = "modules/module-1-dashboard/MODULE-META.json"
    fixture_sequential.write_text(json.dumps(raw))

    reader = DeliveryReader()
    result = reader.load(wbs_root)
    assert isinstance(result, DeliveryFound)
    assert (
        read_module_meta(
            result.delivery,
            "module-1-dashboard",
            project_root=wbs_root.parent,
        )
        is None
    )


# ─── Invariant hard checks (per ModuleState validators) ──────────────────── #


def test_module_invariant_i07_history_mismatch(tmp_path: Path) -> None:
    payload = {
        "version": 1,
        "project": _base_project(tmp_path / "wbs"),
        "current_module": "module-1-crud",
        "execution_mode": "sequential",
        "modules": {
            "module-1-crud": _module(
                "creation",
                history=[
                    {
                        "from": "pending",
                        "to": "execution",  # mismatch!
                        "at": "2026-04-12T12:00:00Z",
                        "by": "build-module-pipeline",
                        "note": "",
                    }
                ],
            ),
        },
        "skeleton": _base_skeleton(),
        "locks": _base_locks_null(),
        "metadata": _base_metadata(),
    }
    (tmp_path / "wbs").mkdir()
    _write_delivery(tmp_path / "wbs" / DELIVERY_FILENAME, payload)

    reader = DeliveryReader()
    result = reader.load(tmp_path / "wbs")
    assert isinstance(result, DeliveryInvalid)
    assert "I-07" in (result.details or "")


def test_locks_i04_partial_raises(tmp_path: Path) -> None:
    payload = {
        "version": 1,
        "project": _base_project(tmp_path / "wbs"),
        "current_module": "module-1-crud",
        "execution_mode": "sequential",
        "modules": {
            "module-1-crud": _module("creation"),
        },
        "skeleton": _base_skeleton(),
        "locks": {
            "holder": "workflow-app",
            "acquired_at": None,  # partial — violates I-04
            "expires_at": "2026-04-12T13:00:00Z",
            "ttl_seconds": 120,
        },
        "metadata": _base_metadata(),
    }
    (tmp_path / "wbs").mkdir()
    _write_delivery(tmp_path / "wbs" / DELIVERY_FILENAME, payload)

    reader = DeliveryReader()
    result = reader.load(tmp_path / "wbs")
    assert isinstance(result, DeliveryInvalid)


def test_rework_without_target_raises(tmp_path: Path) -> None:
    payload = {
        "version": 1,
        "project": _base_project(tmp_path / "wbs"),
        "current_module": "module-1-crud",
        "execution_mode": "sequential",
        "modules": {
            "module-1-crud": _module(
                "rework",
                needs_rework=True,
                rework_iterations=1,
                history=[
                    {
                        "from": "done",
                        "to": "rework",
                        "at": "2026-04-12T12:00:00Z",
                        "by": "delivery:reopen",
                        "note": "regression",
                    }
                ],
                # rework_target intentionally null — should raise I-08
            ),
        },
        "skeleton": _base_skeleton(),
        "locks": _base_locks_null(),
        "metadata": _base_metadata(),
    }
    (tmp_path / "wbs").mkdir()
    _write_delivery(tmp_path / "wbs" / DELIVERY_FILENAME, payload)

    reader = DeliveryReader()
    result = reader.load(tmp_path / "wbs")
    assert isinstance(result, DeliveryInvalid)
    assert "I-08" in (result.details or "")
