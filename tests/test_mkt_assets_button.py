"""Tests for queue-btn-mkt-assets wiring (Item 010 do loop
06-18-marketing-pipeline-30d-instagram-feed).

Cobre os 4+1 pontos do wiring no command_queue_widget:
  (1) GROUP_MAP["mkt_assets"] = sonnet/standard;
  (2) DoublePhaseButton queue-btn-mkt-assets no widget tree;
  (3) registro em loops_content (aba queue-tab-loops);
  (4) handler _on_mkt_assets_command_ready expande a cadeia (forma secao 8,
      sem centralizador) na ordem scan->research->plan->generate->review->
      workflow-app, com anti-redundancia (triplet so na 1a fase, /clear entre
      as demais);
  (5) prefixo /mkt-assets declarado no roteador _on_unified_command_ready.

Gemeo das verificacoes de test_unified_entrypoint.py + test_loop_anti_redundancy.py
para a lane Kimi/loop.
"""

from __future__ import annotations

from unittest.mock import patch

from workflow_app.command_queue.command_queue_widget import (
    GROUP_MAP,
    CommandQueueWidget,
)
from workflow_app.command_queue.double_phase_button import DoublePhaseButton
from workflow_app.domain import EffortLevel, ModelName
from workflow_app.signal_bus import signal_bus


_PROJECT = ".claude/projects/acme.json"
_SLUG = "acme"  # Path(_PROJECT).stem


def _expected_reals(project: str = _PROJECT, slug: str = _SLUG) -> list[str]:
    """Constroi a lista canonica de 66 reais: 4 base + 30 pares iteraction + 2 fechadoras."""
    top = [
        f"/mkt-assets:scan {project}",
        f"/mkt-assets:research {project}",
        f"/mkt-assets:plan {project}",
        f"/mkt-assets:generate {project}",
    ]
    pairs: list[str] = []
    for _i in range(1, 31):
        _pid = f"post-{_i:02d}"
        pairs.append(
            f"/mkt-assets:iteraction:generate-post --slug {slug} --post {_pid} --config {project}"
        )
        pairs.append(
            f"/mkt-assets:iteraction:review-post --slug {slug} --post {_pid} --config {project}"
        )
    closing = [
        f"/mkt-assets:review {project}",
        f"/mkt-assets:workflow-app {project}",
    ]
    return top + pairs + closing


def _capture_mkt_assets_specs(widget, command_line):
    captured = []

    def _handler(specs):
        captured.append(specs)

    signal_bus.pipeline_ready.connect(_handler)
    try:
        widget._on_mkt_assets_command_ready(command_line)
    finally:
        signal_bus.pipeline_ready.disconnect(_handler)
    assert captured, "pipeline_ready nao emitiu specs"
    return [s.name for s in captured[-1]]


# ---------------------------------------------------------------------------
# (1) GROUP_MAP
# ---------------------------------------------------------------------------


def test_group_map_mkt_assets_is_sonnet_standard():
    cfg = GROUP_MAP["mkt_assets"]
    assert cfg["model"] is ModelName.SONNET
    assert cfg["effort"] is EffortLevel.STANDARD


# ---------------------------------------------------------------------------
# (2)/(3) Button presence in the widget tree (loops_content / queue-tab-loops)
# ---------------------------------------------------------------------------


def test_mkt_assets_button_is_double_phase_button(qapp):
    widget = CommandQueueWidget()
    header = widget.header_widget
    btn = None
    for child in header.findChildren(DoublePhaseButton):
        if child.property("testid") == "queue-btn-mkt-assets":
            btn = child
            break
    assert btn is not None, "queue-btn-mkt-assets DoublePhaseButton nao encontrado"
    assert isinstance(btn, DoublePhaseButton)
    widget.deleteLater()


# ---------------------------------------------------------------------------
# (5) Router dispatch
# ---------------------------------------------------------------------------


def test_unified_handler_dispatches_mkt_assets(qapp):
    widget = CommandQueueWidget()
    with patch.object(widget, "_on_mkt_assets_command_ready") as mock_mkt:
        widget._on_unified_command_ready(f"/mkt-assets {_PROJECT}")
        mock_mkt.assert_called_once_with(f"/mkt-assets {_PROJECT}")
    widget.deleteLater()


# ---------------------------------------------------------------------------
# (4) Expansion: canonical chain + anti-redundancy + no centralizer
# ---------------------------------------------------------------------------


def test_mkt_assets_expands_canonical_chain_positional(qapp):
    widget = CommandQueueWidget()
    names = _capture_mkt_assets_specs(widget, f"/mkt-assets {_PROJECT}")

    reals = [
        n for n in names
        if not n.startswith(("/clear", "/model ", "/effort "))
    ]
    # 4 fases base + 30 pares iteraction (60) + 2 fechadoras = 66 reais.
    expected = _expected_reals()
    assert reals == expected, f"reals={reals[:8]}... (total {len(reals)})"
    widget.deleteLater()


def test_mkt_assets_accepts_project_flag_form(qapp):
    # O dialog emite `--project <path>`; o handler deve extrair o positional.
    widget = CommandQueueWidget()
    names = _capture_mkt_assets_specs(
        widget, f"/mkt-assets --project {_PROJECT}"
    )
    reals = [
        n for n in names
        if not n.startswith(("/clear", "/model ", "/effort "))
    ]
    expected = _expected_reals()
    assert reals == expected, f"reals={reals[:8]}... (total {len(reals)})"
    widget.deleteLater()


def test_mkt_assets_no_centralizer_entry(qapp):
    widget = CommandQueueWidget()
    names = _capture_mkt_assets_specs(widget, f"/mkt-assets {_PROJECT}")
    # Forma secao 8: nenhuma entrada centralizadora `/mkt-assets <subindicador>`
    # (o centralizador nunca entra na fila — so os subcomandos `/mkt-assets:*`).
    centralizers = [
        n for n in names
        if n.startswith("/mkt-assets ") and not n.startswith("/mkt-assets:")
    ]
    assert centralizers == [], f"centralizador na fila: {centralizers}"
    widget.deleteLater()


def test_mkt_assets_anti_redundancy(qapp):
    widget = CommandQueueWidget()
    names = _capture_mkt_assets_specs(widget, f"/mkt-assets {_PROJECT}")

    # secao 3.4: primeiro grupo recebe /clear /model sonnet /effort medium
    # (EffortLevel.STANDARD.value == "medium" — GROUP_MAP["mkt_assets"] =
    # sonnet/standard, espelhando a lane kimi_loop sonnet/medium).
    assert names[0] == "/clear"
    assert names[1] == "/model sonnet"
    assert names[2] == "/effort medium"
    # secao 3.1: /model e /effort emitidos exatamente UMA vez (grupo unico,
    # model/effort nunca mudam ao longo da cadeia).
    assert sum(1 for n in names if n.startswith("/model ")) == 1, names
    assert sum(1 for n in names if n.startswith("/effort ")) == 1, names
    # Cada fase real precedida por /clear (1 /clear por subcomando).
    # 4 base + 60 iteraction + 2 fechadoras = 66 reais; 66 /clears (1 por real).
    reals = [
        n for n in names
        if not n.startswith(("/clear", "/model ", "/effort "))
    ]
    assert len(reals) == 66, f"esperado 66 reais, obtido {len(reals)}"
    assert sum(1 for n in names if n == "/clear") == 66, names
    widget.deleteLater()


def test_mkt_assets_missing_project_falls_back(qapp):
    widget = CommandQueueWidget()
    with patch.object(widget, "add_command") as mock_add:
        widget._on_mkt_assets_command_ready("/mkt-assets")
        mock_add.assert_called_once()
    widget.deleteLater()
