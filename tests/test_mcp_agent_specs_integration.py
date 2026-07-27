"""Integracao das specs suplementares no setor MCP (AGENT-TASK-007).

Cobre o contrato de `output-toolbar-mcp` quando o registry de
`agent_integration_specs` tem entradas: botao REAL checkable com
`persona_prompt`, composicao apenas do que esta ativo, ordem deterministica e
rebuild sem perda nem duplicacao de widgets.

O registry canonico e vazio por design (as specs sao acrescentadas por
`/mcp:create-agent`), entao cada teste injeta suas proprias specs via
monkeypatch de `workflow_app.agent_integration_specs.mcp_agent_specs` e
reconstroi a coluna com `_build_mcp_column`.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QRect
from PySide6.QtWidgets import QCheckBox, QPushButton, QRadioButton, QWidget

from workflow_app import agent_integration_specs as specs_mod
from workflow_app.agent_integration_specs import (
    AgentIntegrationSpecError,
    McpAgentSpec,
)
from workflow_app.signal_bus import signal_bus

_HARDENING_DIRECTIVE = (
    "no papel de engenheiro de hardening suplementar, conforme regras em "
    "ai-forge/MCP/agents/hardening-engineer-rules.md"
)
_UX_DIRECTIVE = (
    "no papel de especialista UX suplementar, conforme regras em "
    "ai-forge/MCP/agents/ux-ui-specialist.md"
)


@pytest.fixture
def win(qapp):
    """MainWindow com teardown ORDENADO: a janela morre antes dos popups.

    Rebuildar `output-toolbar-mcp` instancia QComboBox novos, e cada combo
    registra um popup (QFrame com flag Qt.Popup) que conta como top-level em
    `QApplication.topLevelWidgets()`. O teardown global do conftest deleta os
    top-level na ordem da lista: apagar um popup ANTES do combo dono deixa
    ponteiro pendurado no C++ e derruba o processo com SIGSEGV. Destruindo a
    janela aqui primeiro, os popups ja nascem invalidos para o conftest, que
    apenas os ignora. Por isso tambem nao se usa `qtbot.addWidget`: o cleanup
    do pytest-qt chamaria `close()` no wrapper ja destruido.
    """
    import shiboken6

    from workflow_app.main_window import MainWindow

    window = MainWindow()
    yield window
    if shiboken6.isValid(window):
        window.close()
        shiboken6.delete(window)


def _spec(slug: str = "hardening-suplementar", **over) -> McpAgentSpec:
    kwargs = {
        "slug": slug,
        "label": "hardening+",
        "directive": _HARDENING_DIRECTIVE,
    }
    kwargs.update(over)
    return McpAgentSpec(**kwargs)


def _rebuild_column(win) -> QWidget:
    """Reconstroi output-toolbar-mcp e devolve a coluna nova.

    A coluna anterior continua no layout da janela; por isso as buscas dos
    testes partem SEMPRE da coluna devolvida, nunca da MainWindow inteira. A
    nova coluna e parenteada na janela (sem entrar em layout) para o teardown
    do Qt destruir tudo numa arvore so.

    ESCOPO DA GARANTIA: unicidade e nao-acumulo sao provados POR ARVORE, nao
    globalmente na MainWindow. Isso basta porque `_build_mcp_column` tem um
    unico caller de producao (`MainWindow.__init__`) e nao existe rebuild em
    runtime. Se algum dia houver (ex.: recarregar o registry apos
    `/mcp:create-agent` sem restart), este helper precisa virar substituicao
    real (remover do layout, desconectar sinais, `deleteLater`) e as buscas
    passam a partir da MainWindow inteira.
    """
    column, brainstorm_column = win._build_mcp_column(win._mcp_column_btns)
    column.setParent(win)
    column.hide()
    # Desde 2026-07-27 o builder devolve TAMBEM a moldura da secao BRAINSTORM
    # (`output-toolbar-brainstorm`), que nasce sem pai: parenteia junto, senao o
    # widget novo fica solto e vira top-level orfao no teardown.
    brainstorm_column.setParent(win)
    brainstorm_column.hide()
    return column


# I2.1: `output-mcp-provider-*` e `_mcp_provider_radio_input` foram
# eliminados. O provider das acoes MCP sai do Main LLM (`queue-div-main-llm`),
# lido por `MainWindow._current_llm_provider()`.
_MAIN_LLM_TESTIDS = {
    "claude": "queue-radio-main-claude",
    "codex": "queue-radio-main-codex",
    "kimi": "queue-chk-force-kimi",
}


def _set_main_llm(win, provider_id: str) -> None:
    """Seleciona o Main LLM — substituto unico do antigo radio do MCP."""
    _by_testid(
        win._command_queue._llm_box,
        _MAIN_LLM_TESTIDS[provider_id],
        QRadioButton,
    ).setChecked(True)


def _set_route(win, *, t1: bool, t2: bool, t3: bool) -> None:
    win._chk_route_t1.setChecked(t1)
    win._chk_route_t2.setChecked(t2)
    win._chk_route_t3.setChecked(t3)


def _by_testid(root: QWidget, testid: str, widget_type=QPushButton):
    """Busca por testid restrita a um tipo concreto de widget.

    Nunca usar `QWidget` aqui: materializar wrappers de TODOS os QWidget de uma
    MainWindow corrompe o teardown do PySide6 (ver nota em
    test_main_window_terminal_routes.py). Para chegar num container, subir pelo
    `parentWidget()` de um leaf conhecido.
    """
    assert widget_type is not QWidget, "use _row_of/_mcp_column_of para containers"
    for widget in root.findChildren(widget_type):
        if widget.property("testid") == testid:
            return widget
    raise AssertionError(f"widget nao encontrado: {testid}")


def _row_of(leaf: QWidget) -> QWidget:
    row = leaf.parentWidget()
    assert row is not None
    return row


def _mcp_column_of(win) -> QWidget:
    """Sobe do action-btn ate o container com testid output-toolbar-mcp."""
    node = _by_testid(win, "output-mcp-action-main").parentWidget()
    while node is not None and node.property("testid") != "output-toolbar-mcp":
        node = node.parentWidget()
    assert node is not None, "output-toolbar-mcp nao encontrado"
    return node


def _agent_buttons(root: QWidget) -> list[QPushButton]:
    return [
        btn
        for btn in root.findChildren(QPushButton)
        if str(btn.property("testid") or "").startswith("output-mcp-agent-")
    ]


def _rendered_lines(container: QWidget, buttons: list[QPushButton], width: int) -> int:
    """Aplica `width` no container e conta as linhas realmente renderizadas.

    O flow so decide a quebra dentro de `setGeometry`; sem forcar a geometria a
    largura do container em teste (janela nunca exibida) fica no sizeHint e o
    numero de linhas nao reflete a largura pedida.
    """
    height = container.layout().heightForWidth(width)
    container.resize(width, height)
    container.layout().setGeometry(QRect(0, 0, width, height))
    return len({btn.geometry().y() for btn in buttons})


def _publish_and_capture(win, action_testid: str, column: QWidget) -> list[str]:
    sent: list[str] = []
    signal_bus.paste_text_in_terminal.connect(sent.append)
    try:
        _by_testid(column, action_testid).click()
    finally:
        signal_bus.paste_text_in_terminal.disconnect(sent.append)
    return sent


# ── Registry vazio: zero widget novo, zero mudanca de contrato ──────────────


def test_registry_vazio_nao_cria_botao_nem_linha(win):
    column = _mcp_column_of(win)

    assert _agent_buttons(column) == []
    assert win._mcp_agent_buttons == []


def test_registry_vazio_preserva_composicao_existente(win):
    column = _mcp_column_of(win)
    _set_route(win, t1=True, t2=False, t3=False)
    _set_main_llm(win, "claude")

    assert _publish_and_capture(win, "output-mcp-action-main", column) == [
        "/mcp:codex"
    ]


# ── Materializacao: botao real, checkable, com contrato visual ──────────────


def test_spec_vira_qpushbutton_real_checkable_com_persona_prompt(win, monkeypatch):
    monkeypatch.setattr(specs_mod, "mcp_agent_specs", lambda: (_spec(),))
    column = _rebuild_column(win)

    btn = _by_testid(column, "output-mcp-agent-hardening-suplementar")
    assert isinstance(btn, QPushButton)
    assert not isinstance(btn, QCheckBox)
    assert btn.isCheckable()
    assert not btn.isChecked()
    assert btn.text() == "hardening+"
    assert btn.property("persona_prompt") == _HARDENING_DIRECTIVE
    assert btn.property("agent_slug") == "hardening-suplementar"
    # Sem `setFixedHeight`: a altura sai do label + padding 1px do stylesheet.
    assert btn.minimumHeight() == 0
    assert btn.maximumHeight() > btn.sizeHint().height()
    assert btn.sizeHint().height() <= 24
    assert btn.toolTip() == _HARDENING_DIRECTIVE
    assert btn.accessibleName()


def test_botao_suplementar_vive_dentro_de_output_toolbar_mcp(win, monkeypatch):
    monkeypatch.setattr(specs_mod, "mcp_agent_specs", lambda: (_spec(),))
    column = _rebuild_column(win)

    assert column.property("testid") == "output-toolbar-mcp"
    btn = _by_testid(column, "output-mcp-agent-hardening-suplementar")
    assert _row_of(btn).property("testid") == "output-mcp-agent-buttons"


def test_controles_existentes_continuam_intactos(win, monkeypatch):
    monkeypatch.setattr(specs_mod, "mcp_agent_specs", lambda: (_spec(),))
    column = _rebuild_column(win)

    assert len(win._mcp_persona_checkboxes) == 16
    for action_id in ("main", "parallel", "dual"):
        assert _by_testid(column, f"output-mcp-action-{action_id}")
    # A tab bar interna (`output-mcp-tab-mcps` / `-brainstorm`) morreu em
    # 2026-07-27: as duas sub-abas viraram secoes de primeiro nivel do
    # `output-toolbar-section-selector`, entao a coluna nao tem mais nivel de
    # aba proprio.
    rendered = {btn.property("testid") for btn in column.findChildren(QPushButton)}
    assert not {"output-mcp-tab-mcps", "output-mcp-tab-brainstorm"} & rendered


# ── Composicao: so entra o que esta ativo ───────────────────────────────────


@pytest.mark.parametrize(
    ("action_testid", "base"),
    [
        ("output-mcp-action-main", "/mcp:codex"),
        ("output-mcp-action-parallel", "/mcp:kimi"),
        ("output-mcp-action-dual", "/mcp:dual"),
    ],
)
def test_botao_inativo_nao_altera_prompt_nas_tres_acoes(
    win, monkeypatch, action_testid, base
):
    monkeypatch.setattr(specs_mod, "mcp_agent_specs", lambda: (_spec(),))
    column = _rebuild_column(win)
    _set_route(win, t1=True, t2=False, t3=False)
    _set_main_llm(win, "claude")

    assert _publish_and_capture(win, action_testid, column) == [base]


@pytest.mark.parametrize(
    ("action_testid", "base"),
    [
        ("output-mcp-action-main", "/mcp:codex"),
        ("output-mcp-action-parallel", "/mcp:kimi"),
        ("output-mcp-action-dual", "/mcp:dual"),
    ],
)
def test_botao_ativo_anexa_diretiva_uma_vez_nas_tres_acoes(
    win, monkeypatch, action_testid, base
):
    monkeypatch.setattr(specs_mod, "mcp_agent_specs", lambda: (_spec(),))
    column = _rebuild_column(win)
    _set_route(win, t1=True, t2=False, t3=False)
    _set_main_llm(win, "claude")
    _by_testid(column, "output-mcp-agent-hardening-suplementar").setChecked(True)

    sent = _publish_and_capture(win, action_testid, column)

    assert sent == [f"{base} {_HARDENING_DIRECTIVE}"]
    assert sent[0].count(_HARDENING_DIRECTIVE) == 1


def test_apenas_specs_ativas_entram_na_composicao(win, monkeypatch):
    monkeypatch.setattr(
        specs_mod,
        "mcp_agent_specs",
        lambda: (
            _spec(),
            _spec(slug="ux-suplementar", label="ux+", directive=_UX_DIRECTIVE),
        ),
    )
    column = _rebuild_column(win)
    _set_route(win, t1=True, t2=False, t3=False)
    _set_main_llm(win, "claude")
    _by_testid(column, "output-mcp-agent-ux-suplementar").setChecked(True)

    sent = _publish_and_capture(win, "output-mcp-action-main", column)

    assert sent == [f"/mcp:codex {_UX_DIRECTIVE}"]
    assert _HARDENING_DIRECTIVE not in sent[0]


# ── Ordem deterministica ────────────────────────────────────────────────────


def test_ordem_persona_antes_de_suplemento(win, monkeypatch):
    monkeypatch.setattr(specs_mod, "mcp_agent_specs", lambda: (_spec(),))
    column = _rebuild_column(win)
    _set_route(win, t1=True, t2=False, t3=False)
    _set_main_llm(win, "claude")
    _by_testid(column, "output-mcp-persona-search-in", QCheckBox).setChecked(True)
    _by_testid(column, "output-mcp-agent-hardening-suplementar").setChecked(True)

    sent = _publish_and_capture(win, "output-mcp-action-main", column)

    assert sent == [
        "/mcp:codex no papel de search-in, conforme regras em "
        "ai-forge/MCP/agents/search-in-rules.md; e depois disso "
        f"{_HARDENING_DIRECTIVE}"
    ]


def test_ordem_entre_suplementos_segue_o_registry(win, monkeypatch):
    monkeypatch.setattr(
        specs_mod,
        "mcp_agent_specs",
        lambda: (
            _spec(slug="ux-suplementar", label="ux+", directive=_UX_DIRECTIVE),
            _spec(),
        ),
    )
    column = _rebuild_column(win)
    _set_route(win, t1=True, t2=False, t3=False)
    _set_main_llm(win, "claude")
    _by_testid(column, "output-mcp-agent-hardening-suplementar").setChecked(True)
    _by_testid(column, "output-mcp-agent-ux-suplementar").setChecked(True)

    sent = _publish_and_capture(win, "output-mcp-action-main", column)

    assert sent == [
        f"/mcp:codex {_UX_DIRECTIVE}; e depois disso {_HARDENING_DIRECTIVE}"
    ]
    assert [btn.property("testid") for btn in _agent_buttons(column)] == [
        "output-mcp-agent-ux-suplementar",
        "output-mcp-agent-hardening-suplementar",
    ]


def test_suplementos_ficam_entre_personas_e_action_row(win, monkeypatch):
    monkeypatch.setattr(specs_mod, "mcp_agent_specs", lambda: (_spec(),))
    column = _rebuild_column(win)

    agent_row = _row_of(_by_testid(column, "output-mcp-agent-hardening-suplementar"))
    persona_row = _row_of(
        _by_testid(column, "output-mcp-persona-performance-engineer", QCheckBox)
    )
    action_row = _row_of(_by_testid(column, "output-mcp-action-main"))
    # Refactor 07-27: container unico de personas (nao ha mais `-2/-3/-4`).
    assert persona_row.property("testid") == "output-mcp-persona-checkboxes"
    assert action_row.property("testid") == "output-mcp-action-row"
    page_layout = agent_row.parentWidget().layout()
    order = [page_layout.itemAt(i).widget() for i in range(page_layout.count())]

    assert order.index(persona_row) < order.index(agent_row) < order.index(action_row)


def test_specs_vivem_num_flow_unico_com_quebra_por_largura(win, monkeypatch):
    """Contrato responsivo: um container so, quebra ditada pela largura.

    Antes existiam linhas fixas de 4 botoes (`output-mcp-agent-buttons-2`).
    Agora todos os agentes moram em `output-mcp-agent-buttons`, que usa
    `ResponsiveButtonFlowLayout` sem teto de linhas: cada botao tem a largura
    do proprio label e a quantidade por linha cresce com a janela.
    """
    monkeypatch.setattr(
        specs_mod,
        "mcp_agent_specs",
        lambda: tuple(_spec(slug=f"agente-{i}", label=f"a{i}") for i in range(5)),
    )
    column = _rebuild_column(win)

    buttons = _agent_buttons(column)
    assert [btn.property("testid") for btn in buttons] == [
        f"output-mcp-agent-agente-{i}" for i in range(5)
    ]
    assert {_row_of(btn).property("testid") for btn in buttons} == {
        "output-mcp-agent-buttons"
    }

    container = _row_of(buttons[0])
    assert _rendered_lines(container, buttons, 110) == 2
    assert _rendered_lines(container, buttons, 400) == 1


def test_gap_vertical_entre_linhas_de_agentes_e_de_1px(win, monkeypatch):
    monkeypatch.setattr(
        specs_mod,
        "mcp_agent_specs",
        lambda: tuple(_spec(slug=f"agente-{i}", label=f"a{i}") for i in range(5)),
    )
    column = _rebuild_column(win)
    buttons = _agent_buttons(column)
    container = _row_of(buttons[0])

    assert _rendered_lines(container, buttons, 110) == 2
    tops = sorted({btn.geometry().y() for btn in buttons})
    heights = {btn.geometry().height() for btn in buttons}

    assert len(heights) == 1
    assert tops[1] - tops[0] == heights.pop() + 1


# ── Personas: mesmo contrato responsivo dos agentes ────────────────────────


def test_personas_vivem_num_flow_unico_com_largura_do_label(win):
    """Refactor 07-27 (paridade com a aba Brainstorm).

    As 4 linhas fixas de 4 checkboxes com largura igual
    (`output-mcp-persona-checkboxes-2/-3/-4`) viraram UM container com
    `ResponsiveButtonFlowLayout`: cada persona e um controle individual com a
    largura do proprio label e a quebra segue a largura da janela.
    """
    column = _rebuild_column(win)
    personas = [
        chk
        for chk in column.findChildren(QCheckBox)
        if str(chk.property("testid") or "").startswith("output-mcp-persona-")
    ]

    assert len(personas) == 16
    assert {_row_of(chk).property("testid") for chk in personas} == {
        "output-mcp-persona-checkboxes"
    }

    container = _row_of(personas[0])
    # Cada pilula reserva a largura do proprio label: hints diferentes para
    # labels de tamanhos diferentes (antes, o stretch=1 igualava todos).
    hints = {chk.property("testid"): chk.sizeHint().width() for chk in personas}
    assert hints["output-mcp-persona-scaffolds-blueprints-updater"] > hints[
        "output-mcp-persona-executor"
    ]
    # Quebra ditada pela largura: janela larga concentra, janela estreita quebra.
    assert _rendered_lines(container, personas, 260) > _rendered_lines(
        container, personas, 900
    )


# ── Rebuild: nao perde nem duplica ──────────────────────────────────────────


def test_rebuild_nao_duplica_nem_perde_botoes(win, monkeypatch):
    monkeypatch.setattr(
        specs_mod,
        "mcp_agent_specs",
        lambda: (
            _spec(),
            _spec(slug="ux-suplementar", label="ux+", directive=_UX_DIRECTIVE),
        ),
    )

    first = _rebuild_column(win)
    assert len(_agent_buttons(first)) == 2
    assert len(win._mcp_agent_buttons) == 2

    second = _rebuild_column(win)
    testids = [btn.property("testid") for btn in _agent_buttons(second)]

    assert testids == [
        "output-mcp-agent-hardening-suplementar",
        "output-mcp-agent-ux-suplementar",
    ]
    assert len(testids) == len(set(testids))
    assert len(win._mcp_agent_buttons) == 2
    assert all(not btn.isChecked() for btn in win._mcp_agent_buttons)


def test_rebuild_usa_o_registry_atualizado(win, monkeypatch):
    monkeypatch.setattr(specs_mod, "mcp_agent_specs", lambda: (_spec(),))
    _rebuild_column(win)

    monkeypatch.setattr(
        specs_mod,
        "mcp_agent_specs",
        lambda: (
            _spec(),
            _spec(slug="ux-suplementar", label="ux+", directive=_UX_DIRECTIVE),
        ),
    )
    second = _rebuild_column(win)

    assert [btn.property("testid") for btn in _agent_buttons(second)] == [
        "output-mcp-agent-hardening-suplementar",
        "output-mcp-agent-ux-suplementar",
    ]


def test_composicao_apos_rebuild_usa_os_botoes_novos(win, monkeypatch):
    monkeypatch.setattr(specs_mod, "mcp_agent_specs", lambda: (_spec(),))
    _rebuild_column(win)
    column = _rebuild_column(win)
    _set_route(win, t1=True, t2=False, t3=False)
    _set_main_llm(win, "claude")
    _by_testid(column, "output-mcp-agent-hardening-suplementar").setChecked(True)

    sent = _publish_and_capture(win, "output-mcp-action-main", column)

    assert sent == [f"/mcp:codex {_HARDENING_DIRECTIVE}"]
    assert sent[0].count(_HARDENING_DIRECTIVE) == 1


# ── Fail-safe: registry quebrado nao derruba a coluna ───────────────────────


def test_registry_invalido_monta_coluna_sem_suplementos(win, monkeypatch, caplog):

    def _boom():
        raise AgentIntegrationSpecError("testid duplicado: output-mcp-agent-x")

    monkeypatch.setattr(specs_mod, "mcp_agent_specs", _boom)
    with caplog.at_level("WARNING", logger="workflow_app.main_window"):
        column = _rebuild_column(win)

    assert _agent_buttons(column) == []
    assert _by_testid(column, "output-mcp-action-main")
    assert any(
        "specs MCP suplementares ignoradas" in record.message
        for record in caplog.records
    )


def test_registry_que_falha_no_import_nao_derruba_a_coluna(win, monkeypatch, caplog):
    """Registry invalido levanta no IMPORT, nao na chamada.

    `_MCP_AGENT_SPECS` e um literal de modulo e `McpAgentSpec.__post_init__`
    valida na construcao: uma entrada malformada gravada por `/mcp:create-agent`
    explode ao EXECUTAR o modulo, ou seja, no proprio from-import de
    `_collect_mcp_agent_specs`. Se o guard nao cobrir o import, a excecao escapa
    e `MainWindow.__init__` morre (o app nao abre).
    """
    import importlib.abc
    import importlib.util
    import sys

    module_name = "workflow_app.agent_integration_specs"

    class _ExplodingLoader(importlib.abc.Loader):
        def create_module(self, spec):
            return None

        def exec_module(self, module):
            raise AgentIntegrationSpecError(
                "slug invalido: esperado kebab-case [a-z0-9-]"
            )

    class _ExplodingFinder(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname != module_name:
                return None
            return importlib.util.spec_from_loader(fullname, _ExplodingLoader())

    monkeypatch.delitem(sys.modules, module_name, raising=False)
    monkeypatch.setattr(sys, "meta_path", [_ExplodingFinder(), *sys.meta_path])

    with caplog.at_level("WARNING", logger="workflow_app.main_window"):
        assert win._collect_mcp_agent_specs([]) == ()
        column = _rebuild_column(win)

    assert _agent_buttons(column) == []
    assert _by_testid(column, "output-mcp-action-main")
    assert any(
        "falha ao importar o registry" in record.message
        for record in caplog.records
    )


def test_colisao_com_testid_ja_montado_e_recusada(win, monkeypatch, caplog):
    colliding = McpAgentSpec(
        slug="hardening-suplementar", label="x", directive=_HARDENING_DIRECTIVE
    )
    monkeypatch.setattr(specs_mod, "mcp_agent_specs", lambda: (colliding,))

    with caplog.at_level("WARNING", logger="workflow_app.main_window"):
        column = _rebuild_column(win)
        # Segundo build passando o testid ja materializado como "existente":
        # o helper deve recusar o registry inteiro em vez de duplicar o widget.
        assert win._collect_mcp_agent_specs([colliding.testid]) == ()

    assert any(
        "specs MCP suplementares ignoradas" in record.message
        for record in caplog.records
    )
    assert len(_agent_buttons(column)) == 1
