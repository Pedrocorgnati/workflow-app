"""Main LLM MiMo (T1): `queue-btn-play-next` e a seta verde publicam o executor
nativo `/slash-executor --delegation-runtime=mimo /<cmd> ` (um espaco no fim),
conforme ai-forge/rules/mimo-code-cli-contract.md. Antes deste fix nao havia
branch `mimo` no eixo Main-LLM: o slash ia cru, no formato do Claude.
"""
from __future__ import annotations

import pytest

from workflow_app.command_queue.command_queue_widget import CommandQueueWidget
from workflow_app.domain import CommandSpec, EffortLevel, ModelName
from workflow_app.signal_bus import signal_bus


@pytest.fixture()
def widget(qapp, qtbot, monkeypatch) -> CommandQueueWidget:
    w = CommandQueueWidget()
    qtbot.addWidget(w)
    w.show()
    # O radio mimo fica atras do switch do roster MiMo; o teste liga direto.
    w._main_radio_visible["mimo"] = True
    w._main_mimo_radio.setChecked(True)
    # O preflight de CLI/credencial depende do host; nao e o alvo aqui.
    monkeypatch.setattr(w, "_orch_preflight_main_credential", lambda *_a, **_k: None)
    return w


def _capture(fn):
    emitted: list[str] = []
    signal_bus.run_command_in_terminal.connect(emitted.append)
    try:
        result = fn()
    finally:
        signal_bus.run_command_in_terminal.disconnect(emitted.append)
    return result, emitted


def test_builder_payload_matches_cli_contract():
    b = CommandQueueWidget._build_mimo_slash_executor_invocation
    assert b("/qa:trace --module 3") == (
        "/slash-executor --delegation-runtime=mimo /qa:trace --module 3 "
    )
    assert b("/skill:slash-executor /daily") == (
        "/slash-executor --delegation-runtime=mimo /daily "
    )
    assert b("/tools:listener-recovery --channel interactive", recovery_mode=True) == (
        "/slash-executor --delegation-runtime=mimo --recovery-mode "
        "/tools:listener-recovery --channel interactive "
    )
    assert b("texto livre") == "texto livre"


def test_main_llm_resolves_to_mimo(widget):
    assert widget._resolve_interactive_main_llm() == "mimo"


def test_play_next_sends_slash_executor(widget):
    widget.load_pipeline(
        [CommandSpec("/prd-create", ModelName.OPUS, EffortLevel.HIGH, position=1)]
    )
    _, emitted = _capture(widget._on_step_btn_clicked)
    assert emitted == ["/slash-executor --delegation-runtime=mimo /prd-create "]


def test_play_next_clear_goes_raw_without_space(widget):
    widget.load_pipeline([CommandSpec("/clear", ModelName.SONNET, position=1)])
    _, emitted = _capture(widget._on_step_btn_clicked)
    assert emitted == ["/clear"]


def test_model_directive_pulses_without_sending(widget):
    pulsed: list[str] = []
    signal_bus.listener_helper_pulse.connect(pulsed.append)
    try:
        ok, emitted = _capture(lambda: widget._dispatch_mimo_main_command("/model opus"))
    finally:
        signal_bus.listener_helper_pulse.disconnect(pulsed.append)
    assert ok is True
    assert emitted == []
    assert "interactive" in pulsed


def test_green_arrow_sends_slash_executor(widget):
    ok, emitted = _capture(lambda: widget._dispatch_green_arrow("/qa:trace --module 3"))
    assert ok is True
    assert emitted == ["/slash-executor --delegation-runtime=mimo /qa:trace --module 3 "]


def test_missing_command_aborts_with_toast(widget):
    toasts: list[str] = []
    handler = lambda m, _k: toasts.append(m)  # noqa: E731
    signal_bus.toast_requested.connect(handler)
    try:
        ok, emitted = _capture(
            lambda: widget._dispatch_mimo_main_command("/comando-que-nao-existe-xyz")
        )
    finally:
        signal_bus.toast_requested.disconnect(handler)
    assert ok is False
    assert emitted == []
    assert any("MiMo" in t for t in toasts)


# ─────────────────────── Task 010 (ST002): casos T1..T8 ───────────────────────
# Dispatch MiMo Main: ordem publish -> run, rotas, aborts sem efeito, recovery
# interativo, `/clear` da seta verde e insercao no T1. Sem PTY real; rotas e
# ordem observadas por monkeypatch de `_publish_to_terminal`/`_on_run_command`.


def _ins_watch(widget, monkeypatch) -> list[tuple[str, tuple, dict]]:
    """Registra chamadas a `_publish_to_terminal`/`_on_run_command` da instancia.

    Guarda os bound methods originais antes do setattr; os wrappers registram
    (nome, args, kwargs) e continuam chamando o original (a emissao vale)."""
    calls: list[tuple[str, tuple, dict]] = []
    orig_publish = widget._publish_to_terminal
    orig_run = widget._on_run_command

    def _publish(*args, **kwargs):
        calls.append(("publish", args, kwargs))
        return orig_publish(*args, **kwargs)

    def _run(*args, **kwargs):
        calls.append(("run", args, kwargs))
        return orig_run(*args, **kwargs)

    monkeypatch.setattr(widget, "_publish_to_terminal", _publish)
    monkeypatch.setattr(widget, "_on_run_command", _run)
    return calls


def _ins_publishes(calls):
    """Somente as entradas de `_publish_to_terminal` (o run nao tem route)."""
    return [c for c in calls if c[0] == "publish"]


def _ins_capture(signal):
    """Coleta os args de cada emissao de `signal`; devolve (lista, slot)."""
    out: list[tuple] = []
    slot = lambda *args: out.append(args)  # noqa: E731
    signal.connect(slot)
    return out, slot


def _ins_new_window(qtbot):
    from workflow_app.main_window import MainWindow

    win = MainWindow()
    qtbot.addWidget(win)
    return win


def _ins_set_route(win, *, t1, t2, t3):
    radios = (win._chk_route_t1, win._chk_route_t2, win._chk_route_t3)
    states = (t1, t2, t3)
    if sum(states) == 1:
        radios[states.index(True)].setChecked(True)
        return
    win._terminal_route_group.setExclusive(False)
    for radio, checked in zip(radios, states, strict=True):
        radio.setChecked(checked)
    win._terminal_route_group.setExclusive(True)


@pytest.fixture()
def ctx_file(tmp_path):
    """Snapshot diagnostico valido (existe em disco + termina em .md)."""
    p = tmp_path / "interactive-BLOCKED-snapshot.md"
    p.write_text("# recovery snapshot\n", encoding="utf-8")
    return str(p)


def test_t1_prompt_is_pasted_raw_with_prompt_route(widget, monkeypatch):
    """Prompt livre (is_prompt=True) vai cru para o T1 na rota mimo-main-prompt."""
    calls = _ins_watch(widget, monkeypatch)
    ok, emitted = _capture(
        lambda: widget._dispatch_mimo_main_command(
            "texto livre do operador", is_prompt=True
        )
    )
    assert ok is True
    assert emitted == ["texto livre do operador"]
    publishes = _ins_publishes(calls)
    assert len(publishes) == 1
    assert publishes[0][1] == ("interactive",)
    assert publishes[0][2]["route"] == "mimo-main-prompt"
    assert publishes[0][2]["text"] == "texto livre do operador"


def test_t2_missing_custom_prompt_aborts_with_warning(widget, monkeypatch):
    """Custom-prompt 'goal' sem arquivo em ai-forge/custom-prompts aborta."""
    monkeypatch.setattr(widget, "_resolve_custom_prompt_file", lambda _s: None)
    calls = _ins_watch(widget, monkeypatch)
    toasts, toast_slot = _ins_capture(signal_bus.toast_requested)
    try:
        ok, emitted = _capture(lambda: widget._dispatch_mimo_main_command("/goal"))
    finally:
        signal_bus.toast_requested.disconnect(toast_slot)
    assert ok is False
    assert emitted == []
    assert calls == []
    assert len(toasts) == 1
    message, kind = toasts[0]
    assert kind == "warning"
    assert "custom-prompt 'goal'" in message


@pytest.mark.parametrize(
    ("cmd", "toast_fragment"),
    [
        ("/comando-que-nao-existe-xyz", "comando/skill"),
        ("/qa:trace !`printf X`", "!`"),
    ],
)
def test_t3_aborted_dispatch_touches_neither_publish_nor_run(
    widget, monkeypatch, cmd, toast_fragment
):
    """Dispatch abortado nao publica nem roda: o toast identifica o ramo."""
    calls = _ins_watch(widget, monkeypatch)
    toasts, toast_slot = _ins_capture(signal_bus.toast_requested)
    try:
        ok, emitted = _capture(lambda: widget._dispatch_mimo_main_command(cmd))
    finally:
        signal_bus.toast_requested.disconnect(toast_slot)
    assert ok is False
    assert emitted == []
    assert calls == []
    assert len(toasts) == 1
    message, kind = toasts[0]
    assert kind == "warning"
    assert toast_fragment in message


def test_t4_each_dispatch_publishes_before_run_with_route(widget, monkeypatch):
    """As tres entradas publicam primeiro e so entao rodam (ordem publish, run)."""
    calls = _ins_watch(widget, monkeypatch)

    ok, emitted = _capture(
        lambda: widget._dispatch_mimo_main_command("/qa:trace --module 3")
    )
    first = list(calls)
    calls.clear()

    ok_clear, emitted_clear = _capture(
        lambda: widget._dispatch_mimo_main_command("/clear")
    )
    second = list(calls)
    calls.clear()

    ok_prompt, emitted_prompt = _capture(
        lambda: widget._dispatch_mimo_main_command(
            "texto livre do operador", is_prompt=True
        )
    )
    third = list(calls)

    assert (ok, ok_clear, ok_prompt) == (True, True, True)
    assert emitted == [
        "/slash-executor --delegation-runtime=mimo /qa:trace --module 3 "
    ]
    assert emitted_clear == ["/clear"]
    assert emitted_prompt == ["texto livre do operador"]
    batches = (
        (first, "mimo-main"),
        (second, "mimo-main"),
        (third, "mimo-main-prompt"),
    )
    for batch, route in batches:
        assert [name for name, _args, _kwargs in batch] == ["publish", "run"]
        assert [c[2]["route"] for c in _ins_publishes(batch)] == [route]


def test_t5_recovery_interactive_dispatches_mimo_payload(
    widget, ctx_file, monkeypatch
):
    """Recovery interativo sob Main MiMo cola o payload nativo com --recovery-mode."""
    calls = _ins_watch(widget, monkeypatch)
    failed, failed_slot = _ins_capture(signal_bus.terminal_force_failed)
    try:
        _, emitted = _capture(
            lambda: widget._on_request_recovery_command(
                "interactive", "EXIT_NONZERO", ctx_file
            )
        )
    finally:
        signal_bus.terminal_force_failed.disconnect(failed_slot)
    expected = (
        "/slash-executor --delegation-runtime=mimo --recovery-mode "
        "/tools:listener-recovery --channel interactive --reason EXIT_NONZERO "
        f"--context-file {ctx_file} "
    )
    assert emitted == [expected]
    assert "/skill:slash-executor" not in emitted[0]
    assert [name for name, _args, _kwargs in calls] == ["publish"]
    assert calls[0][1] == ("interactive",)
    assert calls[0][2]["route"] == "listener-recovery"
    assert calls[0][2]["text"] == expected
    assert failed == []


def test_t6_recovery_builder_refusal_blocks_channel(widget, ctx_file, monkeypatch):
    """Builder recusado (ValueError) aborta o recovery: BLOCKED e nada publicado."""
    monkeypatch.setattr(
        CommandQueueWidget,
        "_build_mimo_slash_executor_invocation",
        classmethod(lambda cls, *_a, **_k: (_ for _ in ()).throw(ValueError("recusado"))),
    )
    calls = _ins_watch(widget, monkeypatch)
    failed, failed_slot = _ins_capture(signal_bus.terminal_force_failed)
    toasts, toast_slot = _ins_capture(signal_bus.toast_requested)
    try:
        _, emitted = _capture(
            lambda: widget._on_request_recovery_command(
                "interactive", "EXIT_NONZERO", ctx_file
            )
        )
    finally:
        signal_bus.terminal_force_failed.disconnect(failed_slot)
        signal_bus.toast_requested.disconnect(toast_slot)
    assert emitted == []
    assert calls == []
    assert failed == [("interactive", "BLOCKED")]
    assert len(toasts) == 1
    message, kind = toasts[0]
    assert kind == "warning"
    assert message.startswith("Auto-recuperacao abortada")


def test_t7_green_arrow_clear_is_raw_and_unmirrored(widget, monkeypatch):
    """`/clear` da seta verde vai cru para o T1 e nao espelha nada nos workers."""
    for name in (
        "_use_kimi_chk",
        "_use_qwen_chk",
        "_use_mimo_chk",
        "_use_codex_chk",
        "_use_grok_chk",
    ):
        chk = getattr(widget, name, None)
        if chk is not None:
            chk.setChecked(False)
    calls = _ins_watch(widget, monkeypatch)
    ws, ws_slot = _ins_capture(signal_bus.run_command_in_workspace_terminal)
    try:
        ok, emitted = _capture(lambda: widget._dispatch_green_arrow("/clear"))
    finally:
        signal_bus.run_command_in_workspace_terminal.disconnect(ws_slot)
    assert ok is True
    assert emitted == ["/clear"]
    assert ws == []
    assert all("/slash-executor" not in t for t in emitted)
    publishes = _ins_publishes(calls)
    assert len(publishes) == 1
    assert publishes[0][1] == ("interactive",)
    assert publishes[0][2]["route"] == "green-arrow/clear"
    assert publishes[0][2]["text"] == "/clear"


def test_t8_insertion_t1_pastes_mimo_executor_payload(qapp, qtbot, monkeypatch):
    """Insercao roteada para o T1 sob Main MiMo cola o executor nativo com espaco final."""
    win = _ins_new_window(qtbot)
    _ins_set_route(win, t1=True, t2=False, t3=False)
    monkeypatch.setattr(win._command_queue, "current_main_llm", lambda: "mimo")
    pastes, paste_slot = _ins_capture(signal_bus.paste_text_in_terminal)
    try:
        report = win._publish_insertion_llm_aware_report("/corgly:class-review")
    finally:
        signal_bus.paste_text_in_terminal.disconnect(paste_slot)
        win._modal_check_timer.stop()
    assert report.accepted == ("T1",)
    assert len(pastes) == 1
    assert pastes[0][0] == (
        "/slash-executor --delegation-runtime=mimo /corgly:class-review "
    )
