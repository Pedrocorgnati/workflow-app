"""Invariantes dos mapas de flags MCP (`config/llm_flags.py`).

`_flag_maps_invariant_violations` e funcao pura: recebe os mapas por
parametro e devolve a lista de violacoes. O import do modulo a chama com os
mapas `_FULL_*` e levanta `AssertionError` se sobrar violacao, com `raise`:
um `assert` sumiria sob `python -O` e o mapa incoerente viraria flag no-op em
silencio.

Cada regra ganha aqui as suas mutacoes: o teste injeta UM mapa quebrado,
mantem os demais nos defaults e exige a violacao daquela regra. Os testes de
subprocesso provam o guard no import real (inclusive com `-O`) e o recorte
dos mapas derivados nos dois regimes de `SF_LLM_FLAGS_V2`.
"""

from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from workflow_app.config import llm_flags

_WORKFLOW_APP_ROOT = Path(__file__).resolve().parents[1]
_LLM_FLAGS_PATH = _WORKFLOW_APP_ROOT / "src" / "workflow_app" / "config" / "llm_flags.py"

# Switches que mudam o que o import de `llm_flags` enxerga. Saem do ambiente
# de todo subprocesso por default: o shell do operador nao entra no cenario.
_SWITCHES = ("SF_LLM_FLAGS_V2", "SF_MIMO_V1")

# Uma mutacao recebe o modulo e devolve os kwargs da funcao pura; os mapas
# que ela nao cita ficam nos defaults `_FULL_*`.
Mutation = Callable[[ModuleType], dict[str, Any]]


def _without(mapping: Mapping[str, Any], key: str) -> dict[str, Any]:
    return {k: v for k, v in mapping.items() if k != key}


def _assert_rule_fires(mutation: Mutation, expected: str) -> None:
    violations = llm_flags._flag_maps_invariant_violations(**mutation(llm_flags))
    assert violations, "a mutacao passou sem violacao"
    assert any(expected in violation for violation in violations), violations


def _run_python(args: list[str], env_overrides: dict[str, str | None]) -> dict:
    """Roda o interpretador em processo novo e devolve o JSON do stdout.

    Valor `None` remove a variavel do filho. `src` entra no `PYTHONPATH` para
    o probe nao depender de como o pytest foi chamado.
    """
    env = os.environ.copy()
    for name in _SWITCHES:
        env.pop(name, None)
    for key, value in env_overrides.items():
        if value is None:
            env.pop(key, None)
        else:
            env[key] = value
    src = str(_WORKFLOW_APP_ROOT / "src")
    env["PYTHONPATH"] = os.pathsep.join(p for p in (src, env.get("PYTHONPATH")) if p)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(
        [sys.executable, *args],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(_WORKFLOW_APP_ROOT),
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, (
        f"probe falhou (rc={result.returncode})\n"
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    return json.loads(result.stdout)


# ======================================================================
# Mapas reais
# ======================================================================


def test_full_maps_have_no_violations():
    """Os mapas `_FULL_*` sao coerentes, e o guard do import viu o mesmo."""
    assert llm_flags._flag_maps_invariant_violations() == []
    assert llm_flags._INVARIANT_VIOLATIONS == []


# ======================================================================
# Uma mutacao por regra
# ======================================================================


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        pytest.param(
            lambda lf: {"thinking": (*lf._THINKING_FLAG_ORDER, "--qwen")},
            "literal repetido nas colunas: ['--qwen']",
            id="entre-colunas",
        ),
        pytest.param(
            lambda lf: {"execution": (*lf._EXECUTION_FLAG_ORDER, "--grok")},
            "literal repetido nas colunas: ['--grok']",
            id="na-mesma-coluna",
        ),
    ],
)
def test_duplicate_literal_is_a_violation(mutation: Mutation, expected: str):
    """Literal unico: nem repetido numa coluna, nem nas duas."""
    _assert_rule_fires(mutation, expected)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        pytest.param(
            lambda lf: {"literal_to_main": _without(lf._FULL_FLAG_LITERAL_TO_MAIN, "--mimo-pro")},
            "literal_to_main diverge das colunas em ['--mimo-pro']",
            id="sem-mimo-pro",
        ),
        pytest.param(
            lambda lf: {"literal_to_main": {**lf._FULL_FLAG_LITERAL_TO_MAIN, "--gpt": "openai"}},
            "literal_to_main diverge das colunas em ['--gpt']",
            id="literal-desconhecido",
        ),
    ],
)
def test_literal_to_main_must_match_the_columns(mutation: Mutation, expected: str):
    """Toda flag das colunas tem Main, e nenhum Main aponta para flag fora delas."""
    _assert_rule_fires(mutation, expected)


def test_t1_must_accept_every_literal():
    """T1 (Claude) aceita o conjunto cheio."""
    _assert_rule_fires(
        lambda lf: {
            "by_terminal": {
                **lf._FULL_FLAGS_BY_TERMINAL,
                "T1": lf._FULL_FLAGS_BY_TERMINAL["T1"] - {"--mimo-pro"},
            }
        },
        "T1 diverge das colunas em ['--mimo-pro']",
    )


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        pytest.param(
            lambda lf: {
                "by_terminal": {
                    **lf._FULL_FLAGS_BY_TERMINAL,
                    "T2": lf._FULL_FLAGS_BY_TERMINAL["T2"] - {"--mimo-pro"},
                }
            },
            "T2 diverge do Main das flags em ['--mimo-pro']",
            id="t2-sem-mimo-pro",
        ),
        pytest.param(
            lambda lf: {
                "by_terminal": {
                    **lf._FULL_FLAGS_BY_TERMINAL,
                    "T3": lf._FULL_FLAGS_BY_TERMINAL["T3"] | {"--kimi"},
                }
            },
            "T3 diverge do Main das flags em ['--kimi']",
            id="kimi-no-t3",
        ),
    ],
)
def test_t2_and_t3_follow_the_main_of_each_literal(mutation: Mutation, expected: str):
    """O literal esta no terminal se e so se o Main dele esta."""
    _assert_rule_fires(mutation, expected)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        pytest.param(
            lambda lf: {"redundant": _without(lf._FULL_REDUNDANT_FLAG_MAINS, "--mimo-pro")},
            "redundant diverge de literal_to_main em [('--mimo-pro', 'mimo')]",
            id="sem-mimo-pro",
        ),
        pytest.param(
            lambda lf: {"redundant": {**lf._FULL_REDUNDANT_FLAG_MAINS, "--opus": "claude"}},
            "redundant diverge de literal_to_main em [('--opus', 'claude')]",
            id="com-variante-claude",
        ),
    ],
)
def test_redundant_is_literal_to_main_without_claude(mutation: Mutation, expected: str):
    """Variante de Claude escolhe raciocinio, nao CLI: nunca e redundante."""
    _assert_rule_fires(mutation, expected)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        pytest.param(
            lambda lf: {"legacy_order": (*lf._LEGACY_FLAG_ORDER, "--gpt")},
            "roster legado com literal fora das colunas: ['--gpt']",
            id="literal-desconhecido",
        ),
        pytest.param(
            lambda lf: {"legacy_order": (*lf._LEGACY_FLAG_ORDER, "--codex")},
            "roster legado com literal repetido",
            id="literal-repetido",
        ),
        pytest.param(
            lambda lf: {"legacy_order": ("--codex", "--kimi", "--mimo")},
            "--kimi antes de --mimo no roster legado (MiMo > Kimi)",
            id="kimi-antes-da-mimo",
        ),
    ],
)
def test_legacy_roster_must_be_coherent(mutation: Mutation, expected: str):
    """Roster legado: sem repeticao, dentro das colunas, MiMo antes do Kimi."""
    _assert_rule_fires(mutation, expected)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        pytest.param(
            lambda lf: {
                "supersedes": {
                    "--mimo": frozenset({"--kimi"}),
                    "--mimo-pro": frozenset({"--kimi"}),
                }
            },
            "--mimo-pro supersede --kimi de outra coluna (par cruzado)",
            id="par-cruzado",
        ),
        pytest.param(
            lambda lf: {"supersedes": {**lf._FULL_MIMO_SUPERSEDES, "--qwen": frozenset({"--kimi"})}},
            "chave de supersede --qwen nao e literal MiMo das colunas",
            id="chave-com-main-errado",
        ),
        pytest.param(
            lambda lf: {
                "supersedes": {**lf._FULL_MIMO_SUPERSEDES, "--mimo": frozenset({"--kimi", "--qwen"})}
            },
            "--mimo supersede --qwen, que nao e literal Kimi",
            id="valor-com-main-errado",
        ),
        pytest.param(
            lambda lf: {"supersedes": {"--mimo": lf._FULL_MIMO_SUPERSEDES["--mimo"]}},
            "chaves de supersede divergem dos literais MiMo em ['--mimo-pro']",
            id="sem-par-do-mimo-pro",
        ),
        pytest.param(
            lambda lf: {"supersedes": {**lf._FULL_MIMO_SUPERSEDES, "--mimo": frozenset()}},
            "supersede de --mimo tem que tirar o Kimi da coluna execution ['--kimi'], nao []",
            id="par-vazio",
        ),
        pytest.param(
            lambda lf: {"execution": ("--grok", "--sonnet", "--kimi", "--mimo", "--qwen", "--codex")},
            "--kimi renderiza antes de --mimo na coluna execution (MiMo > Kimi)",
            id="kimi-antes-na-execution",
        ),
        pytest.param(
            lambda lf: {
                "thinking": (
                    "--fable", "--opus", "--codex-ultra", "--kimi-k3", "--mimo-pro",
                    "--grok-xhigh",
                )
            },
            "--kimi-k3 renderiza antes de --mimo-pro na coluna thinking (MiMo > Kimi)",
            id="kimi-k3-antes-na-thinking",
        ),
        pytest.param(
            lambda lf: {"mimo_literals": frozenset({"--mimo"})},
            "literais MiMo divergem de literal_to_main em ['--mimo-pro']",
            id="literais-mimo-sem-mimo-pro",
        ),
    ],
)
def test_mimo_supersede_is_paired_per_column(mutation: Mutation, expected: str):
    """MiMo > Kimi pareado: cada literal MiMo tira so o Kimi da propria coluna."""
    _assert_rule_fires(mutation, expected)


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        pytest.param(
            lambda lf: {
                "autoproxy": {
                    **lf._FULL_AUTOPROXY_FLAGS_BY_MAIN,
                    "mimo": lf._FULL_AUTOPROXY_FLAGS_BY_MAIN["mimo"] | {"--mimo"},
                }
            },
            "auto-proxy de mimo inclui --mimo, redundante sob mimo",
            id="flag-redundante",
        ),
        pytest.param(
            lambda lf: {
                "autoproxy": {
                    **lf._FULL_AUTOPROXY_FLAGS_BY_MAIN,
                    "kimi": lf._FULL_AUTOPROXY_FLAGS_BY_MAIN["kimi"] | {"--gpt"},
                }
            },
            "auto-proxy de kimi com literal fora das colunas: --gpt",
            id="literal-desconhecido",
        ),
        pytest.param(
            lambda lf: {
                "autoproxy": {**lf._FULL_AUTOPROXY_FLAGS_BY_MAIN, "mimo": frozenset({"--kimi"})}
            },
            "Main mimo nao desabilita ['--kimi-k3'] (MiMo > Kimi)",
            id="main-mimo-sem-kimi-k3",
        ),
        pytest.param(
            lambda lf: {"autoproxy": _without(lf._FULL_AUTOPROXY_FLAGS_BY_MAIN, "mimo")},
            "Main mimo nao desabilita ['--kimi', '--kimi-k3'] (MiMo > Kimi)",
            id="sem-main-mimo",
        ),
    ],
)
def test_autoproxy_table_is_closed_and_covers_main_mimo(mutation: Mutation, expected: str):
    """Auto-proxy: literal das colunas, nunca redundante, Main mimo tira o Kimi."""
    _assert_rule_fires(mutation, expected)


# ======================================================================
# Guard do import
# ======================================================================


def test_import_guards_raise_instead_of_assert():
    """Guard de import com `assert` some sob `python -O`; tem que ser `raise`."""
    tree = ast.parse(_LLM_FLAGS_PATH.read_text(encoding="utf-8"))
    asserts = [node.lineno for node in tree.body if isinstance(node, ast.Assert)]
    assert asserts == [], f"assert no nivel de modulo de llm_flags.py: linhas {asserts}"
    guarded = [
        ast.unparse(node.test)
        for node in tree.body
        if isinstance(node, ast.If)
        and any(
            isinstance(stmt, ast.Raise)
            and isinstance(stmt.exc, ast.Call)
            and isinstance(stmt.exc.func, ast.Name)
            and stmt.exc.func.id == "AssertionError"
            for stmt in node.body
        )
    ]
    assert "_INVARIANT_VIOLATIONS" in guarded, guarded


# Executa o fonte de `llm_flags.py` com UMA linha extra logo antes de uma
# ancora e conta o que aconteceu. A ancora default e a guarda dos mapas
# `_FULL_*`; o terceiro argumento troca a ancora (guarda do roster vigente).
# Sem `assert` no probe: ele roda sob `-O`.
_GUARD_PROBE = r'''import json
import sys
import types
from pathlib import Path

path = Path(sys.argv[1])
mutation = sys.argv[2]
anchor = (
    sys.argv[3]
    if len(sys.argv) > 3
    else "_INVARIANT_VIOLATIONS: list[str] = _flag_maps_invariant_violations()"
)
source = path.read_text(encoding="utf-8")
outcome = {"anchors": source.count(anchor), "optimize": sys.flags.optimize}
if outcome["anchors"] == 1:
    module = types.ModuleType("llm_flags_mutado")
    mutated = source.replace(anchor, mutation + "\n" + anchor)
    try:
        exec(compile(mutated, str(path), "exec"), module.__dict__)
    except AssertionError as exc:
        outcome["raised"] = str(exc)
    else:
        outcome["raised"] = None
print(json.dumps(outcome, sort_keys=True))
'''


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        pytest.param("pass", None, id="mapas-intactos"),
        pytest.param(
            '_FULL_FLAGS_BY_TERMINAL["T3"] = _FULL_FLAGS_BY_TERMINAL["T3"] | {"--kimi"}',
            "T3 diverge do Main das flags em ['--kimi']",
            id="kimi-no-t3",
        ),
    ],
)
def test_import_guard_survives_optimized_mode(mutation: str, expected: str | None):
    """Mapa incoerente derruba o import mesmo sob `python -O`.

    O controle (`pass`) prova que o fonte intacto importa sob `-O`; a mutacao
    prova que o guard enxerga o mapa do modulo, nao uma copia.
    """
    got = _run_python(
        ["-O", "-c", _GUARD_PROBE, str(_LLM_FLAGS_PATH), mutation],
        {"SF_LLM_FLAGS_V2": "1"},
    )
    assert got["anchors"] == 1, got
    assert got["optimize"] == 1, got
    assert got["raised"] == expected, got


# A mutacao entra logo antes da linha que copia a ordem do regime: o roster
# mutado e o que a guarda do conjunto vigente enxerga.
_REGIME_GUARD_ANCHOR = "_FLAG_CANONICAL_ORDER: tuple[str, ...] = _REGIME_ORDER"
_REGIME_GUARD_MESSAGE = "roster do regime vigente invalido: "


@pytest.mark.parametrize(
    ("mutation", "fires"),
    [
        pytest.param("pass", False, id="roster-intacto"),
        pytest.param(
            "_REGIME_ORDER = _REGIME_ORDER + (_REGIME_ORDER[0],)",
            True,
            id="literal-repetido",
        ),
        pytest.param(
            '_REGIME_ORDER = _REGIME_ORDER + ("--claude",)',
            True,
            id="literal-fora-das-colunas",
        ),
    ],
)
@pytest.mark.parametrize(
    "llm_flags_v2",
    [pytest.param(None, id="legado"), pytest.param("1", id="v2")],
)
def test_regime_roster_guard_fires_under_optimized_mode(
    mutation: str, fires: bool, llm_flags_v2: str | None
):
    """A guarda do roster vigente dispara de verdade, nos dois regimes.

    A guarda antiga comparava a ordem com o conjunto derivado dela mesma e
    nenhuma mutacao a fazia disparar. A atual olha o que a estrutura nao
    garante: literal repetido (sumiria do conjunto, nao da ordem, e sairia
    duas vezes no sufixo T1) e literal fora das colunas (MF-02: nao existe
    `--claude`). O controle (`pass`) prova que o roster intacto importa.
    """
    got = _run_python(
        [
            "-O", "-c", _GUARD_PROBE, str(_LLM_FLAGS_PATH), mutation,
            _REGIME_GUARD_ANCHOR,
        ],
        {"SF_LLM_FLAGS_V2": llm_flags_v2},
    )
    assert got["anchors"] == 1, got
    assert got["optimize"] == 1, got
    if fires:
        assert str(got["raised"]).startswith(_REGIME_GUARD_MESSAGE), got
    else:
        assert got["raised"] is None, got


# ======================================================================
# Mapas derivados por regime
# ======================================================================


_DERIVED_PROBE = '''import json
from workflow_app.config import llm_flags as lf

supported = lf._SUPPORTED_MCP_FLAGS
cited = set(lf._FLAG_CANONICAL_ORDER) | set(lf._FLAG_LITERAL_TO_MAIN)
cited |= set(lf._REDUNDANT_FLAG_MAINS)
for flags in lf._FLAGS_BY_TERMINAL.values():
    cited |= flags
for mimo, losers in lf._MIMO_SUPERSEDES.items():
    cited |= {mimo} | losers
for flags in lf._AUTOPROXY_FLAGS_BY_MAIN.values():
    cited |= flags
print(json.dumps({
    "violations": lf._INVARIANT_VIOLATIONS,
    "outside": sorted(cited - supported),
    "order": list(lf._FLAG_CANONICAL_ORDER),
    "supported": sorted(supported),
    "t1": sorted(lf._FLAGS_BY_TERMINAL["T1"]),
    "mapped": sorted(lf._FLAG_LITERAL_TO_MAIN),
    "empty_rules": sorted(
        [k for k, v in lf._MIMO_SUPERSEDES.items() if not v]
        + [k for k, v in lf._AUTOPROXY_FLAGS_BY_MAIN.items() if not v]
    ),
}, sort_keys=True))
'''


@pytest.mark.parametrize(
    "mimo_v1",
    [
        pytest.param(None, id="mimo-ausente"),
        pytest.param("0", id="mimo-0"),
        pytest.param("1", id="mimo-1"),
    ],
)
@pytest.mark.parametrize(
    ("llm_flags_v2", "roster"),
    [
        pytest.param(None, llm_flags._LEGACY_FLAG_ORDER, id="legado"),
        pytest.param("1", llm_flags._FULL_FLAG_CANONICAL_ORDER, id="v2"),
    ],
)
def test_derived_maps_never_cite_literals_outside_the_regime(
    llm_flags_v2: str | None, roster: tuple[str, ...], mimo_v1: str | None
):
    """Nenhum mapa derivado cita literal fora do conjunto vigente.

    Supersede e auto-proxy sao recortados ao regime: no legado o par do
    `--mimo-pro` some junto com ele, e regra vazia nao sobra na tabela. O
    regime e funcao so de `SF_LLM_FLAGS_V2`: o switch do CLI MiMo (contrato
    D3) varia aqui e o import segue limpo, com o mesmo roster.
    """
    got = _run_python(
        ["-c", _DERIVED_PROBE],
        {"SF_LLM_FLAGS_V2": llm_flags_v2, "SF_MIMO_V1": mimo_v1},
    )
    assert got["violations"] == [], got
    # Ordem de render exata (nao so o conjunto): e ela que o painel e o
    # sufixo T1 percorrem.
    assert got["order"] == list(roster), got
    assert got["supported"] == sorted(roster), got
    assert got["outside"] == [], got
    assert got["t1"] == got["supported"], got
    assert got["mapped"] == got["supported"], got
    assert got["empty_rules"] == [], got
