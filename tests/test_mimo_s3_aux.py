"""Rollout MiMo na superficie auxiliar do workflow-app (area S3c, 2026-10-02).

Cobre o que os testes vizinhos nao travam:

1. `MCPPromptButton` conhece `MiMo` em todas as copias do catalogo (Literal,
   `VALID_BUTTON_TYPES`, as tres tabelas de cor) e o radio resolve `mimo` em
   qualquer caixa para o rotulo de caixa mista, nunca para o default Claude.
2. MiMo, fixo ou via radio, nunca aciona o gate T7, que e exclusivo do Codex
   fixo. Um teste de controle prova que o gate segue vivo para o Codex; sem
   ele, a ausencia de bloqueio nos testes de MiMo seria vacua.
3. A redacao de `tp-` (Token Plan MiMo) em `create_agent_prompt` e na
   telemetria do brainstorm cobre tudo o que a classe `mimo-token-plan` do
   hook de segredos bloqueia, inclusive a chave colada a letra acentuada, onde
   um limite de palavra Unicode nao existe.

As amostras de chave sao sinteticas e montadas por concatenacao: nenhuma linha
deste arquivo carrega o literal inteiro.
"""

from __future__ import annotations

import ast
import re
import typing
from pathlib import Path

import pytest
from PySide6.QtCore import Qt

from workflow_app import brainstorm_telemetry as tel
from workflow_app import create_agent_prompt as cap
from workflow_app.signal_bus import signal_bus
from workflow_app.widgets import mcp_prompt_button as mpb
from workflow_app.widgets.mcp_prompt_button import (
    _CODEX_TOAST_CANONICAL,
    _CODEX_TOAST_SHORT,
)

pytestmark = pytest.mark.timeout(5)

REPO_ROOT = Path(__file__).resolve().parents[3]
HOOK = REPO_ROOT / ".claude" / "hooks" / "pretool-bash-secrets.sh"

#: Chave sintetica do Token Plan. Minuscula porque a classe do hook so aceita
#: minusculas no corpo, e fora do alfabeto hex porque a classe `hex-token` da
#: telemetria mascararia uma amostra hex mesmo sem a entrada `tp-`, e o teste
#: passaria sem provar nada.
_CHAVE = "tp-" + "zx7" * 16

#: Fronteiras a esquerda da chave. Nenhuma pertence a classe ASCII do
#: lookbehind do hook, entao o hook bloqueia a chave depois de cada uma,
#: inclusive depois de letra acentuada.
_FRONTEIRAS = (
    "", " ", "=", ":", "/", "(", "-", ".", "'", '"', "é", "ç", "ã",
)
_BLOQUEADAS = tuple(f + _CHAVE + " fim" for f in _FRONTEIRAS)

#: Vizinhos que nao sao segredo: o `t` segue letra, digito ou `_` (a classe do
#: lookbehind), ou o corpo nao chega ao piso de 40.
_BENIGNOS = {
    "http": "http-" + "zx7" * 16,
    "ftp": "ftp-" + "zx7" * 16,
    "smtp": "smtp-" + "zx7" * 16,
    "stp": "stp-" + "zx7" * 16,
    "sublinhado": "_tp-" + "zx7" * 16,
    "digito": "1tp-" + "zx7" * 16,
    "curto": "tp-" + "zx7" * 3,
}

_ACENTUADAS = ("é", "ç", "ã")


def _padrao_do_hook(rotulo: str) -> re.Pattern[str]:
    """Le a classe `rotulo` de `SECRET_PATTERNS` no hook, por AST.

    Mesma extracao de `test_brainstorm_telemetry._classes_do_hook`: o hook e um
    `.sh` com Python embutido, e o fim da lista e o `]` sozinho no inicio de
    uma linha (o primeiro `]` do arquivo fecha uma classe de caracteres).
    """
    texto = HOOK.read_text(encoding="utf-8")
    m = re.search(
        r"^SECRET_PATTERNS = (\[.*?^\])$", texto, re.MULTILINE | re.DOTALL
    )
    assert m, "SECRET_PATTERNS nao encontrado no hook; o formato mudou"
    classes = {r: p for p, r, _sev in ast.literal_eval(m.group(1))}
    assert rotulo in classes, f"classe {rotulo!r} ausente do hook"
    return re.compile(classes[rotulo])


@pytest.fixture
def toasts():
    """Captura `signal_bus.toast_requested` como (msg, level)."""
    eventos: list[tuple[str, str]] = []

    def _on_toast(msg: str, level: str) -> None:
        eventos.append((msg, level))

    signal_bus.toast_requested.connect(_on_toast)
    yield eventos
    try:
        signal_bus.toast_requested.disconnect(_on_toast)
    except (RuntimeError, TypeError):
        pass


def _radio(factory, getter):
    _, btn = factory(
        button_type="type-selector-radio-input", radio_state_getter=getter,
    )
    return btn


def _espioes(btn) -> tuple[list[str], list[str], list[dict]]:
    """Troca os dois efeitos do gate T7 por espioes e escuta o emit.

    Atribuicao na instancia basta: `clicked` esta ligado ao `_on_clicked`
    bound, que resolve `self._block_codex_unavailable` e
    `self._registrar_bloqueio` a cada chamada.
    """
    gate: list[str] = []
    bloqueios: list[str] = []
    emitidos: list[dict] = []

    def _gate(reason: str = "t3_missing") -> str:
        gate.append(reason)
        return ""

    btn._block_codex_unavailable = _gate
    btn._registrar_bloqueio = bloqueios.append
    btn.prompt_requested.connect(lambda p: emitidos.append(p))
    return gate, bloqueios, emitidos


# Catalogo do botao


def test_mimo_no_literal_e_em_todo_catalogo_derivado():
    """O Literal e o set andam juntos, e os consumidores derivados herdam MiMo."""
    from workflow_app import agent_integration_specs as specs

    assert set(typing.get_args(mpb.ButtonType)) == mpb.VALID_BUTTON_TYPES
    assert "MiMo" in mpb.VALID_BUTTON_TYPES
    assert "MiMo" in specs.VALID_BUTTON_TYPES_FROZEN


def test_tabelas_de_cor_cobrem_exatamente_o_catalogo():
    """Tipo sem entrada numa das tres tabelas levanta KeyError ao montar o botao."""
    assert set(mpb._TYPE_BG) == mpb.VALID_BUTTON_TYPES
    assert set(mpb._TYPE_FG) == mpb.VALID_BUTTON_TYPES
    assert set(mpb._TYPE_BORDER) == mpb.VALID_BUTTON_TYPES


def test_cor_da_mimo_nao_colide_com_os_outros_tipos():
    """O teal e hipotese de paleta; o que precisa valer e a distincao visual."""
    outros = mpb.VALID_BUTTON_TYPES - {"MiMo"}
    assert mpb._TYPE_BG["MiMo"] not in {mpb._TYPE_BG[t] for t in outros}
    assert mpb._TYPE_BORDER["MiMo"] not in {mpb._TYPE_BORDER[t] for t in outros}


def test_botao_mimo_fixo_monta_com_a_propria_cor(mcp_prompt_button_factory):
    _, btn = mcp_prompt_button_factory(
        button_type="MiMo", target_path="terminal-workspace-output",
    )
    assert btn.isEnabled() is True
    assert btn._resolve_provider() == "MiMo"
    assert mpb._TYPE_BG["MiMo"] in btn.styleSheet()
    assert btn.toolTip().startswith("[MiMo] ")
    assert btn.payload()["button_type"] == "MiMo"


# Resolucao do radio


@pytest.mark.parametrize("valor", ["MiMo", "mimo", "MIMO", "mImO", " mimo "])
def test_radio_resolve_mimo_em_qualquer_caixa(mcp_prompt_button_factory, valor):
    """`.capitalize()` daria "Mimo" e cairia no default Claude em silencio."""
    btn = _radio(mcp_prompt_button_factory, lambda: valor)
    assert btn._resolve_provider() == "MiMo"


@pytest.mark.parametrize(
    "valor", ["desconhecido", "", None, 42, "Mimo-pro", "mimo2", "mi mo"],
)
def test_radio_com_valor_desconhecido_cai_em_claude(mcp_prompt_button_factory, valor):
    btn = _radio(mcp_prompt_button_factory, lambda: valor)
    assert btn._resolve_provider() == "Claude"


def test_radio_com_getter_que_levanta_cai_em_claude(mcp_prompt_button_factory):
    def _quebrado() -> str:
        raise RuntimeError("radio destruido")

    btn = _radio(mcp_prompt_button_factory, _quebrado)
    assert btn._resolve_provider() == "Claude"


@pytest.mark.parametrize(
    ("valor", "esperado"),
    [("claude", "Claude"), ("KIMI", "Kimi"), (" Codex ", "Codex"), ("Kimi", "Kimi")],
)
def test_radio_mantem_os_outros_provedores_pelo_nome_canonico(
    mcp_prompt_button_factory, valor, esperado,
):
    btn = _radio(mcp_prompt_button_factory, lambda: valor)
    assert btn._resolve_provider() == esperado


# Gate T7


@pytest.mark.parametrize(
    ("button_type", "getter"),
    [
        pytest.param("MiMo", None, id="fixo"),
        pytest.param("type-selector-radio-input", lambda: "mimo", id="radio"),
    ],
)
def test_mimo_nao_aciona_o_gate_t7_do_codex(
    qtbot, mcp_prompt_button_factory, codex_alive_factory, toasts, button_type, getter,
):
    """Com o T3 morto, um gate que olhasse para MiMo bloquearia este clique."""
    codex_alive_factory(False)
    _, btn = mcp_prompt_button_factory(
        button_type=button_type,
        target_path="terminal-workspace-output",
        radio_state_getter=getter,
    )
    assert btn._resolve_provider() == "MiMo"
    assert btn.isEnabled() is True
    gate, bloqueios, emitidos = _espioes(btn)

    qtbot.mouseClick(btn, Qt.MouseButton.LeftButton)

    assert len(emitidos) == 1
    assert emitidos[0]["button_type"] == button_type
    assert gate == []
    assert bloqueios == []
    assert all(
        msg not in (_CODEX_TOAST_CANONICAL, _CODEX_TOAST_SHORT) for msg, _ in toasts
    )


def test_controle_codex_fixo_sem_t3_aciona_o_gate(
    mcp_prompt_button_factory, codex_alive_factory,
):
    """Controle de nao vacuidade dos testes de MiMo acima."""
    codex_alive_factory(False)
    _, btn = mcp_prompt_button_factory(button_type="Codex")
    gate, bloqueios, emitidos = _espioes(btn)
    # Nasce disabled, entao o clique de mouse morreria no eventFilter; o slot e
    # chamado direto para exercitar o mesmo gate que os testes de MiMo cruzam.
    assert btn.isEnabled() is False

    btn._on_clicked()

    assert gate == ["t3_missing"]
    assert bloqueios == ["codex_unavailable"]
    assert emitidos == []


# Redacao de tp- (create_agent_prompt + telemetria)


@pytest.mark.parametrize("letra", _ACENTUADAS)
def test_token_plan_colado_a_letra_acentuada_e_redigido(letra):
    amostra = letra + _CHAVE
    # Nao vacuidade: entre a letra acentuada e o `t` nao ha limite de palavra
    # Unicode, entao a versao com `\b` deixaria esta chave passar.
    assert re.search(r"\btp-[A-Za-z0-9]{40,}", amostra) is None

    redigido = cap.redact_secrets(amostra)
    assert redigido == letra + "[REDACTED]"
    assert cap.redact_secrets(redigido) == redigido
    assert tel.scrub(amostra) == letra + "***mimo-token-plan***"


@pytest.mark.parametrize("letra", _ACENTUADAS)
def test_validadores_recusam_token_plan_colado_a_letra_acentuada(letra):
    amostra = "agente " + letra + _CHAVE

    with pytest.raises(cap.CreateAgentPromptError) as nome:
        cap.validate_name(amostra)
    assert nome.value.field == "name"
    assert str(nome.value) == "nome contem padrao nao permitido"
    assert _CHAVE not in str(nome.value)

    with pytest.raises(cap.CreateAgentPromptError) as descricao:
        cap.validate_description(amostra)
    assert descricao.value.field == "description"
    assert str(descricao.value) == "descricao contem padrao nao permitido"
    assert _CHAVE not in str(descricao.value)


def test_token_plan_com_maiusculas_tambem_e_redigido():
    """Os redatores podem cobrir mais do que o hook bloqueia, nunca menos."""
    amostra = "tp-" + "Zx7" * 16
    assert cap.redact_secrets(amostra) == "[REDACTED]"
    assert tel.scrub(amostra) == "***mimo-token-plan***"


@pytest.mark.skipif(not HOOK.exists(), reason="hook de segredos ausente no repo")
@pytest.mark.parametrize(
    "amostra", _BLOQUEADAS, ids=[repr(f) for f in _FRONTEIRAS],
)
def test_amostras_de_fronteira_sao_bloqueadas_pelo_hook(amostra):
    """Nao vacuidade do teste de superset: cada fronteira e bloqueada no hook."""
    assert _padrao_do_hook("mimo-token-plan").search(amostra)


@pytest.mark.skipif(not HOOK.exists(), reason="hook de segredos ausente no repo")
@pytest.mark.parametrize(
    "amostra",
    [*_BLOQUEADAS, *_BENIGNOS.values()],
    ids=[*(repr(f) for f in _FRONTEIRAS), *_BENIGNOS],
)
def test_redacao_cobre_tudo_que_o_hook_bloqueia(amostra):
    """Todo trecho que o hook bloquearia some da saida dos dois redatores.

    Roda tambem sobre os benignos: se o hook passar a bloquear um deles, este
    teste fica vermelho, porque os redatores continuam deixando-o intacto.
    """
    hook = _padrao_do_hook("mimo-token-plan")
    saidas = (cap.redact_secrets(amostra), tel.scrub(amostra))
    for m in hook.finditer(amostra):
        for saida in saidas:
            assert m.group(0) not in saida


@pytest.mark.parametrize("amostra", list(_BENIGNOS.values()), ids=list(_BENIGNOS))
def test_vizinhos_benignos_passam_intactos_pelos_redatores(amostra):
    assert cap.redact_secrets(amostra) == amostra
    assert tel.scrub(amostra) == amostra
    assert cap.validate_name(amostra) == amostra
    assert cap.validate_description(amostra) == amostra


# Engrenagem (gear) do brainstorm


def test_engrenagem_oferece_mimo_e_passa_do_gate_de_tipo(qtbot, tmp_path):
    """O combo de tipo e o gate de `_validate_record` derivam do catalogo."""
    from workflow_app.widgets.brainstorm_mcp_config_dialog import (
        BrainstormMcpConfigDialog,
    )

    repo_root = tmp_path / "repo"
    seeds_dir = repo_root / "seeds"
    seeds_dir.mkdir(parents=True)
    dlg = BrainstormMcpConfigDialog(
        parent=None, repo_root=repo_root, seeds_dir=seeds_dir,
    )
    qtbot.addWidget(dlg)

    combo = dlg._type_combo
    itens = [combo.itemText(i) for i in range(combo.count())]
    assert itens == sorted(mpb.VALID_BUTTON_TYPES)
    assert "MiMo" in itens

    # O tipo e julgado antes do `agent_path`. Reprovar no `agent_path` vazio
    # prova que MiMo passou do gate de tipo; o controle com a caixa errada
    # prova que o gate de tipo esta vivo.
    with pytest.raises(ValueError, match="agent_path obrigatorio"):
        dlg._validate_record(
            {"label": "x", "button_type": "MiMo", "agent_path": ""}, "p",
        )
    with pytest.raises(ValueError, match="Type invalido"):
        dlg._validate_record(
            {"label": "x", "button_type": "Mimo", "agent_path": ""}, "p",
        )
