"""Regression + contract tests for workflow_app.daily_loop.loader.

Covers the path-resolution contract (v1.1) introduced after the Onda 8 bug
where multi-segment relative `progress_path` values were silently joined to
`loop_root.parent`, producing path duplication like
`blacksmith/loop-archives/blacksmith/loop-archives/{slug}/PROGRESS.md`.

Contract enforced here:
  - Absolute paths -> used as-is.
  - Relative paths -> resolved as `loop_root / value`. Always. No heuristic.
  - Missing required fields without default -> raise DailyLoopConfigError.
  - PROGRESS.md missing -> raise with diagnostic message including all 3
    relevant locations (declared, loop_root, resolved final).
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

import pytest

from workflow_app.daily_loop import (
    DailyLoopConfigError,
    ReviewBlockedSentinel,
    assert_loop_root_relative_path,
    build_daily_loop_specs,
    build_loop_specs,
    diagnose_workspace_doubled_path,
    parse_progress_items,
    read_review_blocked_sentinel,
    resolve_effective_workspace_root,
    resolve_loop_path,
)
from workflow_app.daily_loop.loader import _rewrite_bare_relative_md_tokens

# ────────────────────────────────────────────────────────────────────────────
# Fixtures — minimal but representative loop structure on tmp_path
# ────────────────────────────────────────────────────────────────────────────


def _write_progress(loop_root: Path, *, items: list[tuple[str, str, str, str]]) -> None:
    """Write PROGRESS.md with given (id, mark, target, bucket) rows."""
    lines = [
        "# Loop Progress: test-slug",
        "",
        "## Items",
        "",
        "| ID  | Status | Target | Bucket | Updated |",
        "|-----|--------|--------|--------|---------|",
    ]
    for item_id, mark, target, bucket in items:
        lines.append(f"| {item_id} | [{mark}] | {target} | {bucket} | - |")
    (loop_root / "PROGRESS.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _base_config(loop_root: Path, *, progress_path: str | None = "PROGRESS.md") -> dict:
    cfg: dict = {
        "name": "test-slug",
        "kind": "daily-loop",
        "basic_flow": {
            "brief_root": str(loop_root),
            "docs_root": str(loop_root),
            "wbs_root": str(loop_root),
            "workspace_root": str(loop_root.parent),
        },
        "daily_loop": {
            "version": "1.1.0",
            "slug": "test-slug",
            "loop_root": str(loop_root),
            "tasks_dir": "tasks",
            "log_path": "_LOOP-LOG.md",
            "total_items": 1,
            "buckets": [
                {
                    "id": "T-sonnet-medium",
                    "model": "sonnet",
                    "effort": "medium",
                    "task_file": "tasks/T-sonnet-medium.md",
                    "items": ["001"],
                    "items_count": 1,
                }
            ],
            "do_command": "/daily-loop:do",
        },
    }
    if progress_path is not None:
        cfg["daily_loop"]["progress_path"] = progress_path
    return cfg


@pytest.fixture
def loop_root(tmp_path: Path) -> Path:
    """Create the typical layout: tmp_path/blacksmith/loop-archives/{slug}/."""
    root = tmp_path / "output" / "daily-loop" / "fullprofile-hardening-onda8"
    root.mkdir(parents=True)
    (root / "tasks").mkdir()
    return root


# ────────────────────────────────────────────────────────────────────────────
# resolve_loop_path — contract unit tests
# ────────────────────────────────────────────────────────────────────────────


class TestResolveLoopPath:
    def test_filename_only_relative_resolves_against_loop_root(self, loop_root: Path) -> None:
        result = resolve_loop_path("PROGRESS.md", loop_root, label="progress_path")
        assert result == (loop_root / "PROGRESS.md").resolve()

    def test_absolute_path_used_as_is(self, loop_root: Path, tmp_path: Path) -> None:
        target = tmp_path / "elsewhere" / "PROGRESS.md"
        result = resolve_loop_path(str(target), loop_root, label="progress_path")
        assert result == target

    def test_multi_segment_relative_resolves_against_loop_root_NOT_parent(
        self, loop_root: Path
    ) -> None:
        """Regression for Onda 8 bug — was joining to loop_root.parent and
        producing /tmp/.../blacksmith/loop-archives/blacksmith/loop-archives/{slug}/PROGRESS.md."""
        result = resolve_loop_path(
            "blacksmith/loop-archives/fullprofile-hardening-onda8/PROGRESS.md",
            loop_root,
            label="progress_path",
        )
        # Must resolve UNDER loop_root, never duplicating blacksmith/loop-archives prefix
        # (the historic loop_root.parent bug).
        assert "blacksmith/loop-archives/blacksmith/loop-archives" not in str(result)
        # New contract (CONTRACT.md 2.2): relative resolves literally as loop_root / value.
        assert result == (loop_root / "blacksmith" / "loop-archives"
                          / "fullprofile-hardening-onda8" / "PROGRESS.md").resolve()

    def test_subdir_relative_resolves_against_loop_root(self, loop_root: Path) -> None:
        result = resolve_loop_path("tasks/T-sonnet-medium.md", loop_root, label="task_file")
        assert result == (loop_root / "tasks" / "T-sonnet-medium.md").resolve()

    def test_empty_string_uses_default(self, loop_root: Path) -> None:
        result = resolve_loop_path("", loop_root, label="progress_path", default="PROGRESS.md")
        assert result == (loop_root / "PROGRESS.md").resolve()

    def test_whitespace_only_uses_default(self, loop_root: Path) -> None:
        result = resolve_loop_path("   ", loop_root, label="progress_path", default="PROGRESS.md")
        assert result == (loop_root / "PROGRESS.md").resolve()

    def test_none_uses_default(self, loop_root: Path) -> None:
        result = resolve_loop_path(None, loop_root, label="progress_path", default="PROGRESS.md")
        assert result == (loop_root / "PROGRESS.md").resolve()

    def test_none_without_default_raises(self, loop_root: Path) -> None:
        with pytest.raises(DailyLoopConfigError, match="ausente e sem default"):
            resolve_loop_path(None, loop_root, label="progress_path")

    def test_non_string_type_raises(self, loop_root: Path) -> None:
        with pytest.raises(DailyLoopConfigError, match="deve ser string"):
            resolve_loop_path(42, loop_root, label="progress_path")

    def test_list_value_raises(self, loop_root: Path) -> None:
        with pytest.raises(DailyLoopConfigError, match="deve ser string"):
            resolve_loop_path(["PROGRESS.md"], loop_root, label="progress_path")


# ────────────────────────────────────────────────────────────────────────────
# CONTRACT v1.1 secao 2.2 — Path field convention (hardening 2026-05-19)
# ────────────────────────────────────────────────────────────────────────────


class TestDiagnoseWorkspaceDoubledPath:
    """Detector for the workspace-relative-stored-in-loop-root-relative-field bug.

    Reproduces the failure mode from loop 05-19-gap-tasklist: producer stored
    `daily_loop.progress_path = "blacksmith/loop-archives/{slug}/PROGRESS.md"`
    while `loop_root` already terminated in that suffix, yielding a doubled
    final path. The detector returns the suggested loop_root-relative tail.
    """

    def test_returns_fix_when_slug_appears_in_value(self, loop_root: Path) -> None:
        slug = loop_root.name
        bad_value = f"blacksmith/loop-archives/{slug}/PROGRESS.md"
        assert diagnose_workspace_doubled_path(bad_value, loop_root) == "PROGRESS.md"

    def test_returns_fix_for_nested_path(self, loop_root: Path) -> None:
        slug = loop_root.name
        bad_value = f"blacksmith/loop-archives/{slug}/tasks/T-opus-high.md"
        assert (
            diagnose_workspace_doubled_path(bad_value, loop_root)
            == "tasks/T-opus-high.md"
        )

    def test_clean_filename_returns_none(self, loop_root: Path) -> None:
        assert diagnose_workspace_doubled_path("PROGRESS.md", loop_root) is None

    def test_clean_subdir_returns_none(self, loop_root: Path) -> None:
        assert diagnose_workspace_doubled_path("tasks/foo.md", loop_root) is None

    def test_absolute_path_returns_none(self, loop_root: Path) -> None:
        assert diagnose_workspace_doubled_path(str(loop_root / "PROGRESS.md"), loop_root) is None

    def test_empty_returns_none(self, loop_root: Path) -> None:
        assert diagnose_workspace_doubled_path("", loop_root) is None
        assert diagnose_workspace_doubled_path("   ", loop_root) is None

    def test_none_returns_none(self, loop_root: Path) -> None:
        assert diagnose_workspace_doubled_path(None, loop_root) is None

    def test_non_string_returns_none(self, loop_root: Path) -> None:
        assert diagnose_workspace_doubled_path(42, loop_root) is None
        assert diagnose_workspace_doubled_path(["a"], loop_root) is None

    def test_slug_substring_does_not_trigger(self, loop_root: Path) -> None:
        # value contains the slug as substring of a path component but NOT as a
        # whole component — must NOT trigger false positive.
        slug = loop_root.name
        bad_lookalike = f"prefix-{slug}-suffix/PROGRESS.md"
        assert diagnose_workspace_doubled_path(bad_lookalike, loop_root) is None


class TestAssertLoopRootRelativePath:
    """Strict guard for producers and review-time validators."""

    def test_clean_filename_passes(self, loop_root: Path) -> None:
        assert_loop_root_relative_path("PROGRESS.md", loop_root, label="progress_path")

    def test_clean_subdir_passes(self, loop_root: Path) -> None:
        assert_loop_root_relative_path("tasks/T-opus-high.md", loop_root, label="spec_path")

    def test_absolute_passes(self, loop_root: Path) -> None:
        assert_loop_root_relative_path(
            str(loop_root / "PROGRESS.md"), loop_root, label="progress_path"
        )

    def test_workspace_relative_raises(self, loop_root: Path) -> None:
        slug = loop_root.name
        bad = f"blacksmith/loop-archives/{slug}/PROGRESS.md"
        with pytest.raises(DailyLoopConfigError, match="CONTRACT v1.1 secao 2.2"):
            assert_loop_root_relative_path(bad, loop_root, label="progress_path")

    def test_error_message_carries_fix_suggestion(self, loop_root: Path) -> None:
        slug = loop_root.name
        bad = f"blacksmith/loop-archives/{slug}/tasks/T-opus-high.md"
        with pytest.raises(DailyLoopConfigError) as exc:
            assert_loop_root_relative_path(bad, loop_root, label="buckets[0].spec_path")
        assert "tasks/T-opus-high.md" in str(exc.value)
        assert "buckets[0].spec_path" in str(exc.value)


# ────────────────────────────────────────────────────────────────────────────
# build_daily_loop_specs — integration tests
# ────────────────────────────────────────────────────────────────────────────


class TestBuildDailyLoopSpecs:
    def test_filename_only_progress_path_loads_successfully(
        self, loop_root: Path
    ) -> None:
        cfg = _base_config(loop_root, progress_path="PROGRESS.md")
        _write_progress(loop_root, items=[("001", " ", "target/file.py", "T-sonnet-medium")])
        specs = build_daily_loop_specs(cfg, loop_root)
        # Expect (1 item, sonnet/medium bucket):
        #   0: /clear
        #   1: /model sonnet
        #   2: /effort medium
        #   3: /daily-loop:do --item 001
        #   4: /model opus
        #      (review-done effort=STANDARD == "medium" — dedup skips re-emission)
        #   5: /daily-loop:review-done --item 001
        #   6: /clear
        #   7: /effort high
        #   8: /daily-loop:review
        # = 9 specs
        assert len(specs) == 9
        assert specs[0].name == "/clear"
        assert specs[3].name == "/daily-loop:do --slug test-slug --item 001"
        assert specs[5].name == "/daily-loop:review-done --slug test-slug --item 001"
        assert specs[-1].name == "/daily-loop:review --slug test-slug"
        assert specs[-1].model.value == "Opus"

    def test_multi_segment_relative_progress_path_now_resolves_under_loop_root(
        self, loop_root: Path
    ) -> None:
        """Onda 8 bug regression — used to produce path duplication via
        loop_root.parent + multi-segment-relative. Now resolves under loop_root.

        We stage PROGRESS.md INSIDE loop_root/blacksmith/loop-archives/.../ to match
        the new (deterministic) resolution rule (loop_root / declared progress_path).
        """
        nested = loop_root / "blacksmith" / "loop-archives" / "fullprofile-hardening-onda8"
        nested.mkdir(parents=True)
        _write_progress(nested, items=[("001", " ", "tgt", "T-sonnet-medium")])
        cfg = _base_config(
            loop_root,
            progress_path="blacksmith/loop-archives/fullprofile-hardening-onda8/PROGRESS.md",
        )
        specs = build_daily_loop_specs(cfg, loop_root)
        # 1 clear + 5 body (model sonnet/effort medium/:do/model opus/:review-done — review-done effort dedup)
        # + 3 review-final = 9 specs
        assert len(specs) == 9

    def test_missing_progress_md_error_includes_diagnostics(self, loop_root: Path) -> None:
        cfg = _base_config(loop_root, progress_path="PROGRESS.md")
        # Do NOT write PROGRESS.md
        with pytest.raises(DailyLoopConfigError) as exc:
            build_daily_loop_specs(cfg, loop_root)
        msg = str(exc.value)
        assert "PROGRESS.md nao encontrado" in msg
        assert "progress_path = 'PROGRESS.md'" in msg
        assert str(loop_root) in msg
        assert "/daily-loop:enumerate" in msg

    def test_absolute_progress_path_used_as_is(
        self, loop_root: Path, tmp_path: Path
    ) -> None:
        elsewhere = tmp_path / "alt"
        elsewhere.mkdir()
        _write_progress(elsewhere, items=[("001", " ", "x", "T-sonnet-medium")])
        cfg = _base_config(loop_root, progress_path=str(elsewhere / "PROGRESS.md"))
        specs = build_daily_loop_specs(cfg, loop_root)
        # 1 clear + 5 body (model sonnet/effort medium/:do/model opus/:review-done — review-done effort dedup)
        # + 3 review-final = 9 specs
        assert len(specs) == 9

    def test_kind_validation_via_daily_loop_block_required(self, loop_root: Path) -> None:
        cfg = _base_config(loop_root)
        del cfg["daily_loop"]
        with pytest.raises(DailyLoopConfigError, match="sem bloco 'daily_loop'"):
            build_daily_loop_specs(cfg, loop_root)

    def test_slug_required(self, loop_root: Path) -> None:
        cfg = _base_config(loop_root)
        cfg["daily_loop"]["slug"] = ""
        with pytest.raises(DailyLoopConfigError, match="slug ausente"):
            build_daily_loop_specs(cfg, loop_root)


    def test_pending_only_emitted_done_and_failed_skipped(self, loop_root: Path) -> None:
        cfg = _base_config(loop_root)
        cfg["daily_loop"]["total_items"] = 3
        cfg["daily_loop"]["buckets"][0]["items"] = ["001", "002", "003"]
        cfg["daily_loop"]["buckets"][0]["items_count"] = 3
        _write_progress(
            loop_root,
            items=[
                ("001", " ", "a", "T-sonnet-medium"),  # pending
                ("002", "x", "b", "T-sonnet-medium"),  # done
                ("003", "!", "c", "T-sonnet-medium"),  # failed
            ],
        )
        specs = build_daily_loop_specs(cfg, loop_root)
        do_specs = [s for s in specs if s.name.startswith("/daily-loop:do")]
        assert len(do_specs) == 1  # only item 001
        assert "001" in do_specs[0].name

    def test_no_pending_returns_empty(self, loop_root: Path) -> None:
        cfg = _base_config(loop_root)
        _write_progress(loop_root, items=[("001", "x", "a", "T-sonnet-medium")])
        specs = build_daily_loop_specs(cfg, loop_root)
        assert specs == []

    def test_unknown_bucket_raises(self, loop_root: Path) -> None:
        cfg = _base_config(loop_root)
        _write_progress(loop_root, items=[("001", " ", "a", "T-bogus-bucket")])
        with pytest.raises(DailyLoopConfigError, match="bucket inexistente"):
            build_daily_loop_specs(cfg, loop_root)

    def test_invalid_model_raises(self, loop_root: Path) -> None:
        cfg = _base_config(loop_root)
        cfg["daily_loop"]["buckets"][0]["model"] = "gpt-5"
        _write_progress(loop_root, items=[("001", " ", "a", "T-sonnet-medium")])
        with pytest.raises(DailyLoopConfigError, match="model invalido"):
            build_daily_loop_specs(cfg, loop_root)

    def test_invalid_effort_raises(self, loop_root: Path) -> None:
        cfg = _base_config(loop_root)
        cfg["daily_loop"]["buckets"][0]["effort"] = "ultra"
        _write_progress(loop_root, items=[("001", " ", "a", "T-sonnet-medium")])
        with pytest.raises(DailyLoopConfigError, match="effort invalido"):
            build_daily_loop_specs(cfg, loop_root)

    def test_consecutive_same_bucket_dedupes_headers(self, loop_root: Path) -> None:
        cfg = _base_config(loop_root)
        cfg["daily_loop"]["total_items"] = 3
        cfg["daily_loop"]["buckets"][0]["items"] = ["001", "002", "003"]
        cfg["daily_loop"]["buckets"][0]["items_count"] = 3
        _write_progress(
            loop_root,
            items=[
                ("001", " ", "a", "T-sonnet-medium"),
                ("002", " ", "b", "T-sonnet-medium"),
                ("003", " ", "c", "T-sonnet-medium"),
            ],
        )
        specs = build_daily_loop_specs(cfg, loop_root)
        # Per item: /model sonnet + /effort medium (only first time) + :do +
        # /model opus + :review-done (review-done effort STANDARD == "medium" — dedup).
        # Item 001: 5 specs (sonnet, medium, do, opus, review-done)
        # Item 002: 4 specs (sonnet, do, opus, review-done) — effort already STANDARD
        # Item 003: 4 specs (sonnet, do, opus, review-done) — effort already STANDARD
        # + 1 /clear inicial + 3 review-final block (clear, effort high, :review) = 17.
        assert len(specs) == 17
        # Model toggles sonnet↔opus once per item (3 items × 2) = 6 model headers.
        # Final block: model opus already current -> 0 model headers.
        model_headers = [s for s in specs if s.name.startswith("/model")]
        effort_headers = [s for s in specs if s.name.startswith("/effort")]
        assert len(model_headers) == 6
        # Effort headers: /effort medium (item 001) + /effort high (final) = 2.
        # Items 002/003 keep effort STANDARD, review-done is also STANDARD → no flips.
        assert len(effort_headers) == 2
        # Confirm each :do is followed by a :review-done with matching item id.
        for item_id in ["001", "002", "003"]:
            do_idx = next(
                idx for idx, s in enumerate(specs)
                if s.name == f"/daily-loop:do --slug test-slug --item {item_id}"
            )
            # review-done is exactly 2 specs after :do (model opus + review-done — effort dedup'd)
            assert specs[do_idx + 2].name == (
                f"/daily-loop:review-done --slug test-slug --item {item_id}"
            )

    def test_sonnet_low_bucket_is_coerced_to_sonnet_medium_floor(
        self, loop_root: Path
    ) -> None:
        """Floor enforcement: /daily-loop:do must NEVER run on sonnet/low.

        The loader silently coerces sonnet → sonnet and low → medium when the
        config carries forbidden values (legacy configs or buggy plan output).
        Coercion is logged to stderr but does not raise.
        """
        cfg = _base_config(loop_root)
        # Force the bucket to forbidden values:
        cfg["daily_loop"]["buckets"][0]["model"] = "sonnet"
        cfg["daily_loop"]["buckets"][0]["effort"] = "low"
        _write_progress(loop_root, items=[("001", " ", "x", "T-sonnet-medium")])
        specs = build_daily_loop_specs(cfg, loop_root)
        # /clear + /model sonnet + /effort medium + :do + /model opus
        # + :review-done (effort STANDARD == "medium" — dedup skips)
        # + /clear + /effort high + :review = 9 specs.
        # NOT /model sonnet + /effort low.
        assert len(specs) == 9
        assert specs[1].name == "/model sonnet", (
            f"sonnet bucket should coerce to sonnet, got {specs[1].name}"
        )
        assert specs[2].name == "/effort medium", (
            f"low bucket should coerce to medium, got {specs[2].name}"
        )
        do_spec = specs[3]
        assert do_spec.name.startswith("/daily-loop:do")
        assert do_spec.model.value == "Sonnet"

    def test_bucket_change_emits_new_headers(self, loop_root: Path) -> None:
        cfg = _base_config(loop_root)
        cfg["daily_loop"]["total_items"] = 2
        cfg["daily_loop"]["buckets"] = [
            {
                "id": "T-sonnet-medium",
                "model": "sonnet",
                "effort": "medium",
                "task_file": "tasks/T-sonnet-medium.md",
                "items": ["001"],
                "items_count": 1,
            },
            {
                "id": "T-opus-high",
                "model": "opus",
                "effort": "high",
                "task_file": "tasks/T-opus-high.md",
                "items": ["002"],
                "items_count": 1,
            },
        ]
        _write_progress(
            loop_root,
            items=[
                ("001", " ", "a", "T-sonnet-medium"),
                ("002", " ", "b", "T-opus-high"),
            ],
        )
        specs = build_daily_loop_specs(cfg, loop_root)
        # Trace (item 001 sonnet/medium then item 002 opus/high). Note:
        # EffortLevel.STANDARD.value == "medium" — review-done effort is the
        # same canonical value as bucket "medium", so dedup skips re-emit.
        #   /clear                                                          (1)
        #   item 001: /model sonnet, /effort medium, :do, /model opus,
        #             :review-done (effort STANDARD dedup)                  (5)
        #   item 002: /effort high, :do, /effort medium (review-done flip
        #             back to STANDARD), :review-done (model opus dedup)    (4)
        #   final:    /clear, /effort high, :review (model opus dedup)      (3)
        # Total 13 specs. model headers: sonnet, opus from item 001 (= 2).
        # effort headers: medium (001), high (002), medium (002 review-done), high (final) (= 4).
        assert len(specs) == 13
        model_headers = [s for s in specs if s.name.startswith("/model")]
        effort_headers = [s for s in specs if s.name.startswith("/effort")]
        assert len(model_headers) == 2
        assert len(effort_headers) == 4


class TestV3DictLifecycleItems:
    """Shape V3 deve preservar lifecycle e commands materializados por item."""

    def test_preparo_iteration_finalizacao_keep_kind_and_order(
        self, loop_root: Path
    ) -> None:
        cfg = _base_config(loop_root)
        cfg["kind"] = "loop"
        items = [
            {
                "id": "001",
                "kind": "preparo",
                "task_path": "tasks/items/task-001-preparo.md",
                "commands": ["/test:preparo"],
            },
            {
                "id": "002",
                "kind": "iteration",
                "delegate_kind": "implementation",
                "task_path": "tasks/items/task-002-iteration.md",
                "commands": ["/test:iteration"],
            },
            {
                "id": "003",
                "kind": "finalizacao",
                "task_path": "tasks/items/task-003-finalizacao.md",
                "commands": ["/test:finalizacao"],
            },
        ]
        cfg["daily_loop"]["total_items"] = len(items)
        cfg["daily_loop"]["buckets"][0]["items"] = items
        cfg["daily_loop"]["buckets"][0]["items_count"] = len(items)
        cfg["daily_loop"]["items_index"] = {
            item["id"]: {
                "id": item["id"],
                "kind": item["kind"],
                "task_path": item["task_path"],
                "commands": list(item["commands"]),
                "model": "sonnet",
                "effort": "medium",
            }
            for item in items
        }
        _write_progress(
            loop_root,
            items=[
                (item["id"], " ", item["task_path"], "T-sonnet-medium")
                for item in items
            ],
        )
        before = copy.deepcopy(cfg)

        names = [spec.name for spec in build_loop_specs(cfg, loop_root)]

        real_positions = [
            names.index("/test:preparo"),
            names.index("/test:iteration"),
            names.index("/test:finalizacao"),
        ]
        assert real_positions == sorted(real_positions)
        assert not any(name.startswith("/daily-loop:do") for name in names)
        assert cfg == before
        assert [
            item["kind"] for item in cfg["daily_loop"]["buckets"][0]["items"]
        ] == ["preparo", "iteration", "finalizacao"]
        assert cfg["daily_loop"]["items_index"]["002"]["kind"] == "iteration"
        assert (
            cfg["daily_loop"]["buckets"][0]["items"][1]["delegate_kind"]
            == "implementation"
        )

    def test_task_path_contract_accepts_relative_and_rejects_embedded_loop_root(
        self, loop_root: Path
    ) -> None:
        clean = "tasks/items/task-001-preparo.md"
        assert_loop_root_relative_path(clean, loop_root, label="items[001].task_path")

        duplicated = f"blacksmith/loop-archives/{loop_root.name}/{clean}"
        with pytest.raises(DailyLoopConfigError, match="workspace-relative detectado"):
            assert_loop_root_relative_path(
                duplicated,
                loop_root,
                label="items[001].task_path",
            )


# ────────────────────────────────────────────────────────────────────────────
# /daily-loop:review-done — per-item adversarial audit injection
# ────────────────────────────────────────────────────────────────────────────


class TestReviewDoneInjection:
    """Verifies that /daily-loop:review-done is interleaved after EVERY :do
    in the queue and runs in opus/standard, mirroring the relationship between
    /execute-task and /review-executed-task."""

    def test_review_done_emitted_after_every_do(self, loop_root: Path) -> None:
        cfg = _base_config(loop_root)
        cfg["daily_loop"]["total_items"] = 2
        cfg["daily_loop"]["buckets"][0]["items"] = ["001", "002"]
        cfg["daily_loop"]["buckets"][0]["items_count"] = 2
        _write_progress(
            loop_root,
            items=[
                ("001", " ", "a", "T-sonnet-medium"),
                ("002", " ", "b", "T-sonnet-medium"),
            ],
        )
        specs = build_daily_loop_specs(cfg, loop_root)

        do_specs = [s for s in specs if s.name.startswith("/daily-loop:do ")]
        review_done_specs = [
            s for s in specs if s.name.startswith("/daily-loop:review-done ")
        ]
        # 1 :review-done per :do.
        assert len(do_specs) == len(review_done_specs) == 2

        # Each :review-done references the same --item id as the preceding :do.
        for do_spec, rd_spec in zip(do_specs, review_done_specs, strict=True):
            do_item = do_spec.name.rsplit("--item ", 1)[1]
            rd_item = rd_spec.name.rsplit("--item ", 1)[1]
            assert do_item == rd_item, (
                f":review-done item ({rd_item}) must match preceding :do ({do_item})"
            )
            # And review-done is opus/STANDARD (which serializes as "medium")
            # regardless of bucket model.
            assert rd_spec.model.value == "Opus"
            assert rd_spec.effort.value == "medium"  # EffortLevel.STANDARD.value

    def test_review_done_uses_slug_from_config(self, loop_root: Path) -> None:
        cfg = _base_config(loop_root)
        cfg["daily_loop"]["slug"] = "custom-loop-slug"
        _write_progress(loop_root, items=[("001", " ", "x", "T-sonnet-medium")])
        specs = build_daily_loop_specs(cfg, loop_root)
        rd = next(s for s in specs if s.name.startswith("/daily-loop:review-done "))
        assert "--slug custom-loop-slug" in rd.name

    def test_review_done_command_override_via_config(self, loop_root: Path) -> None:
        cfg = _base_config(loop_root)
        cfg["daily_loop"]["review_done_command"] = "/custom:review-each"
        _write_progress(loop_root, items=[("001", " ", "x", "T-sonnet-medium")])
        specs = build_daily_loop_specs(cfg, loop_root)
        # Original /daily-loop:review-done replaced by override.
        assert any(s.name.startswith("/custom:review-each ") for s in specs)
        assert not any(s.name.startswith("/daily-loop:review-done ") for s in specs)

    def test_model_returns_to_bucket_on_next_item(self, loop_root: Path) -> None:
        """After review-done flips current to opus/standard, the next :do
        must re-emit /model X /effort Y from its bucket — never inherit
        opus/standard from the prior review-done."""
        cfg = _base_config(loop_root)
        cfg["daily_loop"]["total_items"] = 2
        cfg["daily_loop"]["buckets"][0]["items"] = ["001", "002"]
        cfg["daily_loop"]["buckets"][0]["items_count"] = 2
        _write_progress(
            loop_root,
            items=[
                ("001", " ", "a", "T-sonnet-medium"),
                ("002", " ", "b", "T-sonnet-medium"),
            ],
        )
        specs = build_daily_loop_specs(cfg, loop_root)
        # Find :do for item 002 — must be preceded by /model sonnet (re-emitted
        # because the previous review-done left current_model = opus).
        idx_002 = next(
            i for i, s in enumerate(specs)
            if s.name == "/daily-loop:do --slug test-slug --item 002"
        )
        # Walk backwards: should encounter /effort medium then /model sonnet
        # before any earlier slash-command (no other :do/:review-done between).
        preceding = [s.name for s in specs[:idx_002]]
        last_model = next(
            n for n in reversed(preceding) if n.startswith("/model ")
        )
        last_effort = next(
            n for n in reversed(preceding) if n.startswith("/effort ")
        )
        assert last_model == "/model sonnet"
        assert last_effort == "/effort medium"
        # Ensure the re-emission happened AFTER the previous review-done — i.e.
        # the model header for sonnet is positioned between item 001 review-done
        # and item 002 :do (not stale from the very first emission).
        idx_001_rd = next(
            i for i, s in enumerate(specs)
            if s.name == "/daily-loop:review-done --slug test-slug --item 001"
        )
        idx_sonnet_for_002 = max(
            i for i, s in enumerate(specs[:idx_002]) if s.name == "/model sonnet"
        )
        assert idx_sonnet_for_002 > idx_001_rd


# ────────────────────────────────────────────────────────────────────────────
# clear_between_items opt-in flag
# ────────────────────────────────────────────────────────────────────────────


class TestClearBetweenItems:
    """Verifies the optional `daily_loop.clear_between_items` flag.

    When true, a /clear is inserted after each :review-done and before the
    next item's :do (NEVER between :do and its :review-done — the audit
    depends on the :do context being fresh in conversation memory). The
    initial /clear at position 0 and the final /clear before :review remain
    unchanged. /clear resets only conversation context, never /model nor
    /effort in the CLI (workflow-app-command-lists.md section 1), so the
    injected /clear must NOT force re-emission of identical /model and /effort
    headers — that would violate the anti-redundancy policy (section 3.1).
    """

    def test_default_false_preserves_legacy_no_inter_item_clear(
        self, loop_root: Path
    ) -> None:
        """Without the flag, only 2 /clear markers exist (position 0 + before
        :review final). Two items in the same bucket -> exactly 2 /clear."""
        cfg = _base_config(loop_root)
        cfg["daily_loop"]["total_items"] = 2
        cfg["daily_loop"]["buckets"][0]["items"] = ["001", "002"]
        cfg["daily_loop"]["buckets"][0]["items_count"] = 2
        _write_progress(
            loop_root,
            items=[
                ("001", " ", "a", "T-sonnet-medium"),
                ("002", " ", "b", "T-sonnet-medium"),
            ],
        )
        specs = build_daily_loop_specs(cfg, loop_root)
        clear_specs = [s for s in specs if s.name == "/clear"]
        assert len(clear_specs) == 2

    def test_flag_true_injects_clear_between_items(self, loop_root: Path) -> None:
        """With clear_between_items=true, an extra /clear appears between
        every consecutive pair of items. 2 items -> 3 /clear markers."""
        cfg = _base_config(loop_root)
        cfg["daily_loop"]["clear_between_items"] = True
        cfg["daily_loop"]["total_items"] = 2
        cfg["daily_loop"]["buckets"][0]["items"] = ["001", "002"]
        cfg["daily_loop"]["buckets"][0]["items_count"] = 2
        _write_progress(
            loop_root,
            items=[
                ("001", " ", "a", "T-sonnet-medium"),
                ("002", " ", "b", "T-sonnet-medium"),
            ],
        )
        specs = build_daily_loop_specs(cfg, loop_root)
        clear_specs = [s for s in specs if s.name == "/clear"]
        # position 0 + between (001, 002) + before final :review = 3.
        assert len(clear_specs) == 3

    def test_flag_true_clear_lands_after_review_done_not_between_do_and_rd(
        self, loop_root: Path
    ) -> None:
        """Critical placement contract: the injected /clear must come AFTER
        the prior :review-done and BEFORE the next :do — never between :do
        and its own :review-done (the audit needs the :do context warm)."""
        cfg = _base_config(loop_root)
        cfg["daily_loop"]["clear_between_items"] = True
        cfg["daily_loop"]["total_items"] = 2
        cfg["daily_loop"]["buckets"][0]["items"] = ["001", "002"]
        cfg["daily_loop"]["buckets"][0]["items_count"] = 2
        _write_progress(
            loop_root,
            items=[
                ("001", " ", "a", "T-sonnet-medium"),
                ("002", " ", "b", "T-sonnet-medium"),
            ],
        )
        specs = build_daily_loop_specs(cfg, loop_root)

        idx_rd_001 = next(
            i for i, s in enumerate(specs)
            if s.name == "/daily-loop:review-done --slug test-slug --item 001"
        )
        idx_do_002 = next(
            i for i, s in enumerate(specs)
            if s.name == "/daily-loop:do --slug test-slug --item 002"
        )
        # The injected /clear is the only /clear strictly between rd_001 and
        # do_002 — assert it exists in that window.
        between = specs[idx_rd_001 + 1: idx_do_002]
        assert any(s.name == "/clear" for s in between), (
            "expected /clear between :review-done 001 and :do 002"
        )
        # And no /clear sits between :do 001 and :review-done 001.
        idx_do_001 = next(
            i for i, s in enumerate(specs)
            if s.name == "/daily-loop:do --slug test-slug --item 001"
        )
        between_pair = specs[idx_do_001 + 1: idx_rd_001]
        assert not any(s.name == "/clear" for s in between_pair), (
            "/clear must NOT split the :do / :review-done pair"
        )

    def test_flag_true_suppresses_unchanged_directives_after_clear(
        self, loop_root: Path
    ) -> None:
        """After an injected /clear, the next item must NOT re-emit a directive
        whose value is unchanged — /clear does not reset /model or /effort in
        the CLI (workflow-app-command-lists.md section 1), so re-emitting an
        identical directive violates anti-redundancy (3.1).

        In daily-loop each item's :review-done runs in opus/STANDARD, so the
        model legitimately flips opus->sonnet at the next item (must re-emit
        /model sonnet) while the effort stays STANDARD/medium (must suppress
        /effort medium)."""
        cfg = _base_config(loop_root)
        cfg["daily_loop"]["clear_between_items"] = True
        cfg["daily_loop"]["total_items"] = 2
        cfg["daily_loop"]["buckets"][0]["items"] = ["001", "002"]
        cfg["daily_loop"]["buckets"][0]["items_count"] = 2
        _write_progress(
            loop_root,
            items=[
                ("001", " ", "a", "T-sonnet-medium"),
                ("002", " ", "b", "T-sonnet-medium"),
            ],
        )
        specs = build_daily_loop_specs(cfg, loop_root)

        idx_do_002 = next(
            i for i, s in enumerate(specs)
            if s.name == "/daily-loop:do --slug test-slug --item 002"
        )
        idx_clear_before_002 = max(
            i for i, s in enumerate(specs[:idx_do_002]) if s.name == "/clear"
        )
        window = specs[idx_clear_before_002 + 1: idx_do_002]
        names = [s.name for s in window]
        # Model genuinely changed (opus review-done -> sonnet) -> must re-emit.
        assert "/model sonnet" in names, (
            f"/model sonnet must re-emit after opus review-done; window={names}"
        )
        # Effort unchanged (STANDARD/medium throughout) -> must NOT re-emit.
        assert "/effort medium" not in names, (
            f"/effort medium must NOT re-emit after /clear (unchanged); window={names}"
        )


# ────────────────────────────────────────────────────────────────────────────
# /daily-loop:review-created — .review-blocked sentinel detection
# ────────────────────────────────────────────────────────────────────────────


class TestReviewBlockedSentinel:
    """Pure-helper tests for read_review_blocked_sentinel.

    The sentinel is a marker file dropped by /daily-loop:review-created
    (FASE 6) when the audit's 3-round self-healing exhausts with blockers
    remaining. The workflow-app reads it to gate `queue-btn-daily-loop`
    behind a confirmation modal.
    """

    def test_absent_returns_none(self, loop_root: Path) -> None:
        # Common hot path — no sentinel, no overhead.
        assert read_review_blocked_sentinel(loop_root) is None

    def test_present_returns_sentinel_with_blocker_count(
        self, loop_root: Path
    ) -> None:
        body = (
            "# Daily Loop — Review BLOQUEADO\n"
            "Slug: test-slug\n"
            "Data: 2026-05-06T00:00:00Z\n"
            "Rodadas exauridas: 3/3\n"
            "Blockers remanescentes: 4\n"
            "\n"
            "Resumo dos blockers:\n"
            "- A: 2 items missing in PROGRESS.md\n"
            "- C: iteration_template ambiguo no passo 3\n"
        )
        (loop_root / ".review-blocked").write_text(body, encoding="utf-8")
        result = read_review_blocked_sentinel(loop_root)
        assert isinstance(result, ReviewBlockedSentinel)
        assert result.blocker_count == 4
        assert "Slug: test-slug" in result.summary
        assert result.path == loop_root / ".review-blocked"
        assert result.raw == body

    def test_malformed_blocker_count_defaults_to_zero(
        self, loop_root: Path
    ) -> None:
        # Sentinel still shown to user (presence is the load-bearing signal).
        body = (
            "# Daily Loop — Review BLOQUEADO\n"
            "Slug: test-slug\n"
            "Blockers remanescentes: many\n"
        )
        (loop_root / ".review-blocked").write_text(body, encoding="utf-8")
        result = read_review_blocked_sentinel(loop_root)
        assert result is not None
        assert result.blocker_count == 0
        assert "Slug: test-slug" in result.summary

    def test_minimal_sentinel_still_recognised(self, loop_root: Path) -> None:
        # An empty file is enough to block — UX must surface that the audit
        # was reproved even if details are missing.
        (loop_root / ".review-blocked").write_text("", encoding="utf-8")
        result = read_review_blocked_sentinel(loop_root)
        assert result is not None
        assert result.blocker_count == 0
        assert result.summary == ""

    def test_directory_named_review_blocked_does_not_match(
        self, loop_root: Path
    ) -> None:
        # `.is_file()` rules out a directory accidentally created with the same
        # name. The check must be strict — we don't want to read directory bytes.
        (loop_root / ".review-blocked").mkdir()
        assert read_review_blocked_sentinel(loop_root) is None

    def test_str_loop_root_accepted(self, loop_root: Path) -> None:
        # Helper accepts both Path and str (workflow-app passes Path; CLI
        # tooling may pass str).
        (loop_root / ".review-blocked").write_text("Slug: x\n", encoding="utf-8")
        result = read_review_blocked_sentinel(str(loop_root))
        assert result is not None


# ────────────────────────────────────────────────────────────────────────────
# parse_progress_items — table parser tests
# ────────────────────────────────────────────────────────────────────────────


class TestParseProgressItems:
    def test_pending_done_failed_marks(self) -> None:
        text = (
            "| 001 | [ ] | a | T-x | - |\n"
            "| 002 | [x] | b | T-x | - |\n"
            "| 003 | [!] | c | T-x | - |\n"
        )
        items = parse_progress_items(text)
        assert [i.status for i in items] == ["pending", "done", "failed"]

    def test_skips_header_and_separator_rows(self) -> None:
        text = (
            "| ID | Status | Target | Bucket | Updated |\n"
            "|----|--------|--------|--------|---------|\n"
            "| 001 | [ ] | a | T-x | - |\n"
        )
        items = parse_progress_items(text)
        assert len(items) == 1
        assert items[0].item_id == "001"

    def test_extra_columns_tolerated(self) -> None:
        text = "| 001 | [ ] | a | T-x | extra1 | extra2 |\n"
        items = parse_progress_items(text)
        assert len(items) == 1

    def test_target_with_spaces_preserved(self) -> None:
        text = "| 001 | [ ] | path/with spaces/file.py — note | T-x | - |\n"
        items = parse_progress_items(text)
        assert items[0].target == "path/with spaces/file.py — note"


# ────────────────────────────────────────────────────────────────────────────
# Baseline do corpus real de `blacksmith/loop-archives/` (passo 1 de
# blacksmith/brainstorm-mcp/07-27-md-token-resolution-repo-root.md).
#
# O oraculo abaixo e INDEPENDENTE do loader de proposito: ele materializa a
# regra de contagem declarada no criterio 4 da nota, para que uma mudanca de
# precedencia no loader nao possa ser confundida com regressao. Nao importar o
# resolver aqui — este bloco e a rede, nao o objeto medido.
# ────────────────────────────────────────────────────────────────────────────

_REPO_ROOT = Path(__file__).resolve().parents[4]
_LOOP_ARCHIVES = _REPO_ROOT / "blacksmith" / "loop-archives"

_requires_corpus = pytest.mark.skipif(
    not _LOOP_ARCHIVES.is_dir(),
    reason="blacksmith/loop-archives/ ausente neste checkout",
)


def _corpus_repo_root(loop_root: Path) -> Path | None:
    """Primeiro ancestral com `.claude/` (mesma regra de `_repo_root_anchor`)."""
    for parent in (loop_root, *loop_root.parents):
        if (parent / ".claude").is_dir():
            return parent
    return None


def _corpus_workspace_root(raw: dict, repo_root: Path) -> Path:
    basic_flow = raw.get("basic_flow")
    declared = ""
    if isinstance(basic_flow, dict):
        declared = str(basic_flow.get("workspace_root") or "").strip()
    if not declared:
        return repo_root
    path = Path(declared).expanduser()
    if not path.is_absolute():
        path = repo_root / path
    return Path(os.path.normpath(str(path)))


def _corpus_md_tokens(daily_loop: object) -> list[tuple[str, str]]:
    """Todo token `.md` de `buckets[*].items[*].commands` e `items_index[*].commands`.

    Conta OCORRENCIAS, nao pares distintos: as duas fontes espelham uma a outra
    por forca da validacao W9, entao 40 dos 53 loops contam cada token duas
    vezes. Guarda de tipo em `buckets[*].items[*]` (ha 10 entradas string no
    corpus); `items_index` nao tem valor nao-dict e por isso nao ganha guarda
    equivalente.
    """
    if not isinstance(daily_loop, dict):
        return []
    out: list[tuple[str, str]] = []

    def _collect(item_id: str, commands: object) -> None:
        if not isinstance(commands, list):
            return
        for cmd in commands:
            if not isinstance(cmd, str):
                continue
            out.extend((item_id, tok) for tok in cmd.split() if tok.endswith(".md"))

    buckets = daily_loop.get("buckets")
    if isinstance(buckets, list):
        for bucket in buckets:
            if not isinstance(bucket, dict):
                continue
            for item in bucket.get("items") or []:
                if not isinstance(item, dict):
                    continue
                _collect(str(item.get("id", "?")), item.get("commands"))

    items_index = daily_loop.get("items_index")
    if isinstance(items_index, dict):
        for item_id, entry in items_index.items():
            if isinstance(entry, dict):
                _collect(str(item_id), entry.get("commands"))
    return out


def _classify_corpus_token(
    token: str, *, loop_root: Path, workspace_root: Path, repo_root: Path
) -> str:
    """Veredito do oraculo: precedencia raiz do repo, `workspace_root`, `loop_root`."""
    if token.startswith("/"):
        return "absolute"
    hits: list[tuple[str, str]] = []
    for name, base in (
        ("repo_root", repo_root),
        ("workspace_root", workspace_root),
        ("loop_root", loop_root),
    ):
        candidate = base / token
        if candidate.exists():
            hits.append((name, os.path.realpath(str(candidate))))
    if not hits:
        return "not_found"
    # Ambiguidade e por `realpath` divergente, nunca por pertencer a mais de
    # uma base: sem essa distincao o veredito dispararia 3632 vezes no corpus.
    if len({real for _, real in hits}) > 1:
        return "ambiguous"
    first = hits[0][0]
    return "rewrite" if first == "loop_root" else f"ok:{first}"


class TestWorkspaceDriftPolicy:
    def test_loop_without_project_uses_loop_workspace(self, loop_root: Path) -> None:
        loop_workspace = loop_root.parent / "loop-workspace"
        cfg = _base_config(loop_root)
        cfg["basic_flow"]["workspace_root"] = str(loop_workspace)

        assert resolve_effective_workspace_root(cfg, loop_root) == loop_workspace.resolve()

    def test_equal_project_workspace_is_accepted_without_noise(self, loop_root: Path) -> None:
        workspace = loop_root.parent / "shared-workspace"
        cfg = _base_config(loop_root)
        cfg["basic_flow"]["workspace_root"] = str(workspace)

        assert (
            resolve_effective_workspace_root(
                cfg,
                loop_root,
                project_workspace_root=workspace,
            )
            == workspace.resolve()
        )

    def test_divergent_project_workspace_does_not_block_the_loop(
        self, loop_root: Path, tmp_path: Path
    ) -> None:
        """Regressao 2026-07-27: com project.json anexado (attachments-project-
        row) e workspace divergente, o default `block` levantava
        DailyLoopConfigError e o botao Loop virava toast de erro com a
        queue-command-list vazia. O anexo loop e a autoridade: o project nunca
        bloqueia, so perde a disputa."""
        loop_workspace = tmp_path / "loop-workspace"
        cfg = _base_config(loop_root)
        cfg["basic_flow"]["workspace_root"] = str(loop_workspace)
        _write_progress(loop_root, items=[("001", " ", "target/file.py", "T-sonnet-medium")])

        assert (
            resolve_effective_workspace_root(
                cfg,
                loop_root,
                project_workspace_root=tmp_path / "project-workspace",
            )
            == loop_workspace.resolve()
        )

        specs = build_daily_loop_specs(
            cfg,
            loop_root,
            project_workspace_root=tmp_path / "project-workspace",
        )
        assert specs, "fila deve expandir mesmo com project workspace divergente"

    def test_divergent_project_workspace_warns_on_stderr(
        self, loop_root: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cfg = _base_config(loop_root)
        cfg["basic_flow"]["workspace_root"] = str(tmp_path / "loop-workspace")

        resolve_effective_workspace_root(
            cfg,
            loop_root,
            project_workspace_root=tmp_path / "project-workspace",
        )

        assert "workspace_root divergente" in capsys.readouterr().err

    def test_explicit_block_policy_still_fails_closed(
        self, loop_root: Path, tmp_path: Path
    ) -> None:
        """`block` continua disponivel, agora como opt-in explicito."""
        cfg = _base_config(loop_root)
        cfg["basic_flow"]["workspace_root"] = str(tmp_path / "loop-workspace")
        cfg["workspace_drift_policy"] = "block"
        _write_progress(loop_root, items=[("001", " ", "target/file.py", "T-sonnet-medium")])

        with pytest.raises(DailyLoopConfigError, match="workspace_root divergente"):
            build_daily_loop_specs(
                cfg,
                loop_root,
                project_workspace_root=tmp_path / "project-workspace",
            )

    def test_relative_loop_workspace_anchors_on_repo_root_not_cwd(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`basic_flow.workspace_root` relativo ancora na raiz do repo dona do
        loop (1o ancestral com `.claude/`), nunca no cwd do processo — o
        workflow-app roda com cwd = ai-forge/workflow-app."""
        repo = tmp_path / "repo"
        (repo / ".claude").mkdir(parents=True)
        loop_root = repo / "blacksmith" / "loop-archives" / "07-24-slug"
        loop_root.mkdir(parents=True)
        elsewhere = tmp_path / "cwd-decoy"
        elsewhere.mkdir()
        monkeypatch.chdir(elsewhere)

        cfg = _base_config(loop_root)
        cfg["basic_flow"]["workspace_root"] = "output/workspace/app"

        assert (
            resolve_effective_workspace_root(cfg, loop_root)
            == repo / "output" / "workspace" / "app"
        )

    def test_same_relative_declaration_on_both_sides_is_not_drift(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Falso-positivo real: loop e project declaravam o MESMO
        `output/workspace/tecum-app`, mas o loop resolvia contra o cwd e o
        project contra a raiz do repo, e a comparacao acusava divergencia."""
        repo = tmp_path / "repo"
        (repo / ".claude").mkdir(parents=True)
        loop_root = repo / "blacksmith" / "loop-archives" / "07-23-slug"
        loop_root.mkdir(parents=True)
        monkeypatch.chdir(tmp_path)

        cfg = _base_config(loop_root)
        cfg["basic_flow"]["workspace_root"] = "output/workspace/tecum-app"

        assert (
            resolve_effective_workspace_root(
                cfg,
                loop_root,
                project_workspace_root=repo / "output" / "workspace" / "tecum-app",
            )
            == repo / "output" / "workspace" / "tecum-app"
        )

    def test_explicit_project_override_uses_project_workspace_for_rewrite(
        self, loop_root: Path, tmp_path: Path
    ) -> None:
        project_workspace = tmp_path / "project-workspace"
        project_workspace.mkdir()
        cfg = _base_config(loop_root)
        cfg["basic_flow"]["workspace_root"] = str(tmp_path / "loop-workspace")
        cfg["workspace_drift_policy"] = "allow_project_override"
        cfg["daily_loop"]["buckets"][0]["items"] = [
            {"id": "001", "commands": ["/loop:test tasks/items/task-001.md"]}
        ]
        task_path = loop_root / "tasks" / "items" / "task-001.md"
        task_path.parent.mkdir(parents=True)
        task_path.write_text("# Task\n\n## Acao\n", encoding="utf-8")
        _write_progress(loop_root, items=[("001", " ", "tasks/items/task-001.md", "T-sonnet-medium")])

        specs = build_loop_specs(
            cfg,
            loop_root,
            project_workspace_root=project_workspace,
        )

        expected = f"{os.path.relpath(loop_root, project_workspace)}/tasks/items/task-001.md"
        assert any(spec.name == f"/loop:test {expected}" for spec in specs)

    # ── Baseline do corpus real (rede de regressao do resolver) ────────────

    @_requires_corpus
    def test_corpus_md_token_classification_baseline(self) -> None:
        """Fotografia do corpus de `blacksmith/loop-archives/` em 2026-07-27.

        Rede de seguranca para a centralizacao do resolver de paths: qualquer
        mudanca de precedencia entre raiz do repo, `workspace_root` e
        `loop_root` mexe nestes numeros. Divergencia aqui e SINAL, nao ruido —
        rever a mudanca antes de atualizar a constante.
        """
        tally = {
            "ok:repo_root": 0,
            "ok:workspace_root": 0,
            "rewrite": 0,
            "absolute": 0,
            "not_found": 0,
            "ambiguous": 0,
        }
        configs = sorted(_LOOP_ARCHIVES.glob("*/_LOOP-CONFIG.json"))
        for config_path in configs:
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            loop_root = config_path.parent
            repo_root = _corpus_repo_root(loop_root)
            assert repo_root is not None, f"{config_path} fora de um repo com .claude/"
            workspace_root = _corpus_workspace_root(raw, repo_root)
            for _item_id, token in _corpus_md_tokens(raw.get("daily_loop")):
                verdict = _classify_corpus_token(
                    token,
                    loop_root=loop_root,
                    workspace_root=workspace_root,
                    repo_root=repo_root,
                )
                tally[verdict] += 1

        assert len(configs) == 53
        assert tally == {
            "ok:repo_root": 5887,
            "ok:workspace_root": 419,
            "rewrite": 2,
            "absolute": 68,
            "not_found": 26,
            "ambiguous": 0,
        }
        assert sum(tally.values()) == 6402

    @_requires_corpus
    def test_corpus_loader_rewrites_only_the_known_bare_relative_item(self) -> None:
        """O loader, hoje, so reescreve o item 019 de `05-19-gap-tasklist`.

        Espelha o veredito `rewrite` do oraculo acima (2 ocorrencias, uma em
        `buckets[*]` e outra em `items_index`, por espelhamento W9). Esta e a
        rede que impede a reescrita de `_rewrite_bare_relative_md_tokens` como
        consumidor do resolver de mudar comportamento observavel.
        """
        rewritten: list[tuple[str, str, str, str]] = []
        for config_path in sorted(_LOOP_ARCHIVES.glob("*/_LOOP-CONFIG.json")):
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            daily_loop = raw.get("daily_loop")
            if not isinstance(daily_loop, dict):
                continue
            loop_root = config_path.parent
            repo_root = _corpus_repo_root(loop_root)
            assert repo_root is not None
            workspace_root = _corpus_workspace_root(raw, repo_root)

            def _check(item_id: str, commands: object, *, loop=loop_root, ws=workspace_root,
                       name=config_path.parent.name) -> None:
                if not isinstance(commands, list):
                    return
                cmds = [c for c in commands if isinstance(c, str)]
                out = _rewrite_bare_relative_md_tokens(cmds, loop, ws, item_id)
                rewritten.extend(
                    (name, item_id, before, after)
                    for before, after in zip(cmds, out)
                    if before != after
                )

            for bucket in daily_loop.get("buckets") or []:
                if isinstance(bucket, dict):
                    for item in bucket.get("items") or []:
                        if isinstance(item, dict):
                            _check(str(item.get("id", "?")), item.get("commands"))
            items_index = daily_loop.get("items_index")
            if isinstance(items_index, dict):
                for item_id, entry in items_index.items():
                    if isinstance(entry, dict):
                        _check(str(item_id), entry.get("commands"))

        assert len(rewritten) == 2
        assert {(loop, item) for loop, item, _, _ in rewritten} == {
            ("05-19-gap-tasklist", "019")
        }
        for _loop, _item, _before, after in rewritten:
            assert after.endswith(
                "blacksmith/loop-archives/05-19-gap-tasklist/tasks/items/"
                "task-019-finalizacao.md"
            )


class TestRewriteBareRelativeMdTokens:
    """Cobertura direta de `_rewrite_bare_relative_md_tokens` (§12 criterio 6).

    A funcao nao tinha nenhum teste proprio antes de virar consumidora do
    resolver: era coberta so por tabela, atraves de `build_loop_specs`.
    """

    @pytest.fixture()
    def repo(self, tmp_path: Path) -> Path:
        root = tmp_path / "repo"
        (root / ".claude").mkdir(parents=True)
        return root

    @pytest.fixture()
    def loop(self, repo: Path) -> Path:
        root = repo / "blacksmith" / "loop-archives" / "fake"
        root.mkdir(parents=True)
        return root

    def test_non_md_tokens_pass_through_untouched(self, repo: Path, loop: Path) -> None:
        cmds = ["/model sonnet", "/loop:iteraction:execute-task --task"]
        assert _rewrite_bare_relative_md_tokens(cmds, loop, repo, "001") == cmds

    def test_absolute_token_is_kept(self, repo: Path, loop: Path) -> None:
        cmds = ["/loop:test /tmp/qualquer-coisa.md"]
        assert _rewrite_bare_relative_md_tokens(cmds, loop, repo, "001") == cmds

    def test_token_resolving_from_repo_root_is_kept_silently(
        self, repo: Path, loop: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = repo / "docs" / "guide.md"
        target.parent.mkdir(parents=True)
        target.write_text("# guide\n", encoding="utf-8")
        workspace = repo / "output" / "workspace" / "app"
        workspace.mkdir(parents=True)

        cmds = ["/loop:test docs/guide.md"]
        assert _rewrite_bare_relative_md_tokens(cmds, loop, workspace, "001") == cmds
        assert capsys.readouterr().err == ""

    def test_token_missing_everywhere_is_kept(self, repo: Path, loop: Path) -> None:
        cmds = ["/loop:test tasks/items/fantasma.md"]
        assert _rewrite_bare_relative_md_tokens(cmds, loop, repo, "001") == cmds

    def test_loop_root_only_token_is_rewritten_with_warn(
        self, repo: Path, loop: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        target = loop / "tasks" / "items" / "task-001.md"
        target.parent.mkdir(parents=True)
        target.write_text("# task\n", encoding="utf-8")
        workspace = repo / "output" / "workspace" / "app"
        workspace.mkdir(parents=True)

        out = _rewrite_bare_relative_md_tokens(
            ["/loop:test tasks/items/task-001.md"], loop, workspace, "001"
        )

        rel = os.path.relpath(loop, workspace)
        assert out == [f"/loop:test {rel}/tasks/items/task-001.md"]
        assert "bare-relative path rewritten" in capsys.readouterr().err

    def test_ambiguous_token_warns_and_keeps(
        self, repo: Path, loop: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        workspace = repo / "output" / "workspace" / "app"
        (workspace / "docs").mkdir(parents=True)
        (workspace / "docs" / "guide.md").write_text("# workspace\n", encoding="utf-8")
        (repo / "docs").mkdir()
        (repo / "docs" / "guide.md").write_text("# raiz\n", encoding="utf-8")

        cmds = ["/loop:test docs/guide.md"]
        assert _rewrite_bare_relative_md_tokens(cmds, loop, workspace, "001") == cmds
        err = capsys.readouterr().err
        assert "token ambiguo" in err
        assert "repo_root" in err


# ────────────────────────────────────────────────────────────────────────────
# Real-world regression — replay the Onda 8 _LOOP-CONFIG.json layout
# ────────────────────────────────────────────────────────────────────────────


class TestOnda8RegressionReplay:
    """Reproduces the exact shape of /home/pedro/.../fullprofile-hardening-onda8/
    that triggered the path duplication bug in workflow-app."""

    def test_onda8_layout_with_filename_only_progress_path(
        self, tmp_path: Path
    ) -> None:
        """Post-fix v1.1 contract: progress_path = 'PROGRESS.md' resolves under
        loop_root. No duplication possible."""
        loop_root = tmp_path / "output" / "daily-loop" / "fullprofile-hardening-onda8"
        loop_root.mkdir(parents=True)
        (loop_root / "tasks").mkdir()
        _write_progress(loop_root, items=[("001", " ", "x", "T-sonnet-medium")])
        cfg = {
            "name": "fullprofile-hardening-onda8",
            "kind": "daily-loop",
            "basic_flow": {
                "brief_root": str(loop_root),
                "docs_root": str(loop_root),
                "wbs_root": str(loop_root),
                "workspace_root": str(tmp_path),
            },
            "daily_loop": {
                "version": "1.1.0",
                "slug": "fullprofile-hardening-onda8",
                "loop_root": str(loop_root),
                "progress_path": "PROGRESS.md",
                "tasks_dir": "tasks",
                "log_path": "_LOOP-LOG.md",
                "total_items": 1,
                "buckets": [
                    {
                        "id": "T-sonnet-medium",
                        "model": "sonnet",
                        "effort": "medium",
                        "task_file": "tasks/T-sonnet-medium.md",
                        "items": ["001"],
                        "items_count": 1,
                    }
                ],
                "do_command": "/daily-loop:do",
            },
        }
        # Should NOT raise — filename-only resolves cleanly under loop_root.
        specs = build_daily_loop_specs(cfg, loop_root)
        assert any(s.name.startswith("/daily-loop:do") for s in specs)

    def test_onda8_legacy_layout_with_old_multi_segment_path_no_longer_duplicates(
        self, tmp_path: Path
    ) -> None:
        """Legacy bug shape: progress_path was the FULL relative path. Old code
        joined to loop_root.parent producing duplication. New code joins to
        loop_root, which means the user must STAGE PROGRESS.md at the declared
        nested location — which is the intuitive behavior."""
        loop_root = tmp_path / "output" / "daily-loop" / "fullprofile-hardening-onda8"
        loop_root.mkdir(parents=True)
        (loop_root / "tasks").mkdir()
        # Legacy generator wrote progress_path with embedded loop_root prefix.
        # New resolver: that path is interpreted relative to loop_root.
        nested = loop_root / "blacksmith" / "loop-archives" / "fullprofile-hardening-onda8"
        nested.mkdir(parents=True)
        _write_progress(nested, items=[("001", " ", "x", "T-sonnet-medium")])
        cfg = {
            "name": "fullprofile-hardening-onda8",
            "kind": "daily-loop",
            "basic_flow": {
                "brief_root": str(loop_root),
                "docs_root": str(loop_root),
                "wbs_root": str(loop_root),
                "workspace_root": str(tmp_path),
            },
            "daily_loop": {
                "version": "1.0.0",
                "slug": "fullprofile-hardening-onda8",
                "loop_root": str(loop_root),
                "progress_path": "blacksmith/loop-archives/fullprofile-hardening-onda8/PROGRESS.md",
                "tasks_dir": "tasks",
                "log_path": "_LOOP-LOG.md",
                "total_items": 1,
                "buckets": [
                    {
                        "id": "T-sonnet-medium",
                        "model": "sonnet",
                        "effort": "medium",
                        "task_file": "tasks/T-sonnet-medium.md",
                        "items": ["001"],
                        "items_count": 1,
                    }
                ],
                "do_command": "/daily-loop:do",
            },
        }
        specs = build_daily_loop_specs(cfg, loop_root)
        # 1 clear + 5 body (sonnet/medium/:do/opus/:review-done) + 3 review-final = 9 specs
        assert len(specs) == 9
        # Critical: error path NEVER contains the historic duplication signature.
        # (Test is here for documentation — if a regression brings it back, the
        # missing-PROGRESS test above would catch it via the diagnostic msg.)


# ────────────────────────────────────────────────────────────────────────────
# Self-test of the FASE 6 enforcement (structural — ensures the contract
# documented in enumerate.md FASE 6 cannot be silently violated by future code).
# ────────────────────────────────────────────────────────────────────────────


def test_no_loop_root_placeholder_string_in_emitted_paths(
    loop_root: Path,
) -> None:
    """If a future generator regresses and emits literal `{loop_root}` in
    progress_path (un-substituted template), the error message must surface it
    — never silently ship a broken JSON to workflow-app."""
    cfg = _base_config(loop_root, progress_path="{loop_root}/PROGRESS.md")
    _write_progress(loop_root, items=[("001", " ", "x", "T-sonnet-medium")])
    with pytest.raises(DailyLoopConfigError):
        # Either: missing-file error mentions the literal `{loop_root}` so the
        # operator sees the un-substituted placeholder; or a future explicit
        # check rejects placeholders.
        build_daily_loop_specs(cfg, loop_root)
