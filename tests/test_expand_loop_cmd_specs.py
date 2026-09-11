"""Task 35: cobertura dedicada de `_expand_loop_cmd_specs`.

Nenhum teste da arvore citava este expander. A decisao de MANTER `--cmd`
exige o teste do caminho antigo (I7): batch com JSON, que `--cmd-single`
nao cobre.
"""

from __future__ import annotations

import pytest

from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
from workflow_app.domain import EffortLevel, ModelName


@pytest.fixture()
def widget(qapp, qtbot) -> CommandQueueWidget:
    w = CommandQueueWidget()
    qtbot.addWidget(w)
    return w


def _raw_cmd_batch() -> dict:
    """JSON batch com dois items (create + update) — o que cmd-single nao faz."""
    return {
        "name": "batch-cmd",
        "mode": "cmd",
        "iteration_template": {
            "pre": ["/clear", "/model opus", "/effort high"],
            "exec_create": ["/cmd:create {cmd_target_slash}"],
            "exec_update": ["/cmd:update {cmd_target_slash}"],
            "kimi_eligible_wrapper": ["/cmd:kimi-pair-analyse {cmd_target_slash}"],
        },
        "items": [
            {
                "id": "001",
                "task_path": "tasks/items/task-001.md",
                "cmd_action": "create",
                "cmd_target_slash": "/qa:trace",
                "kimi_eligible": False,
            },
            {
                "id": "002",
                "task_path": "tasks/items/task-002.md",
                "cmd_action": "update",
                "cmd_target_slash": "/qa:report",
                "kimi_eligible": True,
            },
        ],
        "finalization": {"commands": ["/loop:review --name {name}"]},
    }


def test_batch_create_e_update_no_mesmo_json(widget: CommandQueueWidget) -> None:
    specs = widget._expand_loop_cmd_specs(_raw_cmd_batch(), "/tmp/cfg.json")
    nomes = [s.name for s in specs]
    assert "/cmd:create /qa:trace" in nomes
    assert "/cmd:update /qa:report" in nomes
    assert nomes.count("/clear") >= 2
    assert "/loop:review --name batch-cmd" in nomes


def test_cmd_single_nao_substitui_este_batch(widget: CommandQueueWidget) -> None:
    """`--cmd-single` expande UM alvo; este expander materializa N items do JSON."""
    specs = widget._expand_loop_cmd_specs(_raw_cmd_batch(), "/tmp/cfg.json")
    alvos = [s.name for s in specs if s.name.startswith("/cmd:")]
    assert len(alvos) == 2


def test_kimi_wrapper_so_quando_checkbox_ligado(widget: CommandQueueWidget) -> None:
    widget._use_kimi_chk.setChecked(False)
    specs = widget._expand_loop_cmd_specs(_raw_cmd_batch(), "/tmp/cfg.json")
    assert all("kimi-pair" not in s.name for s in specs)

    widget._use_kimi_chk.setChecked(True)
    specs = widget._expand_loop_cmd_specs(_raw_cmd_batch(), "/tmp/cfg.json")
    wrappers = [s.name for s in specs if "kimi-pair-analyse" in s.name]
    assert wrappers, "item kimi_eligible=true deve emitir o wrapper"
    assert len(wrappers) == 1
    assert all("/cmd:create" not in w for w in wrappers)


def test_model_effort_das_diretivas(widget: CommandQueueWidget) -> None:
    specs = widget._expand_loop_cmd_specs(_raw_cmd_batch(), "/tmp/cfg.json")
    create = next(s for s in specs if s.name.startswith("/cmd:create"))
    assert create.model is ModelName.OPUS
    assert create.effort is EffortLevel.HIGH


def test_expand_loop_json_specs_roteia_mode_cmd(widget: CommandQueueWidget) -> None:
    specs = widget._expand_loop_json_specs(_raw_cmd_batch(), "/tmp/cfg.json")
    assert any(s.name.startswith("/cmd:create") for s in specs)
    assert any(s.name.startswith("/cmd:update") for s in specs)
