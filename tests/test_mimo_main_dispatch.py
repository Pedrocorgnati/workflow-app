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
