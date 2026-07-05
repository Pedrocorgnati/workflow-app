"""Regression: queue-btn-loop list must respect anti-redundancy.

`ai-forge/rules/workflow-app-command-lists.md` secao 3.1 (REGRA INVIOLAVEL):
todas as fases do loop rodam em opus/high (GROUP_MAP["loop"]), entao /model e
/effort so podem ser emitidos UMA vez (no primeiro grupo, secao 3.4). Os grupos
seguintes recebem apenas /clear.

Bug historico: `_on_loop_command_ready` chamava `_build_prep_specs("loop", ...)`
antes de CADA subcomando, re-emitindo /model opus /effort high redundante em
todas as 6-8 fases.
"""

from __future__ import annotations

from unittest.mock import patch

from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
from workflow_app.signal_bus import signal_bus


def _capture_loop_specs(widget, command_line):
    captured = []

    def _handler(specs):
        captured.append(specs)

    signal_bus.pipeline_ready.connect(_handler)
    try:
        with patch.object(widget, "_canonical_loop_slug", return_value="06-01-x"), \
             patch.object(widget, "_existing_loop_slug_from_path", return_value=None):
            widget._on_loop_command_ready(command_line)
    finally:
        signal_bus.pipeline_ready.disconnect(_handler)
    assert captured, "pipeline_ready nao emitiu specs"
    return [s.name for s in captured[-1]]


def _assert_anti_redundant(names):
    # secao 3.4: primeiro grupo recebe /clear /model /effort completo.
    assert names[0] == "/clear"
    assert names[1] == "/model opus"
    assert names[2] == "/effort high"
    # secao 3.1: /model e /effort emitidos exatamente UMA vez (sem queda de
    # model/effort no loop, logo nenhum reemit).
    model_count = sum(1 for n in names if n.startswith("/model "))
    effort_count = sum(1 for n in names if n.startswith("/effort "))
    assert model_count == 1, f"/model redundante: {model_count}x em {names}"
    assert effort_count == 1, f"/effort redundante: {effort_count}x em {names}"
    # Cada fase real ainda e precedida por /clear (default entre fases independentes).
    reals = [n for n in names if not n.startswith(("/clear", "/model ", "/effort "))]
    clears = sum(1 for n in names if n == "/clear")
    assert clears == len(reals), (
        f"esperado 1 /clear por fase ({len(reals)} fases), got {clears}: {names}"
    )


def test_loop_both_no_redundant_model_effort(qapp):
    widget = CommandQueueWidget()
    names = _capture_loop_specs(widget, "/loop --both tasks.md")
    _assert_anti_redundant(names)
    # --both = 9 fases
    reals = [n for n in names if not n.startswith(("/clear", "/model ", "/effort "))]
    assert len(reals) == 9, names
    widget.deleteLater()


def test_loop_task_no_redundant_model_effort(qapp):
    widget = CommandQueueWidget()
    names = _capture_loop_specs(widget, "/loop --task tasks.md")
    _assert_anti_redundant(names)
    reals = [n for n in names if not n.startswith(("/clear", "/model ", "/effort "))]
    assert len(reals) == 7, names
    widget.deleteLater()


def test_loop_cmd_no_redundant_model_effort(qapp):
    widget = CommandQueueWidget()
    names = _capture_loop_specs(widget, "/loop --cmd tasks.md")
    _assert_anti_redundant(names)
    widget.deleteLater()


def test_legacy_to_dcp_anti_redundant_via_inject_clears():
    """queue-btn-legacy-to-dcp agora delega a _inject_clears (5 comandos reais,
    4 em sonnet/standard + 1 em sonnet/high). Garante: /clear /model sonnet
    /effort <std> so na 1a; /clear-only nas 2 a 4; /effort reemitido no salto
    para high mas /model sonnet SUPRIMIDO (inalterado). secao 3.1 + 3.4 + 4.
    """
    from workflow_app.domain import CommandSpec, ModelName, InteractionType, EffortLevel
    from workflow_app.templates.quick_templates import _inject_clears

    std = EffortLevel.STANDARD
    reals = [
        CommandSpec(name="/legacy:detect p.json", model=ModelName.SONNET,
                    effort=std, interaction_type=InteractionType.AUTO, position=1),
        CommandSpec(name="/delivery:init --if-missing p.json", model=ModelName.SONNET,
                    effort=std, interaction_type=InteractionType.AUTO, position=2),
        CommandSpec(name="/legacy:modules-from-features p.json", model=ModelName.SONNET,
                    effort=std, interaction_type=InteractionType.AUTO, position=3),
        CommandSpec(name="/dcp:meta-completeness --all --auto-fix-p0 p.json",
                    model=ModelName.SONNET, effort=std,
                    interaction_type=InteractionType.AUTO, position=4),
        CommandSpec(name="/legacy:enqueue-all-modules p.json", model=ModelName.SONNET,
                    effort=EffortLevel.HIGH, interaction_type=InteractionType.AUTO,
                    position=5),
    ]
    names = [s.name for s in _inject_clears(reals)]
    # /model emitido exatamente 1x (sonnet nunca muda); /effort 2x (std + salto high).
    assert sum(1 for n in names if n.startswith("/model ")) == 1, names
    assert sum(1 for n in names if n.startswith("/effort ")) == 2, names
    # Primeiro comando real precedido por /clear /model sonnet /effort <std>.
    assert names[0] == "/clear"
    assert names[1] == "/model sonnet"
    assert names[2].startswith("/effort ")
    assert names[3] == "/legacy:detect p.json"
    # 5 comandos reais, cada um precedido por /clear (5 /clear no total).
    reals_out = [n for n in names if not n.startswith(("/clear", "/model ", "/effort "))]
    assert len(reals_out) == 5
    assert sum(1 for n in names if n == "/clear") == 5
