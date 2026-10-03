"""MiMo nas flags MCP: `--mimo`, `--mimo-pro` e o painel de flags.

Trava o comportamento da area F2 do plano 10-02 (mimo-llm-paralela):

- supersede PAREADO por coluna: `--mimo` tira o `--kimi` e `--mimo-pro` tira
  o `--kimi-k3`, nunca o par cruzado;
- auto-proxy por tabela (`_AUTOPROXY_FLAGS_BY_MAIN`): Main kimi derruba os
  literais Codex (C-43) e Main mimo derruba os literais Kimi (MiMo > Kimi),
  cada um com o seu motivo no tooltip (Zero Silencio);
- contrato D3: o switch das superficies do CLI MiMo nao toca nas flags. Os
  literais MiMo usam o servidor MCP, entao existem, ficam visiveis e
  habilitados com o switch ausente, "0" ou "1"; o regime depende so de
  `SF_LLM_FLAGS_V2`;
- desabilitada = fora do payload T1: `checked_flags` nunca devolve flag
  cinza (auto-proxy, redundante ou kill-switch), sem desmarcar nada, e a
  selecao volta quando o Main volta a aceitar a flag.

Os mapas sao boot-frozen. Trocar de regime no processo exige recarregar
`feature_flags` -> `llm_flags` -> `flags_panel`, com o ambiente gravado e
restaurado direto em `os.environ`: o teardown do monkeypatch roda depois do
`finally` do helper e deixaria os modulos recarregados no ambiente do teste.
"""

from __future__ import annotations

import ast
import importlib
import os
from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from types import ModuleType

import pytest

from workflow_app.config import feature_flags, llm_flags
from workflow_app.llm_config import flags_panel

_WORKFLOW_APP_ROOT = Path(__file__).resolve().parents[1]

_ENV_LLM_FLAGS_V2 = "SF_LLM_FLAGS_V2"
_ENV_MIMO_V1 = "SF_MIMO_V1"
_ENV_DELEGATION = "SYSTEMFORGE_DELEGATION_FLAGS_NONCLAUDE"

# Main e terminais de cada literal, como o tooltip os anuncia. Vale nos dois
# regimes: o legado so tem um subconjunto destas linhas.
_TOOLTIP_TARGETS: dict[str, tuple[str, str]] = {
    "--fable": ("claude", "T1"),
    "--opus": ("claude", "T1"),
    "--codex-ultra": ("codex", "T1, T3"),
    "--mimo-pro": ("mimo", "T1, T2"),
    "--kimi-k3": ("kimi", "T1, T2"),
    "--grok-xhigh": ("grok", "T1, T3"),
    "--grok": ("grok", "T1, T3"),
    "--sonnet": ("claude", "T1"),
    "--mimo": ("mimo", "T1, T2"),
    "--kimi": ("kimi", "T1, T2"),
    "--qwen": ("qwen", "T1, T2"),
    "--codex": ("codex", "T1, T3"),
}

_LEGACY_ROSTER = frozenset({"--codex", "--mimo", "--kimi"})
_V2_ROSTER = frozenset(_TOOLTIP_TARGETS)

_REGIMES = [
    pytest.param(None, _LEGACY_ROSTER, id="legado"),
    pytest.param("1", _V2_ROSTER, id="v2"),
]

_DEFAULT_TOOLTIP = (
    "Quando marcado, anexa {flag} ao label dos itens T1 (Claude). "
    "Nunca afeta /clear, /model, /effort, local-action nem itens worker."
)

# Linha extra de cada lado do par MiMo > Kimi. Nenhum outro literal ganha
# texto de precedencia, e nenhum par cruza de coluna.
_PAIR_LINES: dict[str, str] = {
    "--mimo": "Vence o --kimi quando os dois estao marcados.",
    "--mimo-pro": "Vence o --kimi-k3 quando os dois estao marcados.",
    "--kimi": (
        "Se --mimo tambem estiver marcado, a MiMo vence e o --kimi sai do "
        "payload (MiMo > Kimi)."
    ),
    "--kimi-k3": (
        "Se --mimo-pro tambem estiver marcado, a MiMo vence e o --kimi-k3 sai "
        "do payload (MiMo > Kimi)."
    ),
}

# Texto do `--codex` sob Main Kimi antes da tabela de auto-proxy. A tabela
# nova nao pode mudar um byte dele: o loop legado do widget mostra o mesmo.
_KIMI_CODEX_TOOLTIP = (
    "--codex desabilitado sob Main Kimi: as skills de provider do lado Kimi "
    "sao auto-proxy, entao a flag viraria auto-consulta silenciosa em vez de "
    "segunda opiniao explicita. Para pedir Codex de forma explicita, troque "
    "o Main."
)

# Flags desabilitadas por Main (redundancia + auto-proxy), por regime.
_V2_DISABLED_BY_MAIN: dict[str, frozenset[str]] = {
    "claude": frozenset(),
    "mimo": frozenset({"--mimo", "--mimo-pro", "--kimi", "--kimi-k3"}),
    "kimi": frozenset({"--kimi", "--kimi-k3", "--codex", "--codex-ultra"}),
    "codex": frozenset({"--codex", "--codex-ultra"}),
    "qwen": frozenset({"--qwen"}),
    "grok": frozenset({"--grok", "--grok-xhigh"}),
}
_LEGACY_DISABLED_BY_MAIN: dict[str, frozenset[str]] = {
    "claude": frozenset(),
    "mimo": frozenset({"--mimo", "--kimi"}),
    "kimi": frozenset({"--kimi", "--codex"}),
    "codex": frozenset({"--codex"}),
    "qwen": frozenset(),
    "grok": frozenset(),
}

# Passa por toda transicao que poderia deixar um disable grudado: entra e sai
# de Main mimo a partir de cada vizinho, e termina em claude.
_MAIN_WALK = (
    "claude", "mimo", "kimi", "mimo", "codex", "mimo", "claude",
    "kimi", "claude", "qwen", "mimo", "grok", "mimo", "claude",
)


def _expected_enabled_tooltip(flag: str) -> str:
    main, terminals = _TOOLTIP_TARGETS[flag]
    lines = [_DEFAULT_TOOLTIP.format(flag=flag), f"Delega para {main}. Aceita em: {terminals}."]
    if flag in _PAIR_LINES:
        lines.append(_PAIR_LINES[flag])
    return "\n".join(lines)


def _disabled(panel) -> frozenset[str]:
    return frozenset(flag for flag, chk in panel._checkboxes.items() if not chk.isEnabled())


def _check(panel, flags) -> None:
    for flag in flags:
        panel.checkbox(flag).setChecked(True)


def _tooltips(panel) -> dict[str, str]:
    return {flag: chk.toolTip() for flag, chk in panel._checkboxes.items()}


def _apply_env(values: Mapping[str, str | None]) -> None:
    for name, value in values.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value


@contextmanager
def _flags_regime(
    *,
    llm_flags_v2: str | None,
    mimo_v1: str | None = None,
    delegation: str | None = None,
) -> Iterator[ModuleType]:
    """Recarrega a cadeia de flags sob o ambiente pedido e devolve `flags_panel`.

    `None` remove a variavel. O kill-switch de delegacao fica ausente por
    default (paridade ligada), para o shell do operador nao entrar no cenario.
    O `finally` devolve o ambiente anterior e recarrega a cadeia de novo.
    """
    wanted = {
        _ENV_LLM_FLAGS_V2: llm_flags_v2,
        _ENV_MIMO_V1: mimo_v1,
        _ENV_DELEGATION: delegation,
    }
    previous = {name: os.environ.get(name) for name in wanted}

    def _reload_chain() -> None:
        importlib.reload(feature_flags)
        importlib.reload(llm_flags)
        importlib.reload(flags_panel)

    try:
        _apply_env(wanted)
        _reload_chain()
        yield flags_panel
    finally:
        _apply_env(previous)
        _reload_chain()


# ======================================================================
# Mapas puros
# ======================================================================


def test_mimo_switch_trio_is_public_in_feature_flags():
    """O switch do CLI MiMo ganha o trio completo no `__all__` do modulo.

    O `__init__` do pacote nao o reexporta (censo em
    `test_kill_switches_item005.py`).
    """
    assert {"mimo_v1_enabled", "mimo_v1_flag_name", "mimo_v1_state"} <= set(
        feature_flags.__all__
    )


def test_mimo_supersedes_its_kimi_pair_per_column():
    """`--mimo` tira o `--kimi`; `--mimo-pro` tira o `--kimi-k3`; nada cruzado."""
    assert llm_flags.MIMO_FLAG == "--mimo"
    assert llm_flags.MIMO_PRO_FLAG == "--mimo-pro"
    assert llm_flags._FULL_MIMO_SUPERSEDES == {
        "--mimo": frozenset({"--kimi"}),
        "--mimo-pro": frozenset({"--kimi-k3"}),
    }
    # Alias de compatibilidade que so as rules (llm-routing-div.md,
    # llm-flags.md) ainda citam: e o par da coluna execution, o mesmo objeto.
    # Nenhum consumidor em src o le; o render usa `_MIMO_SUPERSEDES` (guard em
    # `test_only_llm_flags_names_the_execution_only_alias`).
    assert llm_flags.MIMO_SUPERSEDES_KIMI == frozenset({"--kimi"})
    assert llm_flags.MIMO_SUPERSEDES_KIMI is llm_flags._FULL_MIMO_SUPERSEDES["--mimo"]


def test_legacy_roster_keeps_mimo_and_leaves_the_pro_pair_out():
    """`--mimo` substitui o `--kimi` nos dois regimes; o par pro e so do v2."""
    assert llm_flags._LEGACY_MCP_FLAGS == frozenset(llm_flags._LEGACY_FLAG_ORDER)
    assert llm_flags._LEGACY_FLAG_ORDER == ("--codex", "--mimo", "--kimi")
    assert llm_flags._LEGACY_MCP_FLAGS.isdisjoint({"--mimo-pro", "--kimi-k3"})


def test_autoproxy_tables_disable_kimi_under_main_mimo():
    """Auto-proxy por tabela: Main kimi tira o Codex, Main mimo tira o Kimi."""
    assert llm_flags._FULL_AUTOPROXY_FLAGS_BY_MAIN == {
        "kimi": frozenset({"--codex", "--codex-ultra"}),
        "mimo": frozenset({"--kimi", "--kimi-k3"}),
    }


def test_autoproxy_tooltip_keeps_the_kimi_text_byte_for_byte():
    """Sob Main kimi o texto do `--codex` nao mudou; o do `--codex-ultra` se nomeia."""
    assert flags_panel.autoproxy_tooltip("--codex", "kimi") == _KIMI_CODEX_TOOLTIP
    ultra = flags_panel.autoproxy_tooltip("--codex-ultra", "kimi")
    assert ultra.startswith("--codex-ultra desabilitado sob Main Kimi: ")
    assert ultra.replace("--codex-ultra", "--codex", 1) == _KIMI_CODEX_TOOLTIP


@pytest.mark.parametrize("flag", ["--kimi", "--kimi-k3"])
def test_autoproxy_tooltip_under_main_mimo_names_the_precedence(flag: str):
    text = flags_panel.autoproxy_tooltip(flag, "mimo")
    assert text.startswith(f"{flag} desabilitado sob Main MiMo: MiMo > Kimi (2026-10-02). ")
    assert text.endswith("Para pedir Kimi de forma explicita, troque o Main.")


def test_every_autoproxy_main_has_its_own_reason():
    """Main novo na tabela sem texto proprio cairia no tooltip generico."""
    assert flags_panel.autoproxy_tooltip("--qwen", "grok") == "--qwen desabilitado sob Main grok."
    for main, flags in llm_flags._FULL_AUTOPROXY_FLAGS_BY_MAIN.items():
        for flag in flags:
            text = flags_panel.autoproxy_tooltip(flag, main)
            assert text.startswith(f"{flag} desabilitado sob Main "), (main, flag)
            assert text != f"{flag} desabilitado sob Main {main}.", (main, flag)


@pytest.mark.parametrize(
    "relpath",
    [
        "src/workflow_app/config/llm_flags.py",
        "src/workflow_app/llm_config/flags_panel.py",
    ],
)
def test_flag_modules_never_consult_the_mimo_cli_switch(relpath: str):
    """D3: o switch do CLI MiMo nao entra no conjunto de flags nem no painel.

    So nomes de codigo contam (import, nome, atributo): docstring e
    comentario podem citar o switch para dizer que ele NAO participa.
    """
    tree = ast.parse((_WORKFLOW_APP_ROOT / relpath).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.alias):
            names.update(filter(None, (node.name, node.asname)))
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    assert sorted(name for name in names if "mimo_v1" in name.lower()) == []


def test_only_llm_flags_names_the_execution_only_alias():
    """So `config/llm_flags.py` nomeia o alias `MIMO_SUPERSEDES_KIMI`.

    O alias carrega so o par da coluna execution: um consumidor do sufixo T1
    que filtrasse por ele deixaria `--mimo-pro` e `--kimi-k3` juntos no
    payload do regime v2. Painel, `render_with_mcp_flags` e o loop legado do
    widget leem os pares de `_MIMO_SUPERSEDES`; o alias fica so para as rules
    que ainda o citam. Varre o pacote importado; contam nomes de codigo e a
    string exata (`getattr`), nunca docstring. Achar a propria definicao
    prova que a varredura enxerga o nome.
    """
    alias = "MIMO_SUPERSEDES_KIMI"
    package = Path(llm_flags.__file__).resolve().parents[1]
    sources = {path.relative_to(package).as_posix(): path for path in package.rglob("*.py")}
    assert {
        "llm_config/flags_panel.py",
        "command_queue/command_item_widget.py",
        "command_queue/command_queue_widget.py",
    } <= set(sources)
    holders: dict[str, list[int]] = {}
    for rel, path in sorted(sources.items()):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.alias):
                name = node.name
            elif isinstance(node, ast.Name):
                name = node.id
            elif isinstance(node, ast.Attribute):
                name = node.attr
            elif isinstance(node, ast.Constant):
                name = node.value
            else:
                continue
            if name == alias:
                holders.setdefault(rel, []).append(node.lineno)
    assert set(holders) == {"config/llm_flags.py"}, holders


# ======================================================================
# Painel de flags
# ======================================================================


@pytest.mark.parametrize(
    ("mimo_v1", "state"),
    [
        pytest.param(None, "absent", id="mimo-ausente"),
        pytest.param("0", "off", id="mimo-0"),
        pytest.param("1", "on", id="mimo-1"),
    ],
)
@pytest.mark.parametrize(("llm_flags_v2", "roster"), _REGIMES)
def test_mimo_cli_switch_never_touches_the_flag_panel(
    qapp, llm_flags_v2: str | None, roster: frozenset[str], mimo_v1: str | None, state: str
):
    """Contrato D3: switch ausente, "0" ou "1" da o mesmo painel.

    O switch gateia so o radio Main, o worker T2 e o botao `mimod`. Os
    literais MiMo continuam no painel, visiveis, habilitados e no payload
    sob Main claude. `isHidden` (e nao `isVisible`, que depende da janela
    estar na tela) pega o checkbox escondido com `setVisible(False)`.
    """
    with _flags_regime(llm_flags_v2=llm_flags_v2, mimo_v1=mimo_v1) as fp:
        assert feature_flags.mimo_v1_state() == state
        panel = fp.FlagsPanel()
        assert set(panel._checkboxes) == roster
        panel.set_main_llm("claude")
        mimo_flags = sorted(roster & {"--mimo", "--mimo-pro"})
        assert mimo_flags == (["--mimo"] if llm_flags_v2 is None else ["--mimo", "--mimo-pro"])
        for flag in mimo_flags:
            chk = panel.checkbox(flag)
            assert chk is not None and chk.isEnabled(), flag
            assert not chk.isHidden(), flag
            assert chk.property("testid") == f"queue-chk-flag-{flag[2:]}"
        _check(panel, mimo_flags)
        assert sorted(panel.checked_flags()) == mimo_flags


@pytest.mark.parametrize(
    ("llm_flags_v2", "disabled_by_main"),
    [
        pytest.param(None, _LEGACY_DISABLED_BY_MAIN, id="legado"),
        pytest.param("1", _V2_DISABLED_BY_MAIN, id="v2"),
    ],
)
def test_disabled_flags_follow_the_main_on_every_transition(
    qapp, llm_flags_v2: str | None, disabled_by_main: dict[str, frozenset[str]]
):
    """Nenhum disable gruda: cada Main recalcula o conjunto inteiro.

    Ao voltar para claude, todo tooltip volta ao texto de flag habilitada.
    """
    with _flags_regime(llm_flags_v2=llm_flags_v2) as fp:
        panel = fp.FlagsPanel()
        for main in _MAIN_WALK:
            panel.set_main_llm(main)
            assert _disabled(panel) == disabled_by_main[main], main
        assert _MAIN_WALK[-1] == "claude"
        assert _tooltips(panel) == {flag: _expected_enabled_tooltip(flag) for flag in panel._checkboxes}


def test_main_mimo_explains_each_disabled_flag(qapp):
    """Main mimo: literais MiMo por redundancia, literais Kimi por MiMo > Kimi."""
    with _flags_regime(llm_flags_v2="1") as fp:
        panel = fp.FlagsPanel()
        panel.set_main_llm("mimo")
        tips = _tooltips(panel)
        assert tips["--mimo"] == "Flag --mimo redundante sob Main mimo."
        assert tips["--mimo-pro"] == "Flag --mimo-pro redundante sob Main mimo."
        for flag in ("--kimi", "--kimi-k3"):
            assert tips[flag] == fp.autoproxy_tooltip(flag, "mimo")
            assert "MiMo > Kimi" in tips[flag]
        # O slug chega normalizado: rotulo com caixa e espaco da o mesmo estado.
        panel.set_main_llm(" MiMo ")
        assert _disabled(panel) == _V2_DISABLED_BY_MAIN["mimo"]
        assert _tooltips(panel) == tips


def test_main_kimi_keeps_the_mimo_flags_and_drops_codex_by_autoproxy(qapp):
    """Main kimi: MiMo segue disponivel; Codex cai por auto-proxy (C-43)."""
    with _flags_regime(llm_flags_v2="1") as fp:
        panel = fp.FlagsPanel()
        panel.set_main_llm("kimi")
        tips = _tooltips(panel)
        for flag in ("--mimo", "--mimo-pro"):
            assert panel.checkbox(flag).isEnabled(), flag
            assert tips[flag] == _expected_enabled_tooltip(flag)
        assert tips["--codex"] == _KIMI_CODEX_TOOLTIP
        assert tips["--codex-ultra"] == fp.autoproxy_tooltip("--codex-ultra", "kimi")
        assert "auto-proxy" in tips["--codex-ultra"]
        assert tips["--kimi"] == "Flag --kimi redundante sob Main kimi."
        assert tips["--kimi-k3"] == "Flag --kimi-k3 redundante sob Main kimi."


def test_legacy_main_mimo_drops_kimi_and_keeps_codex(qapp):
    """Regime legado: a mesma precedencia vale sobre o roster reduzido."""
    with _flags_regime(llm_flags_v2=None) as fp:
        panel = fp.FlagsPanel()
        assert set(panel._checkboxes) == _LEGACY_ROSTER
        panel.set_main_llm("mimo")
        tips = _tooltips(panel)
        assert panel.checkbox("--codex").isEnabled()
        assert tips["--codex"] == _expected_enabled_tooltip("--codex")
        assert tips["--mimo"] == "Flag --mimo redundante sob Main mimo."
        assert tips["--kimi"] == fp.autoproxy_tooltip("--kimi", "mimo")


@pytest.mark.parametrize(("llm_flags_v2", "roster"), _REGIMES)
def test_enabled_tooltips_announce_only_the_paired_precedence(
    qapp, llm_flags_v2: str | None, roster: frozenset[str]
):
    """Sob Main claude cada literal anuncia Main, terminais e, se tiver, o par.

    So os dois lados de cada par MiMo > Kimi ganham linha de precedencia, e o
    legado nunca cita o par pro, que nao existe nele.
    """
    with _flags_regime(llm_flags_v2=llm_flags_v2) as fp:
        panel = fp.FlagsPanel()
        panel.set_main_llm("claude")
        assert _tooltips(panel) == {flag: _expected_enabled_tooltip(flag) for flag in roster}


def test_panel_born_under_main_mimo_already_applies_the_precedence(qapp):
    """Gap A4: com resolver, o painel nasce com o Main corrente aplicado."""
    with _flags_regime(llm_flags_v2="1") as fp:
        panel = fp.FlagsPanel(main_llm_resolver=lambda: "mimo")
        assert _disabled(panel) == _V2_DISABLED_BY_MAIN["mimo"]


def test_delegation_kill_switch_overrides_the_main_mimo_rules(qapp):
    """Paridade non-Claude desligada: sob Main mimo tudo cai pelo kill-switch.

    Cai do payload tambem: antes o switch so pintava os checkboxes de cinza
    e as flags ja marcadas seguiam no sufixo T1.
    """
    with _flags_regime(llm_flags_v2="1", delegation="0") as fp:
        panel = fp.FlagsPanel()
        _check(panel, fp._FLAG_ORDER)
        panel.set_main_llm("mimo")
        assert _disabled(panel) == _V2_ROSTER
        assert panel.inactive_flags() == _V2_ROSTER
        assert panel.checked_flags() == []
        tips = set(_tooltips(panel).values())
        assert len(tips) == 1
        assert "SYSTEMFORGE_DELEGATION_FLAGS_NONCLAUDE=0" in tips.pop()
        # Sob Main claude o kill-switch nao tem o que frear.
        panel.set_main_llm("claude")
        assert _disabled(panel) == frozenset()
        assert panel.checked_flags() == list(fp._FLAG_ORDER)


# ======================================================================
# Payload T1: desabilitada = fora do sufixo
# ======================================================================


@pytest.mark.parametrize(
    ("llm_flags_v2", "disabled_by_main"),
    [
        pytest.param(None, _LEGACY_DISABLED_BY_MAIN, id="legado"),
        pytest.param("1", _V2_DISABLED_BY_MAIN, id="v2"),
    ],
)
def test_disabled_flags_never_reach_the_payload(
    qapp, llm_flags_v2: str | None, disabled_by_main: dict[str, frozenset[str]]
):
    """Cinza e fora do payload sao a mesma regra, em toda transicao de Main.

    Com o roster inteiro marcado, `checked_flags` sob cada Main e o roster
    menos as desabilitadas, na ordem canonica. O painel publica o mesmo
    conjunto em `inactive_flags`, a funcao pura concorda (e o que o caminho
    legado do widget consome) e nenhum checkbox e desmarcado.
    """
    with _flags_regime(llm_flags_v2=llm_flags_v2) as fp:
        panel = fp.FlagsPanel()
        order = list(fp._FLAG_ORDER)
        _check(panel, order)
        for main in _MAIN_WALK:
            panel.set_main_llm(main)
            disabled = disabled_by_main[main]
            assert _disabled(panel) == disabled, main
            assert panel.inactive_flags() == disabled, main
            assert fp.inactive_flags_for_main(main) == disabled, main
            assert panel.checked_flags() == [f for f in order if f not in disabled], main
            assert all(chk.isChecked() for chk in panel._checkboxes.values()), main


@pytest.mark.parametrize(("llm_flags_v2", "roster"), _REGIMES)
def test_kimi_checked_under_claude_leaves_the_payload_under_main_mimo(
    qapp, llm_flags_v2: str | None, roster: frozenset[str]
):
    """O Kimi marcado sob Main claude nao vaza para o T1 sob Main mimo.

    Era o defeito: o auto-proxy MiMo > Kimi so pintava o checkbox de cinza e
    o `--kimi` (e o `--kimi-k3` no v2) seguia no sufixo. Sob Main mimo o Kimi
    sai do payload sem ser desmarcado; de volta a Main claude, a selecao do
    operador volta inteira.
    """
    with _flags_regime(llm_flags_v2=llm_flags_v2) as fp:
        panel = fp.FlagsPanel()
        panel.set_main_llm("claude")
        kimis = [f for f in fp._FLAG_ORDER if f in {"--kimi", "--kimi-k3"}]
        assert set(kimis) == roster & {"--kimi", "--kimi-k3"}
        assert kimis == (["--kimi"] if llm_flags_v2 is None else ["--kimi-k3", "--kimi"])
        selection = [*kimis, "--codex"]
        _check(panel, selection)
        under_claude = [f for f in fp._FLAG_ORDER if f in selection]
        assert panel.checked_flags() == under_claude

        panel.set_main_llm("mimo")
        assert panel.checked_flags() == ["--codex"]
        assert all(panel.checkbox(f).isChecked() for f in kimis)

        panel.set_main_llm("claude")
        assert panel.checked_flags() == under_claude


@pytest.mark.parametrize(
    ("main", "expected"),
    [
        pytest.param(None, frozenset(), id="none-cai-em-claude"),
        pytest.param("", frozenset(), id="vazio-cai-em-claude"),
        pytest.param(" MiMo ", frozenset({"--mimo", "--kimi"}), id="normaliza"),
        pytest.param("opus", frozenset(), id="main-sem-regra"),
    ],
)
def test_inactive_flags_for_main_normalizes_the_slug(main, expected: frozenset[str]):
    """A funcao pura aceita o Main cru do resolver.

    Vazio ou ausente cai em claude; Main sem regra na tabela nao desabilita
    nada. Sob Main mimo, no regime legado, `--mimo` e redundante e o
    `--kimi` cai por MiMo > Kimi.
    """
    with _flags_regime(llm_flags_v2=None) as fp:
        assert fp.inactive_flags_for_main(main) == expected
