"""Piso e ancora do sizing do loop (Task 10 do loop 08-24-analise-fluxo-loop).

Cobre, por fixture e nunca por contagem de palavra em loop vivo:

* **produtor sem `low`** — a tabela `complexity_score -> (model, effort)` de
  `/loop:individual-analysis` nao produz mais `low`, e o eco de distribuicao
  nao tem chave `low`;
* **item vence run** — sizing explicito per-item ganha do run anchor herdado;
* **run vence bucket** — item com sizing `null` herda o run anchor, NAO o
  default do bucket (incidente 05-25-rede-micro-sites);
* **coercao legado** — `low` gravado em config antiga ainda e aceito pelo
  loader e coagido para `standard` com WARN, apenas como retrocompatibilidade;
* **run anchor obrigatorio** — config em que o produtor declarou sizing
  all-null falha, salvo waiver humano registrado no proprio config.

O piso e `EffortLevel.STANDARD` (valor de fio `medium`). Nenhum tier novo e
introduzido aqui: os testes travam o comportamento das funcoes que ja existem
em `loader.py`.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest

from workflow_app.daily_loop.loader import (
    DailyLoopConfigError,
    _bucket_to_model_effort,
    _coerce_floor,
    _require_run_anchor,
    _resolve_effective_sizing,
    _resolve_run_default_model_effort,
)
from workflow_app.domain import EffortLevel, ModelName

REPO_ROOT = Path(__file__).resolve().parents[3]
PRODUTOR_SPEC = REPO_ROOT / ".claude" / "commands" / "loop" / "individual-analysis.md"

BUCKET_OPUS_HIGH: dict[str, Any] = {"id": "T-opus-high", "model": "opus", "effort": "high"}
BUCKET_SONNET_STANDARD: dict[str, Any] = {
    "id": "T-sonnet-standard",
    "model": "sonnet",
    "effort": "standard",
}


def _daily_loop(items_index: dict[str, Any], **extra: Any) -> dict[str, Any]:
    """Bloco `daily_loop` minimo com `items_index` V3."""
    payload: dict[str, Any] = {"slug": "fixture-sizing", "items_index": items_index}
    payload.update(extra)
    return payload


# ---------------------------------------------------------------------------
# Produtor sem `low`
# ---------------------------------------------------------------------------


def test_spec_do_produtor_existe() -> None:
    assert PRODUTOR_SPEC.is_file(), f"spec do produtor ausente: {PRODUTOR_SPEC}"


def test_tabela_do_produtor_nao_mapeia_nenhum_score_para_low() -> None:
    """Toda linha da tabela `Score | model | effort` resolve para high/standard."""
    texto = PRODUTOR_SPEC.read_text(encoding="utf-8")
    linhas = re.findall(
        r"^\|\s*(>=\s*\d+|\d+\s*-\s*\d+|<\s*\d+)\s*\|\s*(opus|sonnet)\s*\|\s*(\w+)\s*\|",
        texto,
        flags=re.MULTILINE,
    )
    assert linhas, "tabela de mapeamento score -> (model, effort) nao encontrada"
    efforts = {effort for _score, _model, effort in linhas}
    assert "low" not in efforts, (
        f"produtor ainda mapeia algum score para low; efforts encontrados: {sorted(efforts)}"
    )
    assert efforts <= {"standard", "high", "max"}, sorted(efforts)


def test_produtor_nao_emite_par_sonnet_low_em_exemplo() -> None:
    texto = PRODUTOR_SPEC.read_text(encoding="utf-8")
    assert "(sonnet, low)" not in texto
    assert "(opus, low)" not in texto


def test_effort_distribution_do_produtor_nao_tem_chave_low() -> None:
    texto = PRODUTOR_SPEC.read_text(encoding="utf-8")
    match = re.search(r"`effort_distribution`:\s*`(\{[^`]*\})`", texto)
    assert match, "campo effort_distribution nao encontrado na spec do produtor"
    assert '"low"' not in match.group(1), match.group(1)


def test_produtor_declara_o_piso_e_a_natureza_retrocompativel_da_coercao() -> None:
    texto = PRODUTOR_SPEC.read_text(encoding="utf-8")
    assert "Piso de effort: `standard`" in texto
    assert "retrocompatibilidade" in texto
    assert "Run anchor obrigatorio" in texto


# ---------------------------------------------------------------------------
# Precedencia: item > run anchor > bucket
# ---------------------------------------------------------------------------


def test_item_com_sizing_explicito_vence_o_run_ativo() -> None:
    daily = _daily_loop({"002": {"model": "opus", "effort": "high"}})
    model, effort, active_model, active_effort = _resolve_effective_sizing(
        daily,
        "002",
        BUCKET_SONNET_STANDARD,
        active_model=ModelName.SONNET,
        active_effort=EffortLevel.STANDARD,
    )
    assert (model, effort) == (ModelName.OPUS, EffortLevel.HIGH)
    # e o anchor avanca para o proximo item herdar
    assert (active_model, active_effort) == (ModelName.OPUS, EffortLevel.HIGH)


def test_item_com_sizing_explicito_vence_o_bucket() -> None:
    daily = _daily_loop({"001": {"model": "sonnet", "effort": "standard"}})
    model, effort, _am, _ae = _resolve_effective_sizing(
        daily, "001", BUCKET_OPUS_HIGH, active_model=None, active_effort=None
    )
    assert (model, effort) == (ModelName.SONNET, EffortLevel.STANDARD)


def test_item_nulo_herda_o_run_anchor_e_nao_o_bucket() -> None:
    """Regressao do incidente 05-25-rede-micro-sites."""
    daily = _daily_loop(
        {
            "001": {"model": "sonnet", "effort": "standard"},
            "002": {"model": None, "effort": None},
        }
    )
    anchor_model, anchor_effort = _resolve_run_default_model_effort(daily)
    assert (anchor_model, anchor_effort) == (ModelName.SONNET, EffortLevel.STANDARD)

    model, effort, _am, _ae = _resolve_effective_sizing(
        daily,
        "002",
        BUCKET_OPUS_HIGH,  # bucket caro de proposito
        active_model=anchor_model,
        active_effort=anchor_effort,
    )
    assert (model, effort) == (ModelName.SONNET, EffortLevel.STANDARD), (
        "item nulo caiu no default do bucket em vez de herdar o run anchor"
    )


def test_item_anterior_ao_anchor_tambem_herda_o_anchor() -> None:
    """O bookend `preparo` (id 001, nulo) herda o anchor de 002, nao o bucket."""
    daily = _daily_loop(
        {
            "001": {"model": None, "effort": None},
            "002": {"model": "sonnet", "effort": "standard"},
        }
    )
    anchor = _resolve_run_default_model_effort(daily)
    model, effort, _am, _ae = _resolve_effective_sizing(
        daily, "001", BUCKET_OPUS_HIGH, active_model=anchor[0], active_effort=anchor[1]
    )
    assert (model, effort) == (ModelName.SONNET, EffortLevel.STANDARD)


def test_sem_nenhum_sizing_declarado_o_bucket_segue_sendo_a_semente() -> None:
    daily = _daily_loop({"001": {}})
    anchor = _resolve_run_default_model_effort(daily)
    assert anchor == (None, None)
    model, effort, _am, _ae = _resolve_effective_sizing(
        daily, "001", BUCKET_OPUS_HIGH, active_model=None, active_effort=None
    )
    assert (model, effort) == (ModelName.OPUS, EffortLevel.HIGH)


# ---------------------------------------------------------------------------
# Coercao legado: low -> standard
# ---------------------------------------------------------------------------


def test_coercao_de_low_para_standard_com_warn(capsys: pytest.CaptureFixture) -> None:
    model, effort = _coerce_floor(ModelName.SONNET, EffortLevel.LOW, "item '007'")
    assert (model, effort) == (ModelName.SONNET, EffortLevel.STANDARD)
    err = capsys.readouterr().err
    assert "low banned" in err
    assert "item '007'" in err


def test_bucket_legado_com_low_e_promovido_e_nao_rejeitado() -> None:
    """Retrocompat: config antiga com `low` continua carregando, promovida."""
    model, effort = _bucket_to_model_effort(
        {"id": "T-sonnet-low", "model": "sonnet", "effort": "low"}
    )
    assert (model, effort) == (ModelName.SONNET, EffortLevel.STANDARD)


def test_item_legado_com_low_e_promovido_ao_piso() -> None:
    daily = _daily_loop({"003": {"model": "sonnet", "effort": "low"}})
    model, effort, _am, _ae = _resolve_effective_sizing(
        daily, "003", BUCKET_SONNET_STANDARD, active_model=None, active_effort=None
    )
    assert effort is EffortLevel.STANDARD


def test_effort_desconhecido_continua_sendo_erro_e_nao_coercao() -> None:
    with pytest.raises(DailyLoopConfigError):
        _bucket_to_model_effort({"id": "X", "model": "sonnet", "effort": "ultra"})


# ---------------------------------------------------------------------------
# Run anchor obrigatorio no primeiro run
# ---------------------------------------------------------------------------


def test_anchor_presente_passa() -> None:
    daily = _daily_loop({"001": {"model": "sonnet", "effort": "standard"}})
    _require_run_anchor(daily, _resolve_run_default_model_effort(daily))


def test_produtor_com_sizing_all_null_falha_sem_waiver() -> None:
    daily = _daily_loop(
        {
            "001": {"model": None, "effort": None},
            "002": {"model": None, "effort": None},
        }
    )
    with pytest.raises(DailyLoopConfigError) as excinfo:
        _require_run_anchor(daily, _resolve_run_default_model_effort(daily))
    msg = str(excinfo.value)
    assert "anchor" in msg
    assert "sizing_anchor_waiver" in msg, "mensagem deve nomear a saida de emergencia"


def test_waiver_registrado_libera_o_run(capsys: pytest.CaptureFixture) -> None:
    daily = _daily_loop(
        {"001": {"model": None, "effort": None}},
        sizing_anchor_waiver={"motivo": "loop de smoke sem custo", "autor": "pedro"},
    )
    _require_run_anchor(daily, _resolve_run_default_model_effort(daily))
    assert "sizing_anchor_waiver" in capsys.readouterr().err


def test_waiver_incompleto_nao_libera() -> None:
    daily = _daily_loop(
        {"001": {"model": None, "effort": None}},
        sizing_anchor_waiver={"motivo": "porque sim"},  # sem autor
    )
    with pytest.raises(DailyLoopConfigError) as excinfo:
        _require_run_anchor(daily, _resolve_run_default_model_effort(daily))
    assert "autor" in str(excinfo.value)


def test_config_que_nunca_declarou_sizing_nao_e_afetada() -> None:
    """V2 legado / fixture minima: sem chave model|effort, sem gate."""
    _require_run_anchor(_daily_loop({"001": {"commands": ["/cmd:create x.md"]}}), (None, None))
    _require_run_anchor({"slug": "sem-items-index", "buckets": []}, (None, None))


def test_gate_nao_introduz_tier_novo() -> None:
    """O piso continua sendo EffortLevel.STANDARD; nada de escala paralela."""
    from workflow_app.daily_loop import loader

    assert loader._DAILY_LOOP_FLOOR_EFFORT is EffortLevel.STANDARD
    assert loader._DAILY_LOOP_FLOOR_MODEL is ModelName.SONNET
    assert loader._FORBIDDEN_EFFORTS == frozenset({EffortLevel.LOW})
