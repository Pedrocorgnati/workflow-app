"""Recognition + lane-containment tests for the mkt-assets loop mode.

Item 009 of loop 06-18-marketing-pipeline-30d-instagram-feed registers the new
top-level discriminator ``mode == "mkt_assets"`` in the shared loop loader. The
``/mkt-assets`` lane is a twin of ``/loop`` (preparo -> iteration_template ->
finalizacao) that reuses ``build_loop_specs``, distinguished by the discriminator
and per-iteration commands in the ``/mkt-assets:*`` namespace.

Contract: ``daily_loop/CONTRACT.md`` section 2.3 (enum row + lane containment).

Unlike rocksmash, mkt_assets has NO fixed token count — only lane containment:
iteration items may only dispatch ``/mkt-assets:*`` tokens (after stripping
/clear|/model|/effort). preparo/finalizacao items are skipped (cross-lane
housekeeping allowed). Pre-integration empty ``commands`` is tolerated.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from workflow_app.daily_loop import (
    DailyLoopConfigError,
    assert_mkt_assets_iteration_shape,
    is_mkt_assets_mode,
)
from workflow_app.daily_loop.loader import build_daily_loop_specs, build_loop_specs


# ────────────────────────────────────────────────────────────────────────────
# Helpers (self-contained, mirror test_daily_loop_commands_precedence.py)
# ────────────────────────────────────────────────────────────────────────────


def _write_progress(
    loop_root: Path, items: list[tuple[str, str, str, str]]
) -> None:
    lines = [
        "# Loop Progress: mkt-assets-slug",
        "",
        "## Items",
        "",
        "| ID  | Status | Target | Bucket | Updated |",
        "|-----|--------|--------|--------|---------|",
    ]
    for item_id, mark, target, bucket in items:
        lines.append(f"| {item_id} | [{mark}] | {target} | {bucket} | - |")
    (loop_root / "PROGRESS.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def _cfg(
    loop_root: Path,
    items_field: list,
    *,
    mode: str | None = "mkt_assets",
    integration_done: bool = True,
) -> dict:
    cfg: dict = {
        "name": "mkt-assets-slug",
        "kind": "daily-loop",
        "basic_flow": {
            "brief_root": str(loop_root),
            "docs_root": str(loop_root),
            "wbs_root": str(loop_root),
            "workspace_root": str(loop_root.parent),
        },
        "daily_loop": {
            "version": "1.1.0",
            "slug": "mkt-assets-slug",
            "loop_root": str(loop_root),
            "progress_path": "PROGRESS.md",
            "tasks_dir": "tasks",
            "log_path": "_LOOP-LOG.md",
            "total_items": len(items_field),
            "buckets": [
                {
                    "id": "T-sonnet-standard",
                    "model": "sonnet",
                    "effort": "standard",
                    "task_file": "tasks/T-sonnet-standard.md",
                    "items": items_field,
                    "items_count": len(items_field),
                }
            ],
            "do_command": "/mkt-assets:iteraction:execute-task",
            "review_done_command": "/mkt-assets:iteraction:review-executed-loop",
        },
    }
    if mode is not None:
        cfg["mode"] = mode
    if integration_done:
        cfg["metadata"] = {"integration_completed_at": "2026-06-18T16:08:57Z"}
    return cfg


def _mkt_iteration_commands(slug_path: str) -> list[str]:
    return [
        "/clear",
        "/model sonnet",
        "/effort standard",
        f"/mkt-assets:iteraction:create-task --task {slug_path}",
        f"/mkt-assets:iteraction:review-created-task --task {slug_path}",
        f"/mkt-assets:iteraction:execute-task --task {slug_path}",
        f"/mkt-assets:iteraction:review-executed-task --task {slug_path}",
    ]


@pytest.fixture
def loop_root(tmp_path: Path) -> Path:
    root = tmp_path / "loop-archives" / "mkt-assets-slug"
    root.mkdir(parents=True)
    (root / "tasks").mkdir()
    return root


# ────────────────────────────────────────────────────────────────────────────
# is_mkt_assets_mode — discriminator recognition
# ────────────────────────────────────────────────────────────────────────────


class TestIsMktAssetsMode:
    def test_exact_match(self) -> None:
        assert is_mkt_assets_mode({"mode": "mkt_assets"}) is True

    def test_case_insensitive_and_whitespace(self) -> None:
        assert is_mkt_assets_mode({"mode": "  MKT_Assets  "}) is True

    def test_other_modes_are_false(self) -> None:
        for m in ("rocksmash", "task", "cmd", "cmd-single", "both", "normal"):
            assert is_mkt_assets_mode({"mode": m}) is False

    def test_missing_mode_is_false(self) -> None:
        assert is_mkt_assets_mode({}) is False

    def test_non_string_mode_is_false(self) -> None:
        assert is_mkt_assets_mode({"mode": 42}) is False


# ────────────────────────────────────────────────────────────────────────────
# assert_mkt_assets_iteration_shape — lane containment gate
# ────────────────────────────────────────────────────────────────────────────


class TestAssertMktAssetsIterationShape:
    def test_noop_for_non_mkt_assets_mode(self) -> None:
        # Out-of-lane tokens are irrelevant when mode != mkt_assets.
        cfg = {
            "mode": "both",
            "daily_loop": {
                "buckets": [
                    {"items": [{"id": "002", "kind": "iteration",
                                "commands": ["/cmd:create x"]}]}
                ]
            },
        }
        assert_mkt_assets_iteration_shape(cfg)  # must not raise

    def test_valid_lane_tokens_pass(self) -> None:
        cfg = {
            "mode": "mkt_assets",
            "metadata": {"integration_completed_at": "2026-06-18T00:00:00Z"},
            "daily_loop": {
                "buckets": [
                    {"items": [{"id": "002", "kind": "iteration",
                                "commands": _mkt_iteration_commands("t.md")}]}
                ]
            },
        }
        assert_mkt_assets_iteration_shape(cfg)  # must not raise

    def test_out_of_lane_token_raises(self) -> None:
        cfg = {
            "mode": "mkt_assets",
            "metadata": {"integration_completed_at": "2026-06-18T00:00:00Z"},
            "daily_loop": {
                "buckets": [
                    {"items": [{"id": "002", "kind": "iteration",
                                "commands": [
                                    "/mkt-assets:iteraction:execute-task --task t.md",
                                    "/loop:iteraction:execute-task --task t.md",
                                ]}]}
                ]
            },
        }
        with pytest.raises(DailyLoopConfigError) as exc:
            assert_mkt_assets_iteration_shape(cfg)
        assert "002" in str(exc.value)
        assert "/loop:iteraction:execute-task" in str(exc.value)

    def test_preparo_and_finalizacao_skipped(self) -> None:
        # Lifecycle slots may carry cross-lane housekeeping.
        cfg = {
            "mode": "mkt_assets",
            "metadata": {"integration_completed_at": "2026-06-18T00:00:00Z"},
            "daily_loop": {
                "buckets": [
                    {"items": [
                        {"id": "001", "kind": "preparo",
                         "commands": ["/mkt-assets:iteraction:execute-task --task p.md"]},
                        {"id": "011", "kind": "finalizacao",
                         "commands": [
                             "/loop:iteraction:review-executed-loop --name mkt-assets-slug",
                         ]},
                    ]}
                ]
            },
        }
        assert_mkt_assets_iteration_shape(cfg)  # must not raise

    def test_empty_commands_tolerated_pre_integration(self) -> None:
        cfg = {
            "mode": "mkt_assets",
            # no metadata.integration_completed_at
            "daily_loop": {
                "buckets": [
                    {"items": [{"id": "002", "kind": "iteration", "commands": []}]}
                ]
            },
        }
        assert_mkt_assets_iteration_shape(cfg)  # must not raise

    def test_empty_commands_rejected_post_integration(self) -> None:
        cfg = {
            "mode": "mkt_assets",
            "metadata": {"integration_completed_at": "2026-06-18T00:00:00Z"},
            "daily_loop": {
                "buckets": [
                    {"items": [{"id": "002", "kind": "iteration", "commands": []}]}
                ]
            },
        }
        with pytest.raises(DailyLoopConfigError) as exc:
            assert_mkt_assets_iteration_shape(cfg)
        assert "002" in str(exc.value)

    def test_commands_not_list_raises(self) -> None:
        cfg = {
            "mode": "mkt_assets",
            "metadata": {"integration_completed_at": "2026-06-18T00:00:00Z"},
            "daily_loop": {
                "buckets": [
                    {"items": [{"id": "002", "kind": "iteration",
                                "commands": "not-a-list"}]}
                ]
            },
        }
        with pytest.raises(DailyLoopConfigError):
            assert_mkt_assets_iteration_shape(cfg)


# ────────────────────────────────────────────────────────────────────────────
# build_loop_specs — end-to-end recognition (no regression)
# ────────────────────────────────────────────────────────────────────────────


class TestBuildLoopSpecsMktAssets:
    def test_expands_valid_mkt_assets_loop(self, loop_root: Path) -> None:
        task = "blacksmith/loop-archives/mkt-assets-slug/tasks/items/task-002.md"
        items = [
            {"id": "002", "kind": "iteration",
             "commands": _mkt_iteration_commands(task)},
        ]
        _write_progress(loop_root, [("002", " ", "task-002.md", "T-sonnet-standard")])
        specs = build_loop_specs(_cfg(loop_root, items), loop_root)
        names = [s.name for s in specs]
        # the four /mkt-assets: tokens survive into the queue
        assert any(n.startswith("/mkt-assets:iteraction:execute-task") for n in names)
        assert any(n.startswith("/mkt-assets:iteraction:create-task") for n in names)

    def test_out_of_lane_loop_rejected(self, loop_root: Path) -> None:
        task = "blacksmith/loop-archives/mkt-assets-slug/tasks/items/task-002.md"
        bad = _mkt_iteration_commands(task)
        bad.append(f"/cmd:create {task}")  # out-of-lane contamination
        items = [{"id": "002", "kind": "iteration", "commands": bad}]
        _write_progress(loop_root, [("002", " ", "task-002.md", "T-sonnet-standard")])
        with pytest.raises(DailyLoopConfigError):
            build_loop_specs(_cfg(loop_root, items), loop_root)

    def test_non_mkt_assets_mode_unaffected(self, loop_root: Path) -> None:
        # Regression guard: a --both loop with /cmd:* + /loop:* tokens still
        # expands fine because the mkt-assets gate is a noop for mode != mkt_assets.
        task = "blacksmith/loop-archives/mkt-assets-slug/tasks/items/task-002.md"
        items = [
            {"id": "002", "kind": "iteration",
             "commands": [
                 "/clear",
                 f"/loop:iteraction:create-task --task {task}",
                 f"/loop:iteraction:execute-task --task {task}",
             ]},
        ]
        _write_progress(loop_root, [("002", " ", "task-002.md", "T-sonnet-standard")])
        specs = build_loop_specs(
            _cfg(loop_root, items, mode="both"), loop_root
        )
        names = [s.name for s in specs]
        assert any(n.startswith("/loop:iteraction:execute-task") for n in names)


# ────────────────────────────────────────────────────────────────────────────
# build_daily_loop_specs — defensive-parity recognition (loader.py L1532)
# ────────────────────────────────────────────────────────────────────────────


class TestBuildDailyLoopSpecsMktAssets:
    """Parity coverage for the build_daily_loop_specs mkt_assets hook.

    The loader recognizes ``mode == "mkt_assets"`` in build_daily_loop_specs as
    well ("paridade defensiva" per daily_loop/CONTRACT.md), not only in
    build_loop_specs. This guards the V3 daily_loop entry-point against the same
    out-of-lane drift the discovery gate exists to catch.
    """

    def test_expands_valid_mkt_assets_loop(self, loop_root: Path) -> None:
        task = "blacksmith/loop-archives/mkt-assets-slug/tasks/items/task-002.md"
        items = [
            {"id": "002", "kind": "iteration",
             "commands": _mkt_iteration_commands(task)},
        ]
        _write_progress(loop_root, [("002", " ", "task-002.md", "T-sonnet-standard")])
        specs = build_daily_loop_specs(_cfg(loop_root, items), loop_root)
        names = [s.name for s in specs]
        # the /mkt-assets: tokens survive into the queue via the V3 entry-point
        assert any(n.startswith("/mkt-assets:iteraction:execute-task") for n in names)
        assert any(n.startswith("/mkt-assets:iteraction:create-task") for n in names)

    def test_out_of_lane_loop_rejected(self, loop_root: Path) -> None:
        task = "blacksmith/loop-archives/mkt-assets-slug/tasks/items/task-002.md"
        bad = _mkt_iteration_commands(task)
        bad.append(f"/cmd:create {task}")  # out-of-lane contamination
        items = [{"id": "002", "kind": "iteration", "commands": bad}]
        _write_progress(loop_root, [("002", " ", "task-002.md", "T-sonnet-standard")])
        with pytest.raises(DailyLoopConfigError):
            build_daily_loop_specs(_cfg(loop_root, items), loop_root)
