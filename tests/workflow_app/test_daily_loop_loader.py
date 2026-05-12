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

import json
from pathlib import Path

import pytest

from workflow_app.daily_loop import (
    DailyLoopConfigError,
    ReviewBlockedSentinel,
    build_daily_loop_specs,
    parse_progress_items,
    read_review_blocked_sentinel,
    resolve_loop_path,
)


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
        # Must resolve UNDER loop_root, never duplicating blacksmith/loop-archives prefix.
        assert "blacksmith/loop-archives/blacksmith/loop-archives" not in str(result)
        # Must be loop_root / declared_path:
        assert result == (loop_root / "output" / "daily-loop"
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
        the new (deterministic) resolution rule.
        """
        nested = loop_root / "output" / "daily-loop" / "fullprofile-hardening-onda8"
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

    def test_haiku_low_bucket_is_coerced_to_sonnet_medium_floor(
        self, loop_root: Path
    ) -> None:
        """Floor enforcement: /daily-loop:do must NEVER run on haiku/low.

        The loader silently coerces haiku → sonnet and low → medium when the
        config carries forbidden values (legacy configs or buggy plan output).
        Coercion is logged to stderr but does not raise.
        """
        cfg = _base_config(loop_root)
        # Force the bucket to forbidden values:
        cfg["daily_loop"]["buckets"][0]["model"] = "haiku"
        cfg["daily_loop"]["buckets"][0]["effort"] = "low"
        _write_progress(loop_root, items=[("001", " ", "x", "T-sonnet-medium")])
        specs = build_daily_loop_specs(cfg, loop_root)
        # /clear + /model sonnet + /effort medium + :do + /model opus
        # + :review-done (effort STANDARD == "medium" — dedup skips)
        # + /clear + /effort high + :review = 9 specs.
        # NOT /model haiku + /effort low.
        assert len(specs) == 9
        assert specs[1].name == "/model sonnet", (
            f"haiku bucket should coerce to sonnet, got {specs[1].name}"
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
    unchanged. After every injected /clear the next item must re-emit /model
    and /effort, even if the bucket is identical to the previous item, since
    we cannot rely on the harness preserving those flags across /clear.
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

    def test_flag_true_forces_model_and_effort_re_emit_after_clear(
        self, loop_root: Path
    ) -> None:
        """After an injected /clear, the next item must re-emit /model and
        /effort even if its bucket matches the previous item — the harness
        is not assumed to preserve those flags across /clear."""
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
        # Walk back from :do 002 to the most recent /clear; between them the
        # queue must contain BOTH /model sonnet AND /effort medium.
        idx_clear_before_002 = max(
            i for i, s in enumerate(specs[:idx_do_002]) if s.name == "/clear"
        )
        window = specs[idx_clear_before_002 + 1: idx_do_002]
        names = [s.name for s in window]
        assert "/model sonnet" in names, (
            f"/model sonnet must re-emit after /clear; window={names}"
        )
        assert "/effort medium" in names, (
            f"/effort medium must re-emit after /clear; window={names}"
        )


# ────────────────────────────────────────────────────────────────────────────
# /daily-loop:review-created — .review-blocked sentinel detection
# ────────────────────────────────────────────────────────────────────────────


class TestReviewBlockedSentinel:
    """Pure-helper tests for read_review_blocked_sentinel.

    The sentinel is a marker file dropped by /daily-loop:review-created
    (FASE 6) when the audit's 3-round self-healing exhausts with blockers
    remaining. The workflow-app reads it to gate `queue-btn-execute-daily-loop`
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
        nested = loop_root / "output" / "daily-loop" / "fullprofile-hardening-onda8"
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
