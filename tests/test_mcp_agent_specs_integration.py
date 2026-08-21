"""Integracao das specs suplementares no setor MCP (AGENT-TASK-007).

Cobre o contrato de `output-toolbar-mcp` quando o registry de
`agent_integration_specs` tem entradas: botao REAL checkable com
`persona_prompt`, composicao apenas do que esta ativo, ordem deterministica e
rebuild sem perda nem duplicacao de widgets.

O registry canonico contem as specs persistentes `writer`, `tester` e
`art-creator`. Testes genericos
injetam specs isoladas via monkeypatch de
`workflow_app.agent_integration_specs.mcp_agent_specs` e reconstroem a coluna
com `_build_mcp_column`.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from workflow_app import agent_integration_specs as specs_mod
from workflow_app.agent_integration_specs import (
    AgentIntegrationSpecError,
    McpAgentSpec,
)
from workflow_app.config.feature_flags import (
    llm_config_v2_enabled,
    mcp_think_exec_v2_enabled,
)
from workflow_app.signal_bus import signal_bus

# Item 023 do loop 08-11 troca a action row do setor MCP SOMENTE atras de
# `SF_LLM_CONFIG_V2`: os tres botoes `output-mcp-action-{main,parallel,dual}`
# (comando escolhido pelo Main LLM) dao lugar aos grupos Thinking/Execution,
# com matriz FIXA por botao (TE-01, main_window.py `_TE_COMMANDS`). O contrato
# coberto AQUI — materializacao das specs suplementares e composicao do prompt —
# nao depende dessa moldura, entao o ancora e os pares (acao, comando base) sao
# derivados da flag em vez de hardcoded: `execution-codex` publica exatamente o
# mesmo `/mcp:codex` que o `Main MCP` legado sob Main Claude. Fica pulado apenas
# o caso que afirma a semantica legada de "o Main LLM escolhe o comando", que
# sob a flag deixou de existir; esse lado esta travado em
# `tests/test_llm_config_tab.py`, que roda os dois estados em subprocesso porque
# `feature_flags` e boot-frozen (resolve `os.environ` no import, sem reset).
_LLM_CONFIG_V2 = llm_config_v2_enabled()

_ANCHOR_ACTION = (
    "output-mcp-action-thinking-codex-ultra" if _LLM_CONFIG_V2 else "output-mcp-action-main"
)
_ACTION_TESTIDS = (
    (
        "output-mcp-action-thinking-fable",
        "output-mcp-action-thinking-opus",
        "output-mcp-action-thinking-codex-ultra",
        "output-mcp-action-thinking-kimi",
        "output-mcp-action-thinking-grok-xhigh",
        "output-mcp-action-execution-grok",
        "output-mcp-action-execution-sonnet",
        "output-mcp-action-execution-kimi",
        "output-mcp-action-execution-qwen",
        "output-mcp-action-execution-codex",
    )
    if _LLM_CONFIG_V2
    else (
        "output-mcp-action-main",
        "output-mcp-action-parallel",
        "output-mcp-action-dual",
    )
)
# Tres acoes por lado, cada uma com o comando base que ela publica: no legado o
# trio Main/Parallel/Dual sob Main Claude; sob a flag, o trio equivalente da
# matriz fixa. Grok/Qwen em Execution publicam `/mcp:grok` e `/mcp:qwen`.
_ACTION_BASE_PAIRS = (
    [
        ("output-mcp-action-thinking-codex-ultra", "/mcp:codex-ultra"),
        ("output-mcp-action-thinking-kimi", "/mcp:kimi-k3"),
        ("output-mcp-action-execution-kimi", "/mcp:kimi"),
    ]
    if _LLM_CONFIG_V2
    else [
        ("output-mcp-action-main", "/mcp:codex"),
        ("output-mcp-action-parallel", "/mcp:kimi"),
        ("output-mcp-action-dual", "/mcp:dual"),
    ]
)
_skip_under_llm_config_v2 = pytest.mark.skipif(
    _LLM_CONFIG_V2,
    reason=(
        "afirma a semantica legada (Main LLM escolhe o comando da acao MCP); "
        "sob SF_LLM_CONFIG_V2 o comando e fixo por botao (item 023) e esse lado "
        "e travado em tests/test_llm_config_tab.py"
    ),
)

_HARDENING_DIRECTIVE = (
    "no papel de engenheiro de hardening suplementar, conforme regras em "
    "ai-forge/MCP/agents/hardening-engineer-rules.md"
)
_UX_DIRECTIVE = (
    "no papel de especialista UX suplementar, conforme regras em "
    "ai-forge/MCP/agents/ux-ui-specialist.md"
)
_WRITER_DIRECTIVE = (
    "no papel de Writer, seguindo as regras em "
    "ai-forge/MCP/agents/writer.md"
)
_TESTER_DIRECTIVE = (
    "no papel de Tester, seguindo as regras em "
    "ai-forge/MCP/agents/tester.md"
)
_ART_CREATOR_DIRECTIVE = (
    "no papel de Art Creator, seguindo as regras em "
    "ai-forge/MCP/agents/art-creator.md"
)
_SEARCH_PROD_DIRECTIVE = (
    "no papel de Investigador de Ambiente de Producao, seguindo as "
    "regras em ai-forge/MCP/agents/search-prod.md"
)
_PERSISTENT_AGENTS = (
    ("writer", _WRITER_DIRECTIVE),
    ("tester", _TESTER_DIRECTIVE),
    ("art-creator", _ART_CREATOR_DIRECTIVE),
    ("search-prod", _SEARCH_PROD_DIRECTIVE),
)


@pytest.fixture
def win(qapp, monkeypatch):
    """MainWindow com teardown ORDENADO: a janela morre antes dos popups.

    Rebuildar `output-toolbar-mcp` instancia QComboBox novos, e cada combo
    registra um popup (QFrame com flag Qt.Popup) que conta como top-level em
    `QApplication.topLevelWidgets()`. O teardown global do conftest deleta os
    top-level na ordem da lista: apagar um popup ANTES do combo dono deixa
    ponteiro pendurado no C++ e derruba o processo com SIGSEGV. Destruindo a
    janela aqui primeiro, os popups ja nascem invalidos para o conftest, que
    apenas os ignora. Por isso tambem nao se usa `qtbot.addWidget`: o cleanup
    do pytest-qt chamaria `close()` no wrapper ja destruido.

    O registry servido e estado de classe e pode conter um modulo paralelo
    deixado por suites de live-reload anteriores. Zerar antes de construir a
    janela garante que estes testes monkeypatcham o mesmo modulo canonico que
    o builder consulta, sem depender da ordem global de coleta.
    """
    import shiboken6

    from workflow_app.main_window import MainWindow

    monkeypatch.setattr(MainWindow, "_agent_registry_served", None)
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
    radios = (win._chk_route_t1, win._chk_route_t2, win._chk_route_t3)
    states = (t1, t2, t3)
    if sum(states) == 1:
        radios[states.index(True)].setChecked(True)
        return
    win._terminal_route_group.setExclusive(False)
    for radio, checked in zip(radios, states, strict=True):
        radio.setChecked(checked)
    win._terminal_route_group.setExclusive(True)


def _by_testid(root: QWidget, testid: str, widget_type=None):
    """Busca por testid restrita a um tipo concreto de widget.

    Nunca usar `QWidget` aqui: materializar wrappers de TODOS os QWidget de uma
    MainWindow corrompe o teardown do PySide6 (ver nota em
    test_main_window_terminal_routes.py). Para chegar num container, subir pelo
    `parentWidget()` de um leaf conhecido.
    Sem `widget_type`, tenta QPushButton e QCheckBox (acoes MCP vs personas).
    """
    types = (widget_type,) if widget_type is not None else (QPushButton, QCheckBox)
    assert QWidget not in types, "use _row_of/_mcp_column_of para containers"
    for concrete in types:
        for widget in root.findChildren(concrete):
            if widget.property("testid") == testid:
                return widget
    raise AssertionError(f"widget nao encontrado: {testid}")


def _row_of(leaf: QWidget) -> QWidget:
    row = leaf.parentWidget()
    assert row is not None
    return row


def _action_row_of(action_btn: QWidget) -> QWidget:
    """Sobe do botao de acao ate `output-mcp-action-row`.

    No legado o botao e filho DIRETO da action row; sob `SF_LLM_CONFIG_V2` ele
    mora dentro do grupo Thinking ou Execution (item 023), que por sua vez e
    filho da action row. Subir por testid cobre os dois casos sem afrouxar a
    assercao de que a linha existe e continua sendo a mesma.
    """
    node = action_btn.parentWidget()
    while node is not None and node.property("testid") != "output-mcp-action-row":
        node = node.parentWidget()
    assert node is not None, "output-mcp-action-row nao encontrado"
    return node


def _mcp_column_of(win) -> QWidget:
    """Sobe do action-btn ate o container com testid output-toolbar-mcp."""
    node = _by_testid(win, _ANCHOR_ACTION).parentWidget()
    while node is not None and node.property("testid") != "output-toolbar-mcp":
        node = node.parentWidget()
    assert node is not None, "output-toolbar-mcp nao encontrado"
    return node


def _agent_buttons(root: QWidget) -> list[QCheckBox]:
    return [
        chk
        for chk in root.findChildren(QCheckBox)
        if str(chk.property("testid") or "").startswith("output-mcp-agent-")
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


def test_registry_vazio_nao_cria_botao_nem_linha(win, monkeypatch):
    monkeypatch.setattr(specs_mod, "mcp_agent_specs", lambda: ())
    column = _rebuild_column(win)

    assert _agent_buttons(column) == []
    assert win._mcp_agent_buttons == []


def test_registry_vazio_preserva_composicao_existente(win, monkeypatch):
    monkeypatch.setattr(specs_mod, "mcp_agent_specs", lambda: ())
    column = _rebuild_column(win)
    _set_route(win, t1=True, t2=False, t3=False)
    _set_main_llm(win, "claude")

    assert _publish_and_capture(win, _ANCHOR_ACTION, column) == [
        "/mcp:codex"
    ]


# ── Spec persistente Writer: estado ativo/inativo nas tres acoes ────────


@pytest.mark.parametrize(("agent_slug", "directive"), _PERSISTENT_AGENTS)
def test_agente_persistente_materializa_contrato_visual(
    win, agent_slug, directive
):
    column = _mcp_column_of(win)
    btn = _by_testid(column, f"output-mcp-agent-{agent_slug}")

    assert isinstance(btn, QCheckBox)
    assert btn.isCheckable()
    assert not btn.isChecked()
    assert btn.focusPolicy() == Qt.FocusPolicy.StrongFocus
    assert btn.toolTip() == directive
    assert btn.accessibleName()
    assert "#27272A" in btn.styleSheet()
    assert "#16A34A" in btn.styleSheet()
    assert _row_of(btn).property("testid") == "output-mcp-persona-checkboxes"


@pytest.mark.parametrize(("action_testid", "base"), _ACTION_BASE_PAIRS)
@pytest.mark.parametrize(("agent_slug", "directive"), _PERSISTENT_AGENTS)
def test_agente_inativo_nao_altera_as_tres_acoes(
    win, action_testid, base, agent_slug, directive
):
    column = _mcp_column_of(win)
    _set_route(win, t1=True, t2=False, t3=False)
    _set_main_llm(win, "claude")

    btn = _by_testid(column, f"output-mcp-agent-{agent_slug}")
    assert not btn.isChecked()
    sent = _publish_and_capture(win, action_testid, column)
    assert sent == [base]
    assert directive not in sent[0]


@pytest.mark.parametrize(("action_testid", "base"), _ACTION_BASE_PAIRS)
@pytest.mark.parametrize(("agent_slug", "directive"), _PERSISTENT_AGENTS)
def test_agente_ativo_anexa_uma_diretiva_nas_tres_acoes(
    win, action_testid, base, agent_slug, directive
):
    column = _mcp_column_of(win)
    _set_route(win, t1=True, t2=False, t3=False)
    _set_main_llm(win, "claude")
    _by_testid(column, f"output-mcp-agent-{agent_slug}").setChecked(True)

    sent = _publish_and_capture(win, action_testid, column)

    assert sent == [f"{base} {directive}"]
    assert sent[0].count(directive) == 1


@pytest.mark.parametrize(
    ("provider_id", "base"),
    [
        ("claude", "/mcp:codex"),
        ("kimi", "/skill:claude"),
        ("codex", "Use skill-claude. Output JSON. Prompt:"),
    ],
)
@_skip_under_llm_config_v2
@pytest.mark.parametrize(("agent_slug", "directive"), _PERSISTENT_AGENTS)
def test_agente_preserva_o_provider_selecionado(
    win, provider_id, base, agent_slug, directive
):
    column = _mcp_column_of(win)
    _set_route(win, t1=True, t2=False, t3=False)
    _set_main_llm(win, provider_id)
    _by_testid(column, f"output-mcp-agent-{agent_slug}").setChecked(True)

    sent = _publish_and_capture(win, _ANCHOR_ACTION, column)

    assert sent == [f"{base} {directive}"]


# ── Materializacao: botao real, checkable, com contrato visual ──────────────


def test_spec_vira_checkbox_em_persona_checkboxes(win, monkeypatch):
    monkeypatch.setattr(specs_mod, "mcp_agent_specs", lambda: (_spec(),))
    column = _rebuild_column(win)

    btn = _by_testid(column, "output-mcp-agent-hardening-suplementar")
    assert isinstance(btn, QCheckBox)
    assert btn.isCheckable()
    assert not btn.isChecked()
    assert btn.text() == "hardening+"
    assert btn.property("persona_prompt") == _HARDENING_DIRECTIVE
    assert btn.property("agent_slug") == "hardening-suplementar"
    assert btn.toolTip() == _HARDENING_DIRECTIVE
    assert btn.accessibleName()


def test_botao_suplementar_vive_dentro_de_output_toolbar_mcp(win, monkeypatch):
    monkeypatch.setattr(specs_mod, "mcp_agent_specs", lambda: (_spec(),))
    column = _rebuild_column(win)

    assert column.property("testid") == "output-toolbar-mcp"
    btn = _by_testid(column, "output-mcp-agent-hardening-suplementar")
    assert _row_of(btn).property("testid") == "output-mcp-persona-checkboxes"
    assert not any(
        w.property("testid") == "output-mcp-agent-buttons"
        for w in column.findChildren(QWidget)
    )


# Item 015: as 16 personas curadas da secao MCPs, na ORDEM da tupla
# `persona_specs` de `_build_mcp_column()`. A ordem e contrato de
# `_compose_mcp_text`, que concatena os prompts marcados nesta sequencia.
_CURATED_PERSONA_TESTIDS = [
    "output-mcp-persona-search-in",
    "output-mcp-persona-search-out",
    "output-mcp-persona-search-forge",
    "output-mcp-persona-controversial",
    "output-mcp-persona-hardening",
    "output-mcp-persona-criar-task",
    "output-mcp-persona-revisar-task",
    "output-mcp-persona-executor",
    "output-mcp-persona-rev-exec",
    "output-mcp-persona-revisar-qa",
    "output-mcp-persona-code-debugger",
    "output-mcp-persona-delegador",
    "output-mcp-persona-scaffolds-blueprints-updater",
    "output-mcp-persona-questioner",
    "output-mcp-persona-ux-ui",
    "output-mcp-persona-performance-engineer",
]


def test_controles_existentes_continuam_intactos(win, monkeypatch):
    """Item 015: as personas curadas sao travadas por IDENTIDADE e ORDEM.

    Substituicao de contrato: a assercao anterior era `len(...) == 16`, contagem
    nua. Ela nao protege a UI, porque um filtro por exclusao do sufixo `-rules`
    tambem devolve 16 personas, mas 12 dos 16 slugs sao outros. O que importa e
    quais personas aparecem e em que ordem: a ordem da tupla `persona_specs` e a
    ordem de composicao de `_compose_mcp_text`, entao reordenar muda o prompt
    colado. Lista, nao set, exatamente por isso.
    """
    monkeypatch.setattr(specs_mod, "mcp_agent_specs", lambda: (_spec(),))
    column = _rebuild_column(win)

    rendered = [chk.property("testid") for chk in win._mcp_persona_checkboxes]
    assert rendered[: len(_CURATED_PERSONA_TESTIDS)] == _CURATED_PERSONA_TESTIDS
    assert len(rendered) >= len(_CURATED_PERSONA_TESTIDS)
    for action_testid in _ACTION_TESTIDS:
        assert _by_testid(column, action_testid)
    # A tab bar interna (`output-mcp-tab-mcps` / `-brainstorm`) morreu em
    # 2026-07-27: as duas sub-abas viraram secoes de primeiro nivel do
    # `output-toolbar-section-selector`, entao a coluna nao tem mais nivel de
    # aba proprio.
    rendered_btns = {btn.property("testid") for btn in column.findChildren(QPushButton)}
    assert not {"output-mcp-tab-mcps", "output-mcp-tab-brainstorm"} & rendered_btns
    assert not any(
        w.property("testid") == "output-mcp-agent-buttons"
        for w in column.findChildren(QWidget)
    )


def test_extras_da_aba_agentes_entram_depois_do_prefixo_curado(win, monkeypatch):
    """Personas de output-toolbar-agentes que nao estao nas 16 curadas
    aparecem no fim de output-mcp-persona-checkboxes, sem reordenar o prefixo.
    """
    monkeypatch.setattr(specs_mod, "mcp_agent_specs", lambda: ())
    column = _rebuild_column(win)
    rendered = [chk.property("testid") for chk in win._mcp_persona_checkboxes]
    assert rendered[: len(_CURATED_PERSONA_TESTIDS)] == _CURATED_PERSONA_TESTIDS
    scanned = {slug for slug, _rel in win._scan_persona_files()}
    extra_ids = rendered[len(_CURATED_PERSONA_TESTIDS) :]
    assert extra_ids, "esperava extras da aba Agentes depois das 16 curadas"
    for testid in extra_ids:
        assert str(testid).startswith("output-mcp-persona-")
        slug = str(testid)[len("output-mcp-persona-") :]
        assert slug in scanned
    row = _row_of(_by_testid(column, "output-mcp-persona-search-in", QCheckBox))
    assert row.property("testid") == "output-mcp-persona-checkboxes"


@pytest.mark.skipif(
    not mcp_think_exec_v2_enabled(),
    reason="colunas Thinking/Execution so existem com SF_MCP_THINK_EXEC_V2=1",
)
def test_thinking_execution_sao_colunas_a_direita_estilo_main_llm(win):
    """Thinking e Execution: label em cima, canto direito, estilo queue-div-main-llm."""
    column = _mcp_column_of(win)

    def _group_of(leaf_testid: str, group_testid: str) -> QWidget:
        node = _by_testid(column, leaf_testid).parentWidget()
        while node is not None and node.property("testid") != group_testid:
            node = node.parentWidget()
        assert node is not None, group_testid
        return node

    thinking = _group_of(
        "output-mcp-action-thinking-opus", "output-mcp-action-thinking"
    )
    execution = _group_of(
        "output-mcp-action-execution-sonnet", "output-mcp-action-execution"
    )
    assert isinstance(thinking.layout(), QVBoxLayout)
    assert isinstance(execution.layout(), QVBoxLayout)
    th_label = thinking.layout().itemAt(0).widget()
    ex_label = execution.layout().itemAt(0).widget()
    assert isinstance(th_label, QLabel)
    assert isinstance(ex_label, QLabel)
    assert th_label.text() == "Thinking"
    assert ex_label.text() == "Execution"

    col_layout = column.layout()
    assert isinstance(col_layout, QHBoxLayout)
    last = col_layout.itemAt(col_layout.count() - 1).widget()
    action_row = _action_row_of(_by_testid(column, _ANCHOR_ACTION))
    assert last is action_row
    assert thinking.parentWidget() is action_row
    assert execution.parentWidget() is action_row
    personas = _row_of(_by_testid(column, "output-mcp-persona-search-in", QCheckBox))
    personas_idx = col_layout.indexOf(personas.parentWidget())
    action_idx = col_layout.indexOf(action_row)
    assert 0 <= personas_idx < action_idx


# ── Composicao: so entra o que esta ativo ───────────────────────────────────


@pytest.mark.parametrize(("action_testid", "base"), _ACTION_BASE_PAIRS)
def test_botao_inativo_nao_altera_prompt_nas_tres_acoes(
    win, monkeypatch, action_testid, base
):
    monkeypatch.setattr(specs_mod, "mcp_agent_specs", lambda: (_spec(),))
    column = _rebuild_column(win)
    _set_route(win, t1=True, t2=False, t3=False)
    _set_main_llm(win, "claude")

    assert _publish_and_capture(win, action_testid, column) == [base]


@pytest.mark.parametrize(("action_testid", "base"), _ACTION_BASE_PAIRS)
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

    sent = _publish_and_capture(win, _ANCHOR_ACTION, column)

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

    sent = _publish_and_capture(win, _ANCHOR_ACTION, column)

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

    sent = _publish_and_capture(win, _ANCHOR_ACTION, column)

    assert sent == [
        f"/mcp:codex {_UX_DIRECTIVE}; e depois disso {_HARDENING_DIRECTIVE}"
    ]
    assert [btn.property("testid") for btn in _agent_buttons(column)] == [
        "output-mcp-agent-ux-suplementar",
        "output-mcp-agent-hardening-suplementar",
    ]


def test_suplementos_vivem_no_mesmo_container_de_personas(win, monkeypatch):
    monkeypatch.setattr(specs_mod, "mcp_agent_specs", lambda: (_spec(),))
    column = _rebuild_column(win)

    agent_row = _row_of(_by_testid(column, "output-mcp-agent-hardening-suplementar"))
    persona_row = _row_of(
        _by_testid(column, "output-mcp-persona-performance-engineer", QCheckBox)
    )
    action_row = _action_row_of(_by_testid(column, _ANCHOR_ACTION))
    assert persona_row is agent_row
    assert persona_row.property("testid") == "output-mcp-persona-checkboxes"
    assert action_row.property("testid") == "output-mcp-action-row"
    assert action_row is not persona_row
    rendered = [
        chk.property("testid") for chk in win._mcp_persona_checkboxes
    ]
    assert rendered[0] == "output-mcp-persona-search-in"
    assert rendered[-1] == "output-mcp-agent-hardening-suplementar"


def test_specs_vivem_num_flow_unico_com_quebra_por_largura(win, monkeypatch):
    """Contrato responsivo: um container so, quebra ditada pela largura.

    `output-mcp-agent-buttons` foi absorvido por `output-mcp-persona-checkboxes`.
    Specs suplementares moram no mesmo flow das personas, no fim da sequencia.
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
        "output-mcp-persona-checkboxes"
    }

    container = _row_of(buttons[0])
    all_chks = [
        chk
        for chk in container.findChildren(QCheckBox)
        if chk.property("testid")
    ]
    assert _rendered_lines(container, all_chks, 260) > _rendered_lines(
        container, all_chks, 900
    )


def test_gap_vertical_entre_linhas_de_agentes_e_de_1px(win, monkeypatch):
    monkeypatch.setattr(
        specs_mod,
        "mcp_agent_specs",
        lambda: tuple(_spec(slug=f"agente-{i}", label=f"a{i}") for i in range(5)),
    )
    column = _rebuild_column(win)
    buttons = _agent_buttons(column)
    container = _row_of(buttons[0])
    all_chks = [
        chk
        for chk in container.findChildren(QCheckBox)
        if chk.property("testid")
    ]

    assert _rendered_lines(container, all_chks, 110) >= 2
    tops = sorted({chk.geometry().y() for chk in all_chks})
    heights = {chk.geometry().height() for chk in all_chks}

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

    curated = [
        chk
        for chk in personas
        if chk.property("testid") in _CURATED_PERSONA_TESTIDS
    ]
    assert [chk.property("testid") for chk in curated] == _CURATED_PERSONA_TESTIDS
    assert len(personas) >= 16
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

    sent = _publish_and_capture(win, _ANCHOR_ACTION, column)

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
    assert _by_testid(column, _ANCHOR_ACTION)
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
    assert _by_testid(column, _ANCHOR_ACTION)
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
