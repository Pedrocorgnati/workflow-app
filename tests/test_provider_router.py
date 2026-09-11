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


@pytest.mark.parametrize("directive", ["/clear", "/model", "/effort", "/reasoning"])
def test_rule2_session_directives_are_claude(directive):
    # Diretivas nunca viram worker, mesmo com workers ativos.
    assert classify_provider(_spec(directive), _state(kimi=True, codex=True)) is Provider.CLAUDE


@pytest.mark.parametrize(
    "directive",
    ["/model opus", "/effort high", "/model sol high", "/model k3", "/reasoning yes"],
)
def test_rule2_directive_with_args_normalized_to_head(directive):
    # A regra 2 olha o HEAD normalizado, entao vale para o dialeto Claude vivo
    # e para o residuo do dialeto revogado em 2026-08-17 (D-C27-2): a forma
    # Codex de 3 tokens, o `/model k3` e o `/reasoning` do Kimi. Snapshot salvo
    # naquela janela nao pode virar worker por causa do argumento (C27).
    assert classify_provider(_spec(directive), _state(kimi=True, codex=True)) is Provider.CLAUDE


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
# Regra 0: force_main_llm sobrepoe o roteamento normal                         #
# --------------------------------------------------------------------------- #


def test_rule0_force_main_llm_true_ignores_workers():
    # Com comando Kimi-compativel, worker Kimi ativo, mas force_main_llm=True -> CLAUDE
    spec = CommandSpec(name=KIMI_CMD, kind="slash", kimi_eligible=True, force_main_llm=True)
    assert classify_provider(spec, _state(kimi=True, codex=False)) is Provider.CLAUDE


def test_rule0_force_main_llm_true_ignores_codex_worker():
    # Com comando Codex-compativel, worker Codex ativo, mas force_main_llm=True -> CLAUDE
    spec = CommandSpec(name=CODEX_CMD, kind="slash", force_main_llm=True)
    assert classify_provider(spec, _state(kimi=False, codex=True)) is Provider.CLAUDE


def test_rule0_force_main_llm_true_ignores_both_workers():
    # Com comando elegivel a ambos workers, mas force_main_llm=True -> CLAUDE
    spec = CommandSpec(name=CODEX_CMD, kind="slash", kimi_eligible=True, force_main_llm=True)
    assert classify_provider(spec, _state(kimi=True, codex=True)) is Provider.CLAUDE


def test_rule0_force_main_llm_false_respects_kimi_worker():
    # Com force_main_llm=False, o roteamento normal funciona: Kimi worker -> KIMI
    spec = CommandSpec(name=KIMI_CMD, kind="slash", kimi_eligible=True, force_main_llm=False)
    assert classify_provider(spec, _state(kimi=True, codex=False)) is Provider.KIMI


def test_rule0_force_main_llm_false_respects_codex_worker():
    # Com force_main_llm=False, o roteamento normal funciona: Codex worker -> CODEX
    spec = CommandSpec(name=CODEX_CMD, kind="slash", force_main_llm=False)
    assert classify_provider(spec, _state(kimi=False, codex=True)) is Provider.CODEX


def test_rule0_force_main_llm_false_fallback_claude():
    # Com force_main_llm=False e comando nao elegivel -> fallback CLAUDE
    spec = CommandSpec(name=OTHER_CMD, kind="slash", force_main_llm=False)
    assert classify_provider(spec, _state(kimi=True, codex=True)) is Provider.CLAUDE


def test_rule0_force_main_llm_default_is_true():
    # Valor default de force_main_llm e True (comportamento compativel)
    spec = CommandSpec(name=KIMI_CMD, kind="slash", kimi_eligible=True)
    # Nao especifica force_main_llm, deve usar o default True
    assert spec.force_main_llm is True
    # Com worker ativo, mas force_main_llm default=True -> CLAUDE
    assert classify_provider(spec, _state(kimi=True, codex=False)) is Provider.CLAUDE


def test_rule0_is_prompt_true_always_claude():
    # is_prompt=True roteia para CLAUDE independente de workers
    spec = CommandSpec(name=KIMI_CMD, kind="slash", kimi_eligible=True, is_prompt=True)
    assert classify_provider(spec, _state(kimi=True, codex=False)) is Provider.CLAUDE


def test_rule0_is_prompt_true_ignores_codex_worker():
    # is_prompt=True ignora worker Codex
    spec = CommandSpec(name=CODEX_CMD, kind="slash", is_prompt=True)
    assert classify_provider(spec, _state(kimi=False, codex=True)) is Provider.CLAUDE


def test_rule0_is_prompt_true_ignores_both_workers():
    # is_prompt=True ignora ambos workers
    spec = CommandSpec(name=CODEX_CMD, kind="slash", kimi_eligible=True, is_prompt=True)
    assert classify_provider(spec, _state(kimi=True, codex=True)) is Provider.CLAUDE


def test_rule0_is_prompt_true_takes_precedence_over_force_main_llm():
    # is_prompt=True tem precedencia sobre force_main_llm
    spec = CommandSpec(name=CODEX_CMD, kind="slash", is_prompt=True, force_main_llm=False)
    # Mesmo com force_main_llm=False e workers ativos, is_prompt=True -> CLAUDE
    assert classify_provider(spec, _state(kimi=True, codex=True)) is Provider.CLAUDE


def test_rule0_is_prompt_false_respects_kimi_worker():
    # is_prompt=False segue roteamento normal: Kimi worker -> KIMI
    spec = CommandSpec(name=KIMI_CMD, kind="slash", kimi_eligible=True, is_prompt=False)
    assert classify_provider(spec, _state(kimi=True, codex=False)) is Provider.KIMI


def test_rule0_is_prompt_default_is_true():
    # Valor default de is_prompt e True (comportamento compativel)
    spec = CommandSpec(name=KIMI_CMD, kind="slash", kimi_eligible=True)
    # Nao especifica is_prompt, deve usar o default True
    assert spec.is_prompt is True
    # Com worker ativo, mas is_prompt default=True -> CLAUDE
    assert classify_provider(spec, _state(kimi=True, codex=False)) is Provider.CLAUDE


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
# Colisao Main == Worker: regime unico "worker vence" (item 006, gap C7)       #
# --------------------------------------------------------------------------- #
# Ate 2026-08-17 este arquivo travava DOIS regimes contraditorios para a MESMA
# entrada: o legado mandava ao WORKER (contrato de 2026-05-30) e o ramo Router V2
# — atras da conjuncao `SF_LLM_CONFIG_V2` + a flag propria do item 010 — mandava
# ao MAIN. A divergencia foi **REVOGADA pela decisao D3** do item 006 do loop
# `08-17-systemforge-multillm-gaps-refactor`: existe UM regime, e quando o mesmo
# provider ocupa Main e Worker o **worker vence, sempre**, sem condicionar a
# switch nenhum. O ramo V2, o helper `_command_family` e os tres helpers de flag
# do item 010 sairam do codigo de producao; o guard de remocao (para que a flag
# morta nao ressuscite o regime Main-vence) vive em `TestRouterV2FlagRemoved`.
#
# Consequencia estrutural: `classify_provider` nao le NENHUMA feature flag, entao
# estes casos nao precisam mais de processo novo — rodam in-process. O probe em
# subprocesso sobreviveu somente onde ainda prova algo: o guard de remocao, que
# precisa de ambiente controlado no boot para ser honesto.


def _route(cases: list[dict]) -> list[str]:
    """Classifica `cases` in-process: o router e puro e nao le flag nenhuma."""
    out: list[str] = []
    for case in cases:
        spec = _spec(
            case["name"],
            kind=case.get("kind", "slash"),
            kimi_eligible=case.get("kimi_eligible", False),
        )
        state = RoutingState(
            kimi_worker_enabled=case["kimi"],
            codex_worker_enabled=case["codex"],
            main_llm=case["main_llm"],
        )
        out.append(classify_provider(spec, state).value)
    return out


def test_main_kimi_with_kimi_worker_and_kimi_command_routes_to_worker():
    """main=kimi, kimi worker ON, comando kimi -> KIMI (o worker vence).

    Caso outrora chamado `..._routes_to_main`, que afirmava CLAUDE sob o Router
    V2. Regime revogado por D3 (item 006): a colisao Main==Worker tem um unico
    destino, o worker.
    """
    case = {"name": KIMI_CMD, "kimi": True, "codex": True, "main_llm": "kimi"}
    assert _route([case]) == ["kimi"]


def test_main_kimi_with_kimi_worker_and_kimi_eligible_flag_routes_to_worker():
    """main=kimi, `kimi_eligible=True`, kimi worker ON -> KIMI (o worker vence).

    Mesma revogacao (D3, item 006): a elegibilidade por flag do spec entra na
    regra 4b e continua caindo no worker, nao no Main.
    """
    case = {
        "name": OTHER_CMD,
        "kimi_eligible": True,
        "kimi": True,
        "codex": False,
        "main_llm": "kimi",
    }
    assert _route([case]) == ["kimi"]


def test_main_codex_with_codex_worker_and_codex_command_routes_to_worker():
    """main=codex, codex worker ON, comando codex -> CODEX (o worker vence).

    Lado Codex da mesma revogacao (D3, item 006). O comando nao e Kimi-compativel
    e nao carrega `kimi_eligible`, entao a precedencia da regra 6 nao se aplica.
    """
    case = {"name": CODEX_CMD, "kimi": True, "codex": True, "main_llm": "codex"}
    assert _route([case]) == ["codex"]


def test_main_kimi_does_not_affect_codex_command():
    """Main=kimi nao afeta comando codex (familias diferentes) -> CODEX.

    Ja valia nos dois regimes; sobrevive intacto a revogacao de D3 e agora e
    afirmado sem flag alguma.
    """
    case = {"name": CODEX_CMD, "kimi": False, "codex": True, "main_llm": "kimi"}
    assert _route([case]) == ["codex"]


def test_main_codex_does_not_affect_kimi_command():
    """Main=codex nao afeta comando kimi (familias diferentes) -> KIMI.

    Ja valia nos dois regimes; sobrevive intacto a revogacao de D3 e agora e
    afirmado sem flag alguma.
    """
    case = {"name": KIMI_CMD, "kimi": True, "codex": False, "main_llm": "codex"}
    assert _route([case]) == ["kimi"]


def test_no_workers_falls_back_to_claude():
    """Nenhum worker ativo -> CLAUDE, qualquer que seja o Main.

    Antes era `test_v2_without_workers_still_falls_back_to_claude`, e media o
    ramo V2. Com o ramo removido, o early-return legado (regra 3) voltou a ser o
    caminho unico: este teste passa a travar que a conversao do `elif` de volta
    para `if` (ST002 do item 006) preservou o destino em todas as tres formas —
    familia batendo com o Main, familia divergente e comando fora das duas
    whitelists.
    """
    cases = [
        # Familia bate com o Main (antes retornava pela regra de familia do V2).
        {"name": KIMI_CMD, "kimi": False, "codex": False, "main_llm": "kimi"},
        # Familia NAO bate (antes retornava so pelo fallback final).
        {"name": CODEX_CMD, "kimi": False, "codex": False, "main_llm": "kimi"},
        # Comando fora das duas whitelists (familia "unknown").
        {"name": OTHER_CMD, "kimi": False, "codex": False, "main_llm": "claude"},
    ]
    assert _route(cases) == ["claude", "claude", "claude"]


def test_worker_precedence_on_main_worker_collision():
    """Contrato UNICO da colisao Main==Worker: o worker vence, sempre.

    Antes chamado `test_legacy_mode_keeps_worker_precedence_on_main_worker_collision`
    e valido so com as flags ausentes. Depois de D3 (item 006) nao ha "modo
    legado" — este e o contrato, e vale sem depender de flag.
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
    assert _route(cases) == ["kimi", "codex", "kimi"]


# --------------------------------------------------------------------------- #
# Guard de remocao da flag do Router V2 (ST006 do item 006)                    #
# --------------------------------------------------------------------------- #
# Precedente seguido: `TestNoEnvFlag` em tests/test_model_effort_equivalence.py.
# A flag foi REMOVIDA junto com o ramo que ela guardava; o literal so aparece
# aqui, como nome de uma variavel morta que precisa PROVAR que e inerte.

_DEAD_ROUTER_FLAG = "SF_PROVIDER_ROUTER_V2"

# Colisao Main==Worker: a entrada que outrora divergia entre os dois regimes.
_COLLISION_CASE = [{"name": KIMI_CMD, "kimi": True, "codex": True, "main_llm": "kimi"}]

_COLLISION_PROBE = """
import json
import os
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
            # probe que rodasse contra outro `workflow_app` (ou com a variavel
            # perdida no caminho) poderia passar verde por coincidencia.
            "module_file": mod.__file__,
            "global_flag_state": feature_flags.llm_config_v2_state(),
            "dead_flag_env": os.environ.get("SF_PROVIDER_ROUTER_V2"),
            # Superficie: nenhum helper da flag morta pode ter sobrevivido.
            "flag_helpers": [n for n in dir(feature_flags) if "provider_router" in n],
        }
    )
)
"""

# Raiz do workflow-app: o probe roda com este cwd (mesma hermeticidade do
# `_run_probe` de tests/test_command_queue_widget.py).
_WORKFLOW_APP_ROOT = Path(__file__).resolve().parents[1]


def _probe_env(*, global_flag: str | None, dead_flag: str | None) -> dict[str, str]:
    """Ambiente do filho: `None` REMOVE a variavel (estado `absent`)."""
    env = dict(os.environ)
    for var, value in (
        (feature_flags.llm_config_v2_flag_name(), global_flag),
        (_DEAD_ROUTER_FLAG, dead_flag),
    ):
        if value is None:
            env.pop(var, None)
        else:
            env[var] = value
    return env


def _run_collision_probe(*, global_flag: str | None, dead_flag: str | None) -> dict:
    """Classifica a colisao num processo NOVO com o ambiente pedido no boot."""
    result = subprocess.run(
        [sys.executable, "-c", _COLLISION_PROBE, json.dumps(_COLLISION_CASE)],
        capture_output=True,
        text=True,
        env=_probe_env(global_flag=global_flag, dead_flag=dead_flag),
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
    # E o ambiente pedido tem de ter chegado ao processo novo — sem isso, uma
    # variavel perdida no caminho faria o guard medir sempre o mesmo estado.
    assert got["dead_flag_env"] == dead_flag, got
    return got


class TestRouterV2FlagRemoved:
    """`SF_PROVIDER_ROUTER_V2` foi REMOVIDA junto com o ramo Router V2 (D3, item 006).

    Deletar os testes da flag deixaria a porta aberta para a divergencia voltar
    sem ninguem notar. Seguindo o precedente de `TestNoEnvFlag`
    (tests/test_model_effort_equivalence.py), eles viram guard de remocao: a
    variavel pode existir com qualquer valor no boot que o destino da colisao
    Main==Worker nao muda, e nenhum leitor dela sobrevive na superficie publica.
    """

    @pytest.mark.parametrize(
        "global_flag,dead_flag",
        [
            ("1", None),  # global ligado, variavel morta ausente
            (None, "1"),  # variavel morta em "1", global ausente
            ("0", "1"),  # variavel morta em "1", global explicitamente desligado
            ("1", "0"),  # global ligado, variavel morta em "0"
            ("1", "1"),  # a antiga conjuncao que ligava o regime Main-vence
            ("true", "1"),  # valor nao reconhecido no global (sem casefold/strip)
            ("1", " 1 "),  # valor nao reconhecido na variavel morta (sem strip)
            ("1", ""),  # variavel morta vazia
            ("1", "true"),  # variavel morta com valor arbitrario
            (None, None),  # ambas ausentes (default real de producao)
        ],
        ids=[
            "global-on-dead-absent",
            "dead-on-global-absent",
            "dead-on-global-off",
            "global-on-dead-off",
            "old-conjunction-both-on",
            "global-unrecognized",
            "dead-unrecognized",
            "dead-empty",
            "dead-true",
            "both-absent",
        ],
    )
    def test_env_var_does_not_change_the_collision(self, global_flag, dead_flag):
        """Qualquer estado da variavel morta no boot: a colisao continua no worker."""
        got = _run_collision_probe(global_flag=global_flag, dead_flag=dead_flag)
        assert got["providers"] == ["kimi"], got
        # A variavel morta tambem nao pode ter ressuscitado nenhum helper.
        assert got["flag_helpers"] == [], got

    def test_feature_flags_exposes_no_router_v2_reader(self):
        """Os tres helpers do item 010 sairam de `feature_flags` (modulo e `__all__`)."""
        for name in (
            "provider_router_v2_enabled",
            "provider_router_v2_state",
            "provider_router_v2_flag_name",
        ):
            assert not hasattr(feature_flags, name), name
            assert name not in feature_flags.__all__, name
        assert not [n for n in dir(feature_flags) if "provider_router" in n]

    def test_provider_router_exposes_no_flag_reader(self):
        """O router ficou puro: nenhum leitor de flag e nenhum helper de familia do V2."""
        for name in (
            "provider_router_v2_enabled",
            "provider_router_v2_state",
            "provider_router_v2_flag_name",
            "_command_family",
        ):
            assert not hasattr(provider_router_module, name), name


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
