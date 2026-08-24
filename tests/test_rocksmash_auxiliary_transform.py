"""Rocksmash e transformacao auxiliar sobre config normal (Task 18 do estudo 08-24).

O que este arquivo congela:

1. **Nenhum documento promete `mode == "rocksmash"` produzido pela preparacao.**
   `/loop --rocksmash` nao gera JSON, logo nunca escreve o campo. Um gate
   condicionado a esse modo nunca dispara no caminho que o operador clica.

2. **A validacao autoritativa e do shape da fila expandida.** Ela roda sempre,
   independente de `mode`, porque a fila e o que de fato executa.

3. **Tier declarado igual em rule e expander.** Framing `opus` + `standard`;
   iteracao herda o sizing do proprio item/bucket. Rocksmash nao carrega tier
   proprio por iteracao — isso sobrescreveria em silencio o sizing por item.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from workflow_app.command_queue.loop_rocksmash_expander import (
    _FRAMING_EFFORT,
    _FRAMING_MODEL,
    _assert_expanded_queue_shape,
    build_loop_rocksmash_specs,
)
from workflow_app.daily_loop.loader import DailyLoopConfigError
from workflow_app.domain import CommandSpec, EffortLevel, InteractionType, ModelName


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".claude" / "commands" / "loop.md").is_file():
            return parent
    raise RuntimeError("repo root nao encontrado")


def _config(
    items: list[dict],
    *,
    model: str = "opus",
    effort: str = "high",
    mode: str | None = "task",
    legacy_two_step: bool = False,
) -> dict:
    daily: dict = {
        "buckets": [
            {"id": f"T-{model}-{effort}", "model": model, "effort": effort, "items": items}
        ]
    }
    if legacy_two_step:
        daily["rocksmash_legacy_two_step"] = True
    cfg: dict = {"kind": "daily-loop", "daily_loop": daily}
    if mode is not None:
        cfg["mode"] = mode
    return cfg


def _loop(tmp_path: Path, n: int = 2) -> tuple[Path, list[dict]]:
    items_dir = tmp_path / "tasks" / "items"
    items_dir.mkdir(parents=True)
    items = []
    for i in range(1, n + 1):
        rel = f"tasks/items/task-{i:03d}-x.md"
        (tmp_path / rel).write_text(f"# task {i}\n", encoding="utf-8")
        items.append({"id": f"{i:03d}", "kind": "iteration", "task_path": rel, "commands": []})
    return tmp_path, items


def _tokens(specs: list[CommandSpec]) -> list[str]:
    return [
        s.name.split(" ", 1)[0]
        for s in specs
        if s.name != "/clear" and not s.name.startswith(("/model ", "/effort "))
    ]


# --------------------------------------------------------------------------
# 1. Config normal (sem mode=rocksmash) e o caminho executavel
# --------------------------------------------------------------------------


@pytest.mark.parametrize("mode", ["task", "cmd", "both", None])
def test_expander_opera_sobre_config_normal(tmp_path: Path, mode: str | None) -> None:
    """O botao expande config normal. `mode` nao seleciona a lane."""
    root, items = _loop(tmp_path, n=2)
    specs = build_loop_rocksmash_specs(_config(items, mode=mode), str(root))
    assert _tokens(specs) == [
        "/loop-rocksmash:prepare",
        "/loop-rocksmash:do",
        "/loop-rocksmash:review-done",
        "/loop-rocksmash:compare",
        "/loop-rocksmash:integrate",
        "/loop-rocksmash:do",
        "/loop-rocksmash:review-done",
        "/loop-rocksmash:compare",
        "/loop-rocksmash:integrate",
        "/loop-rocksmash:rename",
    ]


def test_gate_da_fila_roda_mesmo_sem_mode_rocksmash(tmp_path: Path) -> None:
    """A fila expandida e validada sempre — nao so quando mode=='rocksmash'.

    Sem `mode`, `assert_rocksmash_iteration_shape` nao dispara; se o gate da
    fila tambem nao rodasse, um loop normal expandiria sem verificacao nenhuma.
    """
    root, items = _loop(tmp_path, n=1)
    cfg = _config(items, mode=None)
    specs = build_loop_rocksmash_specs(cfg, str(root))
    # a mesma funcao que build_loop_rocksmash_specs chama no fim, agora com a
    # fila mutilada: um bloco de iteracao a menos do que os itens declarados.
    with pytest.raises(DailyLoopConfigError) as exc:
        _assert_expanded_queue_shape(
            [s for s in specs if not s.name.startswith("/loop-rocksmash:compare")],
            iteration_ids=["001"],
            legacy_two_step=False,
        )
    msg = str(exc.value)
    assert "esperado" in msg and "observado" in msg
    assert "/loop-rocksmash:compare" in msg


def test_gate_da_fila_valida_bloco_legacy_de_dois(tmp_path: Path) -> None:
    root, items = _loop(tmp_path, n=1)
    specs = build_loop_rocksmash_specs(_config(items, legacy_two_step=True), str(root))
    assert _tokens(specs) == [
        "/loop-rocksmash:prepare",
        "/loop-rocksmash:do",
        "/loop-rocksmash:review-done",
        "/loop-rocksmash:rename",
    ]


def test_gate_rejeita_ordem_trocada() -> None:
    """Ordem importa: o bloco canonico nao e um conjunto."""

    def spec(name: str) -> CommandSpec:
        return CommandSpec(
            name=name,
            model=ModelName.OPUS,
            interaction_type=InteractionType.AUTO,
            config_path="",
            position=0,
        )

    fila = [
        spec("/loop-rocksmash:prepare /x/_LOOP-CONFIG.json"),
        spec("/loop-rocksmash:review-done /x/t.md"),  # trocado com :do
        spec("/loop-rocksmash:do /x/t.md"),
        spec("/loop-rocksmash:compare /x/t.md"),
        spec("/loop-rocksmash:integrate /x/t.md"),
        spec("/loop-rocksmash:rename /x/_LOOP-CONFIG.json"),
    ]
    with pytest.raises(DailyLoopConfigError):
        _assert_expanded_queue_shape(fila, iteration_ids=["001"], legacy_two_step=False)


# --------------------------------------------------------------------------
# 2. Politica de tier: rule e expander declaram a mesma coisa
# --------------------------------------------------------------------------


def test_framing_e_opus_standard() -> None:
    assert _FRAMING_MODEL is ModelName.OPUS
    assert _FRAMING_EFFORT is EffortLevel.STANDARD


def test_iteracao_herda_sizing_do_bucket_e_nao_um_tier_proprio(tmp_path: Path) -> None:
    """Bucket sonnet/medium => iteracao sonnet/medium, nao opus/high."""
    root, items = _loop(tmp_path, n=1)
    specs = build_loop_rocksmash_specs(
        _config(items, model="sonnet", effort="medium"), str(root)
    )
    iteracao = [s for s in specs if s.name.startswith("/loop-rocksmash:do")]
    assert len(iteracao) == 1
    assert iteracao[0].model is ModelName.SONNET
    assert iteracao[0].effort is EffortLevel.STANDARD

    framing = [s for s in specs if s.name.startswith("/loop-rocksmash:prepare")]
    assert framing[0].model is ModelName.OPUS


def test_rules_declara_a_mesma_politica_de_tier() -> None:
    txt = (_repo_root() / "ai-forge" / "rules" / "rocksmash.md").read_text(encoding="utf-8")
    assert "framing" in txt.lower()
    assert "`opus` + `standard`" in txt, (
        "rocksmash.md deve declarar o framing opus+standard igual ao expander "
        "(_FRAMING_MODEL/_FRAMING_EFFORT)"
    )
    assert "_bucket_to_model_effort" in txt, (
        "rocksmash.md deve declarar que a iteracao herda o sizing do item/bucket"
    )
    assert "Rocksmash sobrescreve para `opus` + `high` em iteracoes substantivas." not in txt, (
        "afirmacao antiga de tier fixo por iteracao voltou; ela descreve o bucket "
        "T-opus-high, nao o contrato"
    )


# --------------------------------------------------------------------------
# 3. Nenhum documento promete mode=rocksmash produzido pela preparacao
# --------------------------------------------------------------------------


def test_contract_nao_lista_loop_rocksmash_como_producer_de_mode() -> None:
    txt = (
        _repo_root()
        / "ai-forge/workflow-app/src/workflow_app/daily_loop/CONTRACT.md"
    ).read_text(encoding="utf-8")
    assert "| `\"rocksmash\"`     | `/loop --rocksmash`" not in txt, (
        "CONTRACT.md voltou a listar /loop --rocksmash como origem de mode=rocksmash; "
        "a preparacao nao gera JSON"
    )
    assert "transformacao auxiliar" in txt


def test_loop_md_declara_que_nao_escreve_mode_rocksmash() -> None:
    txt = (_repo_root() / ".claude" / "commands" / "loop.md").read_text(encoding="utf-8")
    assert "NAO escreve `mode: rocksmash`" in txt


def test_nenhum_config_do_corpus_usa_mode_rocksmash() -> None:
    """A premissa do estudo: nenhum config auditado carrega o modo.

    Se um config passar a carregar, este teste falha e a decisao de Task 18
    precisa ser reavaliada com evidencia, nao revertida por impressao.
    """
    archives = _repo_root() / "blacksmith" / "loop-archives"
    if not archives.is_dir():
        pytest.skip("corpus ausente neste checkout")
    ofensores = []
    for cfg in archives.rglob("_LOOP-CONFIG.json"):
        try:
            data = json.loads(cfg.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict) and data.get("mode") == "rocksmash":
            ofensores.append(str(cfg.relative_to(archives)))
    assert ofensores == [], (
        "config com mode=rocksmash encontrado no corpus; a premissa da Task 18 "
        f"(nenhum config usa o modo) precisa ser reavaliada: {ofensores}"
    )
