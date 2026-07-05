"""Tests for the two Usabilidade button handlers and the shared GROUP_MAP entry.

Covers item 004 of loop 06-23-usabilidade-cliente-final-refactor-pipeline (the
redo after the 06-22 revert, whose root cause was reusing scope=module commands
in a project-level pipeline -> orphans). The architecture is DOIS botoes:

  queue-btn-usabilidade-visual -> Cadeia A (12 specs, 100% project,
                                  zero module-bound)
  queue-btn-usabilidade-ia     -> Cadeia B (13 specs; module-bound commands
                                  always preceded by the micro:* bootstrap that
                                  creates the module; no {N} placeholder)

Both handlers share GROUP_MAP["usabilidade"] (OPUS/HIGH) and a single static
chain each (no A/B branch at runtime, no interview).

Covered cases:

  Gates (no enqueue), per handler
    G1  no project loaded            -> warning toast, no pipeline_ready
    G2  config without config_path   -> error toast, no pipeline_ready

  Pipeline emission
    PV  visual -> exactly one pipeline_ready with the 12 logical specs in
        canonical order; $1=config_path for all but /instruction-manual, which
        carries the derived workspace_root
    PI  ia -> exactly one pipeline_ready with the 13 logical specs in canonical
        order; micro:* bootstrap precedes every module-bound command
    PM  every real spec is OPUS / HIGH; GROUP_MAP["usabilidade"] declares them
    PA  anti-orphan invariants: Cadeia A has ZERO module-bound commands; no spec
        carries a literal {N} or {workspace_root} placeholder; no `--module`

Run with: QT_QPA_PLATFORM=offscreen pytest -o addopts="" --no-cov \
          tests/test_usabilidade_handlers.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Tuple

from workflow_app.config.config_parser import PipelineConfig


# ─── Fixtures ────────────────────────────────────────────────────────────── #


def _make_config(tmp_path: Path) -> PipelineConfig:
    """A minimal valid V3-style config pointing at a project.json."""
    cfg_path = tmp_path / ".claude" / "projects" / "site-repo.json"
    return PipelineConfig(
        config_path=str(cfg_path),
        project_name="site-repo",
        brief_root=str(tmp_path / "brief"),
        docs_root=str(tmp_path / "docs"),
        wbs_root=str(tmp_path / "wbs"),
        workspace_root=str(tmp_path / "workspace"),
    )


# Canonical order of the 12 logical commands of Cadeia A (visual).
_EXPECTED_VISUAL = [
    "/usabilidade:detect",
    "/frontend:scan",
    "/frontend:audit",
    "/frontend:mobile-check",
    "/frontend:assets-check",
    "/frontend:report",
    "/tools:layout-full-refactor",
    "/tools:mobile-analysis",
    "/tools:mobile-update",
    "/usabilidade:detect",
    "/frontend:report",
    "/instruction-manual",
]

# Canonical order of the 13 logical commands of Cadeia B (ia).
_EXPECTED_IA = [
    "/usabilidade:detect",
    "/frontend:scan",
    "/frontend:audit",
    "/frontend:report",
    "/micro:brief",
    "/micro:architecture",
    "/micro:specific-flow-prep",
    "/micro:modularize",
    "/micro:review",
    "/build-module-pipeline",
    "/review-executed-module",
    "/front-end-review",
    "/instruction-manual",
]

# Commands that are scope=module (must never appear in Cadeia A).
_MODULE_BOUND = (
    "/build-module-pipeline",
    "/review-executed-module",
    "/micro:brief",
    "/micro:architecture",
    "/micro:specific-flow-prep",
    "/micro:modularize",
    "/micro:review",
)


def _real_specs(specs: List[Any]) -> List[Any]:
    """Strip the /clear, /model X, /effort Y directive headers."""
    return [
        s
        for s in specs
        if not (
            s.name == "/clear"
            or s.name.startswith("/model ")
            or s.name.startswith("/effort ")
        )
    ]


def _drive(handler_name: str, cfg: PipelineConfig | None):
    """Set/clear config, click the named handler, return (toasts, emitted)."""
    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
    from workflow_app.config.app_state import app_state
    from workflow_app.signal_bus import signal_bus

    if cfg is None:
        app_state.clear_config()
    else:
        app_state.set_config(cfg)

    toasts: List[Tuple[str, str]] = []
    emitted: List[List[Any]] = []
    signal_bus.toast_requested.connect(lambda m, lvl: toasts.append((m, lvl)))
    signal_bus.pipeline_ready.connect(emitted.append)

    try:
        widget = CommandQueueWidget()
        try:
            getattr(widget, handler_name)()
        finally:
            widget.deleteLater()
    finally:
        app_state.clear_config()
        try:
            signal_bus.toast_requested.disconnect()
        except (RuntimeError, TypeError):
            pass
        try:
            signal_bus.pipeline_ready.disconnect(emitted.append)
        except (RuntimeError, TypeError):
            pass
    return toasts, emitted


# ─── G1: no project loaded (both handlers) ───────────────────────────────── #


def test_visual_no_config_warns_no_pipeline(qapp) -> None:
    toasts, emitted = _drive("_on_usabilidade_visual_clicked", None)
    assert len(emitted) == 0
    assert len(toasts) == 1
    msg, level = toasts[0]
    assert level == "warning"
    assert "project.json" in msg
    assert "queue-btn-json" in msg


def test_ia_no_config_warns_no_pipeline(qapp) -> None:
    toasts, emitted = _drive("_on_usabilidade_ia_clicked", None)
    assert len(emitted) == 0
    assert len(toasts) == 1
    assert toasts[0][1] == "warning"


# ─── G2: config without config_path (both handlers) ──────────────────────── #


def test_visual_empty_config_path_errors_no_pipeline(qapp, tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    cfg.config_path = ""
    toasts, emitted = _drive("_on_usabilidade_visual_clicked", cfg)
    assert len(emitted) == 0
    assert len(toasts) == 1
    msg, level = toasts[0]
    assert level == "error"
    assert "config_path" in msg


def test_ia_empty_config_path_errors_no_pipeline(qapp, tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    cfg.config_path = ""
    toasts, emitted = _drive("_on_usabilidade_ia_clicked", cfg)
    assert len(emitted) == 0
    assert len(toasts) == 1
    assert toasts[0][1] == "error"


# ─── PV: visual emits 12 ordered specs ───────────────────────────────────── #


def test_visual_twelve_specs_in_order(qapp, tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    path = cfg.config_path
    ws = cfg.workspace_root
    _, emitted = _drive("_on_usabilidade_visual_clicked", cfg)

    assert len(emitted) == 1
    real = _real_specs(emitted[0])
    assert len(real) == 12, f"expected 12 logical specs, got {len(real)}"

    for spec, expected_cmd in zip(real, _EXPECTED_VISUAL):
        if expected_cmd == "/instruction-manual":
            assert spec.name == f"/instruction-manual {ws}", (
                f"instruction-manual must carry derived workspace_root, "
                f"got {spec.name!r}"
            )
        else:
            assert spec.name == f"{expected_cmd} {path}", (
                f"spec {spec.name!r} must be {expected_cmd!r} carrying $1={path!r}"
            )


# ─── PI: ia emits 13 ordered specs, bootstrap precedes module-bound ──────── #


def test_ia_thirteen_specs_in_order(qapp, tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    path = cfg.config_path
    ws = cfg.workspace_root
    _, emitted = _drive("_on_usabilidade_ia_clicked", cfg)

    assert len(emitted) == 1
    real = _real_specs(emitted[0])
    assert len(real) == 13, f"expected 13 logical specs, got {len(real)}"

    names = [s.name for s in real]
    for spec, expected_cmd in zip(real, _EXPECTED_IA):
        if expected_cmd == "/instruction-manual":
            assert spec.name == f"/instruction-manual {ws}"
        else:
            assert spec.name == f"{expected_cmd} {path}"

    # micro:modularize (creates the module) must precede every module-bound
    # consumer of the lock.
    idx_modularize = names.index(f"/micro:modularize {path}")
    idx_build = names.index(f"/build-module-pipeline {path}")
    idx_review_mod = names.index(f"/review-executed-module {path}")
    assert idx_modularize < idx_build < idx_review_mod, (
        "micro:modularize must run before build-module-pipeline and "
        "review-executed-module (lock producer precedes consumers)"
    )


# ─── PM: model/effort ────────────────────────────────────────────────────── #


def test_all_real_specs_are_opus_high(qapp, tmp_path: Path) -> None:
    from workflow_app.domain import EffortLevel, ModelName

    cfg = _make_config(tmp_path)
    for handler in ("_on_usabilidade_visual_clicked", "_on_usabilidade_ia_clicked"):
        _, emitted = _drive(handler, cfg)
        real = _real_specs(emitted[0])
        for spec in real:
            assert spec.model == ModelName.OPUS, f"{spec.name} must be OPUS"
            assert spec.effort == EffortLevel.HIGH, f"{spec.name} must be HIGH"


def test_group_map_declares_usabilidade_opus_high(qapp) -> None:
    from workflow_app.command_queue.command_queue_widget import GROUP_MAP
    from workflow_app.domain import EffortLevel, ModelName

    assert "usabilidade" in GROUP_MAP
    assert GROUP_MAP["usabilidade"]["model"] == ModelName.OPUS
    assert GROUP_MAP["usabilidade"]["effort"] == EffortLevel.HIGH


# ─── PA: anti-orphan invariants ──────────────────────────────────────────── #


def test_cadeia_a_has_zero_module_bound_commands(qapp, tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    _, emitted = _drive("_on_usabilidade_visual_clicked", cfg)
    real = _real_specs(emitted[0])
    for spec in real:
        for mb in _MODULE_BOUND:
            assert not spec.name.startswith(mb), (
                f"Cadeia A (visual) must be 100% project; found module-bound "
                f"command {spec.name!r}"
            )


def test_no_placeholder_or_module_flag_in_any_spec(qapp, tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    for handler in ("_on_usabilidade_visual_clicked", "_on_usabilidade_ia_clicked"):
        _, emitted = _drive(handler, cfg)
        real = _real_specs(emitted[0])
        for spec in real:
            assert "{N}" not in spec.name, f"literal {{N}} placeholder in {spec.name!r}"
            assert "{workspace_root}" not in spec.name, (
                f"literal {{workspace_root}} placeholder in {spec.name!r}"
            )
            assert "--module" not in spec.name, (
                f"--module flag (orphan anti-pattern) in {spec.name!r}"
            )
