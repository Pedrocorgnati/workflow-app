"""Task 30 - o tooltip do botao MCP tem UM construtor, nao tres.

Ate a Task 30 o mesmo f-string era remontado a mao em tres pontos de
`mcp_prompt_button.py`: no `__init__`, no `recheck_codex_availability` e no
`_on_codex_availability_changed`. As tres copias so divergiam quando alguem
mexia na FONTE do literal do prompt -- que e precisamente o que a C2 fez ao
tirar o prompt do frontmatter e passar para o bloco `## Prompt canonico`.
Consertar um caminho e deixar dois exibindo o texto velho e um defeito que
nenhum teste da suite pegava, porque nenhum comparava os tres.

Este arquivo compara. Tres eixos:

1. Paridade de conteudo: os tres caminhos escrevem o MESMO tooltip.
2. Unicidade estrutural: existe um unico construtor no fonte, e os tres
   call-sites o chamam (uma quarta copia futura reprova aqui).
3. Uma leitura por tooltip: o builder chama `_resolve_prompt_text()` uma vez,
   nao duas. Com `prompt` do tipo `Path` -- o caso dos seeds -- cada chamada
   extra era uma leitura de disco a mais por tooltip montado.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.timeout(10)

from workflow_app.widgets import mcp_prompt_button as mpb
from workflow_app.widgets.mcp_prompt_button import MCPPromptButton


def _fonte() -> str:
    return Path(mpb.__file__).read_text(encoding="utf-8")


def _codex_btn(qtbot, prompt="prompt qualquer"):
    """Botao Codex montado numa janela real (recheck exige parent + window)."""
    from PySide6.QtWidgets import QHBoxLayout, QWidget

    parent = QWidget()
    layout = QHBoxLayout(parent)
    btn = MCPPromptButton(
        label="paridade",
        button_type="Codex",
        prompt=prompt,
        agent_name="claude-coder",
        agent_path="ai-forge/MCP/agents/claude-coder.md",
        action="Executar",
        target_path="terminal-codex-output",
        testid_slug="tooltip-parity",
        parent=parent,
    )
    layout.addWidget(btn)
    qtbot.addWidget(parent)
    parent.show()
    qtbot.waitExposed(parent)
    return parent, btn


# ── 1. Paridade de conteudo ───────────────────────────────────────────────


def test_os_tres_caminhos_escrevem_o_mesmo_tooltip(
    qtbot, codex_alive_factory,
):
    """Construcao, recheck e signal global produzem tooltip identico."""
    codex_alive_factory(True)
    _parent, btn = _codex_btn(qtbot)

    do_init = btn.toolTip()

    btn.setToolTip("<sujeira para provar que o caminho reescreveu>")
    btn.recheck_codex_availability()
    do_recheck = btn.toolTip()

    btn.setToolTip("<sujeira para provar que o caminho reescreveu>")
    btn._on_codex_availability_changed(True)
    do_signal = btn.toolTip()

    assert do_init == do_recheck == do_signal
    assert do_init.startswith("[Codex] paridade\n")
    assert "action=Executar target=terminal-codex-output" in do_init
    assert "prompt: prompt qualquer" in do_init


def test_paridade_sobrevive_a_troca_da_fonte_do_literal(
    qtbot, codex_alive_factory, tmp_path,
):
    """Prompt em `Path`: mudar o ARQUIVO muda os tres tooltips juntos.

    Este e o cenario que motivou a task. Com tres copias, uma edicao no
    construtor de um caminho deixava os outros dois lendo do lugar antigo.
    """
    codex_alive_factory(True)
    md = tmp_path / "seed.md"
    md.write_text("corpo antigo", encoding="utf-8")
    _parent, btn = _codex_btn(qtbot, prompt=md)
    assert "prompt: corpo antigo" in btn.toolTip()

    md.write_text("corpo novo depois da C2", encoding="utf-8")
    btn.recheck_codex_availability()
    depois_recheck = btn.toolTip()
    btn._on_codex_availability_changed(True)
    depois_signal = btn.toolTip()

    assert depois_recheck == depois_signal
    assert "prompt: corpo novo depois da C2" in depois_recheck


def test_reticencias_so_aparecem_acima_do_corte(qtbot, codex_alive_factory):
    """O corte e as reticencias vivem no builder, nao no call-site."""
    codex_alive_factory(True)
    limite = mpb._TOOLTIP_PREVIEW_LEN

    _p1, curto = _codex_btn(qtbot, prompt="x" * limite)
    assert curto.toolTip().endswith("x" * limite)
    assert not curto.toolTip().endswith("...")

    _p2, longo = _codex_btn(qtbot, prompt="y" * (limite + 1))
    assert longo.toolTip().endswith("y" * limite + "...")


# ── 2. Unicidade estrutural ───────────────────────────────────────────────


def test_existe_um_unico_construtor_de_tooltip_no_fonte():
    """Uma quarta copia do f-string reprova aqui, nao em producao."""
    fonte = _fonte()
    # O miolo do template so pode aparecer uma vez: dentro de _build_tooltip.
    assert fonte.count("action={self._action} target=") == 1
    # E a forma antiga (locais do __init__) nao pode ressuscitar.
    assert "action={action} target=" not in fonte


def test_os_call_sites_do_builder_sao_exatamente_os_declarados():
    """`_build_tooltip` e definido uma vez, e quem o chama esta declarado aqui.

    A assercao e sobre o CONJUNTO de funcoes chamadoras, nao sobre a
    contagem. Contar so pega remocao; comparar conjunto pega tambem a
    troca silenciosa -- alguem apagar a remontagem do `contextMenuEvent` e
    somar uma em outro lugar deixaria a contagem intacta e o modal voltaria
    a exibir o destino velho.

    Somar um chamador aqui e um ato deliberado: quem adiciona uma nova
    mutacao de `label`/`action`/`target` precisa passar por este teste e,
    ao passar, ja escolheu remontar o tooltip.
    """
    arvore = ast.parse(_fonte())
    definicoes = [
        n for n in ast.walk(arvore)
        if isinstance(n, ast.FunctionDef) and n.name == "_build_tooltip"
    ]
    assert len(definicoes) == 1

    chamadores = set()
    for fn in ast.walk(arvore):
        if not isinstance(fn, ast.FunctionDef):
            continue
        for n in ast.walk(fn):
            if (
                isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "_build_tooltip"
            ):
                chamadores.add(fn.name)
    assert chamadores == {
        "__init__",
        "recheck_codex_availability",
        "_on_codex_availability_changed",
        "_refresh_tooltip",
    }, sorted(chamadores)

    # Todo `setToolTip` do botao ou passa pelo builder, ou e o toast curto
    # (a variante deliberadamente diferente, para Codex sem T3), ou e o
    # tooltip fixo do checkbox embutido.
    for chamada in ast.walk(arvore):
        if not (
            isinstance(chamada, ast.Call)
            and isinstance(chamada.func, ast.Attribute)
            and chamada.func.attr == "setToolTip"
        ):
            continue
        (arg,) = chamada.args
        ok_builder = (
            isinstance(arg, ast.Call)
            and isinstance(arg.func, ast.Attribute)
            and arg.func.attr == "_build_tooltip"
        )
        # Constantes de modulo sao aceitas como tooltip FIXO: sao texto de UI
        # sem parte variavel, entao nao ha o que divergir entre copias. E o
        # caso do toast curto do Codex (variante deliberada, para Codex sem
        # T3) e da dica da previa read-only do modal (Task 31).
        ok_constante = isinstance(arg, ast.Name) and arg.id in {
            "_CODEX_TOAST_SHORT", "_PROMPT_PREVIEW_HINT",
        }
        ok_fixo = isinstance(arg, ast.Constant) and isinstance(arg.value, str)
        assert ok_builder or ok_constante or ok_fixo, ast.dump(arg)


# ── 3. Uma leitura por tooltip ────────────────────────────────────────────


def test_builder_le_o_prompt_uma_vez_por_tooltip(
    qtbot, codex_alive_factory, tmp_path,
):
    """Duas leituras por tooltip eram dois `read_text` por seed em `Path`."""
    codex_alive_factory(True)
    md = tmp_path / "seed.md"
    md.write_text("corpo", encoding="utf-8")
    _parent, btn = _codex_btn(qtbot, prompt=md)

    leituras = {"n": 0}
    original = MCPPromptButton._resolve_prompt_text

    def _contando(self):
        leituras["n"] += 1
        return original(self)

    btn._resolve_prompt_text = _contando.__get__(btn, MCPPromptButton)
    btn._build_tooltip()
    assert leituras["n"] == 1


# -- 4. Mutacao pelo modal remonta o tooltip -------------------------------


def test_edicao_no_modal_atualiza_o_tooltip(qtbot, codex_alive_factory, monkeypatch):
    """Trocar label e destino pelo modal muda o que o tooltip afirma.

    O tooltip e a unica superficie que mostra label, action e target
    juntos. Sem a remontagem, o operador aceitava a edicao e o hover
    continuava jurando o destino antigo.
    """
    from PySide6.QtWidgets import QDialog

    from workflow_app.widgets import mcp_prompt_button as mod

    codex_alive_factory(True)
    _, btn = _codex_btn(qtbot, prompt="corpo do prompt")
    btn._button_type = "Claude"
    btn._target_path = "terminal-interactive-output"
    btn.setToolTip(btn._build_tooltip())
    assert "terminal-interactive-output" in btn.toolTip()
    assert "test-btn" in btn.toolTip() or btn._label in btn.toolTip()

    class _ModalFalso:
        def __init__(self, **kwargs):
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

        def values(self):
            return {
                "label": "rotulo novo",
                "agent_name": "agente-novo",
                "agent_path": "ai-forge/MCP/agents/agente-novo.md",
                "target_path": "terminal-codex-output",
            }

    monkeypatch.setattr(mod, "MCPPromptConfigModal", _ModalFalso)

    class _Evento:
        def accept(self):
            pass

    btn.contextMenuEvent(_Evento())

    assert btn._target_path == "terminal-codex-output"
    assert "terminal-codex-output" in btn.toolTip()
    assert "rotulo novo" in btn.toolTip()


def test_codex_sem_t3_nao_perde_o_aviso_ao_editar(
    qtbot, codex_alive_factory, monkeypatch
):
    """Editar um botao Codex indisponivel NAO troca o aviso por uma previa.

    Naquele estado o botao esta desabilitado; exibir o texto de preview
    seria prometer um disparo que o gate T7 nao deixa acontecer.
    """
    from PySide6.QtWidgets import QDialog

    from workflow_app.widgets import mcp_prompt_button as mod

    codex_alive_factory(False)
    _, btn = _codex_btn(qtbot, prompt="corpo do prompt")
    btn.recheck_codex_availability()
    assert btn.toolTip() == mod._CODEX_TOAST_SHORT

    class _ModalFalso:
        def __init__(self, **kwargs):
            pass

        def exec(self):
            return QDialog.DialogCode.Accepted

        def values(self):
            return {
                "label": "rotulo novo",
                "agent_name": None,
                "agent_path": None,
                "target_path": "terminal-codex-output",
            }

    monkeypatch.setattr(mod, "MCPPromptConfigModal", _ModalFalso)

    class _Evento:
        def accept(self):
            pass

    btn.contextMenuEvent(_Evento())
    assert btn.toolTip() == mod._CODEX_TOAST_SHORT
