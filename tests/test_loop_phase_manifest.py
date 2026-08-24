"""O manifesto de fases e o builder e a documentacao contam a mesma coisa.

Task 07 do estudo 08-24 (10.2 I1, 10.3 P0-C, 13.3).

Tres amarras aqui:

1. O manifesto e internamente valido (fases catalogadas, placeholders
   declarados, contagens batendo com as listas).
2. O que o builder enfileira e exatamente o que o manifesto declara — provado
   contra os snapshots congelados na Task 06, nao contra uma re-implementacao
   das mesmas listas neste arquivo (isso so provaria que copiei duas vezes).
3. Consulta fora do contrato falha alto, em vez de devolver fila vazia.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from workflow_app.command_queue import loop_phase_manifest as manifest

SNAPSHOTS = Path(__file__).parent / "snapshots" / "loop_anatomy"

LANES = ("loop", "kimi_loop")
MODES = ("--task", "--cmd", "--both")
# Contagem vigente POR LANE. As duas lanes divergiram na Task 27 do estudo
# 08-24: `/loop:feature-design` entrou em --task e --both da lane `loop`, e a
# paridade com `kimi_loop` foi DISPENSADA por decisao registrada (a fase exige
# sintese sobre codigo, que weak-llm-pipeline-rules.md mantem fora da lane
# fraca). Uma constante unica escondia essa divergencia; agora ela e explicita.
CONTAGEM_VIGENTE = {
    "loop": {"--task": 8, "--cmd": 7, "--both": 10},
    "kimi_loop": {"--task": 7, "--cmd": 7, "--both": 9},
}


def test_manifesto_existe_e_carrega():
    path = manifest.manifest_path()
    assert path.is_file(), f"manifesto ausente em {path}"
    assert path.as_posix().endswith("ai-forge/rules/loop-phase-manifest.json")
    data = manifest.load_manifest()
    assert data["schema_version"] == "1.0.0"


def test_lanes_e_modos_canonicos():
    assert manifest.lanes() == sorted(LANES)
    for lane in LANES:
        assert manifest.modes(lane) == sorted(MODES)


@pytest.mark.parametrize("lane", LANES)
@pytest.mark.parametrize("mode", MODES)
def test_contagem_declarada_bate_com_a_lista(lane: str, mode: str):
    """`phase_counts` e derivavel; existe para quem le, e nao pode mentir."""
    declarado = manifest.load_manifest()["phase_counts"][lane][mode]
    assert declarado == manifest.phase_count(lane, mode)
    assert declarado == CONTAGEM_VIGENTE[lane][mode], (
        f"{lane} {mode}: contagem real vigente e {CONTAGEM_VIGENTE[lane][mode]} "
        "(12.2.6). Mudar isso exige regenerar os snapshots da Task 06."
    )


@pytest.mark.parametrize("lane", LANES)
@pytest.mark.parametrize("mode", MODES)
def test_toda_fase_esta_catalogada_com_requires_e_produces(lane: str, mode: str):
    catalog = manifest.load_manifest()["phase_catalog"]
    for entry in manifest.phases(lane, mode):
        fase = catalog[entry["phase"]]
        assert fase.get("descricao"), f"{entry['phase']} sem descricao"
        assert isinstance(fase.get("requires"), list) and fase["requires"]
        assert isinstance(fase.get("produces"), list) and fase["produces"]


@pytest.mark.parametrize("lane", LANES)
@pytest.mark.parametrize("mode", MODES)
def test_fases_nao_se_repetem_dentro_do_modo(lane: str, mode: str):
    nomes = [e["phase"] for e in manifest.phases(lane, mode)]
    assert len(nomes) == len(set(nomes)), f"{lane} {mode} repete fase: {nomes}"


@pytest.mark.parametrize("lane", LANES)
@pytest.mark.parametrize("mode", MODES)
def test_prefixo_da_lane_em_todo_comando(lane: str, mode: str):
    prefix = manifest.load_manifest()["lanes"][lane]["command_prefix"]
    nomes = manifest.build_sub_names(
        lane, mode, path_arg="source.md", slug="SLUG"
    )
    assert all(n.startswith(f"{prefix}:") for n in nomes), nomes


@pytest.mark.parametrize("lane", LANES)
@pytest.mark.parametrize("mode", MODES)
def test_nenhum_placeholder_sobra_no_render(lane: str, mode: str):
    nomes = manifest.build_sub_names(
        lane, mode, path_arg="source.md", slug="SLUG"
    )
    for n in nomes:
        assert "{" not in n and "}" not in n, f"placeholder nao resolvido: {n}"


# --------------------------------------------------------------------------
# manifesto x snapshots congelados (a amarra que importa)
# --------------------------------------------------------------------------


@pytest.mark.parametrize("mode", MODES)
def test_manifesto_reproduz_os_snapshots_da_linha_de_base(mode: str):
    """A refatoracao da Task 07 nao pode mexer em uma virgula da fila."""
    snap = json.loads(
        (SNAPSHOTS / f"prep_{mode.lstrip('-')}.json").read_text(encoding="utf-8")
    )
    do_manifesto = manifest.build_sub_names(
        "loop", mode, path_arg="source.md", slug="08-24-fixture-anatomy"
    )
    assert do_manifesto == snap["phases"], (
        "manifesto divergiu da linha de base. Se a mudanca de fila e "
        "intencional, regenere os snapshots com "
        "UPDATE_LOOP_ANATOMY_SNAPSHOTS=1 e explique no commit."
    )


def test_kimi_divide_create_structure_em_init_mais_enumerate():
    """A diferenca estrutural entre as lanes esta declarada, nao implicita."""
    loop_fases = [e["phase"] for e in manifest.phases("loop", "--task")]
    kimi_fases = [e["phase"] for e in manifest.phases("kimi_loop", "--task")]
    assert loop_fases[0] == "create-structure"
    assert kimi_fases[:2] == ["init", "enumerate"]
    assert "create-structure" not in kimi_fases
    assert "friendly-resume" in loop_fases
    assert "friendly-resume" not in kimi_fases


def test_both_e_o_unico_modo_com_marcacao_de_tipo():
    """`mark-type`/`check-tasks-and-cmd` sao exclusivos de --both (CLAUDE.md)."""
    exclusivas = {"mark-type", "check-tasks-and-cmd"}
    for lane in LANES:
        for mode in MODES:
            fases = {e["phase"] for e in manifest.phases(lane, mode)}
            presentes = fases & exclusivas
            if mode == "--both":
                assert presentes == exclusivas, f"{lane} {mode}: {presentes}"
            else:
                assert presentes == set(), f"{lane} {mode} vazou: {presentes}"


# --------------------------------------------------------------------------
# consulta fora do contrato
# --------------------------------------------------------------------------


def test_lane_desconhecida_falha_alto():
    with pytest.raises(manifest.LoopPhaseManifestError) as exc:
        manifest.phases("daily_loop", "--task")
    assert "daily_loop" in str(exc.value)


def test_modo_desconhecido_falha_alto():
    with pytest.raises(manifest.LoopPhaseManifestError) as exc:
        manifest.phases("loop", "--rocksmash")
    assert "--rocksmash" in str(exc.value)


def test_fase_fora_do_catalogo_e_rejeitada_na_validacao():
    ruim = {
        "phase_catalog": {},
        "lanes": {
            "x": {
                "command_prefix": "/x",
                "modes": {"--task": [{"phase": "fantasma", "args": ""}]},
            }
        },
    }
    with pytest.raises(manifest.LoopPhaseManifestError) as exc:
        manifest._validate(ruim, Path("memoria.json"))
    assert "fantasma" in str(exc.value)


def test_placeholder_nao_declarado_e_rejeitado():
    ruim = {
        "phase_catalog": {"f": {}},
        "lanes": {
            "x": {
                "command_prefix": "/x",
                "modes": {"--task": [{"phase": "f", "args": "--x {inventado}"}]},
            }
        },
    }
    with pytest.raises(manifest.LoopPhaseManifestError) as exc:
        manifest._validate(ruim, Path("memoria.json"))
    assert "{inventado}" in str(exc.value)


# --------------------------------------------------------------------------
# Task 27/28 do estudo 08-24 — fronteiras das fases novas
# --------------------------------------------------------------------------


def test_feature_design_so_existe_em_task_e_both_da_lane_loop():
    """`--cmd` cria slash-commands, nao feature de produto.

    Sem esta trava, alguem "uniformiza" as tres listas e o modo --cmd passa a
    gastar uma fase opus/high derivando escopo de feature que nao existe.
    """
    presente = {
        (lane, mode)
        for lane in LANES
        for mode in MODES
        if any(e["phase"] == "feature-design" for e in manifest.phases(lane, mode))
    }
    assert presente == {("loop", "--task"), ("loop", "--both")}


def test_adr_capture_esta_catalogada_e_fora_da_preparacao():
    """Finalizacao nao entra na fila de preparacao nem nas contagens.

    `adr-capture` roda depois de `reconcile-check`, quando ja existe execucao
    para capturar decisao. Enfileira-la na preparacao produziria um DECISIONS.md
    sobre um loop que ainda nao decidiu nada.
    """
    catalog = manifest.load_manifest()["phase_catalog"]
    assert "adr-capture" in catalog, (
        "adr-capture precisa estar catalogada com requires/produces mesmo sem "
        "entrar em modes — o catalogo documenta a fase, os modes so a agendam."
    )
    assert catalog["adr-capture"]["produces"] == ["DECISIONS.md"]
    enfileirada = [
        (lane, mode)
        for lane in LANES
        for mode in MODES
        if any(e["phase"] == "adr-capture" for e in manifest.phases(lane, mode))
    ]
    assert enfileirada == []
