"""Integrated create-agent flow: button -> dialog -> builder -> dispatcher.

AGENT-TASK-009. Covers the end-to-end wiring in MainWindow that the unit
suites cannot see: single modal instance per click, single publish per submit,
no Enter, retry after total failure, observable partial success and the
teardown of sensitive data / connections / references.
"""

from __future__ import annotations

import pytest

from workflow_app.signal_bus import signal_bus

_NAME = "Agente Focal"
_DESC = "Descricao valida para o fluxo integrado de criacao."


def _new_window(qtbot):
    from workflow_app.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    return win


def _set_route(win, *, t1: bool, t2: bool, t3: bool) -> None:
    win._chk_route_t1.setChecked(t1)
    win._chk_route_t2.setChecked(t2)
    win._chk_route_t3.setChecked(t3)


def _create_button(win):
    from PySide6.QtWidgets import QPushButton

    for btn in win.findChildren(QPushButton):
        if btn.property("testid") == "queue-btn-personas-create":
            return btn
    raise AssertionError("botao nao encontrado: queue-btn-personas-create")


class _Capture:
    """Collects paste/run/toast traffic around one publish."""

    def __init__(self) -> None:
        self.paste_t1: list[str] = []
        self.paste_t2: list[str] = []
        # run_* carry text + Enter. T1 and T2 have distinct signals, so the
        # no-Enter proof for a T1 publish must observe run_t1, not run_t2.
        self.run_t1: list[str] = []
        self.run_t2: list[str] = []
        self.toasts: list[tuple[str, str]] = []

    def _toast(self, message: str, kind: str) -> None:
        self.toasts.append((message, kind))

    def __enter__(self) -> _Capture:
        signal_bus.paste_text_in_terminal.connect(self.paste_t1.append)
        signal_bus.paste_text_in_workspace_terminal.connect(self.paste_t2.append)
        signal_bus.run_command_in_terminal.connect(self.run_t1.append)
        signal_bus.run_command_in_workspace_terminal.connect(self.run_t2.append)
        signal_bus.toast_requested.connect(self._toast)
        return self

    def __exit__(self, *_exc: object) -> None:
        signal_bus.paste_text_in_terminal.disconnect(self.paste_t1.append)
        signal_bus.paste_text_in_workspace_terminal.disconnect(self.paste_t2.append)
        signal_bus.run_command_in_terminal.disconnect(self.run_t1.append)
        signal_bus.run_command_in_workspace_terminal.disconnect(self.run_t2.append)
        signal_bus.toast_requested.disconnect(self._toast)


def _open_dialog(win):
    _create_button(win).click()
    dlg = win._create_agent_dialog
    assert dlg is not None
    return dlg


def _submit(dlg, *, name: str = _NAME, description: str = _DESC) -> None:
    dlg.set_fields(name=name, description=description)
    dlg._on_submit()


# ── Single instance / single publish ─────────────────────────────────────────


def test_second_click_reuses_the_same_modal_instance(qtbot):
    from workflow_app.widgets.create_agent_dialog import CreateAgentDialog

    win = _new_window(qtbot)
    _set_route(win, t1=True, t2=False, t3=False)

    btn = _create_button(win)
    btn.click()
    first = win._create_agent_dialog
    btn.click()

    assert win._create_agent_dialog is first
    assert len(win.findChildren(CreateAgentDialog)) == 1


def test_one_submit_publishes_exactly_once_without_enter(qtbot):
    win = _new_window(qtbot)
    _set_route(win, t1=True, t2=False, t3=False)
    dlg = _open_dialog(win)

    with _Capture() as cap:
        _submit(dlg)

    assert len(cap.paste_t1) == 1
    assert cap.paste_t2 == []
    # Enter is never sent: the run_command signals (paste + Enter) stay silent.
    # run_t1 is the one that would actually fire on this route.
    assert cap.run_t1 == []
    assert cap.run_t2 == []
    assert _NAME in cap.paste_t1[0]


def test_replayed_submit_signal_never_republishes(qtbot):
    """A re-emitted submit_requested (stale modal) must not publish twice."""
    win = _new_window(qtbot)
    _set_route(win, t1=True, t2=False, t3=False)
    dlg = _open_dialog(win)

    dlg.set_fields(name=_NAME, description=_DESC)
    request = None

    def _grab(req) -> None:
        nonlocal request
        request = req

    dlg.submit_requested.connect(_grab)
    with _Capture() as cap:
        dlg._on_submit()
        assert request is not None
        # Replay the very same request against the still-connected handler.
        dlg.submit_requested.emit(request)

    assert len(cap.paste_t1) == 1


def test_post_paste_failure_never_republishes(qtbot, monkeypatch):
    """A failure AFTER the paste must not be classified as "nothing happened".

    Regression for the focus step: it runs once the prompt is already in the
    terminal. If it raised out of the dispatcher, the host released the publish
    guard and an explicit retry pasted the very same prompt a second time,
    breaking "um submit publica uma vez".
    """
    win = _new_window(qtbot)
    _set_route(win, t1=False, t2=True, t3=False)
    dlg = _open_dialog(win)

    def _boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("wrapped C/C++ object of type TerminalCanvas has been deleted")

    monkeypatch.setattr(win._workspace_panel._terminal, "setFocus", _boom)

    dlg.set_fields(name=_NAME, description=_DESC)
    request = None

    def _grab(req) -> None:
        nonlocal request
        request = req

    dlg.submit_requested.connect(_grab)

    with _Capture() as cap:
        dlg._on_submit()
        assert len(cap.paste_t2) == 1, "o paste deve ocorrer antes da falha de foco"
        assert request is not None
        # An operator retry against the same handler must find the guard held.
        dlg.submit_requested.emit(request)

    assert len(cap.paste_t2) == 1
    # The publish succeeded: focus is cosmetic, not a dispatch failure.
    assert dlg.result() == 1
    assert dlg.torn_down is True
    assert win._create_agent_dialog is None


def test_publish_targets_only_the_open_time_route(qtbot):
    win = _new_window(qtbot)
    _set_route(win, t1=True, t2=False, t3=False)
    dlg = _open_dialog(win)

    # Operator flips the toggles while the modal is open.
    _set_route(win, t1=False, t2=True, t3=False)

    with _Capture() as cap:
        _submit(dlg)

    assert len(cap.paste_t1) == 1
    assert cap.paste_t2 == []


def test_t3_route_is_injected_without_enter(qtbot, monkeypatch):
    from workflow_app.main_window import MainWindow

    win = _new_window(qtbot)
    _set_route(win, t1=False, t2=False, t3=True)
    dlg = _open_dialog(win)

    calls: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        MainWindow,
        "_xterm_inject_text",
        lambda self, text, with_enter=True: (
            calls.append((text, with_enter)) or True
        ),
    )

    with _Capture() as cap:
        _submit(dlg)

    assert len(calls) == 1
    assert calls[0][1] is False
    assert cap.run_t2 == []


# ── Teardown ─────────────────────────────────────────────────────────────────


def test_success_tears_down_data_connections_and_references(qtbot):
    win = _new_window(qtbot)
    _set_route(win, t1=True, t2=False, t3=False)
    dlg = _open_dialog(win)

    with _Capture():
        _submit(dlg)

    assert dlg.result() == 1
    assert dlg.torn_down is True
    assert dlg.has_sensitive_data() is False
    assert dlg.name_text() == ""
    assert dlg.description_text() == ""
    assert dlg.last_request is None
    assert win._create_agent_dialog is None
    assert win._create_agent_route_snapshot is None


def test_cancel_tears_down_without_publishing(qtbot):
    win = _new_window(qtbot)
    _set_route(win, t1=True, t2=False, t3=False)
    dlg = _open_dialog(win)
    dlg.set_fields(name=_NAME, description=_DESC)

    with _Capture() as cap:
        dlg._on_cancel()

    assert cap.paste_t1 == []
    assert dlg.torn_down is True
    assert dlg.has_sensitive_data() is False
    assert win._create_agent_dialog is None
    assert win._create_agent_route_snapshot is None


def test_close_restores_focus_to_the_create_button(qtbot):
    win = _new_window(qtbot)
    _set_route(win, t1=True, t2=False, t3=False)
    dlg = _open_dialog(win)

    dlg._on_cancel()

    assert win.focusWidget() is _create_button(win)


def test_reopen_after_close_builds_a_fresh_instance_and_snapshot(qtbot):
    win = _new_window(qtbot)
    _set_route(win, t1=True, t2=False, t3=False)
    first = _open_dialog(win)
    first._on_cancel()

    _set_route(win, t1=False, t2=True, t3=False)
    second = _open_dialog(win)

    assert second is not first
    assert win._create_agent_route_snapshot.t1 is False
    assert win._create_agent_route_snapshot.t2 is True

    with _Capture() as cap:
        _submit(second)

    assert cap.paste_t1 == []
    assert len(cap.paste_t2) == 1


def test_stale_teardown_does_not_drop_the_current_dialog(qtbot):
    """A late `finished` from a previous modal must not clear the live one."""
    win = _new_window(qtbot)
    _set_route(win, t1=True, t2=False, t3=False)
    stale = _open_dialog(win)
    stale._on_cancel()
    current = _open_dialog(win)

    win._teardown_create_agent_dialog(stale)

    assert win._create_agent_dialog is current
    assert win._create_agent_route_snapshot is not None


# ── Failure / retry ──────────────────────────────────────────────────────────


def test_total_failure_keeps_modal_data_and_allows_retry(qtbot, monkeypatch):
    from workflow_app.main_window import MainWindow

    win = _new_window(qtbot)
    _set_route(win, t1=True, t2=False, t3=False)
    dlg = _open_dialog(win)

    def _boom(self, text: str) -> None:
        raise RuntimeError("sink indisponivel")

    monkeypatch.setattr(MainWindow, "_paste_text_to_t1", _boom)

    with _Capture() as cap:
        _submit(dlg)

    assert cap.paste_t1 == []
    assert dlg.isVisible()
    assert dlg.torn_down is False
    assert dlg.in_flight is False
    # Operator data survives for the retry.
    assert dlg.name_text() == _NAME
    assert dlg.description_text() == _DESC
    assert "sink indisponivel" not in dlg.last_feedback

    monkeypatch.undo()

    with _Capture() as cap:
        dlg._on_submit()

    assert len(cap.paste_t1) == 1
    assert dlg.torn_down is True


def test_no_route_reports_error_and_never_publishes(qtbot):
    win = _new_window(qtbot)
    _set_route(win, t1=False, t2=False, t3=False)
    dlg = _open_dialog(win)

    with _Capture() as cap:
        _submit(dlg)

    assert cap.paste_t1 == []
    assert cap.paste_t2 == []
    assert dlg.isVisible()
    assert dlg.torn_down is False
    assert dlg.name_text() == _NAME


# ── Observable feedback ──────────────────────────────────────────────────────


@pytest.mark.parametrize("forbidden", ["agente criado", "agente foi criado"])
def test_success_toast_never_claims_the_agent_was_created(qtbot, forbidden):
    win = _new_window(qtbot)
    _set_route(win, t1=True, t2=False, t3=False)
    dlg = _open_dialog(win)

    with _Capture() as cap:
        _submit(dlg)

    published = [t for t in cap.toasts if "publicado" in t[0].lower()]
    assert published, cap.toasts
    message, kind = published[0]
    assert kind == "info"
    assert "T1" in message
    assert forbidden not in message.lower()
    assert _DESC not in message


def test_partial_success_emits_warning_toast_and_closes(qtbot, monkeypatch):
    from workflow_app.main_window import MainWindow

    win = _new_window(qtbot)
    _set_route(win, t1=True, t2=False, t3=True)
    dlg = _open_dialog(win)

    # T1 accepts, T3 sink refuses: partial acceptance, no silent fallback.
    monkeypatch.setattr(
        MainWindow,
        "_xterm_inject_text",
        lambda self, text, with_enter=True: False,
    )

    with _Capture() as cap:
        _submit(dlg)

    assert len(cap.paste_t1) == 1
    assert cap.paste_t2 == []
    warnings = [t for t in cap.toasts if t[1] == "warning"]
    assert warnings, cap.toasts
    message = warnings[0][0]
    assert "T1" in message and "T3" in message
    assert "criado" not in message.lower() or "Nenhum agente foi criado" in message
    assert dlg.result() == 1
    assert dlg.torn_down is True
    assert dlg.has_sensitive_data() is False
