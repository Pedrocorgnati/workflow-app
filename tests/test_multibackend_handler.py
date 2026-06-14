"""Tests for `_on_multibackend_clicked` and the multibackend GROUP_MAP entry.

Closes the item-7 acceptance gap of loop
06-09-multibackend-pipeline-estatica-multitenant: the button handler that
enqueues the 6 `/multibackend:*` subcommands had no pytest coverage.

Covered cases:

  Gates (no enqueue)
    G1  no project loaded            -> warning toast, no pipeline_ready
    G2  config without config_path   -> error toast, no pipeline_ready

  Pipeline emission
    P1  config loaded -> exactly one pipeline_ready with the 6 logical
        `/multibackend:*` specs in canonical order, each carrying $1=config_path
    P2  the 6 real specs all use ModelName.OPUS / EffortLevel.HIGH
    P3  GROUP_MAP["multibackend"] declares model+effort (OPUS/HIGH)

Run with: QT_QPA_PLATFORM=offscreen pytest -o addopts="" --no-cov \
          tests/test_multibackend_handler.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Tuple

from workflow_app.config.config_parser import PipelineConfig


# ─── Fixtures ────────────────────────────────────────────────────────────── #


def _make_config(tmp_path: Path) -> PipelineConfig:
    """A minimal valid V3-style config pointing at a site-repo project.json."""
    cfg_path = tmp_path / ".claude" / "projects" / "site-repo.json"
    return PipelineConfig(
        config_path=str(cfg_path),
        project_name="site-repo",
        brief_root=str(tmp_path / "brief"),
        docs_root=str(tmp_path / "docs"),
        wbs_root=str(tmp_path / "wbs"),
        workspace_root=str(tmp_path / "workspace"),
    )


# Canonical order of the 6 subcommands the handler must enqueue.
_EXPECTED_ORDER = [
    "/multibackend:scan",
    "/multibackend:link-auth",
    "/multibackend:env-wire",
    "/multibackend:build-verify",
    "/multibackend:deploy",
    "/multibackend:verify-prod",
]


def _real_specs(specs: List[Any]) -> List[Any]:
    """Strip the /clear, /model X, /effort Y directive headers that
    `_inject_clears` interleaves, leaving only the logical commands."""
    return [
        s
        for s in specs
        if not (
            s.name == "/clear"
            or s.name.startswith("/model ")
            or s.name.startswith("/effort ")
        )
    ]


# ─── G1: no project loaded ───────────────────────────────────────────────── #


def test_no_config_emits_warning_toast_no_pipeline(qapp) -> None:
    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
    from workflow_app.config.app_state import app_state
    from workflow_app.signal_bus import signal_bus

    app_state.clear_config()

    toasts: List[Tuple[str, str]] = []
    emitted: List[List[Any]] = []
    signal_bus.toast_requested.connect(lambda m, lvl: toasts.append((m, lvl)))
    signal_bus.pipeline_ready.connect(emitted.append)

    try:
        widget = CommandQueueWidget()
        try:
            widget._on_multibackend_clicked()
        finally:
            widget.deleteLater()
    finally:
        try:
            signal_bus.toast_requested.disconnect()
        except (RuntimeError, TypeError):
            pass
        try:
            signal_bus.pipeline_ready.disconnect(emitted.append)
        except (RuntimeError, TypeError):
            pass

    assert len(emitted) == 0, "no pipeline must be emitted without a project"
    assert len(toasts) == 1, "exactly one gate toast expected"
    msg, level = toasts[0]
    assert level == "warning"
    assert "project.json" in msg
    assert "queue-btn-json" in msg


# ─── G2: config without config_path ──────────────────────────────────────── #


def test_empty_config_path_emits_error_toast_no_pipeline(qapp, tmp_path: Path) -> None:
    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
    from workflow_app.config.app_state import app_state
    from workflow_app.signal_bus import signal_bus

    cfg = _make_config(tmp_path)
    cfg.config_path = ""  # PipelineConfig is a plain @dataclass (mutable)
    app_state.set_config(cfg)

    toasts: List[Tuple[str, str]] = []
    emitted: List[List[Any]] = []
    signal_bus.toast_requested.connect(lambda m, lvl: toasts.append((m, lvl)))
    signal_bus.pipeline_ready.connect(emitted.append)

    try:
        widget = CommandQueueWidget()
        try:
            widget._on_multibackend_clicked()
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

    assert len(emitted) == 0, "no pipeline must be emitted without config_path"
    assert len(toasts) == 1
    msg, level = toasts[0]
    assert level == "error"
    assert "config_path" in msg


# ─── P1: happy path emits the 6 ordered specs with $1 = config_path ──────── #


def test_six_specs_enqueued_in_order_with_path(qapp, tmp_path: Path) -> None:
    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
    from workflow_app.config.app_state import app_state
    from workflow_app.signal_bus import signal_bus

    cfg = _make_config(tmp_path)
    path = cfg.config_path
    app_state.set_config(cfg)

    emitted: List[List[Any]] = []
    signal_bus.pipeline_ready.connect(emitted.append)

    try:
        widget = CommandQueueWidget()
        try:
            widget._on_multibackend_clicked()
        finally:
            widget.deleteLater()
    finally:
        app_state.clear_config()
        try:
            signal_bus.pipeline_ready.disconnect(emitted.append)
        except (RuntimeError, TypeError):
            pass

    assert len(emitted) == 1, "exactly one pipeline_ready emission expected"
    real = _real_specs(emitted[0])
    assert len(real) == 6, f"expected 6 logical specs, got {len(real)}"

    for spec, expected_cmd in zip(real, _EXPECTED_ORDER):
        assert spec.name == f"{expected_cmd} {path}", (
            f"spec {spec.name!r} must be {expected_cmd!r} carrying $1={path!r}"
        )


# ─── P2: every real spec is OPUS / HIGH ──────────────────────────────────── #


def test_real_specs_are_opus_high(qapp, tmp_path: Path) -> None:
    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
    from workflow_app.config.app_state import app_state
    from workflow_app.domain import EffortLevel, ModelName
    from workflow_app.signal_bus import signal_bus

    cfg = _make_config(tmp_path)
    app_state.set_config(cfg)

    emitted: List[List[Any]] = []
    signal_bus.pipeline_ready.connect(emitted.append)

    try:
        widget = CommandQueueWidget()
        try:
            widget._on_multibackend_clicked()
        finally:
            widget.deleteLater()
    finally:
        app_state.clear_config()
        try:
            signal_bus.pipeline_ready.disconnect(emitted.append)
        except (RuntimeError, TypeError):
            pass

    real = _real_specs(emitted[0])
    for spec in real:
        assert spec.model == ModelName.OPUS, f"{spec.name} must be OPUS"
        assert spec.effort == EffortLevel.HIGH, f"{spec.name} must be HIGH effort"


# ─── P3: GROUP_MAP declares the multibackend group ───────────────────────── #


def test_group_map_multibackend_declares_opus_high() -> None:
    from workflow_app.command_queue.command_queue_widget import GROUP_MAP
    from workflow_app.domain import EffortLevel, ModelName

    assert "multibackend" in GROUP_MAP
    entry = GROUP_MAP["multibackend"]
    assert entry["model"] == ModelName.OPUS
    assert entry["effort"] == EffortLevel.HIGH


# ─── P4: /clear interleaving (disk-handoff contract) ─────────────────────── #


def test_clears_interleave_each_subcommand(qapp, tmp_path: Path) -> None:
    """Each /multibackend:* communicates via scan-report.json on disk, not via
    conversation context, so the handler must put a /clear before every
    subcommand. `_inject_clears` emits the full /clear+/model+/effort triplet
    once at the head, then a lone /clear before each subsequent command."""
    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
    from workflow_app.config.app_state import app_state
    from workflow_app.signal_bus import signal_bus

    cfg = _make_config(tmp_path)
    app_state.set_config(cfg)

    emitted: List[List[Any]] = []
    signal_bus.pipeline_ready.connect(emitted.append)

    try:
        widget = CommandQueueWidget()
        try:
            widget._on_multibackend_clicked()
        finally:
            widget.deleteLater()
    finally:
        app_state.clear_config()
        try:
            signal_bus.pipeline_ready.disconnect(emitted.append)
        except (RuntimeError, TypeError):
            pass

    raw = emitted[0]
    # Head triplet: /clear, /model opus, /effort high.
    assert raw[0].name == "/clear"
    assert raw[1].name.startswith("/model ")
    assert raw[2].name.startswith("/effort ")

    # Every real subcommand (except the first, guarded by the triplet) must be
    # immediately preceded by a lone /clear so no disk-handoff context leaks.
    names = [s.name for s in raw]
    for cmd in _EXPECTED_ORDER:
        idx = next(i for i, n in enumerate(names) if n.startswith(cmd + " "))
        if cmd == _EXPECTED_ORDER[0]:
            assert names[idx - 1].startswith("/effort ")
        else:
            assert names[idx - 1] == "/clear", (
                f"{cmd} must be preceded by /clear, got {names[idx - 1]!r}"
            )
    # At least one /clear per subcommand boundary (head triplet + 5 separators).
    assert names.count("/clear") >= 6


# ─── P5: template label reflects the enqueued pipeline ───────────────────── #


def test_template_label_set_with_slug_and_count(qapp, tmp_path: Path) -> None:
    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
    from workflow_app.config.app_state import app_state
    from workflow_app.signal_bus import signal_bus

    cfg = _make_config(tmp_path)
    app_state.set_config(cfg)

    emitted: List[List[Any]] = []
    signal_bus.pipeline_ready.connect(emitted.append)

    try:
        widget = CommandQueueWidget()
        try:
            widget._on_multibackend_clicked()
            label_text = widget._template_label.text()
            label_hidden = widget._template_label.isHidden()
        finally:
            widget.deleteLater()
    finally:
        app_state.clear_config()
        try:
            signal_bus.pipeline_ready.disconnect(emitted.append)
        except (RuntimeError, TypeError):
            pass

    assert "multibackend:" in label_text
    assert "site-repo" in label_text  # Path(config_path).stem
    assert "specs" in label_text
    assert label_hidden is False
