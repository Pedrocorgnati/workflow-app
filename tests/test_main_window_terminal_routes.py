"""Regression tests for terminal-route-toggles routing in MainWindow."""

from __future__ import annotations

from types import SimpleNamespace

from workflow_app.signal_bus import signal_bus


def _new_window(qtbot):
    from workflow_app.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    return win


def _set_route(win, *, t1: bool, t2: bool, t3: bool) -> None:
    win._chk_route_t1.setChecked(t1)
    win._chk_route_t2.setChecked(t2)
    win._chk_route_t3.setChecked(t3)


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


def test_mcp_toolbar_uses_provider_radio_and_three_actions(qtbot):
    win = _new_window(qtbot)

    assert _radio_by_testid(win, "output-mcp-provider-claude").text() == "Claude"
    assert _radio_by_testid(win, "output-mcp-provider-kimi").text() == "Kimi"
    assert _radio_by_testid(win, "output-mcp-provider-codex").text() == "Codex"

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
    # Refactor 2026-05-24: o radio de provider escolhe o COMANDO; o terminal e
    # decidido por terminal-route-toggles. Aqui T1 marcado -> comando vai a T1.
    win = _new_window(qtbot)
    _set_route(win, t1=True, t2=False, t3=False)

    sent_t1: list[str] = []
    sent_t2: list[str] = []
    signal_bus.paste_text_in_terminal.connect(sent_t1.append)
    signal_bus.paste_text_in_workspace_terminal.connect(sent_t2.append)
    try:
        _radio_by_testid(win, "output-mcp-provider-claude").setChecked(True)
        _button_by_testid(win, "output-mcp-action-main").click()
    finally:
        signal_bus.paste_text_in_terminal.disconnect(sent_t1.append)
        signal_bus.paste_text_in_workspace_terminal.disconnect(sent_t2.append)

    assert sent_t1 == ["/mcp:codex"]
    assert sent_t2 == []


def test_mcp_toolbar_provider_does_not_force_terminal_when_no_toggle(qtbot):
    # Sem nenhum toggle marcado, a acao MCP e no-op (provider nao força mais
    # terminal). Garante que a função de roteamento saiu do radio.
    win = _new_window(qtbot)
    _set_route(win, t1=False, t2=False, t3=False)

    sent_t1: list[str] = []
    sent_t2: list[str] = []
    signal_bus.paste_text_in_terminal.connect(sent_t1.append)
    signal_bus.paste_text_in_workspace_terminal.connect(sent_t2.append)
    try:
        _radio_by_testid(win, "output-mcp-provider-claude").setChecked(True)
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
        _radio_by_testid(win, "output-mcp-provider-claude").setChecked(True)
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
        _radio_by_testid(win, "output-mcp-provider-claude").setChecked(True)
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


def test_mcp_toolbar_fourth_persona_row_has_exact_paths_and_order(qtbot):
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
    assert row.property("testid") == "output-mcp-persona-checkboxes-4"
    row_checkboxes = row.findChildren(type(_checkbox_by_testid(win, expected[0][0])))
    assert len(row_checkboxes) == 4
    assert [checkbox.property("testid") for checkbox in row_checkboxes] == [
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
        _radio_by_testid(win, "output-mcp-provider-claude").setChecked(True)
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
        _radio_by_testid(win, "output-mcp-provider-kimi").setChecked(True)
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

    _radio_by_testid(win, "output-mcp-provider-codex").setChecked(True)
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

    _radio_by_testid(win, "output-mcp-provider-codex").setChecked(True)
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
