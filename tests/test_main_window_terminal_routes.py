"""Regression tests for terminal route checkboxes (T1/T2/T3) in MainWindow.

Os checkboxes vivem no header de cada terminal desde
07-27-workflow-app-header-toggles-llm-unico (I1.1/I1.2); o bloco unico
`terminal-route-toggles` nao existe mais.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from workflow_app.signal_bus import signal_bus


def _new_window(qtbot):
    from workflow_app.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    return win


@pytest.fixture
def owned_window(qapp):
    """MainWindow que se destroi sozinha, fora do teardown do conftest.

    Necessaria para os testes que chamam metodos de producao que varrem
    `findChildren(QWidget)` (ex.: `_codex_terminal_available`). Sob `qtbot`,
    materializar wrapper Python de todo widget da janela corrompe o
    `_cleanup_qt_widgets` do conftest com segfault no `shiboken6.delete` —
    armadilha ja documentada em tests/test_main_window.py:36. Destruindo a
    janela aqui, o conftest nao encontra mais nada para deletar.
    """
    import shiboken6

    from workflow_app.main_window import MainWindow

    window = MainWindow()
    yield window
    if shiboken6.isValid(window):
        window.close()
        shiboken6.delete(window)


def _set_route(win, *, t1: bool, t2: bool, t3: bool) -> None:
    win._chk_route_t1.setChecked(t1)
    win._chk_route_t2.setChecked(t2)
    win._chk_route_t3.setChecked(t3)


# I2.1: os radios `output-mcp-provider-*` foram eliminados. O provider dos
# botoes MCP passa a sair do Main LLM (`queue-div-main-llm`), fonte de verdade
# unica lida por `MainWindow._current_llm_provider()`.
_MAIN_LLM_TESTIDS = {
    "claude": "queue-radio-main-claude",
    "codex": "queue-radio-main-codex",
    "kimi": "queue-chk-force-kimi",
}


def _set_main_llm(win, provider: str) -> None:
    _radio_by_testid(win, _MAIN_LLM_TESTIDS[provider]).setChecked(True)


def _ancestor_testids(widget) -> list[str]:
    """Testids da cadeia de parents de `widget`, do mais proximo ao topo.

    Subimos a cadeia em vez de usar `findChildren(QWidget)`: materializar
    wrapper Python de todo widget da janela corrompe o teardown do conftest
    (`_cleanup_qt_widgets`) com segfault no `shiboken6.delete` — mesma
    armadilha ja documentada em tests/test_main_window.py:36.
    """
    chain: list[str] = []
    node = widget.parentWidget()
    while node is not None:
        chain.append(str(node.property("testid") or ""))
        node = node.parentWidget()
    return chain


def _button_by_testid(win, testid: str):
    from PySide6.QtWidgets import QPushButton

    for btn in win.findChildren(QPushButton):
        if btn.property("testid") == testid:
            return btn
    raise AssertionError(f"botao nao encontrado: {testid}")


def _radio_by_testid(win, testid: str):
    from PySide6.QtWidgets import QRadioButton

    for rb in win.findChildren(QRadioButton):
        if rb.property("testid") == testid:
            return rb
    raise AssertionError(f"radio nao encontrado: {testid}")


def _checkbox_by_testid(win, testid: str):
    from PySide6.QtWidgets import QCheckBox

    for chk in win.findChildren(QCheckBox):
        if chk.property("testid") == testid:
            return chk
    raise AssertionError(f"checkbox nao encontrado: {testid}")


def test_terminal_route_toggles_exist(qtbot):
    win = _new_window(qtbot)

    assert win._chk_route_t1.property("testid") == "terminal-route-t1"
    assert win._chk_route_t2.property("testid") == "terminal-route-t2"
    assert win._chk_route_t3.property("testid") == "terminal-route-t3"


def test_route_toggles_block_no_longer_exists(qtbot):
    """Criterio 1: o bloco unico `terminal-route-toggles` foi dissolvido."""
    win = _new_window(qtbot)

    for chk in (win._chk_route_t1, win._chk_route_t2, win._chk_route_t3):
        assert "terminal-route-toggles" not in _ancestor_testids(chk)
    assert "terminal-route-toggles" not in _ancestor_testids(win._chk_notes_t1)


def test_route_toggles_live_in_their_own_terminal_headers(qtbot):
    """Criterio 3: cada checkbox mora no header do seu proprio terminal."""
    win = _new_window(qtbot)

    expected = {
        "terminal-route-t1": "terminal-interactive-label-bar",
        "terminal-route-t2": "terminal-workspace-label-bar",
        "terminal-route-t3": "terminal-codex-label-bar",
    }
    for chk_testid, header_testid in expected.items():
        chk = _checkbox_by_testid(win, chk_testid)
        parent = chk.parentWidget()
        assert parent is not None
        assert parent.property("testid") == header_testid


def test_codex_header_bar_exists_with_label_and_t3(owned_window):
    """Criterio 2: o T3 ganhou header proprio e continua alcancavel.

    Usa `owned_window` (nao `qtbot`) porque chama `_codex_terminal_available()`,
    que varre `findChildren(QWidget)` — ver docstring da fixture.
    """
    from PySide6.QtWidgets import QLabel

    win = owned_window

    bar = win._chk_route_t3.parentWidget()
    assert bar is not None
    assert bar.property("testid") == "terminal-codex-label-bar"
    labels = [lb.text().strip() for lb in bar.findChildren(QLabel)]
    assert "CODEX" in labels

    # Criterio 2: o wrapper novo do T3 nao pode esconder o painel do detector
    # de sink. `_codex_terminal_available()` faz busca RECURSIVA, entao o
    # wrapper intermediario tem que ser transparente para ele.
    assert win._codex_terminal_available() is True

    panel = win._workspace_panel_xterm
    assert panel.property("testid") == "terminal-codex-output"
    assert "terminal-codex-label-bar" not in _ancestor_testids(panel)


def test_notes_t1_lives_inside_interactive_notes_after_input(qtbot):
    """Criterio 4 e 13: unico Notes, dentro do footer do T1, depois do input."""
    from PySide6.QtWidgets import QCheckBox, QLineEdit

    win = _new_window(qtbot)

    chk = _checkbox_by_testid(win, "terminal-notes-t1")
    footer = chk.parentWidget()
    assert footer is not None
    assert footer.property("testid") == "terminal-interactive-notes"

    layout = footer.layout()
    idx_input = next(
        i
        for i in range(layout.count())
        if isinstance(layout.itemAt(i).widget(), QLineEdit)
    )
    idx_chk = next(
        i for i in range(layout.count()) if layout.itemAt(i).widget() is chk
    )
    assert idx_chk > idx_input

    # Criterio 13: `terminal-notes-` casa exatamente um widget na janela toda.
    notes_testids = [
        str(w.property("testid"))
        for w in win.findChildren(QCheckBox)
        if str(w.property("testid") or "").startswith("terminal-notes-")
    ]
    assert notes_testids == ["terminal-notes-t1"]


def test_main_llm_switch_updates_mcp_and_brainstorm_in_same_instance(qtbot):
    """Criterio 7: um unico seletor governa MCP e Brainstorm, sem rebuild."""
    win = _new_window(qtbot)

    assert win._current_llm_provider() == "claude"
    assert win._get_brainstorm_runtime_provider() == "Claude"
    claude_cmd = win._mcp_toolbar_commands["claude"]["main"][0]

    _set_main_llm(win, "kimi")
    assert win._current_llm_provider() == "kimi"
    assert win._get_brainstorm_runtime_provider() == "Kimi"
    kimi_cmd = win._mcp_toolbar_commands["kimi"]["main"][0]
    assert kimi_cmd != claude_cmd

    _set_main_llm(win, "codex")
    assert win._current_llm_provider() == "codex"
    assert win._get_brainstorm_runtime_provider() == "Codex"

    _set_main_llm(win, "claude")
    assert win._current_llm_provider() == "claude"
    assert win._get_brainstorm_runtime_provider() == "Claude"


def test_mcp_toolbar_uses_main_llm_and_three_actions(qtbot):
    win = _new_window(qtbot)

    # Criterio 1/6: os radios de provider do MCP nao existem mais; quem manda
    # e o queue-div-main-llm.
    from PySide6.QtWidgets import QRadioButton

    orphan = [
        rb.property("testid")
        for rb in win.findChildren(QRadioButton)
        if str(rb.property("testid") or "").startswith("output-mcp-provider-")
    ]
    assert orphan == []
    assert win._current_llm_provider() == "claude"

    personas = {
        "output-mcp-persona-search-in": "search-in",
        "output-mcp-persona-search-out": "search-out",
        "output-mcp-persona-controversial": "controversial",
        "output-mcp-persona-hardening": "hardening",
        "output-mcp-persona-scaffolds-blueprints-updater": "scaffold-update",
        "output-mcp-persona-questioner": "questionador",
        "output-mcp-persona-ux-ui": "UX/UI",
        "output-mcp-persona-performance-engineer": "performance",
    }
    for testid, label in personas.items():
        assert _checkbox_by_testid(win, testid).text() == label

    actions = {
        "output-mcp-action-main": "Main MCP",
        "output-mcp-action-parallel": "Parallel",
        "output-mcp-action-dual": "Dual",
    }
    for testid, label in actions.items():
        assert _button_by_testid(win, testid).text() == label


def test_ws_rules_button_lives_in_rules_subtab_and_publishes_workspace_rules(qtbot):
    from workflow_app.config.app_state import app_state
    from workflow_app.config.config_parser import PipelineConfig

    app_state.clear_all()
    win = _new_window(qtbot)
    _set_route(win, t1=True, t2=False, t3=False)
    app_state.set_project_config(
        PipelineConfig(
            config_path="/tmp/project/.claude/project.json",
            project_name="project-a",
            brief_root="brief",
            docs_root="docs",
            wbs_root="wbs",
            workspace_root="output/workspace/project-a",
        )
    )

    btn = _button_by_testid(win, "queue-btn-ws-rules-path")
    assert btn.text() == "ws-rules"
    ancestor = btn.parentWidget()
    while (
        ancestor is not None
        and ancestor.property("testid") != "queue-subtab-insertions-rules"
    ):
        ancestor = ancestor.parentWidget()
    assert ancestor is not None

    sent_t1: list[str] = []
    signal_bus.paste_text_in_terminal.connect(sent_t1.append)
    try:
        btn.click()
    finally:
        signal_bus.paste_text_in_terminal.disconnect(sent_t1.append)
        app_state.clear_all()

    assert sent_t1 == ["output/workspace/project-a/rules"]


def test_mcp_toolbar_claude_main_command_routes_by_toggles_not_provider(qtbot):
    # Refactor 2026-05-24 + I2.1: o Main LLM escolhe o COMANDO; o terminal e
    # decidido pelos checkboxes de rota nos headers. T1 marcado -> vai a T1.
    win = _new_window(qtbot)
    _set_route(win, t1=True, t2=False, t3=False)

    sent_t1: list[str] = []
    sent_t2: list[str] = []
    signal_bus.paste_text_in_terminal.connect(sent_t1.append)
    signal_bus.paste_text_in_workspace_terminal.connect(sent_t2.append)
    try:
        _set_main_llm(win, "claude")
        _button_by_testid(win, "output-mcp-action-main").click()
    finally:
        signal_bus.paste_text_in_terminal.disconnect(sent_t1.append)
        signal_bus.paste_text_in_workspace_terminal.disconnect(sent_t2.append)

    assert sent_t1 == ["/mcp:codex"]
    assert sent_t2 == []


def test_mcp_toolbar_provider_does_not_force_terminal_when_no_toggle(qtbot):
    # Sem nenhum checkbox de rota marcado, a acao MCP e no-op (o provider nao
    # força terminal). Garante que a função de roteamento saiu do provider.
    win = _new_window(qtbot)
    _set_route(win, t1=False, t2=False, t3=False)

    sent_t1: list[str] = []
    sent_t2: list[str] = []
    signal_bus.paste_text_in_terminal.connect(sent_t1.append)
    signal_bus.paste_text_in_workspace_terminal.connect(sent_t2.append)
    try:
        _set_main_llm(win, "claude")
        _button_by_testid(win, "output-mcp-action-main").click()
    finally:
        signal_bus.paste_text_in_terminal.disconnect(sent_t1.append)
        signal_bus.paste_text_in_workspace_terminal.disconnect(sent_t2.append)

    assert sent_t1 == []
    assert sent_t2 == []


def test_mcp_toolbar_appends_selected_persona_prompt(qtbot):
    win = _new_window(qtbot)
    _set_route(win, t1=True, t2=False, t3=False)

    sent_t1: list[str] = []
    signal_bus.paste_text_in_terminal.connect(sent_t1.append)
    try:
        _set_main_llm(win, "claude")
        _checkbox_by_testid(win, "output-mcp-persona-controversial").setChecked(True)
        _button_by_testid(win, "output-mcp-action-main").click()
    finally:
        signal_bus.paste_text_in_terminal.disconnect(sent_t1.append)

    assert sent_t1 == [
        "/mcp:codex no papel de controversial, conforme regras em "
        "ai-forge/MCP/agents/controversial-devils-advocate-rules.md"
    ]


def test_mcp_toolbar_joins_multiple_persona_prompts_in_ui_order(qtbot):
    win = _new_window(qtbot)
    _set_route(win, t1=True, t2=False, t3=False)

    sent_t1: list[str] = []
    signal_bus.paste_text_in_terminal.connect(sent_t1.append)
    try:
        _set_main_llm(win, "claude")
        _checkbox_by_testid(win, "output-mcp-persona-search-in").setChecked(True)
        _checkbox_by_testid(win, "output-mcp-persona-hardening").setChecked(True)
        _button_by_testid(win, "output-mcp-action-main").click()
    finally:
        signal_bus.paste_text_in_terminal.disconnect(sent_t1.append)

    assert sent_t1 == [
        "/mcp:codex no papel de search-in, conforme regras em "
        "ai-forge/MCP/agents/search-in-rules.md; e depois disso "
        "no papel de engenheiro de hardening, conforme regras em "
        "ai-forge/MCP/agents/hardening-engineer-rules.md"
    ]


def test_mcp_toolbar_last_personas_have_exact_paths_and_order(qtbot):
    """Refactor 07-27: as 4 linhas fixas viraram um container unico.

    Nao existe mais `output-mcp-persona-checkboxes-4`: todas as personas moram
    em `output-mcp-persona-checkboxes`, com flow responsivo (largura do proprio
    label, quebra por largura da janela). A ordem da UI — que e a ordem da
    composicao do prompt — continua sendo contrato.
    """
    win = _new_window(qtbot)
    expected = [
        (
            "output-mcp-persona-scaffolds-blueprints-updater",
            "ai-forge/MCP/agents/scaffolds-blueprints-updater.md",
        ),
        ("output-mcp-persona-questioner", "ai-forge/MCP/agents/questioner-rules.md"),
        ("output-mcp-persona-ux-ui", "ai-forge/MCP/agents/ux-ui-specialist.md"),
        (
            "output-mcp-persona-performance-engineer",
            "ai-forge/MCP/agents/performance-engineer.md",
        ),
    ]
    # Partir do checkbox conhecido evita materializar wrappers de TODOS os
    # QWidget da MainWindow, operacao que corrompe o teardown do PySide6.
    row = _checkbox_by_testid(win, expected[0][0]).parentWidget()
    assert row is not None
    assert row.property("testid") == "output-mcp-persona-checkboxes"
    row_checkboxes = row.findChildren(type(_checkbox_by_testid(win, expected[0][0])))
    assert len(row_checkboxes) == 16
    assert [checkbox.property("testid") for checkbox in row_checkboxes[-4:]] == [
        testid for testid, _path in expected
    ]
    for testid, path in expected:
        assert path in str(_checkbox_by_testid(win, testid).property("persona_prompt"))


def test_mcp_toolbar_joins_old_and_fourth_row_personas_in_ui_order(qtbot):
    win = _new_window(qtbot)
    _set_route(win, t1=True, t2=False, t3=False)

    sent_t1: list[str] = []
    signal_bus.paste_text_in_terminal.connect(sent_t1.append)
    try:
        _set_main_llm(win, "claude")
        _checkbox_by_testid(win, "output-mcp-persona-search-in").setChecked(True)
        _checkbox_by_testid(
            win, "output-mcp-persona-performance-engineer"
        ).setChecked(True)
        _button_by_testid(win, "output-mcp-action-main").click()
    finally:
        signal_bus.paste_text_in_terminal.disconnect(sent_t1.append)

    assert sent_t1 == [
        "/mcp:codex no papel de search-in, conforme regras em "
        "ai-forge/MCP/agents/search-in-rules.md; e depois disso "
        "no papel de performance engineer, conforme regras em "
        "ai-forge/MCP/agents/performance-engineer.md"
    ]


def test_mcp_toolbar_kimi_command_routes_by_toggle(qtbot):
    # Kimi seleciona o comando /skill:claude; o toggle T2 manda para T2.
    win = _new_window(qtbot)
    _set_route(win, t1=False, t2=True, t3=False)

    sent_t1: list[str] = []
    sent_t2: list[str] = []
    signal_bus.paste_text_in_terminal.connect(sent_t1.append)
    signal_bus.paste_text_in_workspace_terminal.connect(sent_t2.append)
    try:
        _set_main_llm(win, "kimi")
        _button_by_testid(win, "output-mcp-action-main").click()
    finally:
        signal_bus.paste_text_in_terminal.disconnect(sent_t1.append)
        signal_bus.paste_text_in_workspace_terminal.disconnect(sent_t2.append)

    assert sent_t1 == []
    assert sent_t2 == ["/skill:claude"]


def test_mcp_toolbar_codex_parallel_publishes_purple_parallel_to_t3(
    qtbot, monkeypatch,
):
    win = _new_window(qtbot)
    _set_route(win, t1=False, t2=False, t3=True)

    xterm_calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        win,
        "_xterm_inject_text",
        lambda text, with_enter=False: xterm_calls.append((text, with_enter)) or True,
    )

    _set_main_llm(win, "codex")
    _button_by_testid(win, "output-mcp-action-parallel").click()

    assert xterm_calls == [("Use skill-kimi. Output JSON. Prompt: ", False)]


def test_mcp_toolbar_codex_persona_prompt_has_single_spacing(qtbot, monkeypatch):
    win = _new_window(qtbot)
    _set_route(win, t1=False, t2=False, t3=True)

    xterm_calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        win,
        "_xterm_inject_text",
        lambda text, with_enter=False: xterm_calls.append((text, with_enter)) or True,
    )

    _set_main_llm(win, "codex")
    _checkbox_by_testid(win, "output-mcp-persona-hardening").setChecked(True)
    _button_by_testid(win, "output-mcp-action-parallel").click()

    assert xterm_calls == [
        (
            "Use skill-kimi. Output JSON. Prompt: no papel de engenheiro de "
            "hardening, conforme regras em "
            "ai-forge/MCP/agents/hardening-engineer-rules.md",
            False,
        )
    ]


def test_publish_routes_to_t1_only(qtbot, monkeypatch):
    win = _new_window(qtbot)
    _set_route(win, t1=True, t2=False, t3=False)

    sent_t1: list[str] = []
    sent_t3: list[str] = []
    focus_t1: list[int] = []
    xterm_calls: list[tuple[str, bool]] = []

    monkeypatch.setattr(
        win,
        "_xterm_inject_text",
        lambda text, with_enter=False: xterm_calls.append((text, with_enter)),
    )

    signal_bus.paste_text_in_terminal.connect(sent_t1.append)
    signal_bus.paste_text_in_workspace_terminal.connect(sent_t3.append)
    _on_focus = lambda: focus_t1.append(1)
    signal_bus.focus_interactive_terminal.connect(_on_focus)
    try:
        win._publish_to_terminal("echo t1")
    finally:
        signal_bus.paste_text_in_terminal.disconnect(sent_t1.append)
        signal_bus.paste_text_in_workspace_terminal.disconnect(sent_t3.append)
        signal_bus.focus_interactive_terminal.disconnect(_on_focus)

    assert sent_t1 == ["echo t1"]
    assert sent_t3 == []
    assert xterm_calls == []
    assert focus_t1 == [1]


def test_publish_routes_to_t2_only(qtbot, monkeypatch):
    win = _new_window(qtbot)
    _set_route(win, t1=False, t2=True, t3=False)

    sent_t1: list[str] = []
    sent_t3: list[str] = []
    focus_t1: list[int] = []
    xterm_calls: list[tuple[str, bool]] = []

    monkeypatch.setattr(
        win,
        "_xterm_inject_text",
        lambda text, with_enter=False: xterm_calls.append((text, with_enter)),
    )

    signal_bus.paste_text_in_terminal.connect(sent_t1.append)
    signal_bus.paste_text_in_workspace_terminal.connect(sent_t3.append)
    _on_focus = lambda: focus_t1.append(1)
    signal_bus.focus_interactive_terminal.connect(_on_focus)
    try:
        win._publish_to_terminal("echo t2")
    finally:
        signal_bus.paste_text_in_terminal.disconnect(sent_t1.append)
        signal_bus.paste_text_in_workspace_terminal.disconnect(sent_t3.append)
        signal_bus.focus_interactive_terminal.disconnect(_on_focus)

    assert sent_t1 == []
    assert sent_t3 == ["echo t2"]
    assert xterm_calls == []
    assert focus_t1 == []


def test_publish_routes_to_t3_only(qtbot, monkeypatch):
    win = _new_window(qtbot)
    _set_route(win, t1=False, t2=False, t3=True)

    sent_t1: list[str] = []
    sent_t3: list[str] = []
    focus_t1: list[int] = []
    xterm_calls: list[tuple[str, bool]] = []

    monkeypatch.setattr(
        win,
        "_xterm_inject_text",
        lambda text, with_enter=False: xterm_calls.append((text, with_enter)),
    )

    signal_bus.paste_text_in_terminal.connect(sent_t1.append)
    signal_bus.paste_text_in_workspace_terminal.connect(sent_t3.append)
    _on_focus = lambda: focus_t1.append(1)
    signal_bus.focus_interactive_terminal.connect(_on_focus)
    try:
        win._publish_to_terminal("echo t3")
    finally:
        signal_bus.paste_text_in_terminal.disconnect(sent_t1.append)
        signal_bus.paste_text_in_workspace_terminal.disconnect(sent_t3.append)
        signal_bus.focus_interactive_terminal.disconnect(_on_focus)

    assert sent_t1 == []
    assert sent_t3 == []
    assert xterm_calls == [("echo t3", False)]
    assert focus_t1 == []


def test_publish_routes_to_all_with_t1_focus_priority(qtbot, monkeypatch):
    win = _new_window(qtbot)
    _set_route(win, t1=True, t2=True, t3=True)

    sent_t1: list[str] = []
    sent_t3: list[str] = []
    focus_t1: list[int] = []
    xterm_calls: list[tuple[str, bool]] = []

    monkeypatch.setattr(
        win,
        "_xterm_inject_text",
        lambda text, with_enter=False: xterm_calls.append((text, with_enter)),
    )

    signal_bus.paste_text_in_terminal.connect(sent_t1.append)
    signal_bus.paste_text_in_workspace_terminal.connect(sent_t3.append)
    _on_focus = lambda: focus_t1.append(1)
    signal_bus.focus_interactive_terminal.connect(_on_focus)
    try:
        win._publish_to_terminal("echo all")
    finally:
        signal_bus.paste_text_in_terminal.disconnect(sent_t1.append)
        signal_bus.paste_text_in_workspace_terminal.disconnect(sent_t3.append)
        signal_bus.focus_interactive_terminal.disconnect(_on_focus)

    assert sent_t1 == ["echo all"]
    assert sent_t3 == ["echo all"]
    assert xterm_calls == [("echo all", False)]
    assert focus_t1 == [1]


# ── Snapshot-based publish report (AGENT-TASK-005) ───────────────────────────


def test_capture_terminal_route_snapshot_is_immutable(qtbot):
    from workflow_app.main_window import TerminalRouteSnapshot

    win = _new_window(qtbot)
    _set_route(win, t1=True, t2=False, t3=False)
    win._chk_notes_t1.setChecked(True)

    snap = win._capture_terminal_route_snapshot()
    assert isinstance(snap, TerminalRouteSnapshot)
    assert snap.t1 is True
    assert snap.t2 is False
    assert snap.t3 is False
    assert snap.notes_t1 is True
    assert not hasattr(snap, "notes_t2")  # I1.5: eixo eliminado
    assert snap.requested_destinations() == ("T1",)
    assert snap.has_any_terminal_route() is True

    # Mutating widgets after capture does not change the snapshot.
    _set_route(win, t1=False, t2=True, t3=True)
    win._chk_notes_t1.setChecked(False)
    assert snap.t1 is True
    assert snap.t2 is False
    assert snap.t3 is False
    assert snap.notes_t1 is True


def test_publish_report_no_route_is_silent_empty(qtbot):
    win = _new_window(qtbot)
    _set_route(win, t1=False, t2=False, t3=False)
    snap = win._capture_terminal_route_snapshot()

    sent_t1: list[str] = []
    signal_bus.paste_text_in_terminal.connect(sent_t1.append)
    try:
        report = win._publish_to_terminal_report("echo nowhere", snap)
    finally:
        signal_bus.paste_text_in_terminal.disconnect(sent_t1.append)

    assert report.requested == ()
    assert report.accepted == ()
    assert report.failed == ()
    assert report.notes_copied == ()
    assert report.errors == ()
    assert sent_t1 == []


def test_publish_report_uses_snapshot_not_live_toggles(qtbot, monkeypatch):
    win = _new_window(qtbot)
    _set_route(win, t1=True, t2=False, t3=False)
    snap = win._capture_terminal_route_snapshot()

    # Flip toggles after snapshot — report must still target T1 only.
    _set_route(win, t1=False, t2=True, t3=True)
    xterm_calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        win,
        "_xterm_inject_text",
        lambda text, with_enter=False: xterm_calls.append((text, with_enter)) or True,
    )

    sent_t1: list[str] = []
    sent_t2: list[str] = []
    signal_bus.paste_text_in_terminal.connect(sent_t1.append)
    signal_bus.paste_text_in_workspace_terminal.connect(sent_t2.append)
    try:
        report = win._publish_to_terminal_report("echo snap", snap)
    finally:
        signal_bus.paste_text_in_terminal.disconnect(sent_t1.append)
        signal_bus.paste_text_in_workspace_terminal.disconnect(sent_t2.append)

    assert sent_t1 == ["echo snap"]
    assert sent_t2 == []
    assert xterm_calls == []
    assert report.requested == ("T1",)
    assert report.accepted == ("T1",)
    assert report.failed == ()
    assert report.notes_copied == ()


def test_publish_report_t1_t2_t3_and_identical_payload(qtbot, monkeypatch):
    from workflow_app.main_window import TerminalRouteSnapshot

    win = _new_window(qtbot)
    snap = TerminalRouteSnapshot(t1=True, t2=True, t3=True)
    payload = "PROMPT-IDENTICO-ABC"

    sent_t1: list[str] = []
    sent_t2: list[str] = []
    xterm_calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        win,
        "_xterm_inject_text",
        lambda text, with_enter=False: xterm_calls.append((text, with_enter)) or True,
    )
    signal_bus.paste_text_in_terminal.connect(sent_t1.append)
    signal_bus.paste_text_in_workspace_terminal.connect(sent_t2.append)
    try:
        report = win._publish_to_terminal_report(payload, snap)
    finally:
        signal_bus.paste_text_in_terminal.disconnect(sent_t1.append)
        signal_bus.paste_text_in_workspace_terminal.disconnect(sent_t2.append)

    assert sent_t1 == [payload]
    assert sent_t2 == [payload]
    assert xterm_calls == [(payload, False)]
    assert report.requested == ("T1", "T2", "T3")
    assert report.accepted == ("T1", "T2", "T3")
    assert report.failed == ()


def test_publish_report_notes_t1_single_clipboard_copy(qtbot):
    """Notes so existe para o T1 (I1.3): T2 marcado publica direto no terminal."""
    from workflow_app.main_window import TerminalRouteSnapshot

    win = _new_window(qtbot)
    snap = TerminalRouteSnapshot(t1=True, t2=True, t3=False, notes_t1=True)
    payload = "notes-payload"

    sent_t1: list[str] = []
    sent_t2: list[str] = []
    toasts: list[tuple] = []
    signal_bus.paste_text_in_terminal.connect(sent_t1.append)
    signal_bus.paste_text_in_workspace_terminal.connect(sent_t2.append)
    signal_bus.toast_requested.connect(lambda msg, kind: toasts.append((msg, kind)))
    try:
        report = win._publish_to_terminal_report(payload, snap)
    finally:
        signal_bus.paste_text_in_terminal.disconnect(sent_t1.append)
        signal_bus.paste_text_in_workspace_terminal.disconnect(sent_t2.append)

    assert sent_t1 == []
    assert sent_t2 == [payload]
    assert report.notes_copied == ("T1",)
    assert report.accepted == ("T1", "T2")
    assert report.failed == ()
    assert QApplication_clipboard_text() == payload
    assert any("Notas" in t[0] for t in toasts)


def QApplication_clipboard_text() -> str:
    from PySide6.QtWidgets import QApplication

    return QApplication.clipboard().text()


def test_publish_report_t3_failure_no_fallback(qtbot, monkeypatch):
    from workflow_app.main_window import TerminalRouteSnapshot

    win = _new_window(qtbot)
    snap = TerminalRouteSnapshot(t1=False, t2=False, t3=True)
    monkeypatch.setattr(
        win,
        "_xterm_inject_text",
        lambda text, with_enter=False: False,
    )
    sent_t1: list[str] = []
    sent_t2: list[str] = []
    signal_bus.paste_text_in_terminal.connect(sent_t1.append)
    signal_bus.paste_text_in_workspace_terminal.connect(sent_t2.append)
    try:
        report = win._publish_to_terminal_report("echo t3-fail", snap)
    finally:
        signal_bus.paste_text_in_terminal.disconnect(sent_t1.append)
        signal_bus.paste_text_in_workspace_terminal.disconnect(sent_t2.append)

    assert sent_t1 == []
    assert sent_t2 == []
    assert report.accepted == ()
    assert report.failed == ("T3",)
    assert "t3_publish_failed" in report.errors


def test_publish_report_isolated_exception_partial(qtbot, monkeypatch):
    from workflow_app.main_window import TerminalRouteSnapshot

    win = _new_window(qtbot)
    snap = TerminalRouteSnapshot(t1=True, t2=True, t3=False)

    def _boom_t1(_text: str) -> None:
        raise RuntimeError("t1 transport down")

    # Patch thin T1 helper (SignalInstance.emit is read-only).
    monkeypatch.setattr(win, "_paste_text_to_t1", _boom_t1)

    sent_t2: list[str] = []
    signal_bus.paste_text_in_workspace_terminal.connect(sent_t2.append)
    try:
        report = win._publish_to_terminal_report("echo partial", snap)
    finally:
        signal_bus.paste_text_in_workspace_terminal.disconnect(sent_t2.append)

    assert "T1" in report.failed
    assert "T2" in report.accepted
    assert sent_t2 == ["echo partial"]
    assert report.requested == ("T1", "T2")


def test_publish_to_terminal_delegates_to_report(qtbot, monkeypatch):
    win = _new_window(qtbot)
    _set_route(win, t1=True, t2=False, t3=False)
    seen: list[tuple] = []

    def _fake_report(text, snapshot):
        seen.append((text, snapshot))
        from workflow_app.main_window import TerminalPublishReport

        return TerminalPublishReport(requested=("T1",), accepted=("T1",))

    monkeypatch.setattr(win, "_publish_to_terminal_report", _fake_report)
    win._publish_to_terminal("legacy-path")
    assert len(seen) == 1
    assert seen[0][0] == "legacy-path"
    assert seen[0][1].t1 is True


def test_create_agent_dialog_uses_open_snapshot_and_errors_without_route(
    qtbot, monkeypatch,
):
    """Open-time snapshot is used; no route keeps modal open with explicit error."""
    win = _new_window(qtbot)
    _set_route(win, t1=False, t2=False, t3=False)

    create_btn = _button_by_testid(win, "queue-btn-personas-create")
    create_btn.click()
    dlg = win._create_agent_dialog
    assert dlg is not None
    assert win._create_agent_route_snapshot.has_any_terminal_route() is False

    dlg.set_fields(name="Agente X", description="Descricao valida para teste")
    dlg._on_submit()
    # Failure path: modal stays open, controls restored.
    assert dlg.isVisible()
    assert "rota" in dlg.last_feedback.lower() or "terminal" in dlg.last_feedback.lower()
    assert dlg.in_flight is False


def test_create_agent_dialog_publishes_once_on_open_snapshot(qtbot, monkeypatch):
    win = _new_window(qtbot)
    _set_route(win, t1=True, t2=False, t3=False)

    create_btn = _button_by_testid(win, "queue-btn-personas-create")
    create_btn.click()
    dlg = win._create_agent_dialog
    assert dlg is not None

    # Flip routes after open — must not affect publish.
    _set_route(win, t1=False, t2=True, t3=False)

    sent_t1: list[str] = []
    sent_t2: list[str] = []
    signal_bus.paste_text_in_terminal.connect(sent_t1.append)
    signal_bus.paste_text_in_workspace_terminal.connect(sent_t2.append)
    try:
        dlg.set_fields(name="Agente Y", description="Descricao valida para teste")
        dlg._on_submit()
        qtbot.waitUntil(lambda: dlg.result() == 1 or not dlg.in_flight, timeout=3000)
    finally:
        signal_bus.paste_text_in_terminal.disconnect(sent_t1.append)
        signal_bus.paste_text_in_workspace_terminal.disconnect(sent_t2.append)

    assert len(sent_t1) == 1
    assert sent_t2 == []
    assert "PROMPT" in sent_t1[0].upper() or "agent-request-json" in sent_t1[0]
    # Enter must never be implied: only paste signal, never run_command.
    assert "Agente criado" not in dlg.last_feedback


def test_xterm_inject_text_starts_collapsed_t3_before_send(monkeypatch):
    """Parallel Worker Codex can target T3 while the xterm panel is collapsed."""
    from workflow_app import main_window as main_window_module

    class FakeShell:
        def __init__(self):
            self._master_fd = None
            self.sent: list[bytes] = []

        def send_raw(self, data: bytes):
            self.sent.append(data)

    shell = FakeShell()

    class FakePanel:
        _shell = shell

        def ensure_shell_started(self):
            shell._master_fd = 123

    fake_window = SimpleNamespace(_workspace_panel_xterm=FakePanel())

    ok = main_window_module.MainWindow._xterm_inject_text(
        fake_window,
        "echo t3",
        with_enter=False,
    )

    assert ok is True
    assert shell.sent == [b"echo t3"]


def test_xterm_inject_text_schedules_enter_after_one_second(monkeypatch):
    """Codex worker sends prompt first, then Enter after the paste has landed."""
    from workflow_app import main_window as main_window_module

    class FakeShell:
        def __init__(self):
            self._master_fd = 123
            self.sent: list[bytes] = []

        def send_raw(self, data: bytes):
            self.sent.append(data)

    shell = FakeShell()

    class FakePanel:
        _shell = shell

        def ensure_shell_started(self):
            pass

    delays: list[int] = []
    callbacks = []

    def _single_shot(delay_ms, callback):
        delays.append(delay_ms)
        callbacks.append(callback)

    fake_window = SimpleNamespace(_workspace_panel_xterm=FakePanel())
    monkeypatch.setattr(
        main_window_module.QTimer,
        "singleShot",
        _single_shot,
    )

    ok = main_window_module.MainWindow._xterm_inject_text(
        fake_window,
        "echo t3",
        with_enter=True,
    )

    assert ok is True
    assert shell.sent == [b"echo t3"]
    assert delays == [1000]

    callbacks[0]()

    assert shell.sent == [b"echo t3", b"\r"]
