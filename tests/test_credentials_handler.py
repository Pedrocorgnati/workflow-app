"""Tests for the Credentials button handler (queue-btn-credentials).

Covers the new heterogeneous-tier pipeline button in the Auxiliar tab:
  /credentials:env-creation -> /credentials:create -> /credentials:execute

Covered cases:
  - Button existence, label, tooltip and grid order
  - Gate without project.json loaded -> warning toast, no pipeline_ready
  - Gate with empty config_path -> error toast, no pipeline_ready
  - Successful enqueue -> exactly one pipeline_ready with 3 real specs
  - Per-spec model/effort tiers: (SONNET, LOW), (OPUS, HIGH), (SONNET, HIGH)
  - Expanded directive list via _inject_clears (no /effort in 3rd group)
  - Provider routing -> Provider.CLAUDE even with T2/T3 workers enabled
  - Whitelist invariants -> credentials:* NOT in kimi/codex whitelists

Run with:
  QT_QPA_PLATFORM=offscreen pytest -o addopts="" --no-cov \
    tests/test_credentials_handler.py
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, List, Tuple

import pytest
from PySide6.QtWidgets import QPushButton

from workflow_app.command_queue.codex_whitelist import CODEX_COMPATIBLE_COMMANDS
from workflow_app.command_queue.kimi_whitelist import KIMI_COMPATIBLE_COMMANDS
from workflow_app.command_queue.provider_router import Provider, RoutingState, classify_provider
from workflow_app.config.app_state import app_state
from workflow_app.config.config_parser import PipelineConfig
from workflow_app.domain import EffortLevel, ModelName
from workflow_app.signal_bus import signal_bus


# ─── Fixtures ────────────────────────────────────────────────────────────── #


def _make_config(tmp_path: Path) -> PipelineConfig:
    """A minimal valid config pointing at a project.json."""
    cfg_path = tmp_path / ".claude" / "projects" / "site-repo.json"
    return PipelineConfig(
        config_path=str(cfg_path),
        project_name="site-repo",
        brief_root=str(tmp_path / "brief"),
        docs_root=str(tmp_path / "docs"),
        wbs_root=str(tmp_path / "wbs"),
        workspace_root=str(tmp_path / "workspace"),
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


def _drive(cfg: PipelineConfig | None):
    """Set/clear config, click the handler, return (toasts, emitted)."""
    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget

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
            widget._on_credentials_clicked()
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


@pytest.fixture()
def widget(qapp, qtbot):
    """Fresh CommandQueueWidget with app_state cleared."""
    app_state.clear_config()
    from workflow_app.command_queue.command_queue_widget import CommandQueueWidget

    w = CommandQueueWidget()
    qtbot.addWidget(w)
    w.show()
    try:
        yield w
    finally:
        app_state.clear_config()
        w.deleteLater()


# ─── Button existence / tooltip ──────────────────────────────────────────── #


def _find_button_by_testid(widget: Any, testid: str) -> QPushButton | None:
    """Search inside the header widget (where the Auxiliar tab lives)."""
    header = getattr(widget, "header_widget", None)
    search_root = header if header is not None else widget
    for btn in search_root.findChildren(QPushButton):
        if btn.property("testid") == testid:
            return btn
    return None


def test_button_exists_with_correct_testid(widget):
    """Credentials button exists in the Auxiliar tab with the right testid."""
    btn = _find_button_by_testid(widget, "queue-btn-credentials")
    assert btn is not None, "queue-btn-credentials ausente em queue-tab-auxiliar"
    assert btn.text() == "Credentials"


def test_button_tooltip_mentions_chain_and_json_button(widget):
    """Tooltip describes the command chain and names queue-btn-json."""
    btn = _find_button_by_testid(widget, "queue-btn-credentials")
    assert btn is not None
    tooltip = btn.toolTip()
    assert "Credentials" in tooltip
    assert "/credentials:env-creation" in tooltip
    assert "/credentials:execute" in tooltip
    assert "metrics-project-pill" in tooltip
    assert "queue-btn-json" in tooltip


def test_button_positioned_before_maintenance(widget):
    """Credentials button appears before the Maintenance button in the grid."""
    header = getattr(widget, "header_widget", None)
    search_root = header if header is not None else widget
    testids = [b.property("testid") for b in search_root.findChildren(QPushButton)]
    assert "queue-btn-credentials" in testids
    assert "queue-btn-maintenance" in testids
    assert testids.index("queue-btn-credentials") < testids.index("queue-btn-maintenance")


# ─── Gates ───────────────────────────────────────────────────────────────── #


def test_no_config_warns_no_pipeline(qapp) -> None:
    toasts, emitted = _drive(None)
    assert len(emitted) == 0
    assert len(toasts) == 1
    msg, level = toasts[0]
    assert level == "warning"
    assert "project.json" in msg
    assert "queue-btn-json" in msg


def test_empty_config_path_errors_no_pipeline(qapp, tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    cfg.config_path = ""
    toasts, emitted = _drive(cfg)
    assert len(emitted) == 0
    assert len(toasts) == 1
    msg, level = toasts[0]
    assert level == "error"
    assert "config_path" in msg
    assert "queue-btn-json" in msg


# ─── Pipeline emission and ordering ──────────────────────────────────────── #


def test_successful_enqueue_emits_three_specs(qapp, tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    path = cfg.config_path
    _, emitted = _drive(cfg)

    assert len(emitted) == 1
    real = _real_specs(emitted[0])
    assert len(real) == 3

    expected = [
        f"/credentials:env-creation {path}",
        f"/credentials:create {path}",
        f"/credentials:execute {path}",
    ]
    for spec, exp in zip(real, expected):
        assert spec.name == exp


def test_tiers_are_heterogeneous(qapp, tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    _, emitted = _drive(cfg)
    real = _real_specs(emitted[0])

    assert len(real) == 3
    assert (real[0].model, real[0].effort) == (ModelName.SONNET, EffortLevel.LOW)
    assert (real[1].model, real[1].effort) == (ModelName.OPUS, EffortLevel.HIGH)
    assert (real[2].model, real[2].effort) == (ModelName.SONNET, EffortLevel.HIGH)


def test_expanded_directives_match_inject_clears(qapp, tmp_path: Path) -> None:
    """The emitted spec list follows _inject_clears anti-redundancy rules."""
    cfg = _make_config(tmp_path)
    path = cfg.config_path
    _, emitted = _drive(cfg)
    specs = emitted[0]

    names = [s.name for s in specs]
    expected = [
        "/clear",
        "/model sonnet",
        "/effort low",
        f"/credentials:env-creation {path}",
        "/clear",
        "/model opus",
        "/effort high",
        f"/credentials:create {path}",
        "/clear",
        "/model sonnet",
        f"/credentials:execute {path}",
    ]
    assert names == expected


# ─── Provider routing and whitelist invariants ───────────────────────────── #


def test_all_real_specs_route_to_claude_with_workers_enabled(qapp, tmp_path: Path) -> None:
    cfg = _make_config(tmp_path)
    _, emitted = _drive(cfg)
    real = _real_specs(emitted[0])

    state = RoutingState(
        kimi_worker_enabled=True,
        codex_worker_enabled=True,
        main_llm="kimi",  # Even if Main is Kimi, credentials:* are Claude-only.
    )
    for spec in real:
        assert classify_provider(spec, state) == Provider.CLAUDE


def test_credentials_commands_not_in_kimi_whitelist() -> None:
    for cmd in (
        "/credentials:env-creation",
        "/credentials:create",
        "/credentials:execute",
    ):
        assert cmd not in KIMI_COMPATIBLE_COMMANDS, f"{cmd} must not be Kimi-whitelisted"


def test_credentials_commands_not_in_codex_whitelist() -> None:
    for cmd in (
        "/credentials:env-creation",
        "/credentials:create",
        "/credentials:execute",
    ):
        assert cmd not in CODEX_COMPATIBLE_COMMANDS, f"{cmd} must not be Codex-whitelisted"
