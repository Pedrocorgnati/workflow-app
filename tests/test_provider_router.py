"""Pure-logic tests for the provider router (source.md secao 7.1 + secao 11).

Cobre a matriz da secao 11 (Main LLM x Worker Kimi x Worker Codex x tipo de
comando) e cada uma das 7 regras de `classify_provider`. O modulo sob teste e
PURO: nenhum import de Qt, nenhuma fixture de UI. CommandSpec vem do dominio
puro; as whitelists sao consumidas reais (nao mockadas) para garantir que o
router casa com a fonte da verdade de elegibilidade.

Comandos canonicos usados (verificados contra as whitelists reais):
  - KIMI_CMD  "/dcp:matrix-init"  -> is_kimi_compatible == True
  - CODEX_CMD "/cmd:review"       -> is_codex_compatible == True
  - OTHER_CMD "/prd-create"       -> nenhuma das duas
As whitelists nao tem intersecao, entao a precedencia Kimi>Codex (regra 6) e
exercitada via `kimi_eligible=True` sobre um comando Codex-compativel.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from workflow_app.command_queue import provider_router as provider_router_module
from workflow_app.command_queue.codex_whitelist import is_codex_compatible
from workflow_app.command_queue.kimi_whitelist import is_kimi_compatible

# `_classify_family_variant` e deliberadamente privado: o snapshot legado
# (`tests/fixtures/llm_config_legacy_snapshot.json`) compara `dir(provider_router)`
# e qualquer binding publico novo neste modulo e regressao de superficie. O teste
# consome o nome privado; producao nao expoe a tabela familia/variante.
from workflow_app.command_queue.provider_router import (  # noqa: PLC2701
    Provider,
    RoutingState,
    _classify_family_variant,
    classify_provider,
    normalize_command_name,
)
from workflow_app.config import feature_flags
from workflow_app.domain import CommandSpec

KIMI_CMD = "/dcp:matrix-init"
CODEX_CMD = "/cmd:review"
OTHER_CMD = "/prd-create"


def _spec(
    name: str = OTHER_CMD,
    *,
    kind: str = "slash",
    kimi_eligible: bool = False,
) -> CommandSpec:
    """Constroi um CommandSpec minimo para o router (so name/kind/kimi_eligible importam)."""
    return CommandSpec(name=name, kind=kind, kimi_eligible=kimi_eligible)


def _state(*, kimi: bool, codex: bool, main_llm: str = "claude") -> RoutingState:
    return RoutingState(
        kimi_worker_enabled=kimi,
        codex_worker_enabled=codex,
        main_llm=main_llm,
    )


# --------------------------------------------------------------------------- #
# Sanidade das premissas: os comandos escolhidos casam o que o teste afirma.   #
# --------------------------------------------------------------------------- #


def test_command_fixtures_are_what_we_claim():
    assert is_kimi_compatible(KIMI_CMD) is True
    assert is_kimi_compatible(CODEX_CMD) is False
    assert is_codex_compatible(CODEX_CMD) is True
    assert is_codex_compatible(KIMI_CMD) is False
    assert is_kimi_compatible(OTHER_CMD) is False
    assert is_codex_compatible(OTHER_CMD) is False


# --------------------------------------------------------------------------- #
# Matriz da secao 11 — Main LLM x Worker Kimi x Worker Codex x tipo de comando #
# (kimi, codex, main_llm, command_name, expected_provider)                     #
# --------------------------------------------------------------------------- #

MATRIX = [
    # Linha 1: Claude / off / off -> tudo T1 verde
    ("r1-kimi", False, False, "claude", KIMI_CMD, Provider.CLAUDE),
    ("r1-codex", False, False, "claude", CODEX_CMD, Provider.CLAUDE),
    ("r1-other", False, False, "claude", OTHER_CMD, Provider.CLAUDE),
    # Linha 2: Claude / on / off -> comando Kimi vai T2; resto T1
    ("r2-kimi", True, False, "claude", KIMI_CMD, Provider.KIMI),
    ("r2-codex", True, False, "claude", CODEX_CMD, Provider.CLAUDE),
    ("r2-other", True, False, "claude", OTHER_CMD, Provider.CLAUDE),
    # Linha 3: Claude / off / on -> comando Codex vai T3; resto T1
    ("r3-kimi", False, True, "claude", KIMI_CMD, Provider.CLAUDE),
    ("r3-codex", False, True, "claude", CODEX_CMD, Provider.CODEX),
    ("r3-other", False, True, "claude", OTHER_CMD, Provider.CLAUDE),
    # Linha 4: Claude / on / on -> Kimi->T2, Codex->T3, outro->T1
    ("r4-kimi", True, True, "claude", KIMI_CMD, Provider.KIMI),
    ("r4-codex", True, True, "claude", CODEX_CMD, Provider.CODEX),
    ("r4-other", True, True, "claude", OTHER_CMD, Provider.CLAUDE),
    # Linha 5: Main Kimi / off / on -> worker Codex despacha; comando Kimi/outro
    # caem em T1 (via Main Kimi) == Provider.CLAUDE (eixo worker decide, inv 2).
    ("r5-kimi", False, True, "kimi", KIMI_CMD, Provider.CLAUDE),
    ("r5-codex", False, True, "kimi", CODEX_CMD, Provider.CODEX),
    ("r5-other", False, True, "kimi", OTHER_CMD, Provider.CLAUDE),
    # Linha 6: Main Codex / on / off -> worker Kimi despacha; comando Codex/outro
    # caem em T1 (via Main Codex) == Provider.CLAUDE.
    ("r6-kimi", True, False, "codex", KIMI_CMD, Provider.KIMI),
    ("r6-codex", True, False, "codex", CODEX_CMD, Provider.CLAUDE),
    ("r6-other", True, False, "codex", OTHER_CMD, Provider.CLAUDE),
]


@pytest.mark.parametrize(
    "label,kimi,codex,main_llm,name,expected",
    MATRIX,
    ids=[row[0] for row in MATRIX],
)
def test_routing_matrix(label, kimi, codex, main_llm, name, expected):
    result = classify_provider(_spec(name), _state(kimi=kimi, codex=codex, main_llm=main_llm))
    assert result is expected


# --------------------------------------------------------------------------- #
# Regras individuais (source.md secao 7.1)                                     #
# --------------------------------------------------------------------------- #


def test_rule1_local_action_always_claude_even_with_workers_on():
    # Mesmo com ambos workers ativos e nome Kimi-compativel, local-action -> CLAUDE.
    spec = _spec(KIMI_CMD, kind="local-action", kimi_eligible=True)
    assert classify_provider(spec, _state(kimi=True, codex=True)) is Provider.CLAUDE


@pytest.mark.parametrize("directive", ["/clear", "/model", "/effort"])
def test_rule2_session_directives_are_claude(directive):
    # Diretivas nunca viram worker, mesmo com workers ativos.
    assert classify_provider(_spec(directive), _state(kimi=True, codex=True)) is Provider.CLAUDE


def test_rule2_directive_with_args_normalized_to_head():
    # "/model opus" deve normalizar para "/model" e cair em CLAUDE.
    assert classify_provider(_spec("/model opus"), _state(kimi=True, codex=True)) is Provider.CLAUDE


def test_rule3_no_worker_active_is_claude():
    assert classify_provider(_spec(KIMI_CMD), _state(kimi=False, codex=False)) is Provider.CLAUDE


def test_rule4_kimi_eligible_flag_routes_kimi_even_if_name_not_whitelisted():
    # Comando nao listado no whitelist Kimi mas com kimi_eligible herdado -> KIMI.
    spec = _spec(OTHER_CMD, kimi_eligible=True)
    assert classify_provider(spec, _state(kimi=True, codex=False)) is Provider.KIMI


def test_rule4_kimi_eligible_flag_needs_worker_on():
    # kimi_eligible sozinho, sem worker Kimi ativo, nao roteia para Kimi.
    spec = _spec(OTHER_CMD, kimi_eligible=True)
    assert classify_provider(spec, _state(kimi=False, codex=False)) is Provider.CLAUDE


def test_rule6_kimi_wins_when_both_eligible():
    # Comando Codex-compativel + kimi_eligible + ambos workers on -> Kimi vence.
    spec = _spec(CODEX_CMD, kimi_eligible=True)
    assert classify_provider(spec, _state(kimi=True, codex=True)) is Provider.KIMI


def test_rule6_codex_only_when_kimi_not_eligible():
    # Mesmo comando Codex-compativel, sem kimi_eligible, ambos workers on -> Codex.
    spec = _spec(CODEX_CMD, kimi_eligible=False)
    assert classify_provider(spec, _state(kimi=True, codex=True)) is Provider.CODEX


def test_rule7_fallback_claude_for_unknown_command_with_workers_on():
    # Comando que nao casa nenhuma whitelist, sem kimi_eligible -> CLAUDE.
    assert classify_provider(_spec(OTHER_CMD), _state(kimi=True, codex=True)) is Provider.CLAUDE


def test_codex_command_ignored_when_only_kimi_worker_on():
    assert classify_provider(_spec(CODEX_CMD), _state(kimi=True, codex=False)) is Provider.CLAUDE


def test_kimi_command_ignored_when_only_codex_worker_on():
    assert classify_provider(_spec(KIMI_CMD), _state(kimi=False, codex=True)) is Provider.CLAUDE


# --------------------------------------------------------------------------- #
# Contrato do tipo Provider / RoutingState                                     #
# --------------------------------------------------------------------------- #


def test_provider_is_str_enum():
    assert Provider.CLAUDE == "claude"
    assert Provider.KIMI == "kimi"
    assert Provider.CODEX == "codex"


def test_routing_state_is_frozen():
    state = _state(kimi=True, codex=False)
    with pytest.raises(Exception):
        state.kimi_worker_enabled = False  # type: ignore[misc]


def test_normalize_command_name_strips_args_and_whitespace():
    assert normalize_command_name("  /model opus  ") == "/model"
    assert normalize_command_name("/clear") == "/clear"
    assert normalize_command_name("") == ""
    assert normalize_command_name("   ") == ""


def test_classify_matches_whitelist_for_command_with_trailing_args():
    # Args depois do nome nao quebram a classificacao (normalizacao de cabeca).
    spec = _spec(f"{KIMI_CMD} --module 3")
    assert classify_provider(spec, _state(kimi=True, codex=False)) is Provider.KIMI


def test_module_is_pure_no_qt_import():
    # Modulo PURO (source.md secao 12): importar provider_router num interpretador
    # limpo nao pode arrastar Qt transitivamente. Subprocesso garante isolamento de
    # qualquer Qt ja carregado por outros testes nesta sessao.
    import subprocess
    import sys

    probe = (
        "import sys;"
        "import workflow_app.command_queue.provider_router;"
        "qt=[m for m in sys.modules if m.startswith(('PySide6','PyQt'))];"
        "sys.exit(1 if qt else 0)"
    )
    result = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True)
    assert result.returncode == 0, f"provider_router pulled Qt transitively: {result.stdout}"


def test_provider_enum_has_qwen():
    """ST001 (item 009): Provider.QWEN exists with value 'qwen'."""
    assert hasattr(Provider, "QWEN")
    assert Provider.QWEN.value == "qwen"
    assert Provider.QWEN == "qwen"  # str-Enum comparison


# --------------------------------------------------------------------------- #
# Classificacao por familia e variante (item 010)                              #
# --------------------------------------------------------------------------- #


class TestClassifyFamilyVariant:
    """Tabela de classificacao familia/variante (item 010)."""

    @pytest.mark.parametrize(
        "provider,expected_family,expected_variant",
        [
            ("claude", "claude", "claude"),
            ("kimi", "kimi", "kimi"),
            ("codex", "codex", "codex"),
            ("qwen", "qwen", "qwen"),
        ],
        ids=["claude", "kimi", "codex", "qwen"],
    )
    def test_known_providers(self, provider, expected_family, expected_variant):
        family, variant = _classify_family_variant(provider)
        assert family == expected_family
        assert variant == expected_variant

    def test_unknown_provider_returns_unknown_tuple(self):
        assert _classify_family_variant("grok") == ("grok", "grok")  # item 020: grok now known
        assert _classify_family_variant("") == ("unknown", "unknown")

    def test_case_insensitive(self):
        assert _classify_family_variant("KIMI") == ("kimi", "kimi")
        assert _classify_family_variant("Codex") == ("codex", "codex")


# --------------------------------------------------------------------------- #
# Main LLM participa da decisao (item 010) — SOMENTE em modo Router V2         #
# --------------------------------------------------------------------------- #
# A regra "familia do comando == familia do Main -> CLAUDE" vive atras de DOIS
# kill-switches em conjuncao: `SF_LLM_CONFIG_V2` (global, item 002) e
# `SF_PROVIDER_ROUTER_V2` (especifico, item 010). Ambos sao boot-frozen, entao
# todo teste de estado de flag exige PROCESSO NOVO (contrato do feature_flags:
# nao existe hook de reset). Por isso estes casos rodam em subprocesso.
#
# Divergencia deliberada, registrada aqui como oraculo executavel: enquanto o
# mesmo provider puder estar simultaneamente como Main e como Worker, o legado
# manda ao WORKER (contrato de 2026-05-30) e o V2 manda ao MAIN. Os dois lados
# da colisao estao travados por teste abaixo.

_ROUTE_PROBE = """
import json
import sys

from workflow_app.command_queue import provider_router as mod
from workflow_app.command_queue.provider_router import (
    RoutingState,
    classify_provider,
)
from workflow_app.config import feature_flags
from workflow_app.domain import CommandSpec

cases = json.loads(sys.argv[1])
out = []
for case in cases:
    spec = CommandSpec(
        name=case["name"],
        kind=case.get("kind", "slash"),
        kimi_eligible=case.get("kimi_eligible", False),
    )
    state = RoutingState(
        kimi_worker_enabled=case["kimi"],
        codex_worker_enabled=case["codex"],
        main_llm=case["main_llm"],
    )
    out.append(classify_provider(spec, state).value)

sys.stdout.write(
    json.dumps(
        {
            "providers": out,
            # Hermeticidade: prova que o filho importou ESTE checkout e que o
            # ambiente pedido chegou de fato ao processo novo. Sem isso, um
            # probe que rodasse contra outro `workflow_app` (ou com a flag
            # perdida no caminho) poderia passar verde por coincidencia.
            "module_file": mod.__file__,
            "flags": {
                "global": feature_flags.llm_config_v2_state(),
                "router": feature_flags.provider_router_v2_state(),
            },
        }
    )
)
"""

# Raiz do workflow-app: o probe roda com este cwd (mesma hermeticidade do
# `_run_probe` de tests/test_command_queue_widget.py).
_WORKFLOW_APP_ROOT = Path(__file__).resolve().parents[1]


def _probe_env(*, global_flag: str | None, router_flag: str | None) -> dict[str, str]:
    """Ambiente do filho: `None` REMOVE a variavel (estado `absent`)."""
    env = dict(os.environ)
    for var, value in (
        (feature_flags.llm_config_v2_flag_name(), global_flag),
        (feature_flags.provider_router_v2_flag_name(), router_flag),
    ):
        if value is None:
            env.pop(var, None)
        else:
            env[var] = value
    return env


def _run_route_probe(
    cases: list[dict],
    *,
    global_flag: str | None,
    router_flag: str | None,
) -> dict:
    """Classifica `cases` num processo NOVO com as flags no estado pedido."""
    result = subprocess.run(
        [sys.executable, "-c", _ROUTE_PROBE, json.dumps(cases)],
        capture_output=True,
        text=True,
        env=_probe_env(global_flag=global_flag, router_flag=router_flag),
        cwd=str(_WORKFLOW_APP_ROOT),
    )
    assert result.returncode == 0, (
        f"probe falhou rc={result.returncode}\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    got = json.loads(result.stdout)
    # O filho tem de ser o mesmo checkout que este teste esta exercitando.
    assert Path(got["module_file"]).resolve() == Path(provider_router_module.__file__).resolve(), (
        f"probe importou outro provider_router: {got['module_file']}"
    )
    return got


def _route(cases: list[dict], *, router_v2: bool) -> list[str]:
    """Atalho dos dois modos canonicos: V2 ligado (conjuncao) ou legado (ausente).

    O modo legado REMOVE as duas variaveis em vez de setar `"0"`, para exercitar
    o caminho default real de producao.
    """
    flag = "1" if router_v2 else None
    got = _run_route_probe(cases, global_flag=flag, router_flag=flag)
    expected_state = "on" if router_v2 else "absent"
    # Prova que o estado pedido chegou ao filho: sem esta assercao, uma flag
    # perdida no caminho degradaria silenciosamente para o legado e os testes
    # "V2" passariam a medir o legado.
    assert got["flags"] == {"global": expected_state, "router": expected_state}, got["flags"]
    return got["providers"]


def test_main_kimi_with_kimi_worker_and_kimi_command_routes_to_main():
    """V2: main=kimi, kimi worker ON, comando kimi -> CLAUDE (T1 roda o Main)."""
    case = {"name": KIMI_CMD, "kimi": True, "codex": True, "main_llm": "kimi"}
    assert _route([case], router_v2=True) == ["claude"]


def test_main_kimi_with_kimi_worker_and_kimi_eligible_flag_routes_to_main():
    """V2 (via flag): main=kimi, kimi_eligible=True, kimi worker ON -> CLAUDE."""
    case = {
        "name": OTHER_CMD,
        "kimi_eligible": True,
        "kimi": True,
        "codex": False,
        "main_llm": "kimi",
    }
    assert _route([case], router_v2=True) == ["claude"]


def test_main_codex_with_codex_worker_and_codex_command_routes_to_main():
    """V2: main=codex, codex worker ON, comando codex -> CLAUDE (T1 roda o Main)."""
    case = {"name": CODEX_CMD, "kimi": True, "codex": True, "main_llm": "codex"}
    assert _route([case], router_v2=True) == ["claude"]


def test_main_kimi_does_not_affect_codex_command():
    """V2: Main=kimi nao afeta comando codex (familias diferentes) -> CODEX."""
    case = {"name": CODEX_CMD, "kimi": False, "codex": True, "main_llm": "kimi"}
    assert _route([case], router_v2=True) == ["codex"]


def test_main_codex_does_not_affect_kimi_command():
    """V2: Main=codex nao afeta comando kimi (familias diferentes) -> KIMI."""
    case = {"name": KIMI_CMD, "kimi": True, "codex": False, "main_llm": "codex"}
    assert _route([case], router_v2=True) == ["kimi"]


def test_v2_without_workers_still_falls_back_to_claude():
    """V2 ligado e nenhum worker: o early-return legado sumiu, mas o destino nao muda.

    O ramo V2 substituiu o `return CLAUDE` antecipado de "nenhum worker ativo".
    Este teste prova que as regras 4/5 continuam exigindo worker ligado e que o
    fallback final devolve CLAUDE, inclusive quando a familia NAO bate com o Main.
    """
    cases = [
        # Familia bate com o Main (retorno pela regra de familia).
        {"name": KIMI_CMD, "kimi": False, "codex": False, "main_llm": "kimi"},
        # Familia NAO bate (retorno so pelo fallback final).
        {"name": CODEX_CMD, "kimi": False, "codex": False, "main_llm": "kimi"},
        # Comando fora das duas whitelists (familia "unknown").
        {"name": OTHER_CMD, "kimi": False, "codex": False, "main_llm": "claude"},
    ]
    assert _route(cases, router_v2=True) == ["claude", "claude", "claude"]


def test_legacy_mode_keeps_worker_precedence_on_main_worker_collision():
    """Flags ausentes (default de producao): worker vence o Main na colisao.

    Trava o lado legado da divergencia — contrato de 2026-05-30, so superado
    quando o Router V2 virar default.
    """
    cases = [
        {"name": KIMI_CMD, "kimi": True, "codex": True, "main_llm": "kimi"},
        {"name": CODEX_CMD, "kimi": False, "codex": True, "main_llm": "codex"},
        {
            "name": OTHER_CMD,
            "kimi_eligible": True,
            "kimi": True,
            "codex": False,
            "main_llm": "kimi",
        },
    ]
    assert _route(cases, router_v2=False) == ["kimi", "codex", "kimi"]


# A colisao Main==Worker e o oraculo de modo: no legado o worker vence, no V2 o
# Main vence. Toda combinacao que NAO seja a conjuncao das duas flags em "1"
# tem de produzir o resultado legado (fail-closed).
_COLLISION_CASE = [{"name": KIMI_CMD, "kimi": True, "codex": True, "main_llm": "kimi"}]


@pytest.mark.parametrize(
    "global_flag,router_flag",
    [
        ("1", None),  # global ligado, especifica ausente
        (None, "1"),  # especifica ligada, global ausente
        ("0", "1"),  # especifica ligada, global explicitamente desligado
        ("1", "0"),  # global ligado, especifica explicitamente desligada
        ("true", "1"),  # valor nao reconhecido no global (sem casefold/strip)
        ("1", " 1 "),  # valor nao reconhecido na especifica (sem strip)
        (None, None),  # ambas ausentes
    ],
    ids=[
        "global-on-router-absent",
        "router-on-global-absent",
        "router-on-global-off",
        "global-on-router-off",
        "global-unrecognized",
        "router-unrecognized",
        "both-absent",
    ],
)
def test_router_v2_requires_both_kill_switches(global_flag, router_flag):
    """So a conjuncao das duas em `"1"` liga o modo novo; o resto e legado."""
    got = _run_route_probe(_COLLISION_CASE, global_flag=global_flag, router_flag=router_flag)
    assert got["providers"] == ["kimi"], got


_BOOT_FREEZE_PROBE = """
import json
import os
import sys

from workflow_app.config import feature_flags

before = {
    "state": feature_flags.provider_router_v2_state(),
    "enabled": feature_flags.provider_router_v2_enabled(),
}
os.environ[feature_flags.provider_router_v2_flag_name()] = "1"
after_set = {
    "state": feature_flags.provider_router_v2_state(),
    "enabled": feature_flags.provider_router_v2_enabled(),
}
os.environ.pop(feature_flags.provider_router_v2_flag_name(), None)
after_unset = {
    "state": feature_flags.provider_router_v2_state(),
    "enabled": feature_flags.provider_router_v2_enabled(),
}
sys.stdout.write(
    json.dumps({"before": before, "after_set": after_set, "after_unset": after_unset})
)
"""


@pytest.mark.parametrize(
    "initial,expected_state",
    [(None, "absent"), ("0", "off"), ("1", "on"), ("sim", "unrecognized")],
    ids=["absent", "off", "on", "unrecognized"],
)
def test_router_kill_switch_state_is_frozen_at_boot(initial, expected_state):
    """Mutar o ambiente DEPOIS do import nao muda a resposta da flag especifica.

    Mesmo contrato do item 002 (nao existe hook de reset). Sem este probe, uma
    implementacao que voltasse a `os.environ` a cada chamada continuaria verde
    em todos os outros testes, porque nenhum deles muta a variavel in-process.
    """
    result = subprocess.run(
        [sys.executable, "-c", _BOOT_FREEZE_PROBE],
        capture_output=True,
        text=True,
        env=_probe_env(global_flag=None, router_flag=initial),
        cwd=str(_WORKFLOW_APP_ROOT),
    )
    assert result.returncode == 0, f"probe falhou: {result.stderr}"
    got = json.loads(result.stdout)
    assert got["before"] == {"state": expected_state, "enabled": expected_state == "on"}, got
    assert got["after_set"] == got["before"], got
    assert got["after_unset"] == got["before"], got


def test_public_family_variant_name_still_resolves_without_polluting_dir():
    """O nome publico do item 010 continua acessivel, mas fora de `dir()`.

    `classify_family_variant` foi criado publico pelo item 010; o snapshot legado
    trava `dir(provider_router)`. PEP 562 concilia os dois — este teste impede
    que qualquer um dos dois lados seja quebrado silenciosamente.
    """
    assert (
        provider_router_module.classify_family_variant
        is provider_router_module._classify_family_variant
    )
    assert provider_router_module.classify_family_variant("kimi") == ("kimi", "kimi")
    assert "classify_family_variant" not in dir(provider_router_module)

    with pytest.raises(AttributeError):
        provider_router_module.nome_que_nao_existe
