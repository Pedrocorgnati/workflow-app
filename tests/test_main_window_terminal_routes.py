"""Regression tests for terminal-route-toggles routing in MainWindow."""

from __future__ import annotations

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


def test_terminal_route_toggles_exist(qtbot):
    win = _new_window(qtbot)

    assert win._chk_route_t1.property("testid") == "terminal-route-t1"
    assert win._chk_route_t2.property("testid") == "terminal-route-t2"
    assert win._chk_route_t3.property("testid") == "terminal-route-t3"


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
