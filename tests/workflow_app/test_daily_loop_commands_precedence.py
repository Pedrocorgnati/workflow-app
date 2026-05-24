"""Precedence contract tests for items[k].commands in loader.py.

T2 of loop align-workflow-app-runtime-with-loop-specs introduced canonical
support for `buckets[*].items[*]` declared as a dict with a `commands` list.
When populated, each command is emitted as a literal CommandSpec; when
absent/empty/string-pure, the legacy wrapper
`{do_command} --slug X --item N` is preserved (retro-compat for the
/daily-loop lane and pre-migration archives).

Mirrors the contract in
`blacksmith/loop-archives/align-workflow-app-runtime-with-loop-specs/evidence/BASELINE-CONTRACT.md`
Parts B and D.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from workflow_app.daily_loop import (
    DailyLoopConfigError,
    build_daily_loop_specs,
)
from workflow_app.daily_loop.loader import (
    _resolve_item_commands,
    build_loop_specs,
)


# ────────────────────────────────────────────────────────────────────────────
# Helpers (intentionally duplicated from test_daily_loop_loader.py so this
# file is self-contained and the precedence tests stay isolated from the
# path-resolution fixtures that file evolves around).
# ────────────────────────────────────────────────────────────────────────────


def _write_progress(
    loop_root: Path, items: list[tuple[str, str, str, str]]
) -> None:
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
    (loop_root / "PROGRESS.md").write_text(
        "\n".join(lines) + "\n", encoding="utf-8"
    )


def _cfg(loop_root: Path, items_field: list, kind: str = "daily-loop") -> dict:
    return {
        "name": "test-slug",
        "kind": kind,
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
            "progress_path": "PROGRESS.md",
            "tasks_dir": "tasks",
            "log_path": "_LOOP-LOG.md",
            "total_items": len(items_field),
            "buckets": [
                {
                    "id": "T-sonnet-medium",
                    "model": "sonnet",
                    "effort": "medium",
                    "task_file": "tasks/T-sonnet-medium.md",
                    "items": items_field,
                    "items_count": len(items_field),
                }
            ],
            "do_command": "/daily-loop:do",
        },
    }


@pytest.fixture
def loop_root(tmp_path: Path) -> Path:
    root = tmp_path / "loop-archives" / "test-slug"
    root.mkdir(parents=True)
    (root / "tasks").mkdir()
    return root


def _names(specs) -> list[str]:
    return [s.name for s in specs]


def _do_specs(specs) -> list:
    """Filter only specs that represent the `do` slot or a canonical override.

    Excludes /clear, /model, /effort headers and the per-item :review-done +
    final :review entries. We identify these by the wrapper prefix or by the
    canonical strings produced by the precedence path.
    """
    out = []
    for s in specs:
        n = s.name
        if n.startswith("/clear") or n.startswith("/model ") or n.startswith("/effort "):
            continue
        if n.startswith("/daily-loop:review-done") or n.startswith(
            "/daily-loop:review"
        ):
            continue
        out.append(s)
    return out


# ────────────────────────────────────────────────────────────────────────────
# Unit tests for the pure helper
# ────────────────────────────────────────────────────────────────────────────


class TestResolveItemCommands:
    def _dl(self, items_field: list) -> dict:
        return {
            "buckets": [
                {"id": "B1", "items": items_field},
            ]
        }

    def test_string_item_returns_none(self) -> None:
        assert _resolve_item_commands(self._dl(["001"]), "001") is None

    def test_dict_without_commands_returns_empty_list(self) -> None:
        assert _resolve_item_commands(self._dl([{"id": "001"}]), "001") == []

    def test_dict_with_empty_commands_returns_empty_list(self) -> None:
        assert _resolve_item_commands(
            self._dl([{"id": "001", "commands": []}]), "001"
        ) == []

    def test_dict_with_commands_returns_normalized_list(self) -> None:
        cmds = ["/cmd:update --foo", "  /cmd:review --foo  ", ""]
        out = _resolve_item_commands(
            self._dl([{"id": "001", "commands": cmds}]), "001"
        )
        assert out == ["/cmd:update --foo", "/cmd:review --foo"]

    def test_invalid_commands_type_raises(self) -> None:
        with pytest.raises(DailyLoopConfigError, match="must|deve ser list"):
            _resolve_item_commands(
                self._dl([{"id": "001", "commands": "/cmd:update"}]), "001"
            )

    def test_daily_loop_do_in_commands_is_rejected(self) -> None:
        with pytest.raises(DailyLoopConfigError, match="/daily-loop:do"):
            _resolve_item_commands(
                self._dl(
                    [{"id": "001", "commands": ["/daily-loop:do --slug x"]}]
                ),
                "001",
            )

    def test_unknown_item_returns_none(self) -> None:
        assert _resolve_item_commands(self._dl(["001"]), "999") is None


# ────────────────────────────────────────────────────────────────────────────
# Integration tests through build_daily_loop_specs
# ────────────────────────────────────────────────────────────────────────────


class TestBuildDailyLoopSpecsPrecedence:
    def test_string_items_emit_wrapper_retro_compat(
        self, loop_root: Path
    ) -> None:
        """Legacy lane: items[] = ["001"] -> wrapper /daily-loop:do --slug X --item N."""
        _write_progress(
            loop_root, [("001", " ", "fix foo", "T-sonnet-medium")]
        )
        cfg = _cfg(loop_root, ["001"])
        specs = build_daily_loop_specs(cfg, loop_root)
        do_block = _do_specs(specs)
        assert len(do_block) == 1
        assert do_block[0].name == "/daily-loop:do --slug test-slug --item 001"

    def test_dict_with_commands_emits_literal_specs_no_wrapper(
        self, loop_root: Path
    ) -> None:
        """Canonical lane: items[].commands populated -> 1 CommandSpec per entry."""
        _write_progress(
            loop_root, [("001", " ", "edit foo", "T-sonnet-medium")]
        )
        cfg = _cfg(
            loop_root,
            [
                {
                    "id": "001",
                    "commands": [
                        "/cmd:update --target foo",
                        "/mcp:dual --level 3",
                    ],
                }
            ],
        )
        specs = build_daily_loop_specs(cfg, loop_root)
        names = _names(specs)
        assert "/cmd:update --target foo" in names
        assert "/mcp:dual --level 3" in names
        assert all(
            "--slug test-slug --item 001" not in n
            for n in names
            if not n.startswith("/daily-loop:review")
        ), "wrapper /daily-loop:do must NOT be emitted when commands are populated"

    def test_dict_without_commands_falls_back_to_wrapper(
        self, loop_root: Path
    ) -> None:
        """Fallback explicito: dict sem `commands` -> wrapper /daily-loop:do."""
        _write_progress(
            loop_root, [("001", " ", "edit foo", "T-sonnet-medium")]
        )
        cfg = _cfg(loop_root, [{"id": "001"}])
        specs = build_daily_loop_specs(cfg, loop_root)
        do_block = _do_specs(specs)
        assert len(do_block) == 1
        assert do_block[0].name == "/daily-loop:do --slug test-slug --item 001"

    def test_dict_with_empty_commands_falls_back_to_wrapper(
        self, loop_root: Path
    ) -> None:
        _write_progress(
            loop_root, [("001", " ", "edit foo", "T-sonnet-medium")]
        )
        cfg = _cfg(loop_root, [{"id": "001", "commands": []}])
        specs = build_daily_loop_specs(cfg, loop_root)
        do_block = _do_specs(specs)
        assert len(do_block) == 1
        assert do_block[0].name == "/daily-loop:do --slug test-slug --item 001"

    def test_invalid_commands_type_raises_config_error(
        self, loop_root: Path
    ) -> None:
        _write_progress(
            loop_root, [("001", " ", "edit foo", "T-sonnet-medium")]
        )
        cfg = _cfg(
            loop_root, [{"id": "001", "commands": "/cmd:update --foo"}]
        )
        with pytest.raises(DailyLoopConfigError):
            build_daily_loop_specs(cfg, loop_root)

    def test_review_done_and_final_review_unchanged_under_precedence(
        self, loop_root: Path
    ) -> None:
        """review-done and final review must continue to be wrapper-emitted
        even when items[].commands is populated. Parts B.2 and B.3 of the
        BASELINE-CONTRACT.
        """
        _write_progress(
            loop_root, [("001", " ", "edit foo", "T-sonnet-medium")]
        )
        cfg = _cfg(
            loop_root,
            [{"id": "001", "commands": ["/cmd:update --foo"]}],
        )
        specs = build_daily_loop_specs(cfg, loop_root)
        names = _names(specs)
        assert (
            "/daily-loop:review-done --slug test-slug --item 001" in names
        ), "review-done must remain wrapper-emitted per Part B.2"
        assert "/daily-loop:review --slug test-slug" in names, (
            "final review must remain wrapper-emitted per Part B.3"
        )


# ────────────────────────────────────────────────────────────────────────────
# Same precedence must hold in build_loop_specs (the /loop --task|--cmd|--both
# pipeline) — Part D of the contract.
# ────────────────────────────────────────────────────────────────────────────


class TestBuildLoopSpecsPrecedence:
    def test_loop_string_items_emit_wrapper(self, loop_root: Path) -> None:
        _write_progress(
            loop_root, [("001", " ", "fix bar", "T-sonnet-medium")]
        )
        cfg = _cfg(loop_root, ["001"], kind="loop")
        specs = build_loop_specs(cfg, loop_root)
        do_block = _do_specs(specs)
        assert len(do_block) == 1
        assert do_block[0].name == "/daily-loop:do --slug test-slug --item 001"

    def test_loop_dict_commands_emits_literal(self, loop_root: Path) -> None:
        _write_progress(
            loop_root, [("001", " ", "fix bar", "T-sonnet-medium")]
        )
        cfg = _cfg(
            loop_root,
            [
                {
                    "id": "001",
                    "commands": ["/loop:iteraction:execute-task --task X"],
                }
            ],
            kind="loop",
        )
        specs = build_loop_specs(cfg, loop_root)
        names = _names(specs)
        assert "/loop:iteraction:execute-task --task X" in names
        assert all(
            not n.startswith("/daily-loop:do --slug") for n in names
        ), "wrapper must NOT be emitted when items[].commands is populated"

    def test_loop_canonical_cmds_does_not_inject_review_done(
        self, loop_root: Path
    ) -> None:
        """Anti-regression: build_loop_specs must NOT inject /daily-loop:review-done
        when items[].commands is populated (canonical path).

        Pre-fix (before 2026-05-20), review_done_command was ALWAYS appended
        per-item regardless of whether canonical_cmds was populated. This caused
        cross-lane contamination: /daily-loop:review-done (designed to review
        /daily-loop:do output via --slug --item) was injected after
        /loop:iteraction:execute-task (which operates per task_path with
        delegate_kind routing). A mechanic reviewing a doctor's work.
        """
        _write_progress(
            loop_root, [("001", " ", "fix bar", "T-sonnet-medium")]
        )
        cfg = _cfg(
            loop_root,
            [
                {
                    "id": "001",
                    "commands": [
                        "/loop:iteraction:execute-task --task blacksmith/loop-archives/test-slug/tasks/items/task-001-preparo.md",
                        "/loop:iteraction:review-executed-task --task blacksmith/loop-archives/test-slug/tasks/items/task-001-preparo.md",
                    ],
                }
            ],
            kind="loop",
        )
        specs = build_loop_specs(cfg, loop_root)
        names = _names(specs)
        assert "/loop:iteraction:execute-task --task blacksmith/loop-archives/test-slug/tasks/items/task-001-preparo.md" in names
        assert "/loop:iteraction:review-executed-task --task blacksmith/loop-archives/test-slug/tasks/items/task-001-preparo.md" in names
        assert not any(
            "daily-loop:review-done" in n for n in names
        ), "/daily-loop:review-done must NOT be injected when canonical_cmds is populated (cross-lane contamination)"

    def test_loop_fallback_still_injects_review_done(
        self, loop_root: Path
    ) -> None:
        """Fallback path: build_loop_specs MUST inject review_done_command when
        canonical_cmds is empty (items without populated commands).

        This is the legitimate use of review_done_command in the /loop lane —
        only for items that fall back to the do_command wrapper.
        """
        _write_progress(
            loop_root, [("001", " ", "fix bar", "T-sonnet-medium")]
        )
        cfg = _cfg(
            loop_root,
            [{"id": "001", "commands": []}],
            kind="loop",
        )
        specs = build_loop_specs(cfg, loop_root)
        names = _names(specs)
        assert any(
            "daily-loop:review-done" in n for n in names
        ), "review_done_command must still be injected in fallback path (empty commands)"

    def test_daily_loop_lane_review_done_unchanged(
        self, loop_root: Path
    ) -> None:
        """Regression guard: build_daily_loop_specs must continue to emit
        /daily-loop:review-done even when items[].commands is populated.

        The fix in build_loop_specs must NOT affect the legacy /daily-loop lane.
        """
        _write_progress(
            loop_root, [("001", " ", "edit foo", "T-sonnet-medium")]
        )
        cfg = _cfg(
            loop_root,
            [{"id": "001", "commands": ["/cmd:update --foo"]}],
        )
        specs = build_daily_loop_specs(cfg, loop_root)
        names = _names(specs)
        assert (
            "/daily-loop:review-done --slug test-slug --item 001" in names
        ), "daily-loop lane must continue to emit review-done unconditionally (not affected by loop fix)"
