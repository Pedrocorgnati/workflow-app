"""Tests for AppState typed slots (loop 06-26 / item 002).

Cobre isolamento granular entre os slots tipados de project e loop, a facade
legada derivada (``config``/``has_config``) e o empty state pós-``clear_all``.
"""

from __future__ import annotations

import pytest

from workflow_app.config.app_state import AppState
from workflow_app.config.config_parser import PipelineConfig


def _mk_config(name: str) -> PipelineConfig:
    """PipelineConfig minimo distinguivel por ``name``."""
    return PipelineConfig(
        config_path=f"/tmp/{name}/.claude/project.json",
        project_name=name,
        brief_root=f"brief/{name}",
        docs_root=f"docs/{name}",
        wbs_root=f"wbs/{name}",
        workspace_root=f"ws/{name}",
    )


@pytest.fixture
def state() -> AppState:
    return AppState()


# ---------------------------------------------------------------------------
# Empty state
# ---------------------------------------------------------------------------
def test_empty_state_defaults(state: AppState) -> None:
    assert state.project_config is None
    assert state.loop_config is None
    assert state.has_project is False
    assert state.has_loop is False
    assert state.has_config is False
    assert state.config is None
    assert state.project_name == ""
    assert state.loop_mode is None


def test_fresh_states_are_equal() -> None:
    assert AppState() == AppState()


# ---------------------------------------------------------------------------
# has_project / has_loop derivam dos slots
# ---------------------------------------------------------------------------
def test_has_project_and_has_loop_track_slots(state: AppState) -> None:
    assert state.has_project is False and state.has_loop is False

    state.set_project_config(_mk_config("proj"))
    assert state.has_project is True and state.has_loop is False

    state.set_loop_config(_mk_config("loop"))
    assert state.has_project is True and state.has_loop is True


# ---------------------------------------------------------------------------
# Isolamento de carregamento (Aceite)
# ---------------------------------------------------------------------------
def test_loading_loop_does_not_clear_project(state: AppState) -> None:
    proj = _mk_config("proj")
    state.set_project_config(proj)
    state.set_loop_config(_mk_config("loop"))
    assert state.project_config is proj
    assert state.has_project is True


def test_loading_project_does_not_clear_loop(state: AppState) -> None:
    loop = _mk_config("loop")
    state.set_loop_config(loop)
    state.set_project_config(_mk_config("proj"))
    assert state.loop_config is loop
    assert state.has_loop is True


# ---------------------------------------------------------------------------
# Clear granular (Aceite)
# ---------------------------------------------------------------------------
def test_clear_loop_does_not_clear_project(state: AppState) -> None:
    proj = _mk_config("proj")
    state.set_project_config(proj)
    state.set_loop_config(_mk_config("loop"))
    state.set_loop_mode("task")

    state.clear_loop()

    assert state.has_loop is False
    assert state.loop_config is None
    assert state.loop_mode is None
    assert state.project_config is proj
    assert state.has_project is True


def test_clear_project_does_not_clear_loop(state: AppState) -> None:
    loop = _mk_config("loop")
    state.set_project_config(_mk_config("proj"))
    state.set_loop_config(loop)
    state.set_loop_mode("task")

    state.clear_project()

    assert state.has_project is False
    assert state.project_config is None
    assert state.loop_config is loop
    assert state.has_loop is True
    assert state.loop_mode == "task"  # loop_mode pertence ao slot de loop


# ---------------------------------------------------------------------------
# clear_all retorna ao empty state (igualdade canonica com AppState())
# ---------------------------------------------------------------------------
def test_clear_all_returns_to_empty_state() -> None:
    state = AppState()
    state.set_project_config(_mk_config("proj"))
    state.set_loop_config(_mk_config("loop"))
    state.set_loop_mode("both")

    state.clear_all()

    assert state.has_project is False
    assert state.has_loop is False
    assert state.config is None
    assert state == AppState()


# ---------------------------------------------------------------------------
# Facade legada derivada dos slots tipados
# ---------------------------------------------------------------------------
def test_legacy_config_derives_project_first(state: AppState) -> None:
    proj = _mk_config("proj")
    loop = _mk_config("loop")
    state.set_loop_config(loop)
    # so loop carregado -> config cai para o loop
    assert state.config is loop
    assert state.has_config is True
    assert state.project_name == "loop"

    state.set_project_config(proj)
    # project presente vence a derivacao
    assert state.config is proj
    assert state.project_name == "proj"


def test_legacy_set_config_routes_to_project_slot(state: AppState) -> None:
    cfg = _mk_config("legacy")
    state.set_config(cfg)
    assert state.project_config is cfg
    assert state.has_project is True
    assert state.config is cfg


def test_legacy_clear_config_clears_everything(state: AppState) -> None:
    state.set_project_config(_mk_config("proj"))
    state.set_loop_config(_mk_config("loop"))
    state.set_loop_mode("task")

    state.clear_config()

    assert state == AppState()
