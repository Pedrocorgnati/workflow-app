"""Tests for `workflow_app.dcp.flow_validation` (loop 06-09).

Pins the load-time guard that keeps phantom per-task entries (stale
SPECIFIC-FLOW.json synthesized from `loop_multiplier` pre-fix-06-08) and
unrendered placeholder stubs (`TASK-{k}`) out of the rendered queue
(`queue-command-list`), while NEVER dropping entries it cannot verify.
"""

from __future__ import annotations

from pathlib import Path

from workflow_app.dcp.flow_validation import validate_flow_commands


def _cmd(name: str) -> dict:
    return {"name": name, "model": "sonnet", "effort": "medium", "phase": "B3"}


def _module(tmp_path: Path, cm_id: str = "module-1-x") -> Path:
    d = tmp_path / "wbs" / "modules" / cm_id
    d.mkdir(parents=True)
    return d


# ── placeholder guard ──────────────────────────────────────────────────────


def test_unresolved_placeholder_dropped(tmp_path: Path) -> None:
    d = _module(tmp_path)
    res = validate_flow_commands(
        [_cmd(f"/execute-task {d}/TASK-{{k}}")],
        cm_id="module-1-x",
        project_dir=tmp_path,
    )
    assert res.valid == []
    assert len(res.dropped) == 1
    assert "placeholder nao resolvido" in res.dropped[0].reason
    assert "{k}" in res.dropped[0].reason


def test_clean_names_keep_no_placeholder_false_positive(tmp_path: Path) -> None:
    # Braces never appear in legitimately rendered commands; flags/paths pass.
    res = validate_flow_commands(
        [_cmd("/qa:trace --module 1"), _cmd("/build-verify")],
        cm_id="module-1-x",
        project_dir=tmp_path,
    )
    assert [c["name"] for c in res.valid] == ["/qa:trace --module 1", "/build-verify"]
    assert res.dropped == []


# ── task existence guard ───────────────────────────────────────────────────


def test_phantom_task_absolute_path_dropped(tmp_path: Path) -> None:
    d = _module(tmp_path)
    (d / "TASK-1.md").touch()
    (d / "TASK-2.md").touch()
    (d / "TASK-3.md").touch()
    # The exact recurring symptom: 4th entry synthesized from a stale count.
    res = validate_flow_commands(
        [_cmd(f"/execute-task {d}/TASK-{k}.md") for k in (1, 2, 3, 4)],
        cm_id="module-1-x",
        project_dir=tmp_path,
    )
    assert [c["name"].rsplit("/", 1)[-1] for c in res.valid] == [
        "TASK-1.md", "TASK-2.md", "TASK-3.md",
    ]
    assert len(res.dropped) == 1
    assert "TASK-4.md" in res.dropped[0].reason
    assert "TASK inexistente" in res.dropped[0].reason


def test_relative_path_resolved_against_project_dir(tmp_path: Path) -> None:
    d = _module(tmp_path)
    (d / "TASK-0.md").touch()
    rel = "wbs/modules/module-1-x"
    res = validate_flow_commands(
        [_cmd(f"/create-task {rel}/TASK-0.md"), _cmd(f"/create-task {rel}/TASK-9.md")],
        cm_id="module-1-x",
        project_dir=tmp_path,
    )
    assert [c["name"] for c in res.valid] == [f"/create-task {rel}/TASK-0.md"]
    assert len(res.dropped) == 1
    assert "TASK-9.md" in res.dropped[0].reason


def test_flow_path_basename_fallback(tmp_path: Path) -> None:
    # Canonical flow location: SPECIFIC-FLOW.json lives in the module dir, so
    # basenames resolve even when project_dir is unavailable and the rendered
    # path uses a foreign root (e.g. flow generated on another checkout).
    d = _module(tmp_path)
    (d / "TASK-1.md").touch()
    flow = d / "SPECIFIC-FLOW.json"
    res = validate_flow_commands(
        [
            _cmd("/execute-task /other/checkout/modules/module-1-x/TASK-1.md"),
            _cmd("/execute-task /other/checkout/modules/module-1-x/TASK-4.md"),
        ],
        cm_id="module-1-x",
        project_dir=None,
        flow_path=flow,
    )
    assert len(res.valid) == 1
    assert "TASK-1.md" in res.valid[0]["name"]
    assert len(res.dropped) == 1
    assert "TASK-4.md" in res.dropped[0].reason


def test_unverifiable_relative_ref_kept_fail_open(tmp_path: Path) -> None:
    # Relative ref, no project_dir, flow not at canonical module location:
    # nothing to check against -> keep (fail-open, no false drops).
    res = validate_flow_commands(
        [_cmd("/execute-task modules/module-1-x/TASK-7.md")],
        cm_id="module-1-x",
        project_dir=None,
        flow_path=tmp_path / "workflow-app" / "SPECIFIC-FLOW.json",
    )
    assert len(res.valid) == 1
    assert res.dropped == []


def test_decimal_task_index_validated(tmp_path: Path) -> None:
    d = _module(tmp_path)
    (d / "TASK-0.5.md").touch()
    res = validate_flow_commands(
        [
            _cmd(f"/execute-task {d}/TASK-0.5.md"),
            _cmd(f"/execute-task {d}/TASK-1.5.md"),
        ],
        cm_id="module-1-x",
        project_dir=tmp_path,
    )
    assert len(res.valid) == 1
    assert len(res.dropped) == 1
    assert "TASK-1.5.md" in res.dropped[0].reason


def test_non_task_commands_untouched(tmp_path: Path) -> None:
    _module(tmp_path)
    cmds = [
        _cmd("/dcp:congruence-check --module 1"),
        _cmd("/clear"),
        {"weird": True},
        _cmd(""),
    ]
    res = validate_flow_commands(cmds, cm_id="module-1-x", project_dir=tmp_path)
    assert res.valid == cmds
    assert res.dropped == []


def test_companion_artifact_ref_not_matched_as_task(tmp_path: Path) -> None:
    # `TASK-1-REVIEW.md` is a companion, not an executable task ref: the regex
    # must not classify it as a TASK reference (no drop even though a literal
    # exists-check would fail for it).
    d = _module(tmp_path)
    res = validate_flow_commands(
        [_cmd(f"/review-created-task {d}/TASK-1-REVIEW.md")],
        cm_id="module-1-x",
        project_dir=tmp_path,
    )
    assert len(res.valid) == 1
    assert res.dropped == []


def test_placeholder_mode_task_only_keeps_freetext_braces():
    """task-only (restore de snapshot): `{slug}` em texto livre passa; a
    assinatura `TASK-{k}` do stub do gerador continua derrubando."""
    from workflow_app.dcp.flow_validation import validate_flow_commands

    cmds = [
        {"name": "/mcp:codex revisar output/wbs/{slug}/intake-review/"},
        {"name": "/execute-task --module 7 --task TASK-{k}"},
    ]
    res = validate_flow_commands(cmds, cm_id="module-7-x", placeholder_mode="task-only")
    assert [c["name"] for c in res.valid] == [
        "/mcp:codex revisar output/wbs/{slug}/intake-review/"
    ]
    assert len(res.dropped) == 1 and "TASK-{k}" in res.dropped[0].name


def test_placeholder_mode_strict_drops_any_identifier():
    """strict (load do SPECIFIC-FLOW.json): qualquer `{ident}` e drift do
    produtor — derruba mesmo fora de contexto TASK."""
    from workflow_app.dcp.flow_validation import validate_flow_commands

    res = validate_flow_commands(
        [{"name": "/qa:prep --module {module_id}"}], cm_id="module-7-x"
    )
    assert res.valid == []
    assert len(res.dropped) == 1
