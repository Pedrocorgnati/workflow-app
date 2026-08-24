"""As cinco fixtures minimas do corpus existem e congelam o fenomeno declarado.

Fonte: Task 05 do estudo 08-24 (secoes 13.2 e 9.3).

Regra que este arquivo protege: **nenhum teste referencia diretorio vivo do
corpus**. O caso `08-19-conecta-clube-tasklist-ondas-0-4` continua sendo
executado e editado; um teste ancorado nele quebra por motivo alheio ao codigo.
As fixtures sao extracoes minimas, versionadas e imutaveis.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from workflow_app.daily_loop.loader import (
    InvalidMarkerError,
    parse_progress_items,
    scan_progress_invalid_markers,
)

FIXTURES = Path(__file__).parent / "fixtures" / "loop"

CINCO_FIXTURES = (
    "config-sizing-comprimido.json",
    "task-contradicao-minima.md",
    "progress-tres-status-mais-invalido.md",
    "rocksmash-seed-sem-execucao.md",
    "rocksmash-execucao-parcial.json",
)

# Diretorio vivo que NAO pode ser referenciado por nenhum teste (13.2).
LIVE_LOOP_DIR = "08-19-conecta-clube-tasklist-ondas-0-4"


@pytest.mark.parametrize("name", CINCO_FIXTURES)
def test_as_cinco_fixtures_existem_e_nao_sao_vazias(name: str):
    path = FIXTURES / name
    assert path.is_file(), f"fixture ausente: {path}"
    assert path.stat().st_size > 0


def test_nenhum_teste_referencia_o_diretorio_vivo():
    tests_dir = Path(__file__).parent
    ofensores = []
    for py in sorted(tests_dir.rglob("*.py")):
        if py.name == Path(__file__).name:
            continue  # este arquivo cita o nome justamente para proibi-lo
        if LIVE_LOOP_DIR in py.read_text(encoding="utf-8", errors="replace"):
            ofensores.append(str(py.relative_to(tests_dir)))
    assert ofensores == [], (
        "teste ancorado em diretorio vivo do corpus; extraia uma fixture minima: "
        f"{ofensores}"
    )


def test_fixtures_nao_apontam_para_o_diretorio_vivo():
    ofensores = [
        f.name
        for f in FIXTURES.iterdir()
        if f.is_file()
        and f.name != "README.md"  # o README cita a origem como prosa, de proposito
        and LIVE_LOOP_DIR in f.read_text(encoding="utf-8", errors="replace")
    ]
    assert ofensores == [], f"fixture copiou path do corpus vivo: {ofensores}"


def test_config_sizing_comprimido_tem_bucket_e_override_por_item():
    cfg = json.loads(
        (FIXTURES / "config-sizing-comprimido.json").read_text(encoding="utf-8")
    )
    daily = cfg["daily_loop"]
    buckets = {b["id"]: b for b in daily["buckets"]}
    # sizing comprimido: o bucket carrega model/effort para todos os seus itens
    assert buckets["T-opus-high"]["model"] == "opus"
    assert buckets["T-opus-high"]["effort"] == "high"
    # override: o item 002 diverge do proprio bucket
    item_002 = next(i for i in buckets["T-opus-high"]["items"] if i["id"] == "002")
    assert (item_002["model"], item_002["effort"]) == ("sonnet", "medium")
    # o espelho items_index carrega o mesmo override
    assert daily["items_index"]["002"]["model"] == "sonnet"
    # e o item sem override nao inventa sizing proprio
    item_001 = next(i for i in buckets["T-opus-high"]["items"] if i["id"] == "001")
    assert "model" not in item_001 and "effort" not in item_001


def test_task_contradicao_minima_congela_as_duas_frases_opostas():
    txt = (FIXTURES / "task-contradicao-minima.md").read_text(encoding="utf-8")
    escopo = txt.split("## Escopo exato", 1)[1].split("## Notas", 1)[0]
    notas = txt.split("## Notas", 1)[1]
    assert "Nao remover nem comentar o curto-circuito da linha 897" in escopo
    assert "deve ser removido ou refinado" in notas
    # As duas falam do MESMO alvo: e isso que faz a contradicao ser real.
    assert "linha 897" in escopo and "linha 897" in notas


def test_progress_fixture_tem_tres_status_e_um_invalid_marker():
    txt = (FIXTURES / "progress-tres-status-mais-invalido.md").read_text(
        encoding="utf-8"
    )
    with pytest.raises(InvalidMarkerError):
        parse_progress_items(txt)
    trail = scan_progress_invalid_markers(txt)
    assert [(m.item_id, m.glyph) for m in trail] == [("004", "~")]
    itens = parse_progress_items(txt, strict=False)
    assert [i.status for i in itens] == ["done", "pending", "failed"]


def test_rocksmash_seed_nao_tem_marcador_de_execucao():
    txt = (FIXTURES / "rocksmash-seed-sem-execucao.md").read_text(encoding="utf-8")
    assert "###" in txt  # a arvore decimal existe
    for glifo in ("[x]", "[ ]", "[!]", "[~]"):
        assert glifo not in txt, f"seed nao executado nao pode ter marcador {glifo}"


def test_rocksmash_execucao_parcial_e_parcial_de_verdade():
    cfg = json.loads(
        (FIXTURES / "rocksmash-execucao-parcial.json").read_text(encoding="utf-8")
    )
    assert cfg["mode"] == "rocksmash"
    estados = {
        i["subphase"]: i["state"] for i in cfg["daily_loop"]["buckets"][0]["items"]
    }
    assert estados == {"2.1": "done", "2.2": "in_progress", "2.3": "not_started"}
    # parcialidade real: fases inteiras do seed nao foram materializadas
    assert cfg["metadata"]["phases_untouched"] == ["1.1", "1.2", "3.1"]
