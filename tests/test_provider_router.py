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

import pytest

from workflow_app.command_queue.codex_whitelist import is_codex_compatible
from workflow_app.command_queue.kimi_whitelist import is_kimi_compatible
from workflow_app.command_queue.provider_router import (
    Provider,
    RoutingState,
    classify_provider,
    normalize_command_name,
)
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
