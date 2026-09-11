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
    classify_run_anchor,
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


# ---------------------------------------------------------------------------
# Mensagem do gate quando a decisao ja esta documentada (C3)
# ---------------------------------------------------------------------------


def _raw_com_decisao(outcome: str = "override-heuristic-preserve-bucket", *, em_daily: bool = False) -> dict[str, Any]:
    """Config raiz carregando `sizing_decision`, no escopo pedido."""
    metadata = {"individual_analysis_summary": {"sizing_decision": {"outcome": outcome}}}
    daily = _daily_loop({"001": {"model": None, "effort": None}})
    if em_daily:
        daily["metadata"] = metadata
        return {"daily_loop": daily}
    return {"daily_loop": daily, "metadata": metadata}


def _erro_do_gate(raw: dict[str, Any]) -> str:
    daily = raw["daily_loop"]
    with pytest.raises(DailyLoopConfigError) as excinfo:
        _require_run_anchor(daily, _resolve_run_default_model_effort(daily), raw)
    return str(excinfo.value)


def test_sizing_decision_documentado_nao_libera_o_gate_sozinho() -> None:
    """O marcador e escrito pelo produtor: honra-lo desarmaria a guarda."""
    msg = _erro_do_gate(_raw_com_decisao())
    assert "anchor" in msg


def test_mensagem_nomeia_a_decisao_ja_documentada() -> None:
    msg = _erro_do_gate(_raw_com_decisao())
    assert "sizing_decision" in msg
    assert "override-heuristic-preserve-bucket" in msg
    assert "deliberado" in msg


def test_sizing_decision_em_daily_loop_metadata_tambem_e_detectado() -> None:
    assert "sizing_decision" in _erro_do_gate(_raw_com_decisao(em_daily=True))


def test_snippet_sugerido_e_json_valido_e_realmente_libera() -> None:
    """Round-trip: colar o que a mensagem manda colar tem que destravar o loop."""
    import json

    raw = _raw_com_decisao()
    linha = next(
        l.strip()
        for l in _erro_do_gate(raw).splitlines()
        if "sizing_anchor_waiver" in l and "{" in l
    )
    bloco = json.loads("{" + linha + "}")
    waiver = bloco["sizing_anchor_waiver"]
    assert waiver["motivo"].strip() and waiver["autor"].strip()

    raw["daily_loop"]["sizing_anchor_waiver"] = waiver
    _require_run_anchor(
        raw["daily_loop"], _resolve_run_default_model_effort(raw["daily_loop"]), raw
    )


def test_sem_registro_a_mensagem_generica_com_os_tres_remedios_e_mantida() -> None:
    daily = _daily_loop({"001": {"model": None, "effort": None}})
    with pytest.raises(DailyLoopConfigError) as excinfo:
        _require_run_anchor(daily, _resolve_run_default_model_effort(daily), {"daily_loop": daily})
    msg = str(excinfo.value)
    assert "individual-analysis" in msg
    assert "sizing_anchor_waiver" in msg
    assert "sizing_decision" not in msg, "sem registro nao ha o que citar"


def test_raw_config_e_opcional_assinatura_retrocompativel() -> None:
    """Callers antigos de 2 argumentos continuam validos - e caem na generica.

    Nao basta "nao explodir": sem `raw_config` o gate nao tem de onde ler a
    decisao, entao a mensagem PRECISA ser a generica de 3 remedios. Se um dia
    ela citar `sizing_decision` sem receber a config, e porque a deteccao
    passou a olhar estado global - exatamente o que este teste barra.
    """
    raw = _raw_com_decisao()
    daily = raw["daily_loop"]

    with pytest.raises(DailyLoopConfigError) as sem_raw:
        _require_run_anchor(daily, _resolve_run_default_model_effort(daily))
    assert "sizing_decision" not in str(sem_raw.value)

    # mesma config, agora com raw_config: a mensagem muda para a especifica
    assert "sizing_decision" in _erro_do_gate(raw)


def test_extrator_e_tolerante_a_config_malformada() -> None:
    from workflow_app.daily_loop.loader import _extract_sizing_decision

    assert _extract_sizing_decision(None) is None
    assert _extract_sizing_decision({}) is None
    assert _extract_sizing_decision({"metadata": "nao-e-dict"}) is None
    assert _extract_sizing_decision({"metadata": {"individual_analysis_summary": []}}) is None
    assert _extract_sizing_decision({"metadata": {"individual_analysis_summary": {"sizing_decision": {}}}}) is None


# ---------------------------------------------------------------------------
# Forma da decisao: o corpus real grava `sizing_decision` como str E como dict
# ---------------------------------------------------------------------------


def _raw_com_decisao_crua(decisao: Any) -> dict[str, Any]:
    """Config all-null carregando `sizing_decision` no formato dado, sem coagir."""
    return {
        "daily_loop": _daily_loop({"001": {"model": None, "effort": None}}),
        "metadata": {"individual_analysis_summary": {"sizing_decision": decisao}},
    }


def test_decisao_gravada_como_string_tambem_e_detectada() -> None:
    """Restringir a `dict` cegava o gate justamente nos loops mais antigos.

    No corpus de `blacksmith/loop-archives` as duas formas convivem: parte dos
    loops gravou a decisao como frase corrida, parte como objeto. Quem so
    entende `dict` devolve a mensagem generica para metade da populacao que a
    mensagem especifica existe para atender.
    """
    from workflow_app.daily_loop.loader import _extract_sizing_decision

    raw = _raw_com_decisao_crua("override deliberado: preservar bucket T-opus-high")
    assert _extract_sizing_decision(raw) == "override deliberado: preservar bucket T-opus-high"

    msg = _erro_do_gate(raw)
    assert "sizing_decision" in msg
    assert "preservar bucket T-opus-high" in msg


def test_string_vazia_ou_so_espaco_nao_conta_como_decisao() -> None:
    from workflow_app.daily_loop.loader import _extract_sizing_decision

    assert _extract_sizing_decision(_raw_com_decisao_crua("")) is None
    assert _extract_sizing_decision(_raw_com_decisao_crua("   \n\t ")) is None
    assert _extract_sizing_decision(_raw_com_decisao_crua(0)) is None
    assert _extract_sizing_decision(_raw_com_decisao_crua(["lista"])) is None


def test_rotulo_e_de_uma_linha_e_truncado() -> None:
    """O rotulo entra numa string JSON de uma linha: nada de \n nem de novela."""
    from workflow_app.daily_loop.loader import _rotulo_sizing_decision

    rotulo = _rotulo_sizing_decision("linha 1\nlinha 2\n\tlinha 3")
    assert "\n" not in rotulo and "\t" not in rotulo
    assert rotulo == "linha 1 linha 2 linha 3"

    longo = _rotulo_sizing_decision("z" * 400)
    assert len(longo) <= 120 and longo.endswith("...")

    assert _rotulo_sizing_decision({"reason": "colapso no piso"}) == "reason=colapso no piso"
    assert _rotulo_sizing_decision({"chave_desconhecida": "x"}) == "decisao registrada sem rotulo textual"


@pytest.mark.parametrize(
    "decisao",
    [
        {"outcome": 'aspas "duplas" no meio'},
        {"outcome": "barra invertida C:\\temp e aspas simples 'x'"},
        {"outcome": "acentuacao: heuristica colapsou, effort e nao-ASCII"},
        "frase com \"aspas\" e barra \\ no meio",
        "chaves { } e colchetes [ ] soltos",
    ],
    ids=["aspas", "barra", "acento", "str-aspas", "chaves"],
)
def test_snippet_continua_json_valido_com_texto_hostil(decisao: Any) -> None:
    """Regressao do defeito real: snippet montado a mao quebrava com aspas.

    A mensagem manda o operador COLAR o trecho. Se o trecho nao parseia, o gate
    passa a ensinar a produzir um `_LOOP-CONFIG.json` invalido - pior que nao
    sugerir nada.
    """
    import json

    raw = _raw_com_decisao_crua(decisao)
    linha = next(
        l.strip()
        for l in _erro_do_gate(raw).splitlines()
        if "sizing_anchor_waiver" in l and "{" in l
    )
    waiver = json.loads("{" + linha + "}")["sizing_anchor_waiver"]
    assert waiver["motivo"].strip() and waiver["autor"].strip()

    raw["daily_loop"]["sizing_anchor_waiver"] = waiver
    _require_run_anchor(
        raw["daily_loop"], _resolve_run_default_model_effort(raw["daily_loop"]), raw
    )


# ---------------------------------------------------------------------------
# O produtor fecha o proprio buraco (C2)
# ---------------------------------------------------------------------------


def test_produtor_declara_que_grava_o_waiver_no_all_null_deliberado() -> None:
    spec = PRODUTOR_SPEC.read_text(encoding="utf-8")
    assert "PASSO 3.7" in spec, "gate de run anchor precisa existir no produtor"
    assert "sizing_anchor_waiver" in spec
    assert "sizing_decision" in spec


def test_produtor_nao_afirma_mais_que_all_null_so_vem_de_edicao_manual() -> None:
    """Afirmacao empiricamente falsa: 14 dos 15 recusados tinham a analise rodada."""
    spec = PRODUTOR_SPEC.read_text(encoding="utf-8")
    assert "so aparece por edicao manual" not in spec


# ---------------------------------------------------------------------------
# Regressao de corpus: decisao documentada nunca deixa loop bloqueado
# ---------------------------------------------------------------------------


def test_nenhum_loop_com_decisao_documentada_fica_bloqueado() -> None:
    """Se a analise rodou e registrou o override, o waiver tem que estar la.

    Loop bloqueado SEM `sizing_decision` e legitimo: significa que
    `/loop:individual-analysis` nunca rodou, e o remedio certo e roda-la, nao
    isentar. Erros que nao sejam do gate de anchor sao problema de outro teste.
    """
    import json

    from workflow_app.daily_loop.loader import _extract_sizing_decision, build_loop_specs

    raiz = REPO_ROOT / "blacksmith" / "loop-archives"
    if not raiz.is_dir():
        pytest.skip("corpus de loop-archives ausente neste checkout")

    presos: list[str] = []
    for cfg in sorted(raiz.glob("*/_LOOP-CONFIG.json")):
        try:
            raw = json.loads(cfg.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        try:
            build_loop_specs(raw, cfg.parent)
        except DailyLoopConfigError as exc:
            if "anchor de sizing" not in str(exc):
                continue
            if _extract_sizing_decision(raw) is not None:
                presos.append(cfg.parent.name)
        except Exception:  # noqa: BLE001 - outros defeitos nao sao deste gate
            continue

    assert not presos, (
        "loops com override documentado e sem waiver (rode /loop:individual-analysis "
        f"PASSO 3.7 ou cole o waiver da mensagem do gate): {presos}"
    )


def test_nenhum_loop_com_analise_concluida_fica_bloqueado_pelo_anchor() -> None:
    """Cobre a populacao inteira, incluindo o gap que so aparece na reabertura.

    Duas ampliacoes sobre o teste irmao acima:

    1. Criterio e o carimbo `individual_analysis_completed_at`, nao
       `sizing_decision`: ha safra de config que rodou a analise ate o fim sem
       gravar o marcador, e essa safra escapava da rede.
    2. Chama `_require_run_anchor` DIRETO, sem passar por `build_loop_specs`.
       O loader retorna cedo quando nao ha item pendente (`if not pending:
       return []`), entao um loop concluido com config all-null passa hoje e
       quebra no dia em que o operador reabre um item falho. Medir pelo
       `build_loop_specs` deixaria justamente esse gap latente invisivel.

    Loop SEM o carimbo pode e deve ser recusado: la o remedio e rodar a
    analise, nao isentar.
    """
    import json

    from workflow_app.daily_loop.loader import _require_run_anchor as _gate

    raiz = REPO_ROOT / "blacksmith" / "loop-archives"
    if not raiz.is_dir():
        pytest.skip("corpus de loop-archives ausente neste checkout")

    presos: list[str] = []
    for cfg in sorted(raiz.glob("*/_LOOP-CONFIG.json")):
        try:
            raw = json.loads(cfg.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        daily = raw.get("daily_loop")
        if not isinstance(daily, dict):
            continue
        metadata = raw.get("metadata")
        carimbo = (
            metadata.get("individual_analysis_completed_at")
            if isinstance(metadata, dict)
            else None
        )
        if not carimbo:
            continue
        try:
            _gate(daily, _resolve_run_default_model_effort(daily), raw)
        except DailyLoopConfigError:
            presos.append(cfg.parent.name)
        except Exception:  # noqa: BLE001 - outros defeitos nao sao deste gate
            continue

    assert not presos, (
        "loops que concluiram a analise e mesmo assim o gate recusa - hoje ou "
        f"no primeiro item reaberto (falta waiver do PASSO 3.7): {presos}"
    )


# ---------------------------------------------------------------------------
# Task 39: classify_run_anchor e o predicado do W13
# ---------------------------------------------------------------------------


def test_classify_explicit_bate_com_require() -> None:
    daily = _daily_loop({"001": {"model": "sonnet", "effort": "standard"}})
    v = classify_run_anchor(daily, _resolve_run_default_model_effort(daily))
    assert v.status == "explicit"
    assert v.ok
    _require_run_anchor(daily, _resolve_run_default_model_effort(daily))


def test_classify_missing_mensagem_e_a_do_loader() -> None:
    daily = _daily_loop({"001": {"model": None, "effort": None}})
    v = classify_run_anchor(daily, _resolve_run_default_model_effort(daily))
    assert v.status == "missing"
    assert not v.ok
    with pytest.raises(DailyLoopConfigError) as excinfo:
        _require_run_anchor(daily, _resolve_run_default_model_effort(daily))
    assert str(excinfo.value) == v.message
    assert "sizing_anchor_waiver" in v.message


def test_classify_waiver_e_not_applicable() -> None:
    daily = _daily_loop(
        {"001": {"model": None, "effort": None}},
        sizing_anchor_waiver={"motivo": "smoke", "autor": "pedro"},
    )
    v = classify_run_anchor(daily, _resolve_run_default_model_effort(daily))
    assert v.status == "waiver"
    assert v.ok
    v2 = classify_run_anchor(_daily_loop({"001": {"commands": ["/x"]}}), (None, None))
    assert v2.status == "not_applicable"
