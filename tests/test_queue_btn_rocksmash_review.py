"""Regression tests for o botao `queue-btn-rocksmash-review`.

Cobre a Task 4 do loop `05-21-rocksmash-review-base`
(`task-004-botao-workflow-app.md`): o botao `rocksmash review` na aba
`queue-tab-auxiliar` injeta um template estatico de 12 comandos a partir
do JSON do projeto ativo (`metrics-project-pill`).

Template canonico (Secao 4 da task-004):

    /clear
    /model opus
    /effort high
    /agents:troop-review {json}
    /clear  /agents:troop-review {json}   (x4)

Sao 3 comandos de prep + 5 invocacoes single-pass de
`/agents:troop-review` intercaladas por 4 `/clear` proprios = 12 itens.
`/model` e `/effort` aparecem uma unica vez (politica anti-redundancia
de `ai-forge/rules/workflow-app-command-lists.md` secao 3).

Cenarios cobertos:

  * test_group_map_has_rocksmash_review_opus_high
    O GROUP_MAP real declara `rocksmash_review` = Opus / HIGH (sem
    hardcode por botao, conforme WORKFLOW-APP-RULES.md).

  * test_build_prep_specs_for_rocksmash_review
    `_build_prep_specs("rocksmash_review")` produz os 3 CommandSpecs de
    prep com nomes e posicoes canonicos.

  * test_template_has_exactly_twelve_commands
    O template completo tem exatamente 12 itens.

  * test_template_command_breakdown
    Distribuicao: 5x `/agents:troop-review`, 5x `/clear`, 1x `/model`,
    1x `/effort` — `/model`/`/effort` nunca reemitidos.

  * test_template_json_path_propagated
    O `{json}` da metrics-project-pill aparece em cada uma das 5
    invocacoes de `/agents:troop-review`.

  * test_button_registered_with_canonical_testid
    Smoke textual: a tupla do botao esta registrada com o testid
    `queue-btn-rocksmash-review` e o handler `_on_rocksmash_review_clicked`.

O Qt-widget real e exercitado pelos suites de integration; aqui o
template e testado via replica pura (mesmo padrao do sibling
`test_queue_btn_rocksmash_project_json.py`).
"""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from workflow_app.command_queue.command_queue_widget import (  # noqa: E402
    GROUP_MAP,
    _build_prep_specs,
)
from workflow_app.domain import EffortLevel, ModelName  # noqa: E402

WIDGET_SOURCE = (
    Path(__file__).resolve().parents[1]
    / "src"
    / "workflow_app"
    / "command_queue"
    / "command_queue_widget.py"
)


def _build_rocksmash_review_command_names(json_path: str) -> list[str]:
    """Replica pura da sequencia de nomes montada por `_on_rocksmash_review_clicked`.

    Espelha o builder do handler (linhas ~4593-4620): 3 comandos de prep,
    depois 5 rodadas onde a 1a herda o `/clear` do prep e as demais 4
    recebem `/clear` proprio. `/model`/`/effort` nunca sao reemitidos.
    """
    names = ["/clear", "/model opus", "/effort high"]
    for round_idx in range(5):
        if round_idx > 0:
            names.append("/clear")
        names.append(f"/agents:troop-review {json_path}")
    return names


def test_group_map_has_rocksmash_review_opus_high() -> None:
    """GROUP_MAP['rocksmash_review'] deve ser Opus / HIGH (sem hardcode por botao)."""
    assert "rocksmash_review" in GROUP_MAP, (
        "rocksmash_review precisa existir no GROUP_MAP (WORKFLOW-APP-RULES.md)"
    )
    cfg = GROUP_MAP["rocksmash_review"]
    assert cfg["model"] is ModelName.OPUS
    assert cfg["effort"] is EffortLevel.HIGH


def test_build_prep_specs_for_rocksmash_review() -> None:
    """O bloco prep e exatamente /clear, /model opus, /effort high (posicoes 1-3)."""
    specs = _build_prep_specs("rocksmash_review")
    assert [s.name for s in specs] == ["/clear", "/model opus", "/effort high"]
    assert [s.position for s in specs] == [1, 2, 3]
    # Todos os specs de prep herdam o model do grupo (Opus).
    assert all(s.model is ModelName.OPUS for s in specs)


def test_template_has_exactly_twelve_commands() -> None:
    """O template estatico completo tem exatamente 12 itens (Secao 4 da task-004)."""
    names = _build_rocksmash_review_command_names(".claude/projects/demo.json")
    assert len(names) == 12, (
        f"Template deve ter 12 itens (3 prep + 5 troop-review + 4 clear); got {len(names)}"
    )


def test_template_command_breakdown() -> None:
    """Distribuicao canonica: 5 troop-review, 5 clear, 1 model, 1 effort."""
    names = _build_rocksmash_review_command_names(".claude/projects/demo.json")
    troop = [n for n in names if n.startswith("/agents:troop-review ")]
    clears = [n for n in names if n == "/clear"]
    models = [n for n in names if n.startswith("/model ")]
    efforts = [n for n in names if n.startswith("/effort ")]

    assert len(troop) == 5, "5 invocacoes single-pass de /agents:troop-review"
    assert len(clears) == 5, "1 /clear do prep + 4 /clear intercalados = 5"
    assert len(models) == 1, "/model emitido uma unica vez (anti-redundancia)"
    assert len(efforts) == 1, "/effort emitido uma unica vez (anti-redundancia)"
    assert models == ["/model opus"]
    assert efforts == ["/effort high"]
    # Os 3 primeiros itens sao o bloco de prep, nesta ordem.
    assert names[:3] == ["/clear", "/model opus", "/effort high"]


def test_template_json_path_propagated() -> None:
    """O {json} da metrics-project-pill aparece nas 5 invocacoes de troop-review."""
    json_path = "/home/user/.claude/projects/meu-projeto.json"
    names = _build_rocksmash_review_command_names(json_path)
    troop = [n for n in names if n.startswith("/agents:troop-review ")]
    assert len(troop) == 5
    assert all(n == f"/agents:troop-review {json_path}" for n in troop), (
        "cada /agents:troop-review deve carregar o json_path da pill"
    )


def test_button_registered_with_canonical_testid() -> None:
    """Smoke textual: botao registrado com testid e handler canonicos."""
    source = WIDGET_SOURCE.read_text(encoding="utf-8")
    assert '"queue-btn-rocksmash-review"' in source, (
        "botao deve declarar o testid queue-btn-rocksmash-review"
    )
    assert "def _on_rocksmash_review_clicked" in source, (
        "handler _on_rocksmash_review_clicked deve existir"
    )
    assert '"rocksmash review"' in source, (
        "label do botao deve ser 'rocksmash review'"
    )
