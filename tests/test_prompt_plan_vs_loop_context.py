"""Contrato do botao `output-btn-prompt-plan-vs-loop-coverage`.

O `.md` (ai-forge/custom-prompts/prompts-subtab/plan-vs-loop-coverage.md) exige
na FASE 0 exatamente dois artefatos da UI: o `_LOOP-CONFIG.json` do anexo loop
(attachments-loop-row / metrics-loop-pill) e o `.md` do plano aberto em
`brainstorm-md-picker-row`. O terminal nao enxerga o estado do app e o proprio
prompt PROIBE varrer `blacksmith/` atras do "mais recente", entao o clique
precisa colar os dois paths junto do prompt. Faltando qualquer um, o clique e
no-op com toast (Zero Silencio), nunca um prompt que encalha na FASE 0.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

PLAN_VS_LOOP_MD = "plan-vs-loop-coverage.md"


def _new_window(qtbot):
    from workflow_app.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    return win


def _entry_index(win, basename: str) -> int:
    for idx, entry in enumerate(win._prompt_entries):
        if Path(entry.get("path", "")).name == basename:
            return idx
    raise AssertionError(f"entry de prompt {basename} nao encontrada")


def _make_loop(tmp_path: Path) -> SimpleNamespace:
    loop_root = tmp_path / "blacksmith" / "loop-archives" / "07-27-cobertura"
    loop_root.mkdir(parents=True)
    (loop_root / "PROGRESS.md").write_text("# Progress\n", encoding="utf-8")
    raw = {
        "name": "07-27-cobertura",
        "kind": "daily-loop",
        "basic_flow": {"workspace_root": str(tmp_path / "ws")},
        "daily_loop": {"slug": "07-27-cobertura", "buckets": []},
    }
    config_path = loop_root / "_LOOP-CONFIG.json"
    config_path.write_text(json.dumps(raw), encoding="utf-8")
    return SimpleNamespace(
        config_path=str(config_path), raw=raw, project_name="07-27-cobertura"
    )


@pytest.fixture
def captured(qtbot, monkeypatch, tmp_path):
    """Janela com `_publish_to_terminal` e toasts interceptados."""
    from workflow_app.config.app_state import app_state

    app_state.clear_all()
    win = _new_window(qtbot)
    published: list[str] = []
    toasts: list[tuple[str, str]] = []
    monkeypatch.setattr(
        win, "_publish_to_terminal", lambda msg, *a, **kw: published.append(msg)
    )

    from workflow_app.signal_bus import signal_bus

    def on_toast(message: str, level: str) -> None:
        toasts.append((message, level))

    signal_bus.toast_requested.connect(on_toast)
    try:
        yield SimpleNamespace(
            win=win, published=published, toasts=toasts, tmp_path=tmp_path
        )
    finally:
        signal_bus.toast_requested.disconnect(on_toast)
        app_state.clear_all()


def test_context_carries_both_ui_artifacts_in_one_line(captured):
    from workflow_app.config.app_state import app_state

    loop_cfg = _make_loop(captured.tmp_path)
    app_state.set_loop_config(loop_cfg)  # type: ignore[arg-type]
    plan_md = captured.tmp_path / "plano.md"
    plan_md.write_text("# Plano\n", encoding="utf-8")
    captured.win._brainstorm_md_path = str(plan_md)

    captured.win._on_prompt_btn_clicked(_entry_index(captured.win, PLAN_VS_LOOP_MD))

    assert len(captured.published) == 1
    msg = captured.published[0]
    assert f"metrics_loop_pill_json={loop_cfg.config_path}" in msg
    assert f"brainstorm_md_picker_row={plan_md}" in msg
    # O path do proprio .md do prompt continua na mensagem (comportamento base).
    assert PLAN_VS_LOOP_MD in msg
    # Bracketed paste nao garante payload multi-linha em shell nu.
    assert "\n" not in msg
    # Confirmacao explicita do que foi capturado (Zero Silencio).
    assert any(
        level == "info" and "07-27-cobertura" in message and "plano.md" in message
        for message, level in captured.toasts
    )


def test_context_omits_values_derivable_from_the_json(captured):
    """Nada de `loop_dir`/`loop_slug`/`progress_md` no payload.

    Sao derivacao pura do path do JSON (FASE 0.1 do `.md` ja prescreve como
    deriva-los). Duplicar dado em duas fontes e exatamente a classe de defeito
    que travou o botao Loop.
    """
    from workflow_app.config.app_state import app_state

    app_state.set_loop_config(_make_loop(captured.tmp_path))  # type: ignore[arg-type]
    plan_md = captured.tmp_path / "plano.md"
    plan_md.write_text("# Plano\n", encoding="utf-8")
    captured.win._brainstorm_md_path = str(plan_md)

    captured.win._on_prompt_btn_clicked(_entry_index(captured.win, PLAN_VS_LOOP_MD))

    msg = captured.published[0]
    assert "loop_dir=" not in msg
    assert "loop_slug=" not in msg
    assert "progress_md=" not in msg


def test_stale_attachment_pointing_nowhere_is_not_pasted(captured):
    """Anexo carregado mas apagado do disco entre o load e o clique."""
    from workflow_app.config.app_state import app_state

    loop_cfg = _make_loop(captured.tmp_path)
    app_state.set_loop_config(loop_cfg)  # type: ignore[arg-type]
    plan_md = captured.tmp_path / "plano.md"
    plan_md.write_text("# Plano\n", encoding="utf-8")
    captured.win._brainstorm_md_path = str(plan_md)
    Path(loop_cfg.config_path).unlink()

    captured.win._on_prompt_btn_clicked(_entry_index(captured.win, PLAN_VS_LOOP_MD))

    assert captured.published == []
    assert any(level == "warning" for _, level in captured.toasts)


def test_both_missing_asks_for_both_in_one_toast(captured):
    captured.win._brainstorm_md_path = None

    captured.win._on_prompt_btn_clicked(_entry_index(captured.win, PLAN_VS_LOOP_MD))

    assert captured.published == []
    assert len(captured.toasts) == 1
    message, level = captured.toasts[0]
    assert level == "warning"
    assert "Loop" in message and "Selecionar .md" in message


def test_without_loop_attachment_nothing_is_pasted(captured):
    plan_md = captured.tmp_path / "plano.md"
    plan_md.write_text("# Plano\n", encoding="utf-8")
    captured.win._brainstorm_md_path = str(plan_md)

    captured.win._on_prompt_btn_clicked(_entry_index(captured.win, PLAN_VS_LOOP_MD))

    assert captured.published == []
    assert any("metrics-loop-pill" in message for message, _ in captured.toasts)


def test_without_brainstorm_md_nothing_is_pasted(captured):
    from workflow_app.config.app_state import app_state

    app_state.set_loop_config(_make_loop(captured.tmp_path))  # type: ignore[arg-type]
    captured.win._brainstorm_md_path = None

    captured.win._on_prompt_btn_clicked(_entry_index(captured.win, PLAN_VS_LOOP_MD))

    assert captured.published == []
    assert any(
        "brainstorm-md-picker-row" in message for message, _ in captured.toasts
    )


def test_other_prompts_are_not_enriched(captured):
    idx = _entry_index(captured.win, "turn-green.md")

    captured.win._on_prompt_btn_clicked(idx)

    assert len(captured.published) == 1
    assert "CONTEXTO RUNTIME" not in captured.published[0]
